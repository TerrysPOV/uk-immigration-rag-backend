# Neo4J Knowledge Graph Extraction & Traversal - Feature Specification

**Feature ID**: NEO4J-001
**Status**: Planned
**Priority**: Phase 4 - Advanced RAG Capabilities
**Complexity**: 10/10
**Estimated Duration**: 6-8 weeks

---

## Executive Summary

Enhance the UK Immigration RAG system with Neo4J-based knowledge graph extraction and traversal capabilities to augment vector similarity search with structured relationship navigation, improving answer quality for complex multi-hop queries.

### Business Value
- **Complex Query Resolution**: Answer questions requiring multi-entity reasoning (e.g., "What documents are needed for spouse visa if applicant has prior UK student visa?")
- **Relationship Discovery**: Surface implicit connections between visa types, requirements, and processes
- **Explainability**: Provide graph-based evidence chains for decisions
- **Reusability**: Portable graph extraction pipeline for other document-based RAG systems

---

## Current State Analysis

### Existing RAG Pipeline (Haystack Core)
```python
# Current retrieval: Vector similarity + BM25 keyword search
pipeline = Pipeline()
pipeline.add_component("text_embedder", embedder)
pipeline.add_component("retriever", QdrantRetriever)
pipeline.add_component("reranker", DeepInfraReranker)
```

**Limitations**:
- No explicit entity/relationship modeling
- Cannot traverse document cross-references (e.g., "see Section 3.2", "as defined in Appendix B")
- No hierarchical visa category navigation
- Similarity search may miss structurally related but semantically distant content

### Neo4J MCP Server (Development Only)
- **Current Use**: Project memory tracking only (security fixes, deployment status)
- **NOT Used**: Document content extraction or RAG retrieval
- **Location**: `bolt://localhost:7687` (local development)

---

## Technical Architecture

### 1. Neo4J Graph Schema

#### Node Types
```cypher
// Document nodes
(:Document {
    id: string,              // Unique document ID
    title: string,           // Document title
    url: string,             // GOV.UK source URL
    chunk_ids: [string],     // Qdrant vector IDs
    last_updated: datetime   // Publication date
})

// Entity nodes (extracted from documents)
(:VisaType {
    name: string,            // "Skilled Worker", "Family", "Student"
    code: string,            // Official visa code (e.g., "T2")
    tier: string,            // Tier classification
    chunk_ids: [string]      // Qdrant chunks mentioning this visa
})

(:Requirement {
    id: string,              // Unique requirement ID
    text: string,            // Requirement description
    category: string,        // "financial", "documents", "english", "health"
    mandatory: boolean,      // Required vs optional
    chunk_ids: [string]      // Evidence chunks
})

(:Document_Type {
    name: string,            // "Passport", "Bank Statement", "Marriage Certificate"
    accepted_formats: [string],  // ["original", "certified_copy"]
    validity_period: string,     // "6 months", "12 months"
    chunk_ids: [string]
})

(:Organization {
    name: string,            // "Home Office", "UK Visas and Immigration"
    role: string,            // "issuing_authority", "sponsor"
    chunk_ids: [string]
})

(:Country {
    name: string,            // "United Kingdom", "India"
    code: string,            // ISO 3166-1 alpha-2
    chunk_ids: [string]
})

// Procedural nodes
(:Process {
    id: string,              // "visa_application_submission"
    name: string,            // "Submit Visa Application Online"
    steps: [string],         // Ordered list of steps
    duration_estimate: string,  // "2-3 weeks"
    chunk_ids: [string]
})

(:Condition {
    id: string,              // "previous_visa_holder"
    text: string,            // "If applicant held previous UK visa"
    applies_to: [string],    // Visa types this condition affects
    chunk_ids: [string]
})
```

#### Relationship Types
```cypher
// Document relationships
(:Document)-[:REFERENCES]->(:Document)         // Cross-document citations
(:Document)-[:SUPERSEDES]->(:Document)         // Version history
(:Document)-[:CONTAINS_ENTITY]->(:Entity)      // Extraction provenance

// Requirement relationships
(:VisaType)-[:REQUIRES]->(:Requirement)        // Visa → Requirements
(:VisaType)-[:REQUIRES {weight: float}]->(:Document_Type)  // Weighted importance
(:Requirement)-[:SATISFIED_BY]->(:Document_Type)  // How to fulfill requirement
(:Requirement)-[:DEPENDS_ON]->(:Requirement)   // Prerequisite requirements
(:Requirement)-[:APPLIES_IF]->(:Condition)     // Conditional requirements

// Hierarchical relationships
(:VisaType)-[:BELONGS_TO_CATEGORY]->(:VisaType)  // Subcategories
(:VisaType)-[:CAN_TRANSITION_TO]->(:VisaType)    // Visa switching paths
(:VisaType)-[:REQUIRES_SPONSOR]->(:Organization)  // Sponsorship requirements

// Geographical relationships
(:VisaType)-[:ISSUED_BY]->(:Country)
(:Requirement)-[:VARIES_BY_COUNTRY]->(:Country)   // Country-specific rules

// Procedural relationships
(:VisaType)-[:FOLLOWS_PROCESS]->(:Process)
(:Process)-[:NEXT_STEP]->(:Process)               // Process flow
(:Condition)-[:TRIGGERS]->(:Requirement)          // Conditional logic
```

