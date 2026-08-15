"""P0.3 DoD 测试 — 防止 reward-hacking 的整套闸门（真实可执行，不 mock 模型凑通过）。

对应执行手册 docs/EVOLUTION_ROADMAP.md P0.3 七项子任务验收标准：
  ① held_out_eval.py 冻结留出集调参者无法修改；② 双裁判+互不提议；③ ≥0.25 效应量
  ④ constitution 硬规则先于打分、高分但 WER 越界被拒；⑤ kill-switch 升级 rollback+prune
  ⑥ regression_suite 新失败入库后能拒绝其 producer；⑦ 元门禁 verify_meta_guard

红线 #1 主路径真实性：不 mock LLM 模型凑"通过"——本测试只验证**闸门机制**（被 Given
确定性的真指标/真规则会正确拦截/放行），不调用真实 LLM。候选评估通过注入纯函数
（candidate_eval_fn / judge_fn / regression_fn）模拟真值，符合 evaluate_promotion_anti_hack
的函数契约（这些函数本就是上层注入——生产里跑真 LLM，这里跑确定函数验证闸门逻辑）。
"""

from __future__ import annotations

import importlib

import pytest

from audiobook_studio.feedback import constitution as constitution_mod
from audiobook_studio.feedback import evolution_guard as ev_mod
from audiobook_studio.feedback import held_out_eval as held_mod
from audiobook_studio.feedback import promotion_gate as pg
from audiobook_studio.feedback import regression_suite as rs_mod


@pytest.fixture(autouse=True)
def _reset_singletons():
    """每个用例独占单例状态，避免 guard / suite 跨用例污染。"""
    ev_mod.reset_evolution_guard()
    rs_mod.reset_regression_suite()
    yield
    ev_mod.reset_evolution_guard()
    rs_mod.reset_regression_suite()


# ─────────────────────────────────────────────────────────────────────────────
# ① P0.3.1 冻结留出集：调参者无法修改
# ─────────────────────────────────────────────────────────────────────────────

class TestHeldOutImmutable:
    def _dataset(self):
        return held_mod.HeldOutDataset("edit_for_tts")

    def test_cases_is_tuple_immutable(self):
        ds = self._dataset()
        assert isinstance(ds.cases, tuple)
        with pytest.raises((TypeError, AttributeError)):
            ds.cases.append("x")  # tuple 无 append

    def test_reassign_private_frozen(self):
        ds = self._dataset()
        with pytest.raises(TypeError):
            setattr(ds, "_cases", (ds.cases[0],) if ds.cases else ())

    def test_reassign_public_attr_rejected(self):
        ds = self._dataset()
        with pytest.raises((TypeError, AttributeError)):
            setattr(ds, "cases", ())

    def test_by_id_readonly_mapping(self):
        ds = self._dataset()
        assert ds.by_id.__class__.__name__ == "mappingproxy"
        with pytest.raises(TypeError):
            ds.by_id["x"] = ds.cases[0] if ds.cases else None

    def test_manifest_signature_stable(self):
        """指纹在重复构造下稳定——篡改任一例即变。"""
        a = held_mod.HeldOutDataset("quality_check")
        b = held_mod.HeldOutDataset("quality_check")
        assert a.signature == b.signature
        assert a.manifest.case_count > 0
        assert a.manifest.origin_status == "loaded"


# ─────────────────────────────────────────────────────────────────────────────
# ② P0.3.2 双裁判 + 互不提议（双不同 provider 各打分；proposer 排除在裁判外）
# ─────────────────────────────────────────────────────────────────────────────

