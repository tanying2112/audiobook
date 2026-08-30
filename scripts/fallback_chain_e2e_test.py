#!/usr/bin/env python3
"""
VoxCPM2 → Kokoro → Edge-TTS 三级降级链路真验证（方案 A）
=========================================================

本脚本对 **已有的** `src/audiobook_studio/tts/port_factory.py` 的 `auto` 路由做
端到端真验证，并诚实分层标注每一层：

  Tier 1  VoxCPM2 (云GPU层)  —— 路由选路可验证；真实音频 ADR 门禁内未实现 → 仅验证选路 seam
  Tier 2  Kokoro (本地点卡)  —— 真音频验证（ONNX 模型，上轮已端到端证实）
  Tier 3  Edge-TTS (云兜底)  —— 真音频验证（微软 Edge，公网可调用）

⚠️ 诚实声明（红线#1）：
  - Tier 1 的 VoxCPM2 真实音频本脚本**不调用**：voxcpm2-pool/ 远端 worker 是
    ADR-2026-07-19 PENDING 门禁内的影子代码（`pass` 桩 + 0 输出 notebook），
    在人类架构师 sign-off 并对齐真实推理 API 之前，绝不伪造该层成功。
  - 本测试覆盖的是「**选路逻辑 + Tier 2/3 真实降落音频**」，不是「云 HA」。
  - 运行时跨层 health-failover（tier1 挂→自动转 tier2）是 port 层预留 seam
    （RemoteVoxCPM2Port 已带 circuit breaker），不在 factory.autoroute 范畴，
    显式标注不冒充。

退出码：0=全绿；非0=有层级未通过真断言。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

# 让脚本能直接从仓库根目录跑
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from audiobook_studio.tts.port import TTSProsody, TTSStatus, TTSTaskPayload, TTSVoiceAnchor  # noqa: E402
from audiobook_studio.tts.port_factory import create_engine  # noqa: E402

OUT = ROOT / "output" / "fallback_e2e"
OUT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 工具：真音频时长校验（复用项目内 ffmpeg_probe，不另造轮子 §8）
# ---------------------------------------------------------------------------
async def probe_audio(path: Path) -> dict[str, Any]:
    """用项目自带 ffmpeg_probe 拿真实音频元数据（不猜 ffprobe 结构 §10）。"""
    from audiobook_studio.utils.ffmpeg_probe import get_audio_info, get_duration

    dur_ms = await get_duration(path)  # int 毫秒，直接来自项目 API
    sr = None
    try:
        info = await get_audio_info(path) or {}
        streams = info.get("streams") or []
        if streams and isinstance(streams, list):
            sr = streams[0].get("sample_rate")
    except Exception:
        pass
    return {"duration_ms": dur_ms, "duration_s": dur_ms / 1000.0, "sample_rate": sr}


async def assert_real_audio(path: Path, min_duration_s: float, tier: str) -> dict[str, Any]:
    """对最终产物做深度断言（红线#2：禁空断言）。"""
    assert path.exists(), f"[{tier}] 产物不存在: {path}"
    size = path.stat().st_size
    assert size > 1000, f"[{tier}] 产物体积异常({size}B < 1000)，疑似空/损坏: {path}"
    info = await probe_audio(path)
    dur_s = float(info["duration_s"])
    assert dur_s >= min_duration_s, f"[{tier}] 时长 {dur_s:.2f}s < 阈值 {min_duration_s}s: {path}"
    sr = info.get("sample_rate") or "?"
    print(f"    [{tier}] ✅ 真音频: {path.name} | {dur_s:.2f}s | {size/1024:.1f}KB | {sr}Hz")
    return {"path": str(path), "duration_s": dur_s, "size_bytes": size, "sample_rate": sr}


