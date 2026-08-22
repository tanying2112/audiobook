"""Tests for S2.1 — hot-reload provider changes into LLMRouter.

NOTE: tests/conftest.py imports conftest_minimal which mocks
``LLMProvidersConfig`` (fixed single provider). To verify the *real* reload
mechanism we drive ``LLMRouter`` with fake config/loader classes and stub the
health probe (avoids spawning background threads in unit tests). This exercises
the genuine reload path: ``reload_config`` re-reads the source and
``_rebuild_provider_runtime`` rebuilds clients/limiters/breakers/key-pool.
"""

import sys

import pytest

sys.path.insert(0, "src")

import audiobook_studio.llm.router as router_mod
from audiobook_studio.api import provider_router as prov_api
from audiobook_studio.llm.router import create_router, get_llm_router, reload_llm_router, reset_llm_router

# ── Stubs / fakes ──────────────────────────────────────────────────────────


class FakeProvider:
    """Minimal provider shape consumed by _rebuild_provider_runtime."""

    def __init__(
        self,
        name,
        enabled=True,
        priority=1,
        max_tpm=10000,
        max_rpm=60,
        api_key_env=None,
        pool=None,
        strat="round_robin",
        daily=10.0,
    ):
        self.name = name
        self.enabled = enabled
        self.priority = priority
        self.max_tokens_per_minute = max_tpm
        self.max_requests_per_minute = max_rpm
        self.api_key_env = api_key_env
        self.api_key_pool_env = pool or []
        self.key_rotation_strategy = strat
        self.max_daily_cost_usd = daily


class FakeCfg:
    """Config object whose get_all_enabled() reflects self.providers."""

    def __init__(self, providers):
        self.providers = providers

        # PromptCompressor.__init__ reads these; give harmless defaults.
        class _PC:
            max_input_tokens = 4000
            truncate_strategy = "smart"
            remove_few_shot_when_long = True
            min_few_shot_examples = 1
            schema_injection_mode = "minimal"

        self.prompt_compression = _PC()
        self.cost_control = None  # skips set_global_daily_limit
        self.fallback = None

    def get_all_enabled(self):
        return [p for p in self.providers if p.enabled]


def _make_loader(seq):
    """Return a fake LLMProvidersConfig class whose load() walks ``seq``."""
    state = {"i": 0}

    class _Loader:
        @staticmethod
        def load(path=None):
            cfg = seq[state["i"]]
            state["i"] = min(state["i"] + 1, len(seq) - 1)
            return cfg

    return _Loader


@pytest.fixture(autouse=True)
def stub_health_probe(monkeypatch):
    """Prevent real HealthProbe background threads during unit tests."""

    class _Stub:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(router_mod, "HealthProbe", _Stub)


@pytest.fixture
def fake_loader(monkeypatch):
    """Install a fake LLMProvidersConfig loader that returns 1 then 2 providers."""

    cfg1 = FakeCfg([FakeProvider("p1")])
    cfg2 = FakeCfg([FakeProvider("p1"), FakeProvider("p2")])
    loader = _make_loader([cfg1, cfg2])
    monkeypatch.setattr(router_mod, "LLMProvidersConfig", loader)
    return loader


# ── Tests ──────────────────────────────────────────────────────────────────


def test_reload_config_picks_up_new_provider(fake_loader):
    """reload_config() re-reads the source and reflects added providers."""
    router = create_router(config_path="virt.yaml")
    assert len(router.config.get_all_enabled()) == 1

    router.reload_config()
    assert len(router.config.get_all_enabled()) == 2
    names = {p.name for p in router.config.get_all_enabled()}
    assert names == {"p1", "p2"}
    # Runtime state rebuilt for both providers.
    assert set(router.rate_limiters.keys()) == {"p1", "p2"}
    assert set(router.circuit_breakers.keys()) == {"p1", "p2"}


