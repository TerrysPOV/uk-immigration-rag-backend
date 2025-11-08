"""
Admin endpoints for reprocessing failed documents (Feature 019).

Feature 019: Process All Cross-Government Guidance Documents
T014: POST /api/admin/reprocess-failed-documents endpoint
T015: GET /api/admin/reprocessing-status/{batch_id} endpoints (JSON + SSE)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from typing import Optional, AsyncGenerator
import uuid
import logging
import asyncio
import json

from src.middleware.rbac import get_current_user
from src.database import get_db
from src.models.ingestion_job import IngestionJob, IngestionMethod, IngestionStatus
from src.models.processing_job import ProcessingJob, ProcessingStatus
from src.models.document import Document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# Response models
class ReprocessResponse(BaseModel):
    """Response model for POST /api/admin/reprocess-failed-documents"""
    batch_id: str
    queued_documents: int
    estimated_duration_seconds: int
    status_url: str


class ConflictResponse(BaseModel):
    """Response model for 409 Conflict (batch already in progress)"""
    detail: str
    active_batch_id: str


class BatchStatusResponse(BaseModel):
    """Response model for GET /api/admin/reprocessing-status/{batch_id}"""
    batch_id: str
    status: str  # queued, in_progress, completed, failed
    documents_queued: int
    documents_processing: int
    documents_completed: int
    documents_failed: int
    success_rate: float
    estimated_time_remaining_seconds: int
    started_at: str  # ISO 8601
    updated_at: str  # ISO 8601


# Helper functions
async def verify_admin_role(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Verify user has admin role.

    Args:
        current_user: Current authenticated user from get_current_user dependency

    Returns:
        dict: User information if admin

    Raises:
        HTTPException: 403 if user lacks admin role
    """
    user_roles = current_user.get("roles", [])

    if "admin" not in user_roles:
        logger.warning(
            f"User {current_user.get('user_id')} attempted admin action without admin role",
            extra={"user_id": current_user.get("user_id"), "roles": user_roles}
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User lacks required admin role"
        )

    return current_user


async def check_active_batch(db: AsyncSession) -> Optional[str]:
    """
    Check if there's already an active reprocessing batch.

    Args:
        db: Database session

    Returns:
        Optional[str]: batch_id of active batch, or None if no active batch
    """
    # Query for ProcessingJobs with reprocessing_batch_id and status not completed/failed
    stmt = (
        select(ProcessingJob.reprocessing_batch_id)
        .where(ProcessingJob.reprocessing_batch_id.isnot(None))
        .where(ProcessingJob.status.in_([ProcessingStatus.QUEUED, ProcessingStatus.PROCESSING]))
        .limit(1)
    )

    result = await db.execute(stmt)
    active_batch = result.scalar_one_or_none()

    return active_batch


async def get_batch_status(db: AsyncSession, batch_id: str) -> Optional[dict]:
    """
    Get status information for a reprocessing batch.

    Args:
        db: Database session
        batch_id: Reprocessing batch identifier

    Returns:
        Optional[dict]: Batch status dictionary, or None if batch not found
    """
    # Query ProcessingJobs for this batch
    stmt = (
        select(
            ProcessingJob.status,
            func.count().label("count")
        )
        .where(ProcessingJob.reprocessing_batch_id == batch_id)
        .group_by(ProcessingJob.status)
    )

    result = await db.execute(stmt)
    status_counts = {row.status: row.count for row in result.fetchall()}

    # If no jobs found, batch doesn't exist
    if not status_counts:
        return None

    # Calculate counts
    documents_queued = status_counts.get(ProcessingStatus.QUEUED, 0)
    documents_processing = status_counts.get(ProcessingStatus.PROCESSING, 0)
    documents_completed = status_counts.get(ProcessingStatus.COMPLETED, 0)
    documents_failed = status_counts.get(ProcessingStatus.FAILED, 0)

    total_documents = sum(status_counts.values())

    # Calculate success rate
    total_finished = documents_completed + documents_failed
    success_rate = (documents_completed / total_finished * 100) if total_finished > 0 else 0.0

    # Determine overall batch status
    if documents_processing > 0 or documents_queued > 0:
        batch_status = "in_progress"
    elif documents_failed > 0 and documents_completed == 0:
        batch_status = "failed"
    elif total_finished == total_documents:
        batch_status = "completed"
    else:
        batch_status = "queued"

    # Calculate estimated time remaining
    THROUGHPUT_DOCS_PER_SECOND = 0.5  # Conservative estimate (same as reprocess endpoint)
    remaining_documents = documents_queued + documents_processing
    estimated_time_remaining = int(remaining_documents / THROUGHPUT_DOCS_PER_SECOND) if remaining_documents > 0 else 0

    # Get timestamps from IngestionJob
    # Find the IngestionJob associated with this batch
    ingestion_stmt = (
        select(IngestionJob.start_time, IngestionJob.updated_at)
        .join(ProcessingJob, ProcessingJob.ingestion_job_id == IngestionJob.job_id)
        .where(ProcessingJob.reprocessing_batch_id == batch_id)
        .limit(1)
    )

    ingestion_result = await db.execute(ingestion_stmt)
    ingestion_row = ingestion_result.fetchone()

    if ingestion_row:
        started_at = ingestion_row.start_time.isoformat() + "Z" if ingestion_row.start_time else datetime.utcnow().isoformat() + "Z"
        updated_at = ingestion_row.updated_at.isoformat() + "Z" if ingestion_row.updated_at else datetime.utcnow().isoformat() + "Z"
    else:
        # Fallback to current time
        now_iso = datetime.utcnow().isoformat() + "Z"
        started_at = now_iso
        updated_at = now_iso

    return {
        "batch_id": batch_id,
        "status": batch_status,
        "documents_queued": documents_queued,
        "documents_processing": documents_processing,
        "documents_completed": documents_completed,
        "documents_failed": documents_failed,
        "success_rate": round(success_rate, 2),
        "estimated_time_remaining_seconds": estimated_time_remaining,
        "started_at": started_at,
        "updated_at": updated_at
    }


# Endpoints
@router.post(
    "/reprocess-failed-documents",
    response_model=ReprocessResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"description": "Invalid authentication credentials"},
        403: {"description": "User lacks required admin role"},
        409: {"description": "Reprocessing batch already in progress", "model": ConflictResponse}
    }
)
async def reprocess_failed_documents(
    current_user: dict = Depends(verify_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger reprocessing of all failed documents with chrome stripping.

    This endpoint:
    1. Queries for all documents with processing_success IS NULL OR FALSE
    2. Creates a new IngestionJob for the reprocessing batch
    3. Creates ProcessingJob records for each document
    4. Returns batch metadata for status monitoring

    **Requires**: Google OAuth authentication with `admin` role

    **Returns**:
    - 202 Accepted: Batch queued successfully
    - 401 Unauthorized: Missing or invalid authentication
    - 403 Forbidden: User lacks admin role
    - 409 Conflict: Batch already in progress

    Contract reference: .specify/specs/019-process-all-7/contracts/admin_reprocess_endpoint.md
    """
    try:
        # Check for active batch (FR-017: Prevent duplicate batches)
        active_batch_id = await check_active_batch(db)
        if active_batch_id:
            logger.info(
                f"Reprocessing blocked: batch {active_batch_id} already in progress",
                extra={"active_batch_id": active_batch_id, "user_id": current_user.get("user_id")}
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Reprocessing batch already in progress",
                headers={"active_batch_id": active_batch_id}
            )

        # Query failed documents (FR-001: All departments, not just immigration)
        # WHERE (processing_success IS NULL OR processing_success = FALSE) AND content IS NOT NULL
        stmt = (
            select(Document.id)
            .where(
                (Document.processing_success.is_(None) | (Document.processing_success == False)) &
                (Document.content.isnot(None))
            )
        )

        result = await db.execute(stmt)
        failed_document_ids = [row[0] for row in result.fetchall()]

        queued_count = len(failed_document_ids)

        if queued_count == 0:
            logger.info("No failed documents to reprocess")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No failed documents found to reprocess"
            )

        # Generate batch_id (format: reprocess-YYYYMMDD-HHMMSS)
        batch_timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        batch_id = f"reprocess-{batch_timestamp}"

        # Create parent IngestionJob for the batch
        ingestion_job = IngestionJob(
            job_id=str(uuid.uuid4()),
            user_id=current_user.get("user_id"),
            method=IngestionMethod.UPLOAD,  # Reprocessing uses UPLOAD method
            status=IngestionStatus.PENDING,
            source_details=f"Reprocessing batch: {batch_id}",
            total_documents=queued_count,
            processed_documents=0,
            failed_documents=0,
            start_time=datetime.utcnow()
        )
        db.add(ingestion_job)

        # Create ProcessingJob records for each failed document
        processing_jobs = []
        for doc_id in failed_document_ids:
            processing_job = ProcessingJob(
                processing_job_id=str(uuid.uuid4()),
                ingestion_job_id=ingestion_job.job_id,
                document_id=doc_id,
                status=ProcessingStatus.QUEUED,
                reprocessing_batch_id=batch_id,  # Feature 019: Track batch
                chrome_stripper_version="1.0.0"  # Feature 019: Track chrome stripper version
            )
            processing_jobs.append(processing_job)

        db.add_all(processing_jobs)

        # Commit transaction
        await db.commit()

        # Calculate estimated duration (assuming 2 seconds per document avg)
        THROUGHPUT_DOCS_PER_SECOND = 0.5  # Conservative estimate
        estimated_duration = int(queued_count / THROUGHPUT_DOCS_PER_SECOND)

        # Build status URL
        status_url = f"/api/admin/reprocessing-status/{batch_id}"

        # Log audit event (FR-018: Audit trail)
        logger.info(
            "Reprocessing batch initiated",
            extra={
                "event": "reprocessing_initiated",
                "batch_id": batch_id,
                "queued_documents": queued_count,
                "user_id": current_user.get("user_id"),
                "ingestion_job_id": ingestion_job.job_id
            }
        )

        # Return 202 Accepted
        return ReprocessResponse(
            batch_id=batch_id,
            queued_documents=queued_count,
            estimated_duration_seconds=estimated_duration,
            status_url=status_url
        )

    except HTTPException:
        # Re-raise HTTP exceptions (401, 403, 409, 404)
        raise

    except Exception as e:
        logger.error(
            f"Failed to queue documents for reprocessing: {e}",
            extra={"error": str(e), "user_id": current_user.get("user_id")},
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue documents for reprocessing: {str(e)}"
        )


@router.get(
    "/reprocessing-status/{batch_id}",
    response_model=BatchStatusResponse,
    responses={
        401: {"description": "Invalid authentication credentials"},
        403: {"description": "User lacks required admin role"},
        404: {"description": "Reprocessing batch not found"}
    }
)
async def get_reprocessing_status(
    batch_id: str,
    current_user: dict = Depends(verify_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current status of a reprocessing batch (JSON response).

    Returns batch progress including document counts, success rate,
    and estimated time remaining.

    **Requires**: Google OAuth authentication with `admin` role

    **Returns**:
    - 200 OK: Batch status data
    - 401 Unauthorized: Missing or invalid authentication
    - 403 Forbidden: User lacks admin role
    - 404 Not Found: Batch ID not found

    Contract reference: .specify/specs/019-process-all-7/contracts/admin_status_endpoint.md (lines 1-56)
    """
    try:
        # Get batch status
        status_data = await get_batch_status(db, batch_id)

        if status_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Reprocessing batch not found",
                headers={"batch_id": batch_id}
            )

        return BatchStatusResponse(**status_data)

    except HTTPException:
        # Re-raise HTTP exceptions (401, 403, 404)
        raise

    except Exception as e:
        logger.error(
            f"Failed to retrieve batch status: {e}",
            extra={"error": str(e), "batch_id": batch_id, "user_id": current_user.get("user_id")},
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve batch status: {str(e)}"
        )


@router.get(
    "/reprocessing-status/{batch_id}/stream",
    responses={
        200: {"description": "Server-Sent Events stream", "content": {"text/event-stream": {}}},
        401: {"description": "Invalid authentication credentials"},
        403: {"description": "User lacks required admin role"},
        404: {"description": "Reprocessing batch not found"}
    }
)
async def stream_reprocessing_status(
    batch_id: str,
    current_user: dict = Depends(verify_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream reprocessing batch status via Server-Sent Events (SSE).

    Sends status updates every 2 seconds until batch is completed or failed.
    Client should use EventSource API to consume the stream.

    **Requires**: Google OAuth authentication with `admin` role

    **Returns**:
    - 200 OK: SSE stream with text/event-stream content type
    - 401 Unauthorized: Missing or invalid authentication
    - 403 Forbidden: User lacks admin role
    - 404 Not Found: Batch ID not found

    **Event Format**: JSON object matching BatchStatusResponse schema

    Contract reference: .specify/specs/019-process-all-7/contracts/admin_status_endpoint.md (lines 59-144)
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        """
        Generate Server-Sent Events for batch status updates.

        Yields:
            str: SSE-formatted event data (data: {json}\n\n)
        """
        try:
            while True:
                # Get current batch status
                status_data = await get_batch_status(db, batch_id)

                if status_data is None:
                    # Batch not found - send error event and close
                    error_event = {
                        "error": "Batch not found",
                        "batch_id": batch_id
                    }
                    yield f"data: {json.dumps(error_event)}\n\n"
                    break

                # Send status update
                yield f"data: {json.dumps(status_data)}\n\n"

                # Check if batch is complete
                if status_data["status"] in ["completed", "failed"]:
                    logger.info(
                        f"SSE stream closed: batch {batch_id} status is {status_data['status']}",
                        extra={"batch_id": batch_id, "final_status": status_data["status"]}
                    )
                    break

                # Wait 2 seconds before next update (per contract)
                await asyncio.sleep(2)

        except asyncio.CancelledError:
            # Client disconnected
            logger.info(
                f"SSE stream cancelled: client disconnected",
                extra={"batch_id": batch_id, "user_id": current_user.get("user_id")}
            )
            raise

        except Exception as e:
            # Log error and send error event
            logger.error(
                f"SSE stream error: {e}",
                extra={"error": str(e), "batch_id": batch_id},
                exc_info=True
            )
            error_event = {
                "error": "Internal server error",
                "detail": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering for SSE
        }
    )
