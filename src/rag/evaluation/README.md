# Reranker Bakeoff Evaluation

Comparative evaluation framework for testing reranker models on UK immigration corpus.

## Overview

This bakeoff compares:
1. **DeepInfra Qwen/Qwen3-Reranker-8B** - Primary candidate (vendor consolidation)
2. **Cohere rerank-english-v3.0** - Quality benchmark

### Metrics Evaluated

- **NDCG@10**: Ranking quality with graded relevance (0-1, higher is better)
- **MRR**: Mean Reciprocal Rank (0-1, higher is better)
- **Score Distribution**: Variance and range (detects uniform scoring issue)
- **Latency**: P50, P95, P99 (milliseconds)
- **Cost**: Estimated cost per 1M reranks

## Prerequisites

### API Keys Required

```bash
# DeepInfra (for Qwen reranker)
export DEEPINFRA_API_KEY="your_deepinfra_key"

# Cohere (for benchmark comparison)
export COHERE_API_KEY="your_cohere_key"
```

### Python Dependencies

```bash
pip install numpy scipy requests
```

## Quick Start

### 1. Verify API Keys

```bash
cd /Volumes/TerrysPOV/gov_content_ai/backend-source

# Test DeepInfra connection
python3 -c "
from src.rag.components.deepinfra_reranker import DeepInfraReranker
reranker = DeepInfraReranker()
print(reranker.validate_health())
"

# Test Cohere connection
python3 -c "
from src.rag.components.cohere_reranker import CohereReranker
reranker = CohereReranker()
print(reranker.validate_health())
"
```

### 2. Run Bakeoff

```bash
python3 src/rag/evaluation/reranker_bakeoff.py \
  --test-cases test_data/reranker_test_queries.json \
  --output results/reranker_bakeoff_results.json
```

### 3. Review Results

The bakeoff will print a detailed report:

```
================================================================================
RERANKER BAKEOFF RESULTS
================================================================================

📊 RANKING QUALITY
--------------------------------------------------------------------------------
Model                NDCG@10      MRR          Queries
--------------------------------------------------------------------------------
cohere-v3            0.925        0.850        10
qwen-8b              0.910        0.830        10

📈 SCORE DISTRIBUTION
--------------------------------------------------------------------------------
Model                Variance Mean    Variance Std    Range
--------------------------------------------------------------------------------
cohere-v3            0.052000         0.012000        (0.120, 0.980)
qwen-8b              0.048000         0.011000        (0.110, 0.970)

⚡ LATENCY
--------------------------------------------------------------------------------
Model                P50 (ms)     P95 (ms)     P99 (ms)
--------------------------------------------------------------------------------
qwen-8b              120.5        145.2        150.8
cohere-v3            180.3        220.5        235.1

💰 COST
--------------------------------------------------------------------------------
Model                Cost/1M reranks
--------------------------------------------------------------------------------
qwen-8b              $50.00
cohere-v3            $200.00

🎯 RECOMMENDATION
--------------------------------------------------------------------------------
🏆 Best Quality: cohere-v3 (NDCG@10: 0.925)
💎 Best Value: qwen-8b

⚠️  WARNINGS
--------------------------------------------------------------------------------
No issues detected ✓
```

## Decision Criteria

### If Qwen within 5% of Cohere quality:
```
✅ Deploy Qwen-8B
- Save $150/month
- Vendor consolidation with DeepInfra embeddings
- Competitive quality (BEIR 57.2 vs 58.5)
```

### If Cohere significantly better (>5% improvement):
```
✅ Deploy Cohere
- Best-in-class quality
- Production SLA (99.9%)
- Cost acceptable for government service ($200/month)
```

## Test Dataset

**Location**: `test_data/reranker_test_queries.json`

**Format**:
- 10 UK immigration queries (expandable to 500)
- Categories: Factual (40%), Procedural (40%), Multi-hop (20%)
- Relevance scores: 0 (irrelevant) to 3 (highly relevant)

**Example**:
```json
{
  "query_id": "q001",
  "query_text": "What is a BNO visa?",
  "documents": [
    "The British National (Overseas) visa allows...",
    "A Standard Visitor visa allows...",
    ...
  ],
  "relevance_scores": [3, 1, 0, 0, 0],
  "category": "factual"
}
```

## Expanding Test Dataset

To create a comprehensive 500-query dataset:

### Option 1: Manual Annotation
1. Extract 500 real user queries from logs
2. Retrieve top 10 documents per query
3. Human annotators rate relevance (0-3 scale)
4. Cost: ~$500 for annotation (crowdsourcing)

### Option 2: LLM-Judged Relevance
1. Extract queries from logs
2. Retrieve documents
3. GPT-4 rates relevance with prompting
4. Human validation on 10% sample
5. Cost: ~$50 for LLM judging

## Critical Tests

### 1. Uniform Scoring Detection
```python
# CRITICAL: Ensure reranker doesn't mask RRF scores
if result.score_variance < 0.0001:
    logger.warning("⚠️ UNIFORM SCORING DETECTED")
```

### 2. RRF Correlation
```python
# Verify reranker IMPROVES RRF, not replaces it
correlation = spearmanr(reranked_scores, rrf_scores)
# Expected: correlation > 0.7 (strong preservation)
```

### 3. Latency Threshold
```python
# Ensure <200ms P95 for production
assert result.latency_p95 < 200, "Latency too high"
```

## Next Steps After Bakeoff

### 1. Deploy Winning Model

**If Qwen-8B wins**:
```python
# Update haystack_retrieval.py
from rag.components.deepinfra_reranker import DeepInfraReranker

reranker = DeepInfraReranker(model="Qwen/Qwen3-Reranker-8B")
```

**If Cohere wins**:
```python
# Update haystack_retrieval.py
from rag.components.cohere_reranker import CohereReranker

reranker = CohereReranker(model="rerank-english-v3.0")
```

### 2. Production Deployment
```bash
# Deploy to 161.35.44.166
scp -r backend-source root@161.35.44.166:/opt/gov_ai_backend/

# Restart service
ssh root@161.35.44.166 "systemctl restart gov-ai-backend"
```

### 3. Monitor Performance
- Track NDCG@10 on production queries
- Monitor latency P95/P99
- Alert if score variance drops <0.001

### 4. Proceed with RAG-Adv
Once reranker deployed and validated:
```bash
# Implement rag-adv-updated (Phases B-2 to B-7)
# Then rag-advanced-phase2 (Phases B-8 to B-11)
```

## Troubleshooting

### Issue: "No reranker models initialized"
**Solution**: Set API keys in environment
```bash
export DEEPINFRA_API_KEY="..."
export COHERE_API_KEY="..."
```

### Issue: "Low score variance detected"
**Solution**: Model may have uniform scoring issue - try alternative model

### Issue: High latency (>200ms P95)
**Solution**: Check network connection, try smaller model (Qwen-4B), or enable batch processing

## Files

```
backend-source/
├── src/rag/components/
│   ├── deepinfra_reranker.py    # Qwen reranker
│   └── cohere_reranker.py       # Cohere reranker
├── src/rag/evaluation/
│   ├── reranker_bakeoff.py      # Bakeoff framework
│   └── README.md                # This file
└── test_data/
    └── reranker_test_queries.json  # Test dataset (10 queries)
```

## References

- **RAS Framework**: https://levelup.gitconnected.com/4adfc7e810d0
- **Memory #61**: Cross-encoder reranker masking issue
- **RAG-Adv Spec**: `.specify/specs/feature_rag-adv-updated.md`
- **Phase 2 Spec**: `.specify/specs/rag-advanced-phase2/spec.md`
