"""Unit tests for the publish-job state machine model (S3-1)."""

from src.audiobook_studio.models.publish_job import PublishJobState, PublishJobStatus


def _job() -> PublishJobState:
    return PublishJobState(job_id="publish_1_abc", project_id=1, target="audiobookshelf")


def test_initial_state_is_pending():
    job = _job()
    assert job.status == PublishJobStatus.PENDING.value
    assert job.retry_count == 0
    assert job.progress == 0.0
    assert job.error_log is None


def test_mark_processing_transitions_and_sets_started_at():
    job = _job()
    job.mark_processing()
    assert job.status == PublishJobStatus.PROCESSING.value
    assert job.started_at is not None
    job.mark_processing()
    assert job.status == PublishJobStatus.PROCESSING.value


def test_mark_success_sets_terminal_state():
    job = _job()
    job.mark_success({"rss_url": "http://x/rss"})
    assert job.status == PublishJobStatus.SUCCESS.value
    assert job.progress == 1.0
    assert job.finished_at is not None
    assert job.result_json is not None


def test_mark_failure_appends_error_log():
    job = _job()
    job.mark_failure("boom")
    assert job.status == PublishJobStatus.FAILED.value
    assert job.finished_at is not None
    assert "boom" in (job.error_log or "")


def test_register_retry_bumps_count_and_appends_error():
    job = _job()
    job.register_retry("attempt 1 exploded")
    assert job.retry_count == 1
    assert job.status == PublishJobStatus.PROCESSING.value
    assert "attempt 1 exploded" in (job.error_log or "")
    job.register_retry("attempt 2 exploded")
    assert job.retry_count == 2
    assert "attempt 1 exploded" in job.error_log
    assert "attempt 2 exploded" in job.error_log


def test_error_log_is_bounded():
    job = _job()
    for i in range(50):
        job.register_retry(f"err {i}")
    lines = job.error_log.splitlines()
    assert len(lines) <= 20


def test_to_dict_roundtrip():
    job = _job()
    job.mark_success({"rss_url": "http://x/rss", "episode_count": 5})
    data = job.to_dict()
    assert data["status"] == PublishJobStatus.SUCCESS.value
    assert data["result"]["rss_url"] == "http://x/rss"
    assert data["result"]["episode_count"] == 5
    assert data["retry_count"] == 0
    assert data["target"] == "audiobookshelf"
    assert data["created_at"] is None or isinstance(data["created_at"], str)


def test_classmethods():
    assert PublishJobStatus.is_terminal(PublishJobStatus.SUCCESS.value)
    assert PublishJobStatus.is_terminal(PublishJobStatus.FAILED.value)
    assert not PublishJobStatus.is_terminal(PublishJobStatus.PENDING.value)
    assert PublishJobStatus.is_active(PublishJobStatus.PROCESSING.value)
    assert not PublishJobStatus.is_active(PublishJobStatus.FAILED.value)
