"""
Contract Tests: Permanent Content-Addressable Translation Caching

Feature: 022-implement-permanent-content
Purpose: Validate internal service contract for permanent caching with hash-based invalidation
Status: FAILING (implementation pending)

These tests define the contract between OpenRouterService and the database layer.
Tests MUST fail until implementation is complete.
"""

import pytest
import hashlib
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy.exc import IntegrityError

# Import will fail until implementation complete - this is expected
try:
    from src.services.openrouter_service import OpenRouterService
    from src.models.document_translation import DocumentTranslation
    from src.database import get_db
except ImportError:
    pytest.skip("Implementation not yet complete", allow_module_level=True)


class TestHashComputation:
    """
    FR-004: System MUST compute unique identifier for source document content
    FR-007: System MUST compute unique identifier for translation prompt templates
    """

    def test_source_hash_is_md5_of_content(self):
        """Source hash must be MD5 of source text"""
        source_text = "You must apply for a visa before entering the UK."
        expected_hash = hashlib.md5(source_text.encode('utf-8')).hexdigest()

        # Mock db_session (not needed for hash computation)
        from unittest.mock import MagicMock
        mock_db = MagicMock()
        service = OpenRouterService(db_session=mock_db)
        actual_hash = service.compute_source_hash(source_text)

        assert actual_hash == expected_hash
        assert len(actual_hash) == 32  # MD5 produces 32 hex characters

    def test_prompt_hash_is_md5_of_template(self):
        """Prompt hash must be MD5 of prompt template string"""
        prompt_template = """Translate to grade 8 level:
{source_text}
Provide clear explanations."""
        expected_hash = hashlib.md5(prompt_template.encode('utf-8')).hexdigest()

        # Mock db_session (not needed for hash computation)
        from unittest.mock import MagicMock
        mock_db = MagicMock()
        service = OpenRouterService(db_session=mock_db)
        actual_hash = service.compute_prompt_hash(prompt_template)

        assert actual_hash == expected_hash
        assert len(actual_hash) == 32

    def test_same_content_produces_same_hash(self):
        """Determinism: Same input must produce identical hash"""
        source_text = "Test content for hashing"

        # Mock db_session (not needed for hash computation)
        from unittest.mock import MagicMock
        mock_db = MagicMock()
        service = OpenRouterService(db_session=mock_db)

        hash1 = service.compute_source_hash(source_text)
        hash2 = service.compute_source_hash(source_text)

        assert hash1 == hash2

    def test_different_content_produces_different_hash(self):
        """Different content must produce different hashes"""

        # Mock db_session (not needed for hash computation)
        from unittest.mock import MagicMock
        mock_db = MagicMock()
        service = OpenRouterService(db_session=mock_db)

        hash1 = service.compute_source_hash("Version 1 content")
        hash2 = service.compute_source_hash("Version 2 content")

        assert hash1 != hash2


class TestCacheLookup:
    """
    FR-014: System MUST use composite key for cache lookups
    FR-015: Cache hit MUST return translation instantly (< 100ms)
    FR-016: Cache miss MUST trigger fresh translation generation
    """

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_translation(self, db_session, mock_env_vars):
        """Cache hit: All 4 keys match → Return cached translation"""
        # Setup: Compute actual hashes for test data
        document_text = "You must apply for a visa before entering the UK."
        service = OpenRouterService(db_session=db_session)

        source_hash = service.compute_source_hash(document_text)
        prompt_template = service._get_prompt_template("grade8")
        prompt_hash = service.compute_prompt_hash(prompt_template)

        # Pre-populate cache with computed hashes
        cached_entry = DocumentTranslation(
            document_id="https://gov.uk/test-doc",
            source_hash=source_hash,
            reading_level="grade8",
            prompt_hash=prompt_hash,
            translated_text="Cached translation text",
            model_used="anthropic/claude-3-haiku"
        )
        db_session.add(cached_entry)
        db_session.commit()

        # Execute: Request translation with same content
        result = await service.translate(
            document_id="https://gov.uk/test-doc",
            document_text=document_text,
            reading_level="grade8"
        )

        # Verify: Cache hit
        assert result["cached"] == True
        assert result["translated_text"] == "Cached translation text"
        assert result["model_used"] == "anthropic/claude-3-haiku"

    @pytest.mark.asyncio
    async def test_cache_hit_performance(self, db_session, mock_env_vars):
        """FR-015: Cache hit must complete in < 100ms"""
        # Setup: Compute actual hashes for test data
        document_text = "Performance test content"
        service = OpenRouterService(db_session=db_session)

        source_hash = service.compute_source_hash(document_text)
        prompt_template = service._get_prompt_template("grade8")
        prompt_hash = service.compute_prompt_hash(prompt_template)

        # Pre-populate cache
        cached_entry = DocumentTranslation(
            document_id="perf-test-doc",
            source_hash=source_hash,
            reading_level="grade8",
            prompt_hash=prompt_hash,
            translated_text="Fast cached result",
            model_used="anthropic/claude-3-haiku"
        )
        db_session.add(cached_entry)
        db_session.commit()

        # Execute: Measure cache lookup time
        start_time = datetime.now()
        result = await service.translate(
            document_id="perf-test-doc",
            document_text=document_text,
            reading_level="grade8"
        )
        elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

        # Verify: < 100ms response time
        assert result["cached"] == True
        assert elapsed_ms < 100

    @pytest.mark.asyncio
    @patch('src.services.openrouter_service.OpenRouterService._call_openrouter_api')
    async def test_cache_miss_triggers_api_call(self, mock_api, db_session, mock_env_vars):
        """Cache miss: No matching keys → Generate new translation"""
        # Mock API returns tuple (translated_text, model_used)
        mock_api.return_value = ("New translation from API", "anthropic/claude-3-haiku")

        # Execute: Request translation with no cached match
        service = OpenRouterService(db_session=db_session)
        result = await service.translate(
            document_id="https://gov.uk/new-doc",
            document_text="New content never seen before",
            reading_level="grade8"
        )

        # Verify: API was called
        assert result["cached"] == False
        assert result["translated_text"] == "New translation from API"
        mock_api.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_stores_result(self, db_session, mock_env_vars):
        """Cache miss: Result must be stored with all 4 keys"""
        with patch('src.services.openrouter_service.OpenRouterService._call_openrouter_api') as mock_api:
            # Mock API returns tuple (translated_text, model_used)
            mock_api.return_value = ("Translation to store", "anthropic/claude-3-haiku")

            service = OpenRouterService(db_session=db_session)
            await service.translate(
                document_id="store-test-doc",
                document_text="Store this content",
                reading_level="grade8"
            )

            # Verify: New row inserted
            stored = db_session.query(DocumentTranslation).filter(
                DocumentTranslation.document_id == "store-test-doc"
            ).first()

            assert stored is not None
            assert stored.source_hash is not None
            assert stored.prompt_hash is not None
            assert stored.reading_level == "grade8"
            assert stored.translated_text == "Translation to store"


class TestContentChangeInvalidation:
    """
    FR-005: System MUST invalidate cached translation when source content changes
    FR-006: System MUST preserve previous translation versions
    """

    @pytest.mark.asyncio
    @patch('src.services.openrouter_service.OpenRouterService._call_openrouter')
    async def test_content_change_triggers_new_translation(self, mock_api, db_session):
        """Content change: source_hash differs → Cache miss → New translation"""
        mock_api.return_value = "Translation v2"

        # Setup: Cache version 1
        v1_entry = DocumentTranslation(
            document_id="doc-with-updates",
            source_hash="hash_v1",
            reading_level="grade8",
            prompt_hash="prompt_hash",
            translated_text="Translation v1",
            model_used="openai/gpt-4"
        )
        db_session.add(v1_entry)
        db_session.commit()

        # Execute: Request with updated content (different hash)
        service = OpenRouterService()
        result = await service.translate(
            source_text="Updated content v2",  # Will hash to different value
            document_id="doc-with-updates",
            reading_level="grade8"
        )

        # Verify: Cache miss, new translation generated
        assert result["cached"] == False
        assert result["translated_text"] == "Translation v2"
        mock_api.assert_called_once()

    @pytest.mark.asyncio
    async def test_old_version_preserved(self, db_session):
        """FR-006: Old translation versions must be retained"""
        with patch('src.services.openrouter_service.OpenRouterService._call_openrouter') as mock_api:
            mock_api.return_value = "Translation v2"

            # Setup: Cache version 1
            v1_entry = DocumentTranslation(
                document_id="preserve-test-doc",
                source_hash="hash_v1",
                reading_level="grade8",
                prompt_hash="prompt_hash",
                translated_text="Translation v1",
                model_used="openai/gpt-4"
            )
            db_session.add(v1_entry)
            db_session.commit()

            # Execute: Generate version 2 (content changed)
            service = OpenRouterService()
            await service.translate(
                source_text="Updated content",
                document_id="preserve-test-doc",
                reading_level="grade8"
            )

            # Verify: Both versions exist
            all_versions = db_session.query(DocumentTranslation).filter(
                DocumentTranslation.document_id == "preserve-test-doc"
            ).all()

            assert len(all_versions) == 2
            assert all_versions[0].translated_text == "Translation v1"
            assert all_versions[1].translated_text == "Translation v2"


class TestPromptVersionInvalidation:
    """
    FR-008: System MUST invalidate all cached translations when prompt template changes
    FR-009: System MUST preserve translations from previous prompt versions
    FR-010: System MUST allow multiple prompt versions to coexist
    """

    @pytest.mark.asyncio
    @patch('src.services.openrouter_service.OpenRouterService._call_openrouter')
    async def test_prompt_change_triggers_new_translation(self, mock_api, db_session):
        """Prompt change: prompt_hash differs → Cache miss → New translation"""
        mock_api.return_value = "Translation with new prompt"

        # Setup: Cache with old prompt
        old_prompt_entry = DocumentTranslation(
            document_id="prompt-test-doc",
            source_hash="content_hash",
            reading_level="grade8",
            prompt_hash="old_prompt_hash",
            translated_text="Translation with old prompt",
            model_used="openai/gpt-4"
        )
        db_session.add(old_prompt_entry)
        db_session.commit()

        # Execute: Request with new prompt template
        service = OpenRouterService()
        # Modify prompt template to change hash
        service.PROMPT_TEMPLATES["grade8"] = "New improved prompt template"

        result = await service.translate(
            source_text="Same content",
            document_id="prompt-test-doc",
            reading_level="grade8"
        )

        # Verify: Cache miss, new translation generated
        assert result["cached"] == False
        mock_api.assert_called_once()

    @pytest.mark.asyncio
    async def test_prompt_rollback_uses_old_cache(self, db_session):
        """Prompt rollback: Reverting to old prompt → Cache hit (old entry preserved)"""
        # Setup: Cache entries for both prompt versions
        old_prompt_entry = DocumentTranslation(
            document_id="rollback-test-doc",
            source_hash="content_hash",
            reading_level="grade8",
            prompt_hash="old_prompt_hash",
            translated_text="Translation with old prompt",
            model_used="openai/gpt-4"
        )
        new_prompt_entry = DocumentTranslation(
            document_id="rollback-test-doc",
            source_hash="content_hash",
            reading_level="grade8",
            prompt_hash="new_prompt_hash",
            translated_text="Translation with new prompt",
            model_used="openai/gpt-4"
        )
        db_session.add_all([old_prompt_entry, new_prompt_entry])
        db_session.commit()

        # Execute: Rollback to old prompt template
        service = OpenRouterService()
        # Simulate rollback by using old prompt template (hashes to old_prompt_hash)
        result = await service.translate(
            source_text="Same content",
            document_id="rollback-test-doc",
            reading_level="grade8"
        )

        # Verify: Cache hit with old prompt version (no API call)
        assert result["cached"] == True
        assert result["translated_text"] == "Translation with old prompt"


class TestLargeDocumentSupport:
    """
    FR-011: System MUST support translation of documents up to 77 pages
    FR-012: System MUST complete full document translations without truncation
    FR-013: System MUST complete 77-page translations within 60 seconds
    """

    @pytest.mark.asyncio
    @patch('src.services.openrouter_service.OpenRouterService._call_openrouter')
    async def test_max_tokens_increased_to_30000(self, mock_api, db_session):
        """FR-011: max_tokens must be 30,000 to support 77-page documents"""
        mock_api.return_value = "Full translation (30k tokens)"

        service = OpenRouterService()
        large_document = "x" * 180_000  # 77 pages ≈ 180k characters

        await service.translate(
            source_text=large_document,
            document_id="large-doc-test",
            reading_level="grade8"
        )

        # Verify: API called with max_tokens=30000
        call_args = mock_api.call_args
        assert call_args.kwargs.get('max_tokens') == 30000

    @pytest.mark.asyncio
    @patch('src.services.openrouter_service.OpenRouterService._call_openrouter')
    async def test_large_document_completes_without_truncation(self, mock_api, db_session):
        """FR-012: Full document must translate completely"""
        # Mock returns full translation
        full_translation = "Complete translation of all 77 pages: " + ("x" * 25_000)
        mock_api.return_value = full_translation

        service = OpenRouterService()
        large_document = "y" * 180_000

        result = await service.translate(
            source_text=large_document,
            document_id="truncation-test-doc",
            reading_level="grade8"
        )

        # Verify: Full translation returned (no truncation)
        assert len(result["translated_text"]) > 20_000
        assert result["translated_text"] == full_translation


class TestConcurrencyHandling:
    """
    FR-014: Prevent concurrent duplicate translations
    Edge Case: Concurrent translation requests
    """

    @pytest.mark.asyncio
    @patch('src.services.openrouter_service.OpenRouterService._call_openrouter')
    async def test_concurrent_requests_one_api_call(self, mock_api, db_session):
        """Concurrent requests for same document → Only one API call"""
        mock_api.return_value = "Single translation"

        service = OpenRouterService()

        # Simulate concurrent requests
        import asyncio
        results = await asyncio.gather(
            service.translate("Same content", "concurrent-doc", "grade8"),
            service.translate("Same content", "concurrent-doc", "grade8"),
            service.translate("Same content", "concurrent-doc", "grade8")
        )

        # Verify: Only one API call made
        assert mock_api.call_count == 1

        # Verify: All requests got a result
        assert len(results) == 3
        assert all(r["translated_text"] == "Single translation" for r in results)

    @pytest.mark.asyncio
    @patch('src.services.openrouter_service.OpenRouterService._call_openrouter')
    async def test_unique_constraint_prevents_duplicates(self, mock_api, db_session):
        """Database unique constraint prevents duplicate cache entries"""
        mock_api.return_value = "Translation"

        # First insert succeeds
        entry1 = DocumentTranslation(
            document_id="dup-test-doc",
            source_hash="dup_hash",
            reading_level="grade8",
            prompt_hash="dup_prompt",
            translated_text="Translation 1",
            model_used="openai/gpt-4"
        )
        db_session.add(entry1)
        db_session.commit()

        # Second insert with same keys fails
        entry2 = DocumentTranslation(
            document_id="dup-test-doc",
            source_hash="dup_hash",
            reading_level="grade8",
            prompt_hash="dup_prompt",
            translated_text="Translation 2",
            model_used="openai/gpt-4"
        )
        db_session.add(entry2)

        with pytest.raises(IntegrityError):
            db_session.commit()


class TestPermanentCaching:
    """
    FR-001: System MUST cache translations permanently
    FR-002: System MUST NOT expire translations based on time duration
    FR-003: System MUST persist cached translations across system restarts
    """

    @pytest.mark.asyncio
    async def test_no_expiration_timestamp(self, db_session):
        """FR-002: Cache entries must not have expires_at set"""
        with patch('src.services.openrouter_service.OpenRouterService._call_openrouter') as mock_api:
            mock_api.return_value = "Permanent translation"

            service = OpenRouterService()
            await service.translate(
                source_text="Test content",
                document_id="permanent-test-doc",
                reading_level="grade8"
            )

            # Verify: No expires_at set
            stored = db_session.query(DocumentTranslation).filter(
                DocumentTranslation.document_id == "permanent-test-doc"
            ).first()

            assert stored.expires_at is None

    @pytest.mark.asyncio
    async def test_cache_persists_beyond_24_hours(self, db_session):
        """FR-001: Cache must remain valid after 24 hours"""
        # Setup: Create entry 25 hours ago
        old_entry = DocumentTranslation(
            document_id="old-doc",
            source_hash="old_hash",
            reading_level="grade8",
            prompt_hash="old_prompt",
            translated_text="Still valid",
            model_used="openai/gpt-4",
            created_at=datetime.now() - timedelta(hours=25)
        )
        db_session.add(old_entry)
        db_session.commit()

        # Execute: Request same document
        service = OpenRouterService()
        result = await service.translate(
            source_text="test",
            document_id="old-doc",
            reading_level="grade8"
        )

        # Verify: Cache still valid (no expiration)
        assert result["cached"] == True
        assert result["translated_text"] == "Still valid"


class TestCostOptimization:
    """
    FR-017: System MUST reduce annual translation costs from $18k-36k to $500-2k
    FR-018: System MUST minimize redundant API calls
    """

    @pytest.mark.asyncio
    @patch('src.services.openrouter_service.OpenRouterService._call_openrouter')
    async def test_identical_requests_cached(self, mock_api, db_session):
        """FR-018: Identical requests use cache (no redundant API calls)"""
        mock_api.return_value = "Translation"

        service = OpenRouterService()

        # First request → API call
        await service.translate("Content", "cost-test-doc", "grade8")
        assert mock_api.call_count == 1

        # 100 more identical requests → No additional API calls
        for _ in range(100):
            result = await service.translate("Content", "cost-test-doc", "grade8")
            assert result["cached"] == True

        # Verify: Still only 1 API call total
        assert mock_api.call_count == 1


# Pytest configuration
# Note: db_session fixture is now provided by conftest.py (uses SQLite for testing)
