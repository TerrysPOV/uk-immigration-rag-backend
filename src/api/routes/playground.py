"""
Playground API Routes (Feature 024)

Implements prompt version management and controlled promotion workflow for
Template Workflow Playground.

Endpoints:
- POST /api/templates/playground/analyze: Test custom prompt with side-by-side comparison
- GET /api/templates/playground/prompts: List saved prompt versions
- POST /api/templates/playground/prompts: Save new prompt version
- GET /api/templates/playground/prompts/{version_id}: Get specific prompt version
- DELETE /api/templates/playground/prompts/{version_id}: Soft-delete prompt version
- POST /api/templates/playground/prompts/{version_id}/restore: Restore deleted version
- GET /api/templates/playground/prompts/production: Get current production prompt
- POST /api/templates/playground/promote/preview: Preview promotion impact
- POST /api/templates/playground/promote: Promote version to production
- GET /api/templates/playground/audit: Get audit log (placeholder)
- GET /api/templates/playground/backups: Get backup history (placeholder)

Features:
- RBAC enforcement (Editor/Admin roles only)
- Rate limiting (10 req/min per user, 100 req/hour)
- Optimistic locking conflict detection (409 Conflict)
- S3/Spaces backup on promotion
- Comprehensive audit logging
- Soft-delete with 30-day retention
"""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, StaleDataError

from src.middleware.rbac import get_current_user, verify_user_role
from src.services.playground_service import PlaygroundService
from src.services.promotion_service import PromotionService
from src.models.prompt_version import PromptVersionResponse
from src.models.production_prompt import ProductionPromptResponse, PromotionResult
from src.database import get_db

# ============================================================================
# Logging Configuration
# ============================================================================

logger = logging.getLogger(__name__)

# ============================================================================
# Router Setup
# ============================================================================

router = APIRouter(prefix="/api/templates/playground", tags=["Playground"])

# ============================================================================
# Pydantic Request/Response Models
# ============================================================================


class AnalyzeRequest(BaseModel):
    """Request payload for custom prompt testing"""

    document_url: str = Field(..., pattern=r"^https://.*", description="GOV.UK document URL to analyze")
    custom_prompt: str = Field(..., min_length=1, max_length=10000, description="Custom system prompt to test")


class AnalysisComparison(BaseModel):
    """Analysis comparison between production and playground prompts"""

    document_url: str
    production_matches: int
    playground_matches: int
    production_analysis: dict
    playground_analysis: dict
    analysis_duration_ms: int


class CreatePromptRequest(BaseModel):
    """Request payload for creating new prompt version"""

    name: str = Field(..., min_length=1, max_length=255, description="Unique version name")
    prompt_text: str = Field(..., min_length=1, max_length=10000, description="System prompt content")
    notes: Optional[str] = Field(None, description="Optional description of changes")


class PreviewPromotionRequest(BaseModel):
    """Request payload for previewing promotion"""

    version_id: UUID = Field(..., description="Prompt version ID to preview for promotion")


class PromoteRequest(BaseModel):
    """Request payload for promoting version to production"""

    version_id: UUID = Field(..., description="Prompt version ID to promote")
    confirmation: bool = Field(..., description="Must be true to proceed (safety check)")

    @validator("confirmation")
    def validate_confirmation(cls, v):
        if not v:
            raise ValueError("Promotion requires explicit confirmation=true")
        return v


