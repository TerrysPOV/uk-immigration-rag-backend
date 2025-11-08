"""
OpenRouter Models API endpoint (ModelPicker restoration).

Provides model selection dropdown data for the frontend ModelPicker component.
Fetches available models from OpenRouter API with caching for performance.

Endpoints:
- GET /api/models/openrouter: Fetch available OpenRouter models
"""

import os
import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta
import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["models"])

# Cache for OpenRouter models (30 minute TTL)
_models_cache: Dict[str, Any] = {
    "models": [],
    "cached_at": None,
    "ttl_seconds": 1800  # 30 minutes
}


class ModelInfo(BaseModel):
    """OpenRouter model information."""
    id: str = Field(..., description="Model ID (e.g., 'qwen/qwen3-30b-a3b-instruct-2507')")
    name: str = Field(..., description="Human-readable model name")
    description: str = Field(default="", description="Model description")
    context_length: int = Field(default=4096, description="Maximum context window")
    pricing: Dict[str, float] = Field(default_factory=dict, description="Pricing info (prompt/completion)")


class ModelsResponse(BaseModel):
    """Response schema for GET /api/models/openrouter."""
    models: List[ModelInfo] = Field(..., description="List of available models")
    cached: bool = Field(..., description="Whether response was served from cache")
    cached_at: str = Field(None, description="ISO timestamp when cache was last updated")


async def fetch_openrouter_models() -> List[Dict[str, Any]]:
    """
    Fetch models from OpenRouter API.

    Returns:
        List of model dictionaries from OpenRouter

    Raises:
        HTTPException: If API key missing or API request fails
    """
    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        logger.warning("OPENROUTER_API_KEY not configured, using default model list")
        # Return default UK Immigration guidance models
        return [
            {
                "id": "qwen/qwen3-30b-a3b-instruct-2507",
                "name": "Qwen3 30B A3B Instruct",
                "description": "High-quality model optimized for instruction following (default for UK Immigration guidance)",
                "context_length": 32768,
                "pricing": {"prompt": "0.0", "completion": "0.0"}
            },
            {
                "id": "anthropic/claude-3.5-sonnet",
                "name": "Claude 3.5 Sonnet",
                "description": "Anthropic's most intelligent model with strong reasoning capabilities",
                "context_length": 200000,
                "pricing": {"prompt": "0.003", "completion": "0.015"}
            },
            {
                "id": "openai/gpt-4-turbo",
                "name": "GPT-4 Turbo",
                "description": "OpenAI's latest GPT-4 model with improved performance",
                "context_length": 128000,
                "pricing": {"prompt": "0.01", "completion": "0.03"}
            },
        ]

    # Fetch from OpenRouter API
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "https://vectorgov.poview.ai"),
                    "X-Title": "UK Immigration RAG System"
                }
            )

            if response.status_code != 200:
                logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to fetch models from OpenRouter API"
                )

            data = response.json()
            return data.get("data", [])

    except httpx.TimeoutException:
        logger.error("OpenRouter API timeout")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="OpenRouter API request timed out"
        )
    except Exception as e:
        logger.exception(f"Error fetching OpenRouter models: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error fetching models"
        )


def is_cache_valid() -> bool:
    """Check if models cache is still valid based on TTL."""
    if not _models_cache["cached_at"]:
        return False

    cached_at = datetime.fromisoformat(_models_cache["cached_at"])
    ttl = timedelta(seconds=_models_cache["ttl_seconds"])

    return datetime.now() - cached_at < ttl


@router.get(
    "/openrouter",
    response_model=ModelsResponse,
    summary="Get OpenRouter Models",
    description="Fetch available models from OpenRouter API with 30-minute caching. "
                "Used by frontend ModelPicker component for model selection dropdown."
)
async def get_openrouter_models():
    """
    GET /api/models/openrouter

    Returns list of available OpenRouter models with metadata.
    Results are cached for 30 minutes to reduce API calls.

    If OPENROUTER_API_KEY is not configured, returns default model list
    for UK Immigration guidance (Qwen3, Claude 3.5, GPT-4 Turbo).

    Returns:
        ModelsResponse with models list and cache metadata

    Raises:
        HTTPException: 502 if OpenRouter API fails, 504 if timeout
    """
    logger.info("GET /api/models/openrouter - Fetching OpenRouter models")

    # Check cache validity
    if is_cache_valid():
        logger.info("Serving models from cache")
        return ModelsResponse(
            models=_models_cache["models"],
            cached=True,
            cached_at=_models_cache["cached_at"]
        )

    # Fetch fresh data from OpenRouter
    logger.info("Cache expired or empty, fetching fresh models from OpenRouter API")

    raw_models = await fetch_openrouter_models()

    # Transform to ModelInfo schema
    models = []
    for raw_model in raw_models:
        try:
            model_info = ModelInfo(
                id=raw_model.get("id", ""),
                name=raw_model.get("name", raw_model.get("id", "Unknown")),
                description=raw_model.get("description", ""),
                context_length=raw_model.get("context_length", 4096),
                pricing=raw_model.get("pricing", {})
            )
            models.append(model_info)
        except Exception as e:
            logger.warning(f"Skipping invalid model entry: {e}")
            continue

    # Update cache
    cached_at = datetime.now().isoformat()
    _models_cache["models"] = models
    _models_cache["cached_at"] = cached_at

    logger.info(f"Cached {len(models)} models from OpenRouter API")

    return ModelsResponse(
        models=models,
        cached=False,
        cached_at=cached_at
    )
