"""
Mock-backed coverage tests for the feedback critics package.

Seam used to inject the mock LLM
---------------------------------
SemanticCritic / StructuralCritic accept an ``LLMRouter`` via their public
constructor (``router=``).  We pass a :class:`MockRouter` whose ``call()``
returns a small object exposing ``.output`` set to a canned ``CriticResult``.
This mirrors exactly what ``self.router.call(...)`` returns in production
(``LLMCallResult.output``).

ObjectiveCritic.evaluate() does NOT use the router; it delegates metric
computation to ``QualityCheckSuite`` (real audio models).  To stay hermetic we
monkeypatch the *instance* method ``ObjectiveCritic._compute_objective_metrics``
to return canned metric dicts, then exercise the real scoring/confidence/fusion
code paths.

"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from audiobook_studio.feedback.critics import (
    BaseCritic,
    CriticEnsemble,
    CriticEnsembleEvaluator,
    CriticResult,
    CriticType,
    CriticVerdict,
)
from audiobook_studio.feedback.critics import (
    ObjectiveCritic,
    SemanticCritic,
    StructuralCritic,
)
from audiobook_studio.feedback.critics import SyntheticCritic, create_synthetic_critic
from audiobook_studio.feedback.critics.synthetic_critic import (
    CalibrationResult,
    CalibrationSample,
    _compute_confusion_matrix,
    _compute_f1_per_class,
)
from audiobook_studio.schemas import ParagraphAnnotation, TtsRoutingDecision


# Prompts live at the repo root (src-layout); the critics resolve prompt_dir
# relative to the package, so we point them at the real templates explicitly
# via the public ``prompt_dir`` constructor argument (the DI seam).
PROMPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


# ═══════════════════════════════════════════════════════════════════════════
# Mock LLM router seam
# ═══════════════════════════════════════════════════════════════════════════


class _CallResult:
    """Mimics ``LLMCallResult`` — exposes ``.output``."""

    def __init__(self, output):
        self.output = output


class MockRouter:
    """Injectable seam for SemanticCritic / StructuralCritic."""

    def __init__(self, output=None, side_effect=None):
        self.output = output
        self.side_effect = side_effect
        self.calls = []

    def call(self, stage, response_model, messages, **kwargs):
        self.calls.append((stage, response_model, messages))
        if self.side_effect is not None:
            raise self.side_effect
        return _CallResult(self.output)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures: minimal annotation / routing objects
# ═══════════════════════════════════════════════════════════════════════════


def _make_annotation():
    return ParagraphAnnotation(
        paragraph_index=0,
        text="你好，世界。",
        speaker_canonical_name="_narrator_",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        confidence=0.9,
    )


def _make_routing():
    return TtsRoutingDecision(
        segment_id="book_ch1_p0",
        engine_choice="kokoro",
        voice_id="voice_narrator",
        fallback_engine="edge",
        reasoning="default",
        estimated_cost_usd=0.01,
        contract_version=1,
    )


def _sem(router, config=None):
    """Build a SemanticCritic and neutralise the template's undefined ``schema_json`` global."""
    c = SemanticCritic(router=router, config=config or {}, prompt_dir=PROMPT_DIR)
    c.jinja_env.globals["schema_json"] = "{}"
    return c


def _str(router, config=None):
    """Build a StructuralCritic and neutralise the template's undefined ``schema_json`` global."""
    c = StructuralCritic(router=router, config=config or {}, prompt_dir=PROMPT_DIR)
    c.jinja_env.globals["schema_json"] = "{}"
    return c


# ═══════════════════════════════════════════════════════════════════════════
# Concrete BaseCritic subclass (BaseCritic is abstract)
# ═══════════════════════════════════════════════════════════════════════════


class _ConcreteCritic(BaseCritic):
    def evaluate(self, audio_path, annotation, routing_decision, reference_text, context=None):
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════════════════
# 1. CriticResult
# ═══════════════════════════════════════════════════════════════════════════


