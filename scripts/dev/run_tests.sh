#!/bin/bash
cd /Users/guwj/Desktop/AI_Lab/audiobook
source .venv/bin/activate
echo "=== Running test_auto_run.py ==="
python -m pytest tests/unit/test_auto_run.py -v --tb=short 2>&1 | tail -60
echo ""
echo "=== Running test_templates_business.py ==="
python -m pytest tests/unit/test_templates_business.py -v --tb=short 2>&1 | tail -80
echo ""
echo "=== Running test_real_audio_processing.py ==="
python -m pytest tests/integration/test_real_audio_processing.py -v --tb=short 2>&1 | tail -60
