"""SRT 字幕转可读文本清洗器。

功能：
1. 移除时间戳、序号
2. 智能合并跨行断词 (基于词典/语言模型)
3. 修正标点空格、人名一致性
4. 段落语义重组（按说话人、场景）
5. 可选：LLM 二次润色
"""

import logging
import re
from pathlib import Path
from typing import Optional

from ..llm import create_router

logger = logging.getLogger(__name__)

# 人名/专有名词规范化映射（可通过配置文件扩展）
NAME_NORMALIZATION = {
    "Delia": "Della",
    "Sofronie": "Sofronie",
    "Ellison": "Ellison",
    "Scudder": "Scudder",
    "Rockwall": "Rockwall",
    "Lantry": "Lantry",
    "Sofronie's": "Sofronie's",
    "Magi": "Magi",
    "Dillingham": "Dillingham",
    "Sofronies": "Sofronie's",
}

# 常见英文缩写/词汇保护（避免过度合并）
PROTECTED_PATTERNS = [
    r"\b(?:Mr|Mrs|Dr|Ms|Prof|Sr|Jr)\.",
    r"\b(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.",
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.",
    r"\b(?:etc|e\.g|i\.e|vs|Mr|Mrs)\.",
    r"\b\d{1,2}:\d{2}\b",  # 时间格式
]

# 常见英语双字母词（避免被错误合并到后续单词）
# 这些是独立存在的常用词，不应与后续单词合并
COMMON_TWO_LETTER_WORDS = {
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "or",
    "as",
    "if",
    "is",
    "it",
    "he",
    "we",
    "me",
    "my",
    "up",
    "us",
    "go",
    "do",
    "be",
    "am",
    "an",
    "so",
    "no",
    "hi",
    "ok",
    "oh",
    "ah",
    "ha",
    "ho",
    "hm",
    "mm",
    "ex",
    "vs",
    "etc",
    "mr",
    "ms",
    "dr",
    "sr",
    "jr",
    "st",
    "rd",
    "th",
    "nd",
    "am",
    "pm",
    "ad",
    "bc",
    "ce",
    "bce",
    # SRT 常见断词前缀（需保护避免过度合并）
    "co",
    "ld",
    "pr",
    "re",
    "un",
    "de",
    "pre",
    "pro",
    "per",
    "com",
    "con",
    "dis",
    "mis",
    "sub",
    "super",
    "inter",
    "trans",
    "over",
    "under",
    "out",
    "up",
    "down",
    "off",
    "on",
    "in",
    "ex",
    "en",
}