class TestCriticResult:
    def test_construction_and_to_dict(self):
        r = CriticResult(
            critic_type=CriticType.SEMANTIC,
            verdict=CriticVerdict.PASS,
            score=0.9,
            confidence=0.8,
            reasoning="ok",
            evidence={"a": 1},
            tags=["t1"],
        )
        d = r.to_dict()
        assert d["critic_type"] == "semantic"
        assert d["verdict"] == "pass"
        assert d["score"] == 0.9
        assert d["evidence"] == {"a": 1}
        assert d["tags"] == ["t1"]

    def test_from_dict_roundtrip(self):
        r = CriticResult(
            critic_type=CriticType.OBJECTIVE,
            verdict=CriticVerdict.WARNING,
            score=0.6,
            confidence=0.7,
            reasoning="r",
            evidence={"x": 2},
            tags=["t"],
        )
        r2 = CriticResult.from_dict(r.to_dict())
        assert r2 == r

    def test_from_dict_missing_optional_fields(self):
        d = {
            "critic_type": "structural",
            "verdict": "fail",
            "score": 0.2,
            "confidence": 0.4,
            "reasoning": "bad",
        }
        r = CriticResult.from_dict(d)
        assert r.evidence == {}
        assert r.tags == []


# ═══════════════════════════════════════════════════════════════════════════
# 2. BaseCritic helpers (_determine_verdict / _build_base_prompt /
#    _parse_llm_response / __init__ thresholds)
# ═══════════════════════════════════════════════════════════════════════════


class TestBaseCriticHelpers:
    def test_init_custom_thresholds(self):
        c = _ConcreteCritic(
            CriticType.SEMANTIC,
            router=MockRouter(),
            config={
                "pass_threshold": 0.8,
                "warning_threshold": 0.4,
                "min_confidence": 0.3,
            },
        )
        assert c.pass_threshold == 0.8
        assert c.warning_threshold == 0.4
        assert c.min_confidence == 0.3

    def test_determine_verdict_pass(self):
        c = _ConcreteCritic(CriticType.SEMANTIC, router=MockRouter())
        assert c._determine_verdict(0.9) == CriticVerdict.PASS
        assert c._determine_verdict(0.7) == CriticVerdict.PASS

    def test_determine_verdict_warning(self):
        c = _ConcreteCritic(CriticType.SEMANTIC, router=MockRouter())
        assert c._determine_verdict(0.5) == CriticVerdict.WARNING
        assert c._determine_verdict(0.6) == CriticVerdict.WARNING

    def test_determine_verdict_fail(self):
        c = _ConcreteCritic(CriticType.SEMANTIC, router=MockRouter())
        assert c._determine_verdict(0.2) == CriticVerdict.FAIL

    def test_build_base_prompt(self):
        c = _ConcreteCritic(CriticType.STRUCTURAL, router=MockRouter())
        p = c._build_base_prompt("评估结构质量")
        assert "structural" in p
        assert "JSON" in p
        assert "评估结构质量" in p

    def test_parse_llm_response_with_output_key(self):
        c = _ConcreteCritic(CriticType.SEMANTIC, router=MockRouter())
        out = c._parse_llm_response(
            {
                "output": {
                    "verdict": "pass",
                    "score": 0.88,
                    "confidence": 0.9,
                    "reasoning": "good",
                }
            }
        )
        assert out.critic_type == CriticType.SEMANTIC
        assert out.verdict == CriticVerdict.PASS
        assert out.score == 0.88

    def test_parse_llm_response_flat(self):
        c = _ConcreteCritic(CriticType.OBJECTIVE, router=MockRouter())
        out = c._parse_llm_response(
            {"verdict": "warning", "score": 0.6, "confidence": 0.5, "reasoning": "meh"}
        )
        assert out.verdict == CriticVerdict.WARNING
        assert out.critic_type == CriticType.OBJECTIVE

    def test_parse_llm_response_missing_fields_defaults(self):
        c = _ConcreteCritic(CriticType.STRUCTURAL, router=MockRouter())
        out = c._parse_llm_response({})
        assert out.verdict == CriticVerdict.FAIL  # default
        assert out.score == 0.0
        assert out.confidence == 0.5
        assert out.reasoning == ""


