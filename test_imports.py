#!/usr/bin/env python3
"""Test script to verify imports work correctly."""

import sys
sys.path.insert(0, 'src')

# Test feedback_collector
try:
    from audiobook_studio.pipeline.feedback_collector import FeedbackCollector, StageCapture, create_feedback_collector
    print("✓ feedback_collector import OK")
except Exception as e:
    print(f"✗ feedback_collector import FAILED: {e}")

# Test auto_processor
try:
    from audiobook_studio.feedback.auto_processor import FeedbackAutoProcessor, create_auto_processor, run_feedback_analysis_cli
    print("✓ auto_processor import OK")
except Exception as e:
    print(f"✗ auto_processor import FAILED: {e}")

# Test orchestrator with feedback_collector
try:
    from audiobook_studio.pipeline.orchestrator import run_stage
    from audiobook_studio.pipeline.feedback_collector import FeedbackCollector
    import inspect
    sig = inspect.signature(run_stage)
    assert "feedback_collector" in sig.parameters
    print("✓ orchestrator feedback_collector integration OK")
except Exception as e:
    print(f"✗ orchestrator feedback_collector integration FAILED: {e}")

# Test pipeline __init__ exports
try:
    from audiobook_studio.pipeline import FeedbackCollector, StageCapture, create_feedback_collector
    print("✓ pipeline __init__ exports OK")
except Exception as e:
    print(f"✗ pipeline __init__ exports FAILED: {e}")

# Test feedback __init__ exports
try:
    from audiobook_studio.feedback import FeedbackAutoProcessor, create_auto_processor, run_feedback_analysis_cli
    print("✓ feedback __init__ exports OK")
except Exception as e:
    print(f"✗ feedback __init__ exports FAILED: {e}")

print("\nAll import tests completed!")