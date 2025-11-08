"""
DeepInfra Qwen Reranker Component
Integrates Qwen/Qwen3-Reranker-8B via DeepInfra API for reranking search results.

Features:
- Same vendor as embeddings (unified API management)
- Competitive quality (BEIR 57.2 vs BGE 58.5)
- Cost efficient (~$50/month at 100K queries)
- Production SLA from DeepInfra
"""

import os
import logging
from typing import List, Dict, Any, Optional
import requests
import numpy as np
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """Reranking result with scores and metadata."""
    scores: List[float]
    model_name: str
    latency_ms: float
    score_variance: float
    score_range: tuple  # (min, max)


class DeepInfraReranker:
    """
    Qwen3-Reranker-8B reranker via DeepInfra API.

    Usage:
        reranker = DeepInfraReranker(model="Qwen/Qwen3-Reranker-8B")
        scores = reranker.rerank(query="visa requirements", documents=[...])
    """

    AVAILABLE_MODELS = [
        "Qwen/Qwen3-Reranker-0.6B",
        "Qwen/Qwen3-Reranker-4B",
        "Qwen/Qwen3-Reranker-8B"
    ]

    def __init__(
        self,
        model: str = "Qwen/Qwen3-Reranker-8B",
        api_key: Optional[str] = None,
        timeout: int = 30
    ):
        """
        Initialize DeepInfra reranker.

        Args:
            model: Qwen reranker model name
            api_key: DeepInfra API key (or set DEEPINFRA_API_KEY env var)
            timeout: Request timeout in seconds
        """
        if model not in self.AVAILABLE_MODELS:
            raise ValueError(
                f"Model {model} not supported. "
                f"Available: {self.AVAILABLE_MODELS}"
            )

        self.model = model
        self.api_key = api_key or os.getenv("DEEPINFRA_API_KEY")
        self.timeout = timeout

        if not self.api_key:
            raise ValueError(
                "DeepInfra API key required. "
                "Set DEEPINFRA_API_KEY environment variable or pass api_key parameter."
            )

        self.endpoint = "https://api.deepinfra.com/v1/inference/{model}"

        logger.info(f"Initialized DeepInfra reranker: {model}")

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: Optional[int] = None,
        return_documents: bool = False
    ) -> RerankResult:
        """
        Rerank documents by relevance to query.

        Args:
            query: Search query
            documents: List of document texts to rerank
            top_k: Return only top K results (None = all)
            return_documents: Include reranked document texts in response

        Returns:
            RerankResult with scores and metadata

        Raises:
            requests.RequestException: If API call fails
            ValueError: If response format invalid
        """
        import time
        start_time = time.time()

        if not documents:
            logger.warning("No documents to rerank")
            return RerankResult(
                scores=[],
                model_name=self.model,
                latency_ms=0,
                score_variance=0.0,
                score_range=(0.0, 0.0)
            )

        # Prepare API request
        url = self.endpoint.format(model=self.model)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        # DeepInfra expects "queries" (plural) as array
        payload = {
            "queries": [query],
            "documents": documents,
        }

        if top_k is not None:
            payload["top_k"] = top_k

        if return_documents:
            payload["return_documents"] = True

        # Call DeepInfra API
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()

        except requests.RequestException as e:
            logger.error(f"DeepInfra API error: {e}")
            raise

        # Parse response
        try:
            result = response.json()
            scores = result.get("scores", [])

            if not scores:
                raise ValueError("No scores in API response")

        except (ValueError, KeyError) as e:
            logger.error(f"Failed to parse DeepInfra response: {e}")
            raise ValueError(f"Invalid API response format: {e}")

        # Calculate latency
        latency_ms = (time.time() - start_time) * 1000

        # Validate score distribution
        score_variance = float(np.var(scores))
        score_range = (float(np.min(scores)), float(np.max(scores)))

        # CRITICAL: Detect uniform scoring issue (like ms-marco-MiniLM)
        if score_variance < 0.0001:
            logger.warning(
                f"⚠️ UNIFORM SCORING DETECTED! Variance: {score_variance:.6f}. "
                f"This reranker may be masking RRF scores like ms-marco-MiniLM-L-6-v2."
            )

        logger.info(
            f"Reranked {len(documents)} documents in {latency_ms:.1f}ms. "
            f"Score variance: {score_variance:.6f}, range: {score_range}"
        )

        return RerankResult(
            scores=scores,
            model_name=self.model,
            latency_ms=latency_ms,
            score_variance=score_variance,
            score_range=score_range
        )

    def validate_health(self) -> Dict[str, Any]:
        """
        Validate reranker health with test query.

        Returns:
            Health status dict with validation results
        """
        test_query = "What is a visa?"
        test_docs = [
            "A visa is an official document allowing entry to a country.",
            "The weather is sunny today.",
            "Python is a programming language."
        ]

        try:
            result = self.rerank(test_query, test_docs)

            # Check scores are well-distributed
            healthy = result.score_variance > 0.001

            return {
                "status": "healthy" if healthy else "warning",
                "model": self.model,
                "test_variance": result.score_variance,
                "test_range": result.score_range,
                "latency_ms": result.latency_ms,
                "warning": None if healthy else "Low score variance detected"
            }

        except Exception as e:
            return {
                "status": "error",
                "model": self.model,
                "error": str(e)
            }
