"""Tests for pipeline/feedback_collector.py — StageCapture-based file-level feedback collection."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.audiobook_studio.pipeline.feedback_collector import FeedbackCollector, StageCapture, create_feedback_collector


class TestFeedbackCollector:
    """Tests for FeedbackCollector class."""

    def setup_method(self):
        """Setup temp dir for feedback storage."""
        self.tmpdir = tempfile.mkdtemp()
        self.project_id = 9999

        patcher = patch("src.audiobook_studio.pipeline.feedback_collector.project_dir")
        self.mock_pd = patcher.start()
        mock_fb_dir = Path(self.tmpdir) / "feedback" / "raw"
        mock_fb_dir.mkdir(parents=True, exist_ok=True)
        self.mock_pd.return_value = Path(self.tmpdir)
        self.collector = FeedbackCollector(project_id=self.project_id, enable=True)

    def teardown_method(self):
        """Cleanup patches."""
        patch.stopall()

    def test_init_disabled(self):
        """FeedbackCollector with enable=False."""
        collector = FeedbackCollector(project_id=1, enable=False)
        assert collector.enable is False

    def test_capture_stage_disabled_returns_disabled(self):
        """capture_stage returns disabled StageCapture when enable=False."""
        collector = FeedbackCollector(project_id=1, enable=False)
        capture = collector.capture_stage("annotate")
        assert capture._disabled is True

    def test_capture_stage_enabled(self):
        """capture_stage returns active StageCapture when enabled."""
        capture = self.collector.capture_stage("annotate", chapter_index=1, paragraph_index=5)
        assert capture._disabled is False
        assert capture.stage == "annotate"
        assert capture.chapter_index == 1
        assert capture.paragraph_index == 5

    def test_capture_stage_all_fields(self):
        """capture_stage with chapter_id, paragraph_id, input_snapshot."""
        snap = {"text": "hello"}
        capture = self.collector.capture_stage(
            "quality_judge",
            chapter_index=2,
            paragraph_index=3,
            chapter_id=10,
            paragraph_id=20,
            input_snapshot=snap,
        )
        assert capture.stage == "quality_judge"
        assert capture.chapter_id == 10
        assert capture.paragraph_id == 20
        assert capture.input_snapshot == snap

    def test_save_feedback_disabled(self):
        """save_feedback returns /dev/null for disabled collector."""
        collector = FeedbackCollector(project_id=1, enable=False)
        capture = StageCapture._disabled()
        result = collector.save_feedback(capture)
        assert str(result) == "/dev/null"

    def test_save_feedback_minimal(self):
        """save_feedback with minimal required fields."""
        capture = self.collector.capture_stage("annotate", chapter_index=1, paragraph_index=1)
        capture.set_llm_output({"r": "test"})
        capture.set_corrected_output({"r": "fixed"})
        capture.set_rationale("Valid rationale for a correction")

        fp = self.collector.save_feedback(capture)
        assert fp.exists()
        c = json.loads(fp.read_text())
        assert c["stage"] == "annotate"
        assert c["rationale"] == "Valid rationale for a correction"

    def test_save_feedback_all_fields(self):
        """save_feedback with all optional fields populated."""
        capture = self.collector.capture_stage(
            "synthesize",
            chapter_index=3,
            paragraph_index=7,
            chapter_id=30,
            paragraph_id=70,
        )
        capture.set_llm_output({"audio": "s1.wav"})
        capture.set_corrected_output({"audio": "s1_fixed.wav"})
        capture.set_rationale("Fixed pronunciation of a proper noun")
        capture.set_diff_summary("Pronunciation fix")
        capture.set_pattern_tags(["pron", "noun"])
        capture.set_source("quality_judge")
        capture.set_input_snapshot({"txt": "input"})

        fp = self.collector.save_feedback(capture)
        c = json.loads(fp.read_text())
        assert c["source"] == "quality_judge"
        assert c["chapter_id"] == 30
        assert c["diff_summary"] == "Pronunciation fix"
        assert c["pattern_tags"] == ["pron", "noun"]
        assert c["contract_version"] == 1

    def test_save_feedback_warns_empty_llm(self, caplog):
        """save_feedback warns when llm_output is empty."""
        capture = self.collector.capture_stage("annotate")
        capture.set_corrected_output({"r": "ok"})
        capture.set_rationale("Valid rationale for correction")
        self.collector.save_feedback(capture)
        assert "llm_output is empty" in caplog.text

    def test_save_feedback_warns_empty_corrected(self, caplog):
        """save_feedback warns when corrected_output is empty."""
        capture = self.collector.capture_stage("annotate")
        capture.set_llm_output({"r": "ok"})
        capture.set_rationale("Valid rationale for correction")
        self.collector.save_feedback(capture)
        assert "corrected_output is empty" in caplog.text

    def test_save_feedback_warns_short_rationale(self, caplog):
        """save_feedback warns when rationale is too short."""
        capture = self.collector.capture_stage("annotate")
        capture.set_llm_output({"r": "ok"})
        capture.set_corrected_output({"r": "ok"})
        capture.set_rationale("Short")
        self.collector.save_feedback(capture)
        assert "rationale too short" in caplog.text

    def test_load_feedback_found(self):
        """load_feedback retrieves saved record by feedback_id."""
        capture = self.collector.capture_stage("analyze", chapter_index=1)
        capture.set_llm_output({"a": "ok"})
        capture.set_corrected_output({"a": "better"})
        capture.set_rationale("Needs better analysis for this paragraph")
        self.collector.save_feedback(capture)

        loaded = self.collector.load_feedback(capture.feedback_id)
        assert loaded is not None
        assert loaded["llm_output"] == {"a": "ok"}

    def test_load_feedback_not_found(self):
        """load_feedback returns None for unknown ID."""
        assert self.collector.load_feedback("nonexistent") is None

    def test_list_feedback_all(self):
        """list_feedback returns all records."""
        for i in range(3):
            cap = self.collector.capture_stage("annotate", paragraph_index=i)
            cap.set_llm_output({"o": f"out_{i}"})
            cap.set_corrected_output({"o": f"corr_{i}"})
            cap.set_rationale(f"Rationale for correction {i}")
            self.collector.save_feedback(cap)

        assert len(self.collector.list_feedback()) == 3

    def test_list_feedback_filter_by_stage(self):
        """list_feedback filters by stage."""
        for stage in ["annotate", "annotate", "synthesize"]:
            cap = self.collector.capture_stage(stage)
            cap.set_llm_output({"o": "ok"})
            cap.set_corrected_output({"o": "ok"})
            cap.set_rationale("Valid rationale here ok")
            self.collector.save_feedback(cap)

        assert len(self.collector.list_feedback(stage="annotate")) == 2

    def test_list_feedback_filter_by_chapter(self):
        """list_feedback filters by chapter_index."""
        for ch in [1, 2, 2]:
            cap = self.collector.capture_stage("annotate", chapter_index=ch)
            cap.set_llm_output({"o": "ok"})
            cap.set_corrected_output({"o": "ok"})
            cap.set_rationale("Valid rationale here ok")
            self.collector.save_feedback(cap)

        assert len(self.collector.list_feedback(chapter_index=2)) == 2

    def test_list_feedback_empty(self):
        """list_feedback returns empty list with no records."""
        assert self.collector.list_feedback() == []


class TestStageCapture:
    """Tests for StageCapture."""

    def test_disabled_properties(self):
        """Disabled capture has correct defaults."""
        cap = StageCapture._disabled()
        assert cap._disabled is True
        assert cap.feedback_id == "disabled"
        assert cap.stage == "disabled"
        assert cap.project_id == 0

    def test_set_source_valid(self):
        """set_source accepts valid values."""
        cap = StageCapture._disabled()
        cap.set_source("human_edit")
        assert cap.source == "human_edit"
        cap.set_source("quality_judge")
        assert cap.source == "quality_judge"
        cap.set_source("user_rating")
        assert cap.source == "user_rating"

    def test_set_source_invalid_falls_back(self, caplog):
        """set_source with invalid value defaults to human_edit."""
        cap = StageCapture._disabled()
        cap.set_source("bad_source")
        assert "Unknown feedback source" in caplog.text
        assert cap.source == "human_edit"

    def test_set_input_snapshot(self):
        """set_input_snapshot updates the snapshot dict."""
        cap = StageCapture._disabled()
        cap.set_input_snapshot({"new": "data"})
        assert cap.input_snapshot == {"new": "data"}

    def test_set_diff_summary_and_tags(self):
        """set_diff_summary and set_pattern_tags work."""
        cap = StageCapture._disabled()
        cap.set_diff_summary("Summary")
        cap.set_pattern_tags(["t1", "t2"])
        assert cap.diff_summary == "Summary"
        assert cap.pattern_tags == ["t1", "t2"]


class TestCreateFeedbackCollector:
    """Tests for factory function."""

    def test_create_enabled(self):
        """create_feedback_collector with enable=True."""
        c = create_feedback_collector(project_id=42, enable=True)
        assert c.project_id == 42
        assert c.enable is True

    def test_create_disabled(self):
        """create_feedback_collector with enable=False."""
        c = create_feedback_collector(project_id=99, enable=False)
        assert c.project_id == 99
        assert c.enable is False