### 2. Entity Extraction Pipeline

#### Component: `Neo4JGraphExtractor`
```python
from typing import List, Dict, Any, Tuple
from haystack import component, Document
from neo4j import GraphDatabase
import spacy
import re

@component
class Neo4JGraphExtractor:
    """
    Extract entities and relationships from immigration documents.

    Uses hybrid approach:
    1. SpaCy NER for general entities (organizations, locations, dates)
    2. Regex patterns for domain-specific entities (visa codes, document types)
    3. LLM-based extraction for complex relationships (requirements, conditions)
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        spacy_model: str = "en_core_web_lg",
        llm_extractor_model: str = "openai/gpt-4o-mini",  # Via OpenRouter
        batch_size: int = 50
    ):
        self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        self.nlp = spacy.load(spacy_model)
        self.llm_model = llm_extractor_model
        self.batch_size = batch_size

        # Domain-specific regex patterns
        self.patterns = {
            "visa_type": r"(Skilled Worker|Student|Family|Tourist|Entrepreneur|Innovator) visa",
            "visa_code": r"\b[A-Z]\d{1,2}\b",  # e.g., T2, T4, T5
            "document_type": r"(passport|bank statement|marriage certificate|birth certificate|degree certificate)",
            "requirement": r"(must|required to|need to|should) (provide|submit|demonstrate|show|have)",
            "time_period": r"\d+\s*(days?|weeks?|months?|years?)",
            "money": r"£\d+(?:,\d{3})*(?:\.\d{2})?"
        }

    @component.output_types(entities=List[Dict[str, Any]], relationships=List[Tuple[str, str, str]])
    def run(self, documents: List[Document]) -> Dict[str, Any]:
        """
        Extract entities and relationships from documents.

        Args:
            documents: List of Haystack Document objects with content and metadata

        Returns:
            entities: List of extracted entities with types and properties
            relationships: List of (source_id, relationship_type, target_id) tuples
        """
        all_entities = []
        all_relationships = []

        for doc in documents:
            # Step 1: SpaCy NER extraction
            spacy_entities = self._extract_spacy_entities(doc)

            # Step 2: Regex pattern extraction
            pattern_entities = self._extract_pattern_entities(doc)

            # Step 3: LLM-based extraction for complex structures
            llm_entities = self._extract_llm_entities(doc)

            # Step 4: Relationship extraction
            relationships = self._extract_relationships(doc, spacy_entities + pattern_entities + llm_entities)

            all_entities.extend(spacy_entities + pattern_entities + llm_entities)
            all_relationships.extend(relationships)

        # Step 5: Write to Neo4J
        self._write_to_neo4j(all_entities, all_relationships)

        return {
            "entities": all_entities,
            "relationships": all_relationships
        }

    def _extract_spacy_entities(self, doc: Document) -> List[Dict[str, Any]]:
        """Extract named entities using SpaCy."""
        spacy_doc = self.nlp(doc.content[:1000000])  # Limit to 1M chars
        entities = []

        for ent in spacy_doc.ents:
            if ent.label_ in ["ORG", "GPE", "DATE", "MONEY"]:
                entities.append({
                    "id": f"{doc.id}_{ent.start_char}_{ent.end_char}",
                    "type": self._map_spacy_label(ent.label_),
                    "text": ent.text,
                    "chunk_ids": [doc.id],
                    "confidence": 0.8  # SpaCy NER baseline confidence
                })

        return entities

    def _extract_pattern_entities(self, doc: Document) -> List[Dict[str, Any]]:
        """Extract domain-specific entities using regex patterns."""
        entities = []

        for entity_type, pattern in self.patterns.items():
            matches = re.finditer(pattern, doc.content, re.IGNORECASE)
            for match in matches:
                entities.append({
                    "id": f"{doc.id}_{entity_type}_{match.start()}",
                    "type": entity_type,
                    "text": match.group(0),
                    "chunk_ids": [doc.id],
                    "confidence": 0.9  # High confidence for pattern matches
                })

        return entities

    def _extract_llm_entities(self, doc: Document) -> List[Dict[str, Any]]:
        """
        Use LLM to extract complex entities (requirements, conditions, processes).

        Prompt engineering for structured extraction:
        - Requirements: "must provide", "need to demonstrate"
        - Conditions: "if applicant has", "unless"
        - Processes: step-by-step procedures
        """
        # LLM extraction prompt
        prompt = f"""Extract immigration visa requirements and conditions from this text.

Text: {doc.content[:4000]}

Return JSON with:
{{
    "requirements": [
        {{"text": "requirement description", "category": "financial|documents|english|health", "mandatory": true|false}}
    ],
    "conditions": [
        {{"text": "condition description", "applies_to": ["visa types"]}}
    ],
    "processes": [
        {{"name": "process name", "steps": ["step 1", "step 2", ...], "duration": "estimate"}}
    ]
}}"""

        # Call LLM (via OpenRouter)
        response = self._call_llm(prompt)

        # Parse response and create entity objects
        entities = []
        for req in response.get("requirements", []):
            entities.append({
                "id": f"{doc.id}_req_{hash(req['text'])}",
                "type": "requirement",
                "text": req["text"],
                "category": req["category"],
                "mandatory": req["mandatory"],
                "chunk_ids": [doc.id],
                "confidence": 0.7  # LLM extraction has lower confidence
            })

        # Similar processing for conditions and processes...

        return entities

    def _extract_relationships(
        self,
        doc: Document,
        entities: List[Dict[str, Any]]
    ) -> List[Tuple[str, str, str]]:
        """
        Extract relationships between entities.

        Relationships extracted:
        - VisaType → Requirement (REQUIRES)
        - Requirement → Document_Type (SATISFIED_BY)
        - VisaType → VisaType (CAN_TRANSITION_TO)
        - Document → Entity (CONTAINS_ENTITY)
        """
        relationships = []

        # Heuristic: If visa type and requirement appear in same sentence, create REQUIRES relationship
        sentences = doc.content.split('.')
        visa_entities = [e for e in entities if e["type"] == "visa_type"]
        req_entities = [e for e in entities if e["type"] == "requirement"]

        for sent in sentences:
            visa_in_sent = [v for v in visa_entities if v["text"].lower() in sent.lower()]
            req_in_sent = [r for r in req_entities if r["text"].lower() in sent.lower()]

            for visa in visa_in_sent:
                for req in req_in_sent:
                    relationships.append((visa["id"], "REQUIRES", req["id"]))

        # Document provenance relationships
        for entity in entities:
            relationships.append((doc.id, "CONTAINS_ENTITY", entity["id"]))

        return relationships

    def _write_to_neo4j(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Tuple[str, str, str]]
    ):
        """Batch write entities and relationships to Neo4J."""
        with self.driver.session() as session:
            # Create entities
            for i in range(0, len(entities), self.batch_size):
                batch = entities[i:i + self.batch_size]
                session.execute_write(self._create_entity_batch, batch)

            # Create relationships
            for i in range(0, len(relationships), self.batch_size):
                batch = relationships[i:i + self.batch_size]
                session.execute_write(self._create_relationship_batch, batch)

    @staticmethod
    def _create_entity_batch(tx, entities: List[Dict[str, Any]]):
        """Cypher query to create entity nodes."""
        query = """
        UNWIND $entities AS entity
        MERGE (n:Entity {id: entity.id})
        SET n += entity
        WITH n, entity.type AS type
        CALL apoc.create.addLabels(n, [type]) YIELD node
        RETURN count(node)
        """
        tx.run(query, entities=entities)

    @staticmethod
    def _create_relationship_batch(tx, relationships: List[Tuple[str, str, str]]):
        """Cypher query to create relationships."""
        query = """
        UNWIND $rels AS rel
        MATCH (a:Entity {id: rel.source})
        MATCH (b:Entity {id: rel.target})
        CALL apoc.create.relationship(a, rel.type, {}, b) YIELD rel AS r
        RETURN count(r)
        """
        rels_formatted = [
            {"source": src, "type": rel_type, "target": tgt}
            for src, rel_type, tgt in relationships
        ]
        tx.run(query, rels=rels_formatted)

    def _call_llm(self, prompt: str) -> Dict[str, Any]:
        """Call LLM via OpenRouter API."""
        # Implementation using httpx/requests to OpenRouter API
        pass

    def _map_spacy_label(self, label: str) -> str:
        """Map SpaCy entity labels to graph node types."""
        mapping = {
            "ORG": "organization",
            "GPE": "country",
            "DATE": "date",
            "MONEY": "monetary_value"
        }
        return mapping.get(label, label.lower())
```