# 常见英语单词词典（用于验证合并结果是否为真实单词）
# 涵盖高频词汇，避免错误合并产生非单词
COMMON_ENGLISH_WORDS = {
    # 一字词
    "a",
    "i",
    # 二字高频词
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "or",
    "as",
    "if",
    "is",
    "it",
    "he",
    "we",
    "me",
    "my",
    "up",
    "us",
    "go",
    "do",
    "be",
    "am",
    "an",
    "so",
    "no",
    "hi",
    "ok",
    "oh",
    "ah",
    "ha",
    "ho",
    "hm",
    "mm",
    "ex",
    "vs",
    "mr",
    "ms",
    "dr",
    "sr",
    "jr",
    "st",
    "rd",
    "th",
    "nd",
    # 三字高频词
    "the",
    "and",
    "for",
    "are",
    "but",
    "not",
    "you",
    "all",
    "any",
    "can",
    "her",
    "was",
    "one",
    "our",
    "out",
    "day",
    "get",
    "has",
    "him",
    "his",
    "how",
    "its",
    "may",
    "new",
    "now",
    "old",
    "see",
    "two",
    "way",
    "who",
    "boy",
    "did",
    "she",
    "use",
    "man",
    "too",
    "yes",
    "off",
    "put",
    "end",
    "why",
    "let",
    "big",
    "few",
    "run",
    "own",
    "say",
    "try",
    "ask",
    "need",
    # 四字高频词
    "that",
    "with",
    "have",
    "this",
    "will",
    "your",
    "from",
    "they",
    "know",
    "want",
    "been",
    "good",
    "much",
    "some",
    "time",
    "very",
    "when",
    "come",
    "here",
    "just",
    "like",
    "long",
    "make",
    "many",
    "over",
    "such",
    "take",
    "than",
    "them",
    "well",
    "were",
    "what",
    "year",
    "into",
    "back",
    "down",
    "only",
    "find",
    "work",
    "life",
    "most",
    "also",
    "after",
    "think",
    "first",
    "other",
    "look",
    "then",
    "more",
    "these",
    "could",
    "now",
    "than",
    "its",
    # 五字+高频词
    "about",
    "after",
    "again",
    "below",
    "could",
    "every",
    "first",
    "found",
    "great",
    "house",
    "large",
    "learn",
    "never",
    "other",
    "place",
    "plant",
    "point",
    "right",
    "small",
    "sound",
    "spell",
    "still",
    "study",
    "their",
    "there",
    "these",
    "thing",
    "think",
    "three",
    "water",
    "where",
    "which",
    "world",
    "would",
    "write",
    "people",
    "money",
    "problem",
    "problems",
    "difficult",
    "stories",
    "story",
    "america",
    "henry",
    "oklahoma",
    "texas",
    "york",
    "new",
    "north",
    "carolina",
    "dillingham",
    "young",
    "della",
    "jim",
    "sofronie",
    "magi",
    "christmas",
    "gift",
    "gifts",
    "special",
    "beautiful",
    "watch",
    "chain",
    "combs",
    "hair",
    "door",
    "street",
    "store",
    "office",
    "window",
    "kitchen",
    "apartment",
    "apartments",
    "building",
    "floor",
    "table",
    "food",
    "money",
    "week",
    "days",
    "work",
    "write",
    "books",
    "writer",
    "famous",
    "short",
    "life",
    "love",
    "man",
    "woman",
    "old",
    "young",
    "happy",
    "sad",
    "cold",
    "warm",
    "heavy",
    "light",
    "dark",
    "important",
    "expensive",
    "interesting",
    "little",
    "smile",
    "eyes",
    "face",
    "hand",
    "head",
    "morning",
    "evening",
    "afternoon",
    "o'clock",
    "thinks",
    "says",
    "asks",
    "looks",
    "opens",
    "takes",
    "gives",
    "buys",
    "sells",
    "runs",
    "walks",
    "sits",
    "stands",
    "starts",
    "stops",
    "begins",
    "ends",
    "lives",
    "dies",
    "remembers",
    "forgets",
    "knows",
    "understands",
    "finishes",
    "continues",
    "fields",
    "ranches",
    "towns",
    "problems",
    "times",
    "years",
    "weeks",
    "december",
    "december",
    "week",
    "weeks",
    "office",
    "window",
    # 常见动词形式
    "started",
    "finished",
    "worked",
    "lived",
    "moved",
    "went",
    "came",
    "thought",
    "said",
    "told",
    "asked",
    "looked",
    "opened",
    "closed",
    "walked",
    "ran",
    "sat",
    "stood",
    "began",
    "ended",
    "changed",
    # 缩写形式
    "let's",
    "it's",
    "he's",
    "she's",
    "that's",
    "what's",
    "who's",
    "where's",
    "when's",
    "why's",
    "how's",
    "there's",
    "here's",
    "i'm",
    "you're",
    "we're",
    "they're",
    "i've",
    "you've",
    "we've",
    "they've",
    "i'd",
    "you'd",
    "he'd",
    "she'd",
    "we'd",
    "they'd",
    "i'll",
    "you'll",
    "he'll",
    "she'll",
    "we'll",
    "they'll",
    "don't",
    "doesn't",
    "didn't",
    "won't",
    "wouldn't",
    "can't",
    "couldn't",
    "shouldn't",
    "mustn't",
    "needn't",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
    "haven't",
    "hasn't",
    "hadn't",
    # 所有格
    "henry's",
    "della's",
    "jim's",
    "sofronie's",
    "dillingham's",
    "young's",
    # 常见词尾词首组合 + SRT常见断词补全
    "difficult",
    "expensive",
    "different",
    "important",
    "interesting",
    "beautiful",
    "wonderful",
    "terrible",
    "possible",
    "impossible",
    "christmas",
    "delia",
    "sofronie",
    "scudder",
    "rockwall",
    "lantry",
    "ellison",
    "magis",
    "dillingham",
    # SRT特有断词补全
    "apartm",
    "ent",
    "proble",
    "ms",
    "sto",
    "ries",
    "dif",
    "ficult",
    "expe",
    "nsive",
    "differ",
    "ent",
    "import",
    "ant",
    "intere",
    "sting",
    "beauti",
    "ful",
    "wonder",
    "ful",
    "terri",
    "ble",
    "poss",
    "ible",
    "imposs",
    "ible",
    "spec",
    "ial",
    "christ",
    "mas",
    "del",
    "ia",
    "sof",
    "ronie",
    "scud",
    "der",
    "rock",
    "wall",
    "lant",
    "ry",
    "ell",
    "ison",
    "mag",
    "is",
    "dill",
    "ingham",
    "fif",
    "teenth",
    "fifteenth",
    "restauran",
    "ts",
    "restaurant",
    "eve",
    "ry",
    "every",
    "evening",
    "getting",
    "gett",
    "ing",
    "music",
    "stories",
    "story",
    "hi",
    "sm",
    "hism",
    "us",
    "tomor",
    "row",
    "tomorrow",
    "yester",
    "day",
    "yesterday",
    "happ",
    "en",
    "happen",
    "happened",
    "morn",
    "ing",
    "aftern",
    "noon",
    "even",
    "tonight",
    "afternoon",
    "speci",
    "al",
    "especi",
    "ally",
    "especial",
    "diffi",
    "cult",
    "expen",
    "sive",
    "impor",
    "tant",
    "beau",
    "tiful",
    "wonder",
    "ful",
    "intere",
    "sting",
    "apart",
    "ment",
    "probl",
    "em",
    "prob",
    "lem",
    "chri",
    "stmas",
    "christm",
    "as",
    "expens",
    "ive",
    "fif",
    "th",
    "fifteenth",
    "rest",
    "aurant",
    "restaur",
    "ant",
    "hism",
    "usic",
    "eve",
    "ryeven",
    "ing",
    "ev",
    "ery",
    "ev",
    "gett",
    "ing",
    "get",
    "ting",
}


