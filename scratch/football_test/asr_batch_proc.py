#!/usr/bin/env python
"""Isolated batch FunASR worker — _asr_proc.py 的批量版 (一次模型加载转写多个文件).

用法: asr_batch_proc.py <model_name> <audio1> <audio2> ...
协议: stdout 每文件恰一行 JSON {"path":..., "success":true, "text":...} (增量 flush),
      失败行 {"path":..., "success":false, "error":...}。父进程按行解析, 已完成行
      即有效 (超时/崩溃时 TimeoutExpired.stdout 里的行也能救回)。
隔离契约与 _asr_proc.py 相同: 纯文件子进程运行 (禁 python -m), 导入面只允许
stdlib + funasr + soundfile; ≤240s/16kHz mono 分块, 不走 merge_vad。
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


def transcribe(model, audio_path: str) -> str:
    texts = []
    tmpdir = tempfile.mkdtemp(prefix="funasr_batch_")
    try:
        chunks = segment_chunks(audio_path, tmpdir)
        if chunks:
            import soundfile as sf
            for chunk in chunks:
                result = model.generate(input=str(chunk), batch_size_s=300)
                if not result:
                    continue
                if result[0].get("text"):
                    texts.append(result[0]["text"])
        else:
            result = model.generate(input=str(audio_path), batch_size_s=300)
            if result and result[0].get("text"):
                texts.append(result[0]["text"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return "".join(texts)


def main() -> int:
    if len(sys.argv) < 3:
        print(json.dumps({"path": "", "success": False,
                          "error": f"usage: {sys.argv[0]} <model> <wav>..."}), flush=True)
        return 1
    model_name, paths = sys.argv[1], sys.argv[2:]
    from funasr import AutoModel
    model = AutoModel(model=model_name, device="cpu",
                      disable_update=True, disable_pbar=True)
    rc = 0
    for p in paths:
        try:
            text = transcribe(model, p)
            if text.strip():
                print(json.dumps({"path": p, "success": True, "text": text},
                                 ensure_ascii=False), flush=True)
            else:
                print(json.dumps({"path": p, "success": False,
                                  "error": "empty hypothesis"}, ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({"path": p, "success": False,
                              "error": f"{type(e).__name__}: {e}"[:300]},
                             ensure_ascii=False), flush=True)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
