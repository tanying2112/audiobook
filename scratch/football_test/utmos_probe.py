"""UTMOS 分步计时探针：定位 600s 超时的真实瓶颈步骤。"""
import os, time, sys
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import torch
torch.set_num_threads(2)
t = time.time()
def log(m): print(f"[{time.time()-t:7.1f}s] {m}", flush=True)

log("import torch done")
import torchaudio
HUB = os.path.expanduser("~/.cache/torch/hub/tarepan_SpeechMOS_v1.2.0")
model = torch.hub.load(HUB, "utmos22_strong", source="local", trust_repo=True)
model.eval(); log("model loaded")

W44 = "/Users/guwj/Documents/audiobook/output/football_forever_ch1/football_forever_ch1_44k1.wav"
wav, sr = torchaudio.load(W44); log(f"loaded {W44.split('/')[-1]}: shape={tuple(wav.shape)} sr={sr}")
if sr != 16000:
    wav = torchaudio.transforms.Resample(sr, 16000)(wav); log("resampled to 16k")
with torch.no_grad():
    s = model(wav, sr=16000); log(f"inference done: score={float(s.item()):.4f}")
print("PROBE_OK", flush=True)
