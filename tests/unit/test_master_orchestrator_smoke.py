from unittest import mock

import numpy as np
import pytest

import master.orchestrator as M
from master.orchestrator import AudiobookOrchestrator, ChunkStrategy, R2Uploader, SemanticChunker


@pytest.fixture
def orch(monkeypatch):
    monkeypatch.setattr(M, "boto3", mock.MagicMock())
    monkeypatch.setattr(M.redis, "Redis", lambda *a, **k: mock.MagicMock())
    state = mock.MagicMock()
    state.create_task.return_value = mock.MagicMock()
    monkeypatch.setattr(M, "HermesStateStore", lambda *a, **k: state)
    o = AudiobookOrchestrator("h", 6379, "auth", "ep", "ak", "sk", "bucket")
    o.state_store = state
    return o


def test_semantic_chunker():
    c = SemanticChunker(max_chars=20, min_chars=5)
    assert c.chunk("") == []
    assert c.chunk("   ") == []
    out = c.chunk("第一章。第二章很长很长很长很长很长很长很长很长很长很长很长很长。第三章。")
    assert out
    for o in out:
        assert len(o) <= 20


def test_r2_uploader(monkeypatch):
    s3 = mock.MagicMock()
    monkeypatch.setattr(M, "boto3", mock.MagicMock())
    M.boto3.client.return_value = s3
    u = R2Uploader("ep", "ak", "sk", "bucket", "https://pub", verify_ssl=False)
    assert u.upload_bytes(b"data", "k.wav") == "https://pub/k.wav"
    s3.put_object.assert_called_once()
    assert u.upload_file("/tmp/x.wav", "k2.wav") == "https://pub/k2.wav"
    s3.upload_file.assert_called_once()
    s3.get_object.return_value = {"Body": mock.MagicMock(read=lambda: b"bytes")}
    assert u.download_bytes("k3") == b"bytes"


def test_chunk_chapter_and_submit(orch):
    chapters = [{"text": "第一章。第二章。第三章。"}, {"text": ""}]
    task = orch.submit_audiobook("book1", "Title", "Author", chapters, "voice1", {"speed": 1.0})
    assert task.book_id == "book1"
    prog = orch.get_progress("book1")
    assert prog is not None and prog.total_chunks >= 1
    assert orch.state_store.create_task.call_count == prog.total_chunks


def test_submit_fixed_strategy(orch):
    orch.submit_audiobook(
        "b2", "T", "A", [{"text": "abcdefghij"}], "v", {}, chunk_strategy=ChunkStrategy.FIXED, max_chunk_chars=3
    )
    assert orch.get_progress("b2").total_chunks == 4


def test_handle_chunk_result_completed(orch):
    orch.submit_audiobook("b3", "T", "A", [{"text": "一。二。"}], "v", {})
    orch._handle_chunk_result(
        {
            "task_id": "t1",
            "chunk_id": "b3-ch0-ck0",
            "book_id": "b3",
            "chunk_index": 0,
            "status": "completed",
            "audio_url": "https://pub/chunk0.wav",
        }
    )
    prog = orch.get_progress("b3")
    assert prog.completed_chunks == 1
    assert prog.chunk_urls[0] == "https://pub/chunk0.wav"


def test_handle_chunk_result_failed(orch):
    orch.submit_audiobook("b4", "T", "A", [{"text": "一。"}], "v", {})
    orch._handle_chunk_result(
        {
            "task_id": "t2",
            "chunk_id": "b4-ch0-ck0",
            "book_id": "b4",
            "chunk_index": 0,
            "status": "failed",
            "error": "boom",
        }
    )
    assert orch.get_progress("b4").failed_chunks == 1


def test_handle_chunk_result_incomplete(orch):
    # missing fields -> no-op
    orch._handle_chunk_result({"task_id": "x"})
    orch._handle_chunk_result({})


def test_finalize_audiobook(monkeypatch, orch):
    import soundfile as sf

    monkeypatch.setattr(sf, "read", lambda *a, **k: (np.array([0.0, 0.0]), 16000))
    monkeypatch.setattr(sf, "write", lambda *a, **k: None)
    orch.submit_audiobook("b5", "T", "A", [{"text": "一。二。"}], "v", {})
    orch._update_progress("b5", completed_chunks=2)
    orch._update_progress("b5", chunk_urls={0: "https://pub/a.wav", 1: "https://pub/b.wav"})
    orch.r2.public_url_base = "https://pub"
    monkeypatch.setattr(orch.r2, "download_bytes", lambda key: b"wavbytes")
    monkeypatch.setattr(orch.r2, "upload_bytes", lambda data, key, content_type="audio/wav": "https://pub/final.wav")
    orch._finalize_audiobook("b5")
    assert orch.get_progress("b5").status == "COMPLETED"
    assert "final.wav" in orch.get_progress("b5").final_url


def test_finalize_no_chunks(monkeypatch, orch):
    orch.submit_audiobook("b6", "T", "A", [{"text": "一。"}], "v", {})
    orch._update_progress("b6", completed_chunks=1)
    orch._update_progress("b6", chunk_urls={})
    orch._finalize_audiobook("b6")
    assert orch.get_progress("b6").status == "FAILED"


def test_listener_lifecycle(orch):
    orch.start_result_listener()
    orch.stop_result_listener()


def test_cleanup_progress(orch):
    orch.submit_audiobook("b7", "T", "A", [{"text": "一。"}], "v", {})
    orch._update_progress("b7", status="COMPLETED", updated_at=0)
    orch._cleanup_progress(max_age=0)
    assert orch.get_progress("b7") is None


def test_main_missing_env(monkeypatch):
    for v in ["REDIS_HOST", "REDIS_AUTH", "R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(M, "AudiobookOrchestrator", mock.MagicMock())
    with pytest.raises(SystemExit):
        M.main()


def test_main_runs(monkeypatch):
    for k, v in {
        "REDIS_HOST": "h",
        "REDIS_AUTH": "a",
        "R2_ENDPOINT": "e",
        "R2_ACCESS_KEY_ID": "ak",
        "R2_SECRET_ACCESS_KEY": "sk",
        "R2_BUCKET": "b",
    }.items():
        monkeypatch.setenv(k, v)
    inst = mock.MagicMock()
    monkeypatch.setattr(M, "AudiobookOrchestrator", lambda **kw: inst)
    M.main()
    inst.run.assert_called_once()
