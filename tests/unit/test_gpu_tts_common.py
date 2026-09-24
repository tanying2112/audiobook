"""Unit tests for ``gpu_tts_common`` — the honesty-enforcing clone-resolution logic.

These run WITHOUT a GPU. They pin the project red line: a synthesis request that
carries a reference sample is a *clone* request, and the server must either hand
that reference to a real zero-shot entry point or fail loudly. It must never
silently degrade to a preset/default voice (the "fake clone" failure mode this
project refuses). That is why ``accepted_kwargs`` ignores ``**kwargs`` sinks and
``resolve_clone_invocation`` raises ``CloneNotSupportedError`` when no real
cloning entry point exists.

``tests/conftest_minimal.py`` installs MagicMock for ``numpy``/``soundfile``; the
``gpu`` fixture swaps the real libraries back in (same pattern as the
``real_soundfile`` fixture) and reloads the module so ``np`` binds to the real lib.
"""

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FakeTensor:
    """Duck-typed stand-in for a torch.Tensor (no torch import)."""

    def __init__(self, np, arr):
        self._np = np
        self._arr = self._np.asarray(arr, dtype=self._np.float32)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._arr


@pytest.fixture()
def gpu(monkeypatch):
    """Return (gpu_tts_common, real_numpy, real_soundfile) bound to real libs."""
    for mod_name in ("numpy", "soundfile"):
        monkeypatch.delitem(sys.modules, mod_name, raising=False)
    import numpy as np  # noqa: F401  (real)
    import soundfile as sf  # noqa: F401  (real)

    mod = importlib.import_module("gpu_tts_common")
    mod = importlib.reload(mod)
    return mod, np, sf


# ─────────────────────────────────────────────────────────────────────────────
# Fake model builds
# ─────────────────────────────────────────────────────────────────────────────
class CosyVoiceModel:
    """Mimics CosyVoice2's ``inference_zero_shot(tts_text, prompt_speech_16k, ...)``."""

    def __init__(self, np):
        self._np = np
        self.captured = None

    def inference_zero_shot(self, tts_text, prompt_speech_16k, prompt_text="", speed=1.0):
        self.captured = {
            "tts_text": tts_text,
            "prompt_speech_16k": prompt_speech_16k,
            "prompt_text": prompt_text,
            "speed": speed,
        }
        return self._np.zeros(16000, dtype=self._np.float32)


class FunASRModel:
    """Mimics FunASR's ``AutoModel.generate(input, **cfg)`` — a ``**kwargs`` sink."""

    def __init__(self, np):
        self._np = np
        self.captured = None

    def generate(self, input, **cfg):
        # A ``**kwargs`` sink silently swallows an unknown reference argument and
        # would synthesise the default (non-cloned) voice — the forbidden path.
        self.captured = {"input": input, "cfg": cfg}
        return self._np.zeros(16000, dtype=self._np.float32)


class NoCloneModel:
    """A model that has no zero-shot cloning entry point at all."""

    def classify(self, x):  # pragma: no cover - never called in these tests
        return x


# ─────────────────────────────────────────────────────────────────────────────
# Item 7(a): CosyVoice-style inference_zero_shot is resolved and called honestly
# ─────────────────────────────────────────────────────────────────────────────
def test_resolve_cosyvoice_inference_zero_shot(gpu, tmp_path):
    mod, np, sf = gpu
    sample = tmp_path / "ref.wav"
    sf.write(str(sample), np.zeros(16000, dtype=np.float32), 16000)

    model = CosyVoiceModel(np)
    load_prompt = lambda p: FakeTensor(np, np.zeros((1, 16000)))  # noqa: E731
    inv = mod.resolve_clone_invocation(
        model,
        text="你好世界",
        reference_audio_path=str(sample),
        reference_text="你好世界。",
        load_prompt=load_prompt,
    )

    assert inv.method_name == "inference_zero_shot"
    assert inv.prompt_kwarg == "prompt_speech_16k"
    assert inv.prompt_is_tensor is True
    assert inv.kwargs["tts_text"] == "你好世界"
    assert inv.kwargs["prompt_text"] == "你好世界。"
    assert isinstance(inv.kwargs["prompt_speech_16k"], FakeTensor)

    # The resolved invocation actually calls the model with the reference tensor.
    out = inv.call(model)
    assert model.captured["prompt_speech_16k"] is inv.kwargs["prompt_speech_16k"]
    assert model.captured["prompt_text"] == "你好世界。"
    normalized = mod.normalize_audio_result(out)
    assert normalized.shape == (1, 16000)


