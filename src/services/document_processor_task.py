"""
Document processor Celery task for processing queued documents.

Feature 019: Process All Cross-Government Guidance Documents
CRITICAL: Adapted to work with production processing_queue table schema

Production schema: processing_queue (id, document_id, url, status, priority, attempt_count)
"""

import logging
from datetime import datetime
from typing import Dict
from celery import Task
from sqlalchemy import text

from celery_config import app
from src.database import SessionLocal

logger = logging.getLogger(__name__)


@app.task(bind=True, name='process_document', max_retries=3, default_retry_delay=60)
def process_document_task(self: Task, queue_id: int) -> Dict:
    """
    Process a single document from the processing_queue table.

    Args:
        queue_id: ID from processing_queue table (integer primary key)

    Returns:
        Dict with status and details
    """
    db = SessionLocal()

    try:
        # Get queue record using raw SQL (production schema)
        result = db.execute(
            text("SELECT id, document_id, url, status, attempt_count FROM processing_queue WHERE id = :id"),
            {"id": queue_id}
        )
        queue_row = result.fetchone()

        if not queue_row:
            logger.error(f"Queue record not found: {queue_id}")
            return {"status": "failed", "error": "Queue record not found"}

        queue_id, doc_id, url, status, attempt_count = queue_row

        # Update status to 'processing'
        db.execute(
            text("UPDATE processing_queue SET status = 'processing', last_attempt_at = NOW(), attempt_count = attempt_count + 1 WHERE id = :id"),
            {"id": queue_id}
        )
        db.commit()

        # Get document from documents table
        # NOTE: doc_id from processing_queue is document_id (UUID string), not id (integer PK)
        doc_result = db.execute(
            text("SELECT id, document_id, content FROM documents WHERE document_id = :document_id"),
            {"document_id": doc_id}
        )
        doc_row = doc_result.fetchone()

        if not doc_row:
            logger.error(f"Document not found: {doc_id}")
            db.execute(
                text("UPDATE processing_queue SET status = 'failed', error_message = 'Document not found' WHERE id = :id"),
                {"id": queue_id}
            )
            db.commit()
            return {"status": "failed", "error": "Document not found"}

        doc_pk, doc_uuid, content = doc_row

        if not content:
            logger.error(f"Document has no content: {doc_id}")
            db.execute(
                text("UPDATE processing_queue SET status = 'failed', error_message = 'No content' WHERE id = :id"),
                {"id": queue_id}
            )
            db.commit()
            return {"status": "failed", "error": "No content"}

        logger.info(f"Processing document {doc_id} (queue {queue_id}, URL: {url[:100]})")

        # Import processing dependencies (deferred to avoid circular imports)
        from src.services.chrome_stripper import ChromeStripper
        from src.services.file_processor import FileProcessorService
        import asyncio

        # Apply chrome stripping
        chrome_stripper = ChromeStripper()
        cleaned_content, chrome_stats = chrome_stripper.strip_chrome(
            html=content,
            document_id=doc_uuid
        )

        # Process document through file processor
        file_processor = FileProcessorService(chunk_size_tokens=512)

        file_data = {
            'filename': f"{doc_uuid}.html",
            'content': cleaned_content.encode('utf-8'),
            'content_type': 'text/html'
        }

        # Run async processing in new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            file_processor._process_single_file(file_data, chunk_size_tokens=512)
        )
        loop.close()

        if isinstance(result, Exception):
            raise result

        # Update document
        # NOTE: Use doc_pk (integer PK), not doc_id (UUID string)
        db.execute(
            text("""
                UPDATE documents
                SET processing_success = true,
                    processed_at = NOW(),
                    chunk_count = :chunk_count
                WHERE id = :id
            """),
            {"chunk_count": result.get('chunk_count', 0), "id": doc_pk}
        )

        # Update queue status to completed
        db.execute(
            text("UPDATE processing_queue SET status = 'completed' WHERE id = :id"),
            {"id": queue_id}
        )

        db.commit()

        logger.info(
            f"Document processed successfully: doc_id={doc_id}, chunks={result.get('chunk_count', 0)}, "
            f"chrome_removed={chrome_stats.get('chrome_percentage', 0):.1f}%"
        )

        return {
            "status": "completed",
            "document_id": doc_id,
            "chunks_created": result.get('chunk_count', 0),
            "chrome_stats": chrome_stats
        }

    except Exception as e:
        logger.error(f"Failed to process document: {e}", exc_info=True)

        # Update queue with failure
        try:
            db.execute(
                text("UPDATE processing_queue SET status = 'failed', error_message = :error WHERE id = :id"),
                {"error": str(e)[:500], "id": queue_id}
            )
            db.commit()
        except:
            pass

        # Retry on transient errors
        if "connection" in str(e).lower() or "timeout" in str(e).lower():
            raise self.retry(exc=e)

        return {"status": "failed", "error": str(e)}

    finally:
        db.close()


@app.task(name='poll_processing_queue')
def poll_processing_queue_task() -> Dict:
    """
    Poll processing_queue table for 'pending' jobs and dispatch to workers.

    Runs every 30 seconds via Celery beat scheduler.

    Returns:
        Dict with jobs_found, jobs_dispatched
    """
    db = SessionLocal()

    try:
        # Query for pending jobs (production schema)
        result = db.execute(
            text("""
                SELECT id, document_id, url
                FROM processing_queue
                WHERE status = 'pending'
                ORDER BY priority DESC, id ASC
                LIMIT 100
            """)
        )
        pending_jobs = result.fetchall()

        jobs_found = len(pending_jobs)
        jobs_dispatched = 0

        logger.info(f"Polling queue: found {jobs_found} pending jobs")

        for job in pending_jobs:
            queue_id, doc_id, url = job

            # Dispatch to worker
            process_document_task.delay(queue_id)
            jobs_dispatched += 1

            logger.info(f"Dispatched queue_id={queue_id}, document_id={doc_id}, url={url[:100]}")

        return {
            "jobs_found": jobs_found,
            "jobs_dispatched": jobs_dispatched
        }

    except Exception as e:
        logger.error(f"Failed to poll processing queue: {e}", exc_info=True)
        return {"error": str(e)}

    finally:
        db.close()
