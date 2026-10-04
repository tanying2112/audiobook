"""Pipeline Stage: Segment - Text segmentation into paragraphs/sentences.

Supports three strategies:
1. rule: Fast heuristic-based splitting (spaCy + punctuation/length)
2. semantic: Embedding-based semantic coherence clustering
3. llm: LLM-based structured segmentation with prompt engineering

The segment stage runs after extract and before analyze.
"""

import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config.loader import load_pipeline_config
from ..llm import LLMRouter, create_router
from ..schemas import ExtractionResult, ParagraphAnnotation

logger = logging.getLogger(__name__)


class SegmentStrategy(str, Enum):
    """Available segmentation strategies."""

    RULE = "rule"
    SEMANTIC = "semantic"
    LLM = "llm"


@dataclass
class SegmentConfig:
    """Configuration for segmentation."""

    strategy: SegmentStrategy = SegmentStrategy.RULE
    # Rule-based config
    max_paragraph_chars: int = 2000
    min_paragraph_chars: int = 50
    # Semantic config
    semantic_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    semantic_similarity_threshold: float = 0.75
    # LLM config
    llm_prompt_template: Optional[str] = None
    # Common
    preserve_dialogue: bool = True
    language: str = "zh"  # zh, en, auto


@dataclass
class Segment:
    """A single text segment (paragraph or sentence group)."""

    text: str
    index: int
    start_char: int
    end_char: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return len(self.text)


@dataclass
class SegmentationResult:
    """Result of segmentation."""

    segments: List[Segment]
    strategy_used: SegmentStrategy
    config: SegmentConfig
    stats: Dict[str, Any] = field(default_factory=dict)


class BaseSegmenter(ABC):
    """Abstract base class for segmenters."""

    def __init__(self, config: SegmentConfig):
        self.config = config

    @abstractmethod
    def segment(self, text: str) -> SegmentationResult:
        """Segment text into paragraphs."""
        pass

    def _post_process_segments(self, segments: List[Segment], text: str) -> List[Segment]:
        """Post-process segments: merge short header-like paragraphs with next segment."""
        if not segments:
            return segments

        # Merge heuristic: if a segment is short (< 50 chars) and doesn't end with
        # sentence-ending punctuation, it's likely a header - merge with next segment
        merged = []
        i = 0
        while i < len(segments):
            seg = segments[i]
            # Check if this segment looks like a header (short, no sentence end punctuation)
            is_short = len(seg.text) < 50
            ends_with_punct = bool(re.search(r"[。！？.!?]\s*$", seg.text.strip()))

            if is_short and not ends_with_punct and i + 1 < len(segments):
                # Merge with next segment
                next_seg = segments[i + 1]
                merged_text = seg.text + "\n\n" + next_seg.text
                merged.append(
                    Segment(
                        text=merged_text,
                        index=len(merged),
                        start_char=seg.start_char,
                        end_char=next_seg.end_char,
                        metadata={
                            "sentence_count": (
                                seg.metadata.get("sentence_count", 0) + next_seg.metadata.get("sentence_count", 0)
                            ),
                            "merged_from": [seg.index, next_seg.index],
                        },
                    )
                )
                i += 2  # Skip next segment since we merged it
            else:
                # Re-index the segment
                new_seg = Segment(
                    text=seg.text,
                    index=len(merged),
                    start_char=seg.start_char,
                    end_char=seg.end_char,
                    metadata=seg.metadata,
                )
                merged.append(new_seg)
                i += 1

        return merged


