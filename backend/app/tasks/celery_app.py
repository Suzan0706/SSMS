from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("sms", broker=settings.redis_url, backend=settings.redis_url,
                    include=["app.tasks.notifications", "app.tasks.payments"])
celery_app.conf.update(
    timezone="Africa/Dar_es_Salaam",
    task_acks_late=True,                      # a crashed worker does not lose the job
    task_reject_on_worker_lost=True,
    task_publish_retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.5},
    beat_schedule={
        "fee-reminders-weekdays-0800": {
            "task": "app.tasks.payments.send_fee_reminders",
            "schedule": crontab(hour=8, minute=0, day_of_week="mon-fri"),
        },
    },
)