# ═══════════════════════════════════════════════════════════════════════════
# 3. CriticEnsemble dataclass
# ═══════════════════════════════════════════════════════════════════════════


class TestCriticEnsemble:
    def test_to_dict(self):
        r = CriticResult(
            critic_type=CriticType.SEMANTIC,
            verdict=CriticVerdict.PASS,
            score=0.9,
            confidence=0.8,
            reasoning="ok",
        )
        ens = CriticEnsemble(
            results=[r],
            final_verdict=CriticVerdict.PASS,
            final_score=0.9,
            weights={CriticType.SEMANTIC: 1.0},
            rationale="done",
        )
        d = ens.to_dict()
        assert d["final_verdict"] == "pass"
        assert d["final_score"] == 0.9
        assert d["weights"] == {"semantic": 1.0}
        assert d["results"][0]["critic_type"] == "semantic"


# ═══════════════════════════════════════════════════════════════════════════
# 4. SemanticCritic
# ═══════════════════════════════════════════════════════════════════════════


class TestSemanticCritic:
    def test_evaluate_returns_critic_result(self):
        router = MockRouter(
            output=CriticResult(
                critic_type=CriticType.SEMANTIC,
                verdict=CriticVerdict.PASS,
                score=0.85,
                confidence=0.9,
                reasoning="good",
            )
        )
        critic = _sem(router)
        res = critic.evaluate(
            Path("seg.wav"), _make_annotation(), _make_routing(), "文本"
        )
        assert isinstance(res, CriticResult)
        # critic_type is force-set by the critic
        assert res.critic_type == CriticType.SEMANTIC
        assert router.calls[-1][0] == "judge"

    def test_evaluate_non_critic_result_raises(self):
        router = MockRouter(output="not a CriticResult")
        critic = _sem(router)
        with pytest.raises(RuntimeError):
            critic.evaluate(Path("seg.wav"), _make_annotation(), _make_routing(), "文本")

    def test_evaluate_router_failure_propagates(self):
        router = MockRouter(side_effect=RuntimeError("boom"))
        critic = _sem(router)
        with pytest.raises(RuntimeError):
            critic.evaluate(Path("seg.wav"), _make_annotation(), _make_routing(), "文本")

    def test_evaluate_mock(self):
        critic = _sem(MockRouter())
        res = critic._evaluate_mock(
            Path("seg.wav"), _make_annotation(), _make_routing(), "文本"
        )
        assert res.critic_type == CriticType.SEMANTIC
        assert res.verdict == CriticVerdict.PASS
        assert res.evidence["semantic_coherence"] == 0.88

    def test_build_prompt_with_character_profiles(self):
        critic = _sem(MockRouter())
        context = {
            "prev_text": "前文",
            "next_text": "后文",
            "prev_emotion": "sad",
            "next_emotion": "happy",
            "chapter_info": "ch1",
            "character_profiles": [
                {
                    "canonical_name": "Alice",
                    "suggested_voice_id": "v_alice",
                    "语音描述": "soft",
                    "gender": "f",
                    "age_group": "adult",
                }
            ],
        }
        prompt = critic._build_prompt(
            Path("seg.wav"), _make_annotation(), _make_routing(), "文本", context
        )
        assert "Alice" in prompt
        assert "前文" in prompt


# ═══════════════════════════════════════════════════════════════════════════
# 5. StructuralCritic
# ═══════════════════════════════════════════════════════════════════════════


