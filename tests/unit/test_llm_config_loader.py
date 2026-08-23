"""P2.15/#45 覆盖率增益 — llm/config_loader.py 真触测 (该模块此前 0% 覆盖).

**真因链 (双盲核实坐实)**:
- 既有 test_config_loader.py / test_config_loader_isolated.py 实测的是 *config/loader.py*
  (不同模块的 ConfigLoader), 非 *llm/config_loader.py* (LLMProvidersConfig).
- conftest_minimal.py 在 import 期就把 `audiobook_studio.llm.config_loader` 全模块
  mock 成 MockLLMProvidersConfig (load 返回 mock-gpt, ProviderType/StageName 是
  MagicMock). 故任何 `from audiobook_studio.llm.config_loader import X` 的测, 拿到的是
  mock → 真代码不执行 → coverage 0% (即使有测触也测不到真文件).

**解法 (importlib 隔离 -- 真触非 mock)**:
本测用 importlib.util.spec_from_file_location 直接加载真实文件, 用一个不被 conftest
拦截的唯一模块名 (conftest_minimal 只 mock 两个明名 "audiobook_studio.llm.config_loader"
/ "src.audiobook_studio.llm.config_loader"), 这样真代码执行, coverage 追踪真文件.

红线A: 真触非 mock — 经 importlib 加载真实源文件路径, 类/方法/枚举全取自真模块 m,
  不用 conftest 注入的 mock 版. 已用 coverage 针对 --include 验真从 0% 物理可达 77%+.

低于 pyproject fail_under=80%: 探针单独跑触发 CoverageError, 但本测隶属测试套件,
  全套 coverage run 用 --include 口径计总分 (77.60% 基线); 单模块 fail-under 不应用
  到单测运行 (coverage report 无 --fail-under). 见 #45 SSOT 诚实口径.
"""

from __future__ import annotations

import importlib.util
import tempfile
import textwrap
from pathlib import Path

import pytest

# 仓库根 (tests/unit/xxx.py → parents[2] = repo root)
_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src" / "audiobook_studio" / "llm" / "config_loader.py"
_PROBE_MOD = "real_llm_config_loader_via_importlib"  # 唯一名, 不被 conftest 拦截