### 3. Graph Traversal Retriever

#### Component: `Neo4JGraphRetriever`
```python
from typing import List, Dict, Any
from haystack import component, Document
from neo4j import GraphDatabase

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
        max_depth: int = 3,
        top_k: int = 10
    ):
        self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        self.max_depth = max_depth
        self.top_k = top_k

    @component.output_types(documents=List[Document], graph_paths=List[Dict[str, Any]])
    def run(self, query: str, entities: List[str] = None) -> Dict[str, Any]:
        """
        Retrieve documents using graph traversal.

        Args:
            query: User query text
            entities: Extracted entities from query (e.g., ["Skilled Worker visa", "Bank Statement"])

        Returns:
            documents: Retrieved Haystack Document objects
            graph_paths: Explanation of graph traversal paths taken
        """
        if not entities:
            entities = self._extract_query_entities(query)

        # Strategy 1: Direct entity match
        direct_docs = self._direct_entity_search(entities)

        # Strategy 2: Relationship expansion
        expanded_docs = self._relationship_expansion(entities)

        # Strategy 3: Multi-hop reasoning
        multihop_docs = self._multihop_traversal(entities)

        # Merge and rank results
        all_docs = self._merge_and_rank(direct_docs, expanded_docs, multihop_docs)

        return {
            "documents": all_docs[:self.top_k],
            "graph_paths": self._generate_explanation_paths(all_docs[:self.top_k])
        }

    def _direct_entity_search(self, entities: List[str]) -> List[Document]:
        """Find documents directly containing queried entities."""
        with self.driver.session() as session:
            query = """
            UNWIND $entities AS entity_text
            MATCH (e:Entity)
            WHERE toLower(e.text) CONTAINS toLower(entity_text) OR toLower(e.name) CONTAINS toLower(entity_text)
            MATCH (d:Document)-[:CONTAINS_ENTITY]->(e)
            RETURN DISTINCT d.id AS doc_id, d.title AS title, d.url AS url,
                   collect(e.text) AS matched_entities
            ORDER BY size(collect(e.text)) DESC
            LIMIT 20
            """
            result = session.run(query, entities=entities)
            return self._result_to_documents(result)

    def _relationship_expansion(self, entities: List[str]) -> List[Document]:
        """
        Expand search using entity relationships.

        Example: Query mentions "Skilled Worker visa" → Find REQUIRES relationships
        → Retrieve documents about those requirements.
        """
        with self.driver.session() as session:
            query = """
            UNWIND $entities AS entity_text
            MATCH (e:Entity)
            WHERE toLower(e.text) CONTAINS toLower(entity_text)
            MATCH (e)-[r:REQUIRES|SATISFIED_BY|DEPENDS_ON]-(related)
            MATCH (d:Document)-[:CONTAINS_ENTITY]->(related)
            RETURN DISTINCT d.id AS doc_id, d.title AS title, d.url AS url,
                   e.text AS source_entity, type(r) AS relationship, related.text AS target_entity
            LIMIT 20
            """
            result = session.run(query, entities=entities)
            return self._result_to_documents(result)

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
        with self.driver.session() as session:
            query = f"""
            UNWIND $entities AS entity_text
            MATCH path = (start:Entity)-[*1..{self.max_depth}]-(end:Entity)
            WHERE toLower(start.text) CONTAINS toLower(entity_text)
            MATCH (d:Document)-[:CONTAINS_ENTITY]->(end)
            RETURN DISTINCT d.id AS doc_id, d.title AS title, d.url AS url,
                   [node IN nodes(path) | node.text] AS traversal_path,
                   [rel IN relationships(path) | type(rel)] AS relationship_types,
                   length(path) AS hop_count
            ORDER BY hop_count ASC
            LIMIT 20
            """
            result = session.run(query, entities=entities)
            return self._result_to_documents(result)

    def _merge_and_rank(
        self,
        direct: List[Document],
        expanded: List[Document],
        multihop: List[Document]
    ) -> List[Document]:
        """
        Merge results from different strategies and rank by combined score.

        Scoring:
        - Direct match: 1.0 base score
        - Relationship expansion: 0.8 base score
        - Multi-hop: 0.6 / hop_count base score
        - Boost: Graph centrality (PageRank of retrieved entities)
        """
        doc_scores = {}

        for doc in direct:
            doc_scores[doc.id] = doc_scores.get(doc.id, 0) + 1.0

        for doc in expanded:
            doc_scores[doc.id] = doc_scores.get(doc.id, 0) + 0.8

        for doc in multihop:
            hop_count = doc.meta.get("hop_count", 1)
            doc_scores[doc.id] = doc_scores.get(doc.id, 0) + (0.6 / hop_count)

        # Sort by score
        all_docs = list({doc.id: doc for doc in direct + expanded + multihop}.values())
        all_docs.sort(key=lambda d: doc_scores[d.id], reverse=True)

        return all_docs

    def _generate_explanation_paths(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """Generate human-readable explanation of graph traversal."""
        # Return traversal paths for explainability
        pass

    def _extract_query_entities(self, query: str) -> List[str]:
        """Extract entities from user query using NER."""
        # Use SpaCy or simple keyword matching
        pass

    def _result_to_documents(self, result) -> List[Document]:
        """Convert Neo4J query results to Haystack Documents."""
        docs = []
        for record in result:
            doc = Document(
                id=record["doc_id"],
                content="",  # Content fetched from Qdrant using chunk_ids
                meta={
                    "title": record["title"],
                    "url": record["url"],
                    "matched_entities": record.get("matched_entities", []),
                    "traversal_path": record.get("traversal_path", []),
                    "relationship_types": record.get("relationship_types", []),
                    "hop_count": record.get("hop_count", 0)
                }
            )
            docs.append(doc)
        return docs
```

