"""
Celery configuration for document ingestion batch processing.

Feature 011: Document Ingestion & Batch Processing
T003: Configure Celery + Redis broker/backend

This configuration sets up:
- Redis as broker and result backend
- Ingestion queue for processing tasks
- Fair task distribution via prefetch multiplier
- Task acknowledgment after completion (retry on worker crash)
"""

from celery import Celery

# Celery instance
app = Celery('gov_ai_ingestion')

# Broker and Result Backend Configuration
app.conf.broker_url = 'redis://localhost:6379/0'
app.conf.result_backend = 'redis://localhost:6379/0'

# Task Routing
app.conf.task_routes = {
    'ingestion.*': {'queue': 'ingestion'},
}

# Worker Configuration
app.conf.worker_prefetch_multiplier = 1  # Fair distribution across workers
app.conf.task_acks_late = True  # Retry on worker crash

# Task Time Limits
app.conf.task_soft_time_limit = 3600  # 1 hour soft limit
app.conf.task_time_limit = 7200  # 2 hour hard limit

# Result Backend Settings
app.conf.result_expires = 86400  # Results expire after 24 hours

# Task Serialization
app.conf.task_serializer = 'json'
app.conf.result_serializer = 'json'
app.conf.accept_content = ['json']
app.conf.timezone = 'UTC'
app.conf.enable_utc = True

# Task Discovery
app.conf.imports = (
    'backend.src.services.batch_processor',
)

if __name__ == '__main__':
    app.start()
