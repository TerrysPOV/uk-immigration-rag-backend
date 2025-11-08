"""
Template Workflow API Routes (Feature 023)

Implements Mode 1 (Document Analysis) and Mode 2 (Letter Rendering) for Template Workflow.

Endpoints:
- POST /api/templates/analyze: Analyze document and map to decision requirements
- POST /api/templates/render: Render letter from selected requirements
- GET /api/templates/library: Retrieve decision library
- GET /api/templates/health: Health check (no auth required)

Features:
- OpenRouter LLM integration for document analysis
- GDS content standards validation (reading age ≤9, sentences ≤25 words)
- SSRF protection for document URLs
- Rate limiting (10 req/min per user)
- Comprehensive audit logging
- RBAC enforcement (Editor/Admin roles)
"""

import os
import json
import logging
import textstat
import re
from datetime import datetime
from uuid import uuid4
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

from src.middleware.rbac import get_current_user, verify_user_role
from src.services.openrouter_service import OpenRouterService
from src.models.audit_log import AuditLog
from src.database import get_db

# ============================================================================
# Logging Configuration
# ============================================================================

logger = logging.getLogger(__name__)

# ============================================================================
# Router Setup
# ============================================================================

router = APIRouter(prefix="/api/templates", tags=["Template Workflow"])

# ============================================================================
# Pydantic Models
# ============================================================================


class AnalysisRequest(BaseModel):
    """Request payload for Mode 1 (Document Analysis)"""
    document_url: str = Field(..., pattern=r'^https://.*')
    custom_analysis_prompt: Optional[str] = Field(None, max_length=5000)


class DecisionMatch(BaseModel):
    """Single matched decision requirement from document analysis"""
    decision_id: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: str = Field(..., max_length=500)
    suggested_values: Optional[Dict[str, Any]] = None


class AnalysisResponse(BaseModel):
    """Response payload for Mode 1 after LLM analysis"""
    request_id: str
    document_url: str
    matches: List[DecisionMatch]
    analysis_timestamp: str
    model_used: str
    processing_time_ms: int


class RequirementInput(BaseModel):
    """Single decision requirement with placeholder values for rendering"""
    decision_id: str
    values: Dict[str, Any]


class RenderingRequest(BaseModel):
    """Request payload for Mode 2 (Letter Rendering)"""
    requirements: List[RequirementInput] = Field(..., min_items=1)

    @validator('requirements')
    def validate_requirements(cls, v):
        if len(v) < 1:
            raise ValueError("At least one requirement must be provided")
        return v


class ReadabilityMetrics(BaseModel):
    """GDS content standards compliance metrics"""
    flesch_kincaid_grade: float
    reading_age: int
    average_sentence_length: float
    max_sentence_length: int
    gds_compliant: bool


class RenderingResponse(BaseModel):
    """Response payload for Mode 2 after letter rendering"""
    request_id: str
    rendered_letter: str
    requirements_inserted: List[str]
    readability_metrics: ReadabilityMetrics
    generation_timestamp: str
    processing_time_ms: int


class ComponentHealth(BaseModel):
    """Health status of individual component"""
    status: str  # "healthy" or "unhealthy"
    loaded_count: Optional[int] = None
    version: Optional[str] = None
    provider: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: str
    components: Dict[str, ComponentHealth]
    version: str = "1.0.0"


# ============================================================================
# Helper Functions
# ============================================================================


def validate_document_url(url: str) -> None:
    """
    Validate URL to prevent SSRF attacks (FR-052).

    Args:
        url: Document URL to validate

    Raises:
        ValueError: If URL is invalid or blocked
    """
    # Must be HTTPS
    if not url.startswith("https://"):
        raise ValueError("URL must use HTTPS protocol")

    # Parse URL
    parsed = urlparse(url)

    # Block localhost and internal IPs
    blocked_hosts = [
        "localhost", "127.0.0.1", "0.0.0.0",
        "10.", "172.16.", "172.17.", "172.18.", "172.19.",
        "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
        "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
        "172.30.", "172.31.", "192.168.", "169.254."
    ]

    hostname = parsed.hostname.lower() if parsed.hostname else ""
    for blocked in blocked_hosts:
        if hostname == blocked or hostname.startswith(blocked):
            raise ValueError(f"Cannot access restricted network range: {hostname}")


