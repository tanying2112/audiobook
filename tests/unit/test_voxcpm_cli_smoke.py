import argparse
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

# transformers (too-new for torch 2.2.2) can clobber sys.modules['torch'] with
# None during pytest collection, which halts ``import torch``; and the conftest
# injects a MagicMock for ``torch`` that does NOT support ``import torch.nn``
# (which voxcpm performs at module load). Remove the mocked/None torch entries
# so voxcpm can import the *real* torch package.
for _k in list(sys.modules):
    if _k == "torch" or _k.startswith("torch."):
        del sys.modules[_k]

# voxcpm has now cached its own (real) torch reference at import time. The real
# torch package is broken in this environment, so it must NOT leak into the rest
# of the session (it crashes unrelated tests, e.g. spaCy -> thinc -> ``torch._C``
# -> ``NameError: name '_C' is not defined``). Re-establish the conftest
# canonical torch MagicMock for everyone else. voxcpm's tested CLI helpers never
# touch torch at runtime, so the restored mock is safe.
from tests.conftest_minimal import _force_torch_mock

from voxcpm import cli

_force_torch_mock()


def _ns(**kw):
    return argparse.Namespace(**kw)


def test_validate_file_exists():
    p = cli.validate_file_exists(__file__)
    assert Path(p).exists()
    with pytest.raises(FileNotFoundError):
        cli.validate_file_exists("/no/such/file/xyz")


def test_require_file_exists(tmp_path):
    good = tmp_path / "a.txt"
    good.write_text("x")
    assert cli.require_file_exists(str(good), argparse.ArgumentParser()).exists()
    with pytest.raises(SystemExit):
        cli.require_file_exists("/no/such/file/xyz", argparse.ArgumentParser())


def test_validate_output_path(tmp_path):
    out = tmp_path / "deep" / "sub" / "o.wav"
    res = cli.validate_output_path(str(out))
    assert res.parent.exists()


def test_validate_ranges_ok_and_errors():
    parser = argparse.ArgumentParser()
    good = _ns(cfg_value=2.0, inference_timesteps=10, lora_r=4, lora_alpha=8, lora_dropout=0.1)
    cli.validate_ranges(good, parser)
    bad = _ns(cfg_value=99.0, inference_timesteps=10, lora_r=4, lora_alpha=8, lora_dropout=0.1)
    with pytest.raises(SystemExit):
        cli.validate_ranges(bad, parser)
    bad = _ns(cfg_value=2.0, inference_timesteps=999, lora_r=4, lora_alpha=8, lora_dropout=0.1)
    with pytest.raises(SystemExit):
        cli.validate_ranges(bad, parser)
    bad = _ns(cfg_value=2.0, inference_timesteps=10, lora_r=0, lora_alpha=8, lora_dropout=0.1)
    with pytest.raises(SystemExit):
        cli.validate_ranges(bad, parser)
    bad = _ns(cfg_value=2.0, inference_timesteps=10, lora_r=4, lora_alpha=0, lora_dropout=0.1)
    with pytest.raises(SystemExit):
        cli.validate_ranges(bad, parser)
    bad = _ns(cfg_value=2.0, inference_timesteps=10, lora_r=4, lora_alpha=8, lora_dropout=2.0)
    with pytest.raises(SystemExit):
        cli.validate_ranges(bad, parser)


def test_build_final_text():
    assert cli.build_final_text("hi", None) == "hi"
    assert cli.build_final_text("hi", "  ") == "hi"
    assert cli.build_final_text("hi", "warm") == "(warm)hi"


def test_resolve_prompt_text(tmp_path):
    parser = argparse.ArgumentParser()
    pf = tmp_path / "p.txt"
    pf.write_text("  prompt content  ")
    assert cli.resolve_prompt_text(_ns(prompt_text=None, prompt_file=None), parser) is None
    assert cli.resolve_prompt_text(_ns(prompt_text="  hello  ", prompt_file=None), parser) == "hello"
    assert cli.resolve_prompt_text(_ns(prompt_text=None, prompt_file=str(pf)), parser) == "prompt content"
    with pytest.raises(SystemExit):
        cli.resolve_prompt_text(_ns(prompt_text="x", prompt_file=str(pf)), parser)


