"""M1 — Ollama provider integration with ``create_router`` + hot-reload.

``tests/conftest_minimal`` replaces ``config_loader.LLMProvidersConfig`` /
``ProviderType`` with mocks (a single fixed provider), so we drive the *real*
``LLMRouter`` machinery with fake config/loader classes here — mirroring
``tests/unit/test_provider_hotreload.py``. The health probe is a no-op in tests
(``AUDIOBOOK_DISABLE_HEALTH_PROBE=1`` in conftest), so no background threads or
network calls are spawned. The Ollama client init is exercised offline by
temporarily clearing ``MOCK_LLM`` (AsyncOpenAI construction makes no request).

These are the 3 integration tests for the plan's M1 Ollama item:
  1. create_router loads a config containing an Ollama provider and the router
     recognizes it as the OLLAMA type (and flips local-model availability).
  2. The Ollama provider is routed to a DirectProviderClient whose call path
     targets ``http://localhost:11434`` (default and explicit base_url).
  3. The hot-reload path correctly adds/removes an Ollama provider and rebuilds
     runtime state (so local-model availability tracks the live config).
"""

import enum
import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, "src")

import audiobook_studio.llm.router as router_mod
from audiobook_studio.llm.direct_client import DirectProviderClient, DirectProviderClientConfig, DirectProviderType
from audiobook_studio.llm.router import create_router


