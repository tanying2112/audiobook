#!/usr/bin/env python3
"""
v0.4 Deployment Verification Script

Tests all v0.4 endpoints after deployment to Modal/Kaggle:
- Streaming TTS (CosyVoice, Seed-TTS, MeloTTS)
- Zero-Shot Clone (XTTS-v2, OpenVoice V2, CosyVoice Clone)
- VoxCPM2 Remote TTS

Usage:
    python scripts/verify_v04_deployment.py --endpoints endpoints.json
    python scripts/verify_v04_deployment.py --cosyvoice-stream https://xxx.trycloudflare.com --xtts-v2 https://yyy.trycloudflare.com ...
"""

import argparse
import asyncio
import json
import sys
import time
import base64
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

import httpx


@dataclass
class EndpointConfig:
    """Configuration for a single endpoint."""
    name: str
    url: str
    type: str  # "streaming", "clone", "voxcpm2"


@dataclass
class TestResult:
    """Result of a single test."""
    test_id: str
    engine: str
    endpoint: str
    passed: bool
    latency_ms: float
    details: Dict[str, Any]
    error: Optional[str] = None


class V04Verifier:
    """Verifies v0.4 deployment endpoints."""

    def __init__(self, endpoints: List[EndpointConfig], timeout: float = 120.0):
        self.endpoints = {e.name: e for e in endpoints}
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
        self.results: List[TestResult] = []

    async def close(self):
        await self.client.aclose()

    def _find_endpoint(self, engine: str) -> Optional[EndpointConfig]:
        """Find endpoint for engine."""
        # Direct match
        if engine in self.endpoints:
            return self.endpoints[engine]
        # Try with _stream suffix for streaming engines
        if engine.endswith("_stream"):
            base = engine.replace("_stream", "")
            if base in self.endpoints:
                return self.endpoints[base]
        return None

    async def test_health(self, engine: str) -> TestResult:
        """Test health endpoint."""
        endpoint = self._find_endpoint(engine)
        if not endpoint:
            return TestResult(
                test_id=f"health_{engine}",
                engine=engine,
                endpoint="NOT_CONFIGURED",
                passed=False,
                latency_ms=0,
                details={},
                error=f"No endpoint configured for {engine}"
            )

        start = time.time()
        try:
            url = f"{endpoint.url}/health"
            resp = await self.client.get(url)
            latency = (time.time() - start) * 1000

            if resp.status_code == 200:
                data = resp.json()
                return TestResult(
                    test_id=f"health_{engine}",
                    engine=engine,
                    endpoint=endpoint.url,
                    passed=data.get("healthy", False),
                    latency_ms=latency,
                    details=data
                )
            else:
                return TestResult(
                    test_id=f"health_{engine}",
                    engine=engine,
                    endpoint=endpoint.url,
                    passed=False,
                    latency_ms=latency,
                    details={"status_code": resp.status_code},
                    error=f"Health check failed: {resp.status_code}"
                )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return TestResult(
                test_id=f"health_{engine}",
                engine=engine,
                endpoint=endpoint.url,
                passed=False,
                latency_ms=latency,
                details={},
                error=str(e)
            )

    async def test_streaming_tts(self, engine: str, text: str, language: str = "zh",
                                  max_latency_ms: float = 300) -> TestResult:
        """Test streaming TTS endpoint."""
        endpoint = self._find_endpoint(engine)
        if not endpoint:
            return TestResult(
                test_id=f"stream_{engine}",
                engine=engine,
                endpoint="NOT_CONFIGURED",
                passed=False,
                latency_ms=0,
                details={},
                error=f"No endpoint configured for {engine}"
            )

        start = time.time()
        first_chunk_latency = None
        chunk_count = 0
        total_audio_bytes = 0

        try:
            url = f"{endpoint.url}/tts/stream"
            payload = {
                "text": text,
                "voice_id": "default",
                "speed": 1.0,
                "sample_rate": 24000,
                "chunk_size_ms": 100,
            }
            if language:
                payload["language"] = language

            async with self.client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    return TestResult(
                        test_id=f"stream_{engine}",
                        engine=engine,
                        endpoint=endpoint.url,
                        passed=False,
                        latency_ms=(time.time() - start) * 1000,
                        details={"status_code": resp.status_code},
                        error=f"Stream request failed: {resp.status_code}"
                    )

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if first_chunk_latency is None:
                        first_chunk_latency = (time.time() - start) * 1000
                    try:
                        chunk = json.loads(line)
                        chunk_count += 1
                        if "audio_hex" in chunk:
                            total_audio_bytes += len(chunk["audio_hex"]) // 2  # hex -> bytes
                        if chunk.get("is_final"):
                            break
                    except json.JSONDecodeError:
                        pass

            latency = (time.time() - start) * 1000
            passed = (
                first_chunk_latency is not None and
                first_chunk_latency <= max_latency_ms and
                chunk_count > 0
            )

            return TestResult(
                test_id=f"stream_{engine}_{language}",
                engine=engine,
                endpoint=endpoint.url,
                passed=passed,
                latency_ms=latency,
                details={
                    "first_chunk_latency_ms": first_chunk_latency,
                    "chunk_count": chunk_count,
                    "total_audio_bytes": total_audio_bytes,
                    "max_allowed_latency_ms": max_latency_ms
                },
                error=None if passed else f"First chunk latency {first_chunk_latency:.0f}ms > {max_latency_ms}ms"
            )

        except Exception as e:
            latency = (time.time() - start) * 1000
            return TestResult(
                test_id=f"stream_{engine}_{language}",
                engine=engine,
                endpoint=endpoint.url,
                passed=False,
                latency_ms=latency,
                details={},
                error=str(e)
            )

    async def test_zero_shot_clone(self, engine: str, text: str, reference_audio_b64: str,
                                    language: str = "zh", speed: float = 1.0,
                                    min_similarity: float = 0.80) -> TestResult:
        """Test zero-shot clone endpoint."""
        endpoint = self._find_endpoint(engine)
        if not endpoint:
            return TestResult(
                test_id=f"clone_{engine}",
                engine=engine,
                endpoint="NOT_CONFIGURED",
                passed=False,
                latency_ms=0,
                details={},
                error=f"No endpoint configured for {engine}"
            )

        start = time.time()
        try:
            url = f"{endpoint.url}/clone"
            # Handle CosyVoice's prompt_audio vs reference_audio
            if engine == "cosyvoice_clone":
                payload = {
                    "text": text,
                    "prompt_audio": reference_audio_b64,
                    "language": language,
                    "speed": speed,
                    "sample_rate": 24000,
                }
            else:
                payload = {
                    "text": text,
                    "reference_audio": reference_audio_b64,
                    "language": language,
                    "speed": speed,
                    "sample_rate": 24000,
                }

            resp = await self.client.post(url, json=payload)
            latency = (time.time() - start) * 1000

            if resp.status_code != 200:
                return TestResult(
                    test_id=f"clone_{engine}_{language}",
                    engine=engine,
                    endpoint=endpoint.url,
                    passed=False,
                    latency_ms=latency,
                    details={"status_code": resp.status_code},
                    error=f"Clone request failed: {resp.status_code}"
                )

            data = resp.json()
            similarity = data.get("similarity", 0)
            passed = similarity >= min_similarity

            return TestResult(
                test_id=f"clone_{engine}_{language}",
                engine=engine,
                endpoint=endpoint.url,
                passed=passed,
                latency_ms=latency,
                details={
                    "similarity": similarity,
                    "latency_ms": data.get("latency_ms"),
                    "sample_rate": data.get("sample_rate"),
                    "min_required_similarity": min_similarity,
                    "audio_size_bytes": len(data.get("audio_base64", "")) * 3 // 4
                },
                error=None if passed else f"Similarity {similarity:.2f} < {min_similarity}"
            )

        except Exception as e:
            latency = (time.time() - start) * 1000
            return TestResult(
                test_id=f"clone_{engine}_{language}",
                engine=engine,
                endpoint=endpoint.url,
                passed=False,
                latency_ms=latency,
                details={},
                error=str(e)
            )

    async def test_voxcpm2(self, text: str, voice_id: str = "zh_female_1",
                            expected_rtf: float = 0.1) -> TestResult:
        """Test VoxCPM2 remote TTS."""
        endpoint = self.endpoints.get("voxcpm2")
        if not endpoint:
            return TestResult(
                test_id="voxcpm2_synthesis",
                engine="voxcpm2",
                endpoint="NOT_CONFIGURED",
                passed=False,
                latency_ms=0,
                details={},
                error="No voxcpm2 endpoint configured"
            )

        start = time.time()
        try:
            # Submit task
            task_id = f"verify-{uuid.uuid4().hex[:8]}"
            payload = {
                "task_id": task_id,
                "text": text,
                "voice_id": voice_id,
                "language": "zh",
                "prosody": {"cfg_value": 2.0, "inference_timesteps": 10}
            }

            resp = await self.client.post(f"{endpoint.url}/synthesize", json=payload)
            if resp.status_code != 200:
                return TestResult(
                    test_id="voxcpm2_synthesis",
                    engine="voxcpm2",
                    endpoint=endpoint.url,
                    passed=False,
                    latency_ms=(time.time() - start) * 1000,
                    details={"status_code": resp.status_code},
                    error=f"Submit failed: {resp.status_code}"
                )

            # Poll for completion
            max_wait = 120
            poll_start = time.time()
            while time.time() - poll_start < max_wait:
                await asyncio.sleep(2)
                status_resp = await self.client.get(f"{endpoint.url}/status/{task_id}")
                if status_resp.status_code == 200:
                    status = status_resp.json()
                    if status.get("status") == "DONE":
                        break
                    elif status.get("status") == "FAILED":
                        return TestResult(
                            test_id="voxcpm2_synthesis",
                            engine="voxcpm2",
                            endpoint=endpoint.url,
                            passed=False,
                            latency_ms=(time.time() - start) * 1000,
                            details=status,
                            error=f"Task failed: {status.get('error_message')}"
                        )

            # Get result
            result_resp = await self.client.get(f"{endpoint.url}/result/{task_id}")
            latency = (time.time() - start) * 1000

            if result_resp.status_code != 200:
                return TestResult(
                    test_id="voxcpm2_synthesis",
                    engine="voxcpm2",
                    endpoint=endpoint.url,
                    passed=False,
                    latency_ms=latency,
                    details={"status_code": result_resp.status_code},
                    error=f"Get result failed: {result_resp.status_code}"
                )

            result = result_resp.json()
            duration_ms = result.get("duration_ms", 0)
            rtf = latency / duration_ms if duration_ms > 0 else 999
            passed = rtf <= expected_rtf * 2  # Allow 2x margin for network

            return TestResult(
                test_id="voxcpm2_synthesis",
                engine="voxcpm2",
                endpoint=endpoint.url,
                passed=passed,
                latency_ms=latency,
                details={
                    "duration_ms": duration_ms,
                    "rtf": rtf,
                    "expected_rtf": expected_rtf,
                    "audio_url": result.get("audio_url")
                },
                error=None if passed else f"RTF {rtf:.3f} > {expected_rtf * 2:.3f}"
            )

        except Exception as e:
            latency = (time.time() - start) * 1000
            return TestResult(
                test_id="voxcpm2_synthesis",
                engine="voxcpm2",
                endpoint=endpoint.url,
                passed=False,
                latency_ms=latency,
                details={},
                error=str(e)
            )

    async def run_all_tests(self, golden_dataset_path: str) -> Dict:
        """Run all verification tests from golden dataset."""
        with open(golden_dataset_path) as f:
            dataset = json.load(f)

        print(f"\n{'='*60}")
        print(f"v0.4 Deployment Verification")
        print(f"Dataset: {dataset['version']}")
        print(f"Target MOS: {dataset['target_mos']}")
        print(f"Test cases: {len(dataset['test_cases'])}")
        print(f"Configured endpoints: {list(self.endpoints.keys())}")
        print(f"{'='*60}\n")

        # Health checks first
        print("🔍 Health Checks...")
        all_engines = set()
        for tc in dataset["test_cases"]:
            all_engines.update(tc.get("engines", []))

        for engine in sorted(all_engines):
            result = await self.test_health(engine)
            self.results.append(result)
            status = "✅" if result.passed else "❌"
            print(f"  {status} {engine}: {result.latency_ms:.0f}ms - {result.error or 'OK'}")

        # Run test cases
        print("\n🧪 Running Test Cases...")
        for i, tc in enumerate(dataset["test_cases"], 1):
            test_id = tc["id"]
            engines = tc.get("engines", [])

            print(f"\n  [{i}/{len(dataset['test_cases'])}] {test_id}: {tc['description']}")

            if "streaming" in test_id or "Streaming" in tc["description"]:
                for engine in engines:
                    if engine in self.endpoints:
                        result = await self.test_streaming_tts(
                            engine, tc["text"], tc.get("language", "zh"),
                            tc.get("max_first_chunk_latency_ms", 300)
                        )
                        self.results.append(result)
                        status = "✅" if result.passed else "❌"
                        print(f"    {status} {engine}: {result.details.get('first_chunk_latency_ms', 0):.0f}ms "
                              f"({result.details.get('chunk_count', 0)} chunks)")

            elif "clone" in test_id or "Zero-shot" in tc["description"] or "cross_lingual" in test_id:
                # Need reference audio - generate mock if not available
                ref_audio = tc.get("reference_audio", "")
                if ref_audio and Path(ref_audio).exists():
                    with open(ref_audio, "rb") as f:
                        ref_b64 = base64.b64encode(f.read()).decode()
                else:
                    # Generate mock reference audio
                    import numpy as np
                    import soundfile as sf
                    import io
                    sr = 24000
                    duration = tc.get("reference_duration_sec", 3)
                    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
                    audio = np.sin(2 * np.pi * 330 * t) * 0.3
                    audio_int16 = (audio * 32767).astype(np.int16)
                    buf = io.BytesIO()
                    sf.write(buf, audio_int16, sr, format="WAV")
                    ref_b64 = base64.b64encode(buf.getvalue()).decode()

                for engine in engines:
                    if engine in self.endpoints:
                        result = await self.test_zero_shot_clone(
                            engine, tc["target_text"], ref_b64,
                            tc.get("target_language", "zh"),
                            min_similarity=tc.get("expected_speaker_similarity", 0.80)
                        )
                        self.results.append(result)
                        status = "✅" if result.passed else "❌"
                        print(f"    {status} {engine}: sim={result.details.get('similarity', 0):.2f} "
                              f"latency={result.details.get('latency_ms', 0):.0f}ms")

            elif "voxcpm2" in test_id:
                if "voxcpm2" in self.endpoints:
                    result = await self.test_voxcpm2(
                        tc["text"], tc.get("voice_id", "zh_female_1"),
                        tc.get("expected_rtf", 0.1)
                    )
                    self.results.append(result)
                    status = "✅" if result.passed else "❌"
                    print(f"    {status} voxcpm2: RTF={result.details.get('rtf', 0):.3f} "
                          f"duration={result.details.get('duration_ms', 0)}ms")

        # Summary
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        print(f"\n{'='*60}")
        print(f"SUMMARY: {passed}/{total} tests passed")
        print(f"{'='*60}")

        # Group by engine
        by_engine = {}
        for r in self.results:
            if r.engine not in by_engine:
                by_engine[r.engine] = {"passed": 0, "total": 0}
            by_engine[r.engine]["total"] += 1
            if r.passed:
                by_engine[r.engine]["passed"] += 1

        print("\nPer-engine breakdown:")
        for engine, stats in sorted(by_engine.items()):
            pct = stats["passed"] / stats["total"] * 100 if stats["total"] > 0 else 0
            print(f"  {engine}: {stats['passed']}/{stats['total']} ({pct:.0f}%)")

        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "by_engine": by_engine,
            "results": [asdict(r) for r in self.results]
        }