class TestDualJudge:
    def test_proposer_excluded_from_judges(self):
        dj = pg.DualJudgeEvaluator(
            judge_pool=["gpt-4o-mini", "deepseek-chat", "openrouter/auto"],
            proposer_model="gpt-4o-mini",
        )
        assert "gpt-4o-mini" not in dj.judge_models
        assert dj.can_dual_judge
        # 两个裁判必须是**不同** provider
        assert len(set(dj.judge_models)) == 2

    def test_disagreement_blocks_promotable_score(self):
        dj = pg.DualJudgeEvaluator(
            judge_pool=["a", "b"], disagreement_delta=0.25,
        )
        res = dj.evaluate(lambda jm, payload: 0.95 if jm == "a" else 0.30, {})
        assert res.mean is not None
        assert res.agreement is False
        assert res.promotable_score is None  # 分歧 → 无可晋升均分

    def test_agreement_gives_promotable_score(self):
        dj = pg.DualJudgeEvaluator(judge_pool=["a", "b"], disagreement_delta=0.25)
        res = dj.evaluate(lambda jm, payload: 0.80 if jm == "a" else 0.75, {})
        assert res.agreement is True
        assert res.promotable_score == pytest.approx(0.775)

    def test_unavailable_judge_no_fake_pass(self):
        """一位裁判抛错 → 全程不假通过（mean=None）。"""
        dj = pg.DualJudgeEvaluator(judge_pool=["a", "b"])
        def bad_fn(jm, payload):
            if jm == "a":
                raise RuntimeError("LLM down")
            return 0.9
        res = dj.evaluate(bad_fn, {})
        assert res.mean is None
        assert res.promotable_score is None


# ─────────────────────────────────────────────────────────────────────────────
# ③ P0.3.3 ≥0.25 效应量晋升（+0.1 不晋升、+0.3 晋升）
# ─────────────────────────────────────────────────────────────────────────────

class TestEffectSizeGate:
    def test_baseline_plus_025_boundary_promotes(self):
        ds = held_mod.HeldOutDataset("edit_for_tts")
        res = ds.evaluate_candidate(lambda c: 0.25, "cand", lambda c: 0.0, "base")
        assert res.effect_size == pytest.approx(0.25)
        assert res.beat_baseline_by_025 is True  # >=0.25 inclusive

    def test_baseline_plus_01_not_promote(self):
        ds = held_mod.HeldOutDataset("edit_for_tts")
        res = ds.evaluate_candidate(lambda c: 0.55, "cand", lambda c: 0.45, "base")
        assert res.effect_size == pytest.approx(0.10, abs=1e-6)
        assert res.beat_baseline_by_025 is False

    def test_baseline_plus_03_promotes(self):
        ds = held_mod.HeldOutDataset("edit_for_tts")
        res = ds.evaluate_candidate(lambda c: 0.80, "cand", lambda c: 0.50, "base")
        assert res.effect_size == pytest.approx(0.30)
        assert res.beat_baseline_by_025 is True


# ─────────────────────────────────────────────────────────────────────────────
# ④ P0.3.4 constitution：高分但 WER 越界被宪法拒（先于打分）
# ─────────────────────────────────────────────────────────────────────────────

class TestConstitutionHardRules:
    def _adj(self):
        return constitution_mod.ConstitutionAdjudicator(constitution_mod.Constitution())

    def test_high_opacity_but_bad_wer_rejected(self):
        """DoD：高分但 WER 变差的候选被宪法拒，而非被晋升。"""
        adj = self._adj()
        v = adj.adjudge(
            candidate_output="逐字朗读参考文本",
            reference_text="逐字朗读参考文本",
            audio_metrics={"mos": 4.5, "wer": 0.80, "issues": [], "status": "all-ran"},
        )
        assert v.passed is False
        assert any(x.rule == constitution_mod.HardRule.INTELLIGIBLE for x in v.violations)

    def test_bad_mos_rejected_as_clipping(self):
        v = self._adj().adjudge("文本", "文本", {"mos": 2.0, "wer": 0.05})
        assert v.passed is False
        assert any(x.rule == constitution_mod.HardRule.NO_CLIPPING_DISTORTION for x in v.violations)

    def test_missing_deps_honest_degrade_not_pass(self):
        """依赖缺失 → unable_to_judge=True, passed=False（绝不假通过）。"""
        v = self._adj().adjudge("逐字朗读参考文本", "逐字朗读参考文本", {})
        assert v.unable_to_judge is True
        assert v.passed is False

    def test_clean_passes(self):
        v = self._adj().adjudge(
            "逐字朗读参考文本 这是一段样例",
            "逐字朗读参考文本 这是一段样例",
            {"mos": 4.5, "wer": 0.05, "issues": [], "status": "all-ran"},
        )
        assert v.passed is True

    def test_constitution_thresholds_readonly(self):
        """阈值 via as_readonly() 为只读——调参者无法运行期改阈值绕过硬关。"""
        c = constitution_mod.Constitution()
        view = c.as_readonly()
        with pytest.raises(TypeError):
            view["wer_hard_cap"] = 0.99


