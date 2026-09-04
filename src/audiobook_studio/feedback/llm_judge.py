"""LLM Judge Ensemble — multi-model blind evaluation for A/B testing (S2-3).

Runs N LLM judges **in parallel**, each scoring outputs A and B on a fixed
rubric (faithfulness, naturalness, instruction_following, no_hallucination) on
a 1-5 scale. The per-model verdicts are aggregated via **majority vote** with a
**confidence threshold**, and emitted as a structured :class:`JudgeResult`.

This replaces the single-heuristic :func:`_score_output` path for real
evaluations. The heuristic remains only as a no-LLM fallback (see
``ab_test.create_llm_judge_fn``).
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from .. import llm as _llm_module
from ..llm.client import LLMCallResult

logger = logging.getLogger(__name__)

# ── Rubric ──────────────────────────────────────────────────────────────────

# Fixed 1-5 rubric dimensions (S2-3).
RUBRIC_DIMENSIONS = [
    "faithfulness",
    "naturalness",
    "instruction_following",
    "no_hallucination",
]

# Default ensemble: 3 diverse judge models (>=3 for voting consistency).
DEFAULT_ENSEMBLE_MODELS = [
    "openrouter/auto",
    "anthropic/claude-3.5-sonnet",
    "openai/gpt-4o-mini",
]

RUBRIC_MIN = 1.0
RUBRIC_MAX = 5.0

# Agreement (voting consistency) required for a "significant" ensemble verdict.
DEFAULT_CONFIDENCE_THRESHOLD = 0.8


class DimensionScore(BaseModel):
    """Per-output score on a single rubric dimension (1-5)."""

    a: float = Field(default=3.0, ge=1.0, le=5.0)
    b: float = Field(default=3.0, ge=1.0, le=5.0)


class RubricScores(BaseModel):
    """Structured LLM judge output: rubric scores (1-5) for both outputs."""

    faithfulness: DimensionScore = Field(default_factory=DimensionScore)
    naturalness: DimensionScore = Field(default_factory=DimensionScore)
    instruction_following: DimensionScore = Field(default_factory=DimensionScore)
    no_hallucination: DimensionScore = Field(default_factory=DimensionScore)
    winner: str = "tie"  # "A" | "B" | "tie"
    rationale: str = ""


@dataclass
class ModelJudgment:
    """Result of a single judge model within the ensemble."""

    model: str
    scores: RubricScores
    winner: str  # "A" | "B" | "tie"
    score_a: float  # normalized 0-1 (sum of dims / (num_dims * 5))
    score_b: float  # normalized 0-1


@dataclass
class JudgeResult:
    """Aggregated ensemble judgment."""

    winner: str  # "A" | "B" | "tie" (majority vote)
    score_a: float  # normalized 0-1 (avg across models)
    score_b: float  # normalized 0-1
    rationale: str
    dimension_scores: Dict[str, Dict[str, float]]  # dim -> {"a":..,"b":..} (1-5 avg)
    per_model: List[ModelJudgment] = field(default_factory=list)
    agreement: float = 0.0  # voting consistency: fraction of models agreeing on winner
    confidence: float = 0.0  # 0-1 confidence in the verdict
    is_significant: bool = False  # agreement >= confidence_threshold
    num_models: int = 0


def _normalize(rubric_value: float) -> float:
    """Map a 1-5 rubric score onto the 0-1 normalized scale used by run_ab_test."""
    return max(0.0, min(1.0, (rubric_value - RUBRIC_MIN) / (RUBRIC_MAX - RUBRIC_MIN)))


def _model_normalized_scores(scores: RubricScores) -> tuple[float, float]:
    """Average a single model's rubric scores into normalized 0-1 (score_a, score_b)."""
    n = len(RUBRIC_DIMENSIONS)
    dims_a = [getattr(scores, d).a for d in RUBRIC_DIMENSIONS]
    dims_b = [getattr(scores, d).b for d in RUBRIC_DIMENSIONS]
    score_a = sum(_normalize(v) for v in dims_a) / n
    score_b = sum(_normalize(v) for v in dims_b) / n
    return score_a, score_b