### 4. Hybrid Pipeline Integration

```python
from haystack import Pipeline
from haystack.components.embedders import SentenceTransformersTextEmbedder
from haystack.components.retrievers.qdrant import QdrantEmbeddingRetriever

# Hybrid RAG pipeline: Vector + BM25 + Neo4J Graph
pipeline = Pipeline()

# Query processing
pipeline.add_component("query_embedder", SentenceTransformersTextEmbedder())
pipeline.add_component("entity_extractor", EntityExtractor())  # Extract entities from query

# Retrieval strategies (parallel)
pipeline.add_component("vector_retriever", QdrantEmbeddingRetriever(
    document_store=qdrant_store,
    top_k=20
))
pipeline.add_component("bm25_retriever", BM25Retriever(
    document_store=bm25_index,
    top_k=20
))
pipeline.add_component("graph_retriever", Neo4JGraphRetriever(
    neo4j_uri=NEO4J_URI,
    neo4j_user=NEO4J_USER,
    neo4j_password=NEO4J_PASSWORD,
    top_k=20
))

# Candidate merging
pipeline.add_component("document_joiner", DocumentJoiner(
    join_mode="merge",  # Merge results from all retrievers
    weights={"vector_retriever": 0.4, "bm25_retriever": 0.3, "graph_retriever": 0.3}
))

# Reranking
pipeline.add_component("reranker", DeepInfraReranker(
    model="Qwen/Qwen3-Reranker-8B",
    top_k=5
))

# Connect components
pipeline.connect("query_embedder.embedding", "vector_retriever.query_embedding")
pipeline.connect("entity_extractor.entities", "graph_retriever.entities")
pipeline.connect("vector_retriever.documents", "document_joiner.documents")
pipeline.connect("bm25_retriever.documents", "document_joiner.documents")
pipeline.connect("graph_retriever.documents", "document_joiner.documents")
pipeline.connect("document_joiner.documents", "reranker.documents")
```