class TestStructuralCritic:
    def test_evaluate_returns_critic_result(self):
        router = MockRouter(
            output=CriticResult(
                critic_type=CriticType.STRUCTURAL,
                verdict=CriticVerdict.WARNING,
                score=0.65,
                confidence=0.7,
                reasoning="drift",
            )
        )
        critic = _str(router)
        res = critic.evaluate(
            Path("seg.wav"), _make_annotation(), _make_routing(), "文本"
        )
        assert res.critic_type == CriticType.STRUCTURAL
        assert res.verdict == CriticVerdict.WARNING

    def test_evaluate_router_failure_propagates(self):
        router = MockRouter(side_effect=ValueError("x"))
        critic = _str(router)
        with pytest.raises(ValueError):
            critic.evaluate(Path("seg.wav"), _make_annotation(), _make_routing(), "文本")

    def test_evaluate_non_critic_result_raises(self):
        router = MockRouter(output="not a CriticResult")
        critic = _str(router)
        with pytest.raises(RuntimeError):
            critic.evaluate(Path("seg.wav"), _make_annotation(), _make_routing(), "文本")

    def test_evaluate_mock_clean(self):
        critic = _str(MockRouter())
        res = critic._evaluate_mock(
            Path("seg.wav"), _make_annotation(), _make_routing(), "文本"
        )
        assert res.verdict == CriticVerdict.PASS
        assert res.tags == []

    def test_evaluate_mock_chapter_boundary_issue(self):
        critic = _str(MockRouter())
        ann = _make_annotation()
        ann.paragraph_index = 3
        context = {"is_chapter_start": True}
        res = critic._evaluate_mock(
            Path("seg.wav"), ann, _make_routing(), "文本", context
        )
        assert "chapter_boundary_mismatch" in res.tags

    def test_evaluate_mock_cost_overrun(self):
        critic = _str(MockRouter())
        context = {
            "cost_context": {"cumulative_cost_usd": 25.0, "cost_limit_per_book": 20.0}
        }
        res = critic._evaluate_mock(
            Path("seg.wav"), _make_annotation(), _make_routing(), "文本", context
        )
        assert "cost_overrun" in res.tags

    def test_build_prompt_chapter_context(self):
        critic = _str(MockRouter())
        context = {
            "prev_paragraph": {"text": "前段", "speaker": "n", "is_dialogue": False},
            "next_paragraph": {"text": "后段", "speaker": "n", "is_dialogue": True},
            "chapter_boundary_info": "boundary",
            "is_chapter_start": True,
            "is_chapter_end": False,
            "cost_context": {"cumulative_cost_usd": 1.0, "cost_limit_per_book": 20.0},
            "document_structure": {"total_chapters": 5, "total_paragraphs": 100},
        }
        prompt = critic._build_prompt(
            Path("seg.wav"), _make_annotation(), _make_routing(), "文本", context
        )
        assert "前段" in prompt
        assert "boundary" in prompt


# ═══════════════════════════════════════════════════════════════════════════
# 6. ObjectiveCritic (router NOT used by evaluate → monkeypatch metrics)
# ═══════════════════════════════════════════════════════════════════════════