class RuleSegmenter(BaseSegmenter):
    """Rule-based segmenter using punctuation and heuristics.

    Uses spaCy for sentence boundary detection combined with
    heuristic rules for paragraph grouping.
    """

    def __init__(self, config: SegmentConfig):
        super().__init__(config)
        self._nlp = None

    def _get_nlp(self):
        """Lazy load spaCy model."""
        if self._nlp is None:
            try:
                import spacy

                # Try to load appropriate model based on language
                if self.config.language == "zh":
                    model_name = "zh_core_web_sm"
                elif self.config.language == "en":
                    model_name = "en_core_web_sm"
                else:
                    model_name = "xx_sent_ud_sm"  # Multilingual

                try:
                    self._nlp = spacy.load(model_name)
                except OSError:
                    logger.warning(f"spaCy model {model_name} not found, using blank model")
                    self._nlp = spacy.blank(self.config.language if self.config.language != "auto" else "zh")
            except ImportError:
                logger.warning("spaCy not available, using regex fallback")
                self._nlp = None
        return self._nlp

    def segment(self, text: str) -> SegmentationResult:
        """Segment using rule-based approach."""
        nlp = self._get_nlp()

        if nlp is not None:
            result = self._segment_with_spacy(text, nlp)
        else:
            result = self._segment_with_regex(text)

        # Post-process: merge short header-like paragraphs
        merged_segments = self._post_process_segments(result.segments, text)
        result.segments = merged_segments
        return result

    def _segment_with_spacy(self, text: str, nlp) -> SegmentationResult:
        """Segment using spaCy sentence detection, respecting paragraph boundaries."""
        # First, split by paragraph boundaries (double newlines)
        para_starts = [0]
        para_ends = []

        # Find all double newline positions
        for match in re.finditer(r"\n\s*\n", text):
            para_ends.append(match.start())
            para_starts.append(match.end())
        para_ends.append(len(text))

        segments = []
        segment_index = 0
        total_sentence_count = 0

        for _, (start, end) in enumerate(zip(para_starts, para_ends, strict=False)):
            para = text[start:end]
            if not para.strip():
                continue

            # Process this paragraph with spaCy for sentence detection
            doc = nlp(para)
            sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
            total_sentence_count += len(sentences)

            if not sentences:
                continue

            # If the entire paragraph fits within max_paragraph_chars, keep it as one segment
            # (natural paragraph boundary is preserved regardless of min_paragraph_chars)
            full_para = " ".join(sentences)
            if len(full_para) <= self.config.max_paragraph_chars:
                segments.append(
                    Segment(
                        text=full_para,
                        index=segment_index,
                        start_char=start,
                        end_char=start + len(full_para),
                        metadata={"sentence_count": len(sentences)},
                    )
                )
                segment_index += 1
                continue

            # Paragraph is too long - need to split it, respecting min_paragraph_chars for split parts
            current_segment = ""
            current_start = start

            for sent in sentences:
                # Check if adding this sentence would exceed max length
                if current_segment and len(current_segment) + len(sent) > self.config.max_paragraph_chars:
                    # Finalize current segment (apply min_paragraph_chars only for forced splits)
                    if len(current_segment) >= self.config.min_paragraph_chars:
                        segments.append(
                            Segment(
                                text=current_segment,
                                index=segment_index,
                                start_char=current_start,
                                end_char=current_start + len(current_segment),
                                metadata={"sentence_count": current_segment.count("。") + current_segment.count(".")},
                            )
                        )
                        segment_index += 1
                    current_segment = sent
                    current_start = para.find(sent, current_start - start)
                    if current_start == -1:
                        current_start = start
                    else:
                        current_start += start
                else:
                    if current_segment:
                        current_segment += " " + sent
                    else:
                        current_segment = sent
                        current_start = (
                            para.find(sent, current_start - start) if current_start < start else current_start
                        )
                        if current_start == -1 or current_start < start:
                            current_start = start

            # Don't forget the last segment in this paragraph
            if current_segment and len(current_segment) >= self.config.min_paragraph_chars:
                segments.append(
                    Segment(
                        text=current_segment,
                        index=segment_index,
                        start_char=current_start,
                        end_char=current_start + len(current_segment),
                        metadata={"sentence_count": current_segment.count("。") + current_segment.count(".")},
                    )
                )
                segment_index += 1

        return SegmentationResult(
            segments=segments,
            strategy_used=SegmentStrategy.RULE,
            config=self.config,
            stats={"method": "spacy", "sentence_count": total_sentence_count, "paragraph_count": len(para_starts)},
        )

    def _segment_with_regex(self, text: str) -> SegmentationResult:
        """Fallback segmentation using regex patterns with position tracking."""
        # Find all paragraph boundaries (double newlines) with positions
        # Use finditer to get positions of paragraph separators
        para_starts = [0]
        para_ends = []

        # Find all double newline positions
        for match in re.finditer(r"\n\s*\n", text):
            para_ends.append(match.start())
            para_starts.append(match.end())
        para_ends.append(len(text))

        # Now we have paragraph boundaries with correct positions
        segments = []
        segment_index = 0

        for _, (start, end) in enumerate(zip(para_starts, para_ends, strict=False)):
            para = text[start:end].strip()
            if not para:
                continue

            # If paragraph is too long, split by sentence-ending punctuation
            if len(para) > self.config.max_paragraph_chars:
                # Split by Chinese/English sentence endings (including no-space case for Chinese)
                # Use lookbehind to split AFTER punctuation, then filter empty
                sentences = re.split(r"(?<=[。！？.!?])", para)
                # Filter empty strings and strip whitespace
                sentences = [s.strip() for s in sentences if s.strip()]
                current = ""
                current_start = start

                for sent in sentences:
                    sent = sent.strip()
                    if not sent:
                        continue

                    # Find sentence position in original text
                    sent_pos = text.find(sent, current_start, end)
                    if sent_pos == -1:
                        sent_pos = current_start

                    if current and len(current) + len(sent) > self.config.max_paragraph_chars:
                        if len(current) >= self.config.min_paragraph_chars:
                            segments.append(
                                Segment(
                                    text=current,
                                    index=segment_index,
                                    start_char=current_start,
                                    end_char=current_start + len(current),
                                )
                            )
                            segment_index += 1
                        current = sent
                        current_start = sent_pos
                    else:
                        if current:
                            current += " " + sent
                        else:
                            current = sent
                            current_start = sent_pos

                if current and len(current) >= self.config.min_paragraph_chars:
                    segments.append(
                        Segment(
                            text=current,
                            index=segment_index,
                            start_char=current_start,
                            end_char=current_start + len(current),
                        )
                    )
                    segment_index += 1
            else:
                # Natural paragraph boundary - keep as is regardless of min_paragraph_chars
                if len(para) >= 1:  # At least 1 char (empty already filtered)
                    segments.append(
                        Segment(
                            text=para,
                            index=segment_index,
                            start_char=start,
                            end_char=end,
                        )
                    )
                    segment_index += 1

        return SegmentationResult(
            segments=segments,
            strategy_used=SegmentStrategy.RULE,
            config=self.config,
            stats={"method": "regex", "raw_paragraphs": len(para_starts)},
        )