class ProviderType(str, enum.Enum):
    """Minimal stand-in for config_loader.ProviderType (real OLLAMA value)."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    VLLM = "vllm"
    OLLAMA = "ollama"


class FakeProvider:
    """Provider shape consumed by ``_rebuild_provider_runtime`` / ``get_direct_client``."""

    def __init__(
        self,
        name,
        provider=ProviderType.OPENAI,
        model="gpt-3.5-turbo",
        enabled=True,
        priority=1,
        max_tpm=10000,
        max_rpm=60,
        api_key_env=None,
        pool=None,
        strat="round_robin",
        daily=10.0,
        base_url=None,
        extra_params=None,
        health_path=None,
        timeout_seconds=60,
    ):
        self.name = name
        self.provider = provider
        self.model = model
        self.enabled = enabled
        self.priority = priority
        self.max_tokens_per_minute = max_tpm
        self.max_requests_per_minute = max_rpm
        self.api_key_env = api_key_env
        self.api_key_pool_env = pool or []
        self.key_rotation_strategy = strat
        self.max_daily_cost_usd = daily
        self.base_url = base_url
        self.extra_params = extra_params or {}
        self.health_path = health_path
        self.timeout_seconds = timeout_seconds

    def get_api_key(self):
        """Mirror ProviderConfig.get_api_key (used by get_direct_client)."""
        if self.api_key_env:
            return os.getenv(self.api_key_env)
        return None


class FakeCfg:
    """Config object whose ``get_all_enabled`` reflects ``self.providers``."""

    def __init__(self, providers):
        self.providers = providers

        class _PC:
            max_input_tokens = 4000
            truncate_strategy = "smart"
            remove_few_shot_when_long = True
            min_few_shot_examples = 1
            schema_injection_mode = "minimal"

        self.prompt_compression = _PC()
        self.cost_control = None
        self.fallback = None

    def get_all_enabled(self):
        return [p for p in self.providers if p.enabled]


def _loader(seq):
    """Fake LLMProvidersConfig whose load() walks ``seq`` (one cfg per reload)."""
    state = {"i": 0}

    class _Loader:
        @staticmethod
        def load(path=None):
            cfg = seq[state["i"]]
            state["i"] = min(state["i"] + 1, len(seq) - 1)
            return cfg

    return _Loader


@pytest.fixture
def patched_router(monkeypatch):
    """Install the real OLLAMA-aware ProviderType + fake loader on the router."""
    monkeypatch.setattr(router_mod, "ProviderType", ProviderType)
    yield monkeypatch


def _ollama_provider(name="local-llm", **kw):
    kw.setdefault("provider", ProviderType.OLLAMA)
    kw.setdefault("model", "qwen2.5:3b")
    kw.setdefault("base_url", "http://localhost:11434")
    kw.setdefault("extra_params", {"use_direct_sdk": True})
    return FakeProvider(name, **kw)


def test_create_router_recognizes_ollama_provider(monkeypatch):
    """M1-1: create_router loads an Ollama provider and flags local availability."""
    monkeypatch.setattr(router_mod, "ProviderType", ProviderType)
    cfg = FakeCfg(
        [
            FakeProvider("cloud", provider=ProviderType.OPENAI),
            _ollama_provider(),
        ]
    )
    monkeypatch.setattr(router_mod, "LLMProvidersConfig", _loader([cfg]))

    router = create_router(config_path="virt.yaml")
    enabled = router.config.get_all_enabled()
    ollama = [p for p in enabled if p.provider == ProviderType.OLLAMA]
    assert ollama, "expected an OLLAMA provider in the enabled set"
    # Router's own local-model availability detection keys off ProviderType.OLLAMA.
    assert router.get_free_tier_health()["local_model_available"] is True

    # Disabling the Ollama provider flips local availability back off.
    ollama[0].enabled = False
    assert router.get_free_tier_health()["local_model_available"] is False


def test_ollama_provider_routes_to_localhost_direct_client(monkeypatch):
    """M1-2: Ollama provider is wired to a DirectProviderClient on localhost:11434.

    Verifies (a) the router-level mapping forwards the base_url + OLLAMA type to
    the direct client, and (b) the real Ollama client init targets
    http://localhost:11434 (default and explicit base_url) — offline.
    """
    monkeypatch.setattr(router_mod, "ProviderType", ProviderType)
    ollama = _ollama_provider()
    cfg = FakeCfg([FakeProvider("cloud", provider=ProviderType.OPENAI), ollama])
    monkeypatch.setattr(router_mod, "LLMProvidersConfig", _loader([cfg]))
    router = create_router(config_path="virt.yaml")

    # (a) router forwards OLLAMA type + localhost base_url to the direct client.
    captured = {}

    def spy(config):
        captured["config"] = config
        return object()  # placeholder; not used downstream in this assertion

    monkeypatch.setattr(router_mod, "create_direct_client", spy)
    router.get_direct_client(ollama)
    assert captured["config"].provider == DirectProviderType.OLLAMA
    assert "localhost:11434" in (captured["config"].api_base or "")

    # (b) Ollama client init targets http://localhost:11434 as its base_url.
    # instructor/openai are MagicMock modules under unit tests (conftest_minimal),
    # so we capture the base_url actually passed to the AsyncOpenAI constructor
    # (the URL the call path uses) rather than building a live client.
    from unittest.mock import MagicMock as _MagicMock

    import openai as _openai_mod

    recorded = {}

    def _fake_async_openai(**kwargs):
        recorded["base_url"] = kwargs.get("base_url")
        return _MagicMock()

    monkeypatch.setattr(_openai_mod, "AsyncOpenAI", _fake_async_openai)

    prev = os.environ.get("MOCK_LLM")
    os.environ["MOCK_LLM"] = "false"  # exercise the real _init_ollama_client path
    try:
        # Explicit base_url is honored as-is.
        DirectProviderClient(
            DirectProviderClientConfig(
                provider=DirectProviderType.OLLAMA,
                model="qwen2.5:3b",
                api_base="http://localhost:11434",
            )
        )
        assert recorded["base_url"] == "http://localhost:11434"
        # Missing base_url defaults to http://localhost:11434/v1.
        recorded.clear()
        DirectProviderClient(DirectProviderClientConfig(provider=DirectProviderType.OLLAMA, model="qwen2.5:3b"))
        assert recorded["base_url"] == "http://localhost:11434/v1"
    finally:
        if prev is None:
            os.environ.pop("MOCK_LLM", None)
        else:
            os.environ["MOCK_LLM"] = prev


def test_ollama_hot_reload_add_remove(monkeypatch):
    """M1-3: hot-reload add/remove of an Ollama provider rebuilds runtime state."""
    monkeypatch.setattr(router_mod, "ProviderType", ProviderType)

    cfg_no_ollama = FakeCfg([FakeProvider("cloud", provider=ProviderType.OPENAI)])
    cfg_with_ollama = FakeCfg(
        [
            FakeProvider("cloud", provider=ProviderType.OPENAI),
            _ollama_provider(),
        ]
    )
    cfg_back = FakeCfg([FakeProvider("cloud", provider=ProviderType.OPENAI)])
    loader = _loader([cfg_no_ollama, cfg_with_ollama, cfg_back])
    monkeypatch.setattr(router_mod, "LLMProvidersConfig", loader)

    router = create_router(config_path="virt.yaml")
    assert router.get_free_tier_health()["local_model_available"] is False

    # Reload -> Ollama provider appears; runtime rebuilt for it.
    router.reload_config()
    enabled = router.config.get_all_enabled()
    assert any(p.provider == ProviderType.OLLAMA for p in enabled)
    assert router.get_free_tier_health()["local_model_available"] is True
    # The direct client for the Ollama provider is reachable post-reload.
    ollama = next(p for p in enabled if p.provider == ProviderType.OLLAMA)
    captured = {}

    def spy(config):
        captured["config"] = config
        return object()

    monkeypatch.setattr(router_mod, "create_direct_client", spy)
    router.get_direct_client(ollama)
    assert captured["config"].provider == DirectProviderType.OLLAMA

    # Reload again -> Ollama removed; local availability flips back off.
    router.reload_config()
    assert router.get_free_tier_health()["local_model_available"] is False
    assert not any(p.provider == ProviderType.OLLAMA for p in router.config.get_all_enabled())


def test_router_recognizes_ollama_providers_from_real_yaml(monkeypatch):
    """M1-e2e: create_router 识别真实 llm_providers.yaml 中的 Ollama provider。

    直接读取仓库内的 ``config/llm_providers.yaml``（真实运维配置，作为唯一事实源），
    把其中的 provider 条目映射成路由器可识别的 FakeProvider（ollama -> ProviderType.OLLAMA），
    再经 create_router 走真实 ProviderType 映射与 local_model_available 判定。
    """
    monkeypatch.setattr(router_mod, "ProviderType", ProviderType)

    yaml_path = Path("config/llm_providers.yaml")
    assert yaml_path.exists(), "真实 llm_providers.yaml 必须存在"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    providers_yaml = data.get("providers", [])
    assert providers_yaml, "yaml 中应有 providers 列表"

    # 真实 yaml 里必须至少包含一个 ollama provider（且 base_url 指向本地 11434）。
    ollama_in_yaml = [p for p in providers_yaml if p.get("provider") == "ollama"]
    assert ollama_in_yaml, "真实 yaml 必须包含 ollama provider"
    assert any(
        str(p.get("base_url", "")).startswith("http://localhost:11434") for p in ollama_in_yaml
    ), "ollama provider 的 base_url 应指向本地 Ollama (localhost:11434)"

    provider_map = {
        "ollama": ProviderType.OLLAMA,
        "openai": ProviderType.OPENAI,
        "vllm": ProviderType.VLLM,
        "anthropic": ProviderType.ANTHROPIC,
    }
    fakes = []
    for p in providers_yaml:
        pt = provider_map.get(p.get("provider"), ProviderType.OPENAI)
        fakes.append(
            FakeProvider(
                name=p["name"],
                provider=pt,
                model=p.get("model", "x"),
                base_url=p.get("base_url"),
                enabled=p.get("enabled", True),
                extra_params={"use_direct_sdk": p.get("provider") == "ollama"},
            )
        )
    cfg = FakeCfg(fakes)
    monkeypatch.setattr(router_mod, "LLMProvidersConfig", _loader([cfg]))

    router = create_router(config_path=str(yaml_path))
    enabled = router.config.get_all_enabled()
    ollama_enabled = [p for p in enabled if p.provider == ProviderType.OLLAMA and p.enabled]
    # 真实 yaml 里 ollama_qwen35_2b 等默认启用 -> 路由器应识别为本地可用。
    assert ollama_enabled, "create_router 应识别真实 yaml 中的启用态 Ollama provider"
    assert router.get_free_tier_health()["local_model_available"] is True
    # 启用态 Ollama 的 base_url 应指向 localhost:11434。
    assert any((p.base_url or "").startswith("http://localhost:11434") for p in ollama_enabled)
