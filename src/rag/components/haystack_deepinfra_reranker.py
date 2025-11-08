"""
Haystack-compatible wrapper for DeepInfra Qwen Reranker.

Integrates DeepInfraReranker into Haystack 2.x pipelines with standardized
Document input/output interface.
"""

from typing import List, Dict, Any, Optional
from haystack import component, Document
import logging

from src.rag.components.deepinfra_reranker import DeepInfraReranker

logger = logging.getLogger(__name__)


@component
class HaystackDeepInfraReranker:
    """
    Haystack 2.x compatible reranker using DeepInfra Qwen-8B.

    This component wraps DeepInfraReranker to work with Haystack's Document
    objects and pipeline architecture.

    Usage in pipeline:
        reranker = HaystackDeepInfraReranker(model="Qwen/Qwen3-Reranker-8B")
        pipeline.add_component("reranker", reranker)
        pipeline.connect("retriever.documents", "reranker.documents")
        pipeline.connect("query_preprocessor.query", "reranker.query")
    """

    def __init__(
        self,
        model: str = "Qwen/Qwen3-Reranker-8B",
        api_key: Optional[str] = None,
        top_k: int = 5,
        timeout: int = 30
    ):
        """
        Initialize Haystack-compatible DeepInfra reranker.

        Args:
            model: Qwen reranker model name
            api_key: DeepInfra API key (or DEEPINFRA_API_KEY env var)
            top_k: Number of top documents to return
            timeout: Request timeout in seconds
        """
        self.model = model
        self.top_k = top_k
        self.reranker = DeepInfraReranker(
            model=model,
            api_key=api_key,
            timeout=timeout
        )

        logger.info(
            f"Initialized Haystack DeepInfra reranker: {model}, top_k={top_k}"
        )

    @component.output_types(documents=List[Document])
    def run(
        self,
        query: str,
        documents: List[Document]
    ) -> Dict[str, Any]:
        """
        Rerank documents by relevance to query.

        Args:
            query: Search query
            documents: List of Haystack Document objects to rerank

        Returns:
            Dictionary with:
            - documents: Reranked Document objects (top_k)
            - scores: Relevance scores for each document
            - metadata: Reranking metadata (latency, variance, etc.)
        """
        if not documents:
            logger.warning("No documents to rerank")
            return {
                "documents": [],
                "scores": [],
                "metadata": {
                    "latency_ms": 0,
                    "score_variance": 0.0
                }
            }

        # Extract text content from Haystack Documents
        doc_texts = [doc.content for doc in documents]

        # Call DeepInfra reranker
        result = self.reranker.rerank(
            query=query,
            documents=doc_texts,
            top_k=None,  # Get all scores, then we'll take top_k
            return_documents=False
        )

        # Sort documents by reranker scores (descending)
        scored_docs = list(zip(documents, result.scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        # Take top_k
        top_docs = scored_docs[:self.top_k]
        reranked_documents = [doc for doc, score in top_docs]
        reranked_scores = [score for doc, score in top_docs]

        # Update Document scores
        for doc, score in zip(reranked_documents, reranked_scores):
            doc.score = float(score)

        logger.info(
            f"Reranked {len(documents)} docs to top {len(reranked_documents)} "
            f"in {result.latency_ms:.1f}ms. "
            f"Score variance: {result.score_variance:.6f}"
        )

        # Warn if uniform scoring detected
        if result.score_variance < 0.001:
            logger.warning(
                f"⚠️ Low score variance ({result.score_variance:.6f}) detected. "
                f"Reranker may not be differentiating documents effectively."
            )

        return {
            "documents": reranked_documents,
            "scores": reranked_scores,
            "metadata": {
                "model": result.model_name,
                "latency_ms": result.latency_ms,
                "score_variance": result.score_variance,
                "score_range": result.score_range,
                "input_docs": len(documents),
                "output_docs": len(reranked_documents)
            }
        }


def create_deepinfra_reranker(
    model: str = "Qwen/Qwen3-Reranker-8B",
    api_key: Optional[str] = None,
    top_k: int = 5
) -> HaystackDeepInfraReranker:
    """
    Factory function to create Haystack-compatible DeepInfra reranker.

    Args:
        model: Qwen reranker model name
        api_key: DeepInfra API key (or DEEPINFRA_API_KEY env var)
        top_k: Number of top documents to return

    Returns:
        HaystackDeepInfraReranker instance
    """
    return HaystackDeepInfraReranker(
        model=model,
        api_key=api_key,
        top_k=top_k
    )