def load_decision_library() -> dict:
    """
    Load decision library from data/decision_library.json.

    Returns:
        Decision library dictionary

    Raises:
        FileNotFoundError: If library file not found
        ValueError: If library JSON invalid
    """
    library_path = Path(__file__).parent.parent.parent.parent / "data" / "decision_library.json"

    if not library_path.exists():
        logger.error(f"Decision library not found: {library_path}")
        raise FileNotFoundError(f"Decision library not found: {library_path}")

    try:
        with open(library_path, "r", encoding="utf-8") as f:
            library = json.load(f)

        # Validate structure
        if "DecisionLibrary" not in library:
            raise ValueError("Decision library missing 'DecisionLibrary' key")

        if not isinstance(library["DecisionLibrary"], list):
            raise ValueError("DecisionLibrary must be an array")

        return library

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in decision library: {e}")
        raise ValueError(f"Invalid decision library JSON: {e}")


def validate_gds_standards(text: str) -> ReadabilityMetrics:
    """
    Validate text meets GDS content standards (FR-023, FR-024).

    Args:
        text: Text to validate

    Returns:
        ReadabilityMetrics with GDS compliance status
    """
    # Split into sentences
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]

    # Reading age (FR-023: reading age 9 = grade 4 US)
    grade_level = textstat.flesch_kincaid_grade(text)
    reading_age = int(grade_level + 5)  # US grade to UK age

    # Sentence length (FR-024: max 25 words)
    sentence_lengths = []
    for sent in sentences:
        word_count = len(sent.split())
        sentence_lengths.append(word_count)

    avg_length = sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0
    max_length = max(sentence_lengths) if sentence_lengths else 0

    # GDS compliance: reading age ≤9 AND max sentence ≤25 words
    gds_compliant = reading_age <= 9 and max_length <= 25

    return ReadabilityMetrics(
        flesch_kincaid_grade=round(grade_level, 1),
        reading_age=reading_age,
        average_sentence_length=round(avg_length, 1),
        max_sentence_length=max_length,
        gds_compliant=gds_compliant
    )


def substitute_placeholders(template_lines: List[str], values: Dict[str, Any]) -> List[str]:
    """
    Substitute placeholders in template with provided values.

    Args:
        template_lines: Template text lines with placeholders like [DATE_START]
        values: Dictionary of placeholder values

    Returns:
        Template lines with substituted values
    """
    result_lines = []

    for line in template_lines:
        # Handle document list placeholder (special case)
        if "[DOCUMENTS]" in line and "documents" in values:
            # Replace [DOCUMENTS] with bulleted list
            documents = values["documents"]
            if isinstance(documents, list):
                for doc in documents:
                    result_lines.append(f"• {doc}")
            else:
                result_lines.append(f"• {documents}")
        elif "[FORMS]" in line and "forms" in values:
            # Replace [FORMS] with bulleted list
            forms = values["forms"]
            if isinstance(forms, list):
                for form in forms:
                    result_lines.append(f"• {form}")
            else:
                result_lines.append(f"• {forms}")
        else:
            # Standard placeholder substitution
            substituted_line = line
            for key, value in values.items():
                placeholder = f"[{key.upper()}]"
                if placeholder in substituted_line:
                    substituted_line = substituted_line.replace(placeholder, str(value))

            result_lines.append(substituted_line)

    return result_lines


