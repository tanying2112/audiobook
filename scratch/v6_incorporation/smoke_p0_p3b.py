"""Smoke test for P0 (export HTTP download closure) + P3b (CharacterManager dead UI fix).

Run: cd /Users/guwj/Documents/audiobook && .venv/bin/python scratch/v6_incorporation/smoke_p0_p3b.py

Checks (no server process, no pytest):
1. FastAPI app imports and the two new export routes are registered.
2. Path traversal attack: `_resolve_export_file` rejects `../../etc/passwd` (returns None).
3. `_resolve_export_file` accepts a legitimate file inside the project export root.
4. CharacterUpdate schema accepts emotion/speech_rate/pitch_shift_semitones and
   validates ranges (out-of-range -> ValidationError).
5. Character model has the three new columns.
6. Alembic migrations applied: both local DBs have the new columns on `characters`.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("MOCK_LLM", "true")
# The global RateLimitMiddleware (10-burst token bucket per IP) would 429 the
# later TestClient requests in one process; disable it for this smoke run.
os.environ["RATE_LIMIT_ENABLED"] = "false"

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def test_routes():
    print("== P0: FastAPI app routes ==")
    from audiobook_studio.main import app

    # FastAPI 0.139 include_router is lazy: app.routes holds _IncludedRouter
    # wrappers until openapi() flattens them. Use the OpenAPI schema (same
    # thing the client would see) to assert route registration.
    schema = app.openapi()
    all_paths = set(schema.get("paths", {}).keys())
    check(
        "GET /api/projects/{project_id}/export/files registered",
        "/api/projects/{project_id}/export/files" in all_paths,
        f"got: {sorted(p for p in all_paths if 'export' in p)}",
    )
    check(
        "GET /api/projects/{project_id}/export/download registered",
        "/api/projects/{project_id}/export/download" in all_paths,
    )

    # Verify the download route is a GET with 'path' query param
    dl = schema["paths"].get("/api/projects/{project_id}/export/download", {})
    check("download route exists and is GET", "get" in dl, f"ops={sorted(dl.keys())}")
    params = dl.get("get", {}).get("parameters", [])
    check(
        "download GET declares 'path' query param",
        any(p.get("name") == "path" and p.get("in") == "query" for p in params),
        f"params={params}",
    )


def test_traversal_guard():
    print("== P0: path traversal guard (unit-level) ==")
    from audiobook_studio.api import export as export_api

    # Clean the in-process registries so the root falls back to ./output/project_{id}
    export_api._project_latest_export.clear()
    export_api._export_jobs.clear()

    # Traversal attempts must all be rejected (None)
    for evil in [
        "../../etc/passwd",
        "../../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
        "subdir/../../other_project/file.m4b",
        "/etc/passwd",
        "output/../../etc/passwd",
    ]:
        result = export_api._resolve_export_file(999999, evil)
        check(f"rejects {evil!r}", result is None, f"got {result}")

    # Absolute path outside root
    result = export_api._resolve_export_file(999999, str(Path("/etc/passwd")))
    check("rejects absolute /etc/passwd", result is None, f"got {result}")

    # Non-existent file inside root -> None
    result = export_api._resolve_export_file(999999, "nonexistent.m4b")
    check("returns None for missing file inside root", result is None)

    # Legit file inside the (conventional) export root -> resolved
    root = export_api._export_root_for_project(999999)
    root.mkdir(parents=True, exist_ok=True)
    legit = root / "smoke_test_artifact.m4b"
    legit.write_bytes(b"smoke")
    try:
        result = export_api._resolve_export_file(999999, "smoke_test_artifact.m4b")
        check(
            "accepts legit file inside root",
            result is not None and result.is_file() and result.is_relative_to(root),
            f"got {result}",
        )
        # Plain name only (no subdir)
        check("resolved path equals expected", result == legit.resolve())
    finally:
        legit.unlink(missing_ok=True)
        # Also remove the (now empty) scratch export dir created for this test
        try:
            root.rmdir()
        except OSError:
            pass

    # With a registered job output dir: download root follows the job's dir
    with tempfile.TemporaryDirectory() as td:
        job_dir = Path(td).resolve()
        marker = job_dir / "project_1.m4b"
        marker.write_bytes(b"x")
        export_api._export_jobs["t1"] = {
            "status": "complete",
            "output_paths": {"m4b": str(marker)},
            "error": None,
            "project_id": 42,
        }
        export_api._project_latest_export[42] = "t1"
        try:
            check(
                "export root follows latest job output dir",
                export_api._export_root_for_project(42) == job_dir,
                f"got {export_api._export_root_for_project(42)}",
            )
            r = export_api._resolve_export_file(42, "project_1.m4b")
            check("resolves file from job output dir", r is not None and r.name == "project_1.m4b")
            # traversal still blocked against the job's dir
            r = export_api._resolve_export_file(42, "../../etc/passwd")
            check("rejects traversal against job dir", r is None, f"got {r}")
        finally:
            export_api._project_latest_export.clear()
            export_api._export_jobs.clear()


def test_download_endpoint_404():
    print("== P0: download endpoint (TestClient, no real DB/server) ==")
    # Function-level check of the endpoint's guard behaviour via HTTP would
    # need auth+DB; the traversal guard is already unit-tested above. Instead
    # verify the endpoint handler exists and its signature carries the query.
    from audiobook_studio.api.export import download_export_file
    import inspect

    sig = inspect.signature(download_export_file)
    check("download handler has 'path' param", "path" in sig.parameters)
    check("download handler has 'project_id' param", "project_id" in sig.parameters)

    from audiobook_studio.api.export import list_export_files
    sig2 = inspect.signature(list_export_files)
    check("files handler has project_id param", "project_id" in sig2.parameters)


def test_download_endpoint_e2e():
    """TestClient with overridden auth+DB deps: full HTTP round-trip."""
    print("== P0: download endpoint end-to-end (TestClient, deps overridden) ==")
    import tempfile
    from pathlib import Path

    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from audiobook_studio.main import app
    from audiobook_studio.api.dependencies import get_async_db
    from audiobook_studio.auth.dependencies import get_current_active_user
    from audiobook_studio.api import export as export_api
    from audiobook_studio.orm_base import Base
    from audiobook_studio.models import Project

    # In-memory async DB with the projects table + one row
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSessionLocal() as s:
            s.add(Project(id=501, title="smoke", author="tester"))
            await s.commit()

    import asyncio

    asyncio.get_event_loop_policy()
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(seed())
    finally:
        pass

    async def override_db():
        async with AsyncSessionLocal() as session:
            yield session

    async def override_auth():
        return {"id": 1, "username": "smoke"}

    app.dependency_overrides[get_async_db] = override_db
    app.dependency_overrides[get_current_active_user] = override_auth

    # Register an export job pointing at a temp dir so the download root is
    # isolated from the real ./output tree.
    with tempfile.TemporaryDirectory() as td:
        job_dir = Path(td).resolve()
        (job_dir / "project_501.m4b").write_bytes(b"SMOKE-AUDIO")
        (job_dir / "project_501.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
        export_api._export_jobs["smoke-task"] = {
            "status": "complete",
            "output_paths": {"m4b": str(job_dir / "project_501.m4b")},
            "error": None,
            "project_id": 501,
            "chapter_count": 1,
        }
        export_api._project_latest_export[501] = "smoke-task"

        client = TestClient(app)
        try:
            # /files lists both artifacts
            r = client.get("/api/projects/501/export/files")
            check("GET /export/files returns 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
            body = r.json()
            names = {f["filename"] for f in body.get("files", [])}
            check("files list contains m4b + srt", {"project_501.m4b", "project_501.srt"} <= names, f"got {names}")
            m4b_entry = next((f for f in body["files"] if f["filename"] == "project_501.m4b"), None)
            check(
                "file entry has size_bytes + mtime + rel_path",
                m4b_entry is not None
                and m4b_entry["size_bytes"] == len(b"SMOKE-AUDIO")
                and isinstance(m4b_entry["mtime"], str)
                and "T" in m4b_entry["mtime"]  # ISO 8601 (post-timestamp-middleware)
                and m4b_entry["rel_path"] == "project_501.m4b",
                f"entry={m4b_entry}",
            )

            # Download happy path: attachment headers + body
            r = client.get("/api/projects/501/export/download", params={"path": "project_501.m4b"})
            check("download legit file returns 200", r.status_code == 200, f"status={r.status_code}")
            check(
                "Content-Disposition is attachment",
                "attachment" in r.headers.get("content-disposition", "")
                and "project_501.m4b" in r.headers.get("content-disposition", ""),
                f"cd={r.headers.get('content-disposition')}",
            )
            check("download body matches file content", r.content == b"SMOKE-AUDIO")

            # Traversal via HTTP → 404
            for evil in ["../../etc/passwd", "../..", "subdir/../../../etc/passwd"]:
                r = client.get("/api/projects/501/export/download", params={"path": evil})
                check(
                    f"download {evil!r} → 404",
                    r.status_code == 404,
                    f"status={r.status_code}",
                )

            # Unknown project → 404
            r = client.get("/api/projects/999999/export/files")
            check("files for unknown project → 404", r.status_code == 404, f"status={r.status_code}")

            # Unknown project download → 404 (no root leak)
            r = client.get("/api/projects/999999/export/download", params={"path": "x.m4b"})
            check("download for unknown project → 404", r.status_code == 404, f"status={r.status_code}")
        finally:
            export_api._project_latest_export.clear()
            export_api._export_jobs.clear()
            app.dependency_overrides.clear()
            loop.run_until_complete(engine.dispose())
            loop.close()


def test_character_schema():
    print("== P3b: CharacterUpdate schema ==")
    from audiobook_studio.api.characters import CharacterUpdate, CharacterResponse, CharacterBase
    from pydantic import ValidationError

    # Accepted values
    upd = CharacterUpdate(
        emotion="happy",
        speech_rate=1.2,
        pitch_shift_semitones=-3,
    )
    check("accepts valid emotion/speech_rate/pitch", upd.emotion == "happy" and upd.speech_rate == 1.2 and upd.pitch_shift_semitones == -3)

    # Range validation: speech_rate
    try:
        CharacterUpdate(speech_rate=3.0)
        check("rejects speech_rate=3.0", False)
    except ValidationError:
        check("rejects speech_rate=3.0", True)
    try:
        CharacterUpdate(speech_rate=0.1)
        check("rejects speech_rate=0.1", False)
    except ValidationError:
        check("rejects speech_rate=0.1", True)
    check("accepts speech_rate bounds 0.5", CharacterUpdate(speech_rate=0.5).speech_rate == 0.5)
    check("accepts speech_rate bounds 2.0", CharacterUpdate(speech_rate=2.0).speech_rate == 2.0)

    # Range validation: pitch_shift_semitones
    try:
        CharacterUpdate(pitch_shift_semitones=13)
        check("rejects pitch=13", False)
    except ValidationError:
        check("rejects pitch=13", True)
    try:
        CharacterUpdate(pitch_shift_semitones=-13)
        check("rejects pitch=-13", False)
    except ValidationError:
        check("rejects pitch=-13", True)
    check("accepts pitch bounds 12", CharacterUpdate(pitch_shift_semitones=12).pitch_shift_semitones == 12)
    check("accepts pitch bounds -12", CharacterUpdate(pitch_shift_semitones=-12).pitch_shift_semitones == -12)

    # CharacterCreate inherits the fields (used by create flow)
    from audiobook_studio.api.characters import CharacterCreate
    cc = CharacterCreate(canonical_name="X", emotion="sad", speech_rate=0.9, pitch_shift_semitones=2)
    check("CharacterCreate accepts prosody fields", cc.emotion == "sad")

    # Response schema exposes them (frontend reads them back)
    check("CharacterResponse has emotion field", "emotion" in CharacterResponse.model_fields)
    check("CharacterResponse has speech_rate field", "speech_rate" in CharacterResponse.model_fields)
    check("CharacterResponse has pitch_shift_semitones field", "pitch_shift_semitones" in CharacterResponse.model_fields)


def test_character_model_columns():
    print("== P3b: Character model columns ==")
    from audiobook_studio.models import Character

    cols = {c.name for c in Character.__table__.columns}
    check("model has emotion column", "emotion" in cols)
    check("model has speech_rate column", "speech_rate" in cols)
    check("model has pitch_shift_semitones column", "pitch_shift_semitones" in cols)


def test_character_patch_persist():
    """P3b core: PATCH /characters/{id} persists emotion/speech_rate/pitch to DB."""
    print("== P3b: PATCH character persists prosody fields (TestClient, in-memory DB) ==")
    import asyncio

    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from audiobook_studio.main import app
    from audiobook_studio.api.dependencies import get_async_db
    from audiobook_studio.auth.dependencies import get_current_active_user
    from audiobook_studio.orm_base import Base
    from audiobook_studio.models import Character, Project

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    SL = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with SL() as s:
            s.add(Project(id=601, title="smoke-p3b", author="t"))
            s.add(Character(id=11, project_id=601, canonical_name="林冲"))
            await s.commit()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(seed())

    async def odb():
        async with SL() as s:
            yield s

    async def oau():
        return {"id": 1, "username": "s"}

    app.dependency_overrides[get_async_db] = odb
    app.dependency_overrides[get_current_active_user] = oau

    client = TestClient(app)
    try:
        r = client.patch(
            "/api/projects/601/characters/11",
            json={
                "canonical_name": "林冲",
                "suggested_voice_id": "voice-A",
                "emotion": "angry",
                "speech_rate": 1.3,
                "pitch_shift_semitones": -4,
            },
        )
        check("PATCH character returns 200", r.status_code == 200, f"status={r.status_code} body={r.text[:300]}")
        body = r.json()
        check(
            "PATCH response echoes prosody fields",
            body.get("emotion") == "angry"
            and body.get("speech_rate") == 1.3
            and body.get("pitch_shift_semitones") == -4,
            f"body={body}",
        )

        # Read back from the DB session — proves 落库 (persisted), not just echoed
        async def readback():
            async with SL() as s:
                from sqlalchemy import select

                row = (
                    await s.execute(select(Character).where(Character.id == 11))
                ).scalar_one_or_none()
                return row.emotion, row.speech_rate, row.pitch_shift_semitones

        emo, rate, pitch = loop.run_until_complete(readback())
        check(
            "DB row carries emotion/speech_rate/pitch",
            (emo, rate, pitch) == ("angry", 1.3, -4),
            f"got {(emo, rate, pitch)}",
        )

        # GET list also returns them (frontend read path)
        r = client.get("/api/projects/601/characters")
        chars = r.json()
        check(
            "GET /characters exposes prosody fields",
            r.status_code == 200
            and len(chars) == 1
            and chars[0].get("emotion") == "angry"
            and chars[0].get("speech_rate") == 1.3
            and chars[0].get("pitch_shift_semitones") == -4,
            f"body={chars}",
        )

        # Out-of-range PATCH → 422
        r = client.patch(
            "/api/projects/601/characters/11",
            json={"speech_rate": 5.0},
        )
        check("PATCH speech_rate=5.0 → 422", r.status_code == 422, f"status={r.status_code}")
        r = client.patch(
            "/api/projects/601/characters/11",
            json={"pitch_shift_semitones": 99},
        )
        check("PATCH pitch=99 → 422", r.status_code == 422, f"status={r.status_code}")
    finally:
        app.dependency_overrides.clear()
        loop.run_until_complete(engine.dispose())
        loop.close()


def test_db_migrations():
    print("== P3b: both local DBs migrated ==")
    for db_path in [ROOT / "src/data/audiobook.db", ROOT / "data/audiobook.db"]:
        if not db_path.exists():
            check(f"{db_path.name} exists", False, "file missing")
            continue
        con = sqlite3.connect(str(db_path))
        try:
            rows = con.execute("PRAGMA table_info(characters)").fetchall()
            col_names = {r[1] for r in rows}
        finally:
            con.close()
        check(
            f"{db_path.relative_to(ROOT)} characters has emotion",
            "emotion" in col_names,
            f"cols={sorted(col_names)}",
        )
        check(f"{db_path.relative_to(ROOT)} characters has speech_rate", "speech_rate" in col_names)
        check(f"{db_path.relative_to(ROOT)} characters has pitch_shift_semitones", "pitch_shift_semitones" in col_names)


def main():
    print("=== smoke_p0_p3b ===")
    test_routes()
    test_traversal_guard()
    test_download_endpoint_404()
    test_download_endpoint_e2e()
    test_character_schema()
    test_character_model_columns()
    test_character_patch_persist()
    test_db_migrations()
    print(f"\n=== RESULT: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