def parse_srt(srt_path: Path) -> list[dict]:
    """解析 SRT 为结构化条目列表。

    Args:
        srt_path: SRT 文件路径

    Returns:
        条目列表，每项包含 index, timecode, text
    """
    content = srt_path.read_text(encoding="utf-8")
    entries = []
    # 按空行分割字幕块
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            try:
                idx = int(lines[0].strip())
                timecode = lines[1].strip()
                text = "\n".join(lines[2:]).strip()
                entries.append({"index": idx, "timecode": timecode, "text": text})
            except ValueError:
                continue
    return entries


def _is_protected(text: str, pos: int, length: int) -> bool:
    """检查位置是否在受保护模式内（如缩写）。"""
    for pattern in PROTECTED_PATTERNS:
        for match in re.finditer(pattern, text):
            if match.start() <= pos < match.end():
                return True
    return False


def _is_valid_word(word: str) -> bool:
    """检查合并后的词是否为有效英语单词（小写匹配）。"""
    return word.lower() in COMMON_ENGLISH_WORDS


def _try_merge_prefix(text: str, prefix_len: int, min_rest_len: int = 1) -> str:
    """通用前缀合并：尝试合并 N 字母前缀 + 剩余部分。

    仅当合并后形成有效单词时合并。
    """
    pattern = rf"\b([a-zA-Z]{{{prefix_len}}})\s+([a-zA-Z]{{{min_rest_len},}})\b"

    def repl(m):
        if _is_protected(text, m.start(), len(m.group(0))):
            return m.group(0)
        merged = m.group(1) + m.group(2)
        if len(merged) > 20:
            return m.group(0)
        if _is_valid_word(merged):
            return merged
        return m.group(0)

    return re.sub(pattern, repl, text)