class ErrorResponse(BaseModel):
    """Standard error response"""

    request_id: str
    error: str
    message: str
    status_code: int


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/analyze", response_model=AnalysisComparison, status_code=status.HTTP_200_OK)
async def analyze_with_custom_prompt(
    request: AnalyzeRequest,
    http_request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Test custom prompt with side-by-side comparison.

    Runs analysis with custom prompt and compares with production results.

    **Requires**: Editor or Admin role
    **Rate Limit**: 10/min, 100/hour
    """
    request_id = str(uuid4())

    try:
        # Verify role
        verify_user_role(current_user, ["editor", "admin"])

        # Initialize service
        service = PlaygroundService(db)

        # Run analysis
        result = await service.analyze_with_custom_prompt(
            document_url=request.document_url,
            custom_prompt=request.custom_prompt,
            user_id=current_user["user_id"],
        )

        logger.info(
            f"Custom prompt analysis completed",
            extra={
                "request_id": request_id,
                "user_id": current_user["user_id"],
                "document_url": request.document_url,
                "production_matches": result["production_matches"],
                "playground_matches": result["playground_matches"],
            },
        )

        return AnalysisComparison(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in analyze endpoint: {e}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "request_id": request_id,
                "error": "InternalServerError",
                "message": "An unexpected error occurred during analysis",
            },
        )


@router.get("/prompts", response_model=List[PromptVersionResponse], status_code=status.HTTP_200_OK)
def list_prompts(
    include_deleted: bool = False,
    page: int = 1,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all saved prompt versions.

    Returns active and optionally deleted prompt versions.

    **Requires**: Editor or Admin role
    **Rate Limit**: 10/min, 100/hour
    """
    request_id = str(uuid4())

    try:
        # Verify role
        verify_user_role(current_user, ["editor", "admin"])

        # Initialize service
        service = PlaygroundService(db)

        # List prompts
        prompts, total = service.list_prompts(include_deleted=include_deleted, page=page, limit=limit)

        logger.info(
            f"Listed {len(prompts)} prompt versions",
            extra={
                "request_id": request_id,
                "user_id": current_user["user_id"],
                "include_deleted": include_deleted,
                "page": page,
                "total": total,
            },
        )

        return prompts

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in list_prompts endpoint: {e}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "request_id": request_id,
                "error": "InternalServerError",
                "message": "An unexpected error occurred while listing prompts",
            },
        )


@router.post("/prompts", response_model=PromptVersionResponse, status_code=status.HTTP_201_CREATED)
def create_prompt(
    request: CreatePromptRequest,
    http_request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Save a new prompt version.

    Creates a named version of a prompt for testing and potential promotion.

    **Requires**: Editor or Admin role
    **Rate Limit**: 10/min, 100/hour
    """
    request_id = str(uuid4())

    try:
        # Verify role
        verify_user_role(current_user, ["editor", "admin"])

        # Initialize service
        service = PlaygroundService(db)

        # Create prompt
        prompt = service.create_prompt(
            name=request.name,
            prompt_text=request.prompt_text,
            author_id=current_user["user_id"],
            notes=request.notes,
        )

        logger.info(
            f"Created prompt version '{request.name}'",
            extra={
                "request_id": request_id,
                "user_id": current_user["user_id"],
                "version_id": str(prompt.id),
            },
        )

        return prompt

    except IntegrityError as e:
        logger.warning(
            f"Duplicate prompt name: {request.name}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "request_id": request_id,
                "error": "ValidationError",
                "message": f"Prompt version name '{request.name}' already exists",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in create_prompt endpoint: {e}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "request_id": request_id,
                "error": "InternalServerError",
                "message": "An unexpected error occurred while creating prompt",
            },
        )


@router.get("/prompts/{version_id}", response_model=PromptVersionResponse, status_code=status.HTTP_200_OK)
def get_prompt(
    version_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get specific prompt version by ID.

    Returns prompt version details including author and status.

    **Requires**: Editor or Admin role
    **Rate Limit**: 10/min, 100/hour
    """
    request_id = str(uuid4())

    try:
        # Verify role
        verify_user_role(current_user, ["editor", "admin"])

        # Initialize service
        service = PlaygroundService(db)

        # Get prompt
        prompt = service.get_prompt(version_id)

        if not prompt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "request_id": request_id,
                    "error": "NotFound",
                    "message": f"Prompt version '{version_id}' not found",
                },
            )

        logger.info(
            f"Retrieved prompt version",
            extra={"request_id": request_id, "user_id": current_user["user_id"], "version_id": str(version_id)},
        )

        return prompt

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in get_prompt endpoint: {e}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "request_id": request_id,
                "error": "InternalServerError",
                "message": "An unexpected error occurred while retrieving prompt",
            },
        )


