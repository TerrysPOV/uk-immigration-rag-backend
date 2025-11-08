# Neo4J Graph Traversal Implementation

**Feature ID**: NEO4J-001
**Status**: ✅ Implemented
**Implementation Date**: 2025-11-08
**Version**: 1.0.0

---

## Overview

This document describes the implementation of Neo4J graph traversal for the UK Immigration RAG system. The implementation enables multi-hop reasoning for complex queries by extracting entities and relationships from immigration documents and traversing the knowledge graph.

### What Was Implemented

✅ **Core Components**:
- `Neo4JGraphExtractor`: Hybrid entity extraction (SpaCy + Regex + LLM)
- `Neo4JGraphRetriever`: Multi-hop graph traversal retrieval
- `Neo4JGraphService`: Health checks, statistics, and graph management

✅ **API Endpoints**:
- `POST /api/rag/graph/extract`: Trigger entity extraction
- `GET /api/rag/graph/stats`: Graph statistics
- `GET /api/rag/graph/health`: Health check
- `POST /api/rag/graph/query`: Graph-augmented RAG query
- `GET /api/rag/graph/entity/{id}`: Entity details
- `GET /api/rag/graph/visualize/{id}`: Visualization data
- `POST /api/rag/graph/search`: Entity search

✅ **Integration**:
- Added SpaCy dependency for NER
- Integrated with existing FastAPI app
- Environment-based configuration
- Schema initialization on startup

---

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Application                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Graph API Endpoints                         │  │
│  │  /graph/extract, /graph/stats, /graph/query, etc.       │  │
│  └────────────────────┬─────────────────────────────────────┘  │
│                       │                                         │
│  ┌────────────────────▼─────────────────────────────────────┐  │
│  │             Neo4JGraphService                            │  │
│  │  - Health checks                                         │  │
│  │  - Statistics                                            │  │
│  │  - Entity lookup                                         │  │
│  │  - Visualization data                                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         Neo4JGraphExtractor (Haystack Component)         │  │
│  │  ┌────────────┐  ┌─────────────┐  ┌─────────────────┐   │  │
│  │  │ SpaCy NER  │  │ Regex       │  │ LLM Extraction  │   │  │
│  │  │ (ORG, GPE) │  │ (Visa Types)│  │ (Requirements)  │   │  │
│  │  └────────────┘  └─────────────┘  └─────────────────┘   │  │
│  │                       ▼                                   │  │
│  │              Entity & Relationship Extraction            │  │
│  │                       ▼                                   │  │
│  │                 Batch Write to Neo4J                     │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         Neo4JGraphRetriever (Haystack Component)         │  │
│  │  ┌────────────┐  ┌─────────────┐  ┌─────────────────┐   │  │
│  │  │   Direct   │  │Relationship │  │   Multi-hop     │   │  │
│  │  │   Entity   │  │  Expansion  │  │   Traversal     │   │  │
│  │  │   Match    │  │  (REQUIRES) │  │  (Depth 1-3)    │   │  │
│  │  └────────────┘  └─────────────┘  └─────────────────┘   │  │
│  │                       ▼                                   │  │
│  │            Merge & Rank (Graph Scoring)                  │  │
│  │                       ▼                                   │  │
│  │          Return Documents + Graph Paths                  │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   Neo4J Graph   │
                    │    Database     │
                    │                 │
                    │ - Entities      │
                    │ - Relationships │
                    │ - Indexes       │
                    └─────────────────┘
```

### Graph Schema

**Node Types**:
- `Entity` (base label for all nodes)
- `visa_type`: Visa categories (Skilled Worker, Student, Family, etc.)
- `requirement`: Requirements for visa applications
- `document_type`: Required documents (passport, bank statement, etc.)
- `organization`: Organizations (Home Office, UKVI, etc.)
- `country`: Countries (UK, India, etc.)
- `condition`: Conditional logic for requirements
- `process`: Procedural steps for visa applications

**Relationship Types**:
- `CONTAINS_ENTITY`: Document → Entity (provenance)
- `REQUIRES`: VisaType → Requirement
- `SATISFIED_BY`: Requirement → Document_Type
- `DEPENDS_ON`: Requirement → Requirement (prerequisites)
- `APPLIES_IF`: Requirement → Condition
- `CAN_TRANSITION_TO`: VisaType → VisaType (visa switching)

---

## File Structure

### New Files Created

```
src/
├── services/
│   ├── neo4j_graph_extractor.py      # Entity extraction component
│   ├── neo4j_graph_retriever.py      # Graph traversal retrieval
│   └── neo4j_graph_service.py        # Health checks & statistics
│
├── api/
│   └── routes/
│       └── graph.py                  # Graph API endpoints
│
└── main.py                           # Updated with graph router

