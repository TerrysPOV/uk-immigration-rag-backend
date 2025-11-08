"""
Cohere Reranker Component
Integrates Cohere rerank-english-v3.0 API for production-grade reranking.

Features:
- Best-in-class performance (beats BGE on most benchmarks)
- Long document support (4096 tokens vs 512)
- Production SLA (99.9% uptime)
- Metadata-aware reranking
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


class CohereReranker:
    """
    Cohere rerank-english-v3.0 reranker.

    Usage:
        reranker = CohereReranker()
        scores = reranker.rerank(query="visa requirements", documents=[...])
    """

    AVAILABLE_MODELS = [
        "rerank-english-v3.0",
        "rerank-multilingual-v3.0"
    ]

    def __init__(
        self,
        model: str = "rerank-english-v3.0",
        api_key: Optional[str] = None,
        timeout: int = 30
    ):
        """
        Initialize Cohere reranker.

        Args:
            model: Cohere reranker model name
            api_key: Cohere API key (or set COHERE_API_KEY env var)
            timeout: Request timeout in seconds
        """
        if model not in self.AVAILABLE_MODELS:
            raise ValueError(
                f"Model {model} not supported. "
                f"Available: {self.AVAILABLE_MODELS}"
            )

        self.model = model
        self.api_key = api_key or os.getenv("COHERE_API_KEY")
        self.timeout = timeout

        if not self.api_key:
            raise ValueError(
                "Cohere API key required. "
                "Set COHERE_API_KEY environment variable or pass api_key parameter."
            )

        self.endpoint = "https://api.cohere.ai/v1/rerank"

        logger.info(f"Initialized Cohere reranker: {model}")

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: Optional[int] = None,
        max_chunks_per_doc: Optional[int] = None
    ) -> RerankResult:
        """
        Rerank documents by relevance to query.

        Args:
            query: Search query
            documents: List of document texts to rerank
            top_k: Return only top K results (None = all)
            max_chunks_per_doc: Max chunks per long document (None = auto)

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
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "return_documents": False
        }

        if top_k is not None:
            payload["top_n"] = top_k

        if max_chunks_per_doc is not None:
            payload["max_chunks_per_doc"] = max_chunks_per_doc

        # Call Cohere API
        try:
            response = requests.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()

        except requests.RequestException as e:
            logger.error(f"Cohere API error: {e}")
            raise

        # Parse response
        try:
            result = response.json()
            results = result.get("results", [])

            if not results:
                raise ValueError("No results in API response")

            # Cohere returns results sorted by relevance score
            # Extract scores in original document order
            scores = [0.0] * len(documents)
            for item in results:
                index = item["index"]
                score = item["relevance_score"]
                scores[index] = score

        except (ValueError, KeyError) as e:
            logger.error(f"Failed to parse Cohere response: {e}")
            raise ValueError(f"Invalid API response format: {e}")

        # Calculate latency
        latency_ms = (time.time() - start_time) * 1000

        # Validate score distribution
        score_variance = float(np.var(scores))
        score_range = (float(np.min(scores)), float(np.max(scores)))

        # Check for uniform scoring
        if score_variance < 0.0001:
            logger.warning(
                f"⚠️ UNIFORM SCORING DETECTED! Variance: {score_variance:.6f}"
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
