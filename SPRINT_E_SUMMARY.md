# Sprint E: Self-Iteration Feedback Loop Implementation Summary

## Overview
Sprint E implemented a complete self-iteration feedback loop that enables the Audiobook Studio system to autonomously improve its prompt templates based on human feedback and quality judgments.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Pipeline       │────▶│  Feedback        │────▶│  Feedback        │
│  Stages         │     │  Collector       │     │  Processor       │
└─────────────────┘     └──────────────────┘     └────────┬─────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Pipeline       │◀───│  Promotion       │◀───│  Prompt          │
│  Re-execution   │     │  Gate            │     │  Upgrader        │
└─────────────────┘     └──────────────────┘     └──────────────────┘
```

## Components Implemented

### 1. FeedbackCollector (`src/audiobook_studio/pipeline/feedback_collector.py`)
- **File-based storage**: Persists feedback to `storage/books/<project_id>/feedback/raw/`
- **Context manager**: `StageCapture` wraps each pipeline stage
- **Three feedback sources**: `human_edit`, `quality_judge`, `user_rating`
- **Auto-save**: Saves automatically when context exits with all required fields

### 2. FeedbackProcessor (`src/audiobook_studio/feedback/processor.py`)
- **Single feedback analysis**: `analyze_single_feedback()` - diff extraction + pattern tagging
- **Batch analysis**: `analyze_batch()` - aggregates patterns across all unprocessed feedback
- **Pattern tags**: 16 predefined tags (e.g., `dialogue_attribution`, `emotion_too_mild`, `prosody_robotic`)
- **Recommendations**: Generates actionable prompt improvement suggestions
- **Trend reports**: Tracks pattern frequency over time

### 3. PromptUpgrader (`src/audiobook_studio/feedback/prompt_upgrader.py`)
- **Pattern→Prompt mapping**: 16 pattern tags mapped to specific prompt fixes
- **Version management**: Auto-increments version (v1.j2 → v2.j2)
- **Changelog**: Maintains `CHANGELOG.md` per prompt directory
- **Batch upgrade**: `batch_upgrade()` processes all patterns from analysis
- **Stage mapping**: Maps patterns to pipeline stages (`edit_for_tts`, `quality_judge`, etc.)

### 4. PromotionGate (`src/audiobook_studio/feedback/promotion_gate.py`)
- **Four checks**: Format compliance, Golden dataset, Human sample, Quality improvement
- **Configurable thresholds**: `promotion_config.yaml`
- **Canary evaluation**: Validates new prompts on subset before promotion
- **Decision**: Returns `PromotionResult` with promoted/rejected status and reasons

### 5. QualityEnhancement (`src/audiobook_studio/feedback/quality_enhancement.py`)
- **Semantic coherence**: TF-IDF cosine similarity between adjacent paragraphs
- **Emotion validation**: Checks against valid emotion enums
- **Difficulty grading**: Dynamic weights for text complexity metrics
- **Free tier health**: System resource monitoring (CPU, memory, disk, load)
- **False positive tracking**: Adjusts quality scores based on historical false positive rates

### 6. AutoProcessor (`src/audiobook_studio/feedback/auto_processor.py`)
- **Background thread**: Monitors feedback count every 5 minutes (configurable)
- **Threshold trigger**: Auto-runs analysis when feedback ≥ min_feedback_count
- **Manual trigger**: `trigger_now()` for CLI/API use
- **Analysis reports**: Saves JSON reports to `feedback/analysis/`

### 7. SelfIterationLoop (`src/audiobook_studio/feedback/integration.py`)
- **Orchestrator**: Connects all components into automated loop
- **Monitor loop**: Checks for new analysis results every minute
- **Canary validation**: Runs quality checks with upgraded prompts
- **Promotion evaluation**: Uses PromotionGate for each upgraded prompt
- **Status API**: `get_status()` for monitoring

### 8. Pipeline Integration (`src/audiobook_studio/pipeline/orchestrator.py`)
- **Feedback collector parameter**: `run_stage()` accepts `feedback_collector`
- **All 7 stages integrated**: extract, analyze, annotate, edit, audio_postprocess, synthesize, quality
- **Auto-capture**: LLM outputs captured automatically; corrected outputs set externally

## Usage Examples

### Starting the Self-Iteration Loop
```python
from src.audiobook_studio.feedback.integration import create_self_iteration_loop
from src.audiobook_studio.database import SessionLocal

def session_factory():
    return SessionLocal()

loop = create_self_iteration_loop(
    db_session_factory=session_factory,
    project_id=1,
    min_feedback_count=10,
    check_interval_seconds=300,
    enable_auto_trigger=True,
    canary_percentage=0.1,
)

loop.start()
# ... runs in background ...
loop.stop()
```

### Collecting Feedback in Pipeline Stages
```python
from src.audiobook_studio.pipeline.feedback_collector import create_feedback_collector
from src.audiobook_studio.feedback.integration import collect_pipeline_feedback

collector = create_feedback_collector(project_id=1)

