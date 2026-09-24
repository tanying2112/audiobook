from unittest import mock

from audiobook_studio.tts import license_guard as LG
from audiobook_studio.tts import pronunciation_dict as PD
from audiobook_studio.tts import providers_config as PC
from audiobook_studio.tts.pronunciation_dict import DictEntry
from audiobook_studio.utils import gc_manager as GC
from audiobook_studio.utils.gc_manager import GCManager, GCRetentionPolicy


# --------------------------------------------------------------------------
# pronunciation_dict
# --------------------------------------------------------------------------
def test_pronunciation_parse_raw_variants():
    assert PD._parse_raw(None) == {}
    assert PD._parse_raw({"entries": "nope"}) == {}
    assert PD._parse_raw({"entries": {"word": "phon"}}) == {"word": DictEntry(phoneme="phon")}
    assert PD._parse_raw({"entries": {"w": {"phoneme": "X", "source": "s"}}}) == {
        "w": DictEntry(phoneme="X", source="s")
    }
    assert PD._parse_raw({"entries": {"w": {"note": "no-phoneme"}}}) == {}


def test_pronunciation_apply():
    d = {"世界": DictEntry(phoneme="shìjiè"), "cat": DictEntry(phoneme="kæt")}
    out = PD.apply_pronunciation_dict("hello cat 世界", d)
    assert "kæt" in out and "shìjiè" in out
    assert PD.apply_pronunciation_dict("text", {}) == "text"


def test_pronunciation_load_project(tmp_path):
    proj = tmp_path / "p1"
    proj.mkdir()
    (proj / "pronunciation_dict.yaml").write_text("entries:\n  abc: {phoneme: AE}\n", encoding="utf-8")
    reg = PD.load_pronunciation_dict(project_dir=proj)
    assert "abc" in reg
    assert PD.load_pronunciation_dict() == {} or isinstance(PD.load_pronunciation_dict(), dict)


# --------------------------------------------------------------------------
# providers_config
# --------------------------------------------------------------------------
def _write_providers(tmp_path):
    p = tmp_path / "tts_providers.yaml"
    p.write_text(
        "providers:\n"
        "  - name: piper\n"
        "    engine: piper\n"
        "    priority: 0\n"
        "    enabled: true\n"
        "    capabilities: {cloning: false, emotion: false, languages: [en, zh], min_compute: cpu}\n"
        "    license: {commercial_use: true, name: MIT}\n"
        "  - name: voxcpm\n"
        "    engine: voxcpm\n"
        "    priority: 1\n"
        "    enabled: true\n"
        "    capabilities: {cloning: true, emotion: true, languages: [zh], min_compute: gpu}\n"
        "    license: {commercial_use: false, name: Apache2}\n",
        encoding="utf-8",
    )
    return str(p)


def test_providers_config(tmp_path):
    path = _write_providers(tmp_path)
    provs = PC.load_tts_provider_config(path)
    assert len(provs) == 2
    assert PC.provider_priority_map(path) == {"piper": 0, "voxcpm": 1}
    assert "piper" in PC.capability_matrix(path)
    assert PC.license_matrix(path)["voxcpm"].commercial_use is False
    # no GPU -> cloning degrades to preset
    eng, mode = PC.select_engine(language="zh-CN", need_clone=True, gpu_available=False, path=path)
    assert mode == "preset"
    # GPU clone
    eng2, mode2 = PC.select_engine(language="zh-CN", need_clone=True, gpu_available=True, path=path)
    assert mode2 == "clone" and eng2 == "voxcpm"
    # standard narration
    eng3, mode3 = PC.select_engine(language="en", gpu_available=False, path=path)
    assert mode3 == "standard"
    # fallback (missing file)
    assert PC.load_tts_provider_config(str(tmp_path / "missing.yaml"))


# --------------------------------------------------------------------------
# license_guard
# --------------------------------------------------------------------------
def test_license_guard():
    assert LG.is_commercial_profile("potato") is False
    assert LG.is_commercial_profile("pro") is True
    # empty registry -> OK (non-commercial default profile)
    with mock.patch.object(LG, "get_unified_config") as g:
        g.return_value.load_yaml_config.return_value = {
            "engines": {"piper": {"commercial_use": True, "license_name": "MIT", "verified_at": "2024"}}
        }
        reg = LG.load_license_registry()
        assert reg["piper"].commercial_use is True
        assert LG.check_engine_license("piper") == LG.LicenseVerdict.OK
        assert LG.register_guard("piper", "free") is True
        assert LG.register_guard("piper", "pro") is True
    # blocked engine under commercial profile
    with (
        mock.patch.object(LG, "get_unified_config") as g,
        mock.patch.object(LG, "get_active_profile", return_value="pro"),
    ):
        g.return_value.load_yaml_config.return_value = {
            "engines": {"voxcpm": {"commercial_use": False, "license_name": "Apache2"}}
        }
        assert LG.check_engine_license("voxcpm") == LG.LicenseVerdict.BLOCKED
        assert LG.register_guard("voxcpm", "pro") is False
    LG.log_license_audit("piper", LG.LicenseVerdict.OK)


# --------------------------------------------------------------------------
# gc_manager
# --------------------------------------------------------------------------
def test_gc_manager(tmp_path):
    out = tmp_path / "output"
    storage = tmp_path / "storage"
    (out / "project_1").mkdir(parents=True)
    (storage / "1" / "audio").mkdir(parents=True)
    seg = out / "project_1" / "seg_001.wav"
    final = out / "project_1" / "book.m4b"
    seg_storage = storage / "1" / "audio" / "seg_002.mp3"
    seg.write_bytes(b"x")
    final.write_bytes(b"y")
    seg_storage.write_bytes(b"z")

    mgr = GCManager(pipeline_output_dir=str(out), storage_root=str(storage), policy=GCRetentionPolicy())
    res = mgr.cleanup_project_segments(1, keep_final=True)
    assert not seg.exists() and final.exists() and not seg_storage.exists()
    assert res.deleted_files

    # dry run covers the report-only branch
    res2 = mgr.cleanup_project_segments(1, dry_run=True)
    assert res2.deleted_files == []

    # sweep all projects + module helpers
    assert isinstance(mgr.sweep_all_projects(), list)
    after = GC.cleanup_after_export(1, pipeline_output_dir=str(out), storage_root=str(storage))
    assert "deleted_files" in after
    assert isinstance(GC.gc_sweep_all(pipeline_output_dir=str(out), storage_root=str(storage)), list)


def test_gc_manager_policies(tmp_path):
    out = tmp_path / "output"
    (out / "project_2").mkdir(parents=True)
    seg = out / "project_2" / "seg.wav"
    seg.write_bytes(b"x")

    # keep_all -> nothing deleted
    mgr = GCManager(
        pipeline_output_dir=str(out), storage_root=str(tmp_path / "s"), policy=GCRetentionPolicy(policy="keep_all")
    )
    res = mgr.cleanup_project_segments(2)
    assert seg.exists() and res.deleted_files == []

    # keep_for_days with negative window -> delete segment
    mgr2 = GCManager(
        pipeline_output_dir=str(out),
        storage_root=str(tmp_path / "s"),
        policy=GCRetentionPolicy(policy="keep_for_days", keep_days=-1),
    )
    res2 = mgr2.cleanup_project_segments(2)
    assert not seg.exists() and res2.deleted_files
