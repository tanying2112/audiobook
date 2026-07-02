"""LLMFeedbackAnalyzer 单元测试.

测试覆盖：
1. Mock 模式分析（不依赖 LLM API）
2. LLM 调用成功路径（mock router）
3. LLM 调用失败降级路径
4. processor.py 集成 — LLM 优先 + 关键词降级
5. FeedbackAnalysis schema 验证
6. Jinja2 模板渲染
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from src.audiobook_studio.feedback.llm_analyzer import LLMFeedbackAnalyzer
from src.audiobook_studio.schemas import FeedbackAnalysis

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_router():
    """创建一个 mock LLMRouter."""
    router = MagicMock()
    return router


@pytest.fixture
def analyzer(mock_router, tmp_path):
    """创建使用 mock router 的 LLMFeedbackAnalyzer.

    使用项目 prompts/ 目录作为 prompt_dir。
    """
    prompt_dir = Path(__file__).parent.parent.parent / "prompts"
    return LLMFeedbackAnalyzer(
        router=mock_router,
        prompt_dir=str(prompt_dir),
    )


@pytest.fixture
def sample_feedback():
    """样例反馈数据."""
    return {
        "stage": "annotate",
        "llm_output": {
            "speaker": "旁白",
            "emotion": "neutral",
            "text": "他说道：'你好'",
        },
        "corrected_output": {
            "speaker": "张三",
            "emotion": "happy",
            "text": "他说道：'你好'",
        },
        "rationale": "对话归属错误，说话人应该是张三而不是旁白。情感也不对，应该是开心的。",
        "key_differences": [
            "speaker: '旁白' → '张三'",
            "emotion: 'neutral' → 'happy'",
        ],
    }


@pytest.fixture
def sample_feedback_simple():
    """简单样例反馈数据."""
    return {
        "stage": "translate",
        "llm_output": {"text": "Hello world"},
        "corrected_output": {"text": "你好世界"},
        "rationale": "翻译需要更自然",
        "key_differences": ["text: 'Hello world' → '你好世界'"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# 1. Mock 模式分析
# ──────────────────────────────────────────────────────────────────────────────


class TestAnalyzeMock:
    """测试 analyze_mock 方法（不调用 LLM）."""

    def test_mock_returns_feedback_analysis(self, analyzer, sample_feedback):
        """analyze_mock 应返回 FeedbackAnalysis 实例."""
        result = analyzer.analyze_mock(
            stage=sample_feedback["stage"],
            llm_output=sample_feedback["llm_output"],
            corrected_output=sample_feedback["corrected_output"],
            rationale=sample_feedback["rationale"],
            key_differences=sample_feedback["key_differences"],
        )

        assert isinstance(result, FeedbackAnalysis)
        assert result.severity == "medium"
        assert result.confidence == 0.5

    def test_mock_detects_dialogue_attribution(self, analyzer):
        """mock 模式应检测到对话归属问题."""
        result = analyzer.analyze_mock(
            stage="annotate",
            llm_output={"speaker": "旁白"},
            corrected_output={"speaker": "张三"},
            rationale="对话归属错误",
            key_differences=["speaker: '旁白' → '张三'"],
        )
        assert "dialogue_attribution" in result.pattern_tags

    def test_mock_detects_emotion_too_mild(self, analyzer):
        """mock 模式应检测到情感不足."""
        result = analyzer.analyze_mock(
            stage="annotate",
            llm_output={"emotion": "neutral"},
            corrected_output={"emotion": "angry"},
            rationale="情感不足，应该更愤怒",
            key_differences=["emotion: 'neutral' → 'angry'"],
        )
        assert "emotion_too_mild" in result.pattern_tags

    def test_mock_detects_emotion_too_strong(self, analyzer):
        """mock 模式应检测到情感过度."""
        result = analyzer.analyze_mock(
            stage="annotate",
            llm_output={"emotion": "angry"},
            corrected_output={"emotion": "neutral"},
            rationale="情感过度了",
            key_differences=["emotion: 'angry' → 'neutral'"],
        )
        assert "emotion_too_strong" in result.pattern_tags

    def test_mock_detects_speaker_wrong(self, analyzer):
        """mock 模式应检测到说话人错误."""
        result = analyzer.analyze_mock(
            stage="annotate",
            llm_output={"speaker": "A"},
            corrected_output={"speaker": "B"},
            rationale="角色/说话人错误",
            key_differences=["speaker: 'A' → 'B'"],
        )
        assert "speaker_wrong" in result.pattern_tags

    def test_mock_detects_pause_missing(self, analyzer):
        """mock 模式应检测到停顿缺失."""
        result = analyzer.analyze_mock(
            stage="annotate",
            llm_output={"pause": "0"},
            corrected_output={"pause": "1.5"},
            rationale="缺少停顿",
            key_differences=["pause: '0' → '1.5'"],
        )
        assert "pause_missing" in result.pattern_tags

    def test_mock_detects_prosody_robotic(self, analyzer):
        """mock 模式应检测到韵律机械."""
        result = analyzer.analyze_mock(
            stage="annotate",
            llm_output={"prosody": "flat"},
            corrected_output={"prosody": "varied"},
            rationale="太机械了，不自然",
            key_differences=["prosody: 'flat' → 'varied'"],
        )
        assert "prosody_robotic" in result.pattern_tags

    def test_mock_no_tags_for_unknown(self, analyzer):
        """未知关键词应返回空 pattern_tags."""
        result = analyzer.analyze_mock(
            stage="translate",
            llm_output={"text": "A"},
            corrected_output={"text": "B"},
            rationale="just a style preference",
            key_differences=["text: 'A' → 'B'"],
        )
        assert result.pattern_tags == []

    def test_mock_summary_contains_rationale(self, analyzer, sample_feedback):
        """mock 模式的 semantic_summary 应包含 rationale 片段."""
        result = analyzer.analyze_mock(
            stage=sample_feedback["stage"],
            llm_output=sample_feedback["llm_output"],
            corrected_output=sample_feedback["corrected_output"],
            rationale=sample_feedback["rationale"],
            key_differences=sample_feedback["key_differences"],
        )
        assert "对话归属错误" in result.semantic_summary


# ──────────────────────────────────────────────────────────────────────────────
# 2. LLM 调用成功路径
# ──────────────────────────────────────────────────────────────────────────────


class TestAnalyzeSuccess:
    """测试 analyze 方法 LLM 调用成功."""

    def test_analyze_calls_router(self, analyzer, mock_router, sample_feedback):
        """analyze 应调用 router.call."""
        expected = FeedbackAnalysis(
            pattern_tags=["dialogue_attribution", "emotion_wrong"],
            semantic_summary="对话归属和情感标注错误",
            severity="high",
            actionable_instruction="检查引号归属并从上下文推断说话人",
            root_cause="prompt 缺少对话归属判断规则",
            confidence=0.9,
        )
        mock_result = MagicMock()
        mock_result.output = expected
        mock_router.call.return_value = mock_result

        result = analyzer.analyze(
            stage=sample_feedback["stage"],
            llm_output=sample_feedback["llm_output"],
            corrected_output=sample_feedback["corrected_output"],
            rationale=sample_feedback["rationale"],
            key_differences=sample_feedback["key_differences"],
        )

        assert result == expected
        mock_router.call.assert_called_once()
        # 验证调用参数
        call_kwargs = mock_router.call.call_args
        assert call_kwargs.kwargs["stage"] == "judge"
        assert call_kwargs.kwargs["response_model"] == FeedbackAnalysis

    def test_analyze_returns_correct_tags(self, analyzer, mock_router, sample_feedback):
        """analyze 应返回 LLM 分析的 pattern_tags."""
        expected = FeedbackAnalysis(
            pattern_tags=["narrator_pacing_inconsistent"],
            semantic_summary="旁白节奏不一致",
            severity="medium",
            actionable_instruction="统一旁白段落节奏",
            root_cause="缺少节奏控制示例",
            confidence=0.85,
        )
        mock_result = MagicMock()
        mock_result.output = expected
        mock_router.call.return_value = mock_result

        result = analyzer.analyze(**sample_feedback)
        assert result.pattern_tags == ["narrator_pacing_inconsistent"]
        assert result.severity == "medium"
        assert result.confidence == 0.85

    def test_analyze_passes_messages_with_system_and_user(self, analyzer, mock_router, sample_feedback_simple):
        """analyze 应构建 system + user 消息."""
        mock_result = MagicMock()
        mock_result.output = FeedbackAnalysis()
        mock_router.call.return_value = mock_result

        analyzer.analyze(**sample_feedback_simple)

        call_kwargs = mock_router.call.call_args
        messages = call_kwargs.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_analyze_with_empty_key_differences(self, analyzer, mock_router):
        """key_differences 为空时应正常工作."""
        mock_result = MagicMock()
        mock_result.output = FeedbackAnalysis(pattern_tags=["unknown"])
        mock_router.call.return_value = mock_result

        result = analyzer.analyze(
            stage="translate",
            llm_output={"text": "A"},
            corrected_output={"text": "B"},
            rationale="some reason",
            key_differences=None,  # 应被转为 []
        )
        assert result.pattern_tags == ["unknown"]


# ──────────────────────────────────────────────────────────────────────────────
# 3. LLM 调用失败降级
# ──────────────────────────────────────────────────────────────────────────────


class TestAnalyzeFailure:
    """测试 analyze 方法 LLM 调用失败."""

    def test_analyze_raises_on_llm_failure(self, analyzer, mock_router, sample_feedback):
        """LLM 调用失败时应抛出异常（由调用方捕获降级）."""
        mock_router.call.side_effect = Exception("LLM API timeout")

        with pytest.raises(Exception, match="LLM API timeout"):
            analyzer.analyze(**sample_feedback)

    def test_analyze_raises_on_invalid_response(self, analyzer, mock_router, sample_feedback):
        """LLM 返回无效数据时应抛出异常."""
        mock_router.call.side_effect = ValueError("Invalid response format")

        with pytest.raises(ValueError, match="Invalid response format"):
            analyzer.analyze(**sample_feedback)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Prompt 构建
# ──────────────────────────────────────────────────────────────────────────────


class TestPromptBuilding:
    """测试 _build_prompt 方法."""

    def test_prompt_contains_stage(self, analyzer, sample_feedback):
        """prompt 应包含 stage 信息."""
        prompt = analyzer._build_prompt(
            stage=sample_feedback["stage"],
            llm_output=sample_feedback["llm_output"],
            corrected_output=sample_feedback["corrected_output"],
            rationale=sample_feedback["rationale"],
            key_differences=sample_feedback["key_differences"],
        )
        assert "annotate" in prompt

    def test_prompt_contains_rationale(self, analyzer, sample_feedback):
        """prompt 应包含 rationale."""
        prompt = analyzer._build_prompt(
            stage=sample_feedback["stage"],
            llm_output=sample_feedback["llm_output"],
            corrected_output=sample_feedback["corrected_output"],
            rationale=sample_feedback["rationale"],
            key_differences=sample_feedback["key_differences"],
        )
        assert "对话归属错误" in prompt

    def test_prompt_contains_key_differences(self, analyzer, sample_feedback):
        """prompt 应包含 key_differences."""
        prompt = analyzer._build_prompt(
            stage=sample_feedback["stage"],
            llm_output=sample_feedback["llm_output"],
            corrected_output=sample_feedback["corrected_output"],
            rationale=sample_feedback["rationale"],
            key_differences=sample_feedback["key_differences"],
        )
        assert "旁白" in prompt
        assert "张三" in prompt

    def test_prompt_contains_schema(self, analyzer, sample_feedback):
        """prompt 应包含 JSON schema 信息."""
        prompt = analyzer._build_prompt(
            stage=sample_feedback["stage"],
            llm_output=sample_feedback["llm_output"],
            corrected_output=sample_feedback["corrected_output"],
            rationale=sample_feedback["rationale"],
            key_differences=sample_feedback["key_differences"],
        )
        # schema 中应包含 FeedbackAnalysis 的字段名
        assert "pattern_tags" in prompt
        assert "semantic_summary" in prompt
        assert "severity" in prompt


# ──────────────────────────────────────────────────────────────────────────────
# 5. FeedbackAnalysis Schema 验证
# ──────────────────────────────────────────────────────────────────────────────


class TestFeedbackAnalysisSchema:
    """测试 FeedbackAnalysis schema."""

    def test_default_values(self):
        """测试默认值."""
        fa = FeedbackAnalysis()
        assert fa.pattern_tags == []
        assert fa.semantic_summary == ""
        assert fa.severity == "medium"
        assert fa.actionable_instruction == ""
        assert fa.root_cause == ""
        assert fa.confidence == 0.8

    def test_valid_severity_values(self):
        """测试有效的 severity 值."""
        for sev in ["high", "medium", "low"]:
            fa = FeedbackAnalysis(severity=sev)
            assert fa.severity == sev

    def test_invalid_severity_raises(self):
        """无效 severity 应抛出 ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FeedbackAnalysis(severity="critical")

    def test_confidence_range(self):
        """confidence 应在 0-1 范围内."""
        fa = FeedbackAnalysis(confidence=0.0)
        assert fa.confidence == 0.0

        fa = FeedbackAnalysis(confidence=1.0)
        assert fa.confidence == 1.0

    def test_confidence_out_of_range_raises(self):
        """confidence 超出范围应抛出 ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FeedbackAnalysis(confidence=1.5)
        with pytest.raises(ValidationError):
            FeedbackAnalysis(confidence=-0.1)

    def test_custom_tags_allowed(self):
        """允许 LLM 自定义新标签."""
        fa = FeedbackAnalysis(pattern_tags=["custom_tag_from_llm", "another_new_pattern"])
        assert len(fa.pattern_tags) == 2

    def test_serialization(self):
        """测试 JSON 序列化."""
        fa = FeedbackAnalysis(
            pattern_tags=["test"],
            semantic_summary="test summary",
            severity="high",
            confidence=0.95,
        )
        data = fa.model_dump()
        assert data["pattern_tags"] == ["test"]
        assert data["severity"] == "high"
        assert data["confidence"] == 0.95

        # 反序列化
        fa2 = FeedbackAnalysis.model_validate(data)
        assert fa2 == fa


# ──────────────────────────────────────────────────────────────────────────────
# 6. Processor 集成 — LLM 优先 + 关键词降级
# ──────────────────────────────────────────────────────────────────────────────


class TestProcessorIntegration:
    """测试 processor.py 的 analyze_single_feedback 集成."""

    @pytest.fixture
    def mock_record(self):
        """创建 mock FeedbackRecord."""
        record = MagicMock()
        record.feedback_id = "test-fb-001"
        record.stage = "annotate"
        record.llm_output = {
            "speaker": "旁白",
            "emotion": "neutral",
            "text": "他说道：'你好'",
        }
        record.corrected_output = {
            "speaker": "张三",
            "emotion": "happy",
            "text": "他说道：'你好'",
        }
        record.rationale = "对话归属错误，说话人应该是张三"
        return record

    def test_llm_analyzer_unavailable_falls_back_to_keyword(self, mock_record):
        """LLM 分析器不可用时应降级到关键词匹配."""
        from src.audiobook_studio.feedback import processor

        with patch.object(processor, "_get_llm_analyzer", return_value=None):
            result = processor.analyze_single_feedback(mock_record)

        assert result.analysis_source == "keyword"
        assert len(result.pattern_tags) > 0
        assert result.semantic_summary is None

    def test_llm_analyzer_success(self, mock_record):
        """LLM 分析成功时应使用 LLM 结果."""
        from src.audiobook_studio.feedback import processor

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = FeedbackAnalysis(
            pattern_tags=["dialogue_attribution", "emotion_wrong"],
            semantic_summary="对话归属和情感标注错误",
            severity="high",
            actionable_instruction="检查引号归属",
            root_cause="prompt 缺少规则",
            confidence=0.9,
        )

        with patch.object(processor, "_get_llm_analyzer", return_value=mock_analyzer):
            result = processor.analyze_single_feedback(mock_record)

        assert result.analysis_source == "llm"
        assert "dialogue_attribution" in result.pattern_tags
        assert result.semantic_summary == "对话归属和情感标注错误"
        assert result.severity == "high"
        assert result.confidence == 0.9
        assert result.root_cause == "prompt 缺少规则"

    def test_llm_analyzer_failure_falls_back(self, mock_record):
        """LLM 分析失败时应降级到关键词匹配."""
        from src.audiobook_studio.feedback import processor

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.side_effect = Exception("LLM timeout")

        with patch.object(processor, "_get_llm_analyzer", return_value=mock_analyzer):
            result = processor.analyze_single_feedback(mock_record)

        assert result.analysis_source == "keyword"
        assert result.semantic_summary is None
        # 关键词匹配仍应产出 pattern_tags
        assert len(result.pattern_tags) > 0

    def test_diff_summary_contains_analysis_source(self, mock_record):
        """diff_summary 应包含 analysis_source 标记."""
        from src.audiobook_studio.feedback import processor

        with patch.object(processor, "_get_llm_analyzer", return_value=None):
            result = processor.analyze_single_feedback(mock_record)

        assert "Analysis source:" in result.diff_summary

    def test_diff_summary_contains_llm_fields_when_available(self, mock_record):
        """LLM 分析成功时 diff_summary 应包含语义字段."""
        from src.audiobook_studio.feedback import processor

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = FeedbackAnalysis(
            pattern_tags=["test_tag"],
            semantic_summary="测试摘要",
            severity="high",
            actionable_instruction="测试指令",
            root_cause="测试根因",
            confidence=0.9,
        )

        with patch.object(processor, "_get_llm_analyzer", return_value=mock_analyzer):
            result = processor.analyze_single_feedback(mock_record)

        assert "Summary:" in result.diff_summary
        assert "Root cause:" in result.diff_summary
        assert "Action:" in result.diff_summary
