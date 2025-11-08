"""
Haystack 2.x retrieval pipeline for UK Immigration guidance RAG system.

This pipeline integrates all RAG components into a unified workflow:
- QueryPreprocessor: UKVI acronym expansion (FR-012)
- DeepInfraEmbedder: Remote embedding generation (FR-017)
- QdrantRetriever: Vector search with binary quantization (FR-006)
- BM25Ranker: Hybrid search with RRF (FR-010)
- DeepInfraReranker: Qwen-8B reranking via DeepInfra (Memory #61 fix)

Components are conditionally included based on feature flags:
- RAG_HYBRID_SEARCH_ENABLED: Include BM25 hybrid search
- RAG_RERANKING_ENABLED: Include Qwen-8B reranking
- RAG_QUERY_REWRITE_ENABLED: Include query preprocessing

Architecture aligns with Haystack Core specification and constitution.md principles.
"""

import os
from typing import List, Dict, Any, Optional
from haystack import Pipeline, Document
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever

from rag.components.qdrant_store import create_qdrant_store
from rag.components.deepinfra_embedder import DeepInfraEmbedder
from rag.components.bm25_ranker import BM25Ranker
from rag.components.haystack_deepinfra_reranker import create_deepinfra_reranker
from rag.components.query_preprocessor import QueryPreprocessor


class HaystackRetrievalPipeline:
    """
    Production RAG retrieval pipeline using Haystack 2.x framework.

    Pipeline architecture (with all features enabled):
    QueryPreprocessor → DeepInfraEmbedder → QdrantRetriever
                                          → BM25Ranker (hybrid search)
                                          → CrossEncoderRanker (reranking)
                                          → Results

    Feature flags control which components are active.
    """

    def __init__(
        self,
        qdrant_url: str = "http://localhost:6333",
        collection_name: str = "gov_uk_immigration",
        deepinfra_api_key: Optional[str] = None,
        whoosh_index_path: str = "/opt/gov-ai/data/bm25_index",
        enable_hybrid_search: bool = True,
        enable_reranking: bool = True,
        enable_query_rewrite: bool = True,
        top_k: int = 10,
        rerank_top_k: int = 5,
    ):
        """
        Initialize Haystack retrieval pipeline with conditional components.

        Args:
            qdrant_url: Qdrant server URL
            collection_name: Qdrant collection with binary quantization
            deepinfra_api_key: DeepInfra API key (or from DEEPINFRA_API_KEY env)
            whoosh_index_path: Path to existing Whoosh BM25 index
            enable_hybrid_search: Include BM25 hybrid search (RAG_HYBRID_SEARCH_ENABLED)
            enable_reranking: Include cross-encoder reranking (RAG_RERANKING_ENABLED)
            enable_query_rewrite: Include query preprocessing (RAG_QUERY_REWRITE_ENABLED)
            top_k: Number of documents to retrieve
            rerank_top_k: Number of documents after reranking
        """
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        self.whoosh_index_path = whoosh_index_path
        self.enable_hybrid_search = enable_hybrid_search
        self.enable_reranking = enable_reranking
        self.enable_query_rewrite = enable_query_rewrite
        self.top_k = top_k
        self.rerank_top_k = rerank_top_k

        # Get DeepInfra API key from env if not provided
        self.deepinfra_api_key = deepinfra_api_key or os.getenv("DEEPINFRA_API_KEY")
        if not self.deepinfra_api_key:
            raise ValueError(
                "DEEPINFRA_API_KEY environment variable or deepinfra_api_key parameter required"
            )

        # Build pipeline
        self.pipeline = self._build_pipeline()

    def _build_pipeline(self) -> Pipeline:
        """
        Build Haystack pipeline with conditional component inclusion.

        Pipeline wiring logic:
        1. If query_rewrite enabled: QueryPreprocessor → DeepInfraEmbedder
        2. DeepInfraEmbedder → Qdrant retriever (always required)
        3. If hybrid_search enabled: Qdrant results → BM25Ranker → fusion
        4. If reranking enabled: Results → CrossEncoderRanker → final results

        Returns:
            Configured Haystack Pipeline
        """
        pipeline = Pipeline()

        # Component 1: Query Preprocessing (conditional)
        if self.enable_query_rewrite:
            preprocessor = QueryPreprocessor(expand_acronyms=True)
            pipeline.add_component("query_preprocessor", preprocessor)

        # Component 2: DeepInfra Embedder (always required)
        embedder = DeepInfraEmbedder(
            api_key=self.deepinfra_api_key, model="intfloat/e5-large-v2", batch_size=10
        )
        pipeline.add_component("embedder", embedder)

        # Component 3: Qdrant Document Store (always required)
        document_store = create_qdrant_store(
            url=self.qdrant_url, collection_name=self.collection_name, embedding_dim=1024
        )

        # Component 4: Qdrant Retriever (always required)
        # Note: Haystack 2.x uses EmbeddingRetriever for Qdrant
        from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever

        retriever = QdrantEmbeddingRetriever(document_store=document_store, top_k=self.top_k)
        pipeline.add_component("retriever", retriever)

        # Component 5: BM25 Hybrid Search (conditional)
        if self.enable_hybrid_search:
            bm25_ranker = BM25Ranker(
                index_dir=self.whoosh_index_path,
                top_k=self.top_k * 5,  # 5x semantic top_k to ensure overlap
                weight=0.3,  # 30% BM25, 70% semantic (default from FR-010)
            )
            pipeline.add_component("bm25_ranker", bm25_ranker)

        # Component 6: DeepInfra Qwen-8B Reranking (conditional)
        # Winner of bakeoff: NDCG@10=0.992 (better than Cohere)
        # Fixes Memory #61 (cross-encoder uniform scoring issue)
        if self.enable_reranking:
            reranker = create_deepinfra_reranker(
                model="Qwen/Qwen3-Reranker-8B",
                api_key=self.deepinfra_api_key,
                top_k=self.rerank_top_k
            )
            pipeline.add_component("reranker", reranker)

        # Wire components together
        self._connect_components(pipeline)

        return pipeline

    def _connect_components(self, pipeline: Pipeline) -> None:
        """
        Connect pipeline components based on feature flags.

        Connection logic:
        - query_preprocessor.query → embedder.text
        - embedder.embedding → retriever.query_embedding
        - retriever.documents → bm25_ranker.documents (if hybrid)
        - bm25_ranker.documents → reranker.documents (if both hybrid + rerank)
        - retriever.documents → reranker.documents (if rerank only, no hybrid)

        Args:
            pipeline: Pipeline to wire
        """
        # Step 1: Query preprocessing → Embedder
        if self.enable_query_rewrite:
            pipeline.connect("query_preprocessor.query", "embedder.text")

        # Step 2: Embedder → Retriever (always)
        pipeline.connect("embedder.embedding", "retriever.query_embedding")

        # Step 3: Retriever → BM25 (if hybrid search enabled)
        if self.enable_hybrid_search:
            pipeline.connect("retriever.documents", "bm25_ranker.documents")

            # Wire query parameter to BM25Ranker (FR-010 hybrid search fix)
            if self.enable_query_rewrite:
                # Query comes from preprocessor
                pipeline.connect("query_preprocessor.query", "bm25_ranker.query")
            # Note: If no query_rewrite, query must be passed directly in run() call

            # Step 4a: BM25 → Reranker (if both hybrid + reranking)
            if self.enable_reranking:
                pipeline.connect("bm25_ranker.documents", "reranker.documents")
                # Wire query to reranker
                if self.enable_query_rewrite:
                    pipeline.connect("query_preprocessor.query", "reranker.query")

        # Step 4b: Retriever → Reranker (if reranking only, no hybrid)
        elif self.enable_reranking:
            pipeline.connect("retriever.documents", "reranker.documents")
            # Wire query to reranker
            if self.enable_query_rewrite:
                pipeline.connect("query_preprocessor.query", "reranker.query")

    def search(self, query: str) -> Dict[str, Any]:
        """
        Execute retrieval pipeline for a user query.

        Args:
            query: User's natural language question about UK immigration

        Returns:
            Dictionary with:
            - documents: List[Document] with ranked results
            - metadata: Pipeline execution metadata (latency, components used)

        Example:
            >>> pipeline = HaystackRetrievalPipeline()
            >>> results = pipeline.search("How do I apply for a UK work visa?")
            >>> for doc in results["documents"]:
            ...     print(f"{doc.meta['title']}: {doc.score}")
        """
        import time

        start_time = time.time()

        # Run pipeline
        pipeline_inputs = {}

        if self.enable_query_rewrite:
            # Start with query preprocessor
            pipeline_inputs["query_preprocessor"] = {"query": query}
        else:
            # Start with embedder directly
            pipeline_inputs["embedder"] = {"text": query}

            # If hybrid search enabled but no query preprocessor, pass query directly to BM25Ranker
            if self.enable_hybrid_search:
                pipeline_inputs["bm25_ranker"] = {"query": query}

            # If reranking enabled but no query preprocessor, pass query directly to reranker
            if self.enable_reranking:
                pipeline_inputs["reranker"] = {"query": query}

        result = self.pipeline.run(pipeline_inputs)

        elapsed_ms = (time.time() - start_time) * 1000

        # Extract final documents from result
        # Depending on pipeline configuration, documents come from different components
        if self.enable_reranking:
            documents = result["reranker"]["documents"]
        elif self.enable_hybrid_search:
            documents = result["bm25_ranker"]["documents"]
        else:
            documents = result["retriever"]["documents"]

        return {
            "documents": documents,
            "metadata": {
                "took_ms": elapsed_ms,
                "query_preprocessed": self.enable_query_rewrite,
                "hybrid_search_used": self.enable_hybrid_search,
                "reranking_used": self.enable_reranking,
                "total_results": len(documents),
            },
        }


def create_production_pipeline(
    qdrant_url: str = "http://localhost:6333", collection_name: str = "gov_uk_immigration"
) -> HaystackRetrievalPipeline:
    """
    Factory function to create production RAG pipeline with env-based feature flags.

    Feature flags (from environment variables):
    - RAG_HYBRID_SEARCH_ENABLED: Enable BM25 hybrid search (default: true)
    - RAG_RERANKING_ENABLED: Enable cross-encoder reranking (default: true)
    - RAG_QUERY_REWRITE_ENABLED: Enable query preprocessing (default: true)
    - RAG_TOP_K: Number of documents to retrieve (default: 10)
    - RAG_RERANK_TOP_K: Number of documents after reranking (default: 5)

    Args:
        qdrant_url: Qdrant server URL
        collection_name: Qdrant collection name

    Returns:
        Configured HaystackRetrievalPipeline

    Example:
        >>> pipeline = create_production_pipeline()
        >>> results = pipeline.search("What is the BNO visa?")
    """
    # Read feature flags from environment
    enable_hybrid = os.getenv("RAG_HYBRID_SEARCH_ENABLED", "true").lower() == "true"
    enable_rerank = os.getenv("RAG_RERANKING_ENABLED", "true").lower() == "true"
    enable_rewrite = os.getenv("RAG_QUERY_REWRITE_ENABLED", "true").lower() == "true"
    top_k = int(os.getenv("RAG_TOP_K", "10"))
    rerank_top_k = int(os.getenv("RAG_RERANK_TOP_K", "5"))

    pipeline = HaystackRetrievalPipeline(
        qdrant_url=qdrant_url,
        collection_name=collection_name,
        enable_hybrid_search=enable_hybrid,
        enable_reranking=enable_rerank,
        enable_query_rewrite=enable_rewrite,
        top_k=top_k,
        rerank_top_k=rerank_top_k,
    )

    return pipeline


if __name__ == "__main__":
    # Quick validation test
    import sys

    print("Building Haystack retrieval pipeline...")

    try:
        pipeline = create_production_pipeline()
        print(f"✅ Pipeline created successfully")
        print(f"   - Query preprocessing: {pipeline.enable_query_rewrite}")
        print(f"   - Hybrid search: {pipeline.enable_hybrid_search}")
        print(f"   - Reranking: {pipeline.enable_reranking}")
        print(f"   - Top-k: {pipeline.top_k}")

        # Test search
        print("\nTesting search with sample query...")
        results = pipeline.search("What is the BNO visa?")

        print(f"✅ Search completed in {results['metadata']['took_ms']:.0f}ms")
        print(f"   - Results: {results['metadata']['total_results']}")
        print(f"   - Hybrid search used: {results['metadata']['hybrid_search_used']}")
        print(f"   - Reranking used: {results['metadata']['reranking_used']}")

        if results["documents"]:
            print("\nTop result:")
            doc = results["documents"][0]
            print(f"   - Title: {doc.meta.get('title', 'N/A')}")
            print(f"   - Score: {doc.score:.4f}")
            print(f"   - Content preview: {doc.content[:200]}...")

        sys.exit(0)

    except Exception as e:
        print(f"❌ Pipeline creation failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
