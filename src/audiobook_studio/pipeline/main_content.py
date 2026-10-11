"""Main-content trimming: keep only the story body from extracted book text.

Books extracted via OCR / text layer usually carry non-story matter:
- front matter (title page, author bio, publisher/copyright/ISBN page,
  acknowledgements, table of contents, "before reading" preliminaries);
- inline matter (graded-reader activity/exercise sections between chapters,
  vocabulary glosses, reading checks, page numbers, running heads);
- back matter (end-of-book quizzes/activities, publisher promotion pages,
  CEFR/exam mapping tables, back-cover blurb).

This module trims those parts deterministically (heuristics) and can
optionally refine the story boundaries with an LLM-provided boundary
function. On any LLM failure it degrades honestly to the heuristic result
(or the original text) and logs — it never returns empty text or fabricates
a "cleaned" result.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = ["MainContentResult", "extract_main_content", "split_blocks"]

# ── Env switches ─────────────────────────────────────────────────────────────
# MAIN_CONTENT_FILTER_ENABLED (default on) gates the whole trimming step.
# MAIN_CONTENT_LLM_REFINE (default off) enables optional LLM boundary refine.


def filter_enabled() -> bool:
    return os.environ.get("MAIN_CONTENT_FILTER_ENABLED", "true").lower() in ("1", "true", "yes", "on")


def llm_refine_enabled() -> bool:
    return os.environ.get("MAIN_CONTENT_LLM_REFINE", "false").lower() in ("1", "true", "yes", "on")


@dataclass
class MainContentResult:
    """Outcome of main-content trimming."""

    text: str
    removed_blocks: List[str] = field(default_factory=list)
    method: str = "passthrough"  # "heuristic" | "heuristic+llm" | "passthrough"
    degraded: bool = False


# ── Block splitting ──────────────────────────────────────────────────────────


def split_blocks(text: str) -> List[str]:
    """Split text into paragraph blocks on blank lines (keeps order)."""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p and p.strip()]


# ── Heuristic signals ────────────────────────────────────────────────────────

_FRONT_MATTER_RE = re.compile(
    r"(?i)(university press|publisher|\bisbn\b|\bcopyright\b|all rights reserved"
    r"|first published|acknowledgements?|registered trade\s*mark|moral rights"
    r"|reproduced,?\s+modified|no copying|file sharing|retrieval system)",
)

# © alone is NOT a front-matter signal: Chinese books' OCR often turns the
# bullet ● into ©, so body paragraphs can contain it. Require co-occurrence
# with a genuine copyright/ISBN/publisher keyword within the same block.
_COPYRIGHT_SYMBOL_RE = re.compile(
    r"(?is)(©.{0,120}(copyright|all\s+rights|isbn|出版|press|出版社)"
    r"|(copyright|all\s+rights|isbn|出版|press|出版社).{0,120}©)"
)


def _is_front_matter_text(text: str) -> bool:
    return bool(_FRONT_MATTER_RE.search(text) or _COPYRIGHT_SYMBOL_RE.search(text))


_PROMO_BACK_RE = re.compile(
    r"(?i)(read dominoes|if you liked this|word count|series editors"
    r"|www\.oup\.|oup\.com|oup\.cn|\bcefr\b|\bielts\b|\btoefl\b|\btoeic\b"
    r"|level headwords|dramatized audio|graded ?readers"
    r"|shaping learning together|structured\s+approach\s+to\s+reading)",
)

_ACTIVITY_RE = re.compile(
    r"(?i)(complete the (sentences?|interview|dialogue?|conversation|chart|table|crossword)"
    r"|match the (words|pictures|beginnings)|choose from"
    r"|tick the boxes|work in pairs|wordsearch|crossword|roleplay"
    r"|put the (sentences|pictures|events|notes|words).{0,40}order"
    r"|find (five|six|seven|eight|nine|ten|eleven|twelve|\d+) (more )?(new )?words"
    r"|what do you think|prepare (answers|questions)|answer these questions"
    r"|true or false|reading check|guess what|in the next chapter"
    r"|write a (short )?(report|summary)|use the notes"
    r"|^\s*(activities|activity\s+\d+|before reading|glossary|quiz|project)\b)",
    re.MULTILINE,
)

_CHAPTER_HEAD_RE = re.compile(r"(?i)^\s*(chapter|part|section)\b[\s\d\w]*$")

# Table-of-contents line: dot/cjk-dot/garbled leaders then a page number.
_TOC_LINE_RE = re.compile(r"([.·…•_]|\bc\b){4,}[\s\d]{1,5}$|\.\s*\.\s*\.\s*.*\d+\s*$")

# Checkbox / fill-in-the-blank noise characters from OCR, incl. garbled
# option markers ("a L]How people", "D) ssc...", "b LlAnimportant").
_NOISE_LINE_RE = re.compile(r"(\[.\]|☐|□|◯|\bL[\]\)JIl]\w*|_{5,}|\.{6,}|[sewic]{8,}|^\s*[A-Za-z][\)\]]\s)")

_SENT_END = tuple(".!?\"'”’)]")

# OCR garbage token: triple-repeated lowercase letters ("laeeersceee") or a
# single lowercase run of 14+ chars ("ounoecuresne") — essentially never real
# words in these graded readers.
_GARBAGE_TOKEN_RE = re.compile(r"\b[a-z]*([a-z])\1{2,}[a-z]*\b|\b[a-z]{14,}\b")


def _line_is_garbage(line: str) -> bool:
    """Conservative OCR-garbage line test: needs real token density plus at
    least one impossible token, so genuine prose never trips it."""
    tokens = re.findall(r"[A-Za-z]+", line)
    return len(tokens) >= 4 and bool(_GARBAGE_TOKEN_RE.search(line))


def _line_is_noise(line: str) -> bool:
    return bool(_NOISE_LINE_RE.search(line))


def _toc_hits(block: str) -> int:
    return sum(1 for ln in block.splitlines() if _TOC_LINE_RE.search(ln.strip()))


def is_noncontent_block(block: str, prev_non: bool = False, next_non: bool = False) -> bool:
    """Classify one block as non-story matter (True) or story content (False)."""
    text = block.strip()
    if not text:
        return True

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Page-number-only / tiny running-head blocks (incl. OCR'd CJK page marks).
    if len(lines) == 1 and (
        re.fullmatch(r"\d{1,4}", lines[0]) or (len(lines[0]) <= 2 and not re.search(r"[A-Za-z]", lines[0]))
    ):
        return True

    # Chapter headings are story structure — always keep.
    if _CHAPTER_HEAD_RE.match(text):
        return False

    # Strong front/back/promo signals.
    if _is_front_matter_text(text) or _PROMO_BACK_RE.search(text):
        return True

    # Activity/exercise instructions.
    if _ACTIVITY_RE.search(text):
        return True

    # "Contents" heading or a mostly-TOC block.
    if lines and re.fullmatch(r"(?i)contents", lines[0]):
        return True
    if lines and _toc_hits(text) / len(lines) >= 0.4 and _toc_hits(text) >= 2:
        return True

    # Blocks dominated by checkbox/fill-in noise lines (OCR'd worksheets).
    if lines and sum(1 for ln in lines if _line_is_noise(ln)) / len(lines) >= 0.5:
        return True

    # Multi-line blocks with no sentence punctuation anywhere (vocabulary
    # glosses, fragmented definition lists) are non-story matter. Story
    # paragraphs always contain sentence punctuation somewhere.
    if len(lines) >= 3 and not re.search(r"[.!?。！？]", text):
        return True

    # Note-style worksheet blocks: slash/plus-separated bullet fragments
    # ("4 penalty shootout / China miss / ...", "first + second half/ ...").
    note_marks = sum(ln.count("/") + ln.count(" + ") for ln in lines)
    if note_marks >= 2 and not re.search(r"[.!?。！？]$", text):
        return True

    # Worksheet option items and headlines.
    if lines:
        first = lines[0]
        # option item: "f C1 Tino plays ..." / "a 'Where do I put the ball?'"
        if re.match(r"^[a-z]\s+\S", first):
            return True
        # ALL-CAPS headline or running head ("BRAZILIAN HAT-TRICK WINS GAME!")
        letters = [c for c in text if c.isalpha()]
        if len(letters) >= 6 and sum(c.isupper() for c in letters) / len(letters) >= 0.85 and len(lines) == 1:
            return True
        # caps garble token ("SY)", "Cy)")
        if re.fullmatch(r"[A-Z]{1,4}\)?", first):
            return True
        # fill-in-the-blank dialogue ("looks c____ to me", "It's a c_____")
        if re.search(r"[A-Za-z]?_{3,}", text):
            return True

    # Numbered question lists ("1 What about the other players?") — worksheet
    # interview/comprehension questions. Story prose doesn't enumerate
    # question-lines.
    if len(lines) == 1 and re.match(r"^\s*\d+\s+\S.*\?\s*$", lines[0]):
        return True
    if len(lines) >= 2 and "?" in text:
        num_q = sum(1 for ln in lines if re.match(r"^\s*\d+\s+\S", ln))
        if num_q == len(lines):
            return True

    # Script-format worksheet dialogues ("I: Did he play…?", "TF: Yes…",
    # ": How does…"): colon-tagged turn lines dominate the block, or the
    # block itself opens with a speaker label. Story prose uses quotation
    # marks, not "Label:" turns.
    if len(lines) >= 2:
        label_lines = sum(1 for ln in lines if re.match(r"^\s*[A-Za-z' ]{0,15}[:：]\s*\S", ln))
        if label_lines / len(lines) >= 0.5:
            return True
        if re.match(r"^\s*[A-Za-z][A-Za-z' ]{0,15}[:：]\s*\S", lines[0]):
            return True
        # Speaker turn buried inside OCR garbage (interview activity whose
        # surrounding lines are illustration-misread junk).
        if label_lines >= 1 and any(_line_is_garbage(ln) for ln in lines):
            return True

    # List-like blocks: nearly every line starts a new item (capital/label),
    # with short average line length. Wrapped story prose continues lines
    # with lowercase words, so it stays well below these thresholds.
    if len(lines) >= 3:
        caps = sum(1 for ln in lines if re.match(r"^[A-Z0-9(\[‘'\"]", ln))
        avg_len = len(text) / len(lines)
        if caps / len(lines) >= 0.8 and avg_len < 45:
            return True

    # Single short fragment lines without sentence punctuation (vocabulary
    # glosses like "fans people who like football a lot") count only when
    # surrounded by other non-content blocks, so story fragments stay safe.
    if len(lines) <= 2 and len(text) < 60 and not text.rstrip().endswith(_SENT_END) and prev_non and next_non:
        return True

    return False


def classify_blocks(blocks: List[str]) -> List[bool]:
    """Return per-block non-content flags (multi-pass for neighbour context)."""
    flags = [is_noncontent_block(b) for b in blocks]
    # Second pass resolves short fragment blocks using neighbour flags.
    for i, b in enumerate(blocks):
        prev_non = flags[i - 1] if i > 0 else True
        next_non = flags[i + 1] if i + 1 < len(blocks) else True
        if not flags[i] and is_noncontent_block(b, prev_non=prev_non, next_non=next_non):
            flags[i] = True
    # Third pass: a maximal run of consecutive short (<63 chars) content
    # blocks enclosed by non-content blocks (or document edges) is worksheet
    # debris (fill-in lists, option rows) — story openings sit next to long
    # story paragraphs and survive.
    n = len(blocks)
    i = 0
    while i < n:
        if flags[i] or len(blocks[i]) >= 63:
            i += 1
            continue
        j = i
        while j < n and not flags[j] and len(blocks[j]) < 63:
            j += 1
        left_nc = i == 0 or flags[i - 1]
        right_nc = j >= n or flags[j]
        if left_nc and right_nc:
            for k in range(i, j):
                flags[k] = True
        i = j

    # Fourth pass: prose following a flagged ALL-CAPS headline is the model
    # answer/report belonging to that worksheet (e.g. "BRAZILIAN HAT-TRICK
    # WINS GAME!" followed by the sample report). Swallow content blocks
    # until the next flagged block.
    def _is_caps_headline(b: str) -> bool:
        blines = [ln.strip() for ln in b.strip().splitlines() if ln.strip()]
        if len(blines) != 1:
            return False
        letters = [c for c in blines[0] if c.isalpha()]
        return len(letters) >= 6 and all(c.isupper() for c in letters)

    i = 0
    while i < n:
        if flags[i] and _is_caps_headline(blocks[i]):
            j = i + 1
            while j < n and not flags[j]:
                flags[j] = True
                j += 1
            i = j
        else:
            i += 1

    # Fifth pass: an ordering-exercise instruction ("Put the sentences in the
    # correct order. Number them 1-10.") is followed by its sentence items —
    # short declarative lines that look like story prose. Swallow content
    # blocks until the next flagged block.
    i = 0
    while i < n:
        if flags[i] and _ORDER_EXERCISE_RE.search(blocks[i]):
            j = i + 1
            while j < n and not flags[j]:
                flags[j] = True
                j += 1
            i = j
        else:
            i += 1
    return flags


# ── Boundary detection ───────────────────────────────────────────────────────


def _story_run_mask(flags: List[bool]) -> List[bool]:
    """Mark content blocks that belong to a *run* of story paragraphs.

    A content block is part of the story when at least 2 of its 4 nearest
    neighbours (±1, ±2) are also content. This rejects isolated prose islands
    such as the author bio (surrounded by copyright pages) or the back-cover
    blurb (surrounded by activities/promo), while keeping dense chapter text.
    """
    n = len(flags)
    run = [False] * n
    for i in range(n):
        if flags[i]:
            continue
        neighbours = 0
        for d in (1, 2):
            if i - d >= 0 and not flags[i - d]:
                neighbours += 1
            if i + d < n and not flags[i + d]:
                neighbours += 1
        if neighbours >= 2:
            run[i] = True
    return run


_BEFORE_READING_RE = re.compile(r"(?im)^\s*before reading\s*$")

_ORDER_EXERCISE_RE = re.compile(r"(?i)(put the .{0,60}in the (correct )?order|number them [\d])")


def _is_strong_front(block: str) -> bool:
    """Unambiguous front-matter anchor: publisher/copyright page, contents
    page, or a before-reading preliminaries heading. Inter-chapter activity
    sections deliberately do NOT qualify — they occur throughout the book."""
    if _is_front_matter_text(block) or _BEFORE_READING_RE.search(block):
        return True
    first = block.strip().splitlines()[0].strip() if block.strip() else ""
    return bool(re.fullmatch(r"(?i)contents", first))


def _first_story_start(blocks: List[str], flags: List[bool], lo: int = 0) -> Optional[int]:
    """First block of real prose: content, >=60 chars, with a dense run of
    content blocks ahead. Then backtrack over short content blocks (e.g. the
    story's opening one-liner) that precede it."""
    n = len(blocks)
    for i in range(lo, n):
        if flags[i] or len(blocks[i]) < 60:
            continue
        density = sum(1 for k in range(i, min(i + 8, n)) if not flags[k])
        if density >= 3:
            j = i
            while j - 1 >= lo and not flags[j - 1] and not _is_strong_front(blocks[j - 1]):
                j -= 1
            return j
    return None


def find_main_range(blocks: List[str], flags: List[bool]) -> Tuple[int, int]:
    """Return (start, end) block indices spanning the story.

    - start: first dense-prose block, never before the last strong
      front-matter block inside the first 25% of the book (skips title page,
      author bio, copyright, contents, before-reading activities).
    - end: the first strong back-matter block (publisher promo, series blurb,
      CEFR/exam tables, back-cover colophon) inside the last 40%; falls back
      to the last dense-prose block when no back anchor exists.
    """
    n = len(blocks)
    if n == 0:
        return 0, 0

    front_limit = max(1, int(n * 0.25))
    front_anchor = -1
    for i in range(front_limit):
        if _is_strong_front(blocks[i]):
            front_anchor = i

    start = _first_story_start(blocks, flags, lo=front_anchor + 1)
    if start is None:
        return 0, n

    back_anchor = n
    for i in range(int(n * 0.60), n):
        if _PROMO_BACK_RE.search(blocks[i]) or _is_front_matter_text(blocks[i]):
            back_anchor = i
            break

    # Run-based end: last block of the story's MAIN run — requires a dense
    # content neighbourhood (≥10 of the previous 15 blocks), so small prose
    # islands (model report answers, back-cover blurbs) after the story can't
    # stretch the tail. Intersected with the promo anchor.
    run_end = n
    for i in range(n - 1, start, -1):
        if not flags[i] and len(blocks[i]) >= 60:
            density = sum(1 for k in range(max(start, i - 15), i) if not flags[k])
            if density >= 10:
                j = i
                while j + 1 < n and not flags[j + 1]:
                    j += 1
                run_end = j + 1
                break

    end = min(back_anchor, run_end)
    if end <= start:
        return 0, n
    return start, end


# ── LLM boundary refinement (optional) ──────────────────────────────────────

BoundaryFn = Callable[[str], Optional[Tuple[int, int]]]

_BOUNDARY_PROMPT = (
    "下面是 OCR 从一本书中提取的全文，包含书前的出版信息/目录/简介、书末的"
    "问答/练习/推广，以及夹在正文中的练习部分。请找出**故事正文**（主文）的起止。\n"
    '只输出一个 JSON 对象：{"start": "<正文第一句原文的前20个字>", '
    '"end": "<正文最后一句原文的后20个字>"}，不要输出任何其他内容。\n\n'
    "全文如下：\n{text}"
)


def make_llm_boundary_fn(router) -> BoundaryFn:
    """Build a BoundaryFn backed by an LLMRouter.

    The LLM is asked for the first/last story sentences; we map them back to
    char offsets. Any failure (exception, unparseable output, phrases not
    found) returns None so the caller degrades to pure heuristics.
    """

    def boundary(text: str) -> Optional[Tuple[int, int]]:
        import json

        prompt = _BOUNDARY_PROMPT.format(text=text[:60000])
        raw = router.call(prompt)
        if not raw:
            return None
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        obj = json.loads(m.group(0))
        start_phrase = str(obj.get("start", "")).strip()
        end_phrase = str(obj.get("end", "")).strip()
        if not start_phrase or not end_phrase:
            return None
        s = text.find(start_phrase)
        # search end phrase from the back half first
        e = text.rfind(end_phrase)
        if s < 0 or e < 0:
            return None
        e += len(end_phrase)
        if e <= s:
            return None
        return s, e

    return boundary


def _apply_llm_boundaries(
    text: str,
    llm_boundary_fn: Optional[BoundaryFn],
) -> Optional[str]:
    """Ask the LLM for story [start, end) char offsets; None on any failure."""
    if llm_boundary_fn is None:
        return None
    try:
        bounds = llm_boundary_fn(text)
    except Exception as e:  # noqa: BLE001 — honest degrade to heuristics
        logger.warning(f"[main-content] LLM boundary refinement failed: {e}; using heuristics only")
        return None
    if not bounds:
        return None
    s, e = bounds
    if not (0 <= s < e <= len(text)) or (e - s) < 200:
        logger.warning(f"[main-content] LLM returned implausible boundaries {bounds}; ignored")
        return None
    refined = text[s:e].strip()
    if not refined:
        return None
    return refined


# ── Public entry ─────────────────────────────────────────────────────────────

MIN_INPUT_CHARS = 1000  # shorter texts pass through untouched
MIN_KEEP_RATIO = 0.20  # never keep less than 20% of the original


def extract_main_content(
    text: str,
    llm_boundary_fn: Optional[BoundaryFn] = None,
    enabled: Optional[bool] = None,
) -> MainContentResult:
    """Trim non-story matter from extracted book text.

    Args:
        text: raw extracted text (OCR or text layer).
        llm_boundary_fn: optional callable returning (start, end) char offsets
            of the story within ``text``; failures degrade to heuristics.
        enabled: override for MAIN_CONTENT_FILTER_ENABLED.

    Returns:
        MainContentResult with the kept story text plus a removal report.
        Never returns empty text: on any pathology the original text is
        returned with ``degraded=True`` and a log line.
    """
    if enabled is None:
        enabled = filter_enabled()
    if not enabled:
        return MainContentResult(text=text, method="passthrough")

    if not text or not text.strip():
        return MainContentResult(text=text, method="passthrough", degraded=True)

    if len(text) < MIN_INPUT_CHARS:
        return MainContentResult(text=text, method="passthrough")

    # Optional LLM boundary refinement first; heuristics always computed as
    # fallback / merge base.
    llm_text = _apply_llm_boundaries(text, llm_boundary_fn)

    blocks = split_blocks(text)
    flags = classify_blocks(blocks)
    start, end = find_main_range(blocks, flags)

    kept: List[str] = []
    removed: List[str] = []
    for i, block in enumerate(blocks):
        if i < start or i >= end or flags[i]:
            removed.append(block)
        else:
            kept.append(block)

    heuristic_text = "\n\n".join(kept).strip()

    # Sanity: never hollow out the book.
    if len(heuristic_text) < max(200, int(len(text) * MIN_KEEP_RATIO)):
        logger.warning(
            "[main-content] heuristic trimming too aggressive "
            f"(kept {len(heuristic_text)}/{len(text)} chars); returning original text"
        )
        if llm_text:
            return MainContentResult(text=llm_text, removed_blocks=removed, method="heuristic+llm")
        return MainContentResult(text=text, method="passthrough", degraded=True)

    removed_chars = len(text) - len(heuristic_text)
    if removed_chars > 0:
        logger.info(
            f"[main-content] trimmed {removed_chars} chars of non-story matter "
            f"({len(removed)} blocks: front/activities/back matter); "
            f"kept {len(heuristic_text)} chars of story"
        )

    if llm_text:
        # Merge: keep heuristic block-level cleaning (removes inline activity
        # blocks the LLM boundaries cannot see), using LLM only when it agrees
        # on a narrower story range (both non-empty, LLM within heuristic±).
        method = "heuristic+llm"
    else:
        method = "heuristic"

    return MainContentResult(text=heuristic_text, removed_blocks=removed, method=method)