requirements.txt                      # Added spacy>=3.7.0
.env.neo4j.example                   # Neo4J configuration template
NEO4J_IMPLEMENTATION.md              # This file
```

### Modified Files

- `src/main.py`: Added graph router, Neo4J schema initialization
- `requirements.txt`: Added SpaCy and en_core_web_lg model

---

## Setup Instructions

### 1. Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Download SpaCy model
python -m spacy download en_core_web_lg
```

### 2. Start Neo4J

**Option A: Using Docker Compose (Recommended for Development)**

```bash
# Start Neo4J from docker-compose-linkedin.yml
docker-compose -f docker-compose-linkedin.yml up neo4j -d

# Check status
docker-compose -f docker-compose-linkedin.yml ps
```

Neo4J will be available at:
- **Bolt**: `bolt://localhost:7687`
- **HTTP**: `http://localhost:7474`
- **Default credentials**: `neo4j/admin123`

**Option B: Using Standalone Neo4J**

```bash
# Download Neo4J Community Edition
wget https://neo4j.com/artifact.php?name=neo4j-community-5.14.0-unix.tar.gz

# Extract and run
tar -xf neo4j-community-5.14.0-unix.tar.gz
cd neo4j-community-5.14.0
./bin/neo4j start
```

### 3. Configure Environment Variables

```bash
# Copy example configuration
cp .env.neo4j.example .env.neo4j

# Edit configuration
nano .env.neo4j

# Set required variables:
# NEO4J_URI=bolt://localhost:7687
# NEO4J_PASSWORD=your-password
# GRAPH_EXTRACTION_ENABLED=true
# GRAPH_RETRIEVAL_ENABLED=true

# Source environment
source .env.neo4j
```

### 4. Initialize Graph Schema

The schema is automatically initialized on application startup if `GRAPH_EXTRACTION_ENABLED=true`.

Alternatively, you can initialize manually via Python:

```python
from src.services.neo4j_graph_service import get_graph_service

graph_service = get_graph_service(
    neo4j_uri="bolt://localhost:7687",
    neo4j_user="neo4j",
    neo4j_password="your-password",
    neo4j_database="neo4j"
)

graph_service.initialize_schema()
```

### 5. Start the Application

```bash
# Start FastAPI application
python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Usage Examples

### 1. Check Graph Health

```bash
curl http://localhost:8000/api/rag/graph/health
```

**Response**:
```json
{
  "status": "healthy",
  "orphaned_nodes": 0,
  "broken_references": 0,
  "warnings": [],
  "errors": [],
  "timestamp": "2025-11-08T12:00:00Z"
}
```

### 2. Get Graph Statistics

```bash
curl http://localhost:8000/api/rag/graph/stats
```

**Response**:
```json
{
  "node_counts": {
    "Entity": 5432,
    "visa_type": 45,
    "requirement": 1230,
    "document_type": 78
  },
  "relationship_counts": {
    "CONTAINS_ENTITY": 5432,
    "REQUIRES": 2100,
    "SATISFIED_BY": 450
  },
  "total_nodes": 5432,
  "total_relationships": 7982,
  "graph_density": 0.0027,
  "last_updated": "2025-11-08T12:00:00Z"
}
```

### 3. Trigger Entity Extraction

```bash
curl -X POST http://localhost:8000/api/rag/graph/extract \
  -H "Content-Type: application/json" \
  -d '{
    "document_ids": null,
    "enable_llm_extraction": true
  }'
```

**Response**:
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "queued",
  "message": "Graph extraction queued. Processing all documents."
}
```

### 4. Query with Graph Traversal

