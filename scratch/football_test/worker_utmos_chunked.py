"""UTMOS 分块打分子进程（本机长音频整段推理会拖 10+ 分钟，见 utmos_probe 诊断）。
30s 无重叠分块、逐块计分取均值（UTMOS 原论文口径即 ≤20s 短句评测）。
每块进度打到 stderr，最终 stdout 恰一行 JSON（协议同 worker_utmos.py）。
用法: worker_utmos_chunked.py wav1 wav2 ...
"""
import json, os, sys
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import torch
torch.set_num_threads(2)
import torchaudio

HUB = os.path.expanduser("~/.cache/torch/hub/tarepan_SpeechMOS_v1.2.0")
model = torch.hub.load(HUB, "utmos22_strong", source="local", trust_repo=True)
model.eval()

CHUNK = 16000 * 30  # 30s
out = {}
for p in sys.argv[1:]:
    wav, sr = torchaudio.load(p)
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != 16000:
        wav = torchaudio.transforms.Resample(sr, 16000)(wav)
    x = wav[0]
    scores = []
    for i in range(0, len(x), CHUNK):
        seg = x[i:i + CHUNK]
        if len(seg) < 16000:  # <1s 尾块跳过
            continue
        with torch.no_grad():
            s = model(seg.unsqueeze(0), sr=16000)
        scores.append(float(s.item()))
        print(f"[chunk {i // CHUNK + 1}] {float(s.item()):.4f}", file=sys.stderr, flush=True)
    out[p] = round(sum(scores) / max(len(scores), 1), 4)
    print(f"[mean] {p}: {out[p]}", file=sys.stderr, flush=True)
print(json.dumps(out))
