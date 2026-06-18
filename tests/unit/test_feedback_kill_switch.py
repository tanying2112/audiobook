"""Tests for feedback/kill_switch module."""

import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path

from src.audiobook_studio.feedback.kill_switch import (
    DegradationLevel,
    KillSwitchConfig,
    ProviderHealth,
    KillSwitch,
    get_kill_switch,
)


class TestDegradationLevel:
    """Tests for DegradationLevel enum."""

    def test_normal_value(self):
        assert DegradationLevel.NORMAL.value == "normal"

    def test_partial_value(self):
        assert DegradationLevel.PARTIAL.value == "partial"

    def test_degraded_value(self):
        assert DegradationLevel.DEGRADED.value == "degraded"

    def test_emergency_value(self):
        assert DegradationLevel.EMERGENCY.value == "emergency"


class TestKillSwitchConfig:
    """Tests for KillSwitchConfig dataclass."""

    def test_default_values(self):
        config = KillSwitchConfig()
        assert config.max_consecutive_failures == 5
        assert config.max_error_rate == 0.3
        assert config.max_cost_per_hour == 50.0
        assert config.fallback_to_rules is True
        assert config.fallback_to_cache is True
        assert config.health_check_interval_sec == 60
        assert config.llm_provider_health_file == "logs/llm_health.json"
        assert config.recovery_check_interval_sec == 300
        assert config.notify_on_trigger is True
        assert config.notify_on_recovery is True

    def test_custom_values(self):
        config = KillSwitchConfig(
            max_consecutive_failures=10,
            max_error_rate=0.5,
            fallback_to_rules=False,
        )
        assert config.max_consecutive_failures == 10
        assert config.max_error_rate == 0.5
        assert config.fallback_to_rules is False


class TestProviderHealth:
    """Tests for ProviderHealth dataclass."""

    def test_default_values(self):
        health = ProviderHealth(provider="test-provider")
        assert health.provider == "test-provider"
        assert health.is_alive is True
        assert health.consecutive_failures == 0
        assert health.total_calls == 0
        assert health.failed_calls == 0
        assert health.last_error is None
        assert health.last_checked is None

    def test_error_rate_no_calls(self):
        health = ProviderHealth(provider="test")
        assert health.error_rate == 0.0

    def test_error_rate_with_calls(self):
        health = ProviderHealth(provider="test", total_calls=10, failed_calls=3)
        assert health.error_rate == 0.3

    def test_is_degraded_consecutive_failures(self):
        health = ProviderHealth(provider="test", consecutive_failures=3)
        assert health.is_degraded is True

    def test_is_degraded_error_rate(self):
        health = ProviderHealth(provider="test", total_calls=10, failed_calls=3)
        assert health.is_degraded is True

    def test_is_degraded_false(self):
        health = ProviderHealth(provider="test", consecutive_failures=1, total_calls=10, failed_calls=1)
        assert health.is_degraded is False


