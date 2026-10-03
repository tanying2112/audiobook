"""Manual Review Gate API tests — 人工终审门（合成前编辑与确认）.

Covers:
- Summary endpoint (chapter review_status + counts + all_approved)
- Chapter approve / reset / approve-all (review_status 的唯一写入口)
- Routing preview (与合成共用 build_routing_input + make_tts_routing_decision)
- Manual overrides (manual_engine / manual_voice_id 覆盖自动决策)
- Typed paragraph PATCH (编辑/标注/覆盖 + clear_* 开关 + 审计 + 打回待审)
- Error contract (404 / 409 / 400 / 422 extra=forbid)
"""

import asyncio

# Set ALLOWED_HOSTS BEFORE importing the main app to configure TrustedHostMiddleware correctly
import os
import tempfile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

os.environ["ALLOWED_HOSTS"] = '["localhost", "127.0.0.1", "testserver"]'

from src.audiobook_studio.api.auto_run import _active_runs
from src.audiobook_studio.api.dependencies import get_async_db
from src.audiobook_studio.auth.dependencies import get_current_user
from src.audiobook_studio.database import Base
from src.audiobook_studio.main import app
from src.audiobook_studio.models.book import Project
from src.audiobook_studio.models.chapter import Chapter
from src.audiobook_studio.models.paragraph import Paragraph
from src.audiobook_studio.models.user import User


# Clear _active_runs before each test to prevent state leakage
@pytest.fixture(autouse=True)
def clear_active_runs():
    _active_runs.clear()
    yield
    _active_runs.clear()


# =============================================================================
# Test fixtures (same isolation pattern as test_auto_run_api.py)
# =============================================================================


@pytest.fixture(scope="function")
def sync_engine():
    """Create a synchronous SQLite engine for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    engine = create_engine(f"sqlite:///{tmp.name}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(sync_engine):
    """Provide a SQLAlchemy session bound to the test engine."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
    session = SessionLocal()
    try:
        test_user = User(
            id=1,
            email="test@example.com",
            username="testuser",
            hashed_password="hashed",
            is_active=True,
            is_superuser=True,
        )
        session.merge(test_user)
        session.commit()
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
async def async_client(sync_engine, db_session):
    """Async HTTP client for FastAPI with database dependencies overridden."""
    import src.audiobook_studio.database as database_module

    test_async_url = str(sync_engine.url).replace("sqlite:///", "sqlite+aiosqlite:///")
    test_async_engine = create_async_engine(test_async_url, pool_pre_ping=True)
    test_async_session_factory = async_sessionmaker(
        test_async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    orig_async_engine = database_module._async_engine
    orig_async_session_factory = database_module._async_session_factory
    database_module._async_engine = test_async_engine
    database_module._async_session_factory = test_async_session_factory

    async def get_test_async_db():
        async with test_async_session_factory() as session:
            yield session

    async def override_get_current_user():
        async with test_async_session_factory() as session:
            from sqlalchemy import select

            result = await session.execute(select(User).where(User.id == 1))
            return result.scalar_one_or_none()

    from audiobook_studio.config.loader import reset_settings

    reset_settings()

    app.dependency_overrides[get_async_db] = get_test_async_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
    reset_settings()

    database_module._async_engine = orig_async_engine
    database_module._async_session_factory = orig_async_session_factory
    await test_async_engine.dispose()


@pytest.fixture
def sample_project(async_client: AsyncClient, sync_engine):
    """Create a project with 2 chapters and purpose-built paragraphs.

    Chapter 1: normal narration paragraph + a dialogue paragraph.
    Chapter 2: edited_text="" (intentionally cleared) + image-only text
    (both must show up as skipped in the routing preview).
    """

    async def _create():
        test_async_url = str(sync_engine.url).replace("sqlite:///", "sqlite+aiosqlite:///")
        eng = create_async_engine(test_async_url, pool_pre_ping=True)
        factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False, autoflush=False)

        async with factory() as session:
            project = Project(
                title="Review Gate Project",
                author="Test Author",
                genre="fiction",
                language="zh",
                difficulty="B",
                global_style_notes="Test style",
                story_line_summary="A test story.",
            )
            session.add(project)
            await session.commit()
            await session.refresh(project)
            project_id = project.id

            ch1 = Chapter(project_id=project_id, index=1, title="第一章", raw_text="第一章正文。" * 10)
            ch2 = Chapter(project_id=project_id, index=2, title="第二章", raw_text="第二章正文。" * 10)
            session.add_all([ch1, ch2])
            await session.commit()
            await session.refresh(ch1)
            await session.refresh(ch2)

            paragraphs = [
                # Chapter 1: normal narration
                Paragraph(
                    project_id=project_id,
                    chapter_id=ch1.id,
                    chapter_index=1,
                    index=1,
                    text="这是第一章的第一段旁白文本。",
                    speaker="narrator",
                    speaker_canonical_name="_narrator_",
                ),
                # Chapter 1: dialogue with emotion annotation
                Paragraph(
                    project_id=project_id,
                    chapter_id=ch1.id,
                    chapter_index=1,
                    index=2,
                    text="「你来啦！」他兴奋地说道。",
                    speaker="narrator",
                    speaker_canonical_name="张三",
                    is_dialogue=True,
                    emotion="happy",
                    emotion_intensity=0.8,
                ),
                # Chapter 2: edited_text intentionally cleared → skipped at synthesis
                Paragraph(
                    project_id=project_id,
                    chapter_id=ch2.id,
                    chapter_index=2,
                    index=1,
                    text="这是第二章的封面说明文字。",
                    speaker="narrator",
                    edited_text="",
                ),
                # Chapter 2: image-only text → skipped after placeholder strip
                Paragraph(
                    project_id=project_id,
                    chapter_id=ch2.id,
                    chapter_index=2,
                    index=2,
                    text="[插图: 一幅山水画]",
                    speaker="narrator",
                ),
            ]
            session.add_all(paragraphs)
            await session.commit()

        await eng.dispose()
        return project_id

    return asyncio.run(_create())


