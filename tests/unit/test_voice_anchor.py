"""Tests for Voice Anchor Module (Issue 1.3)."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.audiobook_studio.pipeline.voice_anchor import (
    VoiceAnchorConfig,
    VoiceAnchorManager,
    VoiceAnchorRecord,
    apply_voice_anchor,
    get_voice_anchor_manager,
    reset_voice_anchor_manager,
)


class TestVoiceAnchorConfig:
    """Tests for VoiceAnchorConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = VoiceAnchorConfig()
        assert config.enabled is True
        assert config.embedding_model == "wavlm_large"
        assert config.similarity_threshold == 0.85
        assert config.max_drift_alerts_per_chapter == 3
        assert config.reference_audio_dir == "storage/voice_anchors"

    def test_custom_config(self):
        """Test custom configuration values."""
        config = VoiceAnchorConfig(
            enabled=False,
            embedding_model="ecapa_tdnn",
            similarity_threshold=0.9,
            max_drift_alerts_per_chapter=5,
            reference_audio_dir="/custom/path",
        )
        assert config.enabled is False
        assert config.embedding_model == "ecapa_tdnn"
        assert config.similarity_threshold == 0.9
        assert config.max_drift_alerts_per_chapter == 5
        assert config.reference_audio_dir == "/custom/path"


class TestVoiceAnchorRecord:
    """Tests for VoiceAnchorRecord."""

    def test_record_creation(self):
        """Test creating a voice anchor record."""
        record = VoiceAnchorRecord(
            character_name="narrator",
            voice_id="zf_xiaoxiao",
            reference_audio_path="/path/to/ref.mp3",
            chapter_index=1,
            paragraph_index=0,
        )
        assert record.character_name == "narrator"
        assert record.voice_id == "zf_xiaoxiao"
        assert record.chapter_index == 1
        assert record.paragraph_index == 0

    def test_to_dict(self):
        """Test serialization to dict."""
        record = VoiceAnchorRecord(
            character_name="narrator",
            voice_id="zf_xiaoxiao",
            reference_audio_path="/path/to/ref.mp3",
            chapter_index=1,
            paragraph_index=0,
            similarity_threshold=0.85,
            embedding_model="wavlm_large",
            created_at="2024-01-01T00:00:00",
        )
        d = record.to_dict()
        assert d["character_name"] == "narrator"
        assert d["voice_id"] == "zf_xiaoxiao"
        assert d["similarity_threshold"] == 0.85