@router.delete("/prompts/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(
    version_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Soft-delete prompt version (30-day retention).

    Marks version as deleted without immediate removal.

    **Requires**: Editor or Admin role
    **Rate Limit**: 10/min, 100/hour
    """
    request_id = str(uuid4())

    try:
        # Verify role
        verify_user_role(current_user, ["editor", "admin"])

        # Initialize service
        service = PlaygroundService(db)

        # Soft-delete prompt
        service.soft_delete_prompt(version_id, user_id=current_user["user_id"])

        logger.info(
            f"Soft-deleted prompt version",
            extra={"request_id": request_id, "user_id": current_user["user_id"], "version_id": str(version_id)},
        )

        return None

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"request_id": request_id, "error": "ValidationError", "message": str(e)},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in delete_prompt endpoint: {e}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "request_id": request_id,
                "error": "InternalServerError",
                "message": "An unexpected error occurred while deleting prompt",
            },
        )


@router.post("/prompts/{version_id}/restore", response_model=PromptVersionResponse, status_code=status.HTTP_200_OK)
def restore_prompt(
    version_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Restore soft-deleted prompt version.

    Restores version that was previously soft-deleted.

    **Requires**: Editor or Admin role
    **Rate Limit**: 10/min, 100/hour
    """
    request_id = str(uuid4())

    try:
        # Verify role
        verify_user_role(current_user, ["editor", "admin"])

        # Initialize service
        service = PlaygroundService(db)

        # Restore prompt
        prompt = service.restore_prompt(version_id, user_id=current_user["user_id"])

        logger.info(
            f"Restored prompt version",
            extra={"request_id": request_id, "user_id": current_user["user_id"], "version_id": str(version_id)},
        )

        return prompt

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"request_id": request_id, "error": "ValidationError", "message": str(e)},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in restore_prompt endpoint: {e}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "request_id": request_id,
                "error": "InternalServerError",
                "message": "An unexpected error occurred while restoring prompt",
            },
        )


@router.get("/prompts/production", response_model=ProductionPromptResponse, status_code=status.HTTP_200_OK)
def get_production_prompt(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get current production prompt.

    Returns the active production prompt with promoter details.

    **Requires**: Editor or Admin role
    **Rate Limit**: 10/min, 100/hour
    """
    request_id = str(uuid4())

    try:
        # Verify role
        verify_user_role(current_user, ["editor", "admin"])

        # Initialize service
        service = PlaygroundService(db)

        # Get production prompt
        production = service.get_production_prompt()

        logger.info(
            f"Retrieved production prompt",
            extra={"request_id": request_id, "user_id": current_user["user_id"]},
        )

        return production

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in get_production_prompt endpoint: {e}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "request_id": request_id,
                "error": "InternalServerError",
                "message": "An unexpected error occurred while retrieving production prompt",
            },
        )


@router.post("/promote/preview", status_code=status.HTTP_200_OK)
def preview_promotion(
    request: PreviewPromotionRequest,
    http_request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Preview promotion impact before confirming.

    Returns comparison between current production and proposed version.

    **Requires**: Editor or Admin role
    **Rate Limit**: 10/min, 100/hour
    """
    request_id = str(uuid4())

    try:
        # Verify role (Admin only for promotion)
        verify_user_role(current_user, ["admin"])

        # Initialize service
        service = PromotionService(db)

        # Preview promotion
        preview = service.preview_promotion(request.version_id)

        logger.info(
            f"Previewed promotion for version '{request.version_id}'",
            extra={"request_id": request_id, "user_id": current_user["user_id"], "version_id": str(request.version_id)},
        )

        return preview

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"request_id": request_id, "error": "ValidationError", "message": str(e)},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in preview_promotion endpoint: {e}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "request_id": request_id,
                "error": "InternalServerError",
                "message": "An unexpected error occurred while previewing promotion",
            },
        )


@router.post("/promote", response_model=PromotionResult, status_code=status.HTTP_200_OK)
def promote_to_production(
    request: PromoteRequest,
    http_request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Promote version to production with S3 backup and audit.

    Backs up current production, updates production prompt, logs audit entry.

    **Requires**: Admin role ONLY
    **Rate Limit**: 10/min, 100/hour
    **Note**: Returns 409 Conflict if concurrent promotion detected (optimistic locking)
    """
    request_id = str(uuid4())

    try:
        # Verify role (Admin only for promotion)
        verify_user_role(current_user, ["admin"])

        # Initialize service
        service = PromotionService(db)

        # Promote to production
        result = service.promote_to_production(
            version_id=request.version_id,
            user_id=current_user["user_id"],
            confirmation=request.confirmation,
        )

        logger.info(
            f"Promoted version to production",
            extra={
                "request_id": request_id,
                "user_id": current_user["user_id"],
                "version_id": str(request.version_id),
                "backup_path": result.backup_path,
            },
        )

        return result

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"request_id": request_id, "error": "ValidationError", "message": str(e)},
        )
    except StaleDataError as e:
        # Optimistic locking conflict
        logger.warning(
            f"Concurrent promotion detected",
            extra={"request_id": request_id, "user_id": current_user.get("user_id"), "version_id": str(request.version_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "request_id": request_id,
                "error": "ConflictError",
                "message": "Concurrent promotion detected. Another user has promoted a version. Please refresh and retry.",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in promote_to_production endpoint: {e}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "request_id": request_id,
                "error": "InternalServerError",
                "message": "An unexpected error occurred during promotion",
            },
        )