class SemanticSegmenter(BaseSegmenter):
    """Semantic segmenter using sentence embeddings and clustering.

    Groups sentences by semantic coherence using sentence-transformers.
    """

    def __init__(self, config: SegmentConfig):
        super().__init__(config)
        self._model = None

    def _get_model(self):
        """Lazy load sentence transformer model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.config.semantic_model)
            except ImportError:
                logger.warning("sentence-transformers not available, falling back to rule-based")
                return None
        return self._model

    def segment(self, text: str) -> SegmentationResult:
        """Segment using semantic similarity."""
        model = self._get_model()

        if model is None:
            # Fallback to rule-based
            rule_segmenter = RuleSegmenter(self.config)
            result = rule_segmenter.segment(text)
            result.strategy_used = SegmentStrategy.SEMANTIC
            result.stats["fallback"] = "rule"
            return result

        # First, split into sentences using rule-based
        rule_segmenter = RuleSegmenter(self.config)
        rule_result = rule_segmenter._segment_with_regex(text)
        sentences = [seg.text for seg in rule_result.segments]

        if len(sentences) <= 1:
            return SegmentationResult(
                segments=rule_result.segments,
                strategy_used=SegmentStrategy.SEMANTIC,
                config=self.config,
                stats={"method": "semantic", "sentence_count": len(sentences), "note": "single sentence"},
            )

        # Compute embeddings
        embeddings = model.encode(sentences)

        # Cluster by semantic similarity
        segments = self._cluster_sentences(sentences, embeddings, text)

        return SegmentationResult(
            segments=segments,
            strategy_used=SegmentStrategy.SEMANTIC,
            config=self.config,
            stats={"method": "semantic", "sentence_count": len(sentences), "clusters": len(segments)},
        )

    def _cluster_sentences(self, sentences: List[str], embeddings, original_text: str) -> List[Segment]:
        """Cluster sentences by semantic similarity."""
        import numpy as np

        segments = []
        current_cluster = [0]  # Start with first sentence
        segment_index = 0
        char_offset = 0

        for i in range(1, len(sentences)):
            # Compute similarity with cluster centroid
            cluster_embeddings = embeddings[current_cluster]
            centroid = np.mean(cluster_embeddings, axis=0)
            similarity = np.dot(embeddings[i], centroid) / (
                np.linalg.norm(embeddings[i]) * np.linalg.norm(centroid) + 1e-8
            )

            # Check if we should start a new segment
            current_text = " ".join(sentences[j] for j in current_cluster)
            if (
                similarity < self.config.semantic_similarity_threshold
                or len(current_text) > self.config.max_paragraph_chars
            ):
                # Finalize current cluster
                segment_text = " ".join(sentences[j] for j in current_cluster)
                start_pos = original_text.find(sentences[current_cluster[0]], char_offset)
                if start_pos >= 0:
                    segments.append(
                        Segment(
                            text=segment_text,
                            index=segment_index,
                            start_char=start_pos,
                            end_char=start_pos + len(segment_text),
                            metadata={"sentence_count": len(current_cluster), "avg_similarity": float(similarity)},
                        )
                    )
                    segment_index += 1
                    char_offset = start_pos + len(segment_text)

                current_cluster = [i]
            else:
                current_cluster.append(i)

        # Don't forget the last cluster
        if current_cluster:
            segment_text = " ".join(sentences[j] for j in current_cluster)
            start_pos = original_text.find(sentences[current_cluster[0]], char_offset)
            if start_pos >= 0:
                segments.append(
                    Segment(
                        text=segment_text,
                        index=segment_index,
                        start_char=start_pos,
                        end_char=start_pos + len(segment_text),
                        metadata={"sentence_count": len(current_cluster)},
                    )
                )

        return segments


class LLMSegmenter(BaseSegmenter):
    """LLM-based segmenter using structured prompts."""

    def __init__(self, config: SegmentConfig):
        super().__init__(config)
        self._router = None

    def _get_router(self) -> LLMRouter:
        """Get or create LLM router."""
        if self._router is None:
            self._router = create_router(mock_mode=os.environ.get("MOCK_LLM", "false").lower() == "true")
        return self._router

    def segment(self, text: str) -> SegmentationResult:
        """Segment using LLM with structured output."""
        router = self._get_router()

        prompt = self._build_prompt(text)

        try:
            from pydantic import TypeAdapter

            from ..schemas import Segment as SegmentSchema

            result = router.call(
                stage="segment",
                response_model=TypeAdapter(List[SegmentSchema]),
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
            )

            if result and result.output:
                segments = []
                for i, seg_data in enumerate(result.output):
                    start_pos = text.find(seg_data.text)
                    if start_pos >= 0:
                        segments.append(
                            Segment(
                                text=seg_data.text,
                                index=i,
                                start_char=start_pos,
                                end_char=start_pos + len(seg_data.text),
                                metadata=seg_data.metadata or {},
                            )
                        )

                return SegmentationResult(
                    segments=segments,
                    strategy_used=SegmentStrategy.LLM,
                    config=self.config,
                    stats={"method": "llm", "llm_model": getattr(router, "model", "unknown")},
                )

        except Exception as e:
            logger.error(f"LLM segmentation failed: {e}, falling back to rule-based")
            rule_segmenter = RuleSegmenter(self.config)
            result = rule_segmenter.segment(text)
            result.strategy_used = SegmentStrategy.LLM
            result.stats["fallback"] = "rule"
            result.stats["error"] = str(e)
            return result

        # Fallback
        rule_segmenter = RuleSegmenter(self.config)
        result = rule_segmenter.segment(text)
        result.strategy_used = SegmentStrategy.LLM
        result.stats["fallback"] = "rule"
        return result

    def _get_system_prompt(self) -> str:
        """Get system prompt for segmentation."""
        return """你是专业的文本分段专家。请将输入文本分割为语义连贯的段落。

