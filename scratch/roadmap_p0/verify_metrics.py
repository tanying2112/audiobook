"""P0.3 验证：裁判策略 + 分块转写（短/长文件，长文件=修复前必崩路径）。"""
import sys, time
sys.path.insert(0, "/Users/guwj/Documents/audiobook")
from pathlib import Path
from src.audiobook_studio.quality.metrics import ASRWerMetric, FunASRBackend

m = ASRWerMetric(model_name="auto", mock_mode=True)
zh, en = m._resolve_backend("zh"), m._resolve_backend("en")
assert zh.model_name == "iic/SenseVoiceSmall", zh.model_name
assert en.model_name == "iic/SenseVoiceSmall"
assert m._resolve_backend("ja") is en and m._resolve_backend("zh") is zh
print("[1] auto 裁判 zh/en/ja → SenseVoiceSmall + 缓存复用  OK", flush=True)

m2 = ASRWerMetric(backend="funasr", model_name="paraformer-zh", mock_mode=True)
assert m2._resolve_backend("en") is m2._backend
print("[2] 显式 paraformer-zh 不被 auto 覆盖  OK", flush=True)

r = FunASRBackend(model_name="sensevoice_small", mock_mode=True).transcribe(Path("x.wav"))
assert r.success and r.text == "这是一段模拟的中文语音识别结果"
print("[3] mock 转写不受影响  OK", flush=True)

b = FunASRBackend(model_name="sensevoice_small")
t0 = time.time()
r = b.transcribe(Path("/Users/guwj/Documents/audiobook/scratch/kokoro_iter/smoke60.wav"))
assert r.success and len(r.text) > 20, (r.success, r.error)
print(f"[4] 短文件(60s): {len(r.text)} 字, {r.duration_ms}ms, 墙钟 {time.time()-t0:.1f}s  OK", flush=True)

t0 = time.time()
r = b.transcribe(Path("/Users/guwj/Documents/audiobook/scratch/kokoro_iter/final_wav/final_raw.wav"))
assert r.success and len(r.text) > 5000, (r.success, r.error, len(r.text))
print(f"[5] 长文件(35.3min, 修复前必崩): {len(r.text)} 字, {r.duration_ms}ms, 墙钟 {time.time()-t0:.1f}s  OK", flush=True)
print("    head:", r.text[:60])
