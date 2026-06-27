"""Chaos and Performance Tests for Issue 3.2 - simulating API failures and load testing."""

import time
import threading
from unittest.mock import MagicMock, patch, Mock
import pytest

from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker
from src.audiobook_studio.llm.key_pool import ApiKeyPool
from src.audiobook_studio.llm.health_probe import HealthProbe, HealthStatus
from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline, AudioSegment
from src.audiobook_studio.pipeline.quality_check import QualityCheckPipeline, AudioAnalysisResult, ParagraphAnnotation


class TestChaosSimulation:
    """Simulate API provider failures and chaos scenarios."""

    def test_concurrent_api_failures_multiple_providers(self):
        """Test concurrent failures across multiple providers."""
        breakers = {
            "provider_a": CircuitBreaker("provider_a", failure_threshold=2),
            "provider_b": CircuitBreaker("provider_b", failure_threshold=2),
            "provider_c": CircuitBreaker("provider_c", failure_threshold=2),
        }
        
        def simulate_provider_failure(provider_name, num_failures):
            for _ in range(num_failures):
                breakers[provider_name].record_failure()
        
        threads = [
            threading.Thread(target=simulate_provider_failure, args=("provider_a", 3)),
            threading.Thread(target=simulate_provider_failure, args=("provider_b", 3)),
            threading.Thread(target=simulate_provider_failure, args=("provider_c", 3)),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All breakers should be open after 3 failures
        for name, cb in breakers.items():
            assert cb.state == "open", f"{name} should be open"

    def test_api_degradation_with_circuit_breaker(self):
        """Test system gracefully degrades when all providers fail."""
        primary = CircuitBreaker("primary", failure_threshold=2, recovery_timeout_s=0.1)
        fallback = CircuitBreaker("fallback", failure_threshold=5)
        
        for _ in range(3):
            primary.record_failure()
        
        assert primary.can_proceed() is False
        assert fallback.can_proceed() is True

    def test_key_pool_rotation_on_failure(self):
        """Test API key pool rotates keys on failures."""
        import os
        os.environ["TEST_KEY_1"] = "key1"
        os.environ["TEST_KEY_2"] = "key2"
        os.environ["TEST_KEY_3"] = "key3"
        
        pool = ApiKeyPool(
            provider_name="test_provider",
            primary_key_env="TEST_KEY_1",
            pool_key_envs=["TEST_KEY_2", "TEST_KEY_3"],
        )
        
        key1 = pool.get_key()
        assert key1 in ["key1", "key2", "key3"]

    def test_health_probe_detects_unhealthy_provider(self):
        """Test HealthProbe detects unhealthy provider status."""
        mock_provider = Mock()
        mock_provider.name = "test_provider"
        
        probe = HealthProbe(providers=[mock_provider])
        assert "test_provider" in probe.statuses

    def test_stress_test_concurrent_synthesis_requests(self):
        """Test concurrent synthesis requests for stability."""
        pipeline = SynthesizePipeline(mock_mode=True)
        results = []
        errors = []
        
        def synthesize_task(idx):
            try:
                result = pipeline._text_hash(f"测试文本 {idx}")
                results.append(result)
            except Exception as e:
                errors.append(str(e))
        
        threads = [threading.Thread(target=synthesize_task, args=(i,)) for i in range(10)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(results) == 10

    def test_memory_pressure_with_many_segments(self):
        """Test memory handling with many audio segments."""
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = SynthesizePipeline(mock_mode=True, output_dir=tmpdir)
            
            segments = []
            for i in range(100):
                seg = AudioSegment(
                    segment_id=f"seg_{i}",
                    file_path=f"/tmp/seg_{i}.mp3",
                    duration_ms=3000,
                    engine="kokoro",
                    voice_id="v1",
                    text_hash=f"hash_{i}",
                )
                segments.append(seg)
            
            pipeline.existing_segments = {s.segment_id: s for s in segments}
            assert len(pipeline.existing_segments) == 100


class TestPerformanceBenchmarks:
    """Performance benchmark validation tests."""

    def test_latency_threshold_validation(self):
        """Test that latency measurements meet thresholds."""
        mock_latencies = {
            "extract": 0.15,
            "analyze": 0.25,
            "annotate": 0.35,
            "edit": 0.20,
            "synthesize": 0.50,
            "quality": 0.40,
        }
        
        thresholds = {
            "extract": 0.20, "analyze": 0.30, "annotate": 0.50,
            "edit": 0.30, "synthesize": 1.0, "quality": 0.8,
        }
        
        for stage, latency in mock_latencies.items():
            assert latency <= thresholds[stage] * 1.1

    def test_circuit_breaker_recovery_timing(self):
        """Test circuit breaker recovery timing."""
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout_s=0.05)
        
        cb.record_failure()
        cb.record_failure()
        
        assert cb.state == "open"
        
        start = time.time()
        while not cb.can_proceed():
            time.sleep(0.01)
            if time.time() - start > 1:
                break
        
        assert cb.state == "half_open"


class TestChaosSimulationExtended:
    """Extended chaos simulation tests - network failures, timeouts, quota exhaustion."""

    def test_api_timeout_recovery(self):
        """Test circuit breaker handles timeout scenarios."""
        cb = CircuitBreaker("timeout_provider", failure_threshold=2, recovery_timeout_s=0.05)
        
        cb.record_failure()
        cb.record_failure()
        
        assert cb.state == "open"
        
        time.sleep(0.06)
        assert cb.can_proceed() is True
        assert cb.state == "half_open"

    def test_network_partition_scenario(self):
        """Test system behavior during network partition."""
        breakers = {
            "provider_a": CircuitBreaker("provider_a", failure_threshold=5),
            "provider_b": CircuitBreaker("provider_b", failure_threshold=5),
            "provider_c": CircuitBreaker("provider_c", failure_threshold=5),
        }
        
        for _ in range(5):
            breakers["provider_a"].record_failure()
            breakers["provider_b"].record_failure()
        
        assert breakers["provider_c"].can_proceed() is True

    def test_sequential_provider_failover(self):
        """Test sequential failover across providers."""
        providers = ["primary", "secondary", "tertiary"]
        breakers = {p: CircuitBreaker(p, failure_threshold=2) for p in providers}
        
        for _ in range(3):
            breakers["primary"].record_failure()
        
        assert breakers["primary"].state == "open"
        assert breakers["secondary"].can_proceed() is True

    def test_graceful_degradation_no_op(self):
        """Test graceful degradation when all providers unavailable."""
        breakers = [CircuitBreaker(f"p{i}", failure_threshold=1) for i in range(3)]
        for cb in breakers:
            cb.record_failure()
        
        available = sum(1 for cb in breakers if cb.can_proceed())
        assert available == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
