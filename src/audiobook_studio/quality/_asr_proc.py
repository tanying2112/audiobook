#!/usr/bin/env python
"""Isolated FunASR transcription worker — subprocess entry, NOT an importable module.

Run as a plain file:  python _asr_proc.py <audio_path> <model_name> [device]

为什么是子进程：本机（torch 2.2.2 / macOS x86_64）上 funasr generate() 与完整
audiobook app 导入图（≈5500 模块：torch+onnxruntime+pymupdf+litellm+scipy+
pandas+...）共存时必 SIGSEGV（模型加载完成后即死，探针见
scratch/roadmap_p0/probe/）；funasr 单独进程稳定。本文件必须以纯文件路径运行
——`python -m` 会连带执行包 __init__ 全图，正是要避开的东西。父进程是
quality/metrics.py 的 FunASRBackend.transcribe。

为什么分块：generate(merge_vad=True) 在 torch 2.2.2 CPU 长音频单输入下静默硬崩
（无 traceback、tqdm 冻结、泄漏信号量）。用 ffmpeg 切 ≤240s / 16kHz 单声道块，
逐块 generate 且不走 merge_vad；短文件自然只有一块。

协议：stdout 恰好一行 JSON。
  {"success": true, "text": str, "words": [...], "language": "zh",
   "confidence": 1.0, "duration_ms": int}
  {"success": false, "error": str}
导入面只允许：stdlib + funasr + soundfile。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

CHUNK_SECONDS = 240


def segment_chunks(audio_path: str, tmpdir: str):
    """ffmpeg → ≤240s 16kHz mono pcm_s16le 块。失败返回 []（调用方走单发回退）。"""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", audio_path,
             "-ar", "16000", "-ac", "1", "-f", "segment",
             "-segment_time", str(CHUNK_SECONDS), "-c:a", "pcm_s16le",
             str(Path(tmpdir) / "c%04d.wav")],
            capture_output=True, text=True, timeout=300,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    return sorted(Path(tmpdir).glob("c*.wav"))


def extract_words(first, offset_ms):
    """展平 funasr 词时间戳，按块起点偏移 *offset_ms*。"""
    words = []
    for w in first.get("words", []):
        words.append({
            "word": w.get("word", w.get("text", "")),
            "start_ms": int(w.get("start", 0) * 1000) + offset_ms,
            "end_ms": int(w.get("end", 0) * 1000) + offset_ms,
            "confidence": w.get("confidence", 1.0),
        })
    return words


def emit(payload) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        return emit({"success": False,
                     "error": f"usage: {sys.argv[0]} <audio> <model> [device]"})
    audio_path, model_name = sys.argv[1], sys.argv[2]
    device = sys.argv[3] if len(sys.argv) > 3 else "cpu"
    try:
        from funasr import AutoModel

        model = AutoModel(model=model_name, device=device,
                          disable_update=True, disable_pbar=True)
        texts, words, offset_ms = [], [], 0
        tmpdir = tempfile.mkdtemp(prefix="funasr_chunks_")
        try:
            chunks = segment_chunks(audio_path, tmpdir)
            if chunks:
                import soundfile as sf

                for chunk in chunks:
                    result = model.generate(input=str(chunk), batch_size_s=300)
                    if not result:
                        continue
                    first = result[0]
                    if first.get("text"):
                        texts.append(first["text"])
                    words.extend(extract_words(first, offset_ms))
                    try:
                        offset_ms += int(sf.info(str(chunk)).duration * 1000)
                    except Exception:
                        offset_ms += CHUNK_SECONDS * 1000
            else:
                # ffmpeg 不可用/失败：单发（仍不走 merge_vad）。长输入在此可能
                # 触发 torch 2.2.2 硬崩 → 父进程按 rc!=0 上报，不殃及 app 进程。
                result = model.generate(input=str(audio_path), batch_size_s=300)
                if result:
                    first = result[0]
                    if first.get("text"):
                        texts.append(first["text"])
                    words.extend(extract_words(first, 0))
                    if "duration" in first:
                        offset_ms = int(first["duration"] * 1000)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        text = "".join(texts)
        if not text.strip():
            return emit({"success": False,
                        "error": "empty hypothesis (silence / non-speech / VAD rejected)"})
        return emit({"success": True, "text": text, "words": words,
                     "language": "zh", "confidence": 1.0, "duration_ms": offset_ms})
    except Exception as e:  # 任何失败都结构化上报，绝不只留 traceback
        return emit({"success": False, "error": f"{type(e).__name__}: {e}"[:500]})


if __name__ == "__main__":
    sys.exit(main())
