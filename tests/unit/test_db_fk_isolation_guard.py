"""Regression guard for the harness FK=ON class-listener leak (TEST-ISOLATION).

Root cause (see the comment block in ``tests/conftest.py``): harness/storage.py
registers ``event.listens_for(Engine, "connect")`` with ``PRAGMA foreign_keys=ON``
on the *Engine class*, so every SQLite connection opened anywhere in the process
gets FK=ON once any harness test has run. The 14 DB/API tests assume the default
FK=OFF and only fail under full-suite ordering (harness collected before them).

This guard reproduces that leak *locally and self-cleaning* and asserts the shared
``set_sqlite_fk_off`` instance listener (the fix, used by conftest +
test_database_phaseB.py + test_db_optimization.py) restores FK=OFF and lets ``DROP``
proceed through a FK cycle. It does NOT depend on harness collection order, so if the
leak behavior changes or the helper is removed, these tests fail and catch the
regression directly. (TEST-ISOLATION ONLY — no production code is touched.)
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from tests.conftest import set_sqlite_fk_off


def _leak_fk_on(dbapi_connection, connection_record):
    """Stand-in for the harness class-level ``PRAGMA foreign_keys=ON`` listener."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        pass


@pytest.fixture
def _leaked_engine():
    """An engine whose connections are hit by the simulated harness leak.

    The leak is registered on the Engine *class* (process-wide, mirroring storage.py)
    and removed in teardown so it never pollutes the rest of the suite.
    """
    event.listen(Engine, "connect", _leak_fk_on)
    eng = create_engine("sqlite:///:memory:")
    yield eng
    event.remove(Engine, "connect", _leak_fk_on)
    eng.dispose()


def test_instance_listener_overrides_class_fk_on_leak(_leaked_engine):
    # The fix attaches an *instance* listener that fires AFTER the class listener,
    # restoring FK=OFF. Without it, ``PRAGMA foreign_keys`` would read 1 here.
    event.listen(_leaked_engine, "connect", set_sqlite_fk_off)
    with _leaked_engine.connect() as conn:
        val = conn.execute(text("PRAGMA foreign_keys")).scalar()
    assert val == 0


def test_fk_off_allows_drop_through_fk_cycle(tmp_path, _leaked_engine):
    # Mirror the phaseB FK cycle (parents <-> children <-> parents2). With FK=OFF the
    # cycle must not block DROP; with the helper registered BEFORE any connection is
    # opened, drop_all-style DROPs succeed in any order.
    db_file = Path(tmp_path) / "guard.db"
    eng = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", set_sqlite_fk_off)  # register BEFORE any connection
    try:
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE parents (id INTEGER PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE children (id INTEGER PRIMARY KEY, pid INTEGER REFERENCES parents(id))"))
            conn.execute(text("CREATE TABLE parents2 (id INTEGER PRIMARY KEY, cid INTEGER REFERENCES children(id))"))
        with eng.begin() as conn:
            conn.execute(text("DROP TABLE parents2"))
            conn.execute(text("DROP TABLE children"))
            conn.execute(text("DROP TABLE parents"))
    finally:
        eng.dispose()