```bash
curl -X POST http://localhost:8000/api/rag/graph/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What documents are needed for Skilled Worker visa?",
    "use_graph": true,
    "max_graph_depth": 3,
    "top_k": 5
  }'
```

**Response**:
```json
{
  "query": "What documents are needed for Skilled Worker visa?",
  "results": [
    {
      "id": "doc_123",
      "content": "...",
      "metadata": {
        "matched_entities": ["Skilled Worker visa", "passport"],
        "graph_score": 1.8
      }
    }
  ],
  "graph_paths": [
    {
      "document_id": "doc_123",
      "strategy": "direct",
      "graph_score": 1.8,
      "matched_entities": ["Skilled Worker visa", "passport"]
    }
  ],
  "took_ms": 125.4
}
```

### 5. Search Entities

```bash
curl -X POST http://localhost:8000/api/rag/graph/search \
  -H "Content-Type: application/json" \
  -d '{
    "search_term": "Skilled Worker",
    "entity_types": ["visa_type"],
    "limit": 10
  }'
```

### 6. Get Entity Details

```bash
curl http://localhost:8000/api/rag/graph/entity/visa_type_abc123
```

### 7. Get Visualization Data

```bash
curl http://localhost:8000/api/rag/graph/visualize/visa_type_abc123?depth=2
```

---

## API Reference

### Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/rag/graph/extract` | Trigger entity extraction |
| GET | `/api/rag/graph/stats` | Graph statistics |
| GET | `/api/rag/graph/health` | Health check |
| POST | `/api/rag/graph/query` | Graph-augmented query |
| GET | `/api/rag/graph/entity/{id}` | Entity details |
| GET | `/api/rag/graph/visualize/{id}` | Visualization data |
| POST | `/api/rag/graph/search` | Entity search |

Full API documentation available at: `http://localhost:8000/docs`

---

## Configuration Reference

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEO4J_URI` | Yes | - | Neo4J connection URI |
| `NEO4J_USER` | No | `neo4j` | Neo4J username |
| `NEO4J_PASSWORD` | Yes | - | Neo4J password |
| `NEO4J_DATABASE` | No | `neo4j` | Database name |
| `GRAPH_EXTRACTION_ENABLED` | No | `false` | Enable extraction |
| `GRAPH_RETRIEVAL_ENABLED` | No | `false` | Enable retrieval |
| `GRAPH_MAX_HOP_DEPTH` | No | `3` | Max traversal depth |
| `GRAPH_RETRIEVAL_TOP_K` | No | `20` | Docs to retrieve |
| `SPACY_MODEL` | No | `en_core_web_lg` | SpaCy model |

See `.env.neo4j.example` for complete configuration options.

---

## Performance Considerations

### Entity Extraction

- **SpaCy NER**: ~1-2 seconds per document
- **Regex patterns**: <100ms per document
- **LLM extraction**: ~2-5 seconds per document (depends on API latency)

**Estimated costs**:
- Full corpus (117K docs): ~$8.80 one-time (using GPT-4o-mini)
- Incremental: ~$0.01 per 100 new documents

### Graph Retrieval

- **Direct entity search**: 10-50ms
- **Relationship expansion**: 50-200ms
- **Multi-hop traversal (depth 3)**: 100-500ms

**Optimization tips**:
- Create indexes on frequently queried properties
- Use APOC procedures for complex traversals
- Limit `max_depth` to 2-3 for production
- Cache common query patterns

---

## Monitoring

### Health Checks

```bash
# Check graph health
curl http://localhost:8000/api/rag/graph/health

# Check application health
curl http://localhost:8000/api/rag/health
```

### Metrics to Monitor

1. **Graph size**: Node/relationship counts
2. **Orphaned nodes**: Nodes without relationships
3. **Broken references**: Nodes with missing `chunk_ids`
4. **Query latency**: p50, p95, p99 for graph queries
5. **Extraction throughput**: Documents processed per hour

### Neo4J Native Monitoring

Access Neo4J browser at `http://localhost:7474` and run:

```cypher
// Node count by label
MATCH (n)
RETURN labels(n) AS label, count(n) AS count
ORDER BY count DESC

// Relationship count by type
MATCH ()-[r]->()
RETURN type(r) AS type, count(r) AS count
ORDER BY count DESC

// Find orphaned nodes
MATCH (n)
WHERE NOT (n)--()
RETURN n
LIMIT 10
```

---

## Troubleshooting

### Common Issues

**1. "Neo4J driver not initialized"**

- **Cause**: Neo4J connection failed
- **Solution**: Check `NEO4J_URI` and `NEO4J_PASSWORD` in environment
- **Verify**: `docker-compose ps` shows Neo4J running

**2. "SpaCy model not found"**

- **Cause**: SpaCy model not downloaded
- **Solution**: Run `python -m spacy download en_core_web_lg`

**3. "Failed to connect to Neo4J"**

- **Cause**: Neo4J not running or wrong credentials
- **Solution**:
  - Check Neo4J is running: `docker-compose ps`
  - Verify credentials match docker-compose.yml
  - Check firewall allows port 7687

**4. "Graph extraction timeout"**

- **Cause**: Large batch size or slow LLM API
- **Solution**:
  - Reduce `GRAPH_EXTRACTION_BATCH_SIZE` (try 25)
  - Disable LLM extraction: `GRAPH_EXTRACTION_LLM_ENABLED=false`
  - Use faster LLM model

**5. "Orphaned nodes detected"**

- **Cause**: Entity extraction without relationship inference
- **Solution**:
  - Re-run extraction with LLM enabled
  - Manually create relationships via Cypher

---

## Testing

### Manual Testing

```bash
# 1. Health check
curl http://localhost:8000/api/rag/graph/health

# 2. Extract entities from a test document
# (Implementation needed: Add test documents to Qdrant first)

# 3. Query with graph traversal
curl -X POST http://localhost:8000/api/rag/graph/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What documents are needed for Student visa?", "use_graph": true}'

# 4. Check statistics
curl http://localhost:8000/api/rag/graph/stats
```

### Unit Tests

Unit tests should be added in `tests/test_neo4j_*.py`:

- `test_graph_extractor.py`: Test entity extraction
- `test_graph_retriever.py`: Test graph traversal
- `test_graph_service.py`: Test health checks and statistics

---

## Future Enhancements

The following features are specified but not yet implemented:

### Phase 2 Enhancements (Planned)

1. **Automated Extraction Pipeline**:
   - Celery task for async extraction
   - Progress tracking via job_id
   - Webhook notifications on completion

2. **Hybrid RAG Integration**:
   - Combine vector + BM25 + graph retrieval
   - Weighted scoring across retrieval strategies
   - DocumentJoiner for result merging

3. **Advanced Traversal Algorithms**:
   - PageRank-based entity scoring
   - Community detection for related topics
   - Semantic similarity on graph paths

4. **Performance Optimizations**:
   - Query result caching (Redis)
   - APOC procedures for complex traversals
   - Read replicas for high query volumes

5. **UI Features**:
   - Interactive graph visualization (D3.js/Cytoscape.js)
   - Graph path explanations in search results
   - Entity relationship explorer

### Long-term Vision

- **Temporal graphs**: Track how visa requirements change over time
- **Multi-language support**: Extract entities from Welsh documents
- **User feedback loop**: Allow users to correct entity extraction errors
- **Cross-document synthesis**: Generate answers from multiple graph hops

---

## References

- **Specification**: `/home/user/rag-backend/NEO4J_GRAPH_TRAVERSAL_SPEC.md`
- **Neo4J Documentation**: https://neo4j.com/docs/
- **SpaCy Documentation**: https://spacy.io/usage/linguistic-features
- **Haystack Custom Components**: https://docs.haystack.deepset.ai/docs/custom-components

---

## Support

For questions or issues:
1. Check this documentation
2. Review `NEO4J_GRAPH_TRAVERSAL_SPEC.md`
3. Check application logs: `docker-compose logs -f backend`
4. Check Neo4J logs: `docker-compose logs -f neo4j`

---

**Last Updated**: 2025-11-08
**Author**: Claude AI (Anthropic)
**Project**: UK Immigration RAG Backend
**Feature**: NEO4J-001 - Graph Traversal Implementation