class TestObjectiveCritic:
    def _make(self, config=None):
        return ObjectiveCritic(router=MockRouter(), config=config or {}, prompt_dir=PROMPT_DIR)

    def test_evaluate_full_path(self, monkeypatch):
        critic = self._make()
        canned = {"dnsmos": 3.9, "wer": 0.02, "speaker_sim": 0.92}

        def _fake(self_, audio_path, reference_text, context=None):
            return dict(canned)

        monkeypatch.setattr(ObjectiveCritic, "_compute_objective_metrics", _fake)
        res = critic.evaluate(
            Path("seg.wav"), _make_annotation(), _make_routing(), "文本"
        )
        assert res.critic_type == CriticType.OBJECTIVE
        assert res.verdict == CriticVerdict.PASS
        assert "dnsmos_below_threshold" not in res.tags

    def test_evaluate_metrics_all_bad(self):
        critic = self._make(
            {
                "dnsmos_threshold": 4.0,
                "wer_threshold": 0.01,
                "speaker_sim_threshold": 0.95,
            }
        )
        score, evidence, tags, reasoning = critic._evaluate_metrics(
            {"dnsmos": 2.0, "wer": 0.4, "speaker_sim": 0.4}
        )
        assert "dnsmos_below_threshold" in tags
        assert "wer_above_threshold" in tags
        assert "speaker_sim_below_threshold" in tags
        assert "critical_failure" in tags
        assert score < 0.3
        assert "Issues" in reasoning

    def test_evaluate_metrics_good(self):
        critic = self._make()
        score, evidence, tags, reasoning = critic._evaluate_metrics(
            {"dnsmos": 4.5, "wer": 0.0, "speaker_sim": 1.0}
        )
        assert tags == []
        assert score > 0.9

    def test_compute_confidence_fallback_reduced(self):
        critic = self._make()
        # all fallback values → confidence reduced from 0.85
        conf = critic._compute_confidence(
            {"dnsmos": 3.5, "wer": 0.1, "speaker_sim": 0.8},
            {"dnsmos": 3.5, "wer": 0.1, "speaker_sim": 0.8},
        )
        assert conf == 0.6  # 0.85 - 0.1 - 0.1 - 0.05

    def test_compute_confidence_full(self):
        critic = self._make()
        conf = critic._compute_confidence(
            {"dnsmos": 4.5, "wer": 0.0, "speaker_sim": 1.0},
            {"dnsmos": 4.5, "wer": 0.0, "speaker_sim": 1.0},
        )
        assert conf == 0.85

    def test_evaluate_mock(self):
        critic = self._make()
        res = critic._evaluate_mock(
            Path("seg.wav"), _make_annotation(), _make_routing(), "文本"
        )
        assert res.critic_type == CriticType.OBJECTIVE
        assert res.verdict == CriticVerdict.PASS
        assert res.evidence["dnsmos"] == 3.8


# ═══════════════════════════════════════════════════════════════════════════
# 7. CriticEnsembleEvaluator fusion branches
# ═══════════════════════════════════════════════════════════════════════════