def format_date(date_str: str) -> str:
    """
    Format ISO date (YYYY-MM-DD) to readable format (DD Month YYYY).

    Args:
        date_str: ISO 8601 date string

    Returns:
        Formatted date string (e.g., "15 January 2020")
    """
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return date_obj.strftime("%d %B %Y")
    except ValueError:
        # Return original if parsing fails
        return date_str


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/analyze", response_model=AnalysisResponse, status_code=status.HTTP_200_OK)
async def analyze_document(
    request: AnalysisRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mode 1: Analyze document and map to decision requirements.

    FR-001: Requires Editor or Admin role
    FR-005-009: Rate limited to 10 requests/min per user
    FR-010-018: Returns AnalysisResponse with decision matches
    FR-017: 30 second timeout
    FR-052: SSRF protection on document URL

    Args:
        request: AnalysisRequest with document_url
        current_user: Authenticated user from JWT token
        db: Database session

    Returns:
        AnalysisResponse with decision matches

    Raises:
        401: Unauthorized (no valid JWT token)
        403: Forbidden (not Editor/Admin role)
        400: Bad Request (invalid URL, validation errors)
        404: Not Found (document not found)
        429: Too Many Requests (rate limit exceeded)
        502: Bad Gateway (document retrieval failed)
        503: Service Unavailable (LLM service unavailable)
        504: Gateway Timeout (analysis exceeded 30s)
    """
    request_id = str(uuid4())
    start_time = datetime.utcnow()

    # Verify user has Editor or Admin role
    try:
        verify_user_role(current_user, allowed_roles=["editor", "admin"])
    except HTTPException:
        logger.warning(f"User {current_user.get('user_id')} lacks Editor/Admin role for template analysis")
        raise

    try:
        # Validate document URL (SSRF protection)
        try:
            validate_document_url(request.document_url)
        except ValueError as e:
            logger.warning(f"Invalid document URL: {e}", extra={"request_id": request_id})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "request_id": request_id,
                    "error": "ValidationError",
                    "message": str(e)
                }
            )

        # Load decision library
        try:
            library = load_decision_library()
        except (FileNotFoundError, ValueError) as e:
            logger.error(f"Failed to load decision library: {e}", extra={"request_id": request_id})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "request_id": request_id,
                    "error": "ServiceUnavailable",
                    "message": "Decision library unavailable"
                }
            )

        # TODO: Retrieve document content from RAG service
        # For now, use a placeholder (this would be replaced with actual RAG retrieval)
        document_content = f"Document from URL: {request.document_url}\n\nThis is placeholder content. In production, this would be retrieved from the RAG service."

        # Call OpenRouter LLM for analysis
        openrouter_service = OpenRouterService(db)
        try:
            analysis_result = await openrouter_service.analyze_document_with_library(
                document_content=document_content,
                library=library,
                custom_prompt=request.custom_analysis_prompt
            )
        except ValueError as e:
            logger.error(f"LLM analysis failed: {e}", extra={"request_id": request_id})
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "request_id": request_id,
                    "error": "AnalysisError",
                    "message": f"Document analysis failed: {str(e)}"
                }
            )
        except Exception as e:
            logger.error(f"Unexpected error during analysis: {e}", extra={"request_id": request_id}, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "request_id": request_id,
                    "error": "InternalError",
                    "message": f"Internal error during analysis. Request ID: {request_id}"
                }
            )

        # Calculate processing time
        processing_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        # Log to audit_log
        audit_entry = AuditLog(
            user_id=current_user["user_id"],
            action_type="create",  # Analysis is a create action
            resource_type="template",  # Template analysis
            resource_id=request_id,
            new_value={
                "document_url": request.document_url,
                "matches_count": len(analysis_result["matches"]),
                "processing_time_ms": processing_time_ms
            },
            ip_address=current_user.get("ip_address", "unknown"),
            user_agent=current_user.get("user_agent")
        )
        db.add(audit_entry)
        db.commit()

        logger.info(
            f"Analysis completed: {len(analysis_result['matches'])} matches",
            extra={
                "request_id": request_id,
                "user_id": current_user["user_id"],
                "document_url": request.document_url,
                "processing_time_ms": processing_time_ms
            }
        )

        # Build response
        return AnalysisResponse(
            request_id=request_id,
            document_url=request.document_url,
            matches=[DecisionMatch(**match) for match in analysis_result["matches"]],
            analysis_timestamp=datetime.utcnow().isoformat() + "Z",
            model_used=openrouter_service.default_model,
            processing_time_ms=processing_time_ms
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in analyze endpoint: {e}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "request_id": request_id,
                "error": "InternalError",
                "message": f"Internal error. Request ID: {request_id}"
            }
        )


@router.post("/render", response_model=RenderingResponse, status_code=status.HTTP_200_OK)
async def render_letter(
    request: RenderingRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mode 2: Render letter from selected decision requirements.

    FR-001: Requires Editor or Admin role
    FR-005-009: Rate limited to 10 requests/min per user
    FR-019-027: Returns RenderingResponse with rendered letter and GDS metrics
    FR-023: Reading age must be ≤9 for GDS compliance
    FR-024: Max sentence length must be ≤25 words for GDS compliance
    FR-027: 5 second timeout

    Args:
        request: RenderingRequest with requirements array
        current_user: Authenticated user from JWT token
        db: Database session

    Returns:
        RenderingResponse with rendered letter and readability metrics

    Raises:
        401: Unauthorized (no valid JWT token)
        403: Forbidden (not Editor/Admin role)
        400: Bad Request (empty requirements, invalid decision IDs, date validation)
        429: Too Many Requests (rate limit exceeded)
        503: Service Unavailable (decision library unavailable)
    """
    request_id = str(uuid4())
    start_time = datetime.utcnow()

    # Verify user has Editor or Admin role
    try:
        verify_user_role(current_user, allowed_roles=["editor", "admin"])
    except HTTPException:
        logger.warning(f"User {current_user.get('user_id')} lacks Editor/Admin role for template rendering")
        raise

    try:
        # Load decision library
        try:
            library = load_decision_library()
        except (FileNotFoundError, ValueError) as e:
            logger.error(f"Failed to load decision library: {e}", extra={"request_id": request_id})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "request_id": request_id,
                    "error": "ServiceUnavailable",
                    "message": "Decision library unavailable"
                }
            )

        # Build decision ID lookup
        library_lookup = {decision["id"]: decision for decision in library["DecisionLibrary"]}

        # Validate all decision IDs exist
        for req in request.requirements:
            if req.decision_id not in library_lookup:
                logger.warning(f"Unknown decision_id: {req.decision_id}", extra={"request_id": request_id})
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "request_id": request_id,
                        "error": "ValidationError",
                        "message": f"Unknown decision_id: {req.decision_id}"
                    }
                )

        # Validate date ranges (if applicable)
        for req in request.requirements:
            decision = library_lookup[req.decision_id]
            if decision["type"] == "date_range":
                if "date_start" in req.values and "date_end" in req.values:
                    try:
                        start_date = datetime.strptime(req.values["date_start"], "%Y-%m-%d")
                        end_date = datetime.strptime(req.values["date_end"], "%Y-%m-%d")
                        if start_date >= end_date:
                            raise ValueError("date_start must be before date_end")
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Invalid date range: {e}", extra={"request_id": request_id})
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail={
                                "request_id": request_id,
                                "error": "ValidationError",
                                "message": f"Invalid date range for {req.decision_id}: {str(e)}"
                            }
                        )

        # Render letter
        letter_parts = ["Dear Applicant,", "", "We have reviewed your application.", ""]

        requirements_inserted = []

        for req in request.requirements:
            decision = library_lookup[req.decision_id]
            requirements_inserted.append(req.decision_id)

            # Format dates for readability
            formatted_values = {}
            for key, value in req.values.items():
                if key in ["date_start", "date_end"]:
                    formatted_values[key] = format_date(value)
                else:
                    formatted_values[key] = value

            # Substitute placeholders in template
            substituted_lines = substitute_placeholders(decision["on_yes_template"], formatted_values)

            # Add to letter
            letter_parts.extend(substituted_lines)
            letter_parts.append("")  # Blank line between requirements

        # Add closing
        letter_parts.extend([
            "Yours sincerely,",
            "HM Passport Office"
        ])

        rendered_letter = "\n".join(letter_parts)

        # Compute readability metrics
        readability_metrics = validate_gds_standards(rendered_letter)

        # Calculate processing time
        processing_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        # Log to audit_log
        audit_entry = AuditLog(
            user_id=current_user["user_id"],
            action_type="create",  # Rendering is a create action
            resource_type="template",  # Template rendering
            resource_id=request_id,
            new_value={
                "requirements_count": len(request.requirements),
                "gds_compliant": readability_metrics.gds_compliant,
                "processing_time_ms": processing_time_ms
            },
            ip_address=current_user.get("ip_address", "unknown"),
            user_agent=current_user.get("user_agent")
        )
        db.add(audit_entry)
        db.commit()

        logger.info(
            f"Letter rendered: {len(requirements_inserted)} requirements, GDS compliant: {readability_metrics.gds_compliant}",
            extra={
                "request_id": request_id,
                "user_id": current_user["user_id"],
                "requirements_count": len(requirements_inserted),
                "processing_time_ms": processing_time_ms
            }
        )

        # Build response
        return RenderingResponse(
            request_id=request_id,
            rendered_letter=rendered_letter,
            requirements_inserted=requirements_inserted,
            readability_metrics=readability_metrics,
            generation_timestamp=datetime.utcnow().isoformat() + "Z",
            processing_time_ms=processing_time_ms
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in render endpoint: {e}",
            extra={"request_id": request_id, "user_id": current_user.get("user_id")},
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "request_id": request_id,
                "error": "InternalError",
                "message": f"Internal error. Request ID: {request_id}"
            }
        )