def test_detect_model_architecture(tmp_path):
    cfg = tmp_path / "model"
    cfg.mkdir()
    (cfg / "config.json").write_text(json.dumps({"architecture": "VoxCPM2"}))
    assert cli.detect_model_architecture(_ns(model_path=str(cfg), hf_model_id=None)) == "voxcpm2"
    (cfg / "config.json").unlink()
    assert cli.detect_model_architecture(_ns(model_path=str(cfg), hf_model_id=None)) is None
    assert cli.detect_model_architecture(_ns(model_path=None, hf_model_id=None)) is None
    assert cli.detect_model_architecture(_ns(model_path=None, hf_model_id="my-voxcpm2-ckpt")) == "voxcpm2"
    assert cli.detect_model_architecture(_ns(model_path=None, hf_model_id="voxcpm-1.5-base")) == "voxcpm"


def test_validate_prompt_related_args():
    parser = argparse.ArgumentParser()
    cli.validate_prompt_related_args(_ns(prompt_audio=None, prompt_text=None, control=None), parser, None)
    with pytest.raises(SystemExit):
        cli.validate_prompt_related_args(_ns(prompt_audio=None, prompt_text="x", control=None), parser, "x")
    with pytest.raises(SystemExit):
        cli.validate_prompt_related_args(_ns(prompt_audio="a.wav", prompt_text=None, control=None), parser, None)
    with pytest.raises(SystemExit):
        cli.validate_prompt_related_args(_ns(prompt_audio=None, prompt_text="x", control="c"), parser, "x")


def test_validate_reference_support(tmp_path):
    parser = argparse.ArgumentParser()
    cli.validate_reference_support(_ns(reference_audio=None, model_path=None, hf_model_id=None), parser)
    with pytest.raises(SystemExit):
        cli.validate_reference_support(
            _ns(reference_audio="r.wav", model_path=None, hf_model_id="voxcpm-1.5-base"), parser
        )
    cli.validate_reference_support(_ns(reference_audio="r.wav", model_path=None, hf_model_id="voxcpm2-ckpt"), parser)


def test_validate_design_args_and_clone_and_batch(tmp_path):
    parser = argparse.ArgumentParser()
    pf = tmp_path / "p.txt"
    pf.write_text("pt")
    cli.validate_design_args(_ns(prompt_audio=None, reference_audio=None, prompt_text=None, prompt_file=None), parser)
    with pytest.raises(SystemExit):
        cli.validate_design_args(
            _ns(prompt_audio=None, reference_audio=None, prompt_text="x", prompt_file=None), parser
        )
    cli.validate_clone_args(
        _ns(
            prompt_audio="a.wav",
            prompt_text=None,
            prompt_file=str(pf),
            reference_audio=None,
            model_path=None,
            hf_model_id="voxcpm2",
            control=None,
        ),
        parser,
    )
    with pytest.raises(SystemExit):
        cli.validate_clone_args(
            _ns(
                prompt_audio=None,
                prompt_text=None,
                prompt_file=None,
                reference_audio=None,
                model_path=None,
                hf_model_id=None,
                control=None,
            ),
            parser,
        )
    cli.validate_batch_args(
        _ns(
            prompt_audio="a.wav",
            prompt_text=None,
            prompt_file=str(pf),
            reference_audio=None,
            model_path=None,
            hf_model_id="voxcpm2",
            control=None,
        ),
        parser,
    )


def test_maybe_write_timestamps_and_default(tmp_path):
    ap = Path("/tmp/x.wav")
    assert cli.default_timestamp_path(ap) == Path("/tmp/x.timestamps.json")
    args = _ns(timestamps=False, timestamp_output=None)
    assert cli.maybe_write_timestamps(args, text="t", audio_path=ap, sample_rate=16000) is None

    out = tmp_path / "ts.json"
    args_on = _ns(
        timestamps=True,
        timestamp_output=str(out),
        timestamp_backend="whisper",
        timestamp_level="word",
        timestamp_model="tiny",
        timestamp_device="cpu",
        timestamp_language="zh",
        timestamp_strict=False,
    )
    with mock.patch.object(cli, "align_audio_file", return_value={"segments": []}):
        cli.maybe_write_timestamps(args_on, text="t", audio_path=ap, sample_rate=16000)
    assert out.exists()

    out2 = tmp_path / "ts2.json"
    args_strict = _ns(
        timestamps=True,
        timestamp_output=str(out2),
        timestamp_backend="whisper",
        timestamp_level="word",
        timestamp_model="tiny",
        timestamp_device="cpu",
        timestamp_language="zh",
        timestamp_strict=False,
    )
    with mock.patch.object(cli, "align_audio_file", side_effect=RuntimeError("boom")):
        cli.maybe_write_timestamps(args_strict, text="t", audio_path=ap, sample_rate=16000)
    assert not out2.exists()