class TestCriticEnsembleEvaluator:
    def _results(self, *specs):
        out = []
        for ctype, verdict, score, conf in specs:
            out.append(
                CriticResult(
                    critic_type=ctype,
                    verdict=verdict,
                    score=score,
                    confidence=conf,
                    reasoning="r",
                )
            )
        return out

    def test_fuse_empty(self):
        ev = CriticEnsembleEvaluator()
        ens = ev._fuse_results([])
        assert ens.final_verdict == CriticVerdict.ABSTAIN
        assert ens.final_score == 0.0
        assert ens.weights == {}

    def test_fuse_pass(self):
        ev = CriticEnsembleEvaluator()
        ens = ev._fuse_results(
            self._results(
                (CriticType.SEMANTIC, CriticVerdict.PASS, 0.85, 0.9),
                (CriticType.STRUCTURAL, CriticVerdict.PASS, 0.8, 0.8),
                (CriticType.OBJECTIVE, CriticVerdict.PASS, 0.9, 0.95),
            )
        )
        assert ens.final_verdict == CriticVerdict.PASS
        assert ens.final_score >= 0.7

    def test_fuse_fail_low_score(self):
        ev = CriticEnsembleEvaluator()
        ens = ev._fuse_results(
            self._results((CriticType.OBJECTIVE, CriticVerdict.FAIL, 0.0, 0.5))
        )
        assert ens.final_verdict == CriticVerdict.FAIL

    def test_fuse_warning_via_verdict(self):
        ev = CriticEnsembleEvaluator()
        ens = ev._fuse_results(
            self._results((CriticType.STRUCTURAL, CriticVerdict.WARNING, 0.65, 0.7))
        )
        assert ens.final_verdict == CriticVerdict.WARNING

    def test_fuse_warning_via_final_score(self):
        # PASS verdict but low score → triggers `final_score < 0.7` branch
        ev = CriticEnsembleEvaluator()
        ens = ev._fuse_results(
            self._results((CriticType.SEMANTIC, CriticVerdict.PASS, 0.6, 0.9))
        )
        assert ens.final_verdict == CriticVerdict.WARNING

    def test_fuse_zero_total_weight(self):
        ev = CriticEnsembleEvaluator(
            weights={
                CriticType.SEMANTIC: 0.0,
                CriticType.STRUCTURAL: 0.0,
                CriticType.OBJECTIVE: 0.0,
            }
        )
        ens = ev._fuse_results(
            self._results((CriticType.OBJECTIVE, CriticVerdict.PASS, 0.9, 0.9))
        )
        assert ens.final_score == 0.0
        assert ens.final_verdict == CriticVerdict.WARNING

    def test_evaluate_with_real_critics(self, monkeypatch):
        sem = _sem(
            MockRouter(
                output=CriticResult(
                    critic_type=CriticType.SEMANTIC,
                    verdict=CriticVerdict.PASS,
                    score=0.85,
                    confidence=0.9,
                    reasoning="s",
                )
            )
        )
        stc = _str(
            MockRouter(
                output=CriticResult(
                    critic_type=CriticType.STRUCTURAL,
                    verdict=CriticVerdict.PASS,
                    score=0.8,
                    confidence=0.8,
                    reasoning="st",
                )
            )
        )
        obj = ObjectiveCritic(router=MockRouter(), config={})

        def _fake(self_, audio_path, reference_text, context=None):
            return {"dnsmos": 4.0, "wer": 0.01, "speaker_sim": 0.95}

        monkeypatch.setattr(ObjectiveCritic, "_compute_objective_metrics", _fake)

        ev = CriticEnsembleEvaluator(
            semantic_critic=sem, structural_critic=stc, objective_critic=obj
        )
        ens = ev.evaluate(Path("seg.wav"), _make_annotation(), _make_routing(), "文本")
        assert len(ens.results) == 3
        assert ens.final_verdict == CriticVerdict.PASS

    def test_evaluate_mock(self):
        ev = CriticEnsembleEvaluator()
        ens = ev.evaluate_mock(Path("seg.wav"), _make_annotation(), _make_routing(), "文本")
        assert len(ens.results) == 3
        assert ens.final_verdict == CriticVerdict.WARNING

    def test_evaluate_partial_critics_semantic_only(self):
        # Covers the `if self.structural_critic is None` / objective None branches
        sem = _sem(
            MockRouter(
                output=CriticResult(
                    critic_type=CriticType.SEMANTIC,
                    verdict=CriticVerdict.PASS,
                    score=0.9,
                    confidence=0.9,
                    reasoning="s",
                )
            )
        )
        ev = CriticEnsembleEvaluator(semantic_critic=sem)
        ens = ev.evaluate(Path("seg.wav"), _make_annotation(), _make_routing(), "文本")
        assert len(ens.results) == 1
        assert ens.results[0].critic_type == CriticType.SEMANTIC

    def test_evaluate_partial_critics_objective_only(self, monkeypatch):
        # Covers the `if self.semantic_critic is None` / structural None branches
        obj = ObjectiveCritic(router=MockRouter(), config={}, prompt_dir=PROMPT_DIR)

        def _fake(self_, audio_path, reference_text, context=None):
            return {"dnsmos": 4.5, "wer": 0.0, "speaker_sim": 1.0}

        monkeypatch.setattr(ObjectiveCritic, "_compute_objective_metrics", _fake)
        ev = CriticEnsembleEvaluator(objective_critic=obj)
        ens = ev.evaluate(Path("seg.wav"), _make_annotation(), _make_routing(), "文本")
        assert len(ens.results) == 1
        assert ens.results[0].critic_type == CriticType.OBJECTIVE


