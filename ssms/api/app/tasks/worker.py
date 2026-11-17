"""Celery application. Start with:  celery -A app.tasks.worker worker -l info

Each task runs its async handler in a fresh event loop with NullPool connections (use_worker_mode), retries
transient failures with exponential backoff and jitter, and is acknowledged only after it finishes.
"""

import asyncio
import sys

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.db.session import use_worker_mode
from app.services.gepg import GatewayUnavailable
from app.services.sms import TransientSmsError
from app.tasks.handlers import HANDLERS

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

RETRYABLE = (TransientSmsError, GatewayUnavailable, OperationalError, ConnectionError, TimeoutError)

settings = get_settings()
celery_app = Celery("ssms", broker=settings.celery_broker_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_always_eager=settings.celery_eager,
    broker_connection_retry_on_startup=True,
    task_time_limit=900,
    task_soft_time_limit=840,
    timezone="Africa/Dar_es_Salaam",
    beat_schedule={
        "fee-reminders": {"task": "reminders.fanout", "schedule": crontab(hour=9, minute=0)},
        "library-overdue": {"task": "library.fanout", "schedule": crontab(hour=10, minute=0, day_of_week="mon-fri")},
        "absence-alerts": {
            "task": "absence.fanout",
            "schedule": crontab(minute="*/5", hour="8-12", day_of_week="mon-sat"),
        },
    },
)


@worker_process_init.connect
def _init_worker(**_kwargs) -> None:
    use_worker_mode()


def _register(name: str, handler) -> None:
    @celery_app.task(
        name=name, autoretry_for=RETRYABLE, retry_backoff=True, retry_backoff_max=600, retry_jitter=True, max_retries=6
    )
    def run(**kwargs):
        return asyncio.run(handler(**kwargs))


for _name, _handler in HANDLERS.items():
    _register(_name, _handler)
