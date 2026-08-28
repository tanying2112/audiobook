"""Tests for S2-4 Piper model registry & downloader (reuses P0-2 logic)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from audiobook_studio.tts import piper_models as pm


def test_default_voice_is_chinese():
    assert pm.DEFAULT_PIPER_VOICE == "zh_CN-huayan-medium"
    assert pm.DEFAULT_PIPER_VOICE in pm.PIPER_VOICE_MODELS


def test_get_piper_model_path():
    base = Path("/tmp/models/piper")
    model_path, json_path = pm.get_piper_model_path("zh_CN-huayan-medium", base)
    assert model_path == base / "zh_CN-huayan-medium.onnx"
    assert json_path == base / "zh_CN-huayan-medium.onnx.json"


def test_build_files_spec_includes_onnx_and_json():
    spec = pm.build_piper_files_spec(["zh_CN-huayan-medium"])
    assert "zh_CN-huayan-medium.onnx" in spec
    assert "zh_CN-huayan-medium.onnx.json" in spec
    assert spec["zh_CN-huayan-medium.onnx"]["url"].endswith(".onnx")
    assert spec["zh_CN-huayan-medium.onnx.json"]["url"].endswith(".onnx.json")


def test_detect_no_binary_returns_false():
    with patch.dict("os.environ", {}, clear=True), patch("shutil.which", return_value=None):
        available, detail = pm.detect_piper_availability(binary="nonexistent_bin_xyz")
        assert available is False
        assert detail["reason"] == "binary_not_found"


def test_detect_binary_but_no_model_returns_false(tmp_path):
    bin_path = tmp_path / "piper"
    bin_path.write_text("#!/bin/sh\n")
    with patch.dict("os.environ", {}, clear=True), patch("shutil.which", return_value=None):
        available, detail = pm.detect_piper_availability(binary=str(bin_path), model_dir=tmp_path)
        assert available is False
        assert detail["reason"] == "model_not_found"
        assert detail["binary"] == str(bin_path)


def test_detect_binary_and_model_returns_true(tmp_path):
    bin_path = tmp_path / "piper"
    bin_path.write_text("#!/bin/sh\n")
    (tmp_path / "zh_CN-huayan-medium.onnx").write_bytes(b"fake-model")
    with patch.dict("os.environ", {}, clear=True), patch("shutil.which", return_value=None):
        available, detail = pm.detect_piper_availability(binary=str(bin_path), model_dir=tmp_path)
        assert available is True
        assert detail["model"].endswith(".onnx")
        assert detail["model_count"] == 1


def test_detect_respects_local_tts_disabled(tmp_path):
    (tmp_path / "zh_CN-huayan-medium.onnx").write_bytes(b"fake-model")
    with patch.dict("os.environ", {"ENABLE_LOCAL_TTS": "false"}, clear=True), patch("shutil.which", return_value=None):
        available, detail = pm.detect_piper_availability(binary="/usr/bin/piper", model_dir=tmp_path)
        assert available is False
        assert detail["reason"] == "local_tts_disabled"


def test_ensure_piper_models_skips_when_present(tmp_path):
    model = tmp_path / "zh_CN-huayan-medium.onnx"
    model.write_bytes(b"fake")
    jsonf = tmp_path / "zh_CN-huayan-medium.onnx.json"
    jsonf.write_bytes(b"{}")
    with patch.object(pm, "download_file") as mock_dl:
        ok = pm.ensure_piper_models(tmp_path, voices=["zh_CN-huayan-medium"])
        assert ok is True
        mock_dl.assert_not_called()  # already present -> no download


def test_ensure_piper_models_downloads_when_missing(tmp_path):
    def _fake_dl(url, filepath, expected_size_mb=None, progress_bar=None):
        Path(filepath).write_bytes(b"fake-model-bytes")
        return True, ""

    with patch.object(pm, "download_file", side_effect=_fake_dl):
        ok = pm.ensure_piper_models(tmp_path, voices=["zh_CN-huayan-medium"])
        assert ok is True
        assert (tmp_path / "zh_CN-huayan-medium.onnx").exists()
        assert (tmp_path / "zh_CN-huayan-medium.onnx.json").exists()


def test_list_piper_voices_marks_availability(tmp_path):
    (tmp_path / "zh_CN-huayan-medium.onnx").write_bytes(b"fake")
    voices = pm.list_piper_voices(tmp_path)
    ids = {v.voice_id for v in voices}
    assert "zh_CN-huayan-medium" in ids
    assert "zh_CN-shaoer-medium" in ids
    huayan = next(v for v in voices if v.voice_id == "zh_CN-huayan-medium")
    assert huayan.engine == "piper"
    assert huayan.language == "zh-CN"