# In pipeline stage
with collect_pipeline_feedback(collector, "annotate", chapter_index=1, paragraph_index=5) as capture:
    result = llm_call(input_data)
    capture.set_llm_output(result.model_dump())
    # Later when human corrects:
    capture.set_corrected_output(corrected_result)
    capture.set_rationale("Fixed emotion detection for dialogue")
```

### CLI Usage
```bash
# Start loop as daemon
python scripts/run_self_iteration.py --project-id 1 start --daemon

# Check status
python scripts/run_self_iteration.py --project-id 1 status

# Trigger manual iteration
python scripts/run_self_iteration.py --project-id 1 trigger

# One-shot analysis
python scripts/run_self_iteration.py --project-id 1 once
```

## Configuration Files

### `config/promotion_config.yaml`
```yaml
checks:
  format_compliance:
    enabled: true
    weight: 0.2
  golden_dataset:
    enabled: true
    weight: 0.3
  human_sample:
    enabled: true
    weight: 0.3
    sample_size: 10
  quality_improvement:
    enabled: true
    weight: 0.2
    min_improvement: 0.05

promotion_threshold: 0.7
canary_percentage: 0.1
```

## Test Coverage

### Unit Tests Created
- `tests/unit/test_feedback_collector.py` - FeedbackCollector + StageCapture tests
- `tests/unit/test_feedback_processor.py` - Diff analysis, pattern tags, batch analysis
- `tests/unit/test_prompt_upgrader.py` - Version upgrade, pattern mapping, batch upgrade
- `tests/unit/test_promotion_gate.py` - All four promotion checks
- `tests/unit/test_quality_enhancement.py` - Coherence, emotions, difficulty, health, false positives
- `tests/unit/test_auto_processor.py` - Background monitoring, manual trigger, status
- `tests/unit/test_self_iteration_integration.py` - Complete loop integration tests

## Sprint E Deliverables Status

| Task | Status | Description |
|------|--------|-------------|
| H-P0-1 | ✅ | FeedbackCollector module for pipeline feedback hooks |
| H-P0-2 | ✅ | FeedbackProcessor auto-analysis trigger |
| H-P0-3 | ✅ | PromptUpgrader v2.j2 auto-generation |
| H-P0-4 | ⏳ | Promotion gate with canary validation |
| H-P0-5 | ✅ | Quality enhancement (coherence, emotions, difficulty, health) |
| H-P0-6 | ✅ | Auto-processor with threshold-based triggering |
| H-P0-7 | ✅ | SelfIterationLoop integration module |
| H-P0-8 | ✅ | Pipeline orchestrator integration |
| H-P0-9 | ✅ | Unit tests for all components |

## Next Steps (Sprint H)

1. **Automated Monitoring & Alerting** (Task #90)
   - DingTalk/Slack webhook alerts for promotion decisions
   - Health check alerts for free tier resources
   - Feedback threshold approaching alerts

2. **A/B Testing Framework** (Task #91)
   - Blind evaluation of old vs new prompts
   - Statistical significance testing
   - Automated rollback on regression

3. **Pipeline Re-execution** (Integration enhancement)
   - Actual canary re-run with upgraded prompts
   - Baseline comparison metrics
   - Incremental paragraph selection

## Files Created/Modified

### New Files
- `src/audiobook_studio/pipeline/feedback_collector.py`
- `src/audiobook_studio/feedback/collector.py`
- `src/audiobook_studio/feedback/processor.py`
- `src/audiobook_studio/feedback/prompt_upgrader.py`
- `src/audiobook_studio/feedback/promotion_gate.py`
- `src/audiobook_studio/feedback/quality_enhancement.py`
- `src/audiobook_studio/feedback/auto_processor.py`
- `src/audiobook_studio/feedback/integration.py`
- `src/audiobook_studio/feedback/promotion_config.yaml`
- `scripts/run_self_iteration.py`
- `tests/unit/test_feedback_collector.py`
- `tests/unit/test_feedback_processor.py`
- `tests/unit/test_prompt_upgrader.py`
- `tests/unit/test_promotion_gate.py`
- `tests/unit/test_quality_enhancement.py`
- `tests/unit/test_auto_processor.py`
- `tests/unit/test_self_iteration_integration.py`

### Modified Files
- `src/audiobook_studio/pipeline/orchestrator.py` - Added feedback_collector integration
- `src/audiobook_studio/feedback/__init__.py` - Exported all new modules

## Key Design Decisions

1. **File-based feedback storage**: Decouples feedback collection from database, enables offline analysis
2. **Pattern-based upgrades**: Predefined pattern→fix mappings ensure deterministic, auditable changes
3. **Canary validation**: Prevents bad prompt upgrades from affecting production
4. **Promotion gate**: Multi-criteria evaluation prevents single-metric gaming
5. **Background auto-processor**: Non-blocking, threshold-based analysis triggering
6. **Quality enhancement**: Multi-dimensional validation (semantic, emotion, system health)

## Metrics

- **Components**: 8 major modules
- **Lines of code**: ~3,500 (implementation) + ~1,500 (tests)
- **Pattern tags**: 16
- **Pipeline stages integrated**: 7
- **Feedback sources**: 3
- **Promotion checks**: 4