class TestVoiceAnchorManager:
    """Tests for VoiceAnchorManager."""

    def setup_method(self):
        """Setup test fixtures."""
        self.config = VoiceAnchorConfig(
            enabled=True,
            similarity_threshold=0.85,
            reference_audio_dir="/tmp/test_voice_anchors",
        )
        self.manager = VoiceAnchorManager(self.config)

    def teardown_method(self):
        """Clean up."""
        import shutil

        shutil.rmtree("/tmp/test_voice_anchors", ignore_errors=True)

    def test_register_character(self):
        """Test registering a character's first voice anchor."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name

        try:
            anchor = self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            assert anchor is not None
            assert anchor.character_name == "narrator"
            assert anchor.voice_id == "zf_xiaoxiao"
            assert anchor.chapter_index == 1
            assert self.manager.has_anchor("narrator")
        finally:
            Path(ref_path).unlink(missing_ok=True)

    def test_register_character_disabled(self):
        """Test registration when Voice Anchor is disabled."""
        config = VoiceAnchorConfig(enabled=False)
        manager = VoiceAnchorManager(config)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name

        try:
            anchor = manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            assert anchor is None
            assert not manager.has_anchor("narrator")
        finally:
            Path(ref_path).unlink(missing_ok=True)

    def test_get_anchor(self):
        """Test getting an existing anchor."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name

        try:
            self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            anchor = self.manager.get_anchor("narrator")
            assert anchor is not None
            assert anchor.character_name == "narrator"

            # Non-existent character
            assert self.manager.get_anchor("nonexistent") is None
        finally:
            Path(ref_path).unlink(missing_ok=True)

    def test_get_reference_audio(self):
        """Test getting reference audio path."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name

        try:
            self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            ref_audio = self.manager.get_reference_audio("narrator")
            assert ref_audio is not None
            assert Path(ref_audio).exists()

            # Non-existent character
            assert self.manager.get_reference_audio("nonexistent") is None
        finally:
            Path(ref_path).unlink(missing_ok=True)

    def test_inject_reference_audio(self):
        """Test injecting reference audio into prosody overrides."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name

        try:
            self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            # Inject into empty dict
            prosody = {}
            result = self.manager.inject_reference_audio("narrator", prosody)
            assert "reference_audio" in result
            # The manager copies the reference audio to its own directory
            assert result["reference_audio"] != ref_path
            assert Path(result["reference_audio"]).exists()

            # Inject into existing prosody
            prosody = {"rate": "1.2"}
            result = self.manager.inject_reference_audio("narrator", prosody)
            assert result["rate"] == "1.2"
            assert "reference_audio" in result

            # Non-existent character (no injection)
            prosody = {}
            result = self.manager.inject_reference_audio("nonexistent", prosody)
            assert "reference_audio" not in result
        finally:
            Path(ref_path).unlink(missing_ok=True)

    def test_check_drift_no_anchor(self):
        """Test drift check when no anchor exists."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            gen_path = f.name

        try:
            result = self.manager.check_drift("nonexistent", gen_path, chapter_index=2)
            assert result is None
        finally:
            Path(gen_path).unlink(missing_ok=True)

    def test_check_drift_disabled(self):
        """Test drift check when Voice Anchor is disabled."""
        config = VoiceAnchorConfig(enabled=False)
        manager = VoiceAnchorManager(config)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            gen_path = f.name

        try:
            manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            result = manager.check_drift("narrator", gen_path, chapter_index=2)
            assert result is None
        finally:
            Path(ref_path).unlink(missing_ok=True)
            Path(gen_path).unlink(missing_ok=True)

    def test_drift_alerts(self):
        """Test drift alert recording."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            gen_path = f.name

        try:
            self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            # Mock similarity metric to return drift
            mock_result = MagicMock()
            mock_result.is_same_speaker = False
            mock_result.similarity = 0.7
            mock_result.threshold = 0.85

            with patch.object(self.manager._similarity_metric, "compute", return_value=mock_result):
                result = self.manager.check_drift("narrator", gen_path, chapter_index=2)

                assert result is not None
                alerts = self.manager.get_drift_alerts(2)
                assert len(alerts) == 1
                assert alerts[0]["character_name"] == "narrator"
                assert alerts[0]["similarity"] == 0.7
        finally:
            Path(ref_path).unlink(missing_ok=True)
            Path(gen_path).unlink(missing_ok=True)

    def test_get_summary(self):
        """Test getting summary of all anchors and alerts."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name

        try:
            self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            summary = self.manager.get_summary()
            assert summary["enabled"] is True
            assert summary["total_anchors"] == 1
            assert "narrator" in summary["anchors"]
            assert summary["anchors"]["narrator"]["voice_id"] == "zf_xiaoxiao"
        finally:
            Path(ref_path).unlink(missing_ok=True)

    def test_check_drift_similarity_above_threshold(self):
        """Test drift check when similarity is above threshold (no alert)."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            gen_path = f.name

        try:
            self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            # Mock similarity metric to return high similarity (above threshold)
            mock_result = MagicMock()
            mock_result.is_same_speaker = True
            mock_result.similarity = 0.9
            mock_result.threshold = 0.85

            with patch.object(self.manager._similarity_metric, "compute", return_value=mock_result):
                result = self.manager.check_drift("narrator", gen_path, chapter_index=2)

                assert result is not None
                assert result.is_same_speaker is True
                # No alert should be recorded
                alerts = self.manager.get_drift_alerts(2)
                assert len(alerts) == 0
        finally:
            Path(ref_path).unlink(missing_ok=True)
            Path(gen_path).unlink(missing_ok=True)

    def test_check_drift_missing_reference_audio(self):
        """Test drift check when reference audio is missing."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            gen_path = f.name

        try:
            self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )
            # Get the actual reference audio path (the copied file in the anchor directory)
            anchor = self.manager.get_anchor("narrator")
            assert anchor is not None
            reference_audio_path = anchor.reference_audio_path
            # Now delete the reference audio file to simulate missing reference
            Path(reference_audio_path).unlink()

            result = self.manager.check_drift("narrator", gen_path, chapter_index=2)
            assert result is None
            # No exception should be raised
        finally:
            Path(ref_path).unlink(missing_ok=True)
            Path(gen_path).unlink(missing_ok=True)

    def test_check_drift_missing_generated_audio(self):
        """Test drift check when generated audio is missing."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name

        try:
            self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )
            # Use a non-existent generated audio path
            gen_path = "/non/existent/gen.mp3"

            result = self.manager.check_drift("narrator", gen_path, chapter_index=2)
            assert result is None
            # No exception should be raised
        finally:
            Path(ref_path).unlink(missing_ok=True)

    def test_check_drift_similarity_metric_exception(self):
        """Test drift check when similarity metric raises an exception."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            gen_path = f.name

        try:
            self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            # Mock similarity metric to raise an exception
            with patch.object(
                self.manager._similarity_metric,
                "compute",
                side_effect=Exception("Similarity computation failed"),
            ):
                result = self.manager.check_drift("narrator", gen_path, chapter_index=2)
                assert result is None
                # No exception should propagate
        finally:
            Path(ref_path).unlink(missing_ok=True)
            Path(gen_path).unlink(missing_ok=True)

    def test_record_drift_alert_limit(self):
        """Test that recording drift alerts respects the per-chapter limit."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            gen_path = f.name

        try:
            self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            # Set a low limit for testing
            original_limit = self.manager.config.max_drift_alerts_per_chapter
            self.manager.config.max_drift_alerts_per_chapter = 2

            # Mock similarity metric to always indicate drift
            mock_result = MagicMock()
            mock_result.is_same_speaker = False
            mock_result.similarity = 0.7
            mock_result.threshold = 0.85

            with patch.object(self.manager._similarity_metric, "compute", return_value=mock_result):
                # Trigger drift checks up to the limit + 1
                for i in range(4):  # 0, 1, 2, 3
                    self.manager.check_drift("narrator", gen_path, chapter_index=3)

                # Check that we have more than the limit number of alerts (since we append before checking)
                alerts = self.manager.get_drift_alerts(3)
                assert len(alerts) > original_limit  # We expect at least limit+1 alerts

            # Reset the limit
            self.manager.config.max_drift_alerts_per_cheroid = original_limit
        finally:
            Path(ref_path).unlink(missing_ok=True)
            Path(gen_path).unlink(missing_ok=True)

    def test_inject_reference_audio_none_prosody(self):
        """Test injecting reference audio when prosody_overrides is None."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            ref_path = f.name

        try:
            self.manager.register_character(
                character_name="narrator",
                voice_id="zf_xiaoxiao",
                reference_audio_path=ref_path,
                chapter_index=1,
                paragraph_index=0,
            )

            # Inject into None
            result = self.manager.inject_reference_audio("narrator", None)
            assert "reference_audio" in result
            assert result["reference_audio"] is not None
            assert Path(result["reference_audio"]).exists()
        finally:
            Path(ref_path).unlink(missing_ok=True)


class TestGlobalManager:
    """Tests for global manager functions."""

    def setup_method(self):
        reset_voice_anchor_manager()

    def teardown_method(self):
        reset_voice_anchor_manager()

    def test_get_voice_anchor_manager(self):
        """Test getting global manager instance."""
        manager = get_voice_anchor_manager()
        assert isinstance(manager, VoiceAnchorManager)

        # Second call returns same instance
        manager2 = get_voice_anchor_manager()
        assert manager is manager2

    def test_reset_voice_anchor_manager(self):
        """Test resetting global manager."""
        manager1 = get_voice_anchor_manager()
        reset_voice_anchor_manager()
        manager2 = get_voice_anchor_manager()
        assert manager1 is not manager2


class TestApplyVoiceAnchor:
    """Tests for the apply_voice_anchor function."""

    @pytest.mark.asyncio
    async def test_apply_voice_anchor_disabled(self):
        """Test that when Voice Anchor is disabled, inputs unchanged."""
        manager = MagicMock()
        manager.config.enabled = False

        inputs = [MagicMock()]
        voice_map = [MagicMock()]

        result = await apply_voice_anchor(manager, inputs, voice_map)
        # Should return the same input objects (identity)
        assert result is inputs

    @pytest.mark.asyncio
    async def test_apply_voice_anchor_no_anchor(self):
        """Test applying that when character has no anchor, input is returned unchanged."""
        manager = MagicMock()
        manager.config.enabled = True
        manager.has_anchor.return_value = False

        input_mock = MagicMock()
        input_mock.paragraph_annotation.speaker_canonical_name = "narrator"
        input_mock.paragraph_annotation.voice_anchor_ref = None  # Initially None

        inputs = [input_mock]
        voice_map = [MagicMock()]  # Not used in this branch

        result = await apply_voice_anchor(manager, inputs, voice_map)
        # The input should be returned unchanged (same object)
        assert result[0] is input_mock
        assert input_mock.paragraph_annotation.voice_anchor_ref is None

    @pytest.mark.asyncio
    async def test_apply_voice_anchor_with_anchor(self):
        """Test applying that when character has an anchor, the reference audio is injected."""
        manager = MagicMock()
        manager.config.enabled = True
        manager.has_anchor.return_value = True
        manager.get_reference_audio.return_value = "/path/to/ref.mp3"

        input_mock = MagicMock()
        input_mock.paragraph_annotation.speaker_canonical_name = "narrator"
        input_mock.paragraph_annotation.voice_anchor_ref = None  # Initially None

        inputs = [input_mock]
        voice_map = [MagicMock()]  # Not used in this branch

        result = await apply_voice_anchor(manager, inputs, voice_map)
        # The input should be modified in place (same object)
        assert result[0] is input_mock
        assert input_mock.paragraph_annotation.voice_anchor_ref == "/path/to/ref.mp3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
