"""
Feature 012: Template Generation API
T060-T068: Template Generation API endpoints

Endpoints:
- GET /api/v1/templates - List templates with filtering and pagination
- POST /api/v1/templates - Create new template
- GET /api/v1/templates/{id} - Get single template details
- PUT /api/v1/templates/{id} - Update template (auto-creates version)
- DELETE /api/v1/templates/{id} - Soft delete template
- GET /api/v1/templates/{id}/versions - List template versions
- GET /api/v1/templates/{id}/versions/{version_number} - Get specific version
- POST /api/v1/templates/{id}/generate - Generate document from template
- POST /api/v1/templates/{id}/preview - Real-time preview (<200ms)

Authentication: Requires Editor or Admin role (Editor for create/update, Admin for delete)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import time

from ..database import get_db
from ..models.template import Template, TemplateCreate, TemplateUpdate, TemplateInDB
from ..models.template_version import TemplateVersion, TemplateVersionInDB
from ..services.template_service import TemplateService
from ..middleware.rbac import get_current_user_with_role


router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


# ============================================================================
# Request/Response Models
# ============================================================================


class TemplateListResponse(BaseModel):
    """Response schema for template list."""

    templates: List[TemplateInDB]
    pagination: dict


class DocumentGenerationRequest(BaseModel):
    """Request schema for document generation."""

    placeholder_values: dict = Field(..., description="Key-value pairs for placeholder replacement")


class DocumentGenerationResponse(BaseModel):
    """Response schema for document generation."""

    generated_content: str
    missing_placeholders: List[str] = Field(default_factory=list)
    template_id: str
    generated_at: datetime


class TemplatePreviewRequest(BaseModel):
    """Request schema for template preview."""

    placeholder_values: dict = Field(..., description="Key-value pairs for preview")


class TemplatePreviewResponse(BaseModel):
    """Response schema for template preview."""

    preview_html: str
    render_time_ms: float = Field(..., description="Rendering time in milliseconds")
    template_id: str


# ============================================================================
# T060: GET /api/v1/templates
# ============================================================================


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    permission_level: Optional[str] = Query(
        None, description="Filter by permission level (public/shared/private)"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("editor")),
):
    """
    List templates with filtering and pagination (T060).

    Requires: Editor or Admin role

    Filters:
    - permission_level: Filter by access level (public/shared/private)

    Returns:
        TemplateListResponse with templates array and pagination metadata
    """
    try:
        template_service = TemplateService(db)

        # Get templates (TODO: Add permission_level filter)
        # For now, return all templates with pagination
        offset = (page - 1) * limit

        query = db.query(Template).filter(Template.deleted_at.is_(None))

        # Apply permission level filter
        if permission_level:
            query = query.filter(Template.permission_level == permission_level)

        total_count = query.count()
        templates = query.offset(offset).limit(limit).all()

        return TemplateListResponse(
            templates=[TemplateInDB.from_orm(t) for t in templates],
            pagination={
                "page": page,
                "limit": limit,
                "total_count": total_count,
                "total_pages": (total_count + limit - 1) // limit,
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list templates: {str(e)}",
        )


# ============================================================================
# T061: POST /api/v1/templates
# ============================================================================


@router.post("", response_model=TemplateInDB, status_code=status.HTTP_201_CREATED)
async def create_template(
    template_data: TemplateCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("editor")),
):
    """
    Create new template (T061).

    Requires: Editor or Admin role

    Validates content_structure JSONB and sets current_version=1.
    Creates initial TemplateVersion record.

    Args:
        template_data: Template creation data

    Returns:
        Created template object
    """
    try:
        template_service = TemplateService(db)

        # Create template
        new_template = template_service.create_template(
            template_data=template_data, created_by=current_user.id
        )

        return new_template

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create template: {str(e)}",
        )


# ============================================================================
# T062: GET /api/v1/templates/{id}
# ============================================================================


@router.get("/{template_id}", response_model=TemplateInDB)
async def get_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("editor")),
):
    """
    Get single template details (T062).

    Requires: Editor or Admin role

    Returns template with full content_structure and metadata.

    Args:
        template_id: Template UUID

    Returns:
        Template object with full details
    """
    try:
        template_service = TemplateService(db)

        # Get template
        template = template_service.get_template(template_id)

        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {template_id} not found"
            )

        return template

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve template: {str(e)}",
        )


# ============================================================================
# T063: PUT /api/v1/templates/{id}
# ============================================================================


@router.put("/{template_id}", response_model=TemplateInDB)
async def update_template(
    template_id: str,
    template_data: TemplateUpdate,
    change_description: Optional[str] = Query(None, description="Description of changes"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("editor")),
):
    """
    Update template and auto-create version (T063).

    Requires: Editor or Admin role

    Auto-increments current_version and creates TemplateVersion record
    with content snapshot.

    Args:
        template_id: Template UUID
        template_data: Template update data
        change_description: Optional description of changes

    Returns:
        Updated template object
    """
    try:
        template_service = TemplateService(db)

        # Update template (auto-creates version)
        updated_template = template_service.update_template(
            template_id=template_id,
            template_data=template_data,
            updated_by=current_user.id,
            change_description=change_description,
        )

        return updated_template

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update template: {str(e)}",
        )


# ============================================================================
# T064: DELETE /api/v1/templates/{id}
# ============================================================================


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Soft delete template (T064).

    Requires: Admin role

    Sets deleted_at timestamp instead of hard delete.
    Preserves template and version history for audit purposes.

    Args:
        template_id: Template UUID
    """
    try:
        template_service = TemplateService(db)

        # Soft delete template
        template_service.delete_template(template_id)

        return None

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete template: {str(e)}",
        )


