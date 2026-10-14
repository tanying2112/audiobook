"""回归验证：默认参数 espeak 路径 byte 级不变（6122ms 基线），misaki+pause 生效。"""
import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.audiobook_studio.tts.kokoro_backend import KokoroBackend
from src.audiobook_studio.tts.engine import TTSTaskPayload, TTSVoiceAnchor, TTSProsody

TEXT = "第 2 条算读书和寿命的关系：每多受一年教育，死亡风险平均下降 1.9%。"

async def run(g2p, sp, cp, out):
    b = KokoroBackend(output_dir="/tmp/kokoro_sys_test", zh_g2p=g2p, sentence_pause=sp, clause_pause=cp)
    await b.initialize()
    payload = TTSTaskPayload(text=TEXT, voice_anchor=TTSVoiceAnchor(voice_id="zm_yunxi", language="zh"),
                             prosody=TTSProsody(rate=1.25))
    r = await b.synthesize(payload, Path(f"/tmp/kokoro_sys_test/{out}"))
    print(f"[{g2p} sp={sp} cp={cp}] {r.status} {r.duration_ms}ms")
    return r

async def main():
    await run("espeak", 0.25, 0.1, "reg_espeak.mp3")     # 期望 6122ms（基线不变）
    await run("misaki", 0.15, 0.05, "reg_misaki_p.mp3")  # pause 更短 → 时长应 < 5290ms 基线

asyncio.run(main())