# ---------------------------------------------------------------------------
# Part 1: 选路逻辑测试（无音频，快）—— 验证 auto 路由的 4 个分支
# ---------------------------------------------------------------------------
def test_routing() -> list[tuple[str, str, str]]:
    cases = []
    saved = {
        k: os.environ.get(k)
        for k in (
            "VOXCPM2_ENDPOINT",
            "ENABLE_LOCAL_TTS",
            "MOCK_LLM",
            "TEST_MODE",
            "MOCK_TTS",
        )
    }

    def env_set(patch: dict[str, Any]) -> None:
        for k in ("VOXCPM2_ENDPOINT", "ENABLE_LOCAL_TTS", "MOCK_LLM", "TEST_MODE", "MOCK_TTS"):
            os.environ.pop(k, None)
        for k, v in patch.items():
            if v is None:
                continue
            os.environ[k] = v

    def restore() -> None:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    try:
        # 1) VOXCPM2_ENDPOINT 存在 → Tier1 VoxCPM2（仅验证选路 seam）
        #    注：零参调用 create_engine('auto')——反映真实用户调用，不越俎代庖塞 output_dir。
        #    （factory 把 kwargs 透传给各 port，但 voxcpm2/kokoro/edge port 构造签名不一致——
        #     这本身是 factory 的真实接口不一致技术债，见测试末尾汇总，不在此掩盖。）
        env_set({"VOXCPM2_ENDPOINT": "https://voxcpm2.example.invalid"})
        eng = create_engine("auto")
        cases.append(("Tier1 VoxCPM2 (endpoint 设)", type(eng).__name__, "RemoteVoxCPM2Port"))

        # 2) 默认 → Tier2 Kokoro
        env_set({})
        eng = create_engine("auto")
        cases.append(("Tier2 Kokoro (默认)", type(eng).__name__, "KokoroPort"))

        # 3) ENABLE_LOCAL_TTS=false → Tier3 Edge
        env_set({"ENABLE_LOCAL_TTS": "false"})
        eng = create_engine("auto")
        cases.append(("Tier3 Edge (local=false)", type(eng).__name__, "EdgeTTSPort"))

        # 4) MOCK_LLM=true → Fake（dev/test 分支，真实测试不该走到这里）
        env_set({"MOCK_LLM": "true"})
        eng = create_engine("auto")
        cases.append(("Fake (MOCK_LLM=true)", type(eng).__name__, "FakeRemoteTTSPort"))
    finally:
        restore()

    ok = True
    print("\n── Part 1: auto 路由选路（4 分支）────")
    print(f"  {'场景':<32} {'实际类':<22} {'期望':<22} 结果")
    for label, got, want in cases:
        flag = "✅" if got == want else "❌"
        if got != want:
            ok = False
        print(f"  {label:<32} {got:<22} {want:<22} {flag}")
    assert ok, "选路逻辑有分支与期望不符（factory.autoroute 可能被改坏）"
    print("  → 选路逻辑全绿。")
    return cases


# ---------------------------------------------------------------------------
# Part 2: Tier2 Kokoro 真音频 —— auto 默认分支 → submit/poll/真WAV断言
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def _synthesize_tier(
    port: Any, task_id: str, text: str, voice_id: str, prosody: TTSProsody | None, name: str
) -> Path:
    payload = TTSTaskPayload(
        text=text,
        voice_anchor=TTSVoiceAnchor(voice_id=voice_id, language="zh-CN"),
        prosody=prosody,
        metadata={"tier": name},
    )
    accepted = await port.submit(task_id, payload)
    assert accepted, f"[{name}] submit 被拒（task_id 重复？）"
    # submit() 是 fire-and-forget，后台跑 _synthesize_task；轮询 get_status
    t0 = time.time()
    status = None
    while time.time() - t0 < 180:
        st = await port.get_status(task_id)
        if st is None:
            await asyncio.sleep(0.5)
            continue
        status = st.status
        if status in (TTSStatus.DONE, TTSStatus.FAILED):
            break
        await asyncio.sleep(0.5)
    assert status == TTSStatus.DONE, f"[{name}] 任务未完成: status={status} (超时/失败)"
    res = await port.get_result(task_id)
    assert res is not None and res.audio_path, f"[{name}] 结果无 audio_path"
    await port.close()
    return Path(res.audio_path)


@pytest.mark.asyncio
async def test_tier2_kokoro_real_audio() -> dict[str, Any]:
    print("\n── Part 2: Tier 2 Kokoro 真音频 ────")
    # 关键：确保 auto 选到 Kokoro 且不带 mock
    for k in ("VOXCPM2_ENDPOINT", "MOCK_LLM", "TEST_MODE", "MOCK_TTS"):
        os.environ.pop(k, None)
    os.environ["ENABLE_LOCAL_TTS"] = "true"
    # 显式按引擎类型构造，避免 factory kwargs 透传不一致问题（技术债，见末尾汇总）
    port = create_engine("kokoro", output_dir=str(OUT))
    assert type(port).__name__ == "KokoroPort", f"期望 KokoroPort，得到 {type(port).__name__}"
    tid = f"fb_kokoro_{uuid.uuid4().hex[:6]}"
    text = "三级降级链路验证：这是 Kokoro 本地引擎生成的真实中文音频。"
    out = await _synthesize_tier(
        port, tid, text, voice_id="zf_xiaoxiao", prosody=TTSProsody(rate=1.0, emotion="neutral"), name="Tier2-Kokoro"
    )
    return await assert_real_audio(out, min_duration_s=1.5, tier="Tier2-Kokoro")