def test_resolve_cosyvoice_empty_reference_text_forwards_empty_string(gpu, tmp_path):
    mod, np, sf = gpu
    sample = tmp_path / "ref.wav"
    sf.write(str(sample), np.zeros(16000, dtype=np.float32), 16000)

    model = CosyVoiceModel(np)
    inv = mod.resolve_clone_invocation(
        model,
        text="hi",
        reference_audio_path=str(sample),
        reference_text=None,
        load_prompt=lambda p: FakeTensor(np, np.zeros((1, 16000))),
    )
    assert inv.kwargs["prompt_text"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# Item 7(b): a FunASR ``**kwargs`` sink is NOT silently selected for cloning
# ─────────────────────────────────────────────────────────────────────────────
def test_funasr_sink_rejected_without_override(gpu, tmp_path):
    mod, np, sf = gpu
    sample = tmp_path / "ref.wav"
    sf.write(str(sample), np.zeros(16000, dtype=np.float32), 16000)

    model = FunASRModel(np)
    with pytest.raises(mod.CloneNotSupportedError):
        mod.resolve_clone_invocation(
            model,
            text="hello",
            reference_audio_path=str(sample),
            load_prompt=lambda p: FakeTensor(np, np.zeros((1, 16000))),
        )


def test_funasr_sink_override_kwarg_is_explicit(gpu, tmp_path):
    """With an explicit CLONE_PROMPT_KWARG the operator opts in knowingly."""
    mod, np, sf = gpu
    sample = tmp_path / "ref.wav"
    sf.write(str(sample), np.zeros(16000, dtype=np.float32), 16000)

    model = FunASRModel(np)
    inv = mod.resolve_clone_invocation(
        model,
        text="hello",
        reference_audio_path=str(sample),
        reference_text="hello.",
        override_kwarg="prompt_wav_path",
        load_prompt=lambda p: FakeTensor(np, np.zeros((1, 16000))),
    )
    assert inv.explicit_override is True
    assert inv.prompt_kwarg == "prompt_wav_path"
    assert inv.kwargs["input"] == "hello"
    assert inv.kwargs["prompt_wav_path"] == str(sample)
    assert inv.kwargs["prompt_text"] == "hello."


# ─────────────────────────────────────────────────────────────────────────────
# Item 7(c): a model with no cloning entry point fails loudly
# ─────────────────────────────────────────────────────────────────────────────
def test_no_clone_entry_point_raises(gpu, tmp_path):
    mod, np, sf = gpu
    sample = tmp_path / "ref.wav"
    sf.write(str(sample), np.zeros(16000, dtype=np.float32), 16000)
    with pytest.raises(mod.CloneNotSupportedError):
        mod.resolve_clone_invocation(
            NoCloneModel(),
            text="x",
            reference_audio_path=str(sample),
            load_prompt=lambda p: FakeTensor(np, np.zeros((1, 16000))),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Item 7(d): a dangling reference_audio_path is a hard error, not a fake clone
# ─────────────────────────────────────────────────────────────────────────────
def test_dangling_reference_raises_filenotfound(gpu, tmp_path):
    mod, np, sf = gpu
    missing = tmp_path / "does_not_exist.wav"
    model = CosyVoiceModel(np)
    with pytest.raises(FileNotFoundError):
        mod.resolve_clone_invocation(
            model,
            text="x",
            reference_audio_path=str(missing),
            load_prompt=lambda p: FakeTensor(np, np.zeros((1, 16000))),
        )


# ─────────────────────────────────────────────────────────────────────────────
# normalize_audio_result shape handling
# ─────────────────────────────────────────────────────────────────────────────
def test_normalize_1d_becomes_2d(gpu):
    mod, np, sf = gpu
    out = mod.normalize_audio_result(np.zeros(16000, dtype=np.float32))
    assert out.shape == (1, 16000)
    assert out.dtype == np.float32


def test_normalize_passthrough_channels_first(gpu):
    mod, np, sf = gpu
    arr = np.zeros((2, 8000), dtype=np.float32)  # [channels, samples]
    out = mod.normalize_audio_result(arr)
    assert out.shape == (2, 8000)


def test_normalize_transposes_samples_first(gpu):
    mod, np, sf = gpu
    arr = np.zeros((8000, 2), dtype=np.float32)  # [samples, channels]
    out = mod.normalize_audio_result(arr)
    assert out.shape == (2, 8000)


def test_normalize_tensor(gpu):
    mod, np, sf = gpu
    out = mod.normalize_audio_result(FakeTensor(np, np.zeros((1, 16000))))
    assert out.shape == (1, 16000)


def test_normalize_dict_and_generator(gpu, tmp_path):
    mod, np, sf = gpu
    # dict keyed by tts_speech
    d = {"tts_speech": np.zeros(16000, dtype=np.float32)}
    assert mod.normalize_audio_result(d).shape == (1, 16000)
    # generator of chunk dicts (CosyVoice2 streaming), channels-last chunks
    chunks = ({"tts_speech": np.zeros((16000, 1), dtype=np.float32)} for _ in range(3))
    out = mod.normalize_audio_result(chunks)
    assert out.shape == (1, 16000 * 3)


def test_normalize_file_path(gpu, tmp_path):
    mod, np, sf = gpu
    wav = tmp_path / "clip.wav"
    sf.write(str(wav), np.zeros(16000, dtype=np.float32), 16000)
    out = mod.normalize_audio_result(str(wav))
    assert out.shape == (1, 16000)


def test_normalize_none_raises(gpu):
    mod, np, sf = gpu
    with pytest.raises(RuntimeError):
        mod.normalize_audio_result(None)