---

## Implementation Plan

### Phase 1: Foundation (Week 1-2)
**Goal**: Neo4J setup and basic extraction

**Tasks**:
1. **T001**: Set up Neo4J production instance
   - Deploy Neo4J on DigitalOcean Droplet or managed service
   - Configure authentication, backups, monitoring
   - Create database schema (nodes, relationships, indexes)

2. **T002**: Implement `Neo4JGraphExtractor` component
   - SpaCy NER integration (en_core_web_lg model)
   - Regex pattern extraction for domain entities
   - Basic batch writing to Neo4J

3. **T003**: Create graph population script
   - Read existing Qdrant documents
   - Extract entities from 117K document chunks
   - Populate Neo4J with initial graph

4. **T004**: Graph schema validation
   - Write Cypher queries to validate node/relationship counts
   - Check for orphaned nodes
   - Compute basic graph statistics (node degree distribution)

**Deliverables**:
- Neo4J instance running with populated graph
- 90%+ of Qdrant documents have corresponding graph entities
- Graph statistics report (node counts by type, relationship distribution)

### Phase 2: LLM-Based Extraction (Week 3-4)
**Goal**: Enhanced extraction using LLM reasoning

**Tasks**:
1. **T005**: Implement LLM extraction for requirements
   - Design prompts for requirement extraction
   - Parse LLM JSON responses
   - Create Requirement nodes with properties

