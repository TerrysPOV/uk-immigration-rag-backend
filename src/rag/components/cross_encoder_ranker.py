"""Cross-encoder reranker using Haystack TransformersSimilarityRanker"""
from haystack.components.rankers import TransformersSimilarityRanker
from haystack.utils.device import ComponentDevice

def create_cross_encoder_ranker(
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    top_k: int = 10,
    device: str = "cpu"
):
    """
    Create Haystack TransformersSimilarityRanker for cross-encoder reranking.
    
    Preserves existing reranking functionality (FR-011) using same model.
    Controlled by RAG_RERANKING_ENABLED environment variable.
    
    Args:
        model: Cross-encoder model name (default: ms-marco-MiniLM-L-6-v2)
        top_k: Number of top results to return after reranking
        device: Device for inference (default: cpu) - converted to ComponentDevice
    
    Returns:
        TransformersSimilarityRanker instance ready for use in pipeline
    """
    # Convert string device to ComponentDevice
    component_device = ComponentDevice.from_str(device) if isinstance(device, str) else device
    
    ranker = TransformersSimilarityRanker(
        model=model,
        top_k=top_k,
        device=component_device
    )
    
    return ranker

if __name__ == "__main__":
    print(f"✅ Cross-encoder reranker ready")
    print(f"   Model: cross-encoder/ms-marco-MiniLM-L-6-v2")
    print(f"   Top-k: 10")
