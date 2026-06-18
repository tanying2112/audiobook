"""
Self-Iteration Integration Module

This module connects all feedback components into an automated self-iteration loop:
FeedbackCollector → FeedbackProcessor → PromptUpgrader → Pipeline Re-execution → Validation

The integration provides:
1. Automated feedback collection from pipeline stages
2. Periodic batch analysis triggering
3. Prompt auto-upgrade based on pattern analysis
4. Pipeline re-execution with upgraded prompts
5. Quality validation and regression checking
6. Promotion gating for new prompt versions
"""

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from sqlalchemy.orm import Session

from ..models import FeedbackRecord as FeedbackRecordModel
from ..storage import project_dir
from .collector import FeedbackCollector, create_feedback_collector
from .processor import AggregateAnalysis, analyze_batch, analyze_single_feedback
from .prompt_upgrader import batch_upgrade, upgrade_prompt
from .promotion_gate import evaluate_promotion
from .auto_processor import FeedbackAutoProcessor, create_auto_processor
from .quality_enhancement import (
    check_semantic_coherence,
    validate_emotions,
    grade_difficulty,
    get_free_tier_health,
    get_false_positive_tracker,
)

logger = logging.getLogger(__name__)


class SelfIterationLoop:
    """
    Orchestrates the complete self-iteration feedback loop.

    Flow:
    1. Pipeline stages generate feedback via FeedbackCollector
    2. FeedbackAutoProcessor monitors and triggers batch analysis
    3. FeedbackProcessor analyzes patterns and generates recommendations
    4. PromptUpgrader creates new prompt versions based on patterns
    5. Pipeline re-executes with new prompts (canary mode)
    6. Quality enhancement validates the new outputs
    7. Promotion gate evaluates if new prompts should be promoted
    """

    def __slf🌟