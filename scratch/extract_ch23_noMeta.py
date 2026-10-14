"""第 23 节「正文版」清洗：在 ch23_clean.txt 基础上，
去掉朗读向元数据行：• 来源：…、• 证据等级：…、含残留 URL 的行。
保留 成本/说人话/收益/备注 等实质内容行。输出 ch23_body.txt。"""
import re

src = open("output/howtolivebetter_ch23/ch23_clean.txt", encoding="utf-8").read()
paras = [p.strip() for p in re.split(r"\n\s*\n", src) if p.strip()]

kept = []
dropped = 0
for p in paras:
    # 整段是元数据的丢弃（来源/证据等级 bullet）
    if re.match(r"^•\s*(来源|证据等级)[:：]", p):
        dropped += 1
        continue
    # 段内混杂的元数据子行也去掉（如「• 备注：…见第 16 条…来源：xxx」少见，仅保守处理段首 bullet）
    kept.append(p)

# 再次清 URL（防御）
kept = [re.sub(r"https?://\S+", "", p) for p in kept]
kept = [p for p in kept if len(re.findall(r"[一-鿿A-Za-z0-9]", p)) >= 4]

out = "output/howtolivebetter_ch23/ch23_body.txt"
with open(out, "w", encoding="utf-8") as f:
    f.write("\n\n".join(kept))
print(f"kept {len(kept)} / dropped {dropped} paras; chars: {sum(len(p) for p in kept)}")
for i, p in enumerate(kept[:5]):
    print(f"[{i}] {p[:66]}{'…' if len(p)>66 else ''}")
