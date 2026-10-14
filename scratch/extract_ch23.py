"""提取《高性价比人生指南》第 23 节「学什么技能划算」（0-based 页 236-244），
清洗页眉页脚/URL 后按条目分段，输出 ch23_clean.txt 供 TTS。"""
import re
import fitz

PDF = '/Users/guwj/Pictures/高性价比人生指南-HowToLiveBetter-现代-338页.pdf'
TITLE = "23. 学什么技能划算"
PAGES = range(236, 245)

doc = fitz.open(PDF)
lines = []
for i in PAGES:
    lines.extend(doc[i].get_text().splitlines())

clean = []
for ln in lines:
    s = ln.strip()
    if not s:
        clean.append("")
        continue
    if s == "高性价比人生指南" or s == TITLE:
        continue
    if re.fullmatch(r"\d{1,3} / 336", s):
        continue
    clean.append(s)

text = "\n".join(clean)
text = re.sub(r"https?://\S+", "", text)
text = re.sub(r"\n{3,}", "\n\n", text)

paras = []
cur = ""
for ln in text.splitlines():
    s = ln.strip()
    if not s:
        if cur:
            paras.append(cur)
            cur = ""
        continue
    if re.match(r"^\d{1,2}\. ", s) or s.startswith("• "):
        if cur:
            paras.append(cur)
        cur = s
    else:
        cur = cur + s
if cur:
    paras.append(cur)

paras = [p for p in paras if len(re.findall(r"[一-鿿A-Za-z]", p)) >= 4]
paras = [TITLE] + paras  # 标题独立成段（朗读开场）

out = "output/howtolivebetter_ch23/ch23_clean.txt"
with open(out, "w", encoding="utf-8") as f:
    f.write("\n\n".join(paras))

total = sum(len(p) for p in paras)
print(f"paragraphs: {len(paras)}, total chars: {total}, longest: {max(len(p) for p in paras)}")
print("[0]", paras[0])
print("[1]", paras[1][:50])
