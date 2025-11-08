# UK Immigration RAG Backend

Production-ready backend for document processing, vectorization, and RAG (Retrieval-Augmented Generation) system for UK Immigration guidance documents.

## 🎯 Features

### Document Processing Pipeline
- **Web scraping** with BeautifulSoup4 and lxml
- **Metadata extraction** with structured parsing
- **Vectorization** using DeepInfra embeddings (intfloat/e5-large-v2, 1024-dim)
- **Binary quantization** for 97% storage compression
- **Batch processing** with progress tracking

### Search & Retrieval
- **Haystack Core** RAG framework (v2.7.0)
- **Semantic search** with Qdrant vector database
- **Keyword search** with BM25 (Whoosh backend)
- **Hybrid search** combining semantic + keyword ranking
- **Cross-encoder reranking** for precision
- **Query preprocessing** with normalization

### Infrastructure
- **Qdrant** vector database with binary quantization
- **PostgreSQL** for document metadata storage
- **DigitalOcean Spaces** for object storage (UK region for data sovereignty)
- **FastAPI** REST API with async support
- **Redis** rate limiting and caching
- **Google OAuth 2.0** authentication (OIDC)

### AI/ML Integration
- **DeepInfra API** for embeddings
- **OpenRouter API** for LLM inference (multi-model support)
- **Sentence Transformers** for local embeddings
- **PyTorch** backend for model execution

## 📁 Project Structure

```
backend-source/
├── src/
│   ├── main.py                     # FastAPI application entry point
│   ├── api/
│   │   ├── routes/
│   │   │   ├── rag.py              # RAG query endpoints
│   │   │   └── auth.py             # Authentication endpoints
│   │   ├── models/
│   │   │   └── rag.py              # Pydantic models for RAG requests/responses
│   │   └── auth.py                 # Auth middleware and utilities
│   └── rag/
│       ├── components/
│       │   ├── deepinfra_embedder.py      # DeepInfra API embedder
│       │   ├── qdrant_store.py            # Qdrant vector store component
│       │   ├── bm25_ranker.py             # BM25 keyword search ranker
│       │   ├── cross_encoder_ranker.py    # Cross-encoder reranker
│       │   └── query_preprocessor.py      # Query normalization
│       └── pipelines/
│           └── haystack_retrieval.py      # Haystack RAG pipeline
├── tests/
│   ├── integration/
│   │   └── test_haystack_pipeline.py      # Pipeline integration tests
│   └── contract/
│       ├── test_rag_query_contract.py     # RAG API contract tests
│       └── test_auth_token_contract.py    # Auth API contract tests
├── requirements.txt                # Python dependencies
├── docker-compose.yml             # Docker services configuration
└── .env.example                   # Environment variables template
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- DigitalOcean Spaces account (or S3-compatible storage)
- DeepInfra API key

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd backend-source
   ```

2. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Install dependencies**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. **Start infrastructure services**:
   ```bash
   docker-compose up -d
   ```

5. **Run the API server**:
   ```bash
   uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
   ```

### Testing

```bash
# Run all tests
pytest

# Run integration tests only
pytest tests/integration/

# Run contract tests only
pytest tests/contract/

# Generate coverage report
pytest --cov=src --cov-report=html
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DO_SPACES_ACCESS_KEY` | DigitalOcean Spaces access key | Required |
| `DO_SPACES_SECRET_KEY` | DigitalOcean Spaces secret key | Required |
| `DO_SPACES_ENDPOINT` | Spaces endpoint URL | `https://gov-ai-vectorization.lon1.digitaloceanspaces.com` |
| `DO_SPACES_REGION` | Spaces region | `lon1` |
| `DO_SPACES_BUCKET` | Bucket name | `gov-ai-vectorization` |
| `DEEPINFRA_API_KEY` | DeepInfra API key for embeddings | Required |
| `QDRANT_URL` | Qdrant server URL | `http://localhost:6333` |
| `QDRANT_COLLECTION_NAME` | Collection name | `gov_uk_immigration` |
| `EMBEDDING_MODEL` | Embedding model identifier | `intfloat/e5-large-v2` |
| `EMBEDDING_DIMENSIONS` | Embedding vector dimensions | `1024` |
| `EMBEDDING_BATCH_SIZE` | Batch size for embedding | `32` |
| `RAG_ENABLED` | Enable RAG functionality | `true` |
| `RAG_TOP_K` | Number of documents to retrieve | `5` |
| `RAG_BINARY_QUANTIZATION` | Enable binary quantization | `true` |

### Google OAuth Configuration

```bash
GOOGLE_OAUTH_CLIENT_ID=<your-google-client-id>
# Backend verifies Google ID tokens using Google's public JWKS
```

## 📊 Database Schema

### Qdrant Collection

- **Collection Name**: `gov_uk_immigration`
- **Vector Size**: 1024
- **Distance Metric**: Cosine
- **Quantization**: Binary (uint8) for 97% storage reduction
- **Payload Schema**:
  ```json
  {
    "document_id": "string",
    "title": "string",
    "url": "string",
    "content": "string",
    "metadata": {
      "section": "string",
      "last_updated": "datetime"
    }
  }
  ```

### PostgreSQL Tables

