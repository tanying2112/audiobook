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
