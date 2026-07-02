"""Bulk CRUD coverage tests for all legacy API endpoints.

Covers: books, paragraphs, tts_edits, routings, qualities (0% → ~100%).
"""

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.audiobook_studio.api.books import router as books_router
from src.audiobook_studio.api.paragraphs import router as paragraphs_router
from src.audiobook_studio.api.qualities import router as qualities_router
from src.audiobook_studio.api.routings import router as routings_router
from src.audiobook_studio.api.tts_edits import router as tts_router
from src.audiobook_studio.database import Base, get_db

app = FastAPI()
app.include_router(books_router)
app.include_router(paragraphs_router)
app.include_router(tts_router)
app.include_router(routings_router)
app.include_router(qualities_router)


@pytest.fixture()
def client():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()
    os.unlink(tmp.name)


# ── Books CRUD ──────────────────────────────────────────────────────────────


class TestBooksCRUD:
    def test_create_book(self, client):
        r = client.post("/books/", json={"title": "T", "author": "A", "language": "en"})
        assert r.status_code == 201
        assert r.json()["title"] == "T"

    def test_list_books(self, client):
        client.post("/books/", json={"title": "T", "author": "A", "language": "en"})
        r = client.get("/books/")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_get_book(self, client):
        bid = client.post("/books/", json={"title": "T", "author": "A", "language": "en"}).json()["id"]
        r = client.get(f"/books/{bid}")
        assert r.status_code == 200

    def test_get_book_404(self, client):
        r = client.get("/books/99999")
        assert r.status_code == 404

    def test_update_book(self, client):
        bid = client.post("/books/", json={"title": "T", "author": "A", "language": "en"}).json()["id"]
        r = client.put(f"/books/{bid}", json={"title": "New", "author": "A", "language": "en"})
        assert r.status_code == 200
        assert r.json()["title"] == "New"

    def test_update_book_404(self, client):
        r = client.put("/books/99999", json={"title": "X", "author": "A", "language": "en"})
        assert r.status_code == 404

    def test_delete_book(self, client):
        bid = client.post("/books/", json={"title": "T", "author": "A", "language": "en"}).json()["id"]
        r = client.delete(f"/books/{bid}")
        assert r.status_code == 204

    def test_delete_book_404(self, client):
        r = client.delete("/books/99999")
        assert r.status_code == 404


# ── Paragraphs CRUD ─────────────────────────────────────────────────────────


class TestParagraphsCRUD:
    def _book(self, c):
        return c.post("/books/", json={"title": "T", "author": "A", "language": "en"}).json()["id"]

    def test_create_paragraph(self, client):
        bid = self._book(client)
        r = client.post("/paragraphs/", json={"book_id": bid, "index": 0, "text": "hello"})
        assert r.status_code == 201

    def test_list_paragraphs(self, client):
        bid = self._book(client)
        client.post("/paragraphs/", json={"book_id": bid, "index": 0, "text": "hello"})
        r = client.get("/paragraphs/")
        assert r.status_code == 200

    def test_get_paragraph(self, client):
        bid = self._book(client)
        pid = client.post("/paragraphs/", json={"book_id": bid, "index": 0, "text": "hello"}).json()["id"]
        r = client.get(f"/paragraphs/{pid}")
        assert r.status_code == 200

    def test_get_paragraph_404(self, client):
        r = client.get("/paragraphs/99999")
        assert r.status_code == 404

    def test_update_paragraph(self, client):
        bid = self._book(client)
        pid = client.post("/paragraphs/", json={"book_id": bid, "index": 0, "text": "hello"}).json()["id"]
        r = client.put(f"/paragraphs/{pid}", json={"book_id": bid, "index": 0, "text": "world"})
        assert r.status_code == 200
        assert r.json()["text"] == "world"

    def test_delete_paragraph(self, client):
        bid = self._book(client)
        pid = client.post("/paragraphs/", json={"book_id": bid, "index": 0, "text": "hello"}).json()["id"]
        r = client.delete(f"/paragraphs/{pid}")
        assert r.status_code == 204