2. **T006**: Implement LLM extraction for conditions
   - Extract conditional logic ("if applicant has X, then Y")
   - Create Condition nodes and APPLIES_IF relationships

3. **T007**: Implement LLM extraction for processes
   - Extract procedural steps
   - Create Process nodes with ordered steps
   - Link processes to visa types

4. **T008**: Relationship inference
   - LLM prompts to infer implicit relationships
   - Example: "Marriage certificate required" → (Requirement)-[:SATISFIED_BY]->(Document_Type:Marriage Certificate)

5. **T009**: Batch processing optimization
   - Parallel LLM calls using asyncio
   - Rate limiting and error handling
   - Cost optimization (use GPT-4o-mini for extraction)

**Deliverables**:
- Complex entities (requirements, conditions, processes) extracted
- LLM extraction pipeline processing 1000+ docs/hour
- Cost analysis report (<$50 for full corpus extraction)

### Phase 3: Graph Retrieval (Week 5-6)
**Goal**: Integrate graph traversal into RAG pipeline

**Tasks**:
1. **T010**: Implement `Neo4JGraphRetriever` component
   - Direct entity search Cypher queries
   - Relationship expansion queries
   - Multi-hop traversal (max depth 3)

2. **T011**: Query entity extraction
   - SpaCy NER on user queries
   - Map query entities to graph nodes
   - Handle entity ambiguity (multiple matches)

3. **T012**: Scoring and ranking algorithm
   - Graph centrality boost (PageRank)
   - Hop count penalties
   - Combine with vector similarity scores

4. **T013**: Hybrid pipeline integration
   - Add Neo4JGraphRetriever to existing Haystack pipeline
   - Configure DocumentJoiner weights
   - Test with vector + BM25 + graph retrieval

**Deliverables**:
- Neo4JGraphRetriever component in production
- Hybrid pipeline returning graph-augmented results
- Benchmark: 10%+ improvement in answer quality for multi-hop queries

### Phase 4: Optimization & Explainability (Week 7-8)
**Goal**: Performance tuning and user-facing explanations

**Tasks**:
1. **T014**: Graph query optimization
   - Create Neo4J indexes on frequently queried properties
   - Optimize Cypher queries (use EXPLAIN/PROFILE)
   - Cache common traversal patterns

2. **T015**: Explainability features
   - Generate graph path visualizations
   - Return relationship chains in API responses
   - Frontend: Display "How we found this answer" graph

3. **T016**: Monitoring and maintenance
   - Neo4J metrics (query latency, cache hit rate)
   - Graph health checks (orphaned nodes, broken relationships)
   - Automated graph updates when new documents ingested

4. **T017**: User acceptance testing
   - Test with 50+ complex multi-hop queries
   - Measure precision, recall, latency
   - A/B test: Graph-augmented vs baseline RAG

**Deliverables**:
- Graph retrieval latency <500ms p99
- Explainability UI showing graph traversal paths
- UAT report with metrics and user feedback

---

## API Endpoints

### New Endpoints for Graph Features

```python
# FastAPI routes

@router.post("/api/rag/graph/extract", status_code=status.HTTP_202_ACCEPTED)
async def trigger_graph_extraction(
    document_ids: List[str] = None,  # If None, extract from all documents
    background_tasks: BackgroundTasks = None
):
    """
    Trigger entity extraction and graph population.

    Background task processes documents in batches.
    Returns job_id for status checking.
    """
    pass

@router.get("/api/rag/graph/stats")
async def get_graph_statistics():
    """
    Return Neo4J graph statistics.

    Response:
    {
        "node_counts": {"VisaType": 50, "Requirement": 1200, ...},
        "relationship_counts": {"REQUIRES": 3000, "SATISFIED_BY": 800, ...},
        "graph_density": 0.42,
        "last_updated": "2025-11-07T14:00:00Z"
    }
    """
    pass

@router.post("/api/rag/query-graph")
async def query_with_graph(
    query: str,
    use_graph: bool = True,
    max_graph_depth: int = 3,
    top_k: int = 5
) -> QueryResponse:
    """
    RAG query with optional graph traversal.

    Response includes:
    - answer: Generated answer
    - sources: Retrieved documents
    - graph_paths: Explanation of graph traversal (if use_graph=True)
    """
    pass

@router.get("/api/rag/graph/entity/{entity_id}")
async def get_entity_details(entity_id: str):
    """
    Get details about a specific graph entity.

    Response:
    {
        "id": "entity_123",
        "type": "VisaType",
        "properties": {"name": "Skilled Worker", "code": "T2"},
        "relationships": [
            {"type": "REQUIRES", "target": {"id": "req_456", "text": "English language test"}},
            ...
        ],
        "related_documents": ["doc_789", "doc_012"]
    }
    """
    pass

@router.get("/api/rag/graph/visualize/{entity_id}")
async def visualize_entity_graph(
    entity_id: str,
    depth: int = 2
) -> GraphVisualizationData:
    """
    Return graph data for visualization (nodes, edges).

    Frontend can render using D3.js, Cytoscape.js, or vis.js.
    """
    pass
```