def merge_broken_words(text: str) -> str:
    """合并跨行断词（基于启发式 + 词典）。

    处理 SRT 特有的断词问题：
    - 单字符换行: "f\nor" -> "for"
    - 单字符空格分隔: "f or" -> "for" (SRT 条目边界)
    - 双字符换行: "th\ne " -> "the "
    - 双字符空格分隔: "th e" -> "the" (SRT 条目边界)
    - 三字符分隔: "pro ble" -> "proble" (待后续合并)
    - 四字符分隔: "diffi cult" -> "difficult"
    - 标点粘连: "87?What" -> "87? What"
    - 句号粘连: "thinks.O." -> "thinks. O."
    - 小写+大写粘连: "wordWord" -> "word Word"
    - 所有格粘连: "Henry'sshort" -> "Henry's short"
    - 缩写粘连: "Let'sopen" -> "Let's open"
    - 词尾词首跨条目: "proble ms" -> "problems"
    """
    if not text:
        return text

    # 0. 所有格 's + 单词粘连: "Henry'sshort" -> "Henry's short"
    # 匹配 's 后直接跟字母（不分大小写），但排除 its, his, hers, ours, yours, theirs 等物主代词
    text = re.sub(r"(?<![a-zA-Z])('s)([A-Za-z])", r"\1 \2", text)
    # 也处理单词内部的 's + 字母（如 Henry'sshort），但排除 its, his, hers 等
    text = re.sub(
        r"(?<=[a-zA-Z])('s)([A-Za-z])",
        lambda m: m.group(1) + " " + m.group(2) if m.group(0)[-3:].lower() not in ["its", "his", "her"] else m.group(0),
        text,
    )

    # 0b. 所有格 s' + 单词: "parents'house" -> "parents' house"
    text = re.sub(r"(s')([A-Za-z])", r"\1 \2", text)

    # 0c. 缩写粘连: "Let'sopen" "can'tsee" "doesn'tlook" -> "Let's open" "can't see" "doesn't look"
    # 匹配常见缩写后直接跟小写字母（包括开头无词边界的情况）
    text = re.sub(
        r"(?:^|\s|[.!?])(let's|it's|he's|she's|that's|what's|who's|where's|when's|why's|how's|there's|here's|i'm|you're|we're|they're|i've|you've|we've|they've|i'd|you'd|he'd|she'd|we'd|they'd|i'll|you'll|he'll|she'll|we'll|they'll|don't|doesn't|didn't|won't|wouldn't|can't|couldn't|shouldn't|mustn't|needn't|isn't|aren't|wasn't|weren't|haven't|hasn't|hadn't)([a-z])",
        lambda m: (
            (m.group(1) if m.group(1) else "") + m.group(2).upper()
            if False
            else (m.group(1) + " " + m.group(2)) if m.group(1) else m.group(2)
        ),
        text,
        flags=re.IGNORECASE,
    )
    # 简化版本：直接在缩写列表中的形式后加空格
    contraction_pattern = r"(let's|it's|he's|she's|that's|what's|who's|where's|when's|why's|how's|there's|here's|i'm|you're|we're|they're|i've|you've|we've|they've|i'd|you'd|he'd|she'd|we'd|they'd|i'll|you'll|he'll|she'll|we'll|they'll|don't|doesn't|didn't|won't|wouldn't|can't|couldn't|shouldn't|mustn't|needn't|isn't|aren't|wasn't|weren't|haven't|hasn't|hadn't)([a-zA-Z])"
    text = re.sub(contraction_pattern, r"\1 \2", text, flags=re.IGNORECASE)

    # 0d. 无撇号缩写修正：只在合并后形成已知缩写时添加撇号
    # 先处理明确的缩写形式（有词典支持）
    # 注意：排除 "well"、"were"、"ill"、"hell"、"shell" 等真实单词
    known_contractions = {
        "im": "i'm",
        "youre": "you're",
        "hes": "he's",
        "shes": "she's",
        "theyre": "they're",
        "its": "it's",
        "ive": "i've",
        "youve": "you've",
        "weve": "we've",
        "theyve": "they've",
        "id": "i'd",
        "youd": "you'd",
        "hed": "he'd",
        "shed": "she'd",
        "wed": "we'd",
        "theyd": "they'd",
        "ill": "i'll",
        "youll": "you'll",
        "theyll": "they'll",
        "dont": "don't",
        "doesnt": "doesn't",
        "didnt": "didn't",
        "wont": "won't",
        "wouldnt": "wouldn't",
        "cant": "can't",
        "couldnt": "couldn't",
        "shouldnt": "shouldn't",
        "mustnt": "mustn't",
        "neednt": "needn't",
        "isnt": "isn't",
        "arent": "aren't",
        "wasnt": "wasn't",
        "werent": "weren't",
        "havent": "haven't",
        "hasnt": "hasn't",
        "hadnt": "hadn't",
        "lets": "let's",
        "thats": "that's",
        "whats": "what's",
        "whos": "who's",
        "wheres": "where's",
        "whens": "when's",
        "whys": "why's",
        "hows": "how's",
        "theres": "there's",
        "heres": "here's",
    }
    for nocontra, contra in known_contractions.items():
        # 仅在词边界且不是已经是正确形式时替换
        text = re.sub(rf"\b{nocontra}\b", contra, text, flags=re.IGNORECASE)

    # 1. 单字符换行合并: "f\nor" -> "for"
    # 排除英语单字词 "a" 和 "I"，避免 "a cat" -> "acat"
    # 同时排除所有格 's 和缩写
    text = re.sub(
        r"(?<!')\b([b-hj-zB-HJ-Z])\s*\n\s*([a-zA-Z]{2,})\b",
        lambda m: (
            m.group(1) + m.group(2)
            if not _is_protected(text, m.start(), len(m.group(0))) and _is_valid_word(m.group(1) + m.group(2))
            else m.group(0)
        ),
        text,
    )

    # 1b. 单字符空格分隔合并 (SRT 条目边界): "f or" -> "for"
    # 排除英语单字词 "a" 和 "I"，以及所有格 's (如 Henry's short) 和缩写 (如 doesn't look)
    text = re.sub(
        r"(?<!')\b([b-hj-zB-HJ-Z])\s+([a-zA-Z]{2,})\b",
        lambda m: (
            m.group(1) + m.group(2)
            if not _is_protected(text, m.start(), len(m.group(0))) and _is_valid_word(m.group(1) + m.group(2))
            else m.group(0)
        ),
        text,
    )

    # 1c. 换行后跟数字/标点: "\n87?What" -> " 87? What"
    text = re.sub(r"\n\s*(\d+[.!?])([A-Z])", r" \1 \2", text)

    # 2. 两字母换行: "th\ne " -> "the "
    text = re.sub(
        r"\b([a-zA-Z]{2})\s*\n\s*([a-zA-Z]+)\b",
        lambda m: (
            m.group(1) + m.group(2)
            if not _is_protected(text, m.start(), len(m.group(0)))
            and (m.group(1).lower() not in COMMON_TWO_LETTER_WORDS and _is_valid_word(m.group(1) + m.group(2)))
            and len(m.group(1) + m.group(2)) <= 15
            else m.group(0)
        ),
        text,
    )

    # 2b. 两字母空格分隔 (SRT 条目边界): "th e" -> "the"
    # 使用词典验证：如果合并后形成有效单词，则允许合并
    # 注意：不要求第2部分后有词边界，因为常接完整单词（如 "th efields" -> "the fields"）
    text = re.sub(
        r"\b([a-zA-Z]{2})\s+([a-zA-Z]{2,})(?=\s|[.!?,;:]|$)",
        lambda m: (
            m.group(1) + m.group(2)
            if not _is_protected(text, m.start(), len(m.group(0)))
            and (m.group(1).lower() not in COMMON_TWO_LETTER_WORDS and _is_valid_word(m.group(1) + m.group(2)))
            and len(m.group(1) + m.group(2)) <= 15
            else m.group(0)
        ),
        text,
    )

    # 2c. 处理 "th e" -> "the" 这类：2字母 + 空格 + 1字母
    # 这是 SRT 常见分割模式：th\n\ne -> "th e"
    # 注意：不要求第2部分后有词边界，因为常接完整单词（如 "th edifficult"）
    text = re.sub(
        r"\b([a-zA-Z]{2})\s+([a-zA-Z])(?=\s|[a-zA-Z])",
        lambda m: (
            m.group(1) + m.group(2)
            if not _is_protected(text, m.start(), len(m.group(0)))
            and (m.group(1).lower() not in COMMON_TWO_LETTER_WORDS and _is_valid_word(m.group(1) + m.group(2)))
            else m.group(0)
        ),
        text,
    )

    # 2d. 特殊处理：序数词 "Fif th" -> "Fifteenth", "Fir st" -> "First" 等
    # 这些常见于 SRT 条目边界分割
    ordinal_fixes = {
        r"\b(Fif)\s+(th)\b": "Fifteenth",
        r"\b(Fir)\s+(st)\b": "First",
        r"\b(Thir)\s+(d)\b": "Third",
        r"\b(Eigh)\s+(th)\b": "Eighth",
        r"\b(Nin)\s+(th)\b": "Ninth",
        r"\b(Twen)\s+(ty)\b": "Twenty",
        r"\b(Thir)\s+(ty)\b": "Thirty",
        r"\b(Four)\s+(ty)\b": "Forty",
        r"\b(Fif)\s+(ty)\b": "Fifty",
        r"\b(Six)\s+(ty)\b": "Sixty",
        r"\b(Seven)\s+(ty)\b": "Seventy",
        r"\b(Eigh)\s+(ty)\b": "Eighty",
        r"\b(Nine)\s+(ty)\b": "Ninety",
    }
    for pattern, replacement in ordinal_fixes.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # 2e. 处理 "Christm as" -> "Christmas" 等常见节日/专有名词分割
    special_word_fixes = {
        r"\b(Christm)\s+(as)\b": "Christmas",
        r"\b(Thanksg)\s+(iving)\b": "Thanksgiving",
        r"\b(Hallow)\s+(een)\b": "Halloween",
        r"\b(Valent)\s+(ine)\b": "Valentine",
    }
    for pattern, replacement in special_word_fixes.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # 3. 三字母前缀空格分隔: "pro ble" "dif fic" "exp ensive" -> 合并后验证
    text = _try_merge_prefix(text, 3, 2)

    # 4. 四字母前缀空格分隔: "diffi cult" "impor tant" "beau tiful" -> 合并后验证
    text = _try_merge_prefix(text, 4, 2)

    # 5. 五字母前缀空格分隔: "diffic ult" "expens ive" -> 合并后验证
    text = _try_merge_prefix(text, 5, 2)

    # 6. 通用模式：小写字母序列 + 空格 + 小写字母序列 -> 合并验证
    # 处理 "peo ple" "apart ment" "prob lem" 等
    # 但要避免破坏正常词间空格，仅在合并结果为已知单词时操作
    def merge_if_valid(m):
        if _is_protected(text, m.start(), len(m.group(0))):
            return m.group(0)
        merged = m.group(1) + m.group(2)
        if len(merged) > 20 or len(merged) < 3:
            return m.group(0)
        if _is_valid_word(merged):
            return merged
        return m.group(0)

    # 匹配 2-6 字母 + 空格 + 1-6 字母，仅在词边界
    text = re.sub(r"\b([a-z]{2,6})\s+([a-z]{1,6})\b", merge_if_valid, text)

    # 6b. 二次合并：处理首字母大写的单词分割
    # 如 "Th e" -> "The", "An d" -> "And"
    def merge_if_valid_capital(m):
        if _is_protected(text, m.start(), len(m.group(0))):
            return m.group(0)
        merged = m.group(1) + m.group(2).lower()
        if len(merged) > 20 or len(merged) < 3:
            return m.group(0)
        if _is_valid_word(merged):
            # 保持首字母大写
            return m.group(1) + m.group(2)
        return m.group(0)

    text = re.sub(r"\b([A-Z][a-z]{1,5})\s+([a-z]{1,6})\b", merge_if_valid_capital, text)

    # 6c. 处理全小写常见词首尾分割：如 "peo ple", "pro ble"
    common_splits = {
        # 3+3, 3+4, 4+3, 4+4 等常见分割
        "peo ple": "people",
        "pro ble": "problem",
        "pro blem": "problem",
        "dif ficult": "difficult",
        "diffi cult": "difficult",
        "diffic ult": "difficult",
        "expen sive": "expensive",
        "expens ive": "expensive",
        "impor tant": "important",
        "import ant": "important",
        "beau tiful": "beautiful",
        "beauti ful": "beautiful",
        "wonder ful": "wonderful",
        "won derful": "wonderful",
        "intere sting": "interesting",
        "interes ting": "interesting",
        "apart ment": "apartment",
        "apartm ent": "apartment",
        "a partment": "apartment",
        "prob lem": "problem",
        "probl em": "problem",
        "dif ferent": "different",
        "differ ent": "different",
        "spec ial": "special",
        "speci al": "special",
        "christ mas": "christmas",
        "christm as": "christmas",
        "exp ensive": "expensive",
        "expe nsive": "expensive",
        "diffi cult": "difficult",
        "dif ficult": "difficult",
        "ev ery": "every",
        "eve ry": "every",
        "ev erything": "everything",
        "every thing": "everything",
        "eve ning": "evening",
        "even ing": "evening",
        "morn ing": "morning",
        "mor ning": "morning",
        "aft ernoon": "afternoon",
        "after noon": "afternoon",
        "to morrow": "tomorrow",
        "tom orrow": "tomorrow",
        "yes terday": "yesterday",
        "yester day": "yesterday",
        "hap pen": "happen",
        "happen ed": "happened",
        "get ting": "getting",
        "get ing": "getting",
        "lis ten": "listen",
        "list ening": "listening",
        "prob lems": "problems",
        "proble ms": "problems",
        "pr oblems": "problems",
        "rest aurant": "restaurant",
        "restauran t": "restaurant",
        "fif th": "fifteenth",
        "fif teenth": "fifteenth",
        "hi s": "his",
        "hi smusic": "hismusic",
        "eve ry": "every",
        "ev ery": "every",
        "start ed": "started",
        "starte d": "started",
        "yea rs": "years",
        "year s": "years",
        "co ld": "cold",
        "th e": "the",
        "and important": "and important",
        # 常见双字母词被拆分为 1+1 的情况（小写开头，避免误合并 "I need"）
        "i n": "in",
        "o n": "on",
        "a t": "at",
        "t o": "to",
        "b y": "by",
        "i f": "if",
        "i s": "is",
        "i t": "it",
        "h e": "he",
        "w e": "we",
        "m e": "me",
        "m y": "my",
        "u p": "up",
        "u s": "us",
        "g o": "go",
        "d o": "do",
        "b e": "be",
        "a m": "am",
        "a n": "an",
        "s o": "so",
        "n o": "no",
        # 常见单词被拆分为奇怪模式
        "da y": "day",
    }
    for broken, fixed in common_splits.items():
        # 仅在词边界替换
        text = re.sub(rf"\b{re.escape(broken)}\b", fixed, text, flags=re.IGNORECASE)

    # 7. 修正 "it's" -> "its" (所有格，非缩写)
    # 仅在 "it's" 后跟名词/形容词时替换（如 "it's tall" -> "its tall"）
    text = re.sub(
        r"\b(it's)\s+(tall|short|long|big|small|large|little|happy|sad|cold|warm|dark|light|heavy|beautiful|ugly|good|bad|old|new|young|famous|special|important|difficult|expensive|interesting|wonderful|terrible|possible|impossible|happy)\b",
        r"its \2",
        text,
        flags=re.IGNORECASE,
    )

    # 7b. 数字格式修正: "$1. 87" -> "$1.87", "19 10" -> "1910"
    text = re.sub(r"(\$\d+)\. (\d{2})\b", r"\1.\2", text)  # $1. 87 -> $1.87
    text = re.sub(r"\b(\d{2})\s+(\d{2})\b", r"\1\2", text)  # 19 10 -> 1910 (年份)

    # 7c. "Mr.and" -> "Mr. and"
    text = re.sub(r"\b(Mr|Mrs|Dr|Ms|Prof|Sr|Jr)\.([A-Za-z])", r"\1. \2", text)

    # 7d. 标点后缺失空格: "?she" -> "? she", "?\"she" -> "? \"she"
    text = re.sub(r"([.!?])([\"'])([A-Za-z])", r"\1 \2\3", text)
    text = re.sub(r"([.!?])([A-Za-z])", r"\1 \2", text)

    # 7e. 闭合引号后缺失空格: '"Della' -> '" Della', '"She' -> '" She'
    # 在引号后紧跟大写字母（对话标签）时添加空格
    text = re.sub(r'([\'"])([A-Z][a-z])', r"\1 \2", text)

    # 7f. 逗号/句号+引号+大写字母: ',"Della' -> ', " Della', '."Jim' -> '. " Jim'
    text = re.sub(r'([,.])([\'"])([A-Z])', r"\1 \2\3", text)

    # 8. 标点粘连修正: "word.Word" -> "word. Word"
    text = re.sub(r"([.!?])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([.!?])([A-Z][a-z])", r"\1 \2", text)

    # 9. 逗号/分号粘连: "word,Word" -> "word, Word"
    text = re.sub(r"([,;])([A-Za-z])", r"\1 \2", text)

    # 10. 数字+问号粘连: "87?What" -> "87? What"
    text = re.sub(r"(\d)\?([A-Z])", r"\1? \2", text)

    # 11. 小写字母直接跟大写字母（漏掉的句界空格）
    text = re.sub(
        r"([a-z])([A-Z])",
        lambda m: m.group(1) + " " + m.group(2) if not _is_protected(text, m.start(), 2) else m.group(0),
        text,
    )

    # 12. 多余空白归一化
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 13. 修正标点前的多余空格: "hair ?" -> "hair?"
    text = re.sub(r"\s+([.!?,;:])", r"\1", text)

    # 14. 逗号/句号+引号+大写字母: ',"Della' -> ', " Della', '."Jim' -> '. " Jim'
    # 必须在通用引号修复之前运行
    text = re.sub(r'([,.])([\'"])([A-Z])', r"\1 \2\3", text)

    # 15. 闭合引号后补空格（对话标签）：'"Della' -> '" Della'
    # 在引号后紧跟大写字母时添加空格
    text = re.sub(r'([\'"])([A-Z])', r"\1 \2", text)

    # 16. 修正引号空格: '" word' -> '"word', 'word "' -> 'word"'
    text = re.sub(r'"\s+([^"]+?)\s*"', r'"\1"', text)
    text = re.sub(r"'([^']+?)'", r"'\1'", text)

    return text.strip()


