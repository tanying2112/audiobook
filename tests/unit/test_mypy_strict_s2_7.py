"""Tests for S2.7 — Pydantic v2 model_dump() + mypy --strict zero errors.

Guards against regressions:
- No Pydantic v1 ``.dict()`` calls remain anywhere in src/.
- No Pydantic v1 model ``.json()`` (non-DRF / non-stdlib json) calls remain.
- ``mypy --strict`` over ``src/audiobook_studio`` exits 0 (config-based, the
  same staged policy CI uses).
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "audiobook_studio"


def _py_files():
    return [str(p) for p in SRC.rglob("*.py")]


def test_no_pydantic_v1_dict_calls():
    """S2.7: every .dict() must have been migrated to .model_dump()."""
    bad = []
    for f in _py_files():
        with open(f, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if ".dict(" in line:
                    bad.append(f"{f}:{i}: {line.strip()}")
    assert not bad, "Found Pydantic v1 .dict() calls:\n" + "\n".join(bad)


def test_no_pydantic_v1_model_json_calls():
    """S2.7: no Pydantic model .json() method calls (use model_dump_json)."""
    bad = []
    for f in _py_files():
        with open(f, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                s = line.strip()
                # Exclude stdlib/file json usage and HTTP response.json()
                if ".json(" in s and not any(
                    x in s for x in ("json.dumps", "json.loads", "response.json",
                                     "resp.json", ".read_text().json", "r.json",
                                     "Path(", "json_file", "load_json", "save_json")
                ):
                    bad.append(f"{f}:{i}: {s}")
    assert not bad, "Possible Pydantic v1 .json() model calls:\n" + "\n".join(bad)


@pytest.mark.slow
def test_mypy_strict_passes():
    """S2.7: mypy --strict over src must exit 0 (0 errors)."""
    python = sys.executable
    cfg = REPO_ROOT / "mypy.ini"
    result = subprocess.run(
        [python, "-m", "mypy", "--strict", "src/audiobook_studio",
         "--config-file", str(cfg),
         # Per-process cache dir so concurrent pytest workers don't race on the
         # shared .mypy_cache (which caused spurious non-hermetic failures).
         "--cache-dir", tempfile.mkdtemp(prefix="mypy_strict_")],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
    )
    assert result.returncode == 0, (
        f"mypy --strict failed (rc={result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )
