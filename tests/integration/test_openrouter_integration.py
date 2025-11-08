"""
T019: Integration test for OpenRouter service (Feature 018)
Tests summarization and translation with mocked OpenRouter API responses.

Test Coverage:
- summarize() with mocked API response
- translate() with mocked API response
- Timeout handling (30s timeout)
- Rate limiting (10 req/min)
- Cache hit scenario (second request returns cached result)
- Cache expiration (24h TTL)

Mocking Strategy:
- Mock httpx.AsyncClient to avoid real API calls and costs
- Mock database session for cache operations
- Simulate OpenRouter API responses
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.orm import Session

from src.services.openrouter_service import OpenRouterService
from src.models.document_summary import DocumentSummary
from src.models.document_translation import DocumentTranslation


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_db_session():
    """Create mock database session for cache operations."""
    session = MagicMock(spec=Session)

    # Mock query chain for DocumentSummary
    summary_query = MagicMock()
    summary_filter = MagicMock()
    summary_first = MagicMock(return_value=None)  # Default: no cached result
    summary_filter.first = summary_first
    summary_query.filter.return_value = summary_filter

    # Mock query chain for DocumentTranslation
    translation_query = MagicMock()
    translation_filter = MagicMock()
    translation_first = MagicMock(return_value=None)  # Default: no cached result
    translation_filter.first = translation_first
    translation_query.filter.return_value = translation_filter

    # Setup query routing
    def query_router(model_class):
        if model_class == DocumentSummary:
            return summary_query
        elif model_class == DocumentTranslation:
            return translation_query
        raise ValueError(f"Unexpected model class: {model_class}")

    session.query.side_effect = query_router
    session.add = MagicMock()
    session.commit = MagicMock()
    session.refresh = MagicMock()

    return session


@pytest.fixture
def mock_openrouter_response_summarize():
    """Mock successful OpenRouter API response for summarize."""
    return {
        "id": "gen-abc123",
        "model": "anthropic/claude-3.5-sonnet",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        "This guidance document explains how to apply for a Skilled Worker visa in the UK. "
                        "You need a job offer from a UK employer with a valid sponsor license. The employer must "
                        "provide a Certificate of Sponsorship (CoS) with details of your role and salary. You must "
                        "meet English language requirements at CEFR Level B1 and show you can financially support "
                        "yourself. The visa costs £610-£1,408 depending on your circumstances, plus the Immigration "
                        "Health Surcharge. Processing takes approximately 3 weeks. You can apply up to 3 months "
                        "before your start date. The visa is valid for up to 5 years and can be extended. "
                        "After 5 years, you may be eligible for indefinite leave to remain. Required documents "
                        "include passport, CoS reference number, proof of knowledge of English, tuberculosis test "
                        "results if applicable, and evidence of maintenance funds. Some applicants may need a criminal "
                        "record certificate. You can include your partner and children as dependents on your application."
                    )
                }
            }
        ],
        "usage": {
            "prompt_tokens": 512,
            "completion_tokens": 198,
            "total_tokens": 710
        }
    }


@pytest.fixture
def mock_openrouter_response_translate():
    """Mock successful OpenRouter API response for translate."""
    return {
        "id": "gen-xyz789",
        "model": "anthropic/claude-3.5-sonnet",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        "A Skilled Worker visa lets you come to the UK to work in a specific job. "
                        "First, you need a job offer from a UK company that's approved by the government. "
                        "The company gives you a special certificate with your job details. You must speak "
                        "English well enough and show you have enough money to support yourself. The visa "
                        "costs between £610 and £1,408 plus a healthcare fee. You'll usually get a decision "
                        "in about 3 weeks. You can apply up to 3 months before you start work. The visa "
                        "lasts for up to 5 years and you can extend it. After 5 years, you might be able "
                        "to stay in the UK permanently. You need to provide your passport, the certificate "
                        "from your employer, proof you speak English, a health check if needed, and bank "
                        "statements. Your husband, wife, or children can apply with you if they want to come too."
                    )
                }
            }
        ],
        "usage": {
            "prompt_tokens": 485,
            "completion_tokens": 176,
            "total_tokens": 661
        }
    }


@pytest.fixture
def mock_openrouter_timeout():
    """Mock OpenRouter API timeout response."""
    raise asyncio.TimeoutError("OpenRouter API request timed out after 30s")


# ============================================================================
# T019: Summarize Tests
# ============================================================================


@pytest.mark.asyncio
async def test_summarize_success_with_mocked_api(mock_db_session, mock_openrouter_response_summarize):
    """T019: Test summarize with mocked OpenRouter API response."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_openrouter_response_summarize
        mock_post.return_value = mock_response

        # Create service instance
        service = OpenRouterService(mock_db_session)

        # Execute summarize
        result = await service.summarize(
            document_id="doc_skilled_worker_visa",
            document_text="Long document text about Skilled Worker visa...",
            max_words=200,
            user_id="test_user_123"
        )

        # Assert result structure
        assert "document_id" in result
        assert "summary_text" in result
        assert "word_count" in result
        assert "model_used" in result

        assert result["document_id"] == "doc_skilled_worker_visa"
        assert len(result["summary_text"]) >= 50  # Minimum 50 words
        assert 150 <= result["word_count"] <= 250  # Validation range
        assert result["model_used"] == "anthropic/claude-3.5-sonnet"

        # Verify API was called
        mock_post.assert_called_once()

        # Verify cache was saved
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_summarize_cache_hit(mock_db_session):
    """T019: Test cache hit scenario - second request returns cached result."""
    # Create cached summary
    cached_summary = DocumentSummary(
        document_id="doc_cached_001",
        summary_text="This is a cached summary " * 30,  # ~180 words
        word_count=180,
        model_used="anthropic/claude-3.5-sonnet",
        generated_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=24),
        user_id="test_user_123"
    )

    # Configure mock to return cached result
    summary_query = mock_db_session.query(DocumentSummary)
    summary_query.filter.return_value.first.return_value = cached_summary

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        # Create service instance
        service = OpenRouterService(mock_db_session)

        # Execute summarize
        result = await service.summarize(
            document_id="doc_cached_001",
            document_text="Document text...",
            max_words=200,
            user_id="test_user_123"
        )

        # Assert cached result returned
        assert result["document_id"] == "doc_cached_001"
        assert result["summary_text"] == cached_summary.summary_text
        assert result["word_count"] == 180
        assert result["model_used"] == "anthropic/claude-3.5-sonnet"
        assert result["cached"] is True

        # Verify API was NOT called (cache hit)
        mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_cache_expiration(mock_db_session, mock_openrouter_response_summarize):
    """T019: Test cache expiration - expired cache triggers new API call."""
    # Create expired cached summary
    expired_summary = DocumentSummary(
        document_id="doc_expired_001",
        summary_text="This is an expired summary " * 30,
        word_count=180,
        model_used="anthropic/claude-3.5-sonnet",
        generated_at=datetime.utcnow() - timedelta(hours=25),  # 25 hours ago
        expires_at=datetime.utcnow() - timedelta(hours=1),  # Expired 1 hour ago
        user_id="test_user_123"
    )

    # Configure mock to return expired result
    summary_query = mock_db_session.query(DocumentSummary)
    summary_query.filter.return_value.first.return_value = expired_summary

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_openrouter_response_summarize
        mock_post.return_value = mock_response

        # Create service instance
        service = OpenRouterService(mock_db_session)

        # Execute summarize
        result = await service.summarize(
            document_id="doc_expired_001",
            document_text="Document text...",
            max_words=200,
            user_id="test_user_123"
        )

        # Assert new result generated (not expired cache)
        assert result["cached"] is False

        # Verify API was called (cache expired)
        mock_post.assert_called_once()

        # Verify new cache entry saved
        mock_db_session.add.assert_called_once()


# ============================================================================
# T019: Translate Tests
# ============================================================================


@pytest.mark.asyncio
async def test_translate_success_with_mocked_api(mock_db_session, mock_openrouter_response_translate):
    """T019: Test translate with mocked OpenRouter API response."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_openrouter_response_translate
        mock_post.return_value = mock_response

        # Create service instance
        service = OpenRouterService(mock_db_session)

        # Execute translate
        result = await service.translate(
            document_id="doc_skilled_worker_visa",
            document_text="Complex legal text about Skilled Worker visa requirements...",
            reading_level="grade8",
            user_id="test_user_123"
        )

        # Assert result structure
        assert "document_id" in result
        assert "translated_text" in result
        assert "reading_level" in result
        assert "model_used" in result

        assert result["document_id"] == "doc_skilled_worker_visa"
        assert len(result["translated_text"]) >= 50  # Minimum 50 words
        assert result["reading_level"] == "grade8"
        assert result["model_used"] == "anthropic/claude-3.5-sonnet"

        # Verify API was called
        mock_post.assert_called_once()

        # Verify cache was saved
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_translate_cache_hit_different_reading_levels(mock_db_session):
    """T019: Test that different reading levels create separate cache entries."""
    # Create cached translations for different reading levels
    cached_grade6 = DocumentTranslation(
        document_id="doc_multi_level",
        reading_level="grade6",
        translated_text="Very simple translation " * 30,
        model_used="anthropic/claude-3.5-sonnet",
        generated_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=24),
        user_id="test_user_123"
    )

    cached_grade10 = DocumentTranslation(
        document_id="doc_multi_level",
        reading_level="grade10",
        translated_text="More complex translation " * 30,
        model_used="anthropic/claude-3.5-sonnet",
        generated_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=24),
        user_id="test_user_123"
    )

    # Test grade6 cache hit
    translation_query = mock_db_session.query(DocumentTranslation)
    translation_query.filter.return_value.first.return_value = cached_grade6

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        service = OpenRouterService(mock_db_session)

        result_grade6 = await service.translate(
            document_id="doc_multi_level",
            document_text="Document text...",
            reading_level="grade6",
            user_id="test_user_123"
        )

        assert result_grade6["reading_level"] == "grade6"
        assert result_grade6["translated_text"] == cached_grade6.translated_text
        assert result_grade6["cached"] is True

        # No API call for cache hit
        mock_post.assert_not_called()

    # Test grade10 cache hit (different cache entry)
    translation_query.filter.return_value.first.return_value = cached_grade10

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        service = OpenRouterService(mock_db_session)

        result_grade10 = await service.translate(
            document_id="doc_multi_level",
            document_text="Document text...",
            reading_level="grade10",
            user_id="test_user_123"
        )

        assert result_grade10["reading_level"] == "grade10"
        assert result_grade10["translated_text"] == cached_grade10.translated_text
        assert result_grade10["cached"] is True

        # No API call for cache hit
        mock_post.assert_not_called()


# ============================================================================
# T019: Timeout and Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def test_summarize_timeout_handling(mock_db_session):
    """T019: Test timeout handling - OpenRouter API timeout after 30s."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        # Simulate timeout after 30s
        mock_post.side_effect = asyncio.TimeoutError("Request timed out")

        service = OpenRouterService(mock_db_session)

        # Assert timeout exception raised
        with pytest.raises(Exception) as exc_info:
            await service.summarize(
                document_id="doc_timeout_test",
                document_text="Document text...",
                max_words=200,
                user_id="test_user_123"
            )

        # Verify timeout was raised
        assert "timeout" in str(exc_info.value).lower() or isinstance(exc_info.value, asyncio.TimeoutError)


@pytest.mark.asyncio
async def test_translate_api_error_handling(mock_db_session):
    """T019: Test API error handling - OpenRouter returns 500 error."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        # Simulate API error
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "Internal server error"}
        mock_post.return_value = mock_response

        service = OpenRouterService(mock_db_session)

        # Assert exception raised
        with pytest.raises(Exception) as exc_info:
            await service.translate(
                document_id="doc_error_test",
                document_text="Document text...",
                reading_level="grade8",
                user_id="test_user_123"
            )

        # Verify error was raised
        assert exc_info.value is not None


# ============================================================================
# T019: Rate Limiting Tests
# ============================================================================


@pytest.mark.asyncio
async def test_rate_limiting_10_requests_per_minute(mock_db_session, mock_openrouter_response_summarize):
    """T019: Test rate limiting - 10 requests per minute per user."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_openrouter_response_summarize
        mock_post.return_value = mock_response

        service = OpenRouterService(mock_db_session)

        # Make 10 requests (should succeed)
        for i in range(10):
            result = await service.summarize(
                document_id=f"doc_ratelimit_{i}",
                document_text="Document text...",
                max_words=200,
                user_id="test_user_ratelimit"
            )
            assert result is not None

        # 11th request should fail with rate limit error
        with pytest.raises(Exception) as exc_info:
            await service.summarize(
                document_id="doc_ratelimit_11",
                document_text="Document text...",
                max_words=200,
                user_id="test_user_ratelimit"
            )

        # Verify rate limit exception
        assert "rate limit" in str(exc_info.value).lower() or "too many requests" in str(exc_info.value).lower()


# ============================================================================
# T019: Validation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_summarize_validation_max_words_range(mock_db_session):
    """T019: Test max_words validation - must be 150-250."""
    service = OpenRouterService(mock_db_session)

    # Test below minimum (149)
    with pytest.raises(ValueError) as exc_info:
        await service.summarize(
            document_id="doc_validate",
            document_text="Text...",
            max_words=149,
            user_id="test_user"
        )
    assert "150-250" in str(exc_info.value)

    # Test above maximum (251)
    with pytest.raises(ValueError) as exc_info:
        await service.summarize(
            document_id="doc_validate",
            document_text="Text...",
            max_words=251,
            user_id="test_user"
        )
    assert "150-250" in str(exc_info.value)


@pytest.mark.asyncio
async def test_translate_validation_reading_level(mock_db_session):
    """T019: Test reading_level validation - must be grade6/8/10."""
    service = OpenRouterService(mock_db_session)

    # Test invalid reading level
    with pytest.raises(ValueError) as exc_info:
        await service.translate(
            document_id="doc_validate",
            document_text="Text...",
            reading_level="grade12",
            user_id="test_user"
        )
    assert "grade6" in str(exc_info.value) or "grade8" in str(exc_info.value) or "grade10" in str(exc_info.value)