def test_run_single_and_cmds(monkeypatch, tmp_path):
    model = mock.MagicMock()
    model.generate.return_value = [0.0, 0.0]
    model.tts_model.sample_rate = 16000
    monkeypatch.setattr(cli, "load_model", lambda args: model)
    writes = []
    import soundfile as sf

    monkeypatch.setattr(sf, "write", lambda *a, **k: writes.append(a))
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")

    class A:
        text = "hi"
        output = str(tmp_path / "o.wav")
        control = None
        prompt_audio = None
        reference_audio = str(ref)
        prompt_text = None
        prompt_file = None
        cfg_value = 2.0
        inference_timesteps = 10
        normalize = False
        denoise = False
        seed = None
        timestamps = False
        timestamp_output = None

    a = A()
    a.reference_audio = None
    parser = argparse.ArgumentParser()
    cli._run_single(a, parser, text="hi", output=a.output, prompt_text=None)
    assert writes
    cli.cmd_design(a, parser)
    a_clone = A()
    a_clone.reference_audio = str(ref)
    cli.cmd_clone(a_clone, parser)


def test_cmd_batch(monkeypatch, tmp_path):
    model = mock.MagicMock()
    model.generate.return_value = [0.0, 0.0]
    model.tts_model.sample_rate = 16000
    monkeypatch.setattr(cli, "load_model", lambda args: model)
    from unittest import mock as _m

    import soundfile as sf

    sf_write = _m.Mock()
    monkeypatch.setattr(sf, "write", sf_write)
    inp = tmp_path / "texts.txt"
    inp.write_text("line one\n\nline two\n")
    outdir = tmp_path / "outs"

    class A:
        input = str(inp)
        output_dir = str(outdir)
        control = None
        prompt_audio = None
        reference_audio = None
        prompt_text = None
        prompt_file = None
        cfg_value = 2.0
        inference_timesteps = 10
        normalize = False
        denoise = False
        seed = None
        timestamps = False
        timestamp_output = None

    a = A()
    parser = argparse.ArgumentParser()
    cli.cmd_batch(a, parser)
    assert sf_write.call_count == 2


def test_cmd_validate(monkeypatch, tmp_path):
    fake_validate = mock.MagicMock()
    fake_validate.validate_manifest.return_value = mock.MagicMock(is_valid=True)
    sys.modules["voxcpm.training.validate"] = fake_validate
    man = tmp_path / "m.jsonl"
    man.write_text("")
    parser = argparse.ArgumentParser()

    class A:
        manifest = str(man)
        sample_rate = 16000
        max_samples = 0
        verbose = False

    try:
        cli.cmd_validate(A(), parser)
    finally:
        sys.modules.pop("voxcpm.training.validate", None)
    assert fake_validate.validate_manifest.called


def test_build_parser_and_main_design(monkeypatch):
    parser = cli._build_parser()
    assert parser is not None
    monkeypatch.setattr(cli, "cmd_design", lambda args, parser: "design-ran")
    monkeypatch.setattr("sys.argv", ["voxcpm", "design", "--text", "hi", "-o", "/tmp/o.wav"])
    assert cli.main() == "design-ran"


def test_main_validate_dispatch(monkeypatch):
    monkeypatch.setattr(cli, "cmd_validate", lambda args, parser: "validate-ran")
    monkeypatch.setattr("sys.argv", ["voxcpm", "validate", "-m", "m.jsonl"])
    assert cli.main() == "validate-ran"