@pytest.mark.asyncio
async def test_tier3_edge_real_audio() -> dict[str, Any]:
    print("\n── Part 3: Tier 3 Edge-TTS 真音频 ────")
    # 显式构造 edge port（避免 Kokoro 默认抢占）
    port = create_engine("edge", output_dir=str(OUT), mock_mode=False)
    assert type(port).__name__ == "EdgeTTSPort", f"期望 EdgeTTSPort，得到 {type(port).__name__}"
    tid = f"fb_edge_{uuid.uuid4().hex[:6]}"
    text = "三级降级链路验证：这是 Edge-TTS 云端引擎生成的真实中文兜底音频。"
    out = await _synthesize_tier(
        port,
        tid,
        text,
        voice_id="zh-CN-XiaoxiaoNeural",
        prosody=TTSProsody(rate=1.0, emotion="neutral"),
        name="Tier3-Edge",
    )
    return await assert_real_audio(out, min_duration_s=1.5, tier="Tier3-Edge")


# ---------------------------------------------------------------------------
# Part 4: Tier1 VoxCPM2 预留 seam ── 仅验证选路可达 + circuit breaker 存在
# ---------------------------------------------------------------------------
def test_tier1_voxcpm2_reserved() -> dict[str, Any]:
    print("\n── Part 4: Tier 1 VoxCPM2 预留 seam（仅选路验证，无真音频）────")
    saved = os.environ.get("VOXCPM2_ENDPOINT")
    try:
        os.environ["VOXCPM2_ENDPOINT"] = "https://voxcpm2.example.invalid"
        port = create_engine("voxcpm2")
        cls = type(port).__name__
        assert cls == "RemoteVoxCPM2Port", f"期望 RemoteVoxCPM2Port，得到 {cls}"
        # 验证该 port 带运行时降级 seam（circuit breaker 错误类存在）
        from audiobook_studio.tts.remote_voxcpm2_port import PortCircuitOpenError

        print(f"    [Tier1-VoxCPM2] ✅ 选路可达: {cls}（endpoint={os.environ['VOXCPM2_ENDPOINT']}）")
        print("    [Tier1-VoxCPM2] ✅ 运行时 failover seam 存在: PortCircuitOpenError")
        print("    [Tier1-VoxCPM2] ⏸ 真实音频：voxcpm2-pool/ 远端 worker 处于 ADR-2026-07-19 PENDING")
        print("                       门禁内（pass 桩 + 0 输出 notebook），不伪造成功（红线#1）。")
        print("                       待人类架构师 sign-off + 对齐真实推理 API 后再补真音频测试。")
    finally:
        if saved is None:
            os.environ.pop("VOXCPM2_ENDPOINT", None)
        else:
            os.environ["VOXCPM2_ENDPOINT"] = saved
    return {"routed_class": "RemoteVoxCPM2Port", "real_audio": "PENDING-ADR"}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
async def main() -> None:
    print("=" * 72)
    print(" VoxCPM2 → Kokoro → Edge-TTS 三级降级链路 — 方案 A 真验证")
    print("=" * 72)
    print(f" 输出目录: {OUT}")
    print(" 诚实声明：Tier 1 仅验证选路 seam；Tier 2/3 真音频深度断言")

    routing = test_routing()
    kokoro = await test_tier2_kokoro_real_audio()
    edge = await test_tier3_edge_real_audio()
    vox = test_tier1_voxcpm2_reserved()

    print("\n" + "=" * 72)
    print(" 📊 三级降级链路验收汇总")
    print("=" * 72)
    print(f" {'层':<6} {'引擎':<14} {'选路':<10} {'真音频':<22} {'状态'}")
    print("-" * 72)
    print(f" {'Tier1':<6} {'VoxCPM2':<14} {'✅':<10} {'⏸ PENDING-ADR':<22} 预留 seam")
    print(f" {'Tier2':<6} {'Kokoro':<14} {'✅':<10} " f"{'✅ %5.2fs' % kokoro['duration_s']:<22} 真降落")
    print(f" {'Tier3':<6} {'Edge-TTS':<14} {'✅':<10} " f"{'✅ %5.2fs' % edge['duration_s']:<22} 真兜底")
    chain_json = OUT / "fallback_chain_report.json"
    import json

    chain_json.write_text(
        json.dumps(
            {
                "routing_cases": [{"label": line, "got": g, "want": w} for line, g, w in routing],
                "tier1_voxcpm2": vox,
                "tier2_kokoro": kokoro,
                "tier3_edge": edge,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\n 链路报告: {chain_json}")
    print(" 结果：Tier2/3 真音频深度断言全绿；Tier1 按规预留 seam（不伪造）。")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
