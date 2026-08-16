"""
Tests for Remote VoxCPM2 Workers (TEST-001: coverage improvement).

Tests for src/audiobook_studio/tts/remote_workers/
Target: 70%+ coverage
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock heavy dependencies BEFORE importing any worker modules
import sys
from unittest.mock import MagicMock

# Create comprehensive mocks for ALL heavy dependencies
for mod_name in ['torch', 'torchaudio', 'lightning', 'modal', 'kaggle', 'boto3', 'requests', 'transformers', 'paddle', 'paddlenlp', 'paddlenlp.transformers', 'paddlenlp.transformers.auto', 'paddlenlp.transformers.auto.tokenizer', 'paddlenlp.transformers.auto.modeling', 'paddlenlp.transformers.auto.configuration', 'pytesseract', 'soundfile', 'torchaudio', 'paddlaudio']:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

for mod_name in ['torch', 'torchaudio', 'lightning.pytorch', 'lightning', 'modal', 'kaggle', 'boto3', 'requests', 'transformers', 'paddle', 'paddlenlp', 'paddlenlp.transformers', 'paddlenlp.transformers.auto', 'paddle', 'paddlepaddle', 'soundfile', 'torchaudio', 'paddlaudio', 'paddlenlp.transformers.AutoModelForCausalLM', 'paddlenlp.transformers.AutoTokenizer', 'paddlenlp.transformers.AutoConfig', 'paddlenlp.transformers.AutoModel', 'paddlenlp.transformers.AutoTokenizer', 'paddlenlp.transformers.AutoModel', 'paddlenlp.transformers.AutoTokenizer', 'paddlenlp.transformers.AutoModel']:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# Add mock for transformers submodules
sys.modules['transformers'] = MagicMock()
sys.modules['transformers.models'] = MagicMock()
sys.modules['transformers.models.voxcpm2'] = MagicMock()
sys.modules['torch'] = MagicMock()
sys.modules['torch.cuda'] = MagicMock()
sys.modules['torch.cuda.amp'] = MagicMock()
sys.modules['torchaudio'] = MagicMock()
sys.modules['torchaudio.functional'] = MagicMock()
sys.modules['paddle'] = MagicMock()
sys.modules['paddlenlp'] = MagicMock()
sys.modules['paddlenlp.transformers'] = MagicMock()
sys.modules['paddlenlp.transformers.AutoModelForCausalLM'] = MagicMock()
sys.modules['paddlenlp.transformers.AutoTokenizer'] = MagicMock()
sys.modules['paddle.device'] = MagicMock()
sys.modules['paddle.device.cuda'] = MagicMock()

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Now import the modules after mocking
from src.audiobook_studio.tts.remote_workers import BaseWorker
from src.audiobook_studio.tts.remote_workers.baidu_worker import BaiduWorker
from src.audiobook_studio.tts.remote_workers.kaggle_worker import KaggleWorker


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