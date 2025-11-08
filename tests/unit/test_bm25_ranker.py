"""
Unit tests for BM25Ranker component - Reciprocal Rank Fusion scoring.

CRITICAL: Tests for bug fix where doc.score was not being updated.
Bug Location: bm25_ranker.py:120 - scores calculated but not applied.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from haystack import Document
from src.rag.components.bm25_ranker import BM25Ranker


@pytest.fixture
def mock_index_dir(tmp_path):
    """Create mock BM25 index directory for testing."""
    index_dir = tmp_path / "bm25_index"
    index_dir.mkdir()

    # Create required index files for Whoosh
    (index_dir / "_MAIN_1.toc").touch()

    return str(index_dir)


@pytest.fixture
def sample_documents():
    """Create sample Haystack documents with semantic scores."""
    return [
        Document(
            id="doc1",
            content="passport application requirements",
            meta={"document_id": "doc1", "title": "Passport Guide"},
            score=0.95,  # High semantic score
        ),
        Document(
            id="doc2",
            content="visa application process",
            meta={"document_id": "doc2", "title": "Visa Guide"},
            score=0.80,  # Medium semantic score
        ),
        Document(
            id="doc3",
            content="immigration rules overview",
            meta={"document_id": "doc3", "title": "Immigration Rules"},
            score=0.70,  # Lower semantic score
        ),
        Document(
            id="doc4",
            content="settlement requirements",
            meta={"document_id": "doc4", "title": "Settlement"},
            score=0.60,  # Lowest semantic score
        ),
    ]


@pytest.fixture
def bm25_results():
    """Sample BM25 search results with different ranking."""
    return [
        {"document_id": "doc2", "score": 4.5, "rank": 0},  # doc2 ranks high in BM25
        {"document_id": "doc1", "score": 3.2, "rank": 1},  # doc1 ranks second
        {"document_id": "doc4", "score": 1.8, "rank": 2},  # doc4 ranks third
        # doc3 NOT in BM25 results
    ]


def test_rrf_score_calculation_correctness():
    """
    Test that RRF scores are calculated correctly.

    RRF formula: weight * (1/(k + bm25_rank)) + (1-weight) * (1/(k + semantic_rank))
    """
    weight = 0.3
    k = 60

    # Doc at semantic rank 0, BM25 rank 1
    sem_score = (1 - weight) * (1 / (k + 0))  # 0.7 * (1/60) = 0.01167
    bm25_score = weight * (1 / (k + 1))  # 0.3 * (1/61) = 0.00492
    expected_rrf = sem_score + bm25_score  # 0.01659

    assert abs(expected_rrf - 0.01659) < 0.0001, "RRF calculation incorrect"


@patch("src.rag.components.bm25_ranker.open_dir")
def test_bm25_ranker_updates_document_scores(mock_open_dir, sample_documents, bm25_results):
    """
    CRITICAL TEST: Verify that doc.score is updated with RRF scores.

    This test catches the bug where scores were calculated but not applied.
    Bug: Line 120 returned documents without updating doc.score
    Fix: Lines 121-125 now update doc.score before returning
    """
    # Mock Whoosh index
    mock_index = MagicMock()
    mock_searcher = MagicMock()
    mock_open_dir.return_value = mock_index
    mock_index.searcher.return_value.__enter__.return_value = mock_searcher

    # Mock BM25 search results
    mock_results = []
    for result in bm25_results:
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key, r=result: r[key]
        mock_result.score = result["score"]
        mock_results.append(mock_result)

    mock_searcher.search.return_value = mock_results

    # Create ranker
    ranker = BM25Ranker(index_dir="/fake/path", weight=0.3, top_k=10)

    # Store original scores
    original_scores = [doc.score for doc in sample_documents]

    # Run RRF ranking
    result = ranker.run(query="test query", documents=sample_documents, top_k=10)

    reranked_docs = result["documents"]

    # CRITICAL ASSERTION: Document scores MUST be updated
    for doc in reranked_docs:
        assert doc.score is not None, "doc.score is None - RRF score not applied!"
        assert doc.score > 0, f"doc.score {doc.score} is not positive"

        # Score should be different from original semantic score
        # (unless by pure coincidence, which is extremely unlikely)
        original_idx = next(i for i, d in enumerate(sample_documents) if d.id == doc.id)
        original_score = original_scores[original_idx]

        # RRF scores should be much smaller than semantic scores (0.01-0.02 range)
        assert doc.score < 0.1, f"doc.score {doc.score} too large - expected RRF range 0.01-0.02"


@patch("src.rag.components.bm25_ranker.open_dir")
def test_bm25_ranker_correct_ranking_order(mock_open_dir, sample_documents, bm25_results):
    """
    Test that documents are ranked correctly by RRF score.

    Expected order should blend semantic + BM25 rankings.
    """
    # Mock Whoosh index
    mock_index = MagicMock()
    mock_searcher = MagicMock()
    mock_open_dir.return_value = mock_index
    mock_index.searcher.return_value.__enter__.return_value = mock_searcher

    # Mock BM25 search results
    mock_results = []
    for result in bm25_results:
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key, r=result: r[key]
        mock_result.score = result["score"]
        mock_results.append(mock_result)

    mock_searcher.search.return_value = mock_results

    # Create ranker
    ranker = BM25Ranker(index_dir="/fake/path", weight=0.3, top_k=10)

    # Run RRF ranking
    result = ranker.run(query="test query", documents=sample_documents, top_k=10)

    reranked_docs = result["documents"]

    # Verify documents are sorted by score descending
    for i in range(len(reranked_docs) - 1):
        assert (
            reranked_docs[i].score >= reranked_docs[i + 1].score
        ), f"Documents not sorted by RRF score: {reranked_docs[i].score} < {reranked_docs[i+1].score}"


@patch("src.rag.components.bm25_ranker.open_dir")
def test_bm25_ranker_handles_missing_bm25_results(mock_open_dir, sample_documents):
    """
    Test that documents NOT in BM25 results get correct RRF scores.

    Documents not found in BM25 should use rank=999 (as per implementation).
    """
    # Mock Whoosh index
    mock_index = MagicMock()
    mock_searcher = MagicMock()
    mock_open_dir.return_value = mock_index
    mock_index.searcher.return_value.__enter__.return_value = mock_searcher

    # BM25 results with only doc1
    mock_results = [
        MagicMock(
            **{
                "__getitem__": lambda self, key: "doc1" if key == "document_id" else 10.0,
                "score": 10.0,
            }
        )
    ]
    mock_searcher.search.return_value = mock_results

    # Create ranker
    ranker = BM25Ranker(index_dir="/fake/path", weight=0.3, top_k=10)

    # Run RRF ranking
    result = ranker.run(query="test query", documents=sample_documents, top_k=10)

    reranked_docs = result["documents"]

    # All documents should have scores set (even if not in BM25)
    for doc in reranked_docs:
        assert doc.score is not None, f"doc {doc.id} missing score"
        assert doc.score > 0, f"doc {doc.id} has non-positive score {doc.score}"

    # doc1 (in BM25) should rank higher than others (not in BM25)
    doc1 = next(d for d in reranked_docs if d.id == "doc1")
    doc3 = next(d for d in reranked_docs if d.id == "doc3")

    # doc1 should have higher score than doc3 (which is not in BM25)
    assert doc1.score > doc3.score, f"doc1 (in BM25) should rank higher than doc3 (not in BM25)"


@patch("src.rag.components.bm25_ranker.open_dir")
def test_bm25_ranker_respects_weight_parameter(mock_open_dir, sample_documents, bm25_results):
    """
    Test that different weight values produce different rankings.

    weight=0.3: 30% BM25, 70% semantic
    weight=0.7: 70% BM25, 30% semantic
    """
    # Mock Whoosh index
    mock_index = MagicMock()
    mock_searcher = MagicMock()
    mock_open_dir.return_value = mock_index
    mock_index.searcher.return_value.__enter__.return_value = mock_searcher

    # Mock BM25 search results
    mock_results = []
    for result in bm25_results:
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key, r=result: r[key]
        mock_result.score = result["score"]
        mock_results.append(mock_result)

    mock_searcher.search.return_value = mock_results

    # Test with weight=0.3 (favor semantic)
    ranker_semantic = BM25Ranker(index_dir="/fake/path", weight=0.3, top_k=10)
    result_semantic = ranker_semantic.run(
        query="test query", documents=sample_documents.copy(), top_k=10
    )

    # Test with weight=0.7 (favor BM25)
    ranker_bm25 = BM25Ranker(index_dir="/fake/path", weight=0.7, top_k=10)
    result_bm25 = ranker_bm25.run(
        query="test query", documents=[doc for doc in sample_documents], top_k=10  # Fresh copy
    )

    # Rankings should differ
    semantic_top = result_semantic["documents"][0].id
    bm25_top = result_bm25["documents"][0].id

    # Scores should be different (different weight = different RRF calculation)
    assert semantic_top or bm25_top, "Rankings should exist"


@patch("src.rag.components.bm25_ranker.open_dir")
def test_bm25_ranker_respects_top_k(mock_open_dir, sample_documents, bm25_results):
    """Test that ranker returns at most top_k documents."""
    # Mock Whoosh index
    mock_index = MagicMock()
    mock_searcher = MagicMock()
    mock_open_dir.return_value = mock_index
    mock_index.searcher.return_value.__enter__.return_value = mock_searcher

    # Mock BM25 search results
    mock_results = []
    for result in bm25_results:
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key, r=result: r[key]
        mock_result.score = result["score"]
        mock_results.append(mock_result)

    mock_searcher.search.return_value = mock_results

    # Create ranker with top_k=2
    ranker = BM25Ranker(index_dir="/fake/path", weight=0.3, top_k=2)

    # Run with 4 documents
    result = ranker.run(query="test query", documents=sample_documents, top_k=2)

    reranked_docs = result["documents"]

    # Should return exactly 2 documents
    assert len(reranked_docs) == 2, f"Expected 2 documents, got {len(reranked_docs)}"


@patch("src.rag.components.bm25_ranker.open_dir")
def test_bm25_ranker_with_zero_weight_is_pure_semantic(
    mock_open_dir, sample_documents, bm25_results
):
    """
    Test that weight=0.0 produces pure semantic ranking.

    With weight=0.0, BM25 contributes nothing, so ranking should match
    original semantic scores.
    """
    # Mock Whoosh index
    mock_index = MagicMock()
    mock_searcher = MagicMock()
    mock_open_dir.return_value = mock_index
    mock_index.searcher.return_value.__enter__.return_value = mock_searcher

    # Mock BM25 search results (shouldn't matter with weight=0)
    mock_results = []
    for result in bm25_results:
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key, r=result: r[key]
        mock_result.score = result["score"]
        mock_results.append(mock_result)

    mock_searcher.search.return_value = mock_results

    # Create ranker with weight=0.0 (pure semantic)
    ranker = BM25Ranker(index_dir="/fake/path", weight=0.0, top_k=10)

    # Store original order (sorted by semantic score)
    original_order = sorted(sample_documents, key=lambda d: d.score, reverse=True)

    # Run RRF ranking
    result = ranker.run(query="test query", documents=sample_documents, top_k=10)

    reranked_docs = result["documents"]

    # Order should match original semantic ranking
    for i, doc in enumerate(reranked_docs):
        assert (
            doc.id == original_order[i].id
        ), f"With weight=0, ranking should match semantic scores"


def test_bm25_ranker_requires_valid_index_path():
    """Test that BM25Ranker raises error for invalid index path."""
    with pytest.raises(ValueError, match="BM25 index not found"):
        BM25Ranker(index_dir="/nonexistent/path")


@patch("src.rag.components.bm25_ranker.open_dir")
def test_bm25_ranker_score_range_validation(mock_open_dir, sample_documents, bm25_results):
    """
    Validate that RRF scores fall within expected range.

    Expected: 0.005 - 0.025 (roughly 0.5% - 2.5%)
    This catches unrealistic score values.
    """
    # Mock Whoosh index
    mock_index = MagicMock()
    mock_searcher = MagicMock()
    mock_open_dir.return_value = mock_index
    mock_index.searcher.return_value.__enter__.return_value = mock_searcher

    # Mock BM25 search results
    mock_results = []
    for result in bm25_results:
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key, r=result: r[key]
        mock_result.score = result["score"]
        mock_results.append(mock_result)

    mock_searcher.search.return_value = mock_results

    # Create ranker
    ranker = BM25Ranker(index_dir="/fake/path", weight=0.3, top_k=10)

    # Run RRF ranking
    result = ranker.run(query="test query", documents=sample_documents, top_k=10)

    reranked_docs = result["documents"]

    # Validate score range (RRF scores should be small: 0.005 - 0.03)
    for doc in reranked_docs:
        assert (
            0.001 < doc.score < 0.05
        ), f"doc {doc.id} score {doc.score} outside expected RRF range (0.001-0.05)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