def _chapter_ids(db_session, project_id: int) -> list:
    """All chapter ids of the project, ordered by index (fresh read)."""
    from sqlalchemy import select

    db_session.expire_all()
    return (
        db_session.execute(
            select(Chapter.id).where(Chapter.project_id == project_id).order_by(Chapter.index)
        )
        .scalars()
        .all()
    )


def _paragraph_row(db_session, project_id: int, chapter_index: int, para_index: int) -> dict:
    """Fetch one paragraph as a dict (fresh read — expire to dodge identity map)."""
    from sqlalchemy import select

    db_session.expire_all()
    ch_id = db_session.execute(
        select(Chapter.id).where(Chapter.project_id == project_id, Chapter.index == chapter_index)
    ).scalar_one()
    row = db_session.execute(
        select(Paragraph).where(Paragraph.chapter_id == ch_id, Paragraph.index == para_index)
    ).scalar_one()
    return {
        "id": row.id,
        "chapter_id": row.chapter_id,
        "edited_text": row.edited_text,
        "status": row.status,
        "manual_voice_id": row.manual_voice_id,
        "manual_engine": row.manual_engine,
        "notes": row.notes,
    }


# =============================================================================
# Summary endpoint
# =============================================================================


class TestReviewGateSummary:
    """GET /projects/{project_id}/review-gate."""

    @pytest.mark.anyio
    async def test_summary_initial_state(self, async_client: AsyncClient, sample_project: int):
        """Fresh project: all chapters NULL review_status, not all_approved."""
        resp = await async_client.get(f"/api/projects/{sample_project}/review-gate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == sample_project
        assert data["total_chapters"] == 2
        assert data["approved_chapters"] == 0
        assert data["pending_chapters"] == 2
        assert data["all_approved"] is False
        assert data["run_status"] == "not_started"  # no active run
        assert all(c["review_status"] is None for c in data["chapters"])
        # paragraph_count populated from the DB
        counts = {c["index"]: c["paragraph_count"] for c in data["chapters"]}
        assert counts == {1: 2, 2: 2}

    @pytest.mark.anyio
    async def test_summary_nonexistent_project(self, async_client: AsyncClient):
        """Nonexistent project → empty summary, not an error (matches list semantics)."""
        resp = await async_client.get("/api/projects/99999/review-gate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_chapters"] == 0
        assert data["all_approved"] is False  # bool([]) guard — no chapters ≠ approved

    @pytest.mark.anyio
    async def test_summary_reflects_active_run_status(
        self, async_client: AsyncClient, sample_project: int
    ):
        """run_status mirrors the in-memory _active_runs entry."""
        _active_runs[sample_project] = {"status": "awaiting_review"}
        resp = await async_client.get(f"/api/projects/{sample_project}/review-gate")
        assert resp.status_code == 200
        assert resp.json()["run_status"] == "awaiting_review"


# =============================================================================
# Approve / reset / approve-all
# =============================================================================


class TestChapterApproval:
    """POST .../approve | .../reset | .../approve-all."""

    @pytest.mark.anyio
    async def test_approve_single_chapter(
        self, async_client: AsyncClient, sample_project: int, db_session
    ):
        chapter_ids = _chapter_ids(db_session, sample_project)
        resp = await async_client.post(
            f"/api/projects/{sample_project}/review-gate/chapters/{chapter_ids[0]}/approve"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved_chapters"] == 1
        assert data["pending_chapters"] == 1
        assert data["all_approved"] is False
        statuses = {c["chapter_id"]: c["review_status"] for c in data["chapters"]}
        assert statuses[chapter_ids[0]] == "approved"
        assert statuses[chapter_ids[1]] is None

    @pytest.mark.anyio
    async def test_approve_all_releases_gate(
        self, async_client: AsyncClient, sample_project: int
    ):
        resp = await async_client.post(f"/api/projects/{sample_project}/review-gate/approve-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_approved"] is True
        assert data["approved_chapters"] == 2
        # All chapters approved — the gate's poll would now release synthesis
        assert all(c["review_status"] == "approved" for c in data["chapters"])

    @pytest.mark.anyio
    async def test_reset_after_approve(
        self, async_client: AsyncClient, sample_project: int, db_session
    ):
        chapter_ids = _chapter_ids(db_session, sample_project)
        await async_client.post(
            f"/api/projects/{sample_project}/review-gate/chapters/{chapter_ids[0]}/approve"
        )
        resp = await async_client.post(
            f"/api/projects/{sample_project}/review-gate/chapters/{chapter_ids[0]}/reset"
        )
        assert resp.status_code == 200
        statuses = {c["chapter_id"]: c["review_status"] for c in resp.json()["chapters"]}
        assert statuses[chapter_ids[0]] == "pending_review"

    @pytest.mark.anyio
    async def test_reset_not_approved_conflict(
        self, async_client: AsyncClient, sample_project: int, db_session
    ):
        """Resetting a chapter that was never approved → 409 CONFLICT."""
        chapter_ids = _chapter_ids(db_session, sample_project)
        resp = await async_client.post(
            f"/api/projects/{sample_project}/review-gate/chapters/{chapter_ids[0]}/reset"
        )
        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_approve_nonexistent_chapter_404(
        self, async_client: AsyncClient, sample_project: int
    ):
        resp = await async_client.post(
            f"/api/projects/{sample_project}/review-gate/chapters/99999/approve"
        )
        assert resp.status_code == 404


# =============================================================================
# Routing preview
# =============================================================================


class TestRoutingPreview:
    """GET .../chapters/{chapter_id}/routing-preview."""

    @pytest.mark.anyio
    async def test_preview_normal_chapter(
        self, async_client: AsyncClient, sample_project: int, db_session
    ):
        """Normal paragraphs get a full routing decision (engine/voice/prosody)."""
        chapter_ids = _chapter_ids(db_session, sample_project)
        resp = await async_client.get(
            f"/api/projects/{sample_project}/review-gate/chapters/{chapter_ids[0]}/routing-preview"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["chapter_id"] == chapter_ids[0]
        assert data["synthesized_count"] == 2
        assert data["skipped_count"] == 0

        p1, p2 = data["previews"]
        # Narrator default binding: zh-CN-XiaoxiaoNeural, engine via auto routing
        assert p1["skipped"] is False
        assert p1["effective_text"] == "这是第一章的第一段旁白文本。"
        assert p1["voice_id"]  # auto routing picked a concrete voice
        assert p1["engine_choice"] in ("edge", "kokoro", "piper")
        assert p1["prosody_overrides"] is not None
        # Dialogue paragraph keeps its annotated speaker + emotion prosody
        assert p2["skipped"] is False
        assert p2["prosody_overrides"]["emotion"] == "happy"

    @pytest.mark.anyio
    async def test_preview_skips_cleared_and_image_only(
        self, async_client: AsyncClient, sample_project: int, db_session
    ):
        """edited_text="" → empty_text skip; image-only text → image_only skip."""
        chapter_ids = _chapter_ids(db_session, sample_project)
        resp = await async_client.get(
            f"/api/projects/{sample_project}/review-gate/chapters/{chapter_ids[1]}/routing-preview"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["synthesized_count"] == 0
        assert data["skipped_count"] == 2

        p_cleared, p_image = data["previews"]
        assert p_cleared["skip_reason"] == "empty_text"
        assert p_image["skip_reason"] == "image_only"

    @pytest.mark.anyio
    async def test_preview_edited_text_wins(
        self, async_client: AsyncClient, sample_project: int, db_session
    ):
        """edited_text takes precedence over original text in the preview."""
        chapter_ids = _chapter_ids(db_session, sample_project)
        # Human polish: rewrite paragraph 1 of chapter 1
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/{chapter_ids[0]}/paragraphs/1",
            json={"edited_text": "人工润色后的第一段。"},
        )
        assert resp.status_code == 200
        resp = await async_client.get(
            f"/api/projects/{sample_project}/review-gate/chapters/{chapter_ids[0]}/routing-preview"
        )
        data = resp.json()
        assert data["previews"][0]["effective_text"] == "人工润色后的第一段。"

    @pytest.mark.anyio
    async def test_preview_nonexistent_chapter_404(
        self, async_client: AsyncClient, sample_project: int
    ):
        resp = await async_client.get(
            f"/api/projects/{sample_project}/review-gate/chapters/99999/routing-preview"
        )
        assert resp.status_code == 404


# =============================================================================
# Manual overrides (客户最终控制)
# =============================================================================


class TestManualOverrides:
    """manual_engine / manual_voice_id beat auto routing in preview AND edit."""

    @pytest.mark.anyio
    async def test_manual_engine_and_voice_override(
        self, async_client: AsyncClient, sample_project: int, sync_engine
    ):
        """Set kokoro + a Kokoro voice → preview must show exactly that."""
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"manual_engine": "kokoro", "manual_voice_id": "zf_xiaoxiao"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["changes_made"]) == {"manual_engine", "manual_voice_id"}
        assert body["paragraph"]["manual_engine"] == "kokoro"
        assert body["paragraph"]["manual_voice_id"] == "zf_xiaoxiao"

        # Preview reflects the override — the exact synthesis truth
        resp = await async_client.get(
            f"/api/projects/{sample_project}/review-gate/chapters/1/routing-preview"
        )
        data = resp.json()
        p1 = data["previews"][0]
        assert p1["engine_choice"] == "kokoro"
        assert p1["voice_id"] == "zf_xiaoxiao"
        assert p1["fallback_engine"] == "edge"  # fallback recalculated
        assert "manual engine override → kokoro" in p1["reasoning"]

    @pytest.mark.anyio
    async def test_manual_engine_only_keeps_auto_voice(
        self, async_client: AsyncClient, sample_project: int
    ):
        """Engine override alone: auto voice is re-normalized for the NEW
        engine (Edge ID zh-CN-XiaoxiaoNeural → Kokoro zf_xiaoxiao)."""
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"manual_engine": "kokoro"},
        )
        assert resp.status_code == 200
        resp = await async_client.get(
            f"/api/projects/{sample_project}/review-gate/chapters/1/routing-preview"
        )
        p1 = resp.json()["previews"][0]
        assert p1["engine_choice"] == "kokoro"
        assert p1["voice_id"] == "zf_xiaoxiao"  # cross-mapped, not a raw Edge ID
        assert p1["fallback_engine"] == "edge"

    @pytest.mark.anyio
    async def test_clear_manual_overrides(
        self, async_client: AsyncClient, sample_project: int, db_session
    ):
        """clear_* switches remove overrides; routing returns to auto."""
        await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"manual_engine": "kokoro", "manual_voice_id": "zf_xiaoxiao"},
        )
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"clear_manual_voice_id": True, "clear_manual_engine": True},
        )
        assert resp.status_code == 200
        para = resp.json()["paragraph"]
        assert para["manual_voice_id"] is None
        assert para["manual_engine"] is None

        # DB persisted
        row = _paragraph_row(db_session, sample_project, 1, 1)
        assert row["manual_voice_id"] is None
        assert row["manual_engine"] is None

    @pytest.mark.anyio
    async def test_invalid_manual_engine_rejected(
        self, async_client: AsyncClient, sample_project: int
    ):
        """manual_engine not in EngineChoice → 400, nothing written."""
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"manual_engine": "not_a_real_engine"},
        )
        assert resp.status_code == 400


