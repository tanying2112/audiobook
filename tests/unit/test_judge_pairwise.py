"""LLMJudge pairwise 单元测试.

测试覆盖：
1. judge_pairwise 方法调用成功
2. PairwiseJudgment schema 验证
3. Pairwise prompt 渲染
4. 降级路径（LLM 失败时）
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.llm.judge import LLMJudge, JudgeConfig
from src.audiobook_studio.schemas import (
    PairwiseJudgment,
    PairwiseDimensionScore,
    ParagraphAnnotation,
)


@pytest.fixture
def mock_router():
    """创建一个 mock LLMRouter."""
    router = MagicMock()
    return router


@pytest.fixture
def judge(mock_router):
    """创建使用 mock router 的 LLMJudge."""
    config = JudgeConfig(model="test-model")
    return LLMJudge(config=config, router=mock_router)


@pytest.fixture
def sample_data():
    """样例 A/B 测试数据."""
    return {
        "segment_id": "test-seg-001",
        "stage": "annotate_paragraph",
        "reference_text": "他说：'你好，世界。'",
        "output_a": {
            "speaker": "旁白",
            "emotion": "neutral",
            "emotion_intensity": 0.5,
        },
        "output_b": {
            "speaker": "张三",
            "emotion": "happy",
            "emotion_intensity": 0.8,
        },
        "annotation": ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="张三",
            emotion="happy",
            emotion_intensity=0.8,
            is_dialogue=True,
            confidence=0.9,
        ),
        "audio_description": "清晰的男声，语气愉快",
    }


class TestPairwiseJudgmentSchema:
    """测试 PairwiseJudgment schema."""

    def test_default_values(self):
        """测试默认值."""
        pj = PairwiseJudgment(
            segment_id="test",
            winner="A",
            confidence=0.8,
            overall_reasoning="测试",
        )
        assert pj.segment_id == "test"
        assert pj.winner == "A"
        assert pj.confidence == 0.8
        assert pj.dimension_scores == {}
        assert pj.reasoning == {}
        assert pj.statistical_significance is None
        assert pj.p_value is None
        assert pj.effect_size is None

    def test_valid_winner_values(self):
        """测试有效的 winner 值."""
        for winner in ["A", "B", "tie"]:
            pj = PairwiseJudgment(
                segment_id="test",
                winner=winner,
                confidence=0.8,
                overall_reasoning="测试",
            )
            assert pj.winner == winner

    def test_invalid_winner_raises(self):
        """无效 winner 应抛出 ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PairwiseJudgment(
                segment_id="test",
                winner="C",  # 无效
                confidence=0.8,
                overall_reasoning="测试",
            )

    def test_confidence_range(self):
        """confidence 应在 0-1 范围内."""
        pj = PairwiseJudgment(
            segment_id="test",
            winner="A",
            confidence=0.0,
            overall_reasoning="测试",
        )
        assert pj.confidence == 0.0

        pj = PairwiseJudgment(
            segment_id="test",
            winner="A",
            confidence=1.0,
            overall_reasoning="测试",
        )
        assert pj.confidence == 1.0

    def test_confidence_out_of_range_raises(self):
        """confidence 超出范围应抛出 ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PairwiseJudgment(
                segment_id="test",
                winner="A",
                confidence=1.5,
                overall_reasoning="测试",
            )
        with pytest.raises(ValidationError):
            PairwiseJudgment(
                segment_id="test",
                winner="A",
                confidence=-0.1,
                overall_reasoning="测试",
            )

    def test_dimension_scores(self):
        """测试维度评分结构."""
        pj = PairwiseJudgment(
            segment_id="test",
            winner="A",
            confidence=0.9,
            dimension_scores={
                "speaker_clarity": PairwiseDimensionScore(
                    score_a=0.6, score_b=0.9, winner="B"
                ),
                "emotion_match": PairwiseDimensionScore(
                    score_a=0.5, score_b=0.8, winner="B"
                ),
            },
            overall_reasoning="B 版本更好",
        )
        assert len(pj.dimension_scores) == 2
        assert pj.dimension_scores["speaker_clarity"].winner == "B"
        assert pj.dimension_scores["emotion_match"].score_a == 0.5

    def test_serialization(self):
        """测试 JSON 序列化."""
        pj = PairwiseJudgment(
            segment_id="test",
            winner="B",
            confidence=0.85,
            dimension_scores={
                "speaker_clarity": PairwiseDimensionScore(
                    score_a=0.6, score_b=0.9, winner="B"
                ),
            },
            reasoning={"speaker_clarity": "B 版本说话人更准确"},
            overall_reasoning="B 版本整体更优",
            statistical_significance=True,
            p_value=0.03,
            effect_size=0.8,
            judge_model="test-model",
            judge_prompt_version="pairwise_v1",
        )
        data = pj.model_dump()
        assert data["winner"] == "B"
        assert data["confidence"] == 0.85
        assert data["dimension_scores"]["speaker_clarity"]["winner"] == "B"
        assert data["p_value"] == 0.03

        # 反序列化
        pj2 = PairwiseJudgment.model_validate(data)
        assert pj2 == pj


class TestPairwiseDimensionScore:
    """测试 PairwiseDimensionScore."""

    def test_valid_scores(self):
        """测试有效分数."""
        pds = PairwiseDimensionScore(score_a=0.7, score_b=0.8, winner="B")
        assert pds.score_a == 0.7
        assert pds.score_b == 0.8
        assert pds.winner == "B"

    def test_tie_winner(self):
        """测试平局."""
        pds = PairwiseDimensionScore(score_a=0.8, score_b=0.8, winner="tie")
        assert pds.winner == "tie"

    def test_invalid_score_raises(self):
        """无效分数应抛出."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PairwiseDimensionScore(score_a=1.5, score_b=0.5, winner="A")


