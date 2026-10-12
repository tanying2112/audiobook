"""窗口化 SenseVoice: 10s 窗 × 0-680s → 时间戳化转写(粗粒度)。
纯文件运行(禁 -m/禁 app 导入图)——funasr 隔离铁律。
模型只加载一次,窗内 generate;空窗=纯音乐/静音间奏。
"""
import json, os, subprocess, sys, tempfile
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
WAV = ROOT / "scratch/football_test/ref/full_book.wav"
OUT = ROOT / "scratch/football_test/ref/ch1_windows.json"
WIN, TOTAL = 10, 680
print("[win] loading SenseVoice...", flush=True)
from funasr import AutoModel
model = AutoModel(model="iic/SenseVoiceSmall", device="cpu", disable_update=True, disable_pbar=True)
print("[win] model loaded; slicing windows", flush=True)
import re
res = {}
tmp = Path(tempfile.mkdtemp(prefix="win_"))
for s in range(0, TOTAL, WIN):
    seg = tmp / f"w{s:04d}.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(s), "-t", str(WIN),
                    "-i", str(WAV), "-ar", "16000", "-ac", "1", str(seg)], check=True)
    try:
        r = model.generate(input=str(seg), batch_size_s=60)
        txt = r[0].get("text", "") if r else ""
    except Exception as e:
        txt = f"<ERR {e}>"
    txt = re.sub(r"<\|[^|]*\|>\s*", " ", txt).strip()
    res[s] = txt
    print(f"[win] {s:3d}-{s+WIN:3d}s  {len(txt.split()):3d}w  {txt[:70]}", flush=True)
    seg.unlink()
OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
print(f"[win] {len(res)} windows -> {OUT}")
print("WINDOWS_DONE")