class TestKillSwitch:
    """Tests for KillSwitch class."""

    @patch("pathlib.Path.exists")
    def test_init_default_config(self, mock_exists):
        mock_exists.return_value = False  # Mock file not existing
        ks = KillSwitch()
        assert ks.config is not None
        assert isinstance(ks.config, KillSwitchConfig)
        assert ks.level == DegradationLevel.NORMAL
        assert ks.providers == {}
        assert ks.rule_cache == {}

    def test_init_custom_config(self):
        config = KillSwitchConfig(max_consecutive_failures=3)
        ks = KillSwitch(config=config)
        assert ks.config.max_consecutive_failures == 3

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.read_text")
    @patch("yaml.safe_load")
    def test_load_rule_cache_voice_mapping(self, mock_yaml_load, mock_read_text, mock_exists):
        mock_exists.return_value = True
        mock_read_text.return_value = "voice_mapping:\n  speaker1:\n    engine: edge-tts\n"
        mock_yaml_load.return_value = {"speaker1": {"engine": "edge-tts"}}

        ks = KillSwitch()
        assert "voice_mapping" in ks.rule_cache
        assert ks.rule_cache["voice_mapping"] == {"speaker1": {"engine": "edge-tts"}}

    @patch("pathlib.Path.exists")
    def test_load_rule_cache_file_not_exists(self, mock_exists):
        mock_exists.return_value = False

        ks = KillSwitch()
        # Should not crash, just have empty cache
        assert ks.rule_cache == {}

    def test_record_call_success_first_call(self):
        ks = KillSwitch()
        health = ks.record_call("provider1", success=True)

        assert health.provider == "provider1"
        assert health.total_calls == 1
        assert health.failed_calls == 0
        assert health.consecutive_failures == 0
        assert health.is_alive is True
        assert ks.level == DegradationLevel.NORMAL

    def test_record_call_failure_first_call(self):
        ks = KillSwitch()
        health = ks.record_call("provider1", success=False, error="timeout")

        assert health.total_calls == 1
        assert health.failed_calls == 1
        assert health.consecutive_failures == 1
        assert health.last_error == "timeout"

    def test_record_call_multiple_failures_triggers_partial(self):
        ks = KillSwitch()
        for _ in range(3):
            ks.record_call("provider1", success=False, error="error")

        health = ks.providers["provider1"]
        assert health.consecutive_failures == 3
        assert health.is_degraded is True
        assert ks.level == DegradationLevel.PARTIAL

    def test_record_call_all_providers_dead_triggers_emergency(self):
        ks = KillSwitch()
        # Make two providers completely dead
        for _ in range(5):
            ks.record_call("provider1", success=False)
        for _ in range(5):
            ks.record_call("provider2", success=False)

        assert ks.level == DegradationLevel.EMERGENCY

    def test_record_call_mixed_providers(self):
        ks = KillSwitch()
        # provider1: 2 failures (degraded)
        ks.record_call("provider1", success=False)
        ks.record_call("provider1", success=False)
        # provider2: success
        ks.record_call("provider2", success=True)

        # 1 out of 2 providers degraded = 50% -> DEGRADED level
        assert ks.level == DegradationLevel.DEGRADED

    def test_record_call_recovery_after_failures(self):
        ks = KillSwitch()
        # Fail 3 times
        for _ in range(3):
            ks.record_call("provider1", success=False)
        assert ks.providers["provider1"].consecutive_failures == 3

        # Then succeed multiple times to bring error rate below 20%
        for _ in range(15):
            ks.record_call("provider1", success=True)
        health = ks.providers["provider1"]
        assert health.consecutive_failures == 0
        assert health.error_rate < 0.2  # Error rate now below threshold
        assert ks.level == DegradationLevel.NORMAL

    def test_should_fallback_emergency_level(self):
        ks = KillSwitch()
        # Force emergency by killing all providers
        ks.record_call("p1", success=False)
        ks.record_call("p2", success=False)
        for _ in range(4):
            ks.record_call("p1", success=False)
            ks.record_call("p2", success=False)

        assert ks.level == DegradationLevel.EMERGENCY
        assert ks.should_fallback() is True

    def test_should_fallback_specific_provider_consecutive_failures(self):
        ks = KillSwitch()
        config = KillSwitchConfig(max_consecutive_failures=3, max_error_rate=1.0)
        ks.config = config

        ks.record_call("provider1", success=False)
        ks.record_call("provider1", success=False)
        # Not yet at threshold
        assert ks.should_fallback("provider1") is False

        ks.record_call("provider1", success=False)
        # Now at threshold (3)
        assert ks.should_fallback("provider1") is True

    def test_should_fallback_specific_provider_error_rate(self):
        ks = KillSwitch()
        config = KillSwitchConfig(max_error_rate=0.3)
        ks.config = config

        # 10 calls, 4 failures = 40% error rate (> 30%)
        for _ in range(6):
            ks.record_call("provider1", success=True)
        for _ in range(4):
            ks.record_call("provider1", success=False)

        assert ks.should_fallback("provider1") is True

    def test_should_fallback_unknown_provider(self):
        ks = KillSwitch()
        assert ks.should_fallback("unknown") is False

    def test_should_fallback_normal_level(self):
        ks = KillSwitch()
        ks.record_call("provider1", success=True)
        assert ks.should_fallback() is False

    def test_get_fallback_response_edit_for_tts(self):
        ks = KillSwitch()
        input_data = {"text": "Hello world"}
        result = ks.get_fallback_response("edit_for_tts", input_data)

        assert result is not None
        assert result["edited_text"] == "Hello world"
        assert result["changes_made"] == []
        assert result["forbidden_content_removed"] is False
        assert result["confidence"] == 0.3
        assert "纯规则降级" in result["rationale"]
        assert result["difficulty"] == "medium"
        assert result["forbid_edit"] is False

    def test_get_fallback_response_tts_routing(self):
        ks = KillSwitch()
        # Mock rule_cache with voice mapping
        ks.rule_cache["voice_mapping"] = {
            "narrator": {"engine": "azure", "voice_id": "zh-CN-YunyangNeural", "rate": 10}
        }

        input_data = {"character_name": "narrator"}
        result = ks.get_fallback_response("tts_routing", input_data)

        assert result is not None
        assert result["engine"] == "azure"
        assert result["voice_id"] == "zh-CN-YunyangNeural"
        assert result["prosody"]["rate"] == 10
        assert result["confidence"] == 0.5
        assert "纯规则降级" in result["rationale"]

    def test_get_fallback_response_tts_routing_default(self):
        ks = KillSwitch()
        ks.rule_cache = {}  # No voice mapping

        input_data = {"character_name": "unknown"}
        result = ks.get_fallback_response("tts_routing", input_data)

        assert result["engine"] == "edge-tts"
        assert result["voice_id"] == "zh-CN-XiaoxiaoNeural"
        assert result["prosody"]["rate"] == 0

    def test_get_fallback_response_annotate_paragraph(self):
        ks = KillSwitch()
        input_data = {"text": "Some text"}
        result = ks.get_fallback_response("annotate_paragraph", input_data)

        assert result is not None
        assert result["speaker_canonical_name"] == "unknown"
        assert result["is_dialogue"] is False
        assert result["emotion"] == "neutral"
        assert result["emotion_intensity"] == 0.5
        assert result["pause_before_ms"] == 200
        assert result["pause_after_ms"] == 100
        assert result["confidence"] == 0.3
        assert "纯规则降级" in result["notes"]

    def test_get_fallback_response_quality_judge(self):
        ks = KillSwitch()
        input_data = {"segment_id": "seg-123"}
        result = ks.get_fallback_response("quality_judge", input_data)

        assert result is not None
        assert result["segment_id"] == "seg-123"
        assert result["speaker_clarity"] == 0.8
        assert result["emotion_match"] == 0.8
        assert result["prosody_naturalness"] == 0.8
        assert result["text_audio_alignment"] == 0.8
        assert result["overall_score"] == 0.8
        assert result["issues"] == []
        assert result["fix_suggestions"] == []
        assert result["needs_regeneration"] is False
        assert result["judge_model"] == "rule_fallback"
        assert result["contract_version"] == 1

    def test_get_fallback_response_unknown_stage(self):
        ks = KillSwitch()
        result = ks.get_fallback_response("unknown_stage", {})
        assert result is None

    def test_get_fallback_response_disabled(self):
        ks = KillSwitch()
        ks.config.fallback_to_rules = False
        ks.config.fallback_to_cache = False

        result = ks.get_fallback_response("edit_for_tts", {})
        assert result is None

    def test_check_recovery(self):
        ks = KillSwitch()
        # Make provider dead
        ks.record_call("provider1", success=False)
        ks.record_call("provider1", success=False)
        ks.record_call("provider1", success=False)
        ks.providers["provider1"].is_alive = False

        recovered = ks.check_recovery()

        assert recovered is True
        assert ks.providers["provider1"].is_alive is True
        assert ks.providers["provider1"].consecutive_failures == 0
        assert ks.level == DegradationLevel.NORMAL

    def test_check_recovery_no_dead_providers(self):
        ks = KillSwitch()
        ks.record_call("provider1", success=True)

        recovered = ks.check_recovery()
        assert recovered is False

    def test_get_status_report(self):
        ks = KillSwitch()
        ks.record_call("provider1", success=True)
        ks.record_call("provider1", success=False)
        ks.record_call("provider2", success=True)

        report = ks.get_status_report()

        # Provider1 has 50% error rate (>20% threshold) -> degraded
        # 1 of 2 providers degraded -> DEGRADED level
        assert report["level"] == "degraded"
        assert "provider1" in report["providers"]
        assert "provider2" in report["providers"]
        assert report["providers"]["provider1"]["total_calls"] == 2
        assert report["providers"]["provider1"]["failed_calls"] == 1
        assert report["providers"]["provider1"]["error_rate"] == "50.0%"
        assert report["config"]["max_consecutive_failures"] == 5
        assert report["config"]["max_error_rate"] == 0.3

    def test_get_status_report_empty(self):
        ks = KillSwitch()
        report = ks.get_status_report()

        assert report["level"] == "normal"
        assert report["providers"] == {}


