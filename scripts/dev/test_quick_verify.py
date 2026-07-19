#!/usr/bin/env python3
"""Quick verification script for the moved modules."""

import os

os.environ["MOCK_LLM"] = "true"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"

import sys

sys.path.insert(0, "src")

from audiobook_studio.pipeline import (
    analyze_structure,
    annotate_paragraph,
    edit_for_tts,
    extract_text,
    quality_check,
    synthesize_paragraphs,
)
from audiobook_studio.pipeline.analyze_structure import AnalyzeStructurePipeline, analyze_structure
from audiobook_studio.pipeline.annotate_paragraph import AnnotateParagraphPipeline, annotate_paragraph
from audiobook_studio.pipeline.checkpoint import CheckpointManager
from audiobook_studio.pipeline.edit_for_tts import EditForTtsPipeline, edit_for_tts

# Test imports
from audiobook_studio.pipeline.extract import ExtractPipeline, extract_text
from audiobook_studio.pipeline.feedback_collector import FeedbackCollector, StageCapture, create_feedback_collector
from audiobook_studio.pipeline.orchestrator import run_stage
from audiobook_studio.pipeline.quality_check import QualityCheckPipeline, quality_check
from audiobook_studio.pipeline.synthesize import SynthesizePipeline, synthesize_paragraphs

print("✅ All pipeline imports successful")

# Test basic instantiation
extract_pipe = ExtractPipeline()
analyze_pipe = AnalyzeStructurePipeline()
annotate_pipe = AnnotateParagraphPipeline()
edit_pipe = EditForTtsPipeline()
synth_pipe = SynthesizePipeline()
quality_pipe = QualityCheckPipeline()

print("✅ All pipeline classes instantiated successfully")

# Test feedback collector
collector = create_feedback_collector(project_id=1, enable=True)
print("✅ FeedbackCollector created successfully")

# Test checkpoint manager
checkpoint = CheckpointManager(project_id=1)
print("✅ CheckpointManager created successfully")

# Test schemas
from audiobook_studio.schemas import (
    BookAnalysisInput,
    BookAnalysisOutput,
    BookMeta,
    CharacterVoiceBinding,
    EmotionSnapshot,
    ExtractionInput,
    ExtractionResult,
    FeedbackRecord,
    ParagraphAnnotation,
    ParagraphAnnotationInput,
    QualityJudgment,
    TtsEditInput,
    TtsEditOutput,
    TtsRoutingDecision,
    TtsRoutingInput,
)

print("✅ All schema imports successful")

print("\n🎉 All verification passed!")