# ============================================================================
# T065: GET /api/v1/templates/{id}/versions
# ============================================================================


@router.get("/{template_id}/versions", response_model=List[TemplateVersionInDB])
async def list_template_versions(
    template_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("editor")),
):
    """
    List all template versions (T065).

    Requires: Editor or Admin role

    Returns all TemplateVersion records for template,
    ordered by version_number descending (newest first).

    Args:
        template_id: Template UUID

    Returns:
        List of TemplateVersion objects
    """
    try:
        template_service = TemplateService(db)

        # Get template versions
        versions = template_service.get_template_versions(template_id)

        return versions

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve template versions: {str(e)}",
        )


# ============================================================================
# T066: GET /api/v1/templates/{id}/versions/{version_number}
# ============================================================================


@router.get("/{template_id}/versions/{version_number}", response_model=TemplateVersionInDB)
async def get_template_version(
    template_id: str,
    version_number: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("editor")),
):
    """
    Get specific template version (T066).

    Requires: Editor or Admin role

    Returns specific version snapshot with content_snapshot JSONB.

    Args:
        template_id: Template UUID
        version_number: Version number

    Returns:
        TemplateVersion object with snapshot
    """
    try:
        # Query TemplateVersion
        version = (
            db.query(TemplateVersion)
            .filter(
                TemplateVersion.template_id == template_id,
                TemplateVersion.version_number == version_number,
            )
            .first()
        )

        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version_number} not found for template {template_id}",
            )

        return TemplateVersionInDB.from_orm(version)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve template version: {str(e)}",
        )


# ============================================================================
# T067: POST /api/v1/templates/{id}/generate
# ============================================================================


@router.post("/{template_id}/generate", response_model=DocumentGenerationResponse)
async def generate_document(
    template_id: str,
    generation_request: DocumentGenerationRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("editor")),
):
    """
    Generate document from template (T067).

    Requires: Editor or Admin role

    Fills template with placeholder_values.
    Validates required placeholders (FR-TG-008).
    Returns generated_content and missing_placeholders array.

    Args:
        template_id: Template UUID
        generation_request: Placeholder values

    Returns:
        DocumentGenerationResponse with generated content
    """
    try:
        template_service = TemplateService(db)

        # Generate document
        result = template_service.generate_document(
            template_id=template_id, placeholder_values=generation_request.placeholder_values
        )

        return DocumentGenerationResponse(
            generated_content=result["generated_content"],
            missing_placeholders=result.get("missing_placeholders", []),
            template_id=template_id,
            generated_at=datetime.utcnow(),
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate document: {str(e)}",
        )


# ============================================================================
# T068: POST /api/v1/templates/{id}/preview
# ============================================================================


@router.post("/{template_id}/preview", response_model=TemplatePreviewResponse)
async def preview_template(
    template_id: str,
    preview_request: TemplatePreviewRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("editor")),
):
    """
    Real-time template preview (T068).

    Requires: Editor or Admin role

    Real-time preview with <200ms target latency.
    Returns preview_html and render_time_ms.

    Args:
        template_id: Template UUID
        preview_request: Placeholder values for preview

    Returns:
        TemplatePreviewResponse with HTML and render time
    """
    try:
        template_service = TemplateService(db)

        # Start timer
        start_time = time.time()

        # Preview template
        preview_html = template_service.preview_template(
            template_id=template_id, placeholder_values=preview_request.placeholder_values
        )

        # Calculate render time
        render_time_ms = (time.time() - start_time) * 1000

        # Log performance
        if render_time_ms > 200:
            print(
                f"[TemplatesAPI] WARNING: Preview render time {render_time_ms:.2f}ms exceeds 200ms target"
            )

        return TemplatePreviewResponse(
            preview_html=preview_html,
            render_time_ms=round(render_time_ms, 2),
            template_id=template_id,
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to preview template: {str(e)}",
        )