# ═══════════════════════════════════════════════════════════════════════════
# 8. SyntheticCritic
# ═══════════════════════════════════════════════════════════════════════════


class TestSyntheticCritic:
    def test_mock_mode_evaluate(self):
        critic = create_synthetic_critic(mock_mode=True)
        ens = critic.evaluate(Path("seg.wav"), _make_annotation(), _make_routing(), "文本")
        assert isinstance(ens, CriticEnsemble)
        assert ens.final_verdict == CriticVerdict.WARNING

    def test_run_mock_evaluation(self):
        critic = create_synthetic_critic(mock_mode=True)
        ens = critic.run_mock_evaluation()
        assert ens.final_score > 0.0

    def test_evaluate_with_injected_critics(self, monkeypatch):
        sem = _sem(
            MockRouter(
                output=CriticResult(
                    critic_type=CriticType.SEMANTIC,
                    verdict=CriticVerdict.PASS,
                    score=0.9,
                    confidence=0.9,
                    reasoning="s",
                )
            )
        )
        stc = _str(
            MockRouter(
                output=CriticResult(
                    critic_type=CriticType.STRUCTURAL,
                    verdict=CriticVerdict.PASS,
                    score=0.85,
                    confidence=0.8,
                    reasoning="st",
                )
            )
        )
        obj = ObjectiveCritic(router=MockRouter(), config={})

        def _fake(self_, audio_path, reference_text, context=None):
            return {"dnsmos": 4.5, "wer": 0.0, "speaker_sim": 1.0}

        monkeypatch.setattr(ObjectiveCritic, "_compute_objective_metrics", _fake)

        critic = SyntheticCritic(
            semantic_critic=sem, structural_critic=stc, objective_critic=obj
        )
        ens = critic.evaluate(Path("seg.wav"), _make_annotation(), _make_routing(), "文本")
        assert ens.final_verdict == CriticVerdict.PASS

    def test_calibrate(self):
        critic = create_synthetic_critic(mock_mode=True)
        result = critic.calibrate()
        assert isinstance(result, CalibrationResult)
        assert 0.0 <= result.f1_macro <= 1.0
        assert result.total_samples == len(critic.calibration_samples)
        assert isinstance(result.passed, bool)

    def test_calibrate_custom_samples(self):
        samples = [
            CalibrationSample(
                sample_id="p",
                description="p",
                semantic_score=0.9,
                structural_score=0.9,
                objective_score=0.9,
                ground_truth_verdict=CriticVerdict.PASS,
                ground_truth_score=0.9,
            ),
            CalibrationSample(
                sample_id="f",
                description="f",
                semantic_score=0.1,
                structural_score=0.1,
                objective_score=0.1,
                ground_truth_verdict=CriticVerdict.FAIL,
                ground_truth_score=0.1,
            ),
        ]
        critic = create_synthetic_critic(mock_mode=True)
        result = critic.calibrate(samples)
        assert result.total_samples == 2

    def test_calibrate_with_adaptive_weights(self, monkeypatch):
        import numpy as np_mod

        def _fake_linspace(start, stop, num):
            if num is None or num <= 1:
                return [start]
            step = (stop - start) / (num - 1)
            return [start + i * step for i in range(num)]

        if isinstance(np_mod, MagicMock):
            monkeypatch.setattr(np_mod, "linspace", _fake_linspace)

        critic = create_synthetic_critic(mock_mode=True)
        result = critic.calibrate_with_adaptive_weights(n_iterations=3)
        assert isinstance(result, CalibrationResult)
        # weights preserved / set
        assert abs(sum(critic.get_weights().values()) - 1.0) < 0.01

    def test_score_to_verdict(self):
        critic = create_synthetic_critic(
            mock_mode=True, pass_threshold=0.7, warning_threshold=0.5
        )
        assert critic._score_to_verdict(0.8) == CriticVerdict.PASS
        assert critic._score_to_verdict(0.6) == CriticVerdict.WARNING
        assert critic._score_to_verdict(0.2) == CriticVerdict.FAIL

    def test_get_and_set_weights_normalization(self):
        critic = create_synthetic_critic(mock_mode=True)
        critic.set_weights(
            {
                CriticType.SEMANTIC: 1.0,
                CriticType.STRUCTURAL: 1.0,
                CriticType.OBJECTIVE: 1.0,
            }
        )
        w = critic.get_weights()
        assert abs(sum(w.values()) - 1.0) < 0.01

    def test_set_weights_already_normalized(self):
        # Covers the `if abs(total - 1.0) > 0.01` False branch
        critic = create_synthetic_critic(mock_mode=True)
        critic.set_weights(
            {
                CriticType.SEMANTIC: 0.3,
                CriticType.STRUCTURAL: 0.2,
                CriticType.OBJECTIVE: 0.5,
            }
        )
        w = critic.get_weights()
        assert abs(w["objective"] - 0.5) < 1e-9

    def test_calibrate_with_adaptive_weights_no_improvement(self, monkeypatch):
        # Samples where predictions never match ground truth → best_result stays None,
        # exercising the `return self.calibrate(samples)` fallback.
        import numpy as np_mod

        def _fake_linspace(start, stop, num):
            if num is None or num <= 1:
                return [start]
            step = (stop - start) / (num - 1)
            return [start + i * step for i in range(num)]

        if isinstance(np_mod, MagicMock):
            monkeypatch.setattr(np_mod, "linspace", _fake_linspace)

        samples = [
            CalibrationSample(
                sample_id="never",
                description="never matches",
                semantic_score=0.1,
                structural_score=0.1,
                objective_score=0.1,
                ground_truth_verdict=CriticVerdict.PASS,
                ground_truth_score=0.9,
            )
        ]
        critic = create_synthetic_critic(mock_mode=True)
        result = critic.calibrate_with_adaptive_weights(n_iterations=3, samples=samples)
        assert isinstance(result, CalibrationResult)

    def test_factory_custom_weights_and_thresholds(self):
        critic = create_synthetic_critic(
            mock_mode=True,
            weights={
                CriticType.SEMANTIC: 0.5,
                CriticType.STRUCTURAL: 0.3,
                CriticType.OBJECTIVE: 0.2,
            },
            pass_threshold=0.75,
            warning_threshold=0.55,
        )
        assert critic.pass_threshold == 0.75
        assert abs(sum(critic.get_weights().values()) - 1.0) < 0.01


# ═══════════════════════════════════════════════════════════════════════════
# 9. Calibration helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestCalibrationHelpers:
    def test_confusion_matrix(self):
        m = _compute_confusion_matrix(
            ["pass", "fail", "warning"],
            ["pass", "fail", "fail"],
            ["pass", "warning", "fail"],
        )
        assert m["pass"]["pass"] == 1
        assert m["fail"]["fail"] == 1
        assert m["fail"]["warning"] == 0
        assert m["warning"]["fail"] == 1

    def test_f1_per_class(self):
        m = _compute_confusion_matrix(
            ["pass", "pass", "fail"], ["pass", "fail", "fail"], ["pass", "fail"]
        )
        f1 = _compute_f1_per_class(m, ["pass", "fail"])
        # pass: tp=1, fp=1, fn=0 → precision .5, recall 1.0 → f1 = 2/3 (rounded to 4dp)
        # fail: tp=1, fp=0, fn=1 → precision 1.0, recall .5 → f1 = 2/3
        assert abs(f1["pass"] - 0.6667) < 1e-6
        assert abs(f1["fail"] - 0.6667) < 1e-6
