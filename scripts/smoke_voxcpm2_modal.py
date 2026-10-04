#!/usr/bin/env python3
"""
Test VoxCPM2 Modal endpoint after deployment.

Usage:
    python test_voxcpm2_modal.py --endpoint https://xxx.modal.run
    # Or set VOXCPM2_ENDPOINT env var
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

# Add src to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from audiobook_studio.tts.port import TTSTaskPayload, TTSProsody, TTSVoiceAnchor  # noqa: E402
from audiobook_studio.tts.remote_voxcpm2_port import (  # noqa: E402
    RemoteVoxCPM2Port,
    RemoteVoxCPM2PortConfig,
    create_remote_voxcpm2_port,
)


async def test_voxcpm2_endpoint(endpoint: str) -> None:
    """Test the deployed VoxCPM2 Modal endpoint."""

    print(f"Testing VoxCPM2 endpoint: {endpoint}")
    print("=" * 60)

    config = RemoteVoxCPM2PortConfig(
        endpoint=endpoint,
        timeout_sec=120.0,
        connect_timeout=10.0,
        read_timeout=120.0,
    )
    port = RemoteVoxCPM2Port(config)

    try:
        # Test health check
        print("\n1. Health check...")
        health = await port.health_check()
        print(f"   Health: {health}")
        if not health.get("healthy"):
            print("   ⚠️ Service reports unhealthy, but continuing...")

        # Test synthesis
        print("\n2. Submitting synthesis task...")
        task_id = f"test-{uuid.uuid4().hex[:8]}"
        payload = TTSTaskPayload(
            text="这是一个 VoxCPM2 云端推理测试，验证模型是否正常生成中文语音。",
            voice_anchor=TTSVoiceAnchor(voice_id="default", language="zh"),
            prosody=TTSProsody(rate=1.0, emotion="neutral"),
            metadata={"test": "modal-deployment"},
        )

        accepted = await port.submit(task_id, payload)
        print(f"   Submit accepted: {accepted}")

        if not accepted:
            print("   ❌ Task rejected")
            return

        # Poll for completion
        print("\n3. Polling for completion...")
        import time
        start = time.time()
        status = None
        while time.time() - start < 180:  # 3 min timeout
            st = await port.get_status(task_id)
            if st:
                status = st.status
                print(f"   Status: {status} (progress: {st.progress})")
                if status.value in ("DONE", "FAILED"):
                    break
            await asyncio.sleep(2)

        if status.value != "DONE":
            print(f"   ❌ Task did not complete successfully: {status}")
            return

        # Get result
        print("\n4. Retrieving result...")
        result = await port.get_result(task_id)
        print(f"   Result: {result}")
        print(f"   Audio path: {result.audio_path}")
        print(f"   Duration: {result.duration_ms}ms")

        if result.audio_path:
            # Verify audio file
            import soundfile as sf
            info = sf.info(result.audio_path)
            print(f"   Audio info: {info.duration:.2f}s, {info.samplerate}Hz, {info.channels}ch")
            print("   ✅ VoxCPM2 endpoint test PASSED")
        else:
            print("   ❌ No audio file in result")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await port.close()


def main():
    parser = argparse.ArgumentParser(description="Test VoxCPM2 Modal endpoint")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("VOXCPM2_ENDPOINT"),
        help="Modal endpoint URL (or set VOXCPM2_ENDPOINT env var)",
    )
    args = parser.parse_args()

    if not args.endpoint:
        parser.error("Endpoint required. Use --endpoint or set VOXCPM2_ENDPOINT")

    asyncio.run(test_voxcpm2_endpoint(args.endpoint))


if __name__ == "__main__":
    main()