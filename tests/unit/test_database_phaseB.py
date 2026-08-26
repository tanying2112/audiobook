"""Phase B structural tests for database.py (config/routing, in-memory sqlite)."""

import asyncio

import pytest

from sqlalchemy import select, text

from src.audiobook_studio.database import (
    AsyncSessionLocal,
    DatabaseConfig,
    ReadReplicaSelector,
    RoutedEngine,
    RoutedSession,
    _get_async_database_url,
    _get_sync_database_url,
    close_routed_engine,
    create_async_session,
    drop_async_db,
    get_async_engine,
    get_async_session,
    get_async_session_factory,
    get_db,
    get_routed_engine,
    get_routed_session,
    get_routed_session_factory,
    get_sync_engine_url,
    init_async_db,
    init_db,
    init_routed_engine,
)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def test_sync_database_url_conversions(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:////tmp/a.db")
    assert _get_sync_database_url() == "sqlite:////tmp/a.db"

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u/p")
    assert _get_sync_database_url() == "postgresql://u/p"

    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/b.db")
    assert _get_sync_database_url() == "sqlite:////tmp/b.db"

    # no async driver prefix -> returned unchanged (line 38)
    monkeypatch.setenv("DATABASE_URL", "mysql://u/p")
    assert _get_sync_database_url() == "mysql://u/p"

    # sqlite+aiosqlite:// without the third slash -> second branch (lines 34-35)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://x.db")
    assert _get_sync_database_url() == "sqlite://x.db"


def test_get_sync_engine_url_returns_string():
    assert isinstance(get_sync_engine_url(), str)


def test_to_async_url_static():
    assert RoutedEngine._to_async_url("sqlite:///x") == "sqlite+aiosqlite:///x"
    assert RoutedEngine._to_async_url("sqlite://x") == "sqlite+aiosqlite://x"
    assert RoutedEngine._to_async_url("postgresql://u") == "postgresql+asyncpg://u"
    assert RoutedEngine._to_async_url("postgresql+psycopg2://u") == "postgresql+asyncpg://u"
    assert RoutedEngine._to_async_url("mysql://u") == "mysql://u"


# ---------------------------------------------------------------------------
# DatabaseConfig
# ---------------------------------------------------------------------------


def test_database_config_routing_enabled():
    cfg = DatabaseConfig("sqlite:///:memory:", replica_urls=["sqlite:///:memory:"])
    assert cfg.enable_routing is True


def test_database_config_routing_disabled_no_replicas():
    cfg = DatabaseConfig("sqlite:///:memory:", replica_urls=[])
    assert cfg.enable_routing is False


def test_database_config_routing_disabled_explicit():
    cfg = DatabaseConfig("sqlite:///:memory:", replica_urls=["sqlite:///:memory:"], enable_routing=False)
    assert cfg.enable_routing is False


# ---------------------------------------------------------------------------
# ReadReplicaSelector
# ---------------------------------------------------------------------------


def test_read_replica_round_robin():
    sel = ReadReplicaSelector(["a", "b"])
    assert sel.get_replica() == "a"
    assert sel.get_replica() == "b"
    assert sel.get_replica() == "a"


def test_read_replica_empty_raises():
    sel = ReadReplicaSelector([])
    with pytest.raises(ValueError):
        sel.get_replica()
    with pytest.raises(ValueError):
        sel.get_random_replica()


def test_read_replica_random_returns_member():
    sel = ReadReplicaSelector(["a", "b", "c"])
    assert sel.get_random_replica() in ("a", "b", "c")


# ---------------------------------------------------------------------------
# RoutedEngine (in-memory sqlite)
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def test_routed_engine_initialize_and_routing():
    cfg = DatabaseConfig("sqlite:///:memory:", replica_urls=["sqlite:///:memory:"])
    re = RoutedEngine(cfg)
    _run(re.initialize())
    try:
        assert re.primary_engine is not None
        # routing enabled -> returns a replica engine (not primary object identity)
        replica = re.get_replica_engine()
        assert replica is not None
    finally:
        _run(re.close())
    assert re._primary_engine is None


def test_routed_engine_fallback_without_replicas():
    cfg = DatabaseConfig("sqlite:///:memory:", replica_urls=[])
    re = RoutedEngine(cfg)
    _run(re.initialize())
    try:
        # no routing -> get_replica_engine returns primary
        assert re.get_replica_engine() is re.primary_engine
    finally:
        _run(re.close())


def test_routed_engine_primary_before_init_raises():
    re = RoutedEngine(DatabaseConfig("sqlite:///:memory:"))
    with pytest.raises(RuntimeError):
        _ = re.primary_engine


# ---------------------------------------------------------------------------
# RoutedSession toggle
# ---------------------------------------------------------------------------


def test_routed_session_enable_disable():
    cfg = DatabaseConfig("sqlite:///:memory:", replica_urls=["sqlite:///:memory:"])
    re = RoutedEngine(cfg)
    _run(re.initialize())
    try:
        sess = RoutedSession(re)
        assert sess._use_replica is False
        assert sess.enable_replica()._use_replica is True
        assert sess._should_use_replica() is True
        assert sess.disable_replica()._use_replica is False
    finally:
        _run(re.close())


# ---------------------------------------------------------------------------
# Async engine / session factory (sqlite)
# ---------------------------------------------------------------------------


def test_async_engine_and_session():
    eng = get_async_engine()
    assert eng is not None
    factory = get_async_session_factory()
    assert factory is not None
    sess = create_async_session()
    assert sess is not None
    _run(sess.close())
    _run(eng.dispose())


def test_get_async_database_url(monkeypatch):
    monkeypatch.setattr(
        "src.audiobook_studio.database.DATABASE_URL", "sqlite:////tmp/a.db"
    )
    assert _get_async_database_url() == "sqlite+aiosqlite:////tmp/a.db"
    # sqlite:// without the third slash -> second branch (lines 100-101)
    monkeypatch.setattr(
        "src.audiobook_studio.database.DATABASE_URL", "sqlite://x.db"
    )
    assert _get_async_database_url() == "sqlite+aiosqlite://x.db"
    monkeypatch.setattr(
        "src.audiobook_studio.database.DATABASE_URL", "postgresql://u/p"
    )
    assert _get_async_database_url() == "postgresql+asyncpg://u/p"
    monkeypatch.setattr(
        "src.audiobook_studio.database.DATABASE_URL", "postgresql+psycopg2://u/p"
    )
    assert _get_async_database_url() == "postgresql+asyncpg://u/p"
    monkeypatch.setattr(
        "src.audiobook_studio.database.DATABASE_URL", "mysql://u/p"
    )
    assert _get_async_database_url() == "mysql://u/p"


def test_get_routed_engine_and_session_factory():
    re = get_routed_engine()
    # NOTE: test_database.py imports the module as a top-level `database`,
    # causing a double-load; compare by name to stay robust to import aliasing.
    assert type(re).__name__ == "RoutedEngine"
    factory = get_routed_session_factory()
    assert factory is not None
    _run(re.close())


def test_get_db_generator():
    gen = get_db()
    db = next(gen)
    assert db is not None
    with pytest.raises(StopIteration):
        next(gen)
    db.close()


def test_routed_session_execute_routing():
    async def go():
        cfg = DatabaseConfig(
            "sqlite:///:memory:", replica_urls=["sqlite:///:memory:"], enable_routing=True
        )
        re = RoutedEngine(cfg)
        await re.initialize()
        sess = RoutedSession(re)
        # primary path (replica disabled)
        r1 = await sess.execute(text("SELECT 1"))
        assert r1.scalar() is not None
        # replica path (Select + routing enabled)
        sess.enable_replica()
        assert sess._should_use_replica() is True
        r2 = await sess.execute(select(1))
        assert r2.scalar() == 1
        await re.close()

    _run(go())


def test_routed_and_async_session_generators():
    async def go():
        await init_routed_engine()
        async for s in get_routed_session():
            assert s is not None
            break
        await close_routed_engine()

        async for s in get_async_session():
            assert s is not None
            break

    _run(go())


def test_close_routed_engine_noop_when_uninitialized():
    async def go():
        # Ensure global is cleared so the `if _routed_engine:` guard is False
        import src.audiobook_studio.database as db_mod

        db_mod._routed_engine = None
        await close_routed_engine()  # must not raise

    _run(go())


# ---------------------------------------------------------------------------
# Slow-query logger, init/drop, AsyncSessionLocal, full generator consumption
# ---------------------------------------------------------------------------


def test_slow_query_logger_callbacks_fire_on_query():
    # Executing a query through the cached async engine fires the installed
    # before/after_cursor_execute listeners (covers the callback bodies).
    import src.audiobook_studio.database as db_mod

    async def go():
        eng = db_mod.get_async_engine()
        assert eng is not None
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))

    _run(go())


