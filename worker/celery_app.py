import os
from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

app = Celery("pipeline", broker=REDIS_URL, backend=REDIS_URL)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=int(os.environ.get("PIPELINE_TASK_TIME_LIMIT", 6 * 3600)),
    task_soft_time_limit=int(os.environ.get("PIPELINE_TASK_SOFT_TIME_LIMIT", 6 * 3600 - 300)),
)