def _load_real() -> object:
    """importlib 隔离加载真 llm/config_loader.py → module.

    唯一模块名绕过 conftest_minimal 的全模块 mock (它只 mock 两个明名).
    反复加载返回同模块 (Python cache spec); 这里每测新建以隔离跨测状态.
    """
    spec = importlib.util.spec_from_file_location(_PROBE_MOD, _SRC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_yaml(tmp_path: Path, body: str) -> str:
    p = tmp_path / "llm_providers.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


# ── 1. 枚举 (真实值, 非 MagicMock) ─────────────────────────────────────
class TestProviderTypeStageNameEnums:
    def test_provider_type_values(self):
        m = _load_real()
        assert m.ProviderType.GROQ.value == "groq"
        assert m.ProviderType.ANTHROPIC.value == "anthropic"
        assert m.ProviderType("gemini") is m.ProviderType.GEMINI
        # str-Enum: 枚举成员 str() 在此 pydantic-settings 加载下返回
        # "ProviderType.GROQ" (实测此环境), .value 才是 'groq'; .value 已断言上.
        assert m.ProviderType.GROQ == "groq"  # str-Enum 可与 str 等比 (值等)

    def test_stage_name_values(self):
        m = _load_real()
        assert m.StageName.EXTRACT.value == "extract"
        assert m.StageName("annotate_paragraph") is m.StageName.ANNOTATE_PARAGRAPH
        assert m.StageName.JUDGE.value == "judge"


# ── 2. ProviderConfig 三方法 (真 os.getenv, 非 mock) ─────────────────────
class TestProviderConfigKeyMethods:
    def _make(self, **kw):
        m = _load_real()
        base = dict(name="p1", provider=m.ProviderType.GROQ, model="llama-3.3-70b")
        base.update(kw)
        return m.ProviderConfig(**base), m

    def test_get_api_key_reads_env(self, monkeypatch):
        cfg, _ = self._make(api_key_env="MY_KEY")
        monkeypatch.setenv("MY_KEY", "secret-123")
        assert cfg.get_api_key() == "secret-123"

    def test_get_api_key_none_when_no_env_var(self, monkeypatch):
        cfg, _ = self._make(api_key_env="MISSING_KEY_XYZ")
        monkeypatch.delenv("MISSING_KEY_XYZ", raising=False)
        assert cfg.get_api_key() is None

    def test_get_api_key_none_when_no_env_name(self):
        cfg, _ = self._make()  # 无 api_key_env
        assert cfg.get_api_key() is None

    def test_get_api_key_pool_merges_primary_and_pool(self, monkeypatch):
        cfg, _ = self._make(api_key_env="PL_KEY_A", api_key_pool_env=["PL_KEY_B", "PL_KEY_C"])
        monkeypatch.setenv("PL_KEY_A", "ka")
        monkeypatch.setenv("PL_KEY_C", "kc")
        monkeypatch.delenv("PL_KEY_B", raising=False)
        pool = cfg.get_api_key_pool()
        assert "ka" in pool and "kc" in pool
        assert "kb" not in pool  # 缺 env 的不入 pool

    def test_get_api_key_pool_empty_when_no_env(self):
        cfg, _ = self._make()
        assert cfg.get_api_key_pool() == []

    def test_litellm_model_name_groq_prefix(self):
        m = _load_real()
        cfg = m.ProviderConfig(name="x", provider=m.ProviderType.GROQ, model="llama")
        assert cfg.get_litellm_model_name() == "groq/llama"

    def test_litellm_model_name_openai_no_prefix(self):
        m = _load_real()
        cfg = m.ProviderConfig(name="x", provider=m.ProviderType.OPENAI, model="gpt-4o")
        assert cfg.get_litellm_model_name() == "gpt-4o"

    def test_litellm_model_name_cerebras_uses_openai_prefix(self):
        m = _load_real()
        cfg = m.ProviderConfig(name="x", provider=m.ProviderType.CEREBRAS, model="llama3.1")
        assert cfg.get_litellm_model_name() == "openai/llama3.1"

    def test_litellm_model_name_anthropic_prefix(self):
        m = _load_real()
        cfg = m.ProviderConfig(name="x", provider=m.ProviderType.ANTHROPIC, model="claude")
        assert cfg.get_litellm_model_name() == "anthropic/claude"


# ── 3. LLMProvidersConfig.load() 真 yaml 加载 + 排序 + 默认 ─────────────
class TestLLMProvidersConfigLoad:
    def test_load_real_yaml_parses_providers_and_sorts_by_priority(self, tmp_path):
        m = _load_real()
        path = _write_yaml(
            tmp_path,
            """
            providers:
              - name: low_pri
                provider: groq
                model: m-a
                priority: 50
                stages: [extract]
              - name: high_pri
                provider: gemini
                model: m-b
                priority: 10
                stages: [analyze, judge]
            prompt_compression:
              max_input_tokens: 8000
            fallback:
              max_retries_per_provider: 3
            cost_control:
              daily_limit_usd: 5.0
            """,
        )
        cfg = m.LLMProvidersConfig.load(path)
        # 按优先级升序 (低数 = 高优先 → high_pri 在前)
        assert cfg.providers[0].name == "high_pri"
        assert cfg.providers[1].name == "low_pri"
        assert cfg.providers[0].model == "m-b"
        assert cfg.providers[1].provider is m.ProviderType.GROQ
        assert m.StageName.EXTRACT in cfg.providers[1].stages
        # 嵌套配置真解析
        assert cfg.prompt_compression.max_input_tokens == 8000
        assert cfg.fallback.max_retries_per_provider == 3
        assert cfg.cost_control.daily_limit_usd == 5.0

    def test_load_defaults_for_missing_sections(self, tmp_path):
        m = _load_real()
        path = _write_yaml(
            tmp_path,
            """
            providers:
              - name: only
                provider: openai
                model: gpt
            """,
        )
        cfg = m.LLMProvidersConfig.load(path)
        assert len(cfg.providers) == 1
        # 缺 section → 各 Config 默认
        assert cfg.fallback.max_retries_per_provider == 2
        assert cfg.cost_control.alert_threshold == 0.8
        assert cfg.prompt_compression.max_input_tokens == 4000
        # 缺 priority/enabled/stages → 默认
        assert cfg.providers[0].priority == 100
        assert cfg.providers[0].enabled is True
        assert cfg.providers[0].stages == []

    def test_load_empty_providers(self, tmp_path):
        m = _load_real()
        path = _write_yaml(tmp_path, "providers: []\n")
        cfg = m.LLMProvidersConfig.load(path)
        assert cfg.providers == []
        assert cfg.get_all_enabled() == []

    def test_get_providers_for_stage_filters_by_stage(self, tmp_path):
        m = _load_real()
        path = _write_yaml(
            tmp_path,
            """
            providers:
              - name: extract_only
                provider: groq
                model: m1
                priority: 10
                stages: [extract]
              - name: judge_only
                provider: openai
                model: m2
                priority: 20
                stages: [judge]
              - name: both
                provider: gemini
                model: m3
                priority: 30
                stages: [extract, judge]
                enabled: true
              - name: disabled
                provider: openai
                model: m4
                priority: 5
                stages: [extract]
                enabled: false
            """,
        )
        cfg = m.LLMProvidersConfig.load(path)
        extract = cfg.get_providers_for_stage(m.StageName.EXTRACT)
        names = [p.name for p in extract]
        # extract_only + both 均在, 按优先级升序; disabled 不在
        assert names == ["extract_only", "both"]
        assert "disabled" not in names
        assert "judge_only" not in names

    def test_get_all_enabled_excludes_disabled(self, tmp_path):
        m = _load_real()
        path = _write_yaml(
            tmp_path,
            """
            providers:
              - {name: aaaa_probe, provider: groq, model: m}
              - {name: bbbb_probe, provider: openai, model: m, enabled: false}
            """,
        )
        cfg = m.LLMProvidersConfig.load(path)
        active = [p.name for p in cfg.get_all_enabled()]
        assert active == ["aaaa_probe"]

    def test_provider_extra_params_pass_through(self, tmp_path):
        m = _load_real()
        path = _write_yaml(
            tmp_path,
            """
            providers:
              - name: p
                provider: anthropic
                model: claude
                extra_params:
                  custom_field: hello
                  max_retries_literal: 7
            """,
        )
        cfg = m.LLMProvidersConfig.load(path)
        assert cfg.providers[0].extra_params == {"custom_field": "hello", "max_retries_literal": 7}

    def test_load_explicit_none_path_falls_back_to_repo_config(self):
        """load(None) 走 PathPriority 解析仓库 config/llm_providers.yaml (真文件存在)."""
        m = _load_real()
        cfg = m.LLMProvidersConfig.load(None)
        # 仓库真实 config 至少有 local_fcc_gateway (见 config/llm_providers.yaml L11)
        names = [p.name for p in cfg.providers]
        assert "local_fcc_gateway" in names
        assert len(names) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
