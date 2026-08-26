"""Helpers for driving coroutines from synchronous code.

The key helper, :func:`run_sync`, runs an async coroutine to completion while
remaining safe to call from *inside* a running event loop (e.g. from within a
``run_until_complete``-driven pipeline) and from any test harness.

The original ``asyncio.run``-based implementation raised
``RuntimeError: asyncio.run() cannot be called from a running event loop`` when
invoked re-entrantly, which broke synchronous convenience wrappers such as
``get_duration_sync`` whenever they were called from async TTS/export paths.
:func:`run_sync` instead drives the coroutine in a dedicated worker thread with
its own fresh event loop. Because it never touches the caller's event loop (it
does not call ``asyncio.run`` / ``set_event_loop`` / ``get_running_loop`` on the
calling thread), it is also safe under pytest-asyncio's strict loop policy: a
sync test that calls :func:`run_sync` cannot accidentally unset the main-thread
loop that later event-loop lookups rely on.
"""

from __future__ import annotations

import asyncio
import threading


def run_sync(coro) -> Any:  # noqa: ANN001
    """Run ``coro`` to completion and return its result.

    The coroutine is executed in a dedicated worker thread that owns a brand-new
    event loop, so:

    * It works even when a loop is already running in the calling thread
      (no ``asyncio.run() cannot be called from a running event loop`` error).
    * It never mutates the calling thread's event-loop state, so it composes
      safely with pytest-asyncio and other loop managers.

    Exceptions raised by ``coro`` are propagated to the caller.
    """
    store: dict = {}
    errors: list = []

    def _worker() -> None:
        loop = asyncio.new_event_loop()
        try:
            store["value"] = loop.run_until_complete(coro)
        except BaseException as exc:  # noqa: BLE001 - propagate to caller
            errors.append(exc)
        finally:
            loop.close()

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    worker.join()

    if errors:
        raise errors[0]
    return store["value"]