def test_apply_provider_configs_pushes_external_configs():
    """apply_provider_configs() pushes DB-derived configs into the live router."""
    router = create_router(config_path="virt.yaml")
    a = FakeProvider("db-a", priority=5)
    b = FakeProvider("db-b", priority=6)
    router.config = FakeCfg([a, b])
    router.apply_provider_configs([a, b])
    enabled = router.config.get_all_enabled()
    assert {e.name for e in enabled} == {"db-a", "db-b"}
    assert set(router.rate_limiters.keys()) == {"db-a", "db-b"}


def test_singleton_reload_is_idempotent():
    """get_llm_router / reload_llm_router share one instance; reset cleans up."""
    try:
        reset_llm_router()
        r1 = get_llm_router(config_path="virt.yaml")
        r2 = reload_llm_router(config_path="virt.yaml")
        assert r1 is r2
        assert len(r2.config.get_all_enabled()) == 1
    finally:
        reset_llm_router()


# ── DB -> config mapping (uses provider_router's own ProviderConfig) ────────


class _FakeModel:
    def __init__(self, name, model_id, is_enabled=True):
        self.name = name
        self.model_id = model_id
        self.is_enabled = is_enabled


class _FakeProvider:
    def __init__(self, **kw):
        self.name = kw["name"]
        self.provider_type = kw["provider_type"]
        self.models = kw.get("models", [])
        self.default_model = kw.get("default_model")
        self.api_base = kw.get("api_base")
        self.sort_priority = kw.get("sort_priority", 100)
        self.is_enabled = kw.get("is_enabled", True)
        self.api_key = kw.get("api_key")


def test_db_provider_to_config_mapping(monkeypatch):
    """DB provider row maps to a ProviderConfig with merged stages + key env."""
    import os

    # conftest_minimal mocks config_loader.ProviderType/StageName; use the real
    # ones that router.py bound before the patch.
    monkeypatch.setattr(prov_api, "ProviderType", router_mod.ProviderType)
    monkeypatch.setattr(prov_api, "StageName", router_mod.StageName)
    monkeypatch.setattr(prov_api, "_ALL_STAGES", list(router_mod.StageName))
    os.environ.pop("PROVIDER_DB_MYPROV_KEY", None)
    prov = _FakeProvider(
        name="myProv",
        provider_type="openai",
        default_model=None,
        api_base="https://api.example.com/v1",
        sort_priority=7,
        is_enabled=True,
        api_key="sk-secret",
        models=[_FakeModel("m1", "gpt-4o", True), _FakeModel("m2", "gpt-3.5", False)],
    )
    cfg = prov_api._db_provider_to_config(prov)
    assert cfg.name == "myProv"
    assert cfg.provider == router_mod.ProviderType.OPENAI
    assert cfg.model == "gpt-4o"  # falls back to first enabled model's model_id
    assert cfg.base_url == "https://api.example.com/v1"
    assert cfg.priority == 7
    assert cfg.enabled is True
    assert set(cfg.stages) == set(router_mod.StageName)
    assert cfg.api_key_env == "PROVIDER_DB_MYPROV_KEY"
    assert os.environ["PROVIDER_DB_MYPROV_KEY"] == "sk-secret"


def test_db_provider_unknown_type_falls_back_to_openai(monkeypatch):
    """Unknown DB provider_type maps to OPENAI (OpenAI-compatible gateways)."""
    monkeypatch.setattr(prov_api, "ProviderType", router_mod.ProviderType)
    prov = _FakeProvider(
        name="gw",
        provider_type="fcc_gateway",
        default_model="some-model",
        is_enabled=True,
        models=[],
    )
    cfg = prov_api._db_provider_to_config(prov)
    assert cfg.provider == router_mod.ProviderType.OPENAI


def test_reload_endpoint_registered():
    paths = {getattr(r, "path", "") for r in prov_api.router.routes}
    assert "/reload" in paths
