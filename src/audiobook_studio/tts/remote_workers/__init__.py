"""Remote Workers Package for VoxCPM2 TTS.

Unified multi-cloud worker implementations for distributed TTS inference.
Each worker inherits from BaseWorker and implements platform-specific engine.

Usage:
    from audiobook_studio.tts.remote_workers import BaseWorker, LightningWorker, ModalWorker, BaiduWorker, KaggleWorker
"""

from .base_worker import BaseWorker, R2Uploader
from .lightning_worker import LightningWorker
from .modal_worker import ModalWorker
from .baidu_worker import BaiduWorker
from .kaggle_worker import KaggleWorker

__all__ = [
    "BaseWorker",
    "R2Uploader",
    "LightningWorker",
    "ModalWorker",
    "BaiduWorker",
    "KaggleWorker",
]