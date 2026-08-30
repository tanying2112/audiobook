import platform
import sys
import urllib.request

import pytest


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """Make every unit test hermetic: network calls fail fast instead of
    hanging on unavailable external services (model/download endpoints)."""

    def _raise(*args, **kwargs):
        raise OSError("network disabled in unit tests")

    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    try:
        import requests

        for name in ("get", "post", "put", "delete", "head", "patch"):
            if hasattr(requests, name):
                monkeypatch.setattr(requests, name, _raise)
        if hasattr(requests, "Session"):
            monkeypatch.setattr(
                requests.Session,
                "request",
                lambda self, *a, **k: _raise(),
            )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 原生 codec/tts 后端测试在 macOS x86_64 + torch<2.5 环境下会 segfault：官方不为
# macOS x86_64 提供 PyTorch>=2.5 预编译 wheel，本机被迫使用 torch 2.2.2，与原生扩展
# （av / spacy / soundfile 的 libsndfile 等）ABI 冲突。tests/unit/codec 的用例在模块
# 顶层即强制加载真实 soundfile/torch 后端，故在收集期就会崩溃。
# 在此环境下跳过对 tests/unit/codec 的「收集」（连导入都不发生），避免崩溃；
# 具备官方 wheel 的平台（arm64 Mac / Linux x86_64）不受影响，照常运行。
# 属环境问题，非代码改动所致。真正的运行可在 conda/micromamba + conda-forge PyTorch
# 环境下进行（conda-forge 仍提供 macOS x86_64 的 PyTorch 构建）。
# ─────────────────────────────────────────────────────────────────────────────
def _native_codec_env_broken() -> bool:
    if sys.platform != "darwin" or platform.machine() != "x86_64":
        return False
    try:
        import torch

        major, minor = (int(x) for x in torch.__version__.split(".")[:2])
        return (major, minor) < (2, 5)
    except Exception:
        return True


if _native_codec_env_broken():
    collect_ignore = ["codec"]
