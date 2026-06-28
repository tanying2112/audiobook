"""LLM 模块综合测试 — 覆盖 circuit_breaker, key_pool, quota_registry,
health_probe, utils, judge, router 核心逻辑。"""

import json
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

# ===========================================================================
# circuit_breaker
# ===========================================================================


class TestCircuitBreaker:
    def test_default_state_closed(self):
        """新断路器默认为 closed（允许通过）。"""
        from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(provider_name="test")
        assert cb.state == "closed"
        assert cb.can_proceed() is True

    def test_open_after_threshold(self):
        """连续失败达到阈值后断路器变为 open。"""
        from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(provider_name="test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.can_proceed() is False

    def test_half_open_after_cooldown(self):
        """冷却时间过后断路器变为 half_open。"""
        from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(
            provider_name="test",
            failure_threshold=2,
            recovery_timeout_s=0.01,
        )
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.02)
        assert cb.can_proceed() is True
        assert cb.state == "half_open"

    def test_success_in_half_open_closes(self):
        """half_open 状态下成功调用将断路器重置为 closed。"""
        from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(
            provider_name="test",
            failure_threshold=1,
            recovery_timeout_s=0.01,
        )
        cb.record_failure()
        time.sleep(0.02)
        cb.can_proceed()  # → half_open
        cb.record_success()
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_failure_in_half_open_reopens(self):
        """half_open 状态下失败将断路器重新打开。"""
        from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(
            provider_name="test",
            failure_threshold=1,
            recovery_timeout_s=0.01,
        )
        cb.record_failure()
        time.sleep(0.02)
        cb.can_proceed()  # → half_open
        cb.record_failure()
        assert cb.state == "open"

    def test_reset(self):
        """手动重置断路器回到 closed。"""
        from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(provider_name="test", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        cb.reset()
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_get_status(self):
        """get_status 返回完整状态字典。"""
        from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(provider_name="test", failure_threshold=5)
        status = cb.get_status()
        assert status["provider"] == "test"
        assert status["state"] == "closed"
        assert status["failure_count"] == 0
        assert status["failure_threshold"] == 5

    def test_success_decrements_failure_count(self):
        """closed 状态下调用成功会递减 failure_count。"""
        from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(provider_name="test", failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        cb.record_success()
        assert cb.failure_count == 1


# ===========================================================================
# key_pool
# ===========================================================================


class TestApiKeyPool:
    def test_empty_pool(self):
        """没有 API key 时返回 None。"""
        from src.audiobook_studio.llm.key_pool import ApiKeyPool

        pool = ApiKeyPool(provider_name="test", primary_key_env="NONEXISTENT_KEY_999")
        assert pool.size == 0
        assert pool.get_key() is None

    def test_primary_key(self):
        """从环境变量获取主 key。"""
        import os

        from src.audiobook_studio.llm.key_pool import ApiKeyPool

        os.environ["TEST_POOL_KEY_1"] = "sk-test-1"
        try:
            pool = ApiKeyPool(provider_name="test", primary_key_env="TEST_POOL_KEY_1")
            assert pool.size == 1
            key = pool.get_key()
            assert key == "sk-test-1"
        finally:
            del os.environ["TEST_POOL_KEY_1"]

    def test_round_robin(self):
        """多 key 时 round_robin 轮转。"""
        import os

        from src.audiobook_studio.llm.key_pool import ApiKeyPool

        os.environ["TEST_RO_KEY_1"] = "k1"
        os.environ["TEST_RO_KEY_2"] = "k2"
        try:
            pool = ApiKeyPool(
                provider_name="test",
                primary_key_env="TEST_RO_KEY_1",
                pool_key_envs=["TEST_RO_KEY_2"],
                strategy="round_robin",
            )
            assert pool.size == 2
            k1 = pool.get_key()
            k2 = pool.get_key()
            assert k1 != k2 or pool.size == 1  # round_robin 轮转
        finally:
            del os.environ["TEST_RO_KEY_1"]
            del os.environ["TEST_RO_KEY_2"]

    def test_get_stats(self):
        """get_stats 返回正确的统计信息。"""
        import os

        from src.audiobook_studio.llm.key_pool import ApiKeyPool

        os.environ["TEST_STATS_KEY"] = "sk-stats"
        try:
            pool = ApiKeyPool(provider_name="test", primary_key_env="TEST_STATS_KEY")
            pool.get_key()
            stats = pool.get_stats()
            assert stats["provider"] == "test"
            assert stats["total_keys"] == 1
            assert stats["total_requests"] >= 1
        finally:
            del os.environ["TEST_STATS_KEY"]

    def test_record_failure(self):
        """record_failure 后 key 进入冷却。"""
        import os

        from src.audiobook_studio.llm.key_pool import ApiKeyPool

        os.environ["TEST_FAIL_KEY"] = "sk-fail"
        try:
            pool = ApiKeyPool(
                provider_name="test",
                primary_key_env="TEST_FAIL_KEY",
                cooldown_s=10,
            )
            pool.get_key()
            pool.record_failure()
            stats = pool.get_stats()
            assert stats["total_failures"] >= 1
        finally:
            del os.environ["TEST_FAIL_KEY"]


class TestKeyPoolManager:
    def test_register_and_get(self):
        """注册 provider 后可以获取 key。"""
        import os

        from src.audiobook_studio.llm.key_pool import KeyPoolManager

        os.environ["TEST_KPM_KEY"] = "sk-kpm"
        try:
            mgr = KeyPoolManager()
            mgr.register(provider_name="test", primary_key_env="TEST_KPM_KEY")
            key = mgr.get_key("test")
            assert key == "sk-kpm"
        finally:
            del os.environ["TEST_KPM_KEY"]

    def test_get_unknown_provider(self):
        """未注册 provider 返回 None。"""
        from src.audiobook_studio.llm.key_pool import KeyPoolManager

        mgr = KeyPoolManager()
        assert mgr.get_key("nonexistent") is None

    def test_get_all_stats(self):
        """get_all_stats 返回所有已注册 provider 的统计。"""
        from src.audiobook_studio.llm.key_pool import KeyPoolManager

        mgr = KeyPoolManager()
        mgr.register(provider_name="a", primary_key_env="NONEXISTENT_A")
        stats = mgr.get_all_stats()
        assert "a" in stats


# ===========================================================================
# quota_registry
# ===========================================================================


class TestQuotaRegistry:
    def test_can_make_request_default(self):
        """未注册 provider 默认允许。"""
        from src.audiobook_studio.llm.quota_registry import QuotaRegistry

        reg = QuotaRegistry()
        assert reg.can_make_request("unknown_provider") is True

    def test_can_make_request_registered(self):
        """注册 provider 在额度内允许请求。"""
        from src.audiobook_studio.llm.quota_registry import QuotaConfig, QuotaRegistry

        reg = QuotaRegistry()
        reg.register_config(
            QuotaConfig(
                provider_name="test_p",
                requests_per_minute=10,
                requests_per_day=100,
                tokens_per_minute=5000,
                tokens_per_day=50000,
            )
        )
        assert reg.can_make_request("test_p", estimated_tokens=100) is True

    def test_daily_limit_exceeded(self):
        """超过每日请求限制后拒绝。"""
        from src.audiobook_studio.llm.quota_registry import QuotaConfig, QuotaRegistry

        reg = QuotaRegistry()
        reg.register_config(
            QuotaConfig(
                provider_name="limited",
                requests_per_day=2,
                requests_per_minute=100,
                tokens_per_minute=100000,
                tokens_per_day=100000,
            )
        )
        reg.record_request("limited")
        reg.record_request("limited")
        assert reg.can_make_request("limited") is False

    def test_minute_limit_exceeded(self):
        """超过每分钟请求限制后拒绝。"""
        from src.audiobook_studio.llm.quota_registry import QuotaConfig, QuotaRegistry

        reg = QuotaRegistry()
        reg.register_config(
            QuotaConfig(
                provider_name="mtest",
                requests_per_minute=2,
                requests_per_day=1000,
                tokens_per_minute=100000,
                tokens_per_day=100000,
            )
        )
        reg.record_request("mtest")
        reg.record_request("mtest")
        assert reg.can_make_request("mtest") is False

    def test_record_failure(self):
        """记录失败会增加 consecutive_failures。"""
        from src.audiobook_studio.llm.quota_registry import QuotaConfig, QuotaRegistry

        reg = QuotaRegistry()
        reg.register_config(QuotaConfig(provider_name="ftest"))
        reg.record_request("ftest", success=False)
        usage = reg.get_usage("ftest")
        assert usage.consecutive_failures == 1
        assert usage.total_failures_today == 1

    def test_record_success_resets_failures(self):
        """成功请求重置连续失败计数。"""
        from src.audiobook_studio.llm.quota_registry import QuotaConfig, QuotaRegistry

        reg = QuotaRegistry()
        reg.register_config(QuotaConfig(provider_name="srtest"))
        reg.record_request("srtest", success=False)
        reg.record_request("srtest", success=False)
        usage = reg.get_usage("srtest")
        assert usage.consecutive_failures == 2
        reg.record_request("srtest", success=True)
        assert usage.consecutive_failures == 0

    def test_quota_status_configured(self):
        """get_quota_status 返回完整状态。"""
        from src.audiobook_studio.llm.quota_registry import QuotaConfig, QuotaRegistry

        reg = QuotaRegistry()
        reg.register_config(
            QuotaConfig(
                provider_name="qtest",
                requests_per_day=100,
                tokens_per_day=10000,
                requests_per_minute=10,
                tokens_per_minute=1000,
            )
        )
        reg.record_request("qtest", tokens_used=500)
        status = reg.get_quota_status("qtest")
        assert status["configured"] is True
        assert status["daily"]["requests_used"] == 1

    def test_quota_status_unconfigured(self):
        """未配置 provider 返回 configured=False。"""
        from src.audiobook_studio.llm.quota_registry import QuotaRegistry

        reg = QuotaRegistry()
        status = reg.get_quota_status("unknown")
        assert status["configured"] is False

    def test_get_all_statuses(self):
        """get_all_statuses 返回所有已注册 provider 状态。"""
        from src.audiobook_studio.llm.quota_registry import QuotaConfig, QuotaRegistry

        reg = QuotaRegistry()
        reg.register_config(QuotaConfig(provider_name="a"))
        reg.register_config(QuotaConfig(provider_name="b"))
        statuses = reg.get_all_statuses()
        assert "a" in statuses
        assert "b" in statuses

    def test_get_healthy_providers(self):
        """get_healthy_providers 返回未超限的 provider 列表。"""
        from src.audiobook_studio.llm.quota_registry import QuotaConfig, QuotaRegistry

        reg = QuotaRegistry()
        reg.register_config(
            QuotaConfig(provider_name="healthy_p", requests_per_day=100)
        )
        healthy = reg.get_healthy_providers()
        assert "healthy_p" in healthy

    def test_health_score(self):
        """get_quota_health_score 返回 0-1 之间的分数。"""
        from src.audiobook_studio.llm.quota_registry import QuotaConfig, QuotaRegistry

        reg = QuotaRegistry()
        reg.register_config(QuotaConfig(provider_name="hs_p", requests_per_day=100))
        score = reg.get_quota_health_score("hs_p")
        assert 0.0 <= score <= 1.0

    def test_health_score_unconfigured(self):
        """未配置 provider 健康分数为 1.0。"""
        from src.audiobook_studio.llm.quota_registry import QuotaRegistry

        reg = QuotaRegistry()
        assert reg.get_quota_health_score("unknown") == 1.0

    def test_token_daily_limit(self):
        """超过每日 token 限制后拒绝。"""
        from src.audiobook_studio.llm.quota_registry import QuotaConfig, QuotaRegistry

        reg = QuotaRegistry()
        reg.register_config(
            QuotaConfig(
                provider_name="tdtest",
                tokens_per_day=100,
                requests_per_day=10000,
                tokens_per_minute=100000,
                requests_per_minute=10000,
            )
        )
        reg.record_request("tdtest", tokens_used=100)
        assert reg.can_make_request("tdtest", estimated_tokens=1) is False


# ===========================================================================
# health_probe
# ===========================================================================


class TestHealthProbe:
    def test_init(self):
        """HealthProbe 初始化并创建所有 provider 的状态条目。"""
        from src.audiobook_studio.llm.health_probe import HealthProbe

        p1 = MagicMock()
        p1.name = "p1"
        p2 = MagicMock()
        p2.name = "p2"

        hp = HealthProbe(providers=[p1, p2])
        assert "p1" in hp.statuses
        assert "p2" in hp.statuses

    def test_is_healthy_default(self):
        """未探测的 provider 默认为 healthy。"""
        from src.audiobook_studio.llm.health_probe import HealthProbe

        hp = HealthProbe(providers=[])
        assert hp.is_healthy("nonexistent") is True

    def test_start_stop(self):
        """start/stop 不抛出异常。"""
        from src.audiobook_studio.llm.health_probe import HealthProbe

        hp = HealthProbe(providers=[], interval_s=100)
        hp.start()
        hp.stop()

    def test_probe_now_no_base_url(self):
        """无 base_url 的 provider 直接标记为 healthy。"""
        from src.audiobook_studio.llm.health_probe import HealthProbe

        p = MagicMock()
        p.name = "local"
        p.base_url = None

        hp = HealthProbe(providers=[p])
        status = hp.probe_now("local")
        assert status.is_healthy is True

    def test_get_status(self):
        """get_status 返回 HealthStatus 对象。"""
        from src.audiobook_studio.llm.health_probe import HealthProbe, HealthStatus

        hp = HealthProbe(providers=[])
        status = hp.get_status("anything")
        assert isinstance(status, HealthStatus)

    def test_get_all_statuses(self):
        """get_all_statuses 返回所有状态。"""
        from src.audiobook_studio.llm.health_probe import HealthProbe

        p = MagicMock()
        p.name = "prov"
        hp = HealthProbe(providers=[p])
        statuses = hp.get_all_statuses()
        assert "prov" in statuses

    def test_get_healthy_providers(self):
        """get_healthy_providers 返回健康 provider 列表。"""
        from src.audiobook_studio.llm.health_probe import HealthProbe

        p = MagicMock()
        p.name = "ok"
        hp = HealthProbe(providers=[p])
        healthy = hp.get_healthy_providers()
        assert "ok" in healthy

    def test_health_status_to_dict(self):
        """HealthStatus.to_dict 返回完整字典。"""
        from src.audiobook_studio.llm.health_probe import HealthStatus

        hs = HealthStatus(provider="test", is_healthy=True, latency_ms=42.0)
        d = hs.to_dict()
        assert d["provider"] == "test"
        assert d["latency_ms"] == 42.0


# ===========================================================================
# utils
# ===========================================================================


class TestUtils:
    def test_parse_error(self):
        """LLMParseError 包含 raw_response 和 stage。"""
        from src.audiobook_studio.llm.utils import LLMParseError

        err = LLMParseError("bad json", raw_response="{}", stage="judge")
        assert "bad json" in str(err)
        assert err.raw_response == "{}"
        assert err.stage == "judge"

    def test_validate_none_response(self):
        """None 响应抛出 LLMParseError。"""
        from src.audiobook_studio.llm.utils import (
            LLMParseError,
            validate_and_parse_llm_response,
        )

        with pytest.raises(LLMParseError, match="None"):
            validate_and_parse_llm_response(None, MagicMock, "test")

    def test_validate_empty_string(self):
        """空字符串响应抛出 LLMParseError。"""
        from src.audiobook_studio.llm.utils import (
            LLMParseError,
            validate_and_parse_llm_response,
        )

        with pytest.raises(LLMParseError, match="empty"):
            validate_and_parse_llm_response("", MagicMock, "test")

    def test_validate_invalid_json_string(self):
        """无效 JSON 字符串抛出 LLMParseError。"""
        from src.audiobook_studio.llm.utils import (
            LLMParseError,
            validate_and_parse_llm_response,
        )

        with pytest.raises(LLMParseError, match="invalid JSON"):
            validate_and_parse_llm_response("not json", MagicMock, "test")

    def test_validate_valid_json_string(self):
        """有效 JSON 字符串解析后返回 dict。"""
        from src.audiobook_studio.llm.utils import validate_and_parse_llm_response

        result = validate_and_parse_llm_response('{"a": 1}', MagicMock, "test")
        assert result == {"a": 1}

    def test_validate_non_dict(self):
        """非 dict 类型抛出 LLMParseError。"""
        from src.audiobook_studio.llm.utils import (
            LLMParseError,
            validate_and_parse_llm_response,
        )

        with pytest.raises(LLMParseError, match="not a JSON object"):
            validate_and_parse_llm_response([1, 2], MagicMock, "test")

    def test_validate_empty_dict(self):
        """空 dict {} 抛出 LLMParseError。"""
        from src.audiobook_studio.llm.utils import (
            LLMParseError,
            validate_and_parse_llm_response,
        )

        with pytest.raises(LLMParseError, match="empty"):
            validate_and_parse_llm_response({}, MagicMock, "test")

    def test_validate_judge_missing_segment_id(self):
        """judge 阶段缺少 segment_id 抛出 LLMParseError。"""
        from src.audiobook_studio.llm.utils import (
            LLMParseError,
            validate_and_parse_llm_response,
        )

        with pytest.raises(LLMParseError, match="segment_id"):
            validate_and_parse_llm_response({"a": 1}, MagicMock, "judge")

    def test_validate_judge_with_segment_id(self):
        """judge 阶段有 segment_id 时正常返回。"""
        from src.audiobook_studio.llm.utils import validate_and_parse_llm_response

        result = validate_and_parse_llm_response(
            {"segment_id": "s1", "score": 0.8}, MagicMock, "judge"
        )
        assert result["segment_id"] == "s1"


# ===========================================================================
# client — 核心 call 流程
# ===========================================================================


class TestLLMClient:
    def test_config_defaults(self):
        """LLMClientConfig 默认参数正确。"""
        from src.audiobook_studio.llm.client import LLMClientConfig

        cfg = LLMClientConfig(model="m")
        assert cfg.temperature == 0.1
        assert cfg.max_tokens == 4000

    def test_config_custom(self):
        """LLMClientConfig 自定义参数。"""
        from src.audiobook_studio.llm.client import LLMClientConfig

        cfg = LLMClientConfig(model="m", temperature=0.5, max_tokens=2000)
        assert cfg.temperature == 0.5

    def test_mock_mode_call(self):
        """mock_mode 下返回 mock 结果。"""
        from src.audiobook_studio.llm.client import (
            LLMClient,
            LLMClientConfig,
            create_client,
        )

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test-model")
            assert client.config.mock_mode is True

    def test_create_client_factory(self):
        """create_client 工厂函数返回 LLMClient。"""
        from src.audiobook_studio.llm.client import LLMClient, create_client

        client = create_client(model="test", api_base="http://fake")
        assert isinstance(client, LLMClient)

    def test_temperature_override_in_call(self):
        """client.call 时 kwargs 中的 temperature 覆盖 config 默认值，
        且不引发 'got multiple values' 错误。"""
        from src.audiobook_studio.llm.client import LLMClient, LLMClientConfig

        cfg = LLMClientConfig(model="test", temperature=0.1)
        client = LLMClient(cfg)

        # 通过 MOCK_LLM=true 环境变量进入 mock 模式
        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            result = client.call(
                prompt="hello",
                response_model=MagicMock,
                temperature=0.9,
            )
            # 不抛出 TypeError（之前 temperature 重复传递会报错）
            assert result is not None


# ===========================================================================
# router — 核心路由逻辑
# ===========================================================================


class TestLLMRouter:
    def test_model_config(self):
        """ModelConfig 数据类正确初始化。"""
        from src.audiobook_studio.llm.router import ModelConfig

        mc = ModelConfig(name="test_model", temperature=0.2, max_tokens=2000)
        assert mc.name == "test_model"
        assert mc.temperature == 0.2

    def test_stage_routing_config(self):
        """StageRoutingConfig 包含模型列表。"""
        from src.audiobook_studio.llm.router import ModelConfig, StageRoutingConfig

        src = StageRoutingConfig(
            stage="analyze",
            models=[ModelConfig(name="m1")],
        )
        assert len(src.models) == 1

    def test_cost_tracker(self):
        """CostTracker 记录和查询费用。"""
        from src.audiobook_studio.llm.router import CostTracker

        ct = CostTracker()
        ct.set_daily_limit("m1", 10.0)
        ct.add_cost("m1", 1.0)
        assert ct.get_daily_cost("m1") == 1.0
        assert ct.get_total_daily_cost() == 1.0
        assert ct.is_limit_exceeded("m1") is False
        ct.add_cost("m1", 9.5)
        assert ct.is_limit_exceeded("m1") is True

    def test_cost_tracker_alert(self):
        """CostTracker 达到告警阈值。"""
        from src.audiobook_studio.llm.router import CostTracker

        ct = CostTracker()
        ct.set_daily_limit("m2", 10.0)
        ct.add_cost("m2", 8.5)
        assert ct.is_alert_threshold("m2") is True

    def test_cost_tracker_status(self):
        """get_status 返回完整费用状态。"""
        from src.audiobook_studio.llm.router import CostTracker

        ct = CostTracker()
        ct.set_daily_limit("m3", 5.0)
        ct.add_cost("m3", 0.5)
        status = ct.get_status()
        assert "m3" in status
        assert status["m3"]["daily_cost_usd"] == 0.5

    def test_rate_limiter(self):
        """ProviderRateLimiter 在限额内允许、超限拒绝。"""
        from src.audiobook_studio.llm.router import ProviderRateLimiter

        rl = ProviderRateLimiter(max_tpm=100, max_rpm=2)
        assert rl.can_proceed(10) is True
        rl.record_usage(10)
        rl.record_usage(10)
        assert rl.can_proceed(10) is False

    def test_prompt_compressor(self):
        """PromptCompressor 在 token 超限时截断。"""
        from src.audiobook_studio.llm.router import PromptCompressor

        config = MagicMock()
        config.prompt_compression.max_input_tokens = 100
        config.prompt_compression.truncate_strategy = "tail"
        config.prompt_compression.remove_few_shot_when_long = False
        config.prompt_compression.min_few_shot_examples = 0
        config.prompt_compression.schema_injection_mode = "inline"

        pc = PromptCompressor(config)
        # 短 prompt 不截断
        short, tokens = pc.compress("short", "{}", "")
        assert tokens < 100

    def test_prompt_compressor_long(self):
        """PromptCompressor 截断过长 prompt。"""
        from src.audiobook_studio.llm.router import PromptCompressor

        config = MagicMock()
        config.prompt_compression.max_input_tokens = 50
        config.prompt_compression.truncate_strategy = "tail"
        config.prompt_compression.remove_few_shot_when_long = True
        config.prompt_compression.min_few_shot_examples = 0
        config.prompt_compression.schema_injection_mode = "inline"

        pc = PromptCompressor(config)
        long_text = "这是一个很长的提示文本。" * 100
        result, tokens = pc.compress(long_text, "{}", "示例")
        assert "截断" in result

    def test_estimate_tokens(self):
        """estimate_tokens 对中英文混合文本进行估算。"""
        from src.audiobook_studio.llm.router import PromptCompressor

        config = MagicMock()
        pc = PromptCompressor(config)
        tokens = pc.estimate_tokens("hello你好")
        assert tokens > 0

    def test_create_router_factory(self):
        """create_router 工厂函数返回 LLMRouter。"""
        from src.audiobook_studio.llm.router import LLMRouter, create_router

        router = create_router()
        assert isinstance(router, LLMRouter)


# ===========================================================================
# judge
# ===========================================================================


class TestLLMJudge:
    def test_judge_config_defaults(self):
        """JudgeConfig 默认参数。"""
        from src.audiobook_studio.llm.judge import JudgeConfig

        cfg = JudgeConfig()
        assert cfg.temperature == 0.0

    def test_judge_creates_default_router(self):
        """LLMJudge 在无 router 时创建默认 router。"""
        from src.audiobook_studio.llm.judge import LLMJudge

        judge = LLMJudge()
        assert judge.router is not None

    def test_judge_fallback_on_error(self):
        """judge_quality 在 router 抛出异常时返回安全默认值。"""
        from src.audiobook_studio.llm.judge import JudgeConfig, LLMJudge
        from src.audiobook_studio.schemas import ParagraphAnnotation

        mock_router = MagicMock()
        mock_router.call.side_effect = RuntimeError("LLM unavailable")

        judge = LLMJudge(config=JudgeConfig(), router=mock_router)
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="旁白",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            pause_before_ms=300,
            pause_after_ms=500,
            confidence=0.9,
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
        )
        result = judge.judge_quality(
            segment_id="seg1",
            paragraph_annotation=annotation,
            audio_description="test",
            reference_text="ref text",
        )
        assert result.needs_regeneration is True
        assert result.overall_score == 0.0


# ===========================================================================
# constitutional_rules
# ===========================================================================


class TestConstitutionalRules:
    def test_apply_constitutional_rules_returns_response(self):
        """apply_constitutional_rules 返回原始响应（占位符实现）。"""
        from src.audiobook_studio.llm.constitutional_rules import (
            apply_constitutional_rules,
        )
        from src.audiobook_studio.schemas.tts_edit import TtsEditOutput

        output = TtsEditOutput(edited_text="test", confidence=0.9, rationale="test")
        result = apply_constitutional_rules(output)
        assert result == output

    def test_apply_constitutional_rules_with_context(self):
        """apply_constitutional_rules 接受上下文参数。"""
        from src.audiobook_studio.llm.constitutional_rules import (
            apply_constitutional_rules,
        )
        from src.audiobook_studio.schemas.tts_edit import TtsEditOutput

        output = TtsEditOutput(edited_text="test", confidence=0.9, rationale="test")
        result = apply_constitutional_rules(output, context={"stage": "test"})
        assert result == output

    def test_apply_safety_filters(self):
        """apply_safety_filters 返回原始响应（占位符实现）。"""
        from src.audiobook_studio.llm.constitutional_rules import apply_safety_filters
        from src.audiobook_studio.schemas.tts_edit import TtsEditOutput

        output = TtsEditOutput(edited_text="test", confidence=0.9, rationale="test")
        result = apply_safety_filters(output)
        assert result == output

    def test_apply_style_guidelines(self):
        """apply_style_guidelines 返回原始响应（占位符实现）。"""
        from src.audiobook_studio.llm.constitutional_rules import apply_style_guidelines
        from src.audiobook_studio.schemas.tts_edit import TtsEditOutput

        output = TtsEditOutput(edited_text="test", confidence=0.9, rationale="test")
        result = apply_style_guidelines(output, style_guide={"tone": "formal"})
        assert result == output

    def test_apply_domain_constraints(self):
        """apply_domain_constraints 返回原始响应（占位符实现）。"""
        from src.audiobook_studio.llm.constitutional_rules import (
            apply_domain_constraints,
        )
        from src.audiobook_studio.schemas.tts_edit import TtsEditOutput

        output = TtsEditOutput(edited_text="test", confidence=0.9, rationale="test")
        result = apply_domain_constraints(output, domain="medical")
        assert result == output
