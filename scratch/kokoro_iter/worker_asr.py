"""ASR+CER 打分子进程：faster-whisper base (zh) + 字级 Levenshtein CER。
绝不 import src 包（进程隔离）。whisper-zh 输出繁体 → zhconv 归简体后再对齐。
输入: JSON {"path": "参考文本", ...}  输出: {"path": {"cer": f, "hyp": str}}"""
import json, re, sys, unicodedata

refs = json.loads(sys.argv[1])
from faster_whisper import WhisperModel
from zhconv import convert

model = WhisperModel("base", device="cpu", compute_type="int8")

def norm(t: str) -> str:
    """纯汉字比对：数字/拉丁的读法已在音素层验证（cmn 全量 token 实测），
    ASR 对数字/英文名的回写形态不稳定（23↔二十三、Cepeda↔塞佩达），
    保留会引入系统性噪声，故剥离。"""
    t = unicodedata.normalize("NFKC", t).lower()
    t = re.sub(r"[^一-鿿]", "", t)
    return convert(t, "zh-hans")

def cer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    if not r:
        return 0.0
    n, m = len(r), len(h)
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r[i - 1] != h[j - 1]))
        prev = cur
    return prev[m] / n

out = {}
for path, ref in refs.items():
    segs, _ = model.transcribe(path, language="zh", beam_size=5, vad_filter=True)
    hyp = "".join(s.text for s in segs)
    out[path] = {"cer": round(cer(ref, hyp), 4), "hyp": hyp.strip()[:120]}
print(json.dumps(out, ensure_ascii=False))
