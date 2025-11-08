"""
Neo4J Graph Retriever - Graph Traversal for Immigration RAG

Implements NEO4J-001 specification:
- Direct entity search in Neo4J graph
- Relationship expansion (REQUIRES, SATISFIED_BY, etc.)
- Multi-hop graph traversal (max depth configurable)
- Hybrid scoring combining graph centrality and vector similarity
- Explainability through graph path tracking

Architecture:
- Retrieval strategies: Direct match, relationship expansion, multi-hop
- Scoring: Graph centrality boost, hop count penalties
- Integration with Haystack pipeline for hybrid RAG
"""

import logging
import re
from typing import List, Dict, Any, Optional
from haystack import component, Document
from neo4j import GraphDatabase, Driver
import spacy
from spacy.language import Language

logger = logging.getLogger(__name__)


@component
class Neo4JGraphRetriever:
    """
    Retrieve documents using graph traversal to augment vector search.

    Traversal strategies:
    1. Direct entity match: Find documents containing queried entities
    2. Relationship expansion: Traverse REQUIRES, SATISFIED_BY, etc.
    3. Multi-hop reasoning: Follow relationship chains (max depth)
    4. Hybrid scoring: Combine graph centrality with vector similarity
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        neo4j_database: str = "neo4j",
        max_depth: int = 3,
        top_k: int = 10,
        spacy_model: str = "en_core_web_lg",
    ):
        """
        Initialize Neo4J graph retriever.

        Args:
            neo4j_uri: Neo4J connection URI (bolt://localhost:7687)
            neo4j_user: Neo4J username
            neo4j_password: Neo4J password
            neo4j_database: Neo4J database name
            max_depth: Maximum traversal depth for multi-hop reasoning
            top_k: Number of documents to retrieve
            spacy_model: SpaCy model for query entity extraction
        """
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.neo4j_database = neo4j_database
        self.max_depth = max_depth
        self.top_k = top_k

        # Initialize Neo4J driver
        self.driver: Optional[Driver] = None
        self._connect_neo4j()

        # Initialize SpaCy for query entity extraction
        try:
            self.nlp: Optional[Language] = spacy.load(spacy_model)
            logger.info(f"✓ SpaCy model loaded: {spacy_model}")
        except OSError:
            logger.warning(
                f"SpaCy model {spacy_model} not found. "
                "Query entity extraction will use simple keyword matching. "
                "Install with: python -m spacy download en_core_web_lg"
            )
            self.nlp = None

        logger.info(f"Neo4JGraphRetriever initialized (max_depth={max_depth}, top_k={top_k})")

    def _connect_neo4j(self) -> None:
        """Establish Neo4J connection."""
        try:
            self.driver = GraphDatabase.driver(
                self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password)
            )
            # Verify connection
            self.driver.verify_connectivity()
            logger.info(f"✓ Neo4J connected: {self.neo4j_uri}")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4J: {e}")
            self.driver = None
            raise RuntimeError(f"Neo4J connection failed: {e}") from e

    def close(self) -> None:
        """Close Neo4J driver connection."""
        if self.driver:
            self.driver.close()
            logger.info("Neo4J driver closed")

    @component.output_types(documents=List[Document], graph_paths=List[Dict[str, Any]])
    def run(self, query: str, entities: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Retrieve documents using graph traversal.

        Args:
            query: User query text
            entities: Extracted entities from query (optional, will extract if not provided)

        Returns:
            documents: Retrieved Haystack Document objects
            graph_paths: Explanation of graph traversal paths taken
        """
        if not self.driver:
            raise RuntimeError("Neo4J driver not initialized")

        # Extract entities from query if not provided
        if not entities:
            entities = self._extract_query_entities(query)

        if not entities:
            logger.warning(f"No entities extracted from query: '{query}'")
            return {"documents": [], "graph_paths": []}

        logger.info(f"Graph retrieval for entities: {entities}")

        # Strategy 1: Direct entity match
        direct_docs = self._direct_entity_search(entities)

        # Strategy 2: Relationship expansion
        expanded_docs = self._relationship_expansion(entities)

        # Strategy 3: Multi-hop reasoning
        multihop_docs = self._multihop_traversal(entities)

        # Merge and rank results
        all_docs = self._merge_and_rank(direct_docs, expanded_docs, multihop_docs)

        # Get top-k results
        top_docs = all_docs[: self.top_k]

        # Generate explanation paths
        graph_paths = self._generate_explanation_paths(top_docs)

        logger.info(f"Retrieved {len(top_docs)} documents via graph traversal")

        return {"documents": top_docs, "graph_paths": graph_paths}

    def _direct_entity_search(self, entities: List[str]) -> List[Document]:
        """Find documents directly containing queried entities."""
        if not self.driver:
            return []

        try:
            with self.driver.session(database=self.neo4j_database) as session:
                query = """
                UNWIND $entities AS entity_text
                MATCH (e:Entity)
                WHERE toLower(e.text) CONTAINS toLower(entity_text)
                   OR toLower(e.name) CONTAINS toLower(entity_text)
                MATCH (d)-[:CONTAINS_ENTITY]->(e)
                RETURN DISTINCT d.id AS doc_id,
                       collect(DISTINCT e.text)[..5] AS matched_entities,
                       count(DISTINCT e) AS entity_count
                ORDER BY entity_count DESC
                LIMIT 20
                """
                result = session.run(query, entities=entities)
                documents = self._result_to_documents(result, strategy="direct")

                logger.debug(f"Direct search found {len(documents)} documents")
                return documents

        except Exception as e:
            logger.error(f"Direct entity search error: {e}")
            return []

    def _relationship_expansion(self, entities: List[str]) -> List[Document]:
        """
        Expand search using entity relationships.

        Example: Query mentions "Skilled Worker visa" → Find REQUIRES relationships
        → Retrieve documents about those requirements.
        """
        if not self.driver:
            return []

        try:
            with self.driver.session(database=self.neo4j_database) as session:
                query = """
                UNWIND $entities AS entity_text
                MATCH (e:Entity)
                WHERE toLower(e.text) CONTAINS toLower(entity_text)
                   OR toLower(e.name) CONTAINS toLower(entity_text)
                MATCH (e)-[r:REQUIRES|SATISFIED_BY|DEPENDS_ON|APPLIES_IF|CAN_TRANSITION_TO]-(related:Entity)
                MATCH (d)-[:CONTAINS_ENTITY]->(related)
                RETURN DISTINCT d.id AS doc_id,
                       e.text AS source_entity,
                       type(r) AS relationship,
                       related.text AS target_entity,
                       collect(DISTINCT related.text)[..3] AS related_entities
                LIMIT 20
                """
                result = session.run(query, entities=entities)
                documents = self._result_to_documents(result, strategy="expanded")

                logger.debug(f"Relationship expansion found {len(documents)} documents")
                return documents

        except Exception as e:
            logger.error(f"Relationship expansion error: {e}")
            return []

    def _multihop_traversal(self, entities: List[str]) -> List[Document]:
        """
        Multi-hop graph traversal for complex queries.

        Example: "What documents are needed for spouse visa if I previously had student visa?"
        → Find Student visa entity
        → Traverse CAN_TRANSITION_TO → Spouse visa
        → Traverse REQUIRES → Requirements
        → Traverse SATISFIED_BY → Document types
        → Return documents about those document types
        """
        if not self.driver:
            return []

        try:
            with self.driver.session(database=self.neo4j_database) as session:
                query = f"""
                UNWIND $entities AS entity_text
                MATCH (start:Entity)
                WHERE toLower(start.text) CONTAINS toLower(entity_text)
                   OR toLower(start.name) CONTAINS toLower(entity_text)
                MATCH path = (start)-[*1..{self.max_depth}]-(end:Entity)
                MATCH (d)-[:CONTAINS_ENTITY]->(end)
                RETURN DISTINCT d.id AS doc_id,
                       [node IN nodes(path) | node.text][..5] AS traversal_path,
                       [rel IN relationships(path) | type(rel)][..5] AS relationship_types,
                       length(path) AS hop_count
                ORDER BY hop_count ASC
                LIMIT 20
                """
                result = session.run(query, entities=entities)
                documents = self._result_to_documents(result, strategy="multihop")

                logger.debug(f"Multi-hop traversal found {len(documents)} documents")
                return documents

        except Exception as e:
            logger.error(f"Multi-hop traversal error: {e}")
            return []

    def _merge_and_rank(
        self,
        direct: List[Document],
        expanded: List[Document],
        multihop: List[Document],
    ) -> List[Document]:
        """
        Merge results from different strategies and rank by combined score.

        Scoring:
        - Direct match: 1.0 base score
        - Relationship expansion: 0.8 base score
        - Multi-hop: 0.6 / hop_count base score
        - Boost: Graph centrality (if available in metadata)
        """
        doc_scores: Dict[str, float] = {}
        doc_map: Dict[str, Document] = {}

        # Score direct matches
        for doc in direct:
            doc_scores[doc.id] = doc_scores.get(doc.id, 0.0) + 1.0
            doc_map[doc.id] = doc

        # Score relationship expansion
        for doc in expanded:
            doc_scores[doc.id] = doc_scores.get(doc.id, 0.0) + 0.8
            if doc.id not in doc_map:
                doc_map[doc.id] = doc

        # Score multi-hop with hop count penalty
        for doc in multihop:
            hop_count = doc.meta.get("hop_count", 1) if doc.meta else 1
            score = 0.6 / max(hop_count, 1)
            doc_scores[doc.id] = doc_scores.get(doc.id, 0.0) + score
            if doc.id not in doc_map:
                doc_map[doc.id] = doc

        # Sort by score and return documents
        sorted_doc_ids = sorted(doc_scores.keys(), key=lambda d: doc_scores[d], reverse=True)

        # Update documents with final scores
        ranked_docs = []
        for doc_id in sorted_doc_ids:
            doc = doc_map[doc_id]
            # Set score in metadata
            if not doc.meta:
                doc.meta = {}
            doc.meta["graph_score"] = doc_scores[doc_id]
            ranked_docs.append(doc)

        return ranked_docs

    def _generate_explanation_paths(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """Generate human-readable explanation of graph traversal."""
        paths = []

        for doc in documents:
            if not doc.meta:
                continue

            path_info = {
                "document_id": doc.id,
                "strategy": doc.meta.get("retrieval_strategy", "unknown"),
                "graph_score": doc.meta.get("graph_score", 0.0),
            }

            # Add traversal path if available
            if "traversal_path" in doc.meta:
                path_info["traversal_path"] = doc.meta["traversal_path"]
                path_info["relationship_types"] = doc.meta.get("relationship_types", [])
                path_info["hop_count"] = doc.meta.get("hop_count", 0)

            # Add matched entities if available
            if "matched_entities" in doc.meta:
                path_info["matched_entities"] = doc.meta["matched_entities"]

            paths.append(path_info)

        return paths

    def _extract_query_entities(self, query: str) -> List[str]:
        """
        Extract entities from user query using SpaCy NER or keyword matching.

        Args:
            query: User query text

        Returns:
            List of extracted entity strings
        """
        entities = []

        # Strategy 1: SpaCy NER
        if self.nlp:
            try:
                doc = self.nlp(query)
                for ent in doc.ents:
                    if ent.label_ in ["ORG", "GPE", "PERSON", "DATE", "MONEY"]:
                        entities.append(ent.text)
            except Exception as e:
                logger.error(f"SpaCy entity extraction error: {e}")

        # Strategy 2: Keyword matching for visa types and document types
        visa_pattern = re.compile(
            r"(Skilled Worker|Student|Family|Tourist|Entrepreneur|Graduate|Parent|Partner|Settlement)",
            re.IGNORECASE,
        )
        doc_pattern = re.compile(
            r"(passport|bank statement|marriage certificate|degree|IELTS|English test)",
            re.IGNORECASE,
        )

        visa_matches = visa_pattern.findall(query)
        doc_matches = doc_pattern.findall(query)

        entities.extend(visa_matches)
        entities.extend(doc_matches)

        # Remove duplicates while preserving order
        seen = set()
        unique_entities = []
        for entity in entities:
            entity_lower = entity.lower()
            if entity_lower not in seen:
                seen.add(entity_lower)
                unique_entities.append(entity)

        return unique_entities

    def _result_to_documents(self, result, strategy: str = "unknown") -> List[Document]:
        """
        Convert Neo4J query results to Haystack Documents.

        Args:
            result: Neo4J query result
            strategy: Retrieval strategy name (direct, expanded, multihop)

        Returns:
            List of Haystack Document objects
        """
        docs = []

        try:
            for record in result:
                doc_id = record.get("doc_id")
                if not doc_id:
                    continue

                # Build metadata from available fields
                meta = {
                    "retrieval_strategy": strategy,
                }

                # Add optional fields
                if "matched_entities" in record:
                    meta["matched_entities"] = record["matched_entities"]

                if "traversal_path" in record:
                    meta["traversal_path"] = record["traversal_path"]

                if "relationship_types" in record:
                    meta["relationship_types"] = record["relationship_types"]

                if "hop_count" in record:
                    meta["hop_count"] = record["hop_count"]

                if "source_entity" in record:
                    meta["source_entity"] = record["source_entity"]

                if "target_entity" in record:
                    meta["target_entity"] = record["target_entity"]

                if "relationship" in record:
                    meta["relationship"] = record["relationship"]

                if "related_entities" in record:
                    meta["related_entities"] = record["related_entities"]

                # Create document (content will be fetched from Qdrant later)
                doc = Document(
                    id=doc_id,
                    content="",  # Content fetched from Qdrant using chunk_ids
                    meta=meta,
                )

                docs.append(doc)

        except Exception as e:
            logger.error(f"Error converting Neo4J results to documents: {e}")

        return docs


# Singleton instance management
_graph_retriever: Optional[Neo4JGraphRetriever] = None


def get_graph_retriever(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str = "neo4j",
    max_depth: int = 3,
    top_k: int = 10,
) -> Neo4JGraphRetriever:
    """
    Get singleton graph retriever instance.

    Args:
        neo4j_uri: Neo4J connection URI
        neo4j_user: Neo4J username
        neo4j_password: Neo4J password
        neo4j_database: Neo4J database name
        max_depth: Maximum traversal depth
        top_k: Number of documents to retrieve

    Returns:
        Neo4JGraphRetriever instance
    """
    global _graph_retriever
    if _graph_retriever is None:
        _graph_retriever = Neo4JGraphRetriever(
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
            neo4j_database=neo4j_database,
            max_depth=max_depth,
            top_k=top_k,
        )
    return _graph_retriever