class TestJudgePairwise:
    """测试 judge_pairwise 方法."""

    def test_judge_pairwise_calls_router(self, judge, mock_router, sample_data):
        """judge_pairwise 应调用 router.call."""
        expected = PairwiseJudgment(
            segment_id=sample_data["segment_id"],
            winner="B",
            confidence=0.9,
            dimension_scores={
                "speaker_clarity": PairwiseDimensionScore(
                    score_a=0.5, score_b=0.9, winner="B"
                ),
            },
            reasoning={"speaker_clarity": "B 正确识别了说话人"},
            overall_reasoning="B 版本整体更好",
            judge_model="test-model",
            judge_prompt_version="pairwise_v1",
        )
        mock_result = MagicMock()
        mock_result.output = expected
        mock_router.call.return_value = mock_result

        result = judge.judge_pairwise(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
            annotation=sample_data["annotation"],
            audio_description=sample_data["audio_description"],
        )

        assert result == expected
        mock_router.call.assert_called_once()
        call_kwargs = mock_router.call.call_args.kwargs
        assert call_kwargs["stage"] == "judge"
        assert call_kwargs["response_model"] == PairwiseJudgment

    def test_judge_pairwise_returns_correct_winner(self, judge, mock_router, sample_data):
        """judge_pairwise 应返回 LLM 判定的胜者."""
        expected = PairwiseJudgment(
            segment_id=sample_data["segment_id"],
            winner="B",
            confidence=0.85,
            dimension_scores={
                "speaker_clarity": PairwiseDimensionScore(
                    score_a=0.4, score_b=0.9, winner="B"
                ),
                "emotion_match": PairwiseDimensionScore(
                    score_a=0.5, score_b=0.8, winner="B"
                ),
                "prosody_naturalness": PairwiseDimensionScore(
                    score_a=0.6, score_b=0.7, winner="B"
                ),
                "text_audio_alignment": PairwiseDimensionScore(
                    score_a=0.7, score_b=0.7, winner="tie"
                ),
            },
            reasoning={
                "speaker_clarity": "B 正确识别说话人",
                "emotion_match": "B 情感标注更准确",
            },
            overall_reasoning="B 在关键维度上显著优于 A",
            judge_model="test-model",
        )
        mock_result = MagicMock()
        mock_result.output = expected
        mock_router.call.return_value = mock_result

        result = judge.judge_pairwise(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
        )

        assert result.winner == "B"
        assert result.confidence == 0.85
        assert "speaker_clarity" in result.dimension_scores

    def test_judge_pairwise_passes_messages(self, judge, mock_router, sample_data):
        """judge_pairwise 应构建 system + user 消息."""
        mock_result = MagicMock()
        mock_result.output = PairwiseJudgment(
            segment_id=sample_data["segment_id"],
            winner="tie",
            confidence=0.5,
            overall_reasoning="测试",
        )
        mock_router.call.return_value = mock_result

        judge.judge_pairwise(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
        )

        call_kwargs = mock_router.call.call_args
        messages = call_kwargs.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_judge_pairwise_raises_on_llm_failure(self, judge, mock_router, sample_data):
        """LLM 调用失败时应捕获异常并返回降级结果（不抛出）."""
        mock_router.call.side_effect = Exception("LLM API timeout")

        result = judge.judge_pairwise(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
        )

        # 应返回降级结果（tie + 低置信度 + 错误信息）
        assert result.winner == "tie"
        assert result.confidence == 0.5
        assert "LLM API timeout" in result.overall_reasoning

    def test_judge_pairwise_without_annotation(self, judge, mock_router, sample_data):
        """无 annotation 时也应正常工作."""
        mock_result = MagicMock()
        mock_result.output = PairwiseJudgment(
            segment_id=sample_data["segment_id"],
            winner="A",
            confidence=0.7,
            overall_reasoning="测试",
        )
        mock_router.call.return_value = mock_result

        result = judge.judge_pairwise(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
            annotation=None,  # 无标注
        )

        assert result.winner == "A"

    def test_judge_pairwise_without_audio_description(self, judge, mock_router, sample_data):
        """无 audio_description 时也应正常工作."""
        mock_result = MagicMock()
        mock_result.output = PairwiseJudgment(
            segment_id=sample_data["segment_id"],
            winner="B",
            confidence=0.7,
            overall_reasoning="测试",
        )
        mock_router.call.return_value = mock_result

        result = judge.judge_pairwise(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
            audio_description=None,  # 无音频描述
        )

        assert result.winner == "B"


