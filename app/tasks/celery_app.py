"""Celery-приложение для фоновых задач PulseWatch."""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "pulsewatch",
    broker=f"redis://{settings.redis_host}:{settings.redis_port}/1",
    backend=f"redis://{settings.redis_host}:{settings.redis_port}/2",
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "aggregate-hourly": {
            "task": "app.tasks.aggregation_tasks.task_aggregate_hourly",
            "schedule": 3600.0,  # каждый час
        },
        "aggregate-daily": {
            "task": "app.tasks.aggregation_tasks.task_aggregate_daily",
            "schedule": 86400.0,  # каждый день
        },
        "check-heartbeat": {
            "task": "app.tasks.heartbeat_tasks.task_check_heartbeat",
            "schedule": 60.0,  # каждую минуту
        },
    },
)

celery_app.autodiscover_tasks(["app.tasks"])
