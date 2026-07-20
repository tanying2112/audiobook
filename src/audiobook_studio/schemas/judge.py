"""Judge schemas — LLM-as-a-Judge 结构化输出契约.

包含：
- PairwiseJudgment: A/B 测试盲评的成对比较结果
"""

from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, confloat

Score = Annotated[float, Field(ge=0.0, le=1.0)]


class PairwiseDimensionScore(BaseModel):
    """单维度的成对评分."""

    score_a: Score = Field(..., description="版本 A 得分 0-1")
    score_b: Score = Field(..., description="版本 B 得分 0-1")
    winner: Literal["A", "B", "tie"] = Field(..., description="该维度胜者")


class PairwiseJudgment(BaseModel):
    """A/B 测试成对比较判定结果.

    用于 LLM-as-a-Judge 盲评：对比版本 A vs 版本 B，
    输出多维度评分、整体胜者、置信度、推理说明。
    """

    segment_id: str = Field(..., description="片段 ID")
    winner: Literal["A", "B", "tie"] = Field(..., description="整体胜者")
    confidence: Score = Field(..., description="判定置信度 0-1")
    dimension_scores: Dict[str, PairwiseDimensionScore] = Field(default_factory=dict, description="各维度成对评分")
    reasoning: Dict[str, str] = Field(default_factory=dict, description="各维度推理说明")
    overall_reasoning: str = Field(..., description="整体推理总结")
    statistical_significance: Optional[bool] = Field(default=None, description="是否达到统计显著性（需配合 t-test）")
    p_value: Optional[float] = Field(default=None, description="配对 t-test p-value")
    effect_size: Optional[float] = Field(default=None, description="Cohen's d 效应量")
    judge_model: Optional[str] = Field(default=None, description="评判模型名称")
    judge_prompt_version: Optional[str] = Field(default=None, description="评判提示词版本")

    model_config = {"extra": "forbid"}


def create_pairwise_judgment(
    segment_id: str,
    winner: Literal["A", "B", "tie"],
    confidence: float,
    dimension_scores: Dict[str, Dict[str, float]],
    reasoning: Dict[str, str],
    overall_reasoning: str,
) -> PairwiseJudgment:
    """便捷构造函数：从简单字典构建 PairwiseJudgment."""
    dim_scores = {}
    for dim, scores in dimension_scores.items():
        dim_scores[dim] = PairwiseDimensionScore(
            score_a=scores.get("a", 0.5),
            score_b=scores.get("b", 0.5),
            winner=scores.get("winner", "tie"),
        )
    return PairwiseJudgment(
        segment_id=segment_id,
        winner=winner,
        confidence=confidence,
        dimension_scores=dim_scores,
        reasoning=reasoning,
        overall_reasoning=overall_reasoning,
    )