Document metadata, user sessions, and audit logs stored in PostgreSQL (schema TBD).

### Neo4J Knowledge Graph (Planned - Phase 4)

Entity and relationship extraction for advanced graph-based RAG:

- **Node Types**: VisaType, Requirement, Document_Type, Organization, Country, Process, Condition
- **Relationships**: REQUIRES, SATISFIED_BY, DEPENDS_ON, CAN_TRANSITION_TO, etc.
- **Traversal**: Multi-hop reasoning for complex queries (e.g., "What documents needed for spouse visa if previous student visa?")
- **Status**: Specification complete (see `NEO4J_GRAPH_TRAVERSAL_SPEC.md`), implementation planned for Phase 4

See [NEO4J_GRAPH_TRAVERSAL_SPEC.md](./NEO4J_GRAPH_TRAVERSAL_SPEC.md) for detailed architecture and implementation plan.

## 🔌 API Endpoints

### RAG Query

**POST** `/api/v1/rag/query`

Request:
```json
{
  "query": "What are the visa requirements for skilled workers?",
  "top_k": 5,
  "include_metadata": true
}
```

Response:
```json
{
  "query": "What are the visa requirements for skilled workers?",
  "documents": [
    {
      "content": "...",
      "score": 0.87,
      "metadata": {
        "title": "Skilled Worker visa",
        "url": "https://www.gov.uk/skilled-worker-visa"
      }
    }
  ],
  "total_results": 5,
  "processing_time_ms": 245
}
```

### Authentication

**POST** `/api/v1/auth/token`

Request:
```json
{
  "username": "user@example.com",
  "password": "password"
}
```

Response:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

## 🏗️ Architecture

### Haystack RAG Pipeline

```
Query → QueryPreprocessor → DeepInfraEmbedder → QdrantStore (Semantic Search)
                                               → BM25Ranker (Keyword Search)
                                               → Merge Results
                                               → CrossEncoderRanker
                                               → Top K Documents
```

### Data Flow

1. **Ingestion**: Documents scraped → Chunked → Embedded → Stored in Qdrant + PostgreSQL
2. **Query**: User query → Preprocessed → Embedded → Hybrid search → Reranked → Response
3. **LLM**: Retrieved docs → Context → OpenRouter API → Generated response

## 🔐 Security

- **Authentication**: Google OAuth 2.0 with JWT ID token verification
- **Authorization**: Role-based access control (Admin/Examiner/Operator) mapped from Google email domains
- **Rate Limiting**: Redis-backed request throttling with per-user limits
- **Data Residency**: All processing on UK-based DigitalOcean droplet (161.35.44.166)
- **Secrets Management**: Environment variables, never committed to git
- **Security Headers**: OWASP-compliant headers (CSP, HSTS, X-Frame-Options)

## 📈 Performance

- **Query Latency**: 775-1113ms (with binary quantization)
- **Throughput**: ~100 req/sec (single instance)
- **Vector Storage**: 194KB (1,209 vectors with quantization) vs 5MB uncompressed
- **Embedding Batch Size**: 32 documents per request

## 🛠️ Development

### Adding New Embedding Models

Support for multi-modal embeddings (image, video, audio) can be added by:

1. Create new embedder component in `src/rag/components/`
2. Register with Haystack pipeline
3. Configure model in environment variables

Example:
```python
# src/rag/components/image_embedder.py
from haystack import component

@component
class CLIPImageEmbedder:
    def run(self, images: List[str]) -> dict:
        # Implement CLIP embedding logic
        pass
```

### Adding New Search Strategies

Extend `src/rag/pipelines/haystack_retrieval.py` with custom retrievers:

```python
from haystack.components.retrievers import CustomRetriever

pipeline.add_component("custom_retriever", CustomRetriever())
```

## 📝 License

All content available under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)

## 🤝 Contributing

1. Follow [GOV.UK Design Principles](https://www.gov.uk/guidance/government-design-principles)
2. Comply with [WCAG 2.1 AA](https://www.w3.org/WAI/WCAG21/quickref/?currentsidebar=%23col_customize&levels=aaa)
3. Follow [NCSC security guidelines](https://www.ncsc.gov.uk/collection/developers-collection)
4. Write tests for all new features
5. Document configuration changes

## 🆘 Support

For issues, questions, or contributions, please refer to the project documentation or contact the maintainers.

## 🔮 Roadmap

### Phase 1: Core RAG (Complete)
- ✅ Haystack Core integration
- ✅ Hybrid search (Vector + BM25)
- ✅ Cross-encoder reranking
- ✅ Binary quantization
- ✅ Google OAuth authentication

### Phase 2: Template Workflow (Complete)
- ✅ Document analysis with LLM
- ✅ Placeholder-based templating
- ✅ Decision library system

### Phase 3: Advanced Features (Planned)
- ⏳ Guard checks & citation enforcement
- ⏳ User feedback collection
- ⏳ Multi-vector embeddings

### Phase 4: Knowledge Graph (Planned)
- 📋 Neo4J entity extraction
- 📋 Graph traversal retrieval
- 📋 Multi-hop reasoning
- 📋 Explainability UI

---

**Last Updated**: 2025-11-07
**Version**: 1.2.0
**Status**: Production-ready (Phase 1-2 complete)