# ── TTSEdit CRUD ────────────────────────────────────────────────────────────


class TestTTSEditsCRUD:
    def _para(self, c):
        bid = c.post("/books/", json={"title": "T", "author": "A", "language": "en"}).json()["id"]
        return c.post("/paragraphs/", json={"book_id": bid, "index": 0, "text": "x"}).json()["id"]

    def test_create_tts_edit(self, client):
        pid = self._para(client)
        r = client.post("/tts_edits/", json={"paragraph_id": pid, "edited_text": "edited"})
        assert r.status_code == 201

    def test_list_tts_edits(self, client):
        pid = self._para(client)
        client.post("/tts_edits/", json={"paragraph_id": pid, "edited_text": "e"})
        r = client.get("/tts_edits/")
        assert r.status_code == 200

    def test_get_tts_edit(self, client):
        pid = self._para(client)
        eid = client.post("/tts_edits/", json={"paragraph_id": pid, "edited_text": "e"}).json()["id"]
        r = client.get(f"/tts_edits/{eid}")
        assert r.status_code == 200

    def test_delete_tts_edit(self, client):
        pid = self._para(client)
        eid = client.post("/tts_edits/", json={"paragraph_id": pid, "edited_text": "e"}).json()["id"]
        r = client.delete(f"/tts_edits/{eid}")
        assert r.status_code == 204


# ── Routing CRUD ────────────────────────────────────────────────────────────


class TestRoutingsCRUD:
    def _para(self, c):
        bid = c.post("/books/", json={"title": "T", "author": "A", "language": "en"}).json()["id"]
        return c.post("/paragraphs/", json={"book_id": bid, "index": 0, "text": "x"}).json()["id"]

    def test_create_routing(self, client):
        pid = self._para(client)
        r = client.post("/routings/", json={"paragraph_id": pid, "voice": "v1"})
        assert r.status_code == 201

    def test_list_routings(self, client):
        pid = self._para(client)
        client.post("/routings/", json={"paragraph_id": pid, "voice": "v1"})
        r = client.get("/routings/")
        assert r.status_code == 200

    def test_get_routing(self, client):
        pid = self._para(client)
        rid = client.post("/routings/", json={"paragraph_id": pid, "voice": "v1"}).json()["id"]
        r = client.get(f"/routings/{rid}")
        assert r.status_code == 200

    def test_delete_routing(self, client):
        pid = self._para(client)
        rid = client.post("/routings/", json={"paragraph_id": pid, "voice": "v1"}).json()["id"]
        r = client.delete(f"/routings/{rid}")
        assert r.status_code == 204


# ── Quality CRUD ────────────────────────────────────────────────────────────


class TestQualitiesCRUD:
    def _quality_payload(self, c):
        bid = c.post("/books/", json={"title": "T", "author": "A", "language": "en"}).json()["id"]
        pid = c.post("/paragraphs/", json={"book_id": bid, "index": 0, "text": "x"}).json()["id"]
        eid = c.post("/tts_edits/", json={"paragraph_id": pid, "edited_text": "e"}).json()["id"]
        return eid

    def test_create_quality(self, client):
        eid = self._quality_payload(client)
        r = client.post("/qualities/", json={"tts_edit_id": eid, "score": 0.9})
        assert r.status_code == 201

    def test_list_qualities(self, client):
        eid = self._quality_payload(client)
        client.post("/qualities/", json={"tts_edit_id": eid, "score": 0.9})
        r = client.get("/qualities/")
        assert r.status_code == 200

    def test_get_quality(self, client):
        eid = self._quality_payload(client)
        qid = client.post("/qualities/", json={"tts_edit_id": eid, "score": 0.9}).json()["id"]
        r = client.get(f"/qualities/{qid}")
        assert r.status_code == 200

    def test_delete_quality(self, client):
        eid = self._quality_payload(client)
        qid = client.post("/qualities/", json={"tts_edit_id": eid, "score": 0.9}).json()["id"]
        r = client.delete(f"/qualities/{qid}")
        assert r.status_code == 204
