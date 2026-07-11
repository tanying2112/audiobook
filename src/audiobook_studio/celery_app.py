"""
Celery configuration for Audiobook Studio.

Configures Redis broker/result backend and task routing.
"""

import os
from celery import Celery
from celery.schedules import crontab

# Redis connection
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Create Celery app
celery_app = Celery(
    "audiobook_studio",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "src.audiobook_studio.tasks.export_tasks",
        "src.audiobook_studio.tasks.tts_tasks",
    ],
)

# Configuration
celery_app.conf.update(
    # Task routing
    task_routes={
        "src.audiobook_studio.tasks.export_tasks.export_project_async": {"queue": "export"},
        "src.audiobook_studio.tasks.export_tasks.export_chapter_async": {"queue": "export"},
        "src.audiobook_studio.tasks.pipeline_tasks.*": {"queue": "pipeline"},
        "src.audiobook_studio.tasks.tts_tasks.synthesize_chapter_task": {"queue": "pipeline"},
        "src.audiobook_studio.tasks.tts_tasks.resume_chapter_task": {"queue": "pipeline"},
    },
    # Task serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="Asia/Shanghai",
    enable_utc=True,
    # Result backend
    result_expires=3600,  # 1 hour
    # Worker
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=100,
    # Task acknowledgment
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Beat schedule (for periodic tasks if needed)
    beat_schedule={},
)

# Auto-discover tasks
celery_app.autodiscover_tasks([
    "src.audiobook_studio.tasks",
])

# Health check task
@celery_app.task(bind=True)
def health_check(self):
    """Health check task."""
    return {"status": "healthy", "worker": self.request.hostname}