# ─────────────────────────────────────────────────────────────────────────────
# ⑤ P0.3.5 kill-switch 升级为"回滚+剪枝"（连续 2 格退化 → 回滚基线 + 删后代）
# ─────────────────────────────────────────────────────────────────────────────

class TestEvolutionGuardRollbackPrune:
    def test_consecutive_regression_triggers_rollback_and_prune(self):
        g = ev_mod.EvolutionGuard(regression_streak=2, min_effect_to_promote=0.25)
        g.record("root", "edit_for_tts", 0.6, 0.30, "t0")
        g.record("c1", "edit_for_tts", 0.7, 0.40, "t1")
        assert g.active_id == "c1"
        # two consecutive regressions
        r1 = g.record("bad1", "edit_for_tts", 0.5, -0.20, "t2")
        assert r1 is None and g.regression_streak == 1
        r2 = g.record("bad2", "edit_for_tts", 0.48, -0.22, "t3")
        assert r2 is not None
        assert r2.rolled_back_from == "c1"
        assert r2.rolled_back_to == "root"
        assert g.active_id == "root"
        assert "c1" in r2.pruned_node_ids
        assert g.is_pruned("c1")

    def test_single_regression_does_not_rollback(self):
        g = ev_mod.EvolutionGuard(regression_streak=2)
        g.record("root", "edit_for_tts", 0.6, 0.30, "t0")
        r = g.record("bad1", "edit_for_tts", 0.5, -0.10, "t1")
        assert r is None
        assert g.active_id == "root"  # not rolled back, streak 1


# ─────────────────────────────────────────────────────────────────────────────
# ⑥ P0.3.6 regression_suite：新失败入库后能拒绝其 producer
# ─────────────────────────────────────────────────────────────────────────────

class TestRegressionSuite:
    def test_new_failure_added_then_rejects_its_producer(self):
        """DoD：新失败入库后能拒绝其 producer。

        auto_add_new 在候选于某 active 坏例上下文里**评估中暴露**新失败时触发——
        需要至少一个 active 案例（无上下文即无失败可触发）。故此处先种一例历史坏例。
        """
        s = rs_mod.RegressionSuite()
        s.add_failure("edit_for_tts", "历史坏例：读错引号", {"text": "x"}, producer_id="prev")
        nf = rs_mod.KnownFailure("", "edit_for_tts", "破音复现", {"audio": "x"}, producer_id="cand_x")
        # check_candidate 在历史坏例上下文里让 cand_x 暴露该新失败
        verdict = s.check_candidate(
            "cand_x", lambda case: (False, nf), auto_add_new=True,
        )
        assert verdict.rejected
        assert len(verdict.new_failures_added) == 1
        fid = verdict.new_failures_added[0]
        # 该失败已入库
        assert s.is_known_failure(fid)
        # 且能通过 failures_by_producer 拒绝其 producer
        prods = s.failures_by_producer("cand_x")
        assert any(f.failure_id == fid for f in prods)

    def test_known_regression_rejects_candidate(self):
        s = rs_mod.RegressionSuite()
        f = s.add_failure("edit_for_tts", "读错引号", {"text": "x"}, producer_id="prev")
        verdict = s.check_candidate(
            "cand", lambda case: (case.failure_id == f.failure_id, None),
        )
        assert verdict.rejected
        assert f.failure_id in verdict.regressed_on

    def test_passing_candidate_approved(self):
        s = rs_mod.RegressionSuite()
        s.add_failure("edit_for_tts", "坏例", {"text": "x"}, producer_id="prev")
        verdict = s.check_candidate("cand", lambda case: (False, None))
        assert verdict.passed


