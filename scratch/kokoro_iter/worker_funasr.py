"""FunASR 中文 ASR 裁判（分块版 v2）。

背景：整文件 + merge_vad=True 路径在本机（torch 2.2.2 / i5-4690）静默硬崩——
tqdm 冻在 0/1、无 traceback、leaked semaphore（sensevoice 约 10 分钟死、paraformer 约 4 分钟死）。
对策：ffmpeg 预切 240 s / 16 kHz 单声道块，逐块 generate（不走 merge_vad），
每块 flush 进度并落盘部分转写，硬崩也能定位死点并保留已得文本。
用法: worker_funasr.py <sensevoice|paraformer> refs.json
输出: {"path": {"cer": f, "hanzi": int, "chunks": int, "hyp_head": str}}
"""
import json, os, re, subprocess, sys, tempfile, unicodedata

os.environ.setdefault("OMP_NUM_THREADS", "4")

which, refs = sys.argv[1], json.loads(open(sys.argv[2], encoding="utf-8").read())
MODEL = {"sensevoice": "iic/SenseVoiceSmall",
         "paraformer": "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"}[which]
CHUNK_S = 240

from funasr import AutoModel
from zhconv import convert

print(f"[load] {which} -> {MODEL}", flush=True)
model = AutoModel(model=MODEL, device="cpu", disable_update=True, disable_pbar=True)
print("[load] done", flush=True)

CN_NUM = "零一二三四五六七八九"
CN_UNIT = ["", "十", "百", "千"]

def _group4(g: str) -> str:
    n = len(g)
    if n == 1:
        return CN_NUM[int(g)]
    if n == 2 and g[0] == "1":
        return "十" + (CN_NUM[int(g[1])] if g[1] != "0" else "")
    out, pending = "", False
    for i, ch in enumerate(g):
        d = int(ch)
        if d == 0:
            if out:
                pending = True
        else:
            if pending:
                out += "零"
                pending = False
            out += CN_NUM[d] + CN_UNIT[n - 1 - i]
    return out or "零"

def _num2cn(s: str):
    """'19'→'十九' '0.0001'→'零点零零零一'；>8 位整数等超范围返回 None。"""
    if "." in s:
        ip, fp = s.split(".", 1)
        i = _num2cn(ip) if ip else "零"
        if i is None:
            return None
        return i + "点" + "".join(CN_NUM[int(c)] for c in fp if c.isdigit())
    t = s.lstrip("0") or "0"
    if t == "0":
        return "零"
    if len(t) > 8:
        return None
    if len(t) <= 4:
        return _group4(t)
    groups, big = [], ["", "万", "亿"]
    u = t
    while u:
        groups.append(u[-4:])
        u = u[:-4]
    out = ""
    for gi in range(len(groups) - 1, -1, -1):
        if groups[gi].strip("0"):
            out += _group4(groups[gi].lstrip("0")) + big[gi]
    return out or "零"

def norm(t: str) -> str:
    """汉字读法比对。数字串按读音展开（19%→百分之十九、5000→五千、2.9→二点九）：
    2026-10-08 误差归因（scratch/roadmap_p0/err_analysis.py）证明原"剥数字"口径
    69.7% 的误差是格式伪差——TTS 读法正确、比对口径冤枉了它。事件标签为非汉字，自然剥离。"""
    t = unicodedata.normalize("NFKC", t).lower()
    t = re.sub(r"(?<=\d),(?=\d)", "", t)  # 10,000 → 10000
    t = re.sub(r"(\d[\d.]*?)%", lambda m: "百分之" + (_num2cn(m.group(1)) or m.group(1)), t)
    t = re.sub(r"\d[\d.]*", lambda m: _num2cn(m.group(0)) or m.group(0), t)
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
    tmpdir = tempfile.mkdtemp(prefix="funasr_judge_")
    seg_pattern = os.path.join(tmpdir, "c%03d.wav")
    rc = subprocess.run(["ffmpeg", "-y", "-i", path, "-ar", "16000", "-ac", "1",
                         "-f", "segment", "-segment_time", str(CHUNK_S),
                         "-c:a", "pcm_s16le", seg_pattern],
                        capture_output=True)
    if rc.returncode != 0:
        raise RuntimeError(f"ffmpeg segment failed: {rc.stderr.decode()[-300:]}")
    chunks = sorted(f for f in os.listdir(tmpdir) if f.endswith(".wav"))
    full_hyp = ""
    for ci, cn in enumerate(chunks):
        res = model.generate(input=os.path.join(tmpdir, cn), batch_size_s=300)
        t = res[0].get("text", "") if res else ""
        full_hyp += t
        with open(os.path.join(tmpdir, "partial.txt"), "w", encoding="utf-8") as f:
            f.write(full_hyp)
        print(f"[{os.path.basename(path)}] chunk {ci+1}/{len(chunks)} +{len(t)} chars", flush=True)
    out[path] = {"cer": round(cer(ref, full_hyp), 4),
                 "hanzi": len(norm(full_hyp)),
                 "chunks": len(chunks),
                 "hyp_head": full_hyp.strip()[:80]}
    # 全文 hyp 落盘到稳定目录（供数字/多音字误差分析），随后 tmpdir 照常清理
    hyp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "roadmap_p0", "hyp")
    os.makedirs(hyp_dir, exist_ok=True)
    with open(os.path.join(hyp_dir, f"{which}_{os.path.basename(path)}.txt"), "w", encoding="utf-8") as f:
        f.write(full_hyp)
    subprocess.run(["rm", "-rf", tmpdir])
print(json.dumps(out, ensure_ascii=False))