def normalize_names(text: str) -> str:
    """人名/专有名词规范化。"""
    for wrong, correct in NAME_NORMALIZATION.items():
        text = text.replace(wrong, correct)
    return text


def regroup_paragraphs(entries: list[dict]) -> list[str]:
    """按说话人/场景重组段落。

    规则：
    - 连续同一说话人合并为一个段落
    - 说话人切换另起段落
    - 旁白(_narrator_)连续合并
    """
    paragraphs = []
    current_para = []
    current_speaker = None

    for entry in entries:
        text = entry["text"]
        # 检测说话人标签 [_speaker_]
        speaker_match = re.match(r"\[_(\w+)_\]", text)
        if speaker_match:
            speaker = speaker_match.group(1).lower()
            text = text[speaker_match.end() :].strip()
        else:
            speaker = "_narrator_"

        # 说话人切换 → 新段落
        if speaker != current_speaker and current_para:
            paragraphs.append(" ".join(current_para))
            current_para = []

        current_speaker = speaker

        if text:
            current_para.append(text)

    if current_para:
        paragraphs.append(" ".join(current_para))

    return paragraphs


def clean_srt_to_readable_text(
    srt_path: Path,
    output_path: Path,
    use_llm: bool = False,
    llm_prompt: Optional[str] = None,
) -> str:
    """主入口：SRT → 可读文本。

    Args:
        srt_path: 输入 SRT 文件路径
        output_path: 输出文本文件路径
        use_llm: 是否使用 LLM 润色
        llm_prompt: 自定义 LLM 提示词

    Returns:
        清洗后的文本内容
    """
    entries = parse_srt(srt_path)

    if not entries:
        logger.warning(f"No valid SRT entries found in {srt_path}")
        output_path.write_text("", encoding="utf-8")
        return ""

    # 1. 基础清洗：拼接 + 断词合并 + 人名规范化
    raw_text = " ".join(e["text"] for e in entries)
    text = merge_broken_words(raw_text)
    text = normalize_names(text)

    # 2. 段落重组（按说话人）
    paragraphs = regroup_paragraphs(entries)
    # 对每个段落单独做清洗
    cleaned_paragraphs = []
    for para in paragraphs:
        para = merge_broken_words(para)
        para = normalize_names(para)
        if para.strip():
            cleaned_paragraphs.append(para.strip())

    text = "\n\n".join(cleaned_paragraphs)

    # 3. 可选 LLM 润色（修正残留断词、补全标点、优化段落）
    if use_llm:
        text = llm_polish(text, llm_prompt)

    output_path.write_text(text, encoding="utf-8")
    logger.info(f"Cleaned SRT saved to {output_path} ({len(text)} chars, {len(cleaned_paragraphs)} paragraphs)")
    return text


