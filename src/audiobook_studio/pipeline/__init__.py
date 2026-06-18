"""Pipeline package for audiobook processing stages.

Exports convenience functions for each pipeline stage:
- extract_text: Text extraction from various formats
- analyze_structure: Structural analysis of text
- annotate_paragraph: Paragraph-level annotation
- edit_for_tts: TTS preparation editing
- quality_check: Quality validation and scoring
- synthesize_paragraphs: Audio synthesis from paragraphs
"""

from .analyze_structure import AnalyzeStructurePipeline, analyze_structure
from .annotate_paragraph import AnnotateParagraphPipeline, annotate_paragraph
from .audio_postprocess import AudioPostProcessor
from .checkpoint import CheckpointManager
from .edit_for_tts import EditForTtsPipeline, edit_for_tts
from .feedback_collector import FeedbackCollector, StageCapture, create_feedback_collector

# Also export the pipeline classes for advanced usage
# Import convenience functions from each pipeline stage
from .extract import ExtractPipeline, extract_text
from .orchestrator import run_stage
from .quality_check import QualityCheckPipeline, quality_check
from .synthesize import SynthesizePipeline, synthesize_paragraphs

__all__ = [
    # Convenience functions
    "extract_text",
    "analyze_structure",
    "annotate_paragraph",
    "edit_for_tts",
    "quality_check",
    "synthesize_paragraphs",
    "run_stage",
    # Pipeline classes
    "ExtractPipeline",
    "AnalyzeStructurePipeline",
    "AnnotateParagraphPipeline",
    "EditForTtsPipeline",
    "QualityCheckPipeline",
    "SynthesizePipeline",
    # Orchestration components
    "CheckpointManager",
    "AudioPostProcessor",
    # Feedback collection for self-iteration
    "FeedbackCollector",
    "StageCapture",
    "create_feedback_collector",
]