# ─────────────────────────────────────────────────────────────────────────────
# ⑦ P0.3.7 元门禁 verify_meta_guard：尺度文件对进化循环只读
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaGuard:
    def test_clean_change_set(self):
        result = pg.verify_meta_guard(["src/elsewhere/foo.py", "docs/bar.md", "README.md"])
        assert result["clean"] is True
        assert result["touched"] == []

    def test_touching_scale_file_flagged_not_auto_pass(self):
        result = pg.verify_meta_guard([
            "src/main.py",
            "src/audiobook_studio/feedback/constitution.py",  # 宪法
            "tests/golden/edit_for_tts/case_1.json",          # 评估集
            "src/audiobook_studio/quality/metrics.py",         # 指标定义
        ])
        assert result["clean"] is False
        assert len(result["touched"]) == 3

    def test_prompts_dir_treated_readonly(self):
        result = pg.verify_meta_guard(["prompts/edit_for_tts/v2.j2"])
        assert result["clean"] is False

    def test_meta_guard_paths_include_constitution_held_out_metrics(self):
        paths = set(pg.META_GUARD_READONLY_PATHS)
        # 尺度的三大支柱：宪法 / 留出集 / 硬指标定义
        assert any("constitution.py" in p for p in paths)
        assert any("held_out_eval.py" in p for p in paths)
        assert any("quality/metrics.py" in p for p in paths)
        assert "tests/golden/" in paths


# ─────────────────────────────────────────────────────────────────────────────
# 主 DoD：evaluate_promotion_anti_hack —— 一个 reward-hack 候选被拒绝/回滚而非晋升
# ─────────────────────────────────────────────────────────────────────────────

class TestEvaluatePromotionAntiHack:
    @staticmethod
    def _kwargs(**override):
        base = dict(
            stage="edit_for_tts", candidate_id="c",
            candidate_output_text="逐字朗读参考文本 这是一段样例",
            reference_text="逐字朗读参考文本 这是一段样例",
            audio_metrics={"mos": 4.5, "wer": 0.05, "issues": [], "status": "all-ran"},
            candidate_payload={},
            judge_fn=lambda jm, payload: 0.85,
            baseline_fn=lambda case: 0.5,
            candidate_eval_fn=lambda case: 0.80,
            proposer_model="gpt-4o-mini",
            regression_fn=lambda case: (False, None),
            promoted_at="t", config_digest="d", new_version=2,
        )
        base.update(override)
        return base

    def test_reward_hack_high_judge_bad_wer_rejected(self):
        """核心 DoD：LLM 自评分很高但 WER 变差 → 被拒绝而非晋升。"""
        v = pg.evaluate_promotion_anti_hack(
            **self._kwargs(
                judge_fn=lambda jm, payload: 0.95,   # LLM 自评高分
                audio_metrics={"mos": 2.0, "wer": 0.80, "issues": [], "status": "all-ran"},  # 真指标差
                candidate_eval_fn=lambda case: 0.95,
            )
        )
        assert v.passed is False
        assert v.constitution["passed"] is False
        # 被宪法先于打分拒绝
        assert any(x["rule"] in ("intelligible", "no_clipping") for x in v.constitution["violations"])

    def test_clean_candidate_with_025_effect_promotes(self):
        v = pg.evaluate_promotion_anti_hack(**self._kwargs(candidate_eval_fn=lambda case: 0.80))
        assert v.passed is True
        assert v.beat_baseline_by_025 is True
        assert v.effect_size == pytest.approx(0.30)
        assert v.promoted_node_id is not None

    def test_marginal_010_effect_not_promote(self):
        v = pg.evaluate_promotion_anti_hack(
            **self._kwargs(candidate_eval_fn=lambda case: 0.60)
        )
        assert v.passed is False
        assert v.beat_baseline_by_025 is False
        assert v.effect_size == pytest.approx(0.10, abs=1e-6)

    def test_judge_disagreement_blocks_promotion(self):
        v = pg.evaluate_promotion_anti_hack(
            **self._kwargs(
                judge_fn=lambda jm, payload: 0.95 if jm == "gpt-4o-mini" else 0.30,
                proposer_model="other-model",
                judge_pool=["gpt-4o-mini", "deepseek-chat"],
                candidate_eval_fn=lambda case: 0.90,  # effect fine
            )
        )
        assert v.passed is False
        assert v.dual_judge.get("proposer_not_judge") is True
