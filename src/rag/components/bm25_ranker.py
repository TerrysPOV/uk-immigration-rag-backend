"""Haystack component for BM25 ranking using existing Whoosh index"""
import os
from typing import List, Dict, Any, Optional
from haystack import component, Document
from whoosh.index import open_dir
from whoosh.qparser import QueryParser

@component
class BM25Ranker:
    """
    Haystack component for BM25 hybrid search using existing Whoosh index.
    
    Preserves existing 773-document Whoosh BM25 index (FR-010).
    Uses Reciprocal Rank Fusion (RRF) to combine BM25 + semantic scores.
    """
    
    def __init__(
        self,
        index_dir: str = "/opt/gov-ai/data/bm25_index",
        weight: float = 0.3,
        top_k: int = 50
    ):
        """
        Initialize BM25 ranker with existing Whoosh index.
        
        Args:
            index_dir: Path to Whoosh BM25 index directory
            weight: RRF weight for BM25 scores (0.3 = 30% BM25, 70% semantic)
            top_k: Number of BM25 candidates to retrieve
        """
        if not os.path.exists(index_dir):
            raise ValueError(f"BM25 index not found at {index_dir}")
        
        self.index = open_dir(index_dir)
        self.weight = weight
        self.top_k = top_k
    
    @component.output_types(documents=List[Document])
    def run(
        self,
        query: str,
        documents: List[Document],
        top_k: Optional[int] = None
    ) -> Dict[str, List[Document]]:
        """
        Re-rank documents using BM25 + semantic scores via RRF.
        
        Args:
            query: User query text
            documents: Documents from semantic retrieval
            top_k: Override top_k for this query
        
        Returns:
            Dict with 'documents' re-ranked by RRF(BM25, semantic)
        """
        k = top_k or self.top_k
        
        # Get BM25 scores
        bm25_results = self._search_bm25(query, k)
        
        # Merge with semantic results using RRF
        reranked = self._reciprocal_rank_fusion(
            semantic_docs=documents,
            bm25_results=bm25_results,
            weight=self.weight
        )
        
        return {"documents": reranked[:k]}
    
    def _search_bm25(self, query_text: str, top_k: int) -> List[Dict[str, Any]]:
        """Search Whoosh BM25 index"""
        with self.index.searcher() as searcher:
            query = QueryParser("content", self.index.schema).parse(query_text)
            results = searcher.search(query, limit=top_k)
            
            return [
                {
                    "document_id": r["document_id"],
                    "score": r.score,
                    "rank": i
                }
                for i, r in enumerate(results)
            ]
    
    def _reciprocal_rank_fusion(
        self,
        semantic_docs: List[Document],
        bm25_results: List[Dict[str, Any]],
        weight: float,
        k: int = 60
    ) -> List[Document]:
        """
        Combine rankings using Reciprocal Rank Fusion.
        
        RRF score = weight * (1/(k + bm25_rank)) + (1-weight) * (1/(k + semantic_rank))
        """
        # Create BM25 lookup
        bm25_lookup = {r["document_id"]: r["rank"] for r in bm25_results}
        
        # Calculate RRF scores
        scored_docs = []
        for sem_rank, doc in enumerate(semantic_docs):
            doc_id = doc.meta.get("document_id", "")
            
            # Semantic component
            sem_score = (1 - weight) * (1 / (k + sem_rank))
            
            # BM25 component (if document found in BM25 results)
            bm25_rank = bm25_lookup.get(doc_id, 999)
            bm25_score = weight * (1 / (k + bm25_rank))
            
            # Combined RRF score
            rrf_score = sem_score + bm25_score
            
            scored_docs.append((rrf_score, doc))
        
        # Sort by RRF score descending
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        
        return [doc for score, doc in scored_docs]

if __name__ == "__main__":
    print(f"✅ BM25Ranker component ready")
    print(f"   Index location: /opt/gov-ai/data/bm25_index")
