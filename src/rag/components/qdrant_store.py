"""Haystack QdrantDocumentStore wrapper for gov_uk_immigration collection"""
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

def create_qdrant_store(
    url: str = "http://localhost:6333",
    collection_name: str = "gov_uk_immigration",
    embedding_dim: int = 1024
) -> QdrantDocumentStore:
    """
    Create Haystack QdrantDocumentStore connected to gov_uk_immigration collection.
    
    Binary quantization is already configured on the collection (FR-006).
    This wrapper provides Haystack-compatible interface for retrieval.
    
    Args:
        url: Qdrant server URL
        collection_name: Collection name (default: gov_uk_immigration)
        embedding_dim: Vector dimensions (default: 1024 for e5-large-v2)
    
    Returns:
        QdrantDocumentStore instance connected to existing collection
    """
    store = QdrantDocumentStore(
        url=url,
        index=collection_name,
        embedding_dim=embedding_dim,
        recreate_index=False,  # Use existing collection
        return_embedding=True,
        wait_result_from_api=True
    )
    
    return store

if __name__ == "__main__":
    # Test connection
    store = create_qdrant_store()
    print(f"✅ Connected to Qdrant collection: gov_uk_immigration")
    print(f"   Documents in store: {store.count_documents()}")
