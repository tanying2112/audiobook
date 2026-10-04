"""Regression test: write_annotate must NOT trigger NOT NULL constraint failure
when ParagraphAnnotation.pause_before_ms / pause_after_ms are None.

Bug (commit 40abf43): ``persistence.write_annotate`` assigns the v2 schema's
``pause_*_ms`` LLM-returned fields (documented as ``Optional, default=None`` in
the v1-compatible contract) **directly** onto NOT-NULL ORM columns.

In the full pipeline, extract stage first creates the Paragraph row with the
ORM Python-level ``default=0`` (``pause_before_ms == 0``). Then annotate stage
calls ``write_annotate`` which **overwrites** that column with the LLM's
``None``:

    para.pause_before_ms = result.pause_before_ms  # None
    para.pause_after_ms  = result.pause_after_ms   # None
    await db.commit()  # UPDATE ... SET pause_before_ms=NULL -> IntegrityError

This reproduces the production failure observed during the end-to-end
pipeline smoke (``撑 4``):

    sqlite3.IntegrityError: NOT NULL constraint failed: paragraphs.pause_before_ms

The fix coalesces ``None`` -> ``0`` on assignment so the NOT-NULL invariant
is respected regardless of whether the LLM returned the v1-compatible fields.
"""

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audiobook_studio.database import Base  # noqa: F401 — register registry
from src.audiobook_studio.models import Chapter, Paragraph, Project
from src.audiobook_studio.pipeline.persistence import write_annotate
from src.audiobook_studio.schemas import ParagraphAnnotation


async def _seed_with_extracted_paragraph(db: AsyncSession) -> tuple[Project, Chapter, Paragraph]:
    """Mirror the extract-stage path: create Project, Chapter, and a Paragraph
    row whose ``pause_before_ms`` is populated purely via ORM default (== 0).
    Commit so the row is visible to a subsequent annotate-stage session.
    """
    project = Project(title="regress", language="zh")
    db.add(project)
    await db.flush()
    chapter = Chapter(project_id=project.id, index=1)
    db.add(chapter)
    await db.flush()
    para = Paragraph(
        project_id=project.id,
        chapter_id=chapter.id,
        chapter_index=1,
        index=1,
        text="林黛玉缓步走入潇湘馆。",
        status="extracted",
    )
    db.add(para)
    await db.commit()
    # ORM default=0 must have populated the column at insert time.
    assert para.pause_before_ms == 0, "extract stage establishes pause_before_ms=0"
    return project, chapter, para


def _annotation(idx: int, *, pause_before_ms=None, pause_after_ms=None) -> ParagraphAnnotation:
    """A v2 ParagraphAnnotation whose v1-compatible pause fields are deliberately
    left as the schema default ``None`` (mirrors real LLM output for v2 contract).
    """
    return ParagraphAnnotation(
        paragraph_index=idx,
        text="林黛玉缓步走入潇湘馆。",
        speaker_canonical_name="_narrator_",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        confidence=0.9,
        pause_before_ms=pause_before_ms,
        pause_after_ms=pause_after_ms,
    )


def test_paragraphs_schema_pause_columns_are_not_null_without_default(_async_db_path):
    """Schema contract: pause_*_ms are NOT NULL with no server default. The ORM
    Python-level ``default=0`` is the sole guard against the INSERT/UPDATE path.
    Pinning this reality protects the persistence-layer coalescing fix below.
    """
    from sqlalchemy import create_engine

    sync_eng = create_engine(f"sqlite:///{_async_db_path}")
    cols = {c["name"]: c for c in sa_inspect(sync_eng).get_columns("paragraphs")}
    sync_eng.dispose()
    assert cols["pause_before_ms"]["nullable"] is False
    assert cols["pause_before_ms"]["default"] is None, "no server_default (relies on ORM default=0)"
    assert cols["pause_after_ms"]["nullable"] is False
    assert cols["pause_after_ms"]["default"] is None