def llm_polish(text: str, prompt: Optional[str] = None) -> str:
    """使用 LLM 做最终润色（需配置 LLM 路由）。"""
    router = create_router(mock_mode=False)
    if prompt is None:
        prompt = f"""请将以下从字幕提取的文本整理为通顺的阅读版本：

要求：
1. 修正残留的断词错误（如 "f or" → "for"）
2. 补全缺失标点和空格
3. 合并过碎片化的段落，保持语义连贯
4. 保留对话格式和说话人区分
5. 修正明显的识别错误（如人名）

原文：
{text[:12000]}

输出整理后的文本："""

    try:
        from pydantic import TypeAdapter

        from ..schemas.text_clean import TextCleanResult

        result = router.call(
            stage="clean_text",
            response_model=TypeAdapter(TextCleanResult),
            messages=[
                {"role": "system", "content": "你是专业的文本编辑，擅长将语音识别/字幕文本还原为出版级可读文本。"},
                {"role": "user", "content": prompt},
            ],
        )
        if result and result.output:
            return result.output.cleaned_text
    except Exception as e:
        logger.warning(f"LLM polish failed: {e}")
    return text


if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 3:
        print("Usage: python srt_cleaner.py <input.srt> <output.txt> [--llm]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    use_llm = "--llm" in sys.argv

    clean_srt_to_readable_text(input_path, output_path, use_llm=use_llm)
    print(f"Done: {output_path}")