async def main():
    parser = argparse.ArgumentParser(description="Verify v0.4 deployment")
    parser.add_argument("--endpoints", help="JSON file with endpoint configs")
    parser.add_argument("--cosyvoice-stream", help="CosyVoice Stream endpoint URL")
    parser.add_argument("--seed-tts-stream", help="Seed-TTS Stream endpoint URL")
    parser.add_argument("--melotts-stream", help="MeloTTS Stream endpoint URL")
    parser.add_argument("--xtts-v2", help="XTTS-v2 endpoint URL")
    parser.add_argument("--openvoice-v2", help="OpenVoice V2 endpoint URL")
    parser.add_argument("--cosyvoice-clone", help="CosyVoice Clone endpoint URL")
    parser.add_argument("--voxcpm2", help="VoxCPM2 endpoint URL")
    parser.add_argument("--golden-dataset", default="tests/golden/v04_multilingual/test_cases.json")
    parser.add_argument("--output", help="Output JSON file for results")
    parser.add_argument("--timeout", type=float, default=120.0)

    args = parser.parse_args()

    # Build endpoint list
    endpoints = []

    if args.endpoints:
        with open(args.endpoints) as f:
            data = json.load(f)
            for e in data.get("endpoints", []):
                endpoints.append(EndpointConfig(**e))
    else:
        # From command line args
        if args.cosyvoice_stream:
            endpoints.append(EndpointConfig("cosyvoice_stream", args.cosyvoice_stream, "streaming"))
        if args.seed_tts_stream:
            endpoints.append(EndpointConfig("seed_tts_stream", args.seed_tts_stream, "streaming"))
        if args.melotts_stream:
            endpoints.append(EndpointConfig("melotts_stream", args.melotts_stream, "streaming"))
        if args.xtts_v2:
            endpoints.append(EndpointConfig("xtts_v2", args.xtts_v2, "clone"))
        if args.openvoice_v2:
            endpoints.append(EndpointConfig("openvoice_v2", args.openvoice_v2, "clone"))
        if args.cosyvoice_clone:
            endpoints.append(EndpointConfig("cosyvoice_clone", args.cosyvoice_clone, "clone"))
        if args.voxcpm2:
            endpoints.append(EndpointConfig("voxcpm2", args.voxcpm2, "voxcpm2"))

    if not endpoints:
        print("❌ No endpoints configured. Use --endpoints or individual --xxx flags.")
        sys.exit(1)

    verifier = V04Verifier(endpoints, timeout=args.timeout)
    try:
        results = await verifier.run_all_tests(args.golden_dataset)
    finally:
        await verifier.close()

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n📄 Results saved to {args.output}")

    # Exit code based on pass rate
    pass_rate = results["passed"] / results["total"] if results["total"] > 0 else 0
    if pass_rate < 0.5:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
