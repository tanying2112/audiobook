"""Tests for Golden Dataset API endpoints.

Covers:
- Golden sample listing (all stages, by stage, human_verified filter)
- Golden sample detail retrieval
- Contribution from FeedbackRecord
- Approval/rejection of contributions
- Regression testing
- Trend tracking
- Bootstrap few-shot optimization
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.audiobook_studio.api.dependencies import get_async_db as golden_get_async_db

# Import the API router and dependencies
from src.audiobook_studio.api.golden import router as golden_router

# Create test app
test_app = FastAPI()
test_app.include_router(golden_router)


@pytest.fixture
def client(golden_temp_dir):
    """FastAPI test client with mocked async database."""

    async def get_test_db():
        db = AsyncMock()
        # Mock execute/scalar_one_or_none for FeedbackRecord queries
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result
        yield db

    test_app.dependency_overrides[golden_get_async_db] = get_test_db
    with TestClient(test_app) as client:
        yield client
    test_app.dependency_overrides.clear()


@pytest.fixture
def golden_temp_dir(tmp_path):
    """Create a temporary golden directory structure for testing."""
    golden_dir = tmp_path / "tests" / "golden"
    golden_dir.mkdir(parents=True)

    # Create stage directories with test data
    stages = {
        "extract": "extract",
        "analyze": "analyze_structure",
        "annotate": "annotate_paragraph",
        "edit": "edit_for_tts",
        "synthesize": "synthesize",
        "quality": "quality_check",
    }

    for stage_key, stage_dir in stages.items():
        stage_path = golden_dir / stage_dir
        stage_path.mkdir(parents=True)

        # Create few_shot.jsonl
        few_shot = stage_path / "few_shot.jsonl"
        few_shot.write_text(
            json.dumps({"input": {"text": "test"}, "output": {"result": "extracted"}})
            + "\n"
            + json.dumps({"input": {"text": "test2"}, "output": {"result": "extracted2"}})
            + "\n"
        )

        # Create case file
        case_file = stage_path / "case_001.json"
        case_file.write_text(
            json.dumps({"input": {"text": "case input"}, "expected_output": {"result": "case output"}})
        )

    # Create reports directory
    reports_dir = golden_dir / "reports"
    reports_dir.mkdir(parents=True)

    # Write a sample regression report
    sample_report = {
        "run_id": "regression_12345",
        "timestamp": "2024-01-01T00:00:00+00:00",
        "total_samples": 10,
        "passed_count": 8,
        "failed_count": 2,
        "pass_rate": 0.8,
        "by_stage": {"extract": {"passed": 3, "failed": 1}, "analyze": {"passed": 5, "failed": 1}},
        "results": [],
        "prompt_versions_tested": {"extract": "v1", "analyze": "v2"},
    }
    (reports_dir / "regression_12345.json").write_text(json.dumps(sample_report))

    with patch("src.audiobook_studio.api.golden.GOLDEN_DIR", golden_dir):
        yield golden_dir


def _make_feedback_record(fid=1):
    """Create a mock FeedbackRecord."""
    record = MagicMock()
    record.id = fid
    record.project_id = 1
    record.stage = "extract"
    record.feedback_id = f"test_feedback_{fid:03d}"
    record.source = "test"
    record.input_snapshot = {"text": "test input"}
    record.llm_output = {"result": "original output"}
    record.corrected_output = {"result": "test output"}
    record.rationale = "Test rationale"
    record.pattern_tags = ["test_pattern"]
    record.created_at = datetime.now(timezone.utc)
    return record


class TestGoldenSamplesListing:
    """Tests for listing golden samples."""

    def test_list_all_samples(self, client, golden_temp_dir):
        """Test listing all golden samples across all stages."""
        response = client.get("/golden/samples")
        assert response.status_code == 200
        data = response.json()
        assert "samples" in data
        assert "total_count" in data
        assert "by_stage" in data
        assert data["total_count"] > 0
        assert len(data["by_stage"]) > 0

    def test_list_samples_by_stage(self, client, golden_temp_dir):
        """Test listing golden samples for a specific stage."""
        response = client.get("/golden/samples?stage=extract")
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] > 0
        for sample in data["samples"]:
            assert sample["stage"] == "extract"

    def test_list_samples_human_verified_only(self, client, golden_temp_dir):
        """Test filtering for human-verified samples only."""
        response = client.get("/golden/samples?human_verified_only=true")
        assert response.status_code == 200
        data = response.json()
        # All returned samples should be human_verified
        for sample in data["samples"]:
            assert sample["human_verified"] is True


class TestGoldenSampleDetail:
    """Tests for getting a specific golden sample."""

    def test_get_existing_sample(self, client, golden_temp_dir):
        """Test retrieving an existing golden sample."""
        response = client.get("/golden/samples/extract/case_001")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "case_001"
        assert data["stage"] == "extract"
        assert "input" in data
        assert "expected_output" in data

    def test_get_nonexistent_sample(self, client, golden_temp_dir):
        """Test retrieving a non-existent sample returns 404."""
        response = client.get("/golden/samples/extract/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestGoldenContribution:
    """Tests for contributing to golden dataset."""

    @pytest.mark.asyncio
    async def test_contribute_from_feedback_record(self, client, golden_temp_dir):
        """Test contributing a template from FeedbackRecord to golden dataset."""
        # Mock the database to return a FeedbackRecord
        from src.audiobook_studio.api.golden import router

        # Get the test db from dependency override
        test_db = AsyncMock()
        mock_result = MagicMock()
        feedback = _make_feedback_record(1)
        mock_result.scalar_one_or_none.return_value = feedback
        test_db.execute.return_value = mock_result

        # Override the dependency for this test
        test_app.dependency_overrides[golden_get_async_db] = lambda: test_db

        try:
            response = client.post(
                "/golden/contribute",
                json={
                    "template_id": feedback.id,
                    "stage": "extract",
                    "quality_score": 0.9,
                    "notes": "Test contribution",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "contribution_id" in data
            assert data["status"] == "pending"
            assert str(feedback.id) in data["message"]
        finally:
            test_app.dependency_overrides.clear()
            # Re-apply the default override
            test_app.dependency_overrides[golden_get_async_db] = lambda: AsyncMock()

    @pytest.mark.asyncio
    async def test_contribute_nonexistent_feedback(self, client, golden_temp_dir):
        """Test contributing from non-existent FeedbackRecord returns 404."""
        # Mock the database to return None for non-existent record
        test_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        test_db.execute.return_value = mock_result

        test_app.dependency_overrides[golden_get_async_db] = lambda: test_db

        try:
            response = client.post(
                "/golden/contribute",
                json={
                    "template_id": 99999,
                    "stage": "extract",
                    "quality_score": 0.9,
                },
            )
            assert response.status_code == 404
            assert "not found" in response.json()["detail"]
        finally:
            test_app.dependency_overrides.clear()


class TestGoldenApproval:
    """Tests for approving/rejecting golden samples."""

    def test_approve_sample(self, client, golden_temp_dir):
        """Test approving a pending golden sample."""
        # Create a mock sample file for approval
        stage_dir = golden_temp_dir / "extract"
        sample_file = stage_dir / "contrib_extract_12345.json"
        sample_file.write_text(
            json.dumps(
                {
                    "input": {"text": "test"},
                    "output": {"result": "test"},
                    "human_verified": False,
                    "source": "contribution",
                }
            )
        )

        response = client.post("/golden/approve/contrib_extract_12345?stage=extract")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
        assert data["human_verified"] is True

        # Verify file was updated
        updated_data = json.loads(sample_file.read_text())
        assert updated_data["human_verified"] is True

    def test_reject_sample(self, client, golden_temp_dir):
        """Test rejecting a pending golden sample."""
        stage_dir = golden_temp_dir / "extract"
        sample_file = stage_dir / "contrib_extract_67890.json"
        sample_file.write_text(
            json.dumps(
                {
                    "input": {"text": "test"},
                    "output": {"result": "test"},
                    "human_verified": False,
                    "source": "contribution",
                }
            )
        )

        response = client.post("/golden/reject/contrib_extract_67890?stage=extract")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"

        # Original file should be moved to rejected subdirectory
        rejected_dir = stage_dir / "rejected"
        assert rejected_dir.exists()
        assert (rejected_dir / "contrib_extract_67890.json").exists()
        assert not sample_file.exists()


class TestGoldenRegression:
    """Tests for running golden dataset regression."""

    @patch("src.audiobook_studio.pipeline.orchestrator.run_stage")
    @pytest.mark.asyncio
    async def test_run_regression(self, mock_run_stage, client, golden_temp_dir):
        """Test running golden dataset regression test."""
        # Mock run_stage to return a result similar to expected
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"result": "extracted"}
        mock_run_stage.return_value = mock_result

        # Mock the database dependency
        test_db = AsyncMock()
        test_app.dependency_overrides[golden_get_async_db] = lambda: test_db

        try:
            response = client.post("/golden/run-regression", json={"stages": ["extract"], "prompt_versions": {}})

            assert response.status_code == 200
            data = response.json()
            assert "run_id" in data
            assert "total_samples" in data
            assert "passed_count" in data
            assert "pass_rate" in data
            assert "by_stage" in data
            assert "results" in data
        finally:
            test_app.dependency_overrides.clear()

    @patch("src.audiobook_studio.pipeline.orchestrator.run_stage")
    @pytest.mark.asyncio
    async def test_run_regression_empty_stages(self, mock_run_stage, client, golden_temp_dir):
        """Test running regression with no stages specified (should test all)."""
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"result": "extracted"}
        mock_run_stage.return_value = mock_result

        test_db = AsyncMock()
        test_app.dependency_overrides[golden_get_async_db] = lambda: test_db

        try:
            response = client.post("/golden/run-regression", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["total_samples"] > 0
        finally:
            test_app.dependency_overrides.clear()


class TestGoldenTrend:
    """Tests for getting golden dataset trend."""

    def test_get_trend(self, client, golden_temp_dir):
        """Test retrieving historical trend data."""
        response = client.get("/golden/trend?days=30")
        assert response.status_code == 200
        data = response.json()
        assert "trend" in data
        assert "current_pass_rate" in data
        assert "historical_best" in data

    def test_get_trend_by_stage(self, client, golden_temp_dir):
        """Test retrieving trend filtered by stage."""
        response = client.get("/golden/trend?days=30&stage=extract")
        assert response.status_code == 200
        data = response.json()
        assert "trend" in data


class TestBootstrapFewshot:
    """Tests for bootstrap few-shot endpoint."""

    def test_bootstrap_fewshot(self, client, golden_temp_dir):
        """Test triggering few-shot optimization."""
        response = client.post(
            "/golden/bootstrap-fewshot",
            params={"stage": "extract", "max_samples": 5, "optimization_target": "diversity"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["stage"] == "extract"
        assert data["max_samples"] == 5
        assert data["optimization_target"] == "diversity"


class TestGoldenEdgeCases:
    """Edge case tests for golden API."""

    def test_list_samples_nonexistent_stage(self, client, golden_temp_dir):
        """Test listing samples for non-existent stage returns empty."""
        response = client.get("/golden/samples?stage=nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0

    def test_get_sample_wrong_stage(self, client, golden_temp_dir):
        """Test getting sample from wrong stage returns 404."""
        response = client.get("/golden/samples/analyze/nonexistent_sample_id")
        assert response.status_code == 404

    def test_approve_nonexistent_sample(self, client, golden_temp_dir):
        """Test approving non-existent sample returns 404."""
        response = client.post("/golden/approve/nonexistent?stage=extract")
        assert response.status_code == 404

    def test_reject_nonexistent_sample(self, client, golden_temp_dir):
        """Test rejecting non-existent sample returns 404."""
        response = client.post("/golden/reject/nonexistent?stage=extract")
        assert response.status_code == 404


class TestGoldenSimilarity:
    """Tests for the similarity computation function."""

    def test_compute_output_similarity_exact_match(self):
        """Test similarity with exact match."""
        from src.audiobook_studio.api.golden import _compute_output_similarity

        actual = {"key1": "value1", "key2": 100}
        expected = {"key1": "value1", "key2": 100}
        assert _compute_output_similarity(actual, expected) == 1.0

    def test_compute_output_similarity_partial_match(self):
        """Test similarity with partial match."""
        from src.audiobook_studio.api.golden import _compute_output_similarity

        actual = {"key1": "value1", "key2": 100}
        expected = {"key1": "different", "key2": 100}
        sim = _compute_output_similarity(actual, expected)
        assert 0.0 < sim < 1.0

    def test_compute_output_similarity_no_match(self):
        """Test similarity with no match."""
        from src.audiobook_studio.api.golden import _compute_output_similarity

        actual = {"key1": "value1"}
        expected = {"key2": "value2"}
        sim = _compute_output_similarity(actual, expected)
        assert sim < 0.5

    def test_compute_output_similarity_empty(self):
        """Test similarity with empty dicts."""
        from src.audiobook_studio.api.golden import _compute_output_similarity

        # Current implementation returns 0.0 for empty dicts (edge case)
        assert _compute_output_similarity({}, {}) == 0.0
        assert _compute_output_similarity({"a": 1}, {}) == 0.0
        assert _compute_output_similarity({}, {"a": 1}) == 0.0

    def test_compute_output_similarity_numeric_tolerance(self):
        """Test similarity with numeric values within tolerance."""
        from src.audiobook_studio.api.golden import _compute_output_similarity

        actual = {"score": 0.95}
        expected = {"score": 0.96}  # Within 10%
        sim = _compute_output_similarity(actual, expected)
        assert sim >= 0.9


class TestGoldenLoadSave:
    """Tests for internal load/save functions."""

    def test_load_golden_samples(self, golden_temp_dir):
        """Test loading golden samples from disk."""
        from src.audiobook_studio.api.golden import _load_golden_samples

        samples = _load_golden_samples("extract")
        assert len(samples) >= 2  # few_shot + case file
        assert all("id" in s for s in samples)
        assert all("input" in s for s in samples)
        assert all("expected_output" in s for s in samples)

    def test_save_golden_sample(self, golden_temp_dir):
        """Test saving a golden sample."""
        from src.audiobook_studio.api.golden import _save_golden_sample

        sample_id = _save_golden_sample(
            "extract",
            {
                "input": {"text": "new"},
                "output": {"result": "new"},
                "quality_score": 0.8,
                "notes": "test note",
                "pattern_tags": ["tag1"],
            },
        )
        assert sample_id.startswith("contrib_extract_")

        # Verify file was created
        stage_dir = golden_temp_dir / "extract"
        saved_file = stage_dir / f"{sample_id}.json"
        assert saved_file.exists()

        data = json.loads(saved_file.read_text())
        assert data["input"]["text"] == "new"
        assert data["human_verified"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