def test_slow_query_logger_disabled_when_threshold_zero(monkeypatch):
    monkeypatch.setenv("SLOW_QUERY_MS", "0")
    import src.audiobook_studio.database as db_mod

    monkeypatch.setattr(db_mod, "_async_engine", None)
    monkeypatch.setattr(db_mod, "_async_session_factory", None)

    eng = db_mod.get_async_engine()  # early return at threshold <= 0
    assert eng is not None


def test_init_and_drop_async_db(tmp_path, monkeypatch):
    import src.audiobook_studio.database as db_mod

    db_file = tmp_path / "phaseb_tmp.db"
    monkeypatch.setattr(
        db_mod, "DATABASE_URL", f"sqlite+aiosqlite:///{db_file}"
    )
    monkeypatch.setattr(db_mod, "_async_engine", None)
    monkeypatch.setattr(db_mod, "_async_session_factory", None)

    async def go():
        await init_async_db()
        await drop_async_db()

    _run(go())


def test_init_db_sync_creates_tables():
    init_db()  # create_all on the default engine; must not raise


def test_async_session_local_context_manager():
    async def go():
        async with AsyncSessionLocal() as sess:
            assert sess is not None
        # exception path -> rollback branch in __aexit__
        with pytest.raises(RuntimeError):
            async with AsyncSessionLocal() as sess2:
                raise RuntimeError("boom")

    _run(go())


def test_generators_full_consumption():
    # Consume generators to completion (no break) so commit/close finally
    # blocks execute.
    async def go():
        await init_routed_engine()
        async for s in get_routed_session():
            assert s is not None
        await close_routed_engine()

        async for s in get_async_session():
            assert s is not None

    _run(go())


def test_get_async_session_routing_branch(monkeypatch):
    monkeypatch.setenv("ENABLE_READ_REPLICA", "true")
    monkeypatch.setenv("DATABASE_REPLICA_URLS", "sqlite:///:memory:")

    async def go():
        await init_routed_engine()
        async for s in get_async_session():  # delegates to get_routed_session
            assert s is not None
        await close_routed_engine()

    _run(go())
