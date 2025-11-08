"""
T039-T040: Filter API Endpoints
Endpoints for filter facets and preview counts

Endpoints:
- GET /api/v1/search/filters/facets
- POST /api/v1/search/filters/preview
"""

import logging
from typing import Dict, List, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.middleware.rbac import get_current_user, User
from src.services.filter_service import FilterService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/search/filters", tags=["filters"])


# Request/Response schemas
class FilterFacet(BaseModel):
    """Single filter facet with values and counts."""

    facet_type: str = Field(..., description="Facet type (document_type/date_range/source)")
    values: List[Dict[str, Any]] = Field(
        ...,
        description="Facet values with labels and counts: [{label, value, count, disabled?}, ...]",
    )


class FilterFacetsResponse(BaseModel):
    """Response for GET /facets endpoint."""

    facets: List[FilterFacet] = Field(..., description="Available filter facets")


class FilterPreviewRequest(BaseModel):
    """Request for POST /preview endpoint."""

    current_filters: Dict[str, Any] = Field(
        ..., description="Currently active filters"
    )
    preview_filter: Dict[str, Any] = Field(
        ..., description="Additional filter to preview"
    )
    results: List[Dict] = Field(..., description="Current search results")


class FilterPreviewResponse(BaseModel):
    """Response for POST /preview endpoint."""

    result_count: int = Field(..., description="Number of results with preview filter applied", ge=0)


@router.get(
    "/facets",
    response_model=FilterFacetsResponse,
    summary="Get Filter Facets",
    description="Get available filter facets with counts for current search results. "
    "Used to populate filter UI with document types, date ranges, and sources.",
)
async def get_filter_facets(
    user: User = Depends(get_current_user),
) -> FilterFacetsResponse:
    """
    GET /api/v1/search/filters/facets

    Returns available filter facets for the current search context.
    Facets include document_type, date_range, and source with result counts.

    Note: This endpoint currently returns static facets.
    TODO: Integrate with actual search results from session/cache.

    Returns:
        FilterFacetsResponse with facets array
    """
    logger.info(f"GET /filters/facets - user: {user.username}")

    # TODO: Get actual search results from session/cache
    # For now, return static facets for demonstration
    sample_results = [
        {
            "document_type": "guidance",
            "source": "home_office",
            "publication_date": "2024-06-15",
        },
        {
            "document_type": "form",
            "source": "ukvi",
            "publication_date": "2024-03-10",
        },
        {
            "document_type": "guidance",
            "source": "home_office",
            "publication_date": "2023-12-01",
        },
    ]

    facets_dict = FilterService.get_facets(sample_results)

    # Convert to API response format
    facets = [
        FilterFacet(facet_type=facet_type, values=values)
        for facet_type, values in facets_dict.items()
    ]

    logger.info(f"Returning {len(facets)} facet types")
    return FilterFacetsResponse(facets=facets)


@router.post(
    "/preview",
    response_model=FilterPreviewResponse,
    summary="Preview Filter Result Count",
    description="Calculate result count for a filter combination without applying it. "
    "Used for hover preview tooltips showing 'X results' before user clicks filter.",
)
async def preview_filter_results(
    request: FilterPreviewRequest,
    user: User = Depends(get_current_user),
) -> FilterPreviewResponse:
    """
    POST /api/v1/search/filters/preview

    Calculate how many results would remain if preview_filter is applied
    in addition to current_filters.

    Body:
        {
            "current_filters": {document_type: ["guidance"], ...},
            "preview_filter": {source: ["home_office"]},
            "results": [{...}, {...}]
        }

    Returns:
        FilterPreviewResponse with result_count
    """
    logger.info(
        f"POST /filters/preview - user: {user.username}, "
        f"current_filters: {request.current_filters}, "
        f"preview_filter: {request.preview_filter}"
    )

    # Merge current and preview filters
    combined_filters = {**request.current_filters}
    for key, value in request.preview_filter.items():
        if key in combined_filters:
            # Merge arrays for multi-select filters
            if isinstance(combined_filters[key], list) and isinstance(value, list):
                combined_filters[key] = list(set(combined_filters[key] + value))
            else:
                combined_filters[key] = value
        else:
            combined_filters[key] = value

    # Calculate preview count
    result_count = FilterService.get_preview_count(request.results, combined_filters)

    logger.info(f"Preview count: {result_count} results")
    return FilterPreviewResponse(result_count=result_count)
