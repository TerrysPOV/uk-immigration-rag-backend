"""
Batch processor service with Celery integration.

Feature 011: Document Ingestion & Batch Processing
T039: Celery task queue with worker distribution, retry logic, and progress tracking
"""

from datetime import datetime
from typing import List, Dict, Optional
from celery import Celery, group
from celery.result import AsyncResult
from sqlalchemy.orm import Session

from src.models.processing_job import ProcessingJob, ProcessingStatus
from src.models.processing_queue import ProcessingQueue, QueuePriority
from src.models.ingestion_job import IngestionJob, IngestionStatus


class BatchProcessorService:
    """
    Service for coordinating batch document processing.

    Features:
    - Celery task queue integration
    - Worker distribution (1-10 workers, FR-029)
    - Retry logic (0-5 retries, FR-030)
    - Progress tracking (FR-038, FR-043)
    - ETA calculation
    - Worker failure handling (FR-035)
    """

    def __init__(self, celery_app: Celery, db_session: Session):
        self.celery = celery_app
        self.db = db_session

    async def start_batch_processing(
        self,
        ingestion_job_id: str,
        document_ids: List[str],
        chunk_size: int = 512,
        parallel_workers: int = 4,
        retry_attempts: int = 3,
    ) -> Dict:
        """
        Start batch processing of documents.

        Args:
            ingestion_job_id: Parent ingestion job ID
            document_ids: List of document IDs to process
            chunk_size: Token count per chunk (FR-028, FR-032)
            parallel_workers: Number of parallel workers (1-10, FR-029)
            retry_attempts: Retry count for failed chunks (0-5, FR-030)

        Returns:
            Dict with:
            - job_id: Ingestion job ID
            - queued_documents: Count of documents queued
            - processing_jobs: List of processing job IDs
            - estimated_duration_seconds: Estimated completion time
        """
        # Validate worker count (FR-029)
        if not (1 <= parallel_workers <= 10):
            raise ValueError("parallel_workers must be between 1 and 10")

        # Validate retry attempts (FR-030)
        if not (0 <= retry_attempts <= 5):
            raise ValueError("retry_attempts must be between 0 and 5")

        # Create processing queue entries
        processing_jobs = []

        for doc_id in document_ids:
            # Create processing job
            processing_job = ProcessingJob(
                processing_job_id=self._generate_job_id(),
                ingestion_job_id=ingestion_job_id,
                document_id=doc_id,
                status=ProcessingStatus.QUEUED,
                progress=0.0,
                retry_count=0,
            )

            self.db.add(processing_job)
            processing_jobs.append(processing_job.processing_job_id)

            # Add to processing queue
            queue_entry = ProcessingQueue(
                queue_id=self._generate_queue_id(),
                ingestion_job_id=ingestion_job_id,
                document_id=doc_id,
                priority=QueuePriority.NORMAL,
            )

            self.db.add(queue_entry)

        self.db.commit()

        # Distribute work across workers using Celery groups (FR-034)
        # Split documents into batches for each worker
        batch_size = len(document_ids) // parallel_workers or 1
        batches = [
            document_ids[i : i + batch_size] for i in range(0, len(document_ids), batch_size)
        ]

        # Create Celery task group
        task_signatures = []
        for batch in batches:
            task_signatures.append(
                self.celery.signature(
                    "process_document_batch", args=[batch, chunk_size, retry_attempts]
                )
            )

        # Execute tasks in parallel
        job = group(task_signatures).apply_async()

        # Estimate duration (simplified: assume 30 seconds per document)
        estimated_duration = len(document_ids) * 30 // parallel_workers

        # Update ingestion job
        ingestion_job = self.db.query(IngestionJob).filter_by(job_id=ingestion_job_id).first()

        if ingestion_job:
            ingestion_job.status = IngestionStatus.IN_PROGRESS
            ingestion_job.total_documents = len(document_ids)
            self.db.commit()

        return {
            "job_id": ingestion_job_id,
            "queued_documents": len(document_ids),
            "processing_jobs": processing_jobs,
            "estimated_duration_seconds": estimated_duration,
            "worker_count": parallel_workers,
        }

    async def get_processing_status(self, ingestion_job_id: str) -> Dict:
        """
        Get current processing status for an ingestion job.

        Returns:
            Dict with:
            - job_id: Ingestion job ID
            - status: Overall job status
            - total_documents: Total document count
            - processed_documents: Count of completed documents
            - failed_documents: Count of failed documents
            - active_workers: List of active worker IDs
            - queue_status: Dict with pending/processing/completed counts
            - progress_percentage: Overall progress (0-100)
            - eta_seconds: Estimated time remaining
        """
        ingestion_job = self.db.query(IngestionJob).filter_by(job_id=ingestion_job_id).first()

        if not ingestion_job:
            raise ValueError(f"Ingestion job not found: {ingestion_job_id}")

        # Get processing jobs
        processing_jobs = (
            self.db.query(ProcessingJob).filter_by(ingestion_job_id=ingestion_job_id).all()
        )

        # Count statuses
        queued_count = sum(1 for job in processing_jobs if job.status == ProcessingStatus.QUEUED)
        processing_count = sum(
            1 for job in processing_jobs if job.status == ProcessingStatus.PROCESSING
        )
        completed_count = sum(
            1 for job in processing_jobs if job.status == ProcessingStatus.COMPLETED
        )
        failed_count = sum(1 for job in processing_jobs if job.status == ProcessingStatus.FAILED)

        # Get active workers
        active_workers = list(
            set(
                job.worker_id
                for job in processing_jobs
                if job.status == ProcessingStatus.PROCESSING and job.worker_id
            )
        )

        # Calculate overall progress
        progress_percentage = ingestion_job.progress_percentage

        # Calculate ETA (based on average processing time)
        if processing_count > 0:
            processing_jobs_active = [
                job for job in processing_jobs if job.status == ProcessingStatus.PROCESSING
            ]

            avg_eta = sum(job.eta_seconds for job in processing_jobs_active) / len(
                processing_jobs_active
            )
            eta_seconds = int(avg_eta * (queued_count + processing_count))
        else:
            eta_seconds = 0

        return {
            "job_id": ingestion_job_id,
            "status": ingestion_job.status.value,
            "total_documents": ingestion_job.total_documents,
            "processed_documents": completed_count,
            "failed_documents": failed_count,
            "active_workers": active_workers,
            "queue_status": {
                "pending": queued_count,
                "processing": processing_count,
                "completed": completed_count,
                "failed": failed_count,
            },
            "progress_percentage": progress_percentage,
            "eta_seconds": eta_seconds,
        }

    async def retry_failed_jobs(
        self, ingestion_job_id: str, job_ids: Optional[List[str]] = None
    ) -> Dict:
        """
        Retry failed processing jobs (FR-045, FR-046).

        Args:
            ingestion_job_id: Parent ingestion job ID
            job_ids: Optional list of specific job IDs to retry (None = retry all failed)

        Returns:
            Dict with:
            - retried_count: Number of jobs retried
            - job_ids: List of retried job IDs
        """
        # Get failed jobs
        query = self.db.query(ProcessingJob).filter_by(
            ingestion_job_id=ingestion_job_id, status=ProcessingStatus.FAILED
        )

        if job_ids:
            query = query.filter(ProcessingJob.processing_job_id.in_(job_ids))

        failed_jobs = query.all()

        retried_job_ids = []

        for job in failed_jobs:
            # Reset job status
            job.status = ProcessingStatus.QUEUED
            job.progress = 0.0
            job.error_message = None
            job.retry_count += 1

            # Re-add to processing queue
            queue_entry = ProcessingQueue(
                queue_id=self._generate_queue_id(),
                ingestion_job_id=ingestion_job_id,
                document_id=job.document_id,
                priority=QueuePriority.HIGH,  # Prioritize retries
            )

            self.db.add(queue_entry)
            retried_job_ids.append(job.processing_job_id)

        self.db.commit()

        return {"retried_count": len(retried_job_ids), "job_ids": retried_job_ids}

    async def handle_worker_failure(self, worker_id: str) -> Dict:
        """
        Handle worker failure and redistribute tasks (FR-035).

        Args:
            worker_id: Failed worker ID

        Returns:
            Dict with:
            - failed_worker_id: Worker ID that failed
            - redistributed_jobs: Count of jobs redistributed
            - new_worker_assignments: Dict mapping job_id to new worker_id
        """
        # Find all jobs assigned to failed worker
        failed_worker_jobs = (
            self.db.query(ProcessingJob)
            .filter_by(worker_id=worker_id, status=ProcessingStatus.PROCESSING)
            .all()
        )

        redistributed_count = 0
        new_assignments = {}

        for job in failed_worker_jobs:
            # Reset job to queued
            job.status = ProcessingStatus.QUEUED
            job.worker_id = None
            job.progress = 0.0

            # Re-add to queue with high priority
            queue_entry = ProcessingQueue(
                queue_id=self._generate_queue_id(),
                ingestion_job_id=job.ingestion_job_id,
                document_id=job.document_id,
                priority=QueuePriority.HIGH,
            )

            self.db.add(queue_entry)
            redistributed_count += 1

        self.db.commit()

        return {
            "failed_worker_id": worker_id,
            "redistributed_jobs": redistributed_count,
            "new_worker_assignments": new_assignments,
        }

    async def pause_ingestion(self, ingestion_job_id: str) -> Dict:
        """
        Pause ongoing ingestion (FR-055).

        Finishes current batch, then pauses remaining documents.

        Returns:
            Dict with:
            - job_id: Ingestion job ID
            - paused_documents: Count of documents paused
            - completing_documents: Count of documents still completing
        """
        ingestion_job = self.db.query(IngestionJob).filter_by(job_id=ingestion_job_id).first()

        if not ingestion_job:
            raise ValueError(f"Ingestion job not found: {ingestion_job_id}")

        # Pause job
        ingestion_job.status = IngestionStatus.PAUSED
        self.db.commit()

        # Count jobs by status
        processing_jobs = (
            self.db.query(ProcessingJob).filter_by(ingestion_job_id=ingestion_job_id).all()
        )

        completing_count = sum(
            1 for job in processing_jobs if job.status == ProcessingStatus.PROCESSING
        )
        paused_count = sum(1 for job in processing_jobs if job.status == ProcessingStatus.QUEUED)

        return {
            "job_id": ingestion_job_id,
            "paused_documents": paused_count,
            "completing_documents": completing_count,
        }

    async def cancel_ingestion(self, ingestion_job_id: str) -> Dict:
        """
        Cancel ongoing ingestion (FR-056).

        Returns:
            Dict with:
            - job_id: Ingestion job ID
            - cancelled_documents: Count of documents cancelled
        """
        ingestion_job = self.db.query(IngestionJob).filter_by(job_id=ingestion_job_id).first()

        if not ingestion_job:
            raise ValueError(f"Ingestion job not found: {ingestion_job_id}")

        # Cancel job
        ingestion_job.status = IngestionStatus.CANCELLED
        self.db.commit()

        # Cancel all queued processing jobs
        queued_jobs = (
            self.db.query(ProcessingJob)
            .filter_by(ingestion_job_id=ingestion_job_id, status=ProcessingStatus.QUEUED)
            .all()
        )

        for job in queued_jobs:
            job.status = ProcessingStatus.FAILED
            job.error_message = "Cancelled by user"

        self.db.commit()

        return {"job_id": ingestion_job_id, "cancelled_documents": len(queued_jobs)}

    def _generate_job_id(self) -> str:
        """Generate unique processing job ID"""
        import uuid

        return str(uuid.uuid4())

    def _generate_queue_id(self) -> str:
        """Generate unique queue entry ID"""
        import uuid

        return str(uuid.uuid4())
