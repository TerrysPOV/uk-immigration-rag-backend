"""Haystack component for UKVI query preprocessing and acronym expansion"""
from typing import Dict, List
from haystack import component

# UKVI-specific acronym expansions
UKVI_ACRONYMS = {
    "BNO": "British National (Overseas)",
    "EEA": "European Economic Area",
    "EUSS": "EU Settlement Scheme",
    "ILR": "Indefinite Leave to Remain",
    "CoS": "Certificate of Sponsorship",
    "PBS": "Points-Based System",
    "UKVI": "UK Visas and Immigration",
    "HO": "Home Office",
    "CTA": "Common Travel Area",
    "BRP": "Biometric Residence Permit"
}

@component
class QueryPreprocessor:
    """
    Haystack component for query preprocessing and UKVI acronym expansion.
    
    Preserves existing query rewriting functionality (FR-012).
    Expands UKVI-specific acronyms to improve semantic search.
    Controlled by RAG_QUERY_REWRITE_ENABLED environment variable.
    """
    
    def __init__(self, expand_acronyms: bool = True):
        """
        Initialize query preprocessor.
        
        Args:
            expand_acronyms: Whether to expand UKVI acronyms (default: True)
        """
        self.expand_acronyms = expand_acronyms
        self.acronyms = UKVI_ACRONYMS
    
    @component.output_types(query=str, original_query=str)
    def run(self, query: str) -> Dict[str, str]:
        """
        Preprocess query by expanding acronyms.
        
        Args:
            query: Original user query
        
        Returns:
            Dict with 'query' (preprocessed) and 'original_query'
        """
        original = query
        processed = query
        
        if self.expand_acronyms:
            processed = self._expand_acronyms(query)
        
        return {
            "query": processed,
            "original_query": original
        }
    
    def _expand_acronyms(self, text: str) -> str:
        """
        Expand UKVI acronyms in query text.
        
        Examples:
            "BNO visa" → "British National (Overseas) visa"
            "EEA citizens" → "European Economic Area citizens"
        """
        expanded = text
        
        # Replace acronyms (case-insensitive, whole word only)
        for acronym, expansion in self.acronyms.items():
            # Match whole words only using word boundaries
            import re
            pattern = r'\b' + re.escape(acronym) + r'\b'
            expanded = re.sub(pattern, expansion, expanded, flags=re.IGNORECASE)
        
        return expanded

if __name__ == "__main__":
    # Test query preprocessor
    preprocessor = QueryPreprocessor()
    
    test_queries = [
        "How do I apply for a BNO visa?",
        "What are EEA citizen rights?",
        "ILR requirements for skilled workers"
    ]
    
    print("✅ QueryPreprocessor component ready\n")
    for q in test_queries:
        result = preprocessor.run(q)
        print(f"Original: {q}")
        print(f"Expanded: {result['query']}\n")