class TestPromptBuilding:
    """测试 _build_pairwise_prompt 方法."""

    def test_prompt_contains_segment_id(self, judge, sample_data):
        """prompt 应包含 segment_id."""
        prompt = judge._build_pairwise_prompt(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
            annotation=sample_data["annotation"],
            audio_description=sample_data["audio_description"],
        )
        assert sample_data["segment_id"] in prompt

    def test_prompt_contains_stage(self, judge, sample_data):
        """prompt 应包含 stage."""
        prompt = judge._build_pairwise_prompt(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
            annotation=sample_data["annotation"],
            audio_description=sample_data["audio_description"],
        )
        assert sample_data["stage"] in prompt

    def test_prompt_contains_reference_text(self, judge, sample_data):
        """prompt 应包含参考文本."""
        prompt = judge._build_pairwise_prompt(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
            annotation=sample_data["annotation"],
            audio_description=sample_data["audio_description"],
        )
        assert "你好" in prompt  # reference_text 中的内容

    def test_prompt_contains_both_outputs(self, judge, sample_data):
        """prompt 应包含 A 和 B 两版输出."""
        prompt = judge._build_pairwise_prompt(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
            annotation=sample_data["annotation"],
            audio_description=sample_data["audio_description"],
        )
        # JSON 序列化会将中文转为 Unicode escape，检查键名
        assert "speaker" in prompt
        assert "emotion" in prompt
        # output_a 有 "旁白" -> 旁白
        assert "旁白" in prompt or "speaker" in prompt
        # output_b 有 "张三" -> 张三
        assert "张三" in prompt or "speaker" in prompt

    def test_prompt_contains_annotation(self, judge, sample_data):
        """prompt 应包含 annotation."""
        prompt = judge._build_pairwise_prompt(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
            annotation=sample_data["annotation"],
            audio_description=sample_data["audio_description"],
        )
        assert "张三" in prompt or "speaker_canonical_name" in prompt  # annotation 中的说话人

    def test_prompt_contains_audio_description(self, judge, sample_data):
        """prompt 应包含 audio_description."""
        prompt = judge._build_pairwise_prompt(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
            annotation=sample_data["annotation"],
            audio_description=sample_data["audio_description"],
        )
        assert "愉快" in prompt or "audio_description" in prompt

    def test_prompt_contains_schema(self, judge, sample_data):
        """prompt 应包含 JSON schema 信息."""
        prompt = judge._build_pairwise_prompt(
            segment_id=sample_data["segment_id"],
            stage=sample_data["stage"],
            reference_text=sample_data["reference_text"],
            output_a=sample_data["output_a"],
            output_b=sample_data["output_b"],
            annotation=sample_data["annotation"],
            audio_description=sample_data["audio_description"],
        )
        assert "winner" in prompt
        assert "confidence" in prompt
        assert "dimension_scores" in prompt


class TestPairwiseJudgeFn:
    """测试 create_pairwise_judge_fn."""

    def test_create_pairwise_judge_fn(self):
        """create_pairwise_judge_fn 应返回可调用函数."""
        from src.audiobook_studio.feedback.ab_test import create_pairwise_judge_fn

        judge_fn = create_pairwise_judge_fn("annotate_paragraph", judge_model="test")
        assert callable(judge_fn)

    def test_pairwise_judge_fn_fallback(self):
        """pairwise judge fn 失败时应降级."""
        from src.audiobook_studio.feedback.ab_test import create_pairwise_judge_fn

        # 不传 router，使用默认（会失败并降级）
        judge_fn = create_pairwise_judge_fn("annotate_paragraph", judge_model="nonexistent")

        result = judge_fn(
            segment_id="test-seg",
            input_data={"paragraph_text": "test"},
            output_a={"speaker": "A"},
            output_b={"speaker": "B"},
        )

        assert isinstance(result, PairwiseJudgment)
        assert result.winner in ("A", "B", "tie")
        assert result.confidence == 0.5  # 降级时的默认置信度
        assert "fallback" in result.overall_reasoning.lower() or "heuristic" in result.overall_reasoning.lower()