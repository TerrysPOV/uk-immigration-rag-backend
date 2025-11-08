"""
Ingestion API endpoints for document ingestion.

Feature 011: Document Ingestion & Batch Processing
T041-T043: URL scraping, file upload, and cloud drive sync endpoints
"""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, HttpUrl, validator
from sqlalchemy.orm import Session

from ..models.ingestion_job import IngestionJob, IngestionMethod, IngestionStatus
from ..models.ingestion_config import IngestionConfig as IngestionConfigModel
from ..models.cloud_drive_connection import CloudDriveConnection, CloudProvider
from ..services.url_scraper import URLScraperService
from ..services.file_processor import FileProcessorService
from ..services.cloud_sync import CloudSyncService
from ..services.batch_processor import BatchProcessorService
from ..utils.oauth_encryption import create_encryption_service
from ..middleware.rate_limiter import rate_limit

# Router for ingestion endpoints
router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])

# OAuth2 dependency
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# ============================================================================
# Request/Response Models
# ============================================================================

class IngestionConfigRequest(BaseModel):
    """Batch processing configuration"""
    chunk_size: int
    parallel_workers: int
    retry_attempts: int

    @validator('chunk_size')
    def validate_chunk_size(cls, v):
        if v < 1:
            raise ValueError('chunk_size must be >= 1')
        return v

    @validator('parallel_workers')
    def validate_workers(cls, v):
        if not (1 <= v <= 10):
            raise ValueError('parallel_workers must be between 1 and 10')
        return v

    @validator('retry_attempts')
    def validate_retries(cls, v):
        if not (0 <= v <= 5):
            raise ValueError('retry_attempts must be between 0 and 5')
        return v


class UrlIngestionRequest(BaseModel):
    """Request body for URL scraping ingestion"""
    urls: List[HttpUrl]
    fetch_nested: bool = False
    config: IngestionConfigRequest

    @validator('urls')
    def validate_urls(cls, v):
        if len(v) < 1:
            raise ValueError('At least one URL is required')
        return v


class CloudIngestionRequest(BaseModel):
    """Request body for cloud drive sync ingestion"""
    provider: str
    folder_path: str
    config: IngestionConfigRequest

    @validator('provider')
    def validate_provider(cls, v):
        valid_providers = ['google', 'onedrive', 'sharepoint']
        if v not in valid_providers:
            raise ValueError(f'Provider must be one of: {valid_providers}')
        return v


class IngestionJobResponse(BaseModel):
    """Response for created ingestion job"""
    job_id: str
    user_id: str
    method: str
    status: str
    total_documents: int
    processed_documents: int
    failed_documents: int
    start_time: datetime
    end_time: Optional[datetime]

    class Config:
        from_attributes = True


# ============================================================================
# Dependencies
# ============================================================================

def get_db() -> Session:
    """Database session dependency"""
    # TODO: Implement database session factory
    # from ..database import SessionLocal
    # db = SessionLocal()
    # try:
    #     yield db
    # finally:
    #     db.close()
    raise NotImplementedError("Database session factory not implemented")


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Verify OAuth token and extract user info.

    Returns:
        dict with user_id, roles, permissions
    """
    # TODO: Implement token verification with Google OAuth
    # For now, return mock user
    return {
        'user_id': 'user-123',
        'roles': ['Admin'],
        'permissions': ['canManagePipeline']
    }


def require_admin_permission(user: dict = Depends(get_current_user)) -> dict:
    """
    Verify user has Admin role and canManagePipeline permission (FR-001, FR-002).

    Raises:
        HTTPException: 403 if user lacks required permissions
    """
    if 'Admin' not in user.get('roles', []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required to manage document ingestion"
        )

    if 'canManagePipeline' not in user.get('permissions', []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="canManagePipeline permission required to manage document ingestion"
        )

    return user


# ============================================================================
# T041: POST /api/v1/ingestion/url
# ============================================================================

@router.post("/url", response_model=IngestionJobResponse, status_code=status.HTTP_201_CREATED)
@rate_limit(max_requests=10, window_seconds=60, key_prefix="ingestion_url")
async def ingest_urls(
    request: UrlIngestionRequest,
    user: dict = Depends(require_admin_permission),
    db: Session = Depends(get_db)
):
    """
    Start URL scraping ingestion (T041).

    Features:
    - URL validation (FR-006)
    - Nested URL discovery up to 20 degrees (FR-007, FR-008)
    - Content validation for guidance pages (FR-008a)
    - gov.uk domain restriction (FR-009)
    - RBAC enforcement (FR-001, FR-002)
    - Rate limiting: 10 requests/minute per user (T073)

    Returns:
        201: Ingestion job created
        400: Invalid URLs or configuration
        403: Missing permissions
        429: Rate limit exceeded
    """
    # Create ingestion job
    job_id = str(uuid.uuid4())
    ingestion_job = IngestionJob(
        job_id=job_id,
        user_id=user['user_id'],
        method=IngestionMethod.URL,
        status=IngestionStatus.PENDING,
        source_urls=[str(url) for url in request.urls],
        total_documents=0,
        processed_documents=0,
        failed_documents=0
    )

    db.add(ingestion_job)
    db.commit()
    db.refresh(ingestion_job)

    # Start URL scraping (async background task)
    scraper = URLScraperService()

    try:
        scrape_result = await scraper.scrape_urls_with_nested(
            initial_urls=[str(url) for url in request.urls],
            max_depth=20 if request.fetch_nested else 0,
            validate_content=True
        )

        # Update job with discovered documents
        ingestion_job.total_documents = len(scrape_result['scraped_documents'])
        db.commit()

        # Start batch processing
        batch_processor = BatchProcessorService(celery_app=None, db_session=db)

        document_ids = [doc['url'] for doc in scrape_result['scraped_documents']]

        await batch_processor.start_batch_processing(
            ingestion_job_id=job_id,
            document_ids=document_ids,
            chunk_size=request.config.chunk_size,
            parallel_workers=request.config.parallel_workers,
            retry_attempts=request.config.retry_attempts
        )

        # Return created job
        return IngestionJobResponse.from_orm(ingestion_job)

    except Exception as e:
        # Update job status to failed
        ingestion_job.status = IngestionStatus.FAILED
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL ingestion failed: {str(e)}"
        )


# ============================================================================
# T042: POST /api/v1/ingestion/upload
# ============================================================================

@router.post("/upload", response_model=IngestionJobResponse, status_code=status.HTTP_201_CREATED)
@rate_limit(max_requests=10, window_seconds=60, key_prefix="ingestion_upload")
async def ingest_files(
    files: List[UploadFile] = File(...),
    config: str = Form(...),
    user: dict = Depends(require_admin_permission),
    db: Session = Depends(get_db)
):
    """
    Upload files for ingestion (T042).

    Features:
    - Multi-file upload (FR-018)
    - 50MB file size validation (FR-014)
    - Format validation for PDF/Word/HTML/MD/TXT (FR-013, FR-016)
    - Parallel upload processing (FR-018)
    - RBAC enforcement (FR-001, FR-002)
    - Rate limiting: 10 requests/minute per user (T073)

    Returns:
        201: Ingestion job created
        400: File validation failed
        403: Missing permissions
        429: Rate limit exceeded
    """
    import json

    # Parse config from JSON string
    try:
        config_data = json.loads(config)
        ingestion_config = IngestionConfigRequest(**config_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid config: {str(e)}"
        )

    # Create ingestion job
    job_id = str(uuid.uuid4())
    ingestion_job = IngestionJob(
        job_id=job_id,
        user_id=user['user_id'],
        method=IngestionMethod.UPLOAD,
        status=IngestionStatus.PENDING,
        source_urls=[],  # No URLs for file upload
        total_documents=len(files),
        processed_documents=0,
        failed_documents=0
    )

    db.add(ingestion_job)
    db.commit()
    db.refresh(ingestion_job)

    # Process uploaded files
    file_processor = FileProcessorService(chunk_size_tokens=ingestion_config.chunk_size)

    try:
        # Read file contents
        file_data_list = []
        for upload_file in files:
            content = await upload_file.read()

            file_data_list.append({
                'filename': upload_file.filename,
                'content': content,
                'content_type': upload_file.content_type
            })

        # Process files in parallel (FR-018)
        process_result = await file_processor.process_files(
            files=file_data_list,
            chunk_size_tokens=ingestion_config.chunk_size
        )

        # Handle failed files
        if process_result['failed_files']:
            error_messages = [
                f"{f['filename']}: {f['error']}"
                for f in process_result['failed_files']
            ]

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File validation failed: {'; '.join(error_messages)}"
            )

        # Start batch processing
        batch_processor = BatchProcessorService(celery_app=None, db_session=db)

        document_ids = [f['filename'] for f in process_result['processed_files']]

        await batch_processor.start_batch_processing(
            ingestion_job_id=job_id,
            document_ids=document_ids,
            chunk_size=ingestion_config.chunk_size,
            parallel_workers=ingestion_config.parallel_workers,
            retry_attempts=ingestion_config.retry_attempts
        )

        # Return created job
        return IngestionJobResponse.from_orm(ingestion_job)

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Update job status to failed
        ingestion_job.status = IngestionStatus.FAILED
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File upload failed: {str(e)}"
        )


# ============================================================================
# T043: POST /api/v1/ingestion/cloud
# ============================================================================

@router.post("/cloud", response_model=IngestionJobResponse, status_code=status.HTTP_201_CREATED)
@rate_limit(max_requests=10, window_seconds=60, key_prefix="ingestion_cloud")
async def ingest_cloud_drive(
    request: CloudIngestionRequest,
    user: dict = Depends(require_admin_permission),
    db: Session = Depends(get_db)
):
    """
    Start cloud drive sync ingestion (T043).

    Features:
    - Google Drive, OneDrive, SharePoint support (FR-020)
    - OAuth token validation (FR-022)
    - Folder selection (FR-023)
    - Token expiry handling (FR-025)
    - Duplicate detection (FR-027)
    - RBAC enforcement (FR-001, FR-002)
    - Rate limiting: 10 requests/minute per user (T073)

    Returns:
        201: Ingestion job created
        401: OAuth token expired or invalid
        403: Missing permissions
        429: Rate limit exceeded
    """
    # Map provider string to enum
    provider_map = {
        'google': CloudProvider.GOOGLE_DRIVE,
        'onedrive': CloudProvider.ONEDRIVE,
        'sharepoint': CloudProvider.SHAREPOINT
    }

    provider = provider_map[request.provider]

    # Get cloud drive connection for user
    connection = db.query(CloudDriveConnection).filter_by(
        user_id=user['user_id'],
        provider=provider
    ).first()

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"No {request.provider} connection found. Please authenticate first."
        )

    # Check if token is expired (FR-025)
    if connection.is_token_expired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{request.provider} OAuth token expired. Please re-authenticate."
        )

    # Decrypt OAuth tokens
    encryption_service = create_encryption_service(master_secret="MASTER_SECRET")  # TODO: Load from config

    access_token, refresh_token = encryption_service.decrypt_token_pair(
        encrypted_access_token=connection.access_token_encrypted,
        encrypted_refresh_token=connection.refresh_token_encrypted,
        user_id=user['user_id']
    )

    # Create ingestion job
    job_id = str(uuid.uuid4())
    ingestion_job = IngestionJob(
        job_id=job_id,
        user_id=user['user_id'],
        method=IngestionMethod.CLOUD,
        status=IngestionStatus.PENDING,
        source_urls=[request.folder_path],
        total_documents=0,
        processed_documents=0,
        failed_documents=0
    )

    db.add(ingestion_job)
    db.commit()
    db.refresh(ingestion_job)

    # Start cloud sync
    cloud_sync = CloudSyncService()

    try:
        sync_result = await cloud_sync.sync_folder(
            provider=provider,
            access_token=access_token,
            folder_id=request.folder_path,
            refresh_token=refresh_token
        )

        # Handle token refresh needed
        if sync_result['needs_refresh']:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"{request.provider} OAuth token expired. Please re-authenticate."
            )

        # Update job with synced documents
        ingestion_job.total_documents = sync_result['total_synced']
        db.commit()

        # Start batch processing
        batch_processor = BatchProcessorService(celery_app=None, db_session=db)

        document_ids = [f['filename'] for f in sync_result['synced_files']]

        await batch_processor.start_batch_processing(
            ingestion_job_id=job_id,
            document_ids=document_ids,
            chunk_size=request.config.chunk_size,
            parallel_workers=request.config.parallel_workers,
            retry_attempts=request.config.retry_attempts
        )

        # Return created job
        return IngestionJobResponse.from_orm(ingestion_job)

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Update job status to failed
        ingestion_job.status = IngestionStatus.FAILED
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cloud sync failed: {str(e)}"
        )