---

## Configuration

### Environment Variables
```bash
# Neo4J Configuration
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<secure-password>
NEO4J_DATABASE=immigration_graph

# Graph Extraction
GRAPH_EXTRACTION_ENABLED=true
GRAPH_EXTRACTION_BATCH_SIZE=50
GRAPH_EXTRACTION_LLM_MODEL=openai/gpt-4o-mini

# Graph Retrieval
GRAPH_RETRIEVAL_ENABLED=true
GRAPH_MAX_HOP_DEPTH=3
GRAPH_RETRIEVAL_TOP_K=20
GRAPH_WEIGHT_IN_HYBRID=0.3  # 30% weight for graph retrieval

# SpaCy Model
SPACY_MODEL=en_core_web_lg
```

### Feature Flags
```python
# config/features.py
GRAPH_FEATURES = {
    "extraction_enabled": os.getenv("GRAPH_EXTRACTION_ENABLED", "false").lower() == "true",
    "retrieval_enabled": os.getenv("GRAPH_RETRIEVAL_ENABLED", "false").lower() == "true",
    "explainability_enabled": True,  # Always show graph paths if available
}
```

---

## Testing Strategy

### Unit Tests
```python
# tests/test_neo4j_extractor.py
def test_spacy_entity_extraction():
    """Test SpaCy NER extraction from sample document."""
    pass

def test_pattern_entity_extraction():
    """Test regex pattern matching for visa codes, document types."""
    pass

def test_llm_requirement_extraction():
    """Test LLM-based extraction with mock API responses."""
    pass

def test_relationship_inference():
    """Test relationship creation between entities."""
    pass

def test_neo4j_batch_write():
    """Test batch writing to Neo4J with mock driver."""
    pass
```

### Integration Tests
```python
# tests/test_graph_retrieval_integration.py
def test_hybrid_pipeline_with_graph():
    """Test full pipeline: Query → Vector + BM25 + Graph → Rerank → Answer."""
    pass

def test_graph_traversal_accuracy():
    """Test that multi-hop traversal finds correct documents."""
    pass

def test_graph_retrieval_latency():
    """Ensure graph queries complete within 500ms p99."""
    pass
```

### Evaluation Metrics
1. **Extraction Quality**:
   - Entity precision/recall (compare LLM extraction vs human-labeled gold set)
   - Relationship accuracy (sample 100 relationships, manual verification)

2. **Retrieval Quality**:
   - NDCG@10 for multi-hop queries (compare graph-augmented vs baseline)
   - Answer correctness (human eval on 50 complex queries)
   - Graph path relevance (are traversal paths semantically meaningful?)

3. **Performance**:
   - Extraction throughput (documents processed per hour)
   - Graph query latency (p50, p95, p99)
   - End-to-end query latency (with graph enabled vs disabled)

---

## Monitoring & Maintenance

### Neo4J Monitoring
- **Metrics**:
  - Query latency (ms)
  - Cache hit rate (%)
  - Concurrent connections
  - Database size (GB)
  - Page faults (disk I/O)

- **Alerts**:
  - Query latency >1000ms for >1% of queries
  - Cache hit rate <80%
  - Disk usage >80%

### Graph Health Checks
```python
# Scheduled job (daily)
async def run_graph_health_check():
    """Validate graph integrity."""
    with neo4j_driver.session() as session:
        # Check for orphaned nodes (no relationships)
        orphaned = session.run("""
            MATCH (n)
            WHERE NOT (n)--()
            RETURN count(n) AS orphaned_count
        """).single()["orphaned_count"]

        if orphaned > 100:
            logger.warning(f"{orphaned} orphaned nodes detected")

        # Check for broken chunk_id references
        broken = session.run("""
            MATCH (n)
            WHERE size(n.chunk_ids) = 0
            RETURN count(n) AS broken_count
        """).single()["broken_count"]

        if broken > 0:
            logger.error(f"{broken} nodes with missing chunk_ids")
```

