"""Haystack component for DeepInfra API embeddings"""
import os
import requests
from typing import List, Dict, Any
from haystack import component, default_from_dict, default_to_dict
from tenacity import retry, stop_after_attempt, wait_exponential

@component
class DeepInfraEmbedder:
    """
    Haystack component for generating embeddings via DeepInfra API.
    
    Uses intfloat/e5-large-v2 model (1024 dimensions) for semantic search.
    Handles API rate limits with exponential backoff retry logic (FR-018).
    """
    
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "intfloat/e5-large-v2",
        batch_size: int = 32
    ):
        """
        Initialize DeepInfra embedder.
        
        Args:
            api_key: DeepInfra API key (defaults to DEEPINFRA_API_KEY env var)
            model: Model name (default: intfloat/e5-large-v2)
            batch_size: Batch size for API calls (FR-019: batching for throughput)
        """
        self.api_key = api_key or os.getenv("DEEPINFRA_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPINFRA_API_KEY not found in environment")
        
        self.model = model
        self.batch_size = batch_size
        self.api_url = "https://api.deepinfra.com/v1/inference"
    
    @component.output_types(embedding=List[float], meta=Dict[str, Any])
    def run(self, text: str) -> Dict[str, Any]:
        """
        Generate embedding for a single text query.
        
        Args:
            text: Query text to embed
        
        Returns:
            Dict with 'embedding' (1024-dim vector) and 'meta' (API metadata)
        """
        embedding = self._embed_batch([text])[0]
        return {
            "embedding": embedding,
            "meta": {"model": self.model, "text_length": len(text)}
        }
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a batch of texts with retry logic.
        
        Args:
            texts: List of texts to embed
        
        Returns:
            List of 1024-dim embedding vectors
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "inputs": texts
        }
        
        response = requests.post(
            f"{self.api_url}/{self.model}",
            json=payload,
            headers=headers,
            timeout=30
        )
        
        if response.status_code != 200:
            raise RuntimeError(
                f"DeepInfra API error {response.status_code}: {response.text}"
            )
        
        result = response.json()
        return result.get("embeddings", [])
    
    def to_dict(self) -> Dict[str, Any]:
        return default_to_dict(
            self,
            model=self.model,
            batch_size=self.batch_size
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeepInfraEmbedder":
        return default_from_dict(cls, data)

if __name__ == "__main__":
    # Test embedder
    embedder = DeepInfraEmbedder()
    result = embedder.run("How do I apply for a UK work visa?")
    print(f"✅ DeepInfra embedder working")
    print(f"   Embedding dim: {len(result['embedding'])}")
    print(f"   Model: {result['meta']['model']}")