class TestGetKillSwitch:
    """Tests for get_kill_switch singleton."""

    def test_singleton_returns_same_instance(self):
        # Reset global for clean test
        import src.audiobook_studio.feedback.kill_switch as ks_module
        ks_module._kill_switch = None

        ks1 = get_kill_switch()
        ks2 = get_kill_switch()

        assert ks1 is ks2

    def test_singleton_initializes_with_defaults(self):
        import src.audiobook_studio.feedback.kill_switch as ks_module
        ks_module._kill_switch = None

        ks = get_kill_switch()
        assert isinstance(ks, KillSwitch)
        assert ks.level == DegradationLevel.NORMAL


class TestKillSwitchIntegration:
    """Integration-style tests for KillSwitch behavior."""

    def test_full_degradation_cycle(self):
        """Test complete cycle: normal -> partial -> degraded -> emergency -> recovery."""
        # Use config with max_consecutive_failures=4 so 3 failures = degraded but alive
        config = KillSwitchConfig(max_consecutive_failures=4, max_error_rate=1.0)
        ks = KillSwitch(config=config)

        # Normal
        ks.record_call("p1", success=True)
        assert ks.level == DegradationLevel.NORMAL

        # Partial - one provider degraded (3 failures < 4 threshold)
        for _ in range(3):
            ks.record_call("p1", success=False)
        assert ks.level == DegradationLevel.PARTIAL

        # Degraded - half providers degraded
        for _ in range(3):
            ks.record_call("p2", success=False)
        assert ks.level == DegradationLevel.DEGRADED

        # Emergency - all providers dead (4 failures each with max_consecutive_failures=4)
        ks.record_call("p1", success=False)  # 4th failure -> dead
        ks.record_call("p2", success=False)  # 4th failure -> dead
        for _ in range(4):
            ks.record_call("p3", success=False)  # 4 failures -> dead
        assert ks.level == DegradationLevel.EMERGENCY
        assert ks.should_fallback() is True

        # Recovery
        ks.check_recovery()
        assert ks.level == DegradationLevel.NORMAL

    def test_fallback_responses_for_all_stages(self):
        """Test that all pipeline stages have fallback responses."""
        ks = KillSwitch()
        ks.config.fallback_to_rules = True

        stages = ["edit_for_tts", "tts_routing", "annotate_paragraph", "quality_judge"]
        for stage in stages:
            result = ks.get_fallback_response(stage, {})
            assert result is not None, f"Stage {stage} should have fallback"
            assert "rationale" in result or "notes" in result
            assert "confidence" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])