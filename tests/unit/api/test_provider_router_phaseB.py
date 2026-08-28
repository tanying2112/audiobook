"""Phase B tests for provider_router CRUD endpoints.

These exercises were previously uncovered: every provider/model CRUD handler
body (create/list/get/update/delete), the hot-reload endpoint, and the
trigger_router_reload happy path. DB access is mocked with a lightweight
async fake so no real database is required.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import NoResultFound
from unittest.mock import AsyncMock

from src.audiobook_studio.api import provider_router as pr
from src.audiobook_studio.schemas.provider import (
    ModelCreate,
    ModelOut,
    ModelUpdate,
    ProviderCreate,
    ProviderOut,
    ProviderUpdate,
)
from src.audiobook_studio.exceptions import DomainError


class FakeResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        if not self.rows:
            raise NoResultFound()
        return self.rows[0]


class FakeDB:
    def __init__(self, results):
        self._results = list(results)
        self._idx = 0
        self.added = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, stmt):
        if self._idx >= len(self._results):
            return FakeResult([])
        r = self._results[self._idx]
        self._idx += 1
        return r

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        # Simulate DB-populated auto-increment primary key.
        if getattr(obj, "id", None) is None:
            obj.id = 1
        self.refreshed.append(obj)

    def add(self, obj):
        self.added.append(obj)


def _provider(name="openai-1", pid=1, **kw):
    attrs = dict(
        id=pid,
        name=name,
        display_name="OpenAI",
        description="x",
        provider_type="openai",
        api_base="https://api.openai.com",
        api_key="sk-test",
        auth_type="bearer",
        default_model="gpt-4o",
        max_tokens=4000,
        temperature=0.1,
        is_enabled=True,
        sort_priority=100,
        created_by="tester",
    )
    attrs.update(kw)
    return type("Provider", (), attrs)()


def _model(name="gpt-4o", mid=1, pid=1, **kw):
    attrs = dict(
        id=mid,
        name=name,
        provider_id=pid,
        model_id="gpt-4o",
        version="v1",
        context_window=128000,
        instructions=None,
        parameters=None,
        is_enabled=True,
        sort_priority=100,
    )
    attrs.update(kw)
    return type("Model", (), attrs)()


@pytest.fixture(autouse=True)
def _patch_router_bridge(monkeypatch):
    # Avoid mutating the global LLM router during tests.
    monkeypatch.setattr(pr, "sync_router_from_db", AsyncMock())
    monkeypatch.setattr(pr, "reload_llm_router", lambda: None)


# ── Provider CRUD ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_provider():
    db = FakeDB([FakeResult([])])
    payload = ProviderCreate(name="prov-a", provider_type="openai", api_key="k")
    res = await pr.create_provider(payload, db=db)
    assert res.name == "prov-a"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_create_provider_duplicate_raises():
    db = FakeDB([FakeResult([_provider(name="prov-a")])])
    payload = ProviderCreate(name="prov-a", provider_type="openai")
    with pytest.raises(DomainError):
        await pr.create_provider(payload, db=db)


@pytest.mark.asyncio
async def test_list_providers():
    db = FakeDB([FakeResult([_provider()]), FakeResult([_model()])])
    res = await pr.list_providers(db=db)
    assert res.total == 1
    assert res.providers[0].model_count == 1
    assert isinstance(res.providers[0], ProviderOut)


@pytest.mark.asyncio
async def test_get_provider_found():
    db = FakeDB([FakeResult([_provider()])])
    res = await pr.get_provider(1, db=db)
    assert res.id == 1


@pytest.mark.asyncio
async def test_get_provider_not_found():
    db = FakeDB([FakeResult([])])
    with pytest.raises(DomainError):
        await pr.get_provider(999, db=db)


@pytest.mark.asyncio
async def test_update_provider_found():
    db = FakeDB([FakeResult([_provider()])])
    payload = ProviderUpdate(display_name="New Name")
    res = await pr.update_provider(1, payload, db=db)
    assert res.display_name == "New Name"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_update_provider_not_found():
    db = FakeDB([FakeResult([])])
    payload = ProviderUpdate(display_name="x")
    with pytest.raises(DomainError):
        await pr.update_provider(999, payload, db=db)


@pytest.mark.asyncio
async def test_delete_provider_with_models_soft_delete():
    db = FakeDB([FakeResult([_model(), _model(name="m2", mid=2)]), FakeResult([_provider()])])
    await pr.delete_provider(1, db=db)
    assert db.commits == 1


@pytest.mark.asyncio
async def test_delete_provider_no_models_hard_delete():
    db = FakeDB([FakeResult([])])
    await pr.delete_provider(1, db=db)
    assert db.commits == 1


# ── Model CRUD ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_model():
    db = FakeDB([FakeResult([_provider()]), FakeResult([])])
    payload = ModelCreate(name="m1", provider_id=1, model_id="gpt-4o")
    res = await pr.create_model(1, payload, db=db)
    assert res.name == "m1"
    assert res.provider_name == "openai-1"
    assert isinstance(res, ModelOut)


@pytest.mark.asyncio
async def test_create_model_provider_not_found():
    db = FakeDB([FakeResult([])])
    payload = ModelCreate(name="m1", provider_id=1)
    with pytest.raises(DomainError):
        await pr.create_model(1, payload, db=db)


@pytest.mark.asyncio
async def test_create_model_duplicate_name():
    db = FakeDB([FakeResult([_provider()]), FakeResult([_model()])])
    payload = ModelCreate(name="gpt-4o", provider_id=1)
    with pytest.raises(DomainError):
        await pr.create_model(1, payload, db=db)


@pytest.mark.asyncio
async def test_list_models():
    db = FakeDB([FakeResult([_provider()]), FakeResult([_model(), _model(name="m2", mid=2)])])
    res = await pr.list_models(1, db=db)
    assert res.total == 2
    assert res.provider_name == "openai-1"


@pytest.mark.asyncio
async def test_list_models_provider_not_found():
    db = FakeDB([FakeResult([])])
    with pytest.raises(DomainError):
        await pr.list_models(1, db=db)


@pytest.mark.asyncio
async def test_get_model_found():
    db = FakeDB([FakeResult([_model()]), FakeResult([_provider()])])
    res = await pr.get_model(1, 1, db=db)
    assert res.id == 1
    assert res.provider_name == "openai-1"


@pytest.mark.asyncio
async def test_get_model_not_found():
    db = FakeDB([FakeResult([])])
    with pytest.raises(DomainError):
        await pr.get_model(1, 999, db=db)


@pytest.mark.asyncio
async def test_update_model_found():
    db = FakeDB([FakeResult([_model()]), FakeResult([_provider()])])
    payload = ModelUpdate(context_window=64000)
    res = await pr.update_model(1, 1, payload, db=db)
    assert res.context_window == 64000


@pytest.mark.asyncio
async def test_update_model_not_found():
    db = FakeDB([FakeResult([])])
    payload = ModelUpdate(context_window=1)
    with pytest.raises(DomainError):
        await pr.update_model(1, 999, payload, db=db)


@pytest.mark.asyncio
async def test_update_model_name_conflict():
    # model found, conflict exists for the new name
    db = FakeDB([FakeResult([_model(name="m1", mid=1)]), FakeResult([_model(name="m2", mid=2)]), FakeResult([_provider()])])
    payload = ModelUpdate(name="m2")
    with pytest.raises(DomainError):
        await pr.update_model(1, 1, payload, db=db)


@pytest.mark.asyncio
async def test_delete_model_found():
    db = FakeDB([FakeResult([_model()])])
    await pr.delete_model(1, 1, db=db)
    assert db.commits == 1


@pytest.mark.asyncio
async def test_delete_model_not_found():
    db = FakeDB([FakeResult([])])
    res = await pr.delete_model(1, 999, db=db)
    assert res is None


# ── Hot reload ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reload_providers():
    db = FakeDB([])
    res = await pr.reload_providers(db=db)
    assert res["db_sync"] == "ok"
    assert res["yaml_reload"] == "ok"


def test_trigger_router_reload_happy(monkeypatch):
    called = {}
    monkeypatch.setattr(pr, "reload_llm_router", lambda: called.setdefault("ran", True))
    pr.trigger_router_reload()
    assert called.get("ran") is True
