"""audiobook_studio.schemas
~~~~~~~~~~~~~~~~~~~~~~~~~~
HARNESS 规范契约层 (Contract Layer) — 所有 Pydantic 模型定义。

三层架构:
1. 契约层: 本包 (Pydantic Schemas + 黄金数据集)
2. 执行层: LLM 调用 + Instructor 解析 + LiteLLM 路由
3. 评估层: LLM-as-a-Judge + 规则检查 (DNSMOS/ASR/SpeakerSim) + 人工校准

核心模型 (对应 6 个 LLM 环节 + 反馈):
* ExtractionInput / ExtractionResult          — 环节① 文本提取
* BookAnalysisInput / BookAnalysisOutput      — 环节② 结构分析 (上帝视角)
* ParagraphAnnotationInput / ParagraphAnnotation — 环节③ 段落标注
* TtsEditInput / TtsEditOutput                — 环节④ 文本编辑
* TtsRoutingInput / TtsRoutingDecision        — 环节⑤ TTS 路由
* QualityJudgment                             — 环节⑥ 质量检测
* FeedbackRecord                              — 反馈回路 (横切所有环节)
* ChapterSource / ChapterSourceCollection     — 章节源数据契约 (黄金数据集)
"""

from .audio_finalize import AudioFinalizeParams, AudioFinalizeResult
from .audio_postprocess import AudioPostProcessParams
from .book import Book, BookAnalysisInput, BookAnalysisOutput, BookMeta, CharacterVoiceBinding, EmotionSnapshot
from .chapter_source import ChapterSource, ChapterSourceCollection, ChapterSourceParagraph
from .extraction import ExtractionInput, ExtractionResult
from .feedback import FeedbackRecord
from .feedback_analysis import FeedbackAnalysis
from .paragraph import Paragraph, ParagraphAnnotation, ParagraphAnnotationInput
from .project import Project
from .quality import FixSuggestion, Quality, QualityJudgment
from .routing import Routing
from .tts_edit import TTSEdit, TtsEditInput, TtsEditOutput
from .tts_routing import TtsRoutingDecision, TtsRoutingInput

__all__ = [
    # 环节①
    "ExtractionInput",
    "ExtractionResult",
    # 环节②
    "BookAnalysisInput",
    "BookMeta",
    "CharacterVoiceBinding",
    "EmotionSnapshot",
    "BookAnalysisOutput",
    "Book",
    # 环节③
    "ParagraphAnnotationInput",
    "ParagraphAnnotation",
    "Paragraph",
    # 环节④
    "TtsEditInput",
    "TtsEditOutput",
    "TTSEdit",
    # 环节⑤
    "TtsRoutingInput",
    "TtsRoutingDecision",
    "Routing",
    # 环节⑥
    "QualityJudgment",
    "Quality",
    # 反馈回路
    "FeedbackRecord",
    "FeedbackAnalysis",
    # 章节源数据契约 (黄金数据集)
    "ChapterSource",
    "ChapterSourceCollection",
    "ChapterSourceParagraph",
    # 音频后处理契约
    "AudioFinalizeParams",
    "AudioFinalizeResult",
]
