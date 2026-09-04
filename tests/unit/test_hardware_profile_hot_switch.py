"""Item 10: runtime hot-switch observability.

Proves that switching the active hardware tier (via ``set_active_profile`` /
``reload_hardware_profile``) is observed by downstream consumers without a
process restart — the core contract of hardware hot-reload.
"""

from unittest.mock import MagicMock

from src.audiobook_studio.config.hardware_profile import get_hardware_profile, reset_hardware_profile
from src.audiobook_studio.llm import LLMRouter
from src.audiobook_studio.pipeline.quality_check import QualityCheckPipeline
from src.audiobook_studio.schemas import ParagraphAnnotation


def test_hot_switch_reflected_in_quality_checker():
    """QualityChecker re-syncs its hardware-derived config on a runtime switch."""
    reset_hardware_profile()
    profile = get_hardware_profile()
    try:
        profile.set_active_profile("cloud_hybrid")
        qc = QualityCheckPipeline(mock_mode=True)

        # Switch to potato at runtime: heavy quality metrics must turn off.
        profile.set_active_profile("potato")
        qc._sync_hardware_profile()
        assert qc.hardware_profile.active_profile == "potato"
        assert qc._hw_dnsmos_enabled is False
        assert qc._hw_asr_enabled is False
        assert qc._hw_speaker_sim_enabled is False
        # Underlying suite is rebuilt for the new tier (device selection).
        assert qc._quality_suite.hardware_profile == "potato"

        # Switch to pro_studio: stricter thresholds and heavy metrics on.
        profile.set_active_profile("pro_studio")
        qc._sync_hardware_profile()
        assert qc.hardware_profile.active_profile == "pro_studio"
        assert qc._hw_dnsmos_enabled is True
        assert qc._hw_dnsmos_min == 3.8
        assert qc._hw_asr_wer_max == 0.03
        assert qc._hw_speaker_sim_enabled is True
        assert qc._quality_suite.hardware_profile == "pro_studio"
    finally:
        reset_hardware_profile()


def test_run_re_resolves_hardware_profile_on_each_call():
    """``run`` re-applies the live hardware profile so a switch is honored."""
    reset_hardware_profile()
    try:
        # ``run`` must re-resolve the live hardware profile at entry so a runtime
        # switch is honored on the next run without a restart. Guard the wiring
        # with a source check (a full run needs real audio + LLM, out of scope).
        import inspect

        qc = QualityCheckPipeline(mock_mode=True)
        run_src = inspect.getsource(qc.run)
        assert "_sync_hardware_profile()" in run_src
    finally:
        reset_hardware_profile()


def test_hot_switch_reflected_in_llm_router():
    """LLMRouter observes the active tier's stage model map at call time."""
    reset_hardware_profile()
    profile = get_hardware_profile()
    try:
        profile.set_active_profile("potato")
        router = LLMRouter(mock_mode=True)

        captured = {}

        def spy_routing(stage, providers, stage_models):
            captured["stage_models"] = stage_models
            return providers

        router._apply_hardware_profile_routing = spy_routing
        # Avoid depending on real provider config in this unit test.
        router.config.get_providers_for_stage = lambda _: [MagicMock(name="provider")]

        # potato has no stage_model_map → routing is skipped entirely.
        router.call(
            stage="extract",
            response_model=ParagraphAnnotation,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert "stage_models" not in captured

        # Switch to pro_studio at runtime: the same router instance must now
        # apply gemini_pro / gemini-1.5-pro to the extract stage.
        profile.set_active_profile("pro_studio")
        router.call(
            stage="extract",
            response_model=ParagraphAnnotation,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert captured["stage_models"]
        models = {m["provider"]: m["model"] for m in captured["stage_models"]}
        assert models.get("gemini_pro") == "gemini-1.5-pro"
    finally:
        reset_hardware_profile()


def test_hardware_profile_env_selection(monkeypatch):
    """HARDWARE_PROFILE env var deterministically selects the active tier.

    Mirrors docker-compose.gpu.yml setting HARDWARE_PROFILE=pro_studio so the
    GPU deployment boots straight into pro_studio instead of auto-detecting.
    """
    monkeypatch.setenv("HARDWARE_PROFILE", "pro_studio")
    reset_hardware_profile()
    try:
        profile = get_hardware_profile()
        assert profile.active_profile == "pro_studio"
        assert profile.active_profile == "pro_studio"
    finally:
        monkeypatch.delenv("HARDWARE_PROFILE", raising=False)
        reset_hardware_profile()


def test_hardware_profile_env_unknown_falls_back_to_config(monkeypatch, caplog):
    """An unknown HARDWARE_PROFILE is ignored (falls back to config/auto-detect)."""
    import logging

    monkeypatch.setenv("HARDWARE_PROFILE", "does_not_exist")
    reset_hardware_profile()
    try:
        with caplog.at_level(logging.WARNING):
            profile = get_hardware_profile()
        assert profile.active_profile in ("potato", "cloud_hybrid", "pro_studio")
        assert "HARDWARE_PROFILE" in caplog.text
    finally:
        monkeypatch.delenv("HARDWARE_PROFILE", raising=False)
        reset_hardware_profile()