@pytest.mark.asyncio
async def test_write_annotate_survives_null_pause_after_extract(_async_db_engine):
    """Reproduction + fix target. Reproduces the production failure path:

    1. extract stage commits Paragraph(pause_before_ms=0)
    2. annotate stage calls write_annotate with v2 annotation where
       pause_*_ms is None (the documented v1-compatible default)
    3. write_annotate MUST coalesce None -> 0; otherwise UPDATE fails with
       ``IntegrityError: NOT NULL constraint failed: paragraphs.pause_before_ms``

    Before the fix this test FAILS with the exact production error. After the
    fix, the paragraph persists with both pause columns coalesced to 0.
    """
    # 1) extract stage: create + commit the paragraph with ORM default pause=0
    async with AsyncSession(_async_db_engine, expire_on_commit=False) as db:
        project, chapter, _ = await _seed_with_extracted_paragraph(db)
        pid, cid = project.id, chapter.id

    # 2) annotate stage: a fresh session updates the existing row via write_annotate
    async with AsyncSession(_async_db_engine, expire_on_commit=False) as db:
        chapter_ref = (await db.execute(select(Chapter).filter(Chapter.id == cid))).scalar_one()
        para = await write_annotate(
            db,
            project_id=pid,
            chapter=chapter_ref,
            paragraph_index=1,
            result=_annotation(1),  # pause_*_ms=None
        )
        assert para.pause_before_ms == 0, "None must be coalesced to 0, not persisted as NULL"
        assert para.pause_after_ms == 0

    # 3) The row in DB must carry the coalesced 0, not NULL.
    async with AsyncSession(_async_db_engine, expire_on_commit=False) as db:
        row = (
            await db.execute(select(Paragraph).filter(Paragraph.index == 1, Paragraph.chapter_id == cid))
        ).scalar_one()
        assert row.pause_before_ms == 0, "coalesced None must reach the DB as 0"
        assert row.pause_after_ms == 0
        assert row.status == "annotated"


@pytest.mark.asyncio
async def test_annotate_apersist_uses_ground_truth_paragraph_index(_async_db_engine):
    """Regression: ``AnnotateStage.apersist`` must use the caller-provided
    ``paragraph_index`` (ground truth from the CLI orchestrator loop) when
    persisting annotation, NOT the LLM-returned ``result.paragraph_index``.

    Bug: ``apersist`` did ``para_index = getattr(result, "paragraph_index",
    paragraph_index or 0)``. This trusts the LLM's ``ParagraphAnnotation.
    paragraph_index`` first and only falls back to the caller's value when the
    attribute is missing. In production, the deepseek model returned
    ``paragraph_index=0`` for the first paragraph, which caused
    ``write_annotate`` to INSERT a bogus ``Paragraph(index=0, text="")`` row
    with the real paragraph's annotation. The phantom idx=0 paragraph then
    crashed downstream stages: synthesize with ``TtsRoutingInput text=''
    min_length=1`` violation, and quality with
    ``MultipleResultsFound`` on TTSEdit lookup.

    The fix flips the precedence: caller-provided ``paragraph_index`` wins; the
    LLM value is used only as a last-resort fallback when the caller passes
    ``None``.
    """
    from src.audiobook_studio.pipeline.stage_registry import AnnotateStage

    # 1) extract stage: create paragraph idx=5 (not 0) with real text
    async with AsyncSession(_async_db_engine, expire_on_commit=False) as db:
        project = Project(title="regress_idx", language="zh")
        db.add(project)
        await db.flush()
        chapter = Chapter(project_id=project.id, index=1)
        db.add(chapter)
        await db.flush()
        para = Paragraph(
            project_id=project.id,
            chapter_id=chapter.id,
            chapter_index=1,
            index=5,  # the real paragraph index for this test
            text="林黛玉蹙眉凝望窗外砌成的一庭碎雪。",
            status="extracted",
        )
        db.add(para)
        await db.commit()
        pid, cid = project.id, chapter.id

    # 2) annotate stage: simulate LLM returning paragraph_index=0 (the bug)
    #    but caller passes ground truth paragraph_index=5 to apersist
    handler = AnnotateStage()
    async with AsyncSession(_async_db_engine, expire_on_commit=False) as db:
        chapter_ref = (await db.execute(select(Chapter).filter(Chapter.id == cid))).scalar_one()
        para_ref = (
            await db.execute(select(Paragraph).filter(Paragraph.index == 5, Paragraph.chapter_id == cid))
        ).scalar_one()
        result = _annotation(
            0,  # <-- LLM lies: returns paragraph_index=0 (the bug source)
            pause_before_ms=200,
            pause_after_ms=100,
        )
        await handler.apersist(
            db,
            project_id=pid,
            chapter=chapter_ref,
            paragraph=para_ref,
            result=result,
            chapter_index=1,
            paragraph_index=5,  # <-- caller's ground truth
        )

    # 3) The annotation MUST land on paragraph idx=5 (ground truth),
    #    and NO phantom idx=0 paragraph may be created.
    async with AsyncSession(_async_db_engine, expire_on_commit=False) as db:
        rows = (
            (await db.execute(select(Paragraph).filter(Paragraph.chapter_id == cid).order_by(Paragraph.index)))
            .scalars()
            .all()
        )
        indices = [r.index for r in rows]
        assert indices == [5], f"expected only [5], got {indices} (LLM paragraph_index=0 must NOT create phantom idx=0)"
        annotated = rows[0]
        assert annotated.status == "annotated"
        assert annotated.speaker_canonical_name == "_narrator_"
        assert annotated.pause_before_ms == 200
        assert annotated.pause_after_ms == 100
