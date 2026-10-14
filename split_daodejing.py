"""Split the full Daodejing text into chapters and save all of them."""

import os
import re

SRC = "output/daodejing_full.txt"
OUT_DIR = "output/daodejing_chapters"

text = open(SRC, encoding="utf-8").read()
lines = text.split("\n")

# Body starts at the "《老子》正文解读" marker; everything before is TOC/intro.
body_start = next(i for i, ln in enumerate(lines) if "正文解读" in ln and "|" not in ln)

chapters = []
current_start, current_title = None, None
for i in range(body_start, len(lines)):
    line = lines[i]
    s = line.strip()
    # Real chapter titles are short lines; in-text references like
    # "第一章的内容…" / "第十七章提到…" have a function word right after 章.
    m = re.match(r"^第[一二三四五六七八九十百0-9]+章", s)
    if m and len(s) < 30 and not re.match(r"^(的|首先|说|提到|谈|讲|介绍|内容|中|里|指|写|开头|认为)", s[m.end() :]):
        if current_start is not None:
            chapters.append((current_title, current_start, i))
        current_start = i
        current_title = line.strip()
if current_start is not None:
    chapters.append((current_title, current_start, len(lines)))

# Remove stale chapter files from the previous (buggy-trim) split.
for old in os.listdir(OUT_DIR) if os.path.isdir(OUT_DIR) else []:
    if old.startswith("chapter_"):
        os.remove(os.path.join(OUT_DIR, old))

os.makedirs(OUT_DIR, exist_ok=True)
for idx, (title, s, e) in enumerate(chapters):
    content = "\n".join(lines[s:e]).strip()
    fname = os.path.join(OUT_DIR, f"chapter_{idx + 1:02d}.txt")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"chapter_{idx + 1:02d}: {len(content):6d} chars | {title[:40]}")

print(f"\nTotal: {len(chapters)} chapters")
