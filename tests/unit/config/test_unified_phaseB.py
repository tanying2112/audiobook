"""Phase B structural tests for config/unified.py (UnifiedConfig).

Covers priority-based config resolution, YAML/TOML/docker-compose loading,
env interpolation, section merging, provider/redis/db/llm/tts config
consolidation, validation, and sensitive masking. External Settings and
filesystem are mocked/faked for determinism.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.audiobook_studio.config.unified import (
    UnifiedConfig,
    dump_config,
    get_config,
    get_database_config,
    get_hardware_profile,
    get_llm_config,
    get_llm_providers_config,
    get_pipeline_config,
    get_redis_config,
    get_tts_config,
    get_unified_config,
    reset_unified_config,
    validate_config,
)


class FakeSettings:
    """Minimal stand-in for pydantic Settings used by UnifiedConfig."""

    def __init__(self, **kwargs):
        self._data = {
            "DATABASE_URL": "sqlite+aiosqlite:///./test.db",
            "SQL_ECHO": "false",
            "REDIS_URL": "redis://localhost:6379/0",
            "REDIS_MAX_CONNECTIONS": 50,
            "REDIS_POOL_SIZE": 10,
            "REDIS_SOCKET_KEEPALIVE": True,
            "REDIS_RETRY_ON_TIMEOUT": True,
            "MOCK_LLM": False,
            "ENABLE_LOCAL_TTS": True,
            "KOKORO_MODEL_PATH": "/models/kokoro",
            "EDGE_TTS_VOICE": "zh-CN-XiaoxiaoNeural",
            "GROQ_API_KEY": "groq-secret-key",
            "OPENAI_API_KEY": "",
        }
        self._data.update(kwargs)

    def __getattr__(self, name):
        if name in self._data:
            return self._data[name]
        raise AttributeError(name)

    def model_dump(self):
        return dict(self._data)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def validate_jwt_secret(self):
        if not self._data.get("JWT_SECRET"):
            raise RuntimeError("JWT secret missing")
        return True

    def validate_cors_security(self):
        if self._data.get("CORS_ORIGINS") == "*":
            raise RuntimeError("CORS too permissive")
        return True


@pytest.fixture
def cfg(tmp_path: Path):
    c = UnifiedConfig(project_root=tmp_path)
    c._settings = FakeSettings()
    return c


@pytest.fixture
def patched_llm_config():
    """Make the env-mocked LLMProvidersConfig/ProviderConfig accept the
    production code's keyword constructor calls."""
    import sys
    from types import SimpleNamespace

    mod = sys.modules["src.audiobook_studio.llm.config_loader"]
    orig_llm = mod.LLMProvidersConfig
    orig_pc = mod.ProviderConfig

    def llm_factory(**kwargs):
        ns = SimpleNamespace(**kwargs)
        ns.get_providers_for_stage = lambda stage: ns.providers
        ns.get_all_enabled = lambda: ns.providers
        return ns

    mod.LLMProvidersConfig = llm_factory
    mod.ProviderConfig = lambda **kw: SimpleNamespace(**kw)
    yield
    mod.LLMProvidersConfig = orig_llm
    mod.ProviderConfig = orig_pc


def test_interpolate_brace_format(cfg, monkeypatch) -> None:
    monkeypatch.setenv("MY_VAR", "value123")
    assert cfg._interpolate_env("prefix-${MY_VAR}-suffix") == "prefix-value123-suffix"


def test_interpolate_simple_format(cfg, monkeypatch) -> None:
    monkeypatch.setenv("MY_TOKEN", "abc")
    assert cfg._interpolate_env("tok=$MY_TOKEN") == "tok=abc"


def test_interpolate_unknown_var_kept(cfg, monkeypatch) -> None:
    monkeypatch.delenv("DOES_NOT_EXIST_X", raising=False)
    assert cfg._interpolate_env("x=${DOES_NOT_EXIST_X}") == "x=${DOES_NOT_EXIST_X}"


def test_interpolate_escaped_dollar(cfg, monkeypatch) -> None:
    monkeypatch.delenv("VAR", raising=False)
    assert cfg._interpolate_env("$$VAR") == "$$VAR"


