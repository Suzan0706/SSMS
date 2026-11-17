"""Hand work to Celery only after the database transaction that created it has committed.

Production uses CeleryDispatcher. Development and E2E runs without Redis use InlineDispatcher
(SSMS_TASKS_INLINE=true, refused in production). Tests install RecordingDispatcher and run the handlers
explicitly, so a test sees exactly which jobs were queued and with what arguments.
"""

import asyncio
import logging
from typing import Protocol

from app.core.config import get_settings

log = logging.getLogger(__name__)


class Dispatcher(Protocol):
    def send(self, name: str, **kwargs) -> None: ...


class CeleryDispatcher:
    def send(self, name: str, **kwargs) -> None:
        from app.tasks.worker import celery_app

        celery_app.send_task(name, kwargs=kwargs)


class InlineDispatcher:
    """Runs the handler as a background asyncio task of the API process (no retries, no persistence)."""

    def __init__(self):
        self._running: set[asyncio.Task] = set()

    def send(self, name: str, **kwargs) -> None:
        from app.tasks.handlers import HANDLERS

        task = asyncio.get_running_loop().create_task(HANDLERS[name](**kwargs))
        self._running.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task) -> None:
        self._running.discard(task)
        if not task.cancelled() and task.exception():
            log.error("inline task failed", exc_info=task.exception())


class RecordingDispatcher:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    def send(self, name: str, **kwargs) -> None:
        self.sent.append((name, kwargs))

    def take(self, name: str) -> list[dict]:
        """Remove and return the queued calls of one task."""
        taken = [kw for n, kw in self.sent if n == name]
        self.sent = [(n, kw) for n, kw in self.sent if n != name]
        return taken


_dispatcher: Dispatcher | None = None


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = InlineDispatcher() if get_settings().tasks_inline else CeleryDispatcher()
    return _dispatcher


def set_dispatcher(dispatcher: Dispatcher) -> None:
    global _dispatcher
    _dispatcher = dispatcher
