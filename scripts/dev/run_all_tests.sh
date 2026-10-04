#!/bin/bash
set -e
cd /Users/guwj/Desktop/AI_Lab/audiobook
.venv/bin/python -m pytest tests/unit/test_templates_business.py tests/unit/test_auto_run.py tests/integration/test_real_audio_processing.py -v --tb=short