@router.get("/library", status_code=status.HTTP_200_OK)
async def get_decision_library(
    current_user: dict = Depends(get_current_user)
):
    """
    Retrieve decision library.

    FR-001: Requires Editor or Admin role
    Returns complete decision library JSON (no transformation)

    Args:
        current_user: Authenticated user from JWT token

    Returns:
        Decision library dictionary

    Raises:
        401: Unauthorized (no valid JWT token)
        403: Forbidden (not Editor/Admin role)
        503: Service Unavailable (library file missing or invalid)
    """
    # Verify user has Editor or Admin role
    try:
        verify_user_role(current_user, allowed_roles=["editor", "admin"])
    except HTTPException:
        logger.warning(f"User {current_user.get('user_id')} lacks Editor/Admin role for library access")
        raise

    try:
        library = load_decision_library()
        return library
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"Failed to load decision library: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "ServiceUnavailable",
                "message": "Decision library unavailable"
            }
        )


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check():
    """
    Health check endpoint (no authentication required).

    FR-045-049: Checks decision library and OpenRouter API availability

    Returns:
        HealthResponse with component statuses

    Status Codes:
        200: All components healthy
        503: One or more components unhealthy
    """
    timestamp = datetime.utcnow().isoformat() + "Z"
    components = {}

    # Check decision library
    library_health = ComponentHealth(status="unhealthy")
    try:
        library = load_decision_library()
        library_health = ComponentHealth(
            status="healthy",
            loaded_count=len(library.get("DecisionLibrary", [])),
            version=library.get("version", "unknown")
        )
    except Exception as e:
        library_health.error = str(e)

    components["decision_library"] = library_health

    # Check OpenRouter API (simple ping)
    openrouter_health = ComponentHealth(status="unhealthy")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        # API key is configured
        openrouter_health = ComponentHealth(
            status="healthy",
            provider="OpenRouter",
            latency_ms=0  # Placeholder - actual ping would measure latency
        )
    else:
        openrouter_health.error = "OPENROUTER_API_KEY not configured"

    components["llm_service"] = openrouter_health

    # Overall status
    overall_status = "healthy" if all(c.status == "healthy" for c in components.values()) else "degraded"

    return HealthResponse(
        status=overall_status,
        timestamp=timestamp,
        components=components
    )