规则：
1. 每个段落应包含完整的语义单元（场景、话题、对话）
2. 对话应保持在同一段落内
3. 段落长度建议 100-2000 字符
4. 保留原文的标点和格式
5. 输出 JSON 数组，每个元素包含：text, metadata"""

    def _build_prompt(self, text: str) -> str:
        """Build user prompt for segmentation."""
        if self.config.llm_prompt_template:
            return self.config.llm_prompt_template.format(text=text, max_chars=self.config.max_paragraph_chars)

        return f"""请将以下文本分割为语义连贯的段落（每段 100-{self.config.max_paragraph_chars} 字符）。

文本：
{text[:8000]}{'...' if len(text) > 8000 else ''}

输出格式（JSON 数组）：
[
  {{"text": "段落1文本", "metadata": {{"type": "narrative"}}}},
  {{"text": "段落2文本", "metadata": {{"type": "dialogue"}}}}
]"""


class SegmentPipeline:
    """Main pipeline for text segmentation."""

    def __init__(
        self,
        config: Optional[SegmentConfig] = None,
        config_path: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ):
        """Initialize segment pipeline.

        Args:
            config: SegmentConfig object (takes precedence over config_path)
            config_path: Path to YAML config file
            mock_mode: If True, use mock LLM. Defaults to MOCK_LLM env var.
        """
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = os.environ.get("MOCK_LLM", "false").lower() == "true"

        # Load config
        if config is not None:
            self.config = config
        elif config_path:
            self.config = self._load_config(config_path)
        else:
            self.config = SegmentConfig()

        # Initialize segmenters
        self._segmenters = {
            SegmentStrategy.RULE: RuleSegmenter(self.config),
            SegmentStrategy.SEMANTIC: SemanticSegmenter(self.config),
            SegmentStrategy.LLM: LLMSegmenter(self.config),
        }

        logger.info(f"SegmentPipeline initialized with strategy={self.config.strategy}, mock_mode={self.mock_mode}")

    def _load_config(self, config_path: str) -> SegmentConfig:
        """Load config from YAML file."""
        raw_config = load_pipeline_config(config_path)
        seg_config = raw_config.get("segment", {})

        return SegmentConfig(
            strategy=SegmentStrategy(seg_config.get("strategy", "rule")),
            max_paragraph_chars=seg_config.get("max_paragraph_chars", 2000),
            min_paragraph_chars=seg_config.get("min_paragraph_chars", 50),
            semantic_model=seg_config.get(
                "semantic_model", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            ),
            semantic_similarity_threshold=seg_config.get("semantic_similarity_threshold", 0.75),
            llm_prompt_template=seg_config.get("llm_prompt_template"),
            preserve_dialogue=seg_config.get("preserve_dialogue", True),
            language=seg_config.get("language", "zh"),
        )

    def run(
        self,
        text: Optional[str] = None,
        extract_file: Optional[str] = None,
        extraction_result: Optional[ExtractionResult] = None,
    ) -> SegmentationResult:
        """Run segmentation.

        Args:
            text: Raw text to segment
            extract_file: Path to extracted text file
            extraction_result: ExtractionResult from extract stage

        Returns:
            SegmentationResult with segments
        """
        # Resolve input text
        if text is None:
            if extraction_result is not None:
                text = extraction_result.raw_text
            elif extract_file is not None:
                text = Path(extract_file).read_text(encoding="utf-8")
            else:
                raise ValueError("Must provide text, extract_file, or extraction_result")

        logger.info(f"Segmenting text ({len(text)} chars) using {self.config.strategy.value} strategy")

        # Get appropriate segmenter
        segmenter = self._segmenters.get(self.config.strategy)
        if segmenter is None:
            logger.warning(f"Unknown strategy {self.config.strategy}, falling back to rule")
            segmenter = self._segmenters[SegmentStrategy.RULE]

        # Run segmentation
        result = segmenter.segment(text)

        logger.info(f"Segmentation complete: {len(result.segments)} segments")
        return result

    def to_paragraph_annotations(self, result: SegmentationResult) -> List[ParagraphAnnotation]:
        """Convert segmentation result to ParagraphAnnotations for downstream stages."""
        annotations = []
        for seg in result.segments:
            # Detect if dialogue
            is_dialogue = "「" in seg.text or "「" in seg.text or '"' in seg.text

            annotations.append(
                ParagraphAnnotation(
                    paragraph_index=seg.index,
                    speaker_canonical_name="_narrator_",
                    is_dialogue=is_dialogue,
                    emotion="neutral",
                    emotion_intensity=0.5,
                    speech_rate=1.0,
                    pitch_shift_semitones=0,
                    confidence=0.9,
                    needs_sfx=False,
                    sfx_tags=[],
                    pause_before_ms=300,
                    pause_after_ms=500,
                )
            )
        return annotations


def segment_text(
    text: str,
    strategy: SegmentStrategy = SegmentStrategy.RULE,
    config: Optional[SegmentConfig] = None,
    mock_mode: bool = False,
) -> SegmentationResult:
    """Convenience function for segmentation."""
    pipeline = SegmentPipeline(config=config, mock_mode=mock_mode)
    if config:
        pipeline.config.strategy = strategy
    return pipeline.run(text=text)


if __name__ == "__main__":  # pragma: no cover

    logging.basicConfig(level=logging.INFO)

    # Quick test
    test_text = """这是第一段叙述文字。它描述了故事的开始。

"你好！"主角说道。"这是对话。"

这是第二段叙述。故事继续发展。"""

    pipeline = SegmentPipeline(mock_mode=True)
    result = pipeline.run(text=test_text)

    logger.info(f"Strategy: {result.strategy_used}")
    logger.info(f"Segments: {len(result.segments)}")
    for seg in result.segments:
        logger.info(f"  [{seg.index}] {seg.text[:50]}...")
