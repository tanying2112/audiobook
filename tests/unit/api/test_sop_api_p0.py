"""P0 tests for api/sop_reflection.py — REST endpoints & WebSocket loop.

Covers: correction submission (accepted/queue_full), rules lookup, manual
reflection trigger (404 / below-threshold / applied), background thread
status/start/stop, import rule application, config snapshot, queue size,
and the WebSocket message protocol (correction/ping/unknown/disconnect/error).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.api.sop_reflection import (
    ApplyRulesOnImportRequest,
    CorrectionRequest,
    apply_rules_on_import,
    get_background_status,
    get_config_snapshot,
    get_genre_rules,
    get_queue_size,
    list_genres,
    start_background_thread,
    stop_background_thread,
    submit_correction,
    trigger_reflection,
)

MODULE_API = "src.audiobook_studio.api.sop_reflection"
MODULE_CORE = "src.audiobook_studio.pipeline.sop_reflection"


def make_correction(**over):
    data = dict(
        project_id=1,
        chapter_index=1,
        paragraph_index=2,
        field="emotion",
        original_value="neutral",
        corrected_value="tense",
        genre="玄幻",
        context={"speaker": "旁白"},
    )
    data.update(over)
    return CorrectionRequest(**data)


class TestSubmitCorrection:
    @pytest.mark.asyncio
    async def test_accepted_and_genre_cached(self):
        collector = MagicMock()
        collector.add_correction_dict.return_value = True
        collector.queue_size.return_value = 3
        with patch(f"{MODULE_API}.get_correction_collector", return_value=collector):
            resp = await submit_correction(make_correction())
        assert resp.status == "accepted"
        assert resp.queued_count == 3
        collector.cache_project_genre.assert_called_once_with(1, "玄幻")

    @pytest.mark.asyncio
    async def test_queue_full_reported(self):
        collector = MagicMock()
        collector.add_correction_dict.return_value = False
        collector.queue_size.return_value = 99
        with patch(f"{MODULE_API}.get_correction_collector", return_value=collector):
            resp = await submit_correction(make_correction())
        assert resp.status == "queue_full"


class TestRulesAndGenres:
    @pytest.mark.asyncio
    async def test_get_genre_rules_with_stats(self):
        cfg = MagicMock()
        cfg.get_genre_rules.return_value = {"emotion_defaults": {"x": "y"}}
        cfg.get_genre_config.return_value = {"learning_stats": {"confidence": 0.8}}
        with patch(f"{MODULE_API}.get_sop_config", return_value=cfg):
            resp = await get_genre_rules("玄幻")
        assert resp.rules_applied is True
        assert resp.confidence == 0.8

    @pytest.mark.asyncio
    async def test_get_genre_rules_unknown_defaults_confidence(self):
        cfg = MagicMock()
        cfg.get_genre_rules.return_value = {}
        cfg.get_genre_config.return_value = {}  # no learning_stats key
        with patch(f"{MODULE_API}.get_sop_config", return_value=cfg):
            resp = await get_genre_rules("未知")
        assert resp.rules_applied is False
        assert resp.confidence == 0.5

    @pytest.mark.asyncio
    async def test_list_genres(self):
        cfg = MagicMock()
        cfg.list_genres.return_value = ["default", "玄幻"]
        with patch(f"{MODULE_API}.get_sop_config", return_value=cfg):
            assert await list_genres() == ["default", "玄幻"]


class TestTriggerReflection:
    @pytest.mark.asyncio
    async def test_404_when_no_corrections_for_genre(self):
        collector = MagicMock()
        collector.get_corrections_by_genre.return_value = []
        with (
            patch(f"{MODULE_API}.get_correction_collector", return_value=collector),
            patch(f"{MODULE_API}.get_reflection_engine"),
        ):
            with pytest.raises(Exception) as ei:
                await trigger_reflection("科幻")
        # DomainError has 'message' attribute instead of 'detail'
        assert "No corrections found" in str(ei.value.message)

    @pytest.mark.asyncio
    async def test_below_threshold_no_update(self):
        from src.audiobook_studio.pipeline.sop_reflection import ReflectionResult

        collector = MagicMock()
        corrections = [MagicMock(), MagicMock()]
        collector.get_corrections_by_genre.return_value = corrections
        engine = MagicMock()
        engine.reflect.return_value = ReflectionResult(
            genre="玄幻", proposed_rules={"a": 1}, confidence=0.2,
            reasoning="weak", corrections_analyzed=2, timestamp="now",
        )
        cfg = MagicMock()
        cfg.get_confidence_threshold.return_value = 0.65
        with (
            patch(f"{MODULE_API}.get_correction_collector", return_value=collector),
            patch(f"{MODULE_API}.get_reflection_engine", return_value=engine),
            patch(f"{MODULE_API}.get_sop_config", return_value=cfg),
        ):
            resp = await trigger_reflection("玄幻")
        assert resp.rules_updated is False
        cfg.update_genre_rules.assert_not_called()

    @pytest.mark.asyncio
    async def test_high_confidence_updates_rules_and_counts(self):
        from src.audiobook_studio.pipeline.sop_reflection import ReflectionResult

        collector = MagicMock()
        collector.get_corrections_by_genre.return_value = [MagicMock() for _ in range(4)]
        engine = MagicMock()
        engine.reflect.return_value = ReflectionResult(
            genre="玄幻", proposed_rules={"emotion_defaults": {"战斗": "intense"}},
            confidence=0.9, reasoning="strong", corrections_analyzed=4, timestamp="now",
        )
        cfg = MagicMock()
        cfg.get_confidence_threshold.return_value = 0.65
        cfg.update_genre_rules.return_value = True
        with (
            patch(f"{MODULE_API}.get_correction_collector", return_value=collector),
            patch(f"{MODULE_API}.get_reflection_engine", return_value=engine),
            patch(f"{MODULE_API}.get_sop_config", return_value=cfg),
        ):
            resp = await trigger_reflection("玄幻", max_corrections=10)
        assert resp.rules_updated is True
        assert cfg.update_genre_rules.call_count == 1
        assert cfg.record_correction.call_count == 4

    @pytest.mark.asyncio
    async def test_empty_proposed_rules_skip_update_even_if_confident(self):
        from src.audiobook_studio.pipeline.sop_reflection import ReflectionResult

        collector = MagicMock()
        collector.get_corrections_by_genre.return_value = [MagicMock()]
        engine = MagicMock()
        engine.reflect.return_value = ReflectionResult(
            genre="玄幻", proposed_rules={}, confidence=0.99,
            reasoning="", corrections_analyzed=1, timestamp="now",
        )
        cfg = MagicMock()
        cfg.get_confidence_threshold.return_value = 0.65
        with (
            patch(f"{MODULE_API}.get_correction_collector", return_value=collector),
            patch(f"{MODULE_API}.get_reflection_engine", return_value=engine),
            patch(f"{MODULE_API}.get_sop_config", return_value=cfg),
        ):
            resp = await trigger_reflection("玄幻")
        assert resp.rules_updated is False


class TestBackgroundThreadEndpoints:
    @pytest.mark.asyncio
    async def test_status_not_running(self):
        with patch(f"{MODULE_CORE}._background_thread", None):
            resp = await get_background_status()
        assert resp.running is False

    @pytest.mark.asyncio
    async def test_status_running_reports_interval(self):
        fake = MagicMock()
        fake.check_interval = 12.5
        fake._last_reflection = {"玄幻": "2026-08-26T10:00:00Z"}
        # MagicMock()._thread.is_alive() returns a truthy MagicMock → running branch
        with patch(f"{MODULE_CORE}._background_thread", fake):
            resp = await get_background_status()
        assert resp.running is True
        assert resp.check_interval == 12.5
        assert resp.last_reflections == {"玄幻": "2026-08-26T10:00:00Z"}

    @pytest.mark.asyncio
    async def test_start_endpoint(self):
        fake_thread = MagicMock(check_interval=5.0)
        with patch(f"{MODULE_API}.start_sop_background_thread", return_value=fake_thread) as st:
            resp = await start_background_thread(check_interval=5.0)
        st.assert_called_once_with(check_interval=5.0)
        assert resp == {"status": "started", "check_interval": 5.0}

    @pytest.mark.asyncio
    async def test_stop_endpoint(self):
        with patch(f"{MODULE_API}.stop_sop_background_thread") as sp:
            resp = await stop_background_thread()
        sp.assert_called_once()
        assert resp == {"status": "stopped"}


class TestImportAndDiagnostics:
    @pytest.mark.asyncio
    async def test_apply_rules_on_import(self):
        payload = ApplyRulesOnImportRequest(
            project_id=1,
            book_meta={"title": "t", "author": "a", "genre": "小说", "difficulty": "B",
                       "language": "zh", "total_chapters_estimated": 3},
            analyzed_json={"scene_tags": ["宗门"]},
        )
        with patch(f"{MODULE_API}.apply_learned_rules_on_import") as fn:
            fn.return_value = {"genre": "玄幻", "rules_applied": True,
                               "confidence": 0.7, "rules": {"a": 1}}
            resp = await apply_rules_on_import(payload)
        assert resp.genre == "玄幻"
        assert resp.rules_applied is True

    @pytest.mark.asyncio
    async def test_config_snapshot(self):
        cfg = MagicMock()
        cfg.get_config_snapshot.return_value = {"version": "1.0"}
        with patch(f"{MODULE_API}.get_sop_config", return_value=cfg):
            assert await get_config_snapshot() == {"version": "1.0"}

    @pytest.mark.asyncio
    async def test_queue_size(self):
        collector = MagicMock()
        collector.queue_size.return_value = 7
        with patch(f"{MODULE_API}.get_correction_collector", return_value=collector):
            assert await get_queue_size() == {"queue_size": 7}


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket protocol — exercised via a fake socket
# ─────────────────────────────────────────────────────────────────────────────


class FakeWebSocket:
    def __init__(self, incoming, fail_send=False):
        self.incoming = list(incoming)
        self.sent = []
        self.accepted = False
        self._fail_send = fail_send

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        if not self.incoming:
            from fastapi import WebSocketDisconnect

            raise WebSocketDisconnect()
        return self.incoming.pop(0)

    async def send_text(self, text):
        if self._fail_send:
            raise RuntimeError("socket gone")
        self.sent.append(json.loads(text))


class TestSopCorrectionsWebsocket:
    async def run_ws(self, incoming, project_id=1, **kw):
        from src.audiobook_studio.api.sop_reflection import sop_corrections_websocket

        ws = FakeWebSocket(incoming, **kw)
        collector = MagicMock()
        collector.add_correction_dict.return_value = True
        collector.queue_size.return_value = 1
        with patch(f"{MODULE_API}.get_correction_collector", return_value=collector):
            await sop_corrections_websocket(ws, project_id)
        return ws

    @pytest.mark.asyncio
    async def test_accept_ack_ping_unknown_disconnect(self):
        msg = {
            "type": "correction", "chapter_index": 1, "paragraph_index": 1,
            "field": "emotion", "original_value": "n", "corrected_value": "t",
            "genre": "悬疑",
        }
        ws = await self.run_ws([json.dumps(msg), json.dumps({"type": "ping"}),
                                json.dumps({"type": "mystery"}), "not-json-at-all"])
        types = [m["type"] for m in ws.sent]
        assert ws.accepted is True
        assert types[0] == "ack"
        assert ws.sent[0]["status"] == "accepted"
        assert "pong" in types
        assert "error" in types  # unknown type AND invalid json both produce error frames

    @pytest.mark.asyncio
    async def test_generic_error_path_attempts_error_frame(self):
        msg = {
            "type": "correction", "project_id": 5, "chapter_index": 1,
            "paragraph_index": 1, "field": "emotion",
            "original_value": {},  # unhashable weirdness downstream? keep simple: valid
            "corrected_value": "t", "genre": "悬疑",
        }
        # Force handler failure by making handle_user_correction_websocket raise
        ws = FakeWebSocket([json.dumps(msg)])
        with patch(f"{MODULE_API}.get_correction_collector", return_value=MagicMock()), \
             patch(f"{MODULE_API}.handle_user_correction_websocket", side_effect=RuntimeError("boom")):
            from src.audiobook_studio.api.sop_reflection import sop_corrections_websocket

            await sop_corrections_websocket(ws, 1)
        assert ws.sent[-1] == {"type": "error", "message": "boom"}

    @pytest.mark.asyncio
    async def test_error_frame_suppressed_when_socket_dead(self):
        msg = {
            "type": "correction", "project_id": 5, "chapter_index": 1,
            "paragraph_index": 1, "field": "emotion",
            "original_value": "n", "corrected_value": "t", "genre": "悬疑",
        }
        ws = FakeWebSocket([json.dumps(msg)], fail_send=True)
        with patch(f"{MODULE_API}.get_correction_collector", return_value=MagicMock()), \
             patch(f"{MODULE_API}.handle_user_correction_websocket", side_effect=RuntimeError("boom")):
            from src.audiobook_studio.api.sop_reflection import sop_corrections_websocket

            await sop_corrections_websocket(ws, 5)  # RuntimeError on send swallowed