# =============================================================================
# Typed paragraph PATCH (编辑/标注/审计/打回)
# =============================================================================


class TestReviewParagraphEdit:
    """PATCH .../chapters/{chapter_id}/paragraphs/{paragraph_id}."""

    @pytest.mark.anyio
    async def test_edit_annotated_fields(
        self, async_client: AsyncClient, sample_project: int, db_session
    ):
        """Polish text + fix annotation in one PATCH."""
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/2",
            json={
                "edited_text": "「你来啦！」他高兴地喊道。",
                "emotion": "joy",
                "emotion_intensity": 0.9,
                "speech_rate": 1.1,
                "notes": "终审时把「兴奋」改为「高兴」",
                "note": "术语统一",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "edited_text" in body["changes_made"]
        assert "emotion" in body["changes_made"]
        assert body["paragraph"]["emotion"] == "joy"
        assert body["paragraph"]["edited_text"] == "「你来啦！」他高兴地喊道。"

        row = _paragraph_row(db_session, sample_project, 1, 2)
        assert row["edited_text"] == "「你来啦！」他高兴地喊道。"
        assert row["status"] == "edited"  # human-edited paragraph state
        assert row["notes"] == "终审时把「兴奋」改为「高兴」"

    @pytest.mark.anyio
    async def test_edit_writes_human_tts_edit_audit(
        self, async_client: AsyncClient, sample_project: int, db_session
    ):
        """Every effective edit creates a TTSEdit version with source="human"."""
        await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"edited_text": "润色一次。"},
        )
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"edited_text": "又润色一次。"},
        )
        assert resp.status_code == 200
        assert resp.json()["tts_edit_version"] == 2  # version increments

        from sqlalchemy import select

        from src.audiobook_studio.models.tts_edit import TTSEdit

        db_session.expire_all()
        rows = (
            db_session.execute(select(TTSEdit).where(TTSEdit.paragraph_id == 1)).scalars().all()
        )
        assert len(rows) == 2
        assert all(r.source == "human" for r in rows)
        assert [r.version for r in rows] == [1, 2]
        assert rows[-1].edited_text == "又润色一次。"
        assert rows[-1].rationale == "人工终审编辑 (manual review edit)"

    @pytest.mark.anyio
    async def test_edit_resets_approved_chapter(
        self, async_client: AsyncClient, sample_project: int, db_session
    ):
        """Editing a paragraph in an approved chapter → back to pending_review."""
        chapter_ids = _chapter_ids(db_session, sample_project)
        ch_id = chapter_ids[0]
        await async_client.post(f"/api/projects/{sample_project}/review-gate/chapters/{ch_id}/approve")
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/{ch_id}/paragraphs/1",
            json={"edited_text": "确认后又改了。"},
        )
        assert resp.status_code == 200
        assert resp.json()["chapter_review_reset"] is True
        statuses = {c["chapter_id"]: c["review_status"] for c in (await _summary(async_client, sample_project))["chapters"]}
        assert statuses[ch_id] == "pending_review"

    @pytest.mark.anyio
    async def test_noop_edit_changes_nothing(
        self, async_client: AsyncClient, sample_project: int, db_session
    ):
        """Sending the same value twice → second PATCH is a no-op (no audit)."""
        # First PATCH: edited_text was NULL → setting it IS a change
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"edited_text": "这是第一章的第一段旁白文本。"},
        )
        assert resp.status_code == 200
        assert resp.json()["changes_made"] == ["edited_text"]
        # Second identical PATCH: nothing changed
        resp2 = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"edited_text": "这是第一章的第一段旁白文本。"},
        )
        assert resp2.json()["changes_made"] == []
        assert resp2.json()["tts_edit_version"] is None

        from sqlalchemy import select

        from src.audiobook_studio.models.tts_edit import TTSEdit

        db_session.expire_all()
        count = len(db_session.execute(select(TTSEdit.id).where(TTSEdit.paragraph_id == 1)).all())
        assert count == 1  # only the first edit's audit record

    @pytest.mark.anyio
    async def test_clear_edited_text_skips_paragraph(
        self, async_client: AsyncClient, sample_project: int
    ):
        """edited_text="" is a legal, intentional clear → synthesis skip."""
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"edited_text": ""},
        )
        assert resp.status_code == 200
        assert "edited_text" in resp.json()["changes_made"]

        resp = await async_client.get(
            f"/api/projects/{sample_project}/review-gate/chapters/1/routing-preview"
        )
        assert resp.json()["previews"][0]["skip_reason"] == "empty_text"

    @pytest.mark.anyio
    async def test_unknown_field_rejected(
        self, async_client: AsyncClient, sample_project: int
    ):
        """extra=forbid: typos must fail loudly (422), not be silently dropped."""
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"edited_texte": "typo field"},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_out_of_range_prosody_rejected(
        self, async_client: AsyncClient, sample_project: int
    ):
        """Annotation bounds enforced at the API layer (422)."""
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/1",
            json={"speech_rate": 99.0},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_edit_nonexistent_paragraph_404(
        self, async_client: AsyncClient, sample_project: int
    ):
        resp = await async_client.patch(
            f"/api/projects/{sample_project}/review-gate/chapters/1/paragraphs/99999",
            json={"edited_text": "x"},
        )
        assert resp.status_code == 404


async def _summary(async_client: AsyncClient, project_id: int) -> dict:
    resp = await async_client.get(f"/api/projects/{project_id}/review-gate")
    assert resp.status_code == 200
    return resp.json()
