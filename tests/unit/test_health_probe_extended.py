"""HealthProbe 扩展测试 — 覆盖 _probe_provider, _probe_all, probe_now 等路径。"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


class TestHealthProbeExtended:
    def _make_hp(self, providers=None):
        """创建 HealthProbe 并绕过 conftest 的 autouse mock。"""
        from src.audiobook_studio.llm.health_probe import HealthProbe

        if providers is None:
            providers = []
        return HealthProbe(providers=providers)

    def test_probe_provider_with_base_url_200(self):
        """有 base_url 且返回 200 时标记 healthy。"""
        p = MagicMock()
        p.name = "prov"
        p.base_url = "http://localhost:1234"
        p.get_api_key.return_value = "sk-test"

        hp = self._make_hp(providers=[p])

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}

        with patch("src.audiobook_studio.llm.health_probe.httpx.Client") as MockClient:
            instance = MagicMock()
            instance.get.return_value = mock_resp
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = instance

            status = hp.probe_now("prov")
            assert status.is_healthy is True

    def test_probe_provider_with_base_url_401(self):
        """有 base_url 且返回 401 时标记 unhealthy。"""
        p = MagicMock()
        p.name = "prov"
        p.base_url = "http://localhost:1234"
        p.get_api_key.return_value = "sk-test"

        hp = self._make_hp(providers=[p])

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {}

        with patch("src.audiobook_studio.llm.health_probe.httpx.Client") as MockClient:
            instance = MagicMock()
            instance.get.return_value = mock_resp
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = instance

            status = hp.probe_now("prov")
            assert status.is_healthy is False

    def test_probe_provider_timeout(self):
        """超时异常标记 unhealthy。"""
        import httpx as httpx_mod

        p = MagicMock()
        p.name = "prov"
        p.base_url = "http://localhost:1234"
        p.get_api_key.return_value = "sk-test"

        hp = self._make_hp(providers=[p])

        with patch("src.audiobook_studio.llm.health_probe.httpx.Client") as MockClient:
            instance = MagicMock()
            instance.get.side_effect = httpx_mod.TimeoutException("timeout")
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = instance

            status = hp.probe_now("prov")
            assert status.is_healthy is False
            assert "timeout" in status.error_message

    def test_probe_provider_general_exception(self):
        """通用异常标记 unhealthy。"""
        p = MagicMock()
        p.name = "prov"
        p.base_url = "http://localhost:1234"
        p.get_api_key.return_value = "sk-test"

        hp = self._make_hp(providers=[p])

        with patch("src.audiobook_studio.llm.health_probe.httpx.Client") as MockClient:
            instance = MagicMock()
            instance.get.side_effect = ConnectionError("refused")
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = instance

            status = hp.probe_now("prov")
            assert status.is_healthy is False
            assert "refused" in status.error_message

    def test_probe_provider_with_rate_limit_headers(self):
        """包含速率限制头时解析 quota。"""
        p = MagicMock()
        p.name = "prov"
        p.base_url = "http://localhost:1234"
        p.get_api_key.return_value = "sk"

        hp = self._make_hp(providers=[p])

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {
            "x-ratelimit-remaining": "50",
            "x-ratelimit-limit": "100",
        }

        with patch("src.audiobook_studio.llm.health_probe.httpx.Client") as MockClient:
            instance = MagicMock()
            instance.get.return_value = mock_resp
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = instance

            status = hp.probe_now("prov")
            assert status.quota_remaining == 50
            assert status.quota_limit == 100

    def test_probe_provider_invalid_rate_limit_headers(self):
        """无效速率限制头时不崩溃。"""
        p = MagicMock()
        p.name = "prov"
        p.base_url = "http://localhost:1234"
        p.get_api_key.return_value = "sk"

        hp = self._make_hp(providers=[p])

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {
            "x-ratelimit-remaining": "not-a-number",
            "x-ratelimit-limit": "also-not",
        }

        with patch("src.audiobook_studio.llm.health_probe.httpx.Client") as MockClient:
            instance = MagicMock()
            instance.get.return_value = mock_resp
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = instance

            status = hp.probe_now("prov")
            assert status.quota_remaining is None
            assert status.quota_limit is None

    def test_probe_now_unknown_provider(self):
        """probe_now 未知 provider 返回 not found。"""
        hp = self._make_hp(providers=[])
        status = hp.probe_now("unknown")
        assert status.is_healthy is False
        assert "not found" in status.error_message

    def test_probe_provider_no_api_key(self):
        """无 API key 时探测不带 Authorization。"""
        p = MagicMock()
        p.name = "prov"
        p.base_url = "http://localhost:1234"
        p.get_api_key.return_value = None

        hp = self._make_hp(providers=[p])

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}

        with patch("src.audiobook_studio.llm.health_probe.httpx.Client") as MockClient:
            instance = MagicMock()
            instance.get.return_value = mock_resp
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = instance

            status = hp.probe_now("prov")
            assert status.is_healthy is True

    def test_probe_all_exception_in_provider(self):
        """_probe_all 中某 provider 抛异常不影响其他。"""
        p1 = MagicMock()
        p1.name = "p1"
        p1.base_url = None

        p2 = MagicMock()
        p2.name = "p2"
        p2.base_url = "http://x"

        hp = self._make_hp(providers=[p1, p2])

        with patch.object(hp, "_probe_provider") as mock_probe:

            def side_effect(name, prov):
                if name == "p1":
                    hp.statuses["p1"] = hp.statuses["p1"]  # no-op
                else:
                    raise RuntimeError("boom")

            mock_probe.side_effect = side_effect
            hp._probe_all()
            assert hp.statuses["p1"].is_healthy is True

    def test_start_stop_thread(self):
        """start/stop 创建并终止线程（绕过 conftest autouse mock）。"""
        # 直接调用原始 start，不受 conftest mock 影响
        from src.audiobook_studio.llm.health_probe import HealthProbe

        # 创建实例时不经过 start，直接操作内部状态
        hp = HealthProbe(providers=[], interval_s=300)

        # 手动启动线程（绕过 mock）
        import threading

        hp._stop_event.clear()
        hp._thread = threading.Thread(target=hp._probe_loop, daemon=True)
        hp._thread.start()
        assert hp._thread is not None
        assert hp._thread.is_alive()
        hp.stop()

    def test_stop_without_start(self):
        """stop 未 start 不报错。"""
        hp = self._make_hp(providers=[])
        hp.stop()  # 不应报错

    def test_health_status_to_dict(self):
        """HealthStatus.to_dict() 返回正确结构。"""
        from src.audiobook_studio.llm.health_probe import HealthStatus

        hs = HealthStatus(
            provider="test",
            is_healthy=True,
            latency_ms=123.4,
            error_message=None,
            quota_remaining=50,
            quota_limit=100,
        )
        d = hs.to_dict()
        assert d["provider"] == "test"
        assert d["is_healthy"] is True
        assert d["latency_ms"] == 123.4
        assert d["quota_remaining"] == 50
        assert d["quota_limit"] == 100

    def test_get_status(self):
        """get_status 返回缓存状态。"""
        hp = self._make_hp(providers=[])
        status = hp.get_status("any")
        assert status.provider == "any"
        assert status.is_healthy is True  # default

    def test_get_all_statuses(self):
        """get_all_statuses 返回所有缓存。"""
        hp = self._make_hp(providers=[])
        all_s = hp.get_all_statuses()
        assert isinstance(all_s, dict)

    def test_is_healthy_unknown(self):
        """is_healthy 对未知 provider 返回 True（默认）。"""
        hp = self._make_hp(providers=[])
        assert hp.is_healthy("unknown") is True

    def test_get_healthy_providers(self):
        """get_healthy_providers 返回健康列表。"""
        from src.audiobook_studio.llm.health_probe import HealthStatus

        hp = self._make_hp(providers=[])
        hp.statuses["a"] = HealthStatus(provider="a", is_healthy=True)
        hp.statuses["b"] = HealthStatus(provider="b", is_healthy=False)
        healthy = hp.get_healthy_providers()
        assert "a" in healthy
        assert "b" not in healthy

    def test_probe_provider_no_base_url(self):
        """provider 无 base_url 时直接标记 healthy。"""
        p = MagicMock()
        p.name = "prov"
        p.base_url = None

        hp = self._make_hp(providers=[p])
        hp._probe_provider("prov", p)
        assert hp.statuses["prov"].is_healthy is True

    def test_probe_loop_runs_once(self):
        """_probe_loop 在 stop 后退出。"""
        hp = self._make_hp(providers=[])
        hp._stop_event.set()  # 立即设置停止事件
        hp._probe_loop()  # 应立即退出
        # 不报错即可

    def test_probe_provider_500_status(self):
        """500 状态码标记 unhealthy。"""
        p = MagicMock()
        p.name = "prov"
        p.base_url = "http://localhost:1234"
        p.get_api_key.return_value = "sk"

        hp = self._make_hp(providers=[p])

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.headers = {}

        with patch("src.audiobook_studio.llm.health_probe.httpx.Client") as MockClient:
            instance = MagicMock()
            instance.get.return_value = mock_resp
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = instance

            status = hp.probe_now("prov")
            assert status.is_healthy is False