### Graph Updates
- **Incremental Updates**: When new documents ingested, run graph extraction on new docs only
- **Full Rebuild**: Quarterly full graph rebuild to fix accumulated errors
- **Schema Migrations**: Use `neo4j-migrations` tool for version-controlled schema changes

---

## Security Considerations

### Neo4J Security
1. **Authentication**: Strong password, rotate every 90 days
2. **Network**: Neo4J port 7687 NOT exposed to internet, only accessible via backend VPC
3. **Encryption**: TLS for Neo4J connections (`bolt+s://`)
4. **Backups**: Daily automated backups to DigitalOcean Spaces
5. **Access Control**: Role-based access (read-only for RAG retrieval, read-write for extraction jobs)

### Data Privacy
- **PII Handling**: No user-specific data in graph (only document entities)
- **Anonymization**: If document contains user data, extract only generic entities
- **Audit Logging**: Log all graph write operations (who, what, when)

---

## Cost Analysis

### Neo4J Hosting (Production)
- **Option 1**: Self-hosted on DigitalOcean Droplet
  - Droplet: 8GB RAM, 4 vCPUs, 160GB SSD = $48/month
  - Backups: ~$5/month
  - Total: **~$53/month**

- **Option 2**: Neo4J AuraDB (managed)
  - Professional: 8GB RAM = $175/month
  - Includes backups, monitoring, auto-scaling
  - Total: **~$175/month**

**Recommendation**: Start with self-hosted (Option 1), migrate to AuraDB if scaling needed.

### LLM Extraction Costs
- **Documents**: 117,343 chunks
- **Avg chunk size**: 500 tokens
- **LLM model**: GPT-4o-mini via OpenRouter ($0.15/$1M input tokens)
- **Total tokens**: 117,343 × 500 = 58.7M tokens
- **Cost**: 58.7M × $0.15 / 1M = **~$8.80 one-time**

**Incremental costs**: ~$0.01 per 100 new documents

---

## Success Metrics

### Quantitative
- **Graph Coverage**: 95%+ of documents have at least one entity extracted
- **Extraction Quality**: 90%+ precision/recall on entity extraction (vs gold set)
- **Retrieval Improvement**: 10%+ NDCG@10 improvement for multi-hop queries
- **Latency**: Graph retrieval adds <200ms overhead (p99)
- **Adoption**: 30%+ of queries use graph retrieval

### Qualitative
- Users report better answers for complex multi-entity questions
- Explainability: Users understand why specific documents were retrieved
- Trust: Graph paths provide transparency into RAG reasoning

---

## Rollback Plan

### Feature Flags
- Graph retrieval disabled by default
- Enable for 10% of queries initially (A/B test)
- Gradual rollout based on metrics

### Rollback Triggers
- Graph retrieval increases latency >500ms p99
- Answer quality degrades (NDCG@10 drops >5%)
- Neo4J errors/downtime >0.1% of queries

### Rollback Steps
1. Set `GRAPH_RETRIEVAL_ENABLED=false`
2. Pipeline falls back to vector + BM25 only
3. Neo4J remains populated (no data loss)
4. Investigate issues, fix, re-enable

---

## Future Enhancements (Post-MVP)

1. **Graph-Guided Generation**: Use graph paths as additional context for LLM answer generation
2. **Dynamic Graph Updates**: Real-time entity extraction as new GOV.UK pages published
3. **User Feedback Loop**: Allow users to correct entity extraction errors
4. **Cross-Document Reasoning**: Synthesize answers from multiple graph hops
5. **Temporal Graphs**: Track how visa requirements change over time (historical nodes)
6. **Multi-Language Support**: Extract entities from Welsh-language documents

---

## References & Resources

### Libraries
- **Neo4J Python Driver**: https://neo4j.com/docs/python-manual/current/
- **SpaCy**: https://spacy.io/usage/linguistic-features
- **Haystack Custom Components**: https://docs.haystack.deepset.ai/docs/custom-components

### Graph RAG Papers
- "From Local to Global: A Graph RAG Approach" (Microsoft, 2024)
- "HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models" (2024)
- "Graph Retrieval-Augmented Generation: A Survey" (2024)

### Neo4J Best Practices
- Neo4J Data Modeling: https://neo4j.com/developer/data-modeling/
- Cypher Query Optimization: https://neo4j.com/docs/cypher-manual/current/query-tuning/

---

**Last Updated**: 2025-11-07
**Status**: Specification Complete, Implementation Pending
**Owner**: Terry Yodaiken
**Contact**: terry@poview.ai
