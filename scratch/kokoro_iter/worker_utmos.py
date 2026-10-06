"""UTMOS 打分子进程：只 import torch/torchaudio/soundfile，绝不 import src 包
（src.metrics 链 + torch.hub.load 同进程会 SIGSEGV，见项目记忆 torch 2.2.2）。
用法: worker_utmos.py wav1 wav2 ...  → stdout: {"path": score, ...}"""
import json, sys
import torch
import torchaudio

model = torch.hub.load("tarepan/SpeechMOS:v1.2.0", "utmos22_strong", trust_repo=True)
model.eval()
out = {}
for p in sys.argv[1:]:
    wav, sr = torchaudio.load(p)
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != 16000:
        wav = torchaudio.transforms.Resample(sr, 16000)(wav)
    with torch.no_grad():
        score = model(wav, sr=16000)
    out[p] = round(float(score.item()), 4)
print(json.dumps(out))