# ── nested get ──────────────────────────────────────────────────────────────


def test_get_nested_found() -> None:
    data = {"a": {"b": {"c": 42}}}
    assert UnifiedConfig()._get_nested(data, ["a", "b", "c"]) == 42


def test_get_nested_missing() -> None:
    data = {"a": {"b": 1}}
    assert UnifiedConfig()._get_nested(data, ["a", "x"]) is None


def test_get_nested_non_dict() -> None:
    data = {"a": 5}
    assert UnifiedConfig()._get_nested(data, ["a", "b"]) is None


# ── get priority resolution ────────────────────────────────────────────────


def test_get_env_highest_priority(cfg, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "env-override")
    assert cfg.get("database.url") == "env-override"


def test_get_from_settings(cfg) -> None:
    assert cfg.get("redis.url") == "redis://localhost:6379/0"


def test_get_from_yaml(cfg, tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "tts_providers.yaml").write_text("kokoro:\n  model: test-model\n")
    assert cfg.get("kokoro.model") == "test-model"


def test_get_default(cfg) -> None:
    assert cfg.get("nonexistent.key", "fallback") == "fallback"


# ── YAML loading ────────────────────────────────────────────────────────────


def test_load_yaml_config_present(cfg, tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.yaml").write_text("steps:\n  - a\n  - b\n")
    data = cfg.load_yaml_config("pipeline")
    assert data["steps"] == ["a", "b"]


def test_load_yaml_config_yml_extension(cfg, tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.yml").write_text("x: 1\n")
    assert cfg.load_yaml_config("pipeline") == {"x": 1}


def test_load_yaml_config_missing(cfg) -> None:
    assert cfg.load_yaml_config("nope") == {}


def test_load_yaml_config_cached(cfg, tmp_path) -> None:
    (tmp_path / "config").mkdir()
    p = tmp_path / "config" / "pipeline.yaml"
    p.write_text("v: 1\n")
    assert cfg.load_yaml_config("pipeline") is cfg.load_yaml_config("pipeline")


def test_load_yaml_config_parse_error(cfg, tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.yaml").write_text("::: not valid: [\n")
    assert cfg.load_yaml_config("pipeline") == {}


def test_load_yaml_config_non_dict(cfg, tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.yaml").write_text("- just\n- a\n- list\n")
    assert cfg.load_yaml_config("pipeline") == {}


def test_load_all_yaml_configs_excludes(cfg, tmp_path) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "pipeline.yaml").write_text("a: 1\n")
    (cfg_dir / "quality_thresholds.yaml").write_text("b: 2\n")
    (cfg_dir / "agent_sop.yaml").write_text("c: 3\n")
    (cfg_dir / "pipeline.yaml.bak").write_text("d: 4\n")
    configs = cfg.load_all_yaml_configs()
    assert "pipeline" in configs
    assert "quality_thresholds" in configs
    assert "agent_sop" not in configs
    assert "pipeline.yaml.bak" not in configs


# ── LLM providers ───────────────────────────────────────────────────────────


def test_load_llm_providers_empty_returns_defaults(cfg, tmp_path, patched_llm_config) -> None:
    (tmp_path / "config").mkdir()
    result = cfg.load_llm_providers()
    assert result is not None
    assert getattr(result, "providers", None) == [] or isinstance(result, dict)


def test_load_llm_providers_parsed(cfg, tmp_path, patched_llm_config) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "llm_providers.yaml").write_text(
        "providers:\n"
        "  - name: groq\n"
        "    provider: groq\n"
        "    model: llama3\n"
        "    stages: [extract]\n"
        "    priority: 10\n"
        "fallback: {}\n"
        "cost_control: {}\n"
        "prompt_compression: {}\n"
    )
    result = cfg.load_llm_providers()
    assert len(result.providers) == 1
    assert result.providers[0].name == "groq"


def test_load_llm_providers_cached(cfg, tmp_path, patched_llm_config) -> None:
    (tmp_path / "config").mkdir()
    assert cfg.load_llm_providers() is cfg.load_llm_providers()


# ── docker compose ──────────────────────────────────────────────────────────


def test_load_docker_compose_present(cfg, tmp_path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services:\n  api:\n    image: x\n")
    assert cfg.load_docker_compose()["services"]["api"]["image"] == "x"


def test_load_docker_compose_missing(cfg) -> None:
    assert cfg.load_docker_compose() == {}


def test_load_docker_compose_cached(cfg, tmp_path) -> None:
    f = tmp_path / "docker-compose.yml"
    f.write_text("services:\n  api:\n    image: x\n")
    assert cfg.load_docker_compose() is cfg.load_docker_compose()


def test_load_all_docker_compose(cfg, tmp_path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services:\n  api:\n    image: a\n")
    (tmp_path / "docker-compose.worker.yml").write_text("services:\n  worker:\n    image: b\n")
    configs = cfg.load_all_docker_compose()
    assert "default" in configs
    assert "worker" in configs


def test_get_service_env_dict(cfg, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SERVICE_SECRET", "shh")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n" "  api:\n" "    environment:\n" "      KEY1: value1\n" "      KEY2: ${SERVICE_SECRET}\n"
    )
    env = cfg.get_service_env("api")
    assert env["KEY1"] == "value1"
    assert env["KEY2"] == "shh"


def test_get_service_env_list(cfg, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SVC_TOKEN", "tok")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n" "  worker:\n" "    environment:\n" "      - FOO=bar\n" "      - TOKEN=${SVC_TOKEN}\n"
    )
    env = cfg.get_service_env("worker")
    assert env["FOO"] == "bar"
    assert env["TOKEN"] == "tok"


# ── pyproject ───────────────────────────────────────────────────────────────


def test_load_pyproject_present(cfg, tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest]\naddopts = '-q'\n[project]\nname = 'x'\n")
    data = cfg.load_pyproject()
    assert data["project"]["name"] == "x"


def test_load_pyproject_missing(cfg) -> None:
    assert cfg.load_pyproject() == {}


def test_load_pyproject_cached(cfg, tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert cfg.load_pyproject() is cfg.load_pyproject()


def test_get_tool_config(cfg, tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    assert cfg.get_tool_config("ruff", "line-length") == 100


def test_get_tool_config_missing(cfg, tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert cfg.get_tool_config("ruff", "nope") is None


# ── sections ────────────────────────────────────────────────────────────────


def test_get_section_combines(cfg, tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.yaml").write_text("steps: [a]\n")
    (tmp_path / "docker-compose.yml").write_text("services:\n  redis:\n    environment:\n      REDIS_HOST: localhost\n")
    section = cfg.get_section("redis")
    assert "REDIS_URL" in section
    assert "redis.REDIS_HOST" in section


def test_get_section_settings_match(cfg) -> None:
    section = cfg.get_section("database")
    assert "DATABASE_URL" in section


# ── consolidated config getters ─────────────────────────────────────────────


def test_get_database_config(cfg) -> None:
    db = cfg.get_database_config()
    assert db["url"] == "sqlite+aiosqlite:///./test.db"
    assert db["sync_url"] == "sqlite:///./test.db"
    assert db["pool_recycle"] == 3600


def test_async_to_sync_variants(cfg) -> None:
    assert cfg._get_async_to_sync_url("sqlite+aiosqlite:///x") == "sqlite:///x"
    assert cfg._get_async_to_sync_url("sqlite+aiosqlite://x") == "sqlite://x"
    assert cfg._get_async_to_sync_url("postgresql+asyncpg://u@h/db") == "postgresql://u@h/db"
    assert cfg._get_async_to_sync_url("postgresql+psycopg2://u@h/db") == "postgresql://u@h/db"
    assert cfg._get_async_to_sync_url("mysql://x") == "mysql://x"


def test_get_redis_config(cfg) -> None:
    rc = cfg.get_redis_config()
    assert rc["url"] == "redis://localhost:6379/0"
    assert rc["max_connections"] == 50


def test_get_llm_config(cfg) -> None:
    lc = cfg.get_llm_config()
    assert lc["mock_mode"] is False
    assert lc["providers"]["groq"] == "groq-secret-key"


def test_get_tts_config(cfg, tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "tts_providers.yaml").write_text("kokoro:\n  enabled: true\n")
    tc = cfg.get_tts_config()
    assert tc["enable_local"] is True
    assert tc["kokoro"]["enabled"] is True


def test_get_pipeline_config(cfg, tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.yaml").write_text("steps: [a, b]\n")
    assert cfg.get_pipeline_config()["steps"] == ["a", "b"]


def test_get_hardware_profile(cfg, tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "hardware_profile.yaml").write_text("gpu: false\n")
    assert cfg.get_hardware_profile()["gpu"] is False


# ── validation ──────────────────────────────────────────────────────────────


def test_validate_all_with_issues(cfg, tmp_path) -> None:
    cfg._settings = FakeSettings(CORS_ORIGINS="*")
    issues = cfg.validate_all()
    assert any(i.startswith("JWT") for i in issues)
    assert any(i.startswith("CORS") for i in issues)
    assert any("Missing required" in i for i in issues)


def test_validate_all_clean(cfg, tmp_path) -> None:
    cfg._settings = FakeSettings(JWT_SECRET="enough", CORS_ORIGINS="http://localhost")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.yaml").write_text("x: 1\n")
    (tmp_path / "config" / "quality_thresholds.yaml").write_text("y: 2\n")
    assert cfg.validate_all() == []


# ── dump / masking ──────────────────────────────────────────────────────────


def test_mask_sensitive_dict(cfg) -> None:
    data = {"api_key": "abcdefghij", "name": "ok"}
    masked = cfg._mask_sensitive(data)
    assert masked["api_key"] == "abcd****ghij"
    assert masked["name"] == "ok"


def test_mask_sensitive_short(cfg) -> None:
    assert cfg._mask_sensitive({"token": "abc"})["token"] == "****"


def test_mask_sensitive_nested(cfg) -> None:
    data = {"db": {"password": "longpassword"}, "list": [{"secret": "supersecret"}]}
    masked = cfg._mask_sensitive(data)
    assert masked["db"]["password"] == "long****word"
    assert masked["list"][0]["secret"] == "supe****cret"


def test_dump_all(cfg, tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.yaml").write_text("steps: [a]\n")
    dumped = cfg.dump_all()
    assert "settings" in dumped
    assert "yaml_configs" in dumped


# ── global singleton + convenience functions ────────────────────────────────


def test_get_unified_config_singleton(tmp_path) -> None:
    reset_unified_config()
    c1 = get_unified_config()
    c2 = get_unified_config()
    assert c1 is c2
    reset_unified_config()


def test_convenience_functions(tmp_path, patched_llm_config) -> None:
    reset_unified_config()
    c = get_unified_config()
    c._settings = FakeSettings()
    c.project_root = tmp_path
    assert get_config("redis.url") == "redis://localhost:6379/0"
    assert get_database_config()["sync_url"].startswith("sqlite://")
    assert get_redis_config()["max_connections"] == 50
    assert get_llm_config()["providers"]["groq"] == "groq-secret-key"
    assert get_pipeline_config() == {}
    assert get_hardware_profile() == {}
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "tts_providers.yaml").write_text("kokoro:\n  enabled: true\n")
    assert get_tts_config()["kokoro"]["enabled"] is True
    assert get_llm_providers_config() is not None
    reset_unified_config()


def test_get_llm_providers_config_method(cfg, patched_llm_config) -> None:
    assert cfg.get_llm_providers_config() is not None


def test_validate_config_module(patched_llm_config) -> None:
    reset_unified_config()
    c = get_unified_config()
    c._settings = FakeSettings(JWT_SECRET="x", CORS_ORIGINS="http://localhost")
    c.project_root = Path("/tmp")
    issues = validate_config()
    assert isinstance(issues, list)
    reset_unified_config()


def test_dump_config_module(patched_llm_config, tmp_path) -> None:
    reset_unified_config()
    c = get_unified_config()
    c._settings = FakeSettings()
    c.project_root = tmp_path
    d = dump_config()
    assert "settings" in d
    reset_unified_config()
