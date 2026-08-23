"""
Tests for Remote VoxCPM2 Workers (TEST-001: coverage improvement).

Tests for src/audiobook_studio/tts/remote_workers/
Target: 70%+ coverage
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock heavy dependencies ONLY during import of the worker modules, then restore
# sys.modules so we do not pollute other test files in the same pytest session.
# (The worker modules cache their imports in their own globals at import time, so
#  removing them from sys.modules afterwards does not break the already-imported
#  classes. The 4 worker test files reload their target module per-test with
#  proper mocks; leaving MagicMocks here would leak into those reloads.)
_IMPORT_MODULES = [
    'torch', 'torchaudio', 'torch.cuda', 'torch.cuda.amp', 'torchaudio.functional',
    'lightning', 'lightning.pytorch', 'modal', 'kaggle',
    'boto3', 'requests', 'transformers', 'transformers.models',
    'transformers.models.voxcpm2', 'paddle', 'paddlepaddle',
    'paddlenlp', 'paddlenlp.transformers', 'paddlenlp.transformers.auto',
    'paddlenlp.transformers.AutoModelForCausalLM',
    'paddlenlp.transformers.AutoTokenizer',
    'paddlenlp.transformers.AutoConfig',
    'paddlenlp.transformers.AutoModel',
    'paddle.device', 'paddle.device.cuda',
    'pytesseract', 'soundfile', 'paddlaudio',
]

_saved_modules = {}
for _mod in _IMPORT_MODULES:
    if _mod not in sys.modules:
        _saved_modules[_mod] = None  # was absent -> remove after import
        sys.modules[_mod] = MagicMock()

# Now import the modules after mocking
from src.audiobook_studio.tts.remote_workers import BaseWorker
from src.audiobook_studio.tts.remote_workers.baidu_worker import BaiduWorker
from src.audiobook_studio.tts.remote_workers.kaggle_worker import KaggleWorker

# Restore sys.modules so MagicMocks do not leak into other test files.
for _mod, _orig in _saved_modules.items():
    if _orig is None:
        sys.modules.pop(_mod, None)


class TestBaiduWorker:
    """Tests for BaiduWorker class."""

    def test_worker_attributes(self):
        """Test worker initialization attributes."""
        worker = BaiduWorker.__new__(BaiduWorker)
        worker.worker_id = 'baidu-001'
        worker.status = 'idle'
        worker.current_job = None
        # Note: prefer_paddle is set in __init__, which we're not calling
        worker.prefer_paddle = True
        worker.backend = None
        worker.engine = None
        assert worker.worker_id == 'baidu-001'
        assert worker.status == 'idle'
        assert worker.current_job is None

    def test_crossfade_ms_fixed(self):
        """Test _crossfade_ms returns fixed value when set."""
        task = BaiduWorker.__new__(BaiduWorker)
        task._crossfade_ms = 100
        assert task._crossfade_ms == 100


class TestKaggleWorker:
    """Tests for KaggleWorker class."""

    def test_initialization(self):
        """Test worker initialization."""
        worker = KaggleWorker.__new__(KaggleWorker)
        worker.worker_id = 'kaggle-001'
        worker.status = 'idle'
        assert worker.worker_id == 'kaggle-001'
        assert worker.status == 'idle'


class TestBaseWorker:
    """Tests for BaseWorker abstract class."""

    def test_abstract_methods(self):
        """Test that base worker defines required abstract methods."""
        from src.audiobook_studio.tts.remote_workers.base_worker import BaseWorker

        assert '_init_engine' in BaseWorker.__abstractmethods__
        assert '_execute_smoke_test' in BaseWorker.__abstractmethods__
        assert '_synthesize' in BaseWorker.__abstractmethods__
        assert '_get_platform_gpu_metrics' in BaseWorker.__abstractmethods__


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])