"""
RAG Service Layer - Haystack 2.x Pipeline Initialization and Query Execution

Implements T002 requirements:
- Initialize Qdrant client and Haystack components
- Warm up pipeline with test query
- Health check with PipelineHealthStatus
- Query execution with RAGQueryRequest → RAGQueryResponse

Architecture: Service layer between API routes and RAG components
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any, List
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse

from haystack import Pipeline
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever

from src.rag.components.qdrant_store import create_qdrant_store
from src.rag.components.deepinfra_embedder import DeepInfraEmbedder
from src.api.models.rag import RAGQuery, QueryResult, DocumentResult, HealthStatus

logger = logging.getLogger(__name__)


class RAGService:
    """
    RAG service layer managing Haystack pipeline lifecycle.

    Provides:
    - Lazy initialization with warmup query (T002)
    - Health check for monitoring (T002)
    - Query execution with error handling (T002)
    - Graceful degradation when Qdrant unavailable (T008)
    """

    def __init__(
        self,
        qdrant_url: str = "http://localhost:6333",
        collection_name: str = "gov_uk_immigration",
        embedding_dim: int = 1024,
    ):
        """
        Initialize RAG service with configuration.

        Args:
            qdrant_url: Qdrant server URL
            collection_name: Collection name (default: gov_uk_immigration)
            embedding_dim: Vector dimensions (default: 1024 for e5-large-v2)
        """
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        self.embedding_dim = embedding_dim

        # Components initialized in async initialize()
        self.qdrant_client: QdrantClient | None = None
        self.document_store = None
        self.embedder: DeepInfraEmbedder | None = None
        self.pipeline: Pipeline | None = None

        self.initialized = False
        self.initialization_time: datetime | None = None
        self.last_health_check: datetime | None = None

        logger.info(f"RAGService created (collection: {collection_name})")

    async def initialize(self) -> None:
        """
        Initialize RAG pipeline components and warm up with test query.

        Steps:
        1. Create Qdrant client and document store
        2. Initialize DeepInfra embedder
        3. Build Haystack retrieval pipeline
        4. Execute warmup query to test end-to-end

        Raises:
            RuntimeError: If initialization fails
        """
        if self.initialized:
            logger.warning("RAG service already initialized, skipping")
            return

        start_time = time.time()
        logger.info("Initializing RAG pipeline...")

        try:
            # Step 1: Initialize Qdrant client
            self.qdrant_client = QdrantClient(url=self.qdrant_url)
            logger.info(f"✓ Qdrant client connected: {self.qdrant_url}")

            # Step 2: Create Haystack document store
            self.document_store = create_qdrant_store(
                url=self.qdrant_url,
                collection_name=self.collection_name,
                embedding_dim=self.embedding_dim,
            )
            doc_count = self.document_store.count_documents()
            logger.info(f"✓ Document store connected: {doc_count} documents")

            # Step 3: Initialize DeepInfra embedder
            self.embedder = DeepInfraEmbedder()
            logger.info("✓ DeepInfra embedder initialized")

            # Step 4: Build retrieval pipeline
            self.pipeline = Pipeline()

            # Add embedder component
            self.pipeline.add_component("text_embedder", self.embedder)

            # Add retriever component
            retriever = QdrantEmbeddingRetriever(document_store=self.document_store)
            self.pipeline.add_component("retriever", retriever)

            # Connect components
            self.pipeline.connect("text_embedder.embedding", "retriever.query_embedding")

            logger.info("✓ Haystack pipeline built")

            # Step 5: Warmup query
            warmup_query = "UK visa requirements"
            logger.info(f"Running warmup query: '{warmup_query}'")

            warmup_result = self.pipeline.run({
                "text_embedder": {"text": warmup_query},
                "retriever": {"top_k": 3}
            })

            warmup_docs = warmup_result.get("retriever", {}).get("documents", [])
            logger.info(f"✓ Warmup complete: {len(warmup_docs)} results")

            # Mark as initialized
            self.initialized = True
            self.initialization_time = datetime.utcnow()

            elapsed = time.time() - start_time
            logger.info(f"✅ RAG pipeline initialized successfully ({elapsed:.2f}s)")

        except Exception as e:
            logger.error(f"❌ RAG pipeline initialization failed: {e}")
            self.initialized = False
            raise RuntimeError(f"Failed to initialize RAG pipeline: {e}") from e

    async def health_check(self) -> HealthStatus:
        """
        Check RAG pipeline health status.

        Returns:
            HealthStatus with:
            - status: healthy, degraded, unhealthy
            - document_count: Number of documents in Qdrant
            - quantization_active: Binary quantization enabled (T001)
            - qdrant_status, deepinfra_status, pipeline_components

        Raises:
            RuntimeError: If health check encounters fatal error
        """
        self.last_health_check = datetime.utcnow()

        status = "unknown"
        document_count = 0
        quantization_active = False
        compression_ratio = 0.0
        memory_mb = 0.0
        qdrant_status = "disconnected"
        deepinfra_status = "unknown"
        bm25_index_status = "unknown"
        pipeline_components: List[str] = []

        try:
            # Check Qdrant connection
            if self.qdrant_client:
                try:
                    collection_info = self.qdrant_client.get_collection(self.collection_name)
                    document_count = collection_info.points_count
                    qdrant_status = "connected"

                    # Check binary quantization (T001)
                    quant_config = collection_info.config.quantization_config
                    if quant_config and hasattr(quant_config, 'binary'):
                        quantization_active = True
                        # Binary quantization provides 97% compression
                        compression_ratio = 0.97
                        # Estimated memory: vectors_count * embedding_dim * 0.03
                        memory_mb = (document_count * self.embedding_dim * 4 * 0.03) / (1024 * 1024)
                    else:
                        # No quantization: full float32
                        compression_ratio = 0.0
                        memory_mb = (document_count * self.embedding_dim * 4) / (1024 * 1024)

                    logger.debug(f"Qdrant: {document_count} docs, quantization={quantization_active}")

                except UnexpectedResponse as e:
                    logger.error(f"Qdrant error: {e}")
                    qdrant_status = "error"

            # Check DeepInfra embedder
            if self.embedder:
                deepinfra_status = "available"

            # Check pipeline components
            if self.pipeline:
                pipeline_components = list(self.pipeline.graph.nodes.keys())

            # Determine overall status
            if qdrant_status == "connected" and self.initialized:
                status = "healthy"
            elif qdrant_status == "connected" and not self.initialized:
                status = "degraded"
            else:
                status = "unhealthy"

            return HealthStatus(
                status=status,
                document_count=document_count,
                quantization_active=quantization_active,
                compression_ratio=compression_ratio,
                memory_mb=memory_mb,
                qdrant_status=qdrant_status,
                deepinfra_status=deepinfra_status,
                bm25_index_status=bm25_index_status,
                pipeline_components=pipeline_components,
                last_check=self.last_health_check,
            )

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            # Return unhealthy status instead of raising
            return HealthStatus(
                status="unhealthy",
                document_count=0,
                quantization_active=False,
                compression_ratio=0.0,
                memory_mb=0.0,
                qdrant_status="error",
                deepinfra_status="unknown",
                bm25_index_status="unknown",
                pipeline_components=[],
                last_check=self.last_health_check,
            )

    async def query(self, request: RAGQuery) -> QueryResult:
        """
        Execute RAG query using Haystack pipeline.

        Args:
            request: RAGQuery with query string, top_k, filters

        Returns:
            QueryResult with ranked document results, took_ms, metadata

        Raises:
            RuntimeError: If pipeline not initialized
            ValueError: If query is invalid
        """
        if not self.initialized or not self.pipeline:
            raise RuntimeError(
                "RAG pipeline not initialized. Please check health endpoint or wait for startup."
            )

        start_time = time.time()
        logger.info(f"Executing query: '{request.query[:50]}...' (top_k={request.top_k})")

        try:
            # Execute pipeline
            result = self.pipeline.run({
                "text_embedder": {"text": request.query},
                "retriever": {"top_k": request.top_k}
            })

            # Extract documents from retriever output
            documents = result.get("retriever", {}).get("documents", [])

            # Convert to DocumentResult models
            results: List[DocumentResult] = []
            for doc in documents:
                # Extract content with fallback handling
                content = doc.content
                if content is None and doc.meta:
                    # Try to get content from metadata
                    content = doc.meta.get('text') or doc.meta.get('content')
                if content is None:
                    # Fallback: use title or URL as minimal content
                    title = doc.meta.get("title") if doc.meta else None
                    url = doc.meta.get("url") if doc.meta else None
                    content = title or url or "[No content available]"

                # Skip documents with no meaningful content
                if not content or content == "[No content available]":
                    logger.warning(f"Skipping document with no content: {doc.meta.get('url') if doc.meta else 'unknown'}")
                    continue

                results.append(DocumentResult(
                    content=content,
                    score=doc.score if hasattr(doc, 'score') and doc.score else 0.5,
                    metadata=doc.meta or {},
                    title=doc.meta.get("title") if doc.meta else None,
                    url=doc.meta.get("url") if doc.meta else None,
                    published_date=doc.meta.get("published_date") if doc.meta else None,
                    document_type=doc.meta.get("document_type") if doc.meta else None,
                ))

            took_ms = (time.time() - start_time) * 1000

            logger.info(f"Query complete: {len(results)} results ({took_ms:.1f}ms)")

            return QueryResult(
                results=results,
                took_ms=took_ms,
                total_results=len(results),
                query_preprocessed=False,
                hybrid_search_used=False,
                reranking_used=False,
            )

        except Exception as e:
            took_ms = (time.time() - start_time) * 1000
            logger.error(f"Query failed after {took_ms:.1f}ms: {e}")
            raise RuntimeError(f"Query execution failed: {e}") from e


# Global singleton instance
_rag_service: RAGService | None = None


def get_rag_service() -> RAGService:
    """
    Get singleton RAG service instance.

    Returns:
        RAGService instance
    """
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service