class LLMJudgeEnsemble:
    """Run multiple LLM judges in parallel and aggregate their verdicts.

    Each judge independently scores outputs A and B on the rubric. The ensemble
    performs a majority vote over the per-model winners, reports the voting
    consistency (``agreement``), and flags significance against a confidence
    threshold.
    """

    def __init__(
        self,
        models: Optional[List[str]] = None,
        rubric: Optional[List[str]] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        num_workers: Optional[int] = None,
        client_factory: Optional[Callable[[str], Any]] = None,
    ):
        self.models = list(models) if models else list(DEFAULT_ENSEMBLE_MODELS)
        self.rubric = list(rubric) if rubric else list(RUBRIC_DIMENSIONS)
        self.confidence_threshold = confidence_threshold
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.num_workers = num_workers or max(1, len(self.models))
        # client_factory(model) -> an object with .call(prompt=, response_model=, temperature=)
        # Default uses the unified LLM client via the llm module (honours MOCK_LLM env
        # and any monkeypatch of src.audiobook_studio.llm.create_client).
        self.client_factory = client_factory or (
            lambda model: _llm_module.create_client(model=model, temperature=temperature, max_tokens=max_tokens)
        )

    def judge(
        self,
        input_data: Dict[str, Any],
        output_a: Dict[str, Any],
        output_b: Dict[str, Any],
        stage: str,
    ) -> JudgeResult:
        """Score (output_a, output_b) with the ensemble and aggregate.

        Raises:
            ValueError: if every judge model failed (so no verdict is possible).
        """
        judgments: List[ModelJudgment] = []
        errors: List[str] = []

        def _work(model: str) -> Optional[ModelJudgment]:
            try:
                return self._judge_one(model, input_data, output_a, output_b, stage)
            except Exception as exc:  # noqa: BLE001 - isolate per-model failures
                logger.warning(f"Ensemble judge model {model} failed: {exc}")
                errors.append(f"{model}: {exc}")
                return None

        with ThreadPoolExecutor(max_workers=self.num_workers) as ex:
            futures = {ex.submit(_work, m): m for m in self.models}
            for fut in as_completed(futures):
                res = fut.result()
                if res is not None:
                    judgments.append(res)

        if not judgments:
            raise ValueError(
                f"LLM Judge Ensemble failed: all {len(self.models)} model(s) raised " f"errors: {'; '.join(errors)}"
            )

        return self._aggregate(judgments)

    def _judge_one(
        self,
        model: str,
        input_data: Dict[str, Any],
        output_a: Dict[str, Any],
        output_b: Dict[str, Any],
        stage: str,
    ) -> ModelJudgment:
        client = self.client_factory(model)
        prompt = self._build_prompt(input_data, output_a, output_b, stage)
        result: LLMCallResult = client.call(
            prompt=prompt,
            response_model=RubricScores,
            temperature=self.temperature,
        )
        scores = result.output
        if not isinstance(scores, RubricScores):
            raise TypeError(f"Judge model {model} returned unexpected output type: {type(scores)}")
        score_a, score_b = _model_normalized_scores(scores)
        winner = scores.winner if scores.winner in ("A", "B", "tie") else "tie"
        return ModelJudgment(
            model=model,
            scores=scores,
            winner=winner,
            score_a=score_a,
            score_b=score_b,
        )

    def _aggregate(self, judgments: List[ModelJudgment]) -> JudgeResult:
        n = len(judgments)
        winners = [j.winner for j in judgments]
        counts = Counter(winners)
        majority_winner, majority_count = counts.most_common(1)[0]
        agreement = majority_count / n  # voting consistency / 一致性

        # Average rubric dimension scores across models (1-5 scale).
        dim_avg: Dict[str, Dict[str, float]] = {}
        for d in self.rubric:
            a_vals = [getattr(j.scores, d).a for j in judgments]
            b_vals = [getattr(j.scores, d).b for j in judgments]
            dim_avg[d] = {"a": sum(a_vals) / n, "b": sum(b_vals) / n}

        avg_score_a = sum(j.score_a for j in judgments) / n
        avg_score_b = sum(j.score_b for j in judgments) / n

        # Confidence combines voting consistency with how decisive the margin is.
        margin = abs(avg_score_b - avg_score_a)  # 0-1
        confidence = agreement * min(1.0, 0.5 + margin)

        is_significant = agreement >= self.confidence_threshold

        rationale = self._build_rationale(judgments, majority_winner, agreement, confidence)

        return JudgeResult(
            winner=majority_winner,
            score_a=avg_score_a,
            score_b=avg_score_b,
            rationale=rationale,
            dimension_scores=dim_avg,
            per_model=judgments,
            agreement=agreement,
            confidence=confidence,
            is_significant=is_significant,
            num_models=n,
        )

    @staticmethod
    def _build_rationale(
        judgments: List[ModelJudgment],
        winner: str,
        agreement: float,
        confidence: float,
    ) -> str:
        parts = [
            f"Ensemble verdict: {winner} (voting_agreement={agreement:.2f}, "
            f"confidence={confidence:.2f}, n_models={len(judgments)})"
        ]
        for j in judgments:
            parts.append(f"[{j.model}] -> {j.winner} (A={j.score_a:.2f}, B={j.score_b:.2f})")
        return "; ".join(parts)

    def _build_prompt(
        self,
        input_data: Dict[str, Any],
        output_a: Dict[str, Any],
        output_b: Dict[str, Any],
        stage: str,
    ) -> str:
        if isinstance(input_data, dict):
            input_text = str(
                input_data.get("paragraph_text")
                or input_data.get("text")
                or input_data.get("book_text")
                or input_data.get("expected_text")
                or ""
            )
        else:
            input_text = str(input_data)
        input_text = input_text[:2000]

        rubric_lines = "\n".join(f"- {d} (score 1-5, 5 = best)" for d in self.rubric)
        rubric_defs = (
            "- faithfulness: factual/semantic fidelity to the input and reference, no distortion\n"
            "- naturalness: oral, natural fluency; sounds human, not robotic\n"
            "- instruction_following: correctly follows the editing/annotation instructions\n"
            "- no_hallucination: no invented content; no dropped or added facts"
        )

        return f"""You are a panel of expert audiobook quality evaluators conducting a BLIND A/B test.
You do NOT know which output is the old version (A) or the new version (B).

Pipeline stage: {stage}
Input:
{input_text}

Version A output:
{_safe_json(output_a)[:3000]}

Version B output:
{_safe_json(output_b)[:3000]}

Score BOTH outputs independently on each rubric dimension (integer 1-5, 5 = best):
{rubric_lines}

Rubric definitions:
{rubric_defs}

Then decide the overall winner ("A", "B", or "tie").

Output STRICT JSON matching this schema:
{{
  "faithfulness": {{"a": <1-5>, "b": <1-5>}},
  "naturalness": {{"a": <1-5>, "b": <1-5>}},
  "instruction_following": {{"a": <1-5>, "b": <1-5>}},
  "no_hallucination": {{"a": <1-5>, "b": <1-5>}},
  "winner": "A" | "B" | "tie",
  "rationale": "<concise reason>"
}}"""


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)
