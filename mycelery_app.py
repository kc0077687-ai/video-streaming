# mycelery_app.py
from celery import Celery
from config import settings

celery = Celery(
    "video_tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)

import tasks