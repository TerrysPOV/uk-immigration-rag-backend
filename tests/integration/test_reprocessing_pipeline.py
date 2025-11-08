"""
Integration tests for reprocessing pipeline (Feature 019).

These tests verify end-to-end flow from failed document retrieval through
chrome stripping, chunking, embedding, and Qdrant indexing.

According to TDD, these tests MUST FAIL initially because components
have not been implemented yet. They will pass after T009-T015 implementation.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# These imports will fail initially (TDD approach)
from src.services.chrome_stripper import ChromeStripper
from src.services.file_processor import FileProcessor
from src.services.batch_processor import BatchProcessor
from src.models.processing_job import ProcessingJob
from src.models.document import Document


@pytest.mark.integration
@pytest.mark.slow
class TestReprocessingPipelineIntegration:
    """Integration tests for complete reprocessing pipeline."""

    def test_reprocess_single_document_end_to_end(self, db_session):
        """
        Verify complete document reprocessing flow from database to Qdrant.

        This test verifies:
        1. Document fetched from PostgreSQL (failed state)
        2. ChromeStripper removes GOV.UK chrome
        3. FileProcessor chunks cleaned content
        4. Embeddings generated for chunks
        5. Chunks indexed to Qdrant
        6. Document marked as processed with chrome stats

        Contract reference: data-model.md lines 182-199
        """
        # Arrange - Create failed document in database
        failed_doc = Document(
            document_id="test-failed-001",
            url="https://www.gov.uk/test-guidance",
            title="Test Guidance",
            content="""
            <html>
              <div class="gem-c-cookie-banner">Cookies on GOV.UK</div>
              <main class="govuk-main-wrapper">
                <h1>Test Guidance Document</h1>
                <p>This is legitimate government guidance content that should be processed.</p>
              </main>
              <footer class="govuk-footer">Footer content</footer>
            </html>
            """,
            department="Test Department",
            document_type="guidance",
            processing_success=False,
            created_at=datetime.utcnow()
        )
        db_session.add(failed_doc)
        db_session.commit()

        # Act - Trigger reprocessing
        batch_processor = BatchProcessor()
        result = batch_processor.reprocess_document(failed_doc.document_id)

        # Assert - Document updated
        reprocessed_doc = db_session.query(Document).filter_by(
            document_id=failed_doc.document_id
        ).first()

        assert reprocessed_doc.chrome_removed is True, \
            "Document should be marked as chrome_removed"
        assert reprocessed_doc.chrome_removal_stats is not None, \
            "Document should have chrome_removal_stats"
        assert reprocessed_doc.reprocessed_at is not None, \
            "Document should have reprocessed_at timestamp"
        assert reprocessed_doc.processing_success is True, \
            "Document should be marked as successfully processed"

        # Assert - Chrome stats populated
        stats = reprocessed_doc.chrome_removal_stats
        assert "original_chars" in stats
        assert "chrome_chars" in stats
        assert "guidance_chars" in stats
        assert "chrome_percentage" in stats
        assert "patterns_matched" in stats

        # Assert - Qdrant indexing (mocked for integration test)
        # In real deployment, this would verify Qdrant has the vectors
        assert result["chunks_created"] > 0, \
            "Reprocessing should create chunks"
        assert result["vectors_indexed"] > 0, \
            "Reprocessing should index vectors to Qdrant"

    def test_chrome_stripper_integrates_with_file_processor(self):
        """
        Verify ChromeStripper is correctly integrated into FileProcessor.

        This test verifies:
        1. FileProcessor calls ChromeStripper.strip_chrome() before chunking
        2. Cleaned HTML is passed to chunking logic
        3. Chrome stats are returned alongside processed content

        Contract reference: data-model.md lines 182-193
        """
        # Arrange
        file_processor = FileProcessor()
        html_with_chrome = """
        <html>
          <div class="gem-c-cookie-banner">Cookies on GOV.UK</div>
          <main class="govuk-main-wrapper">
            <h1>NHS Prescription Charges</h1>
            <p>Guidance content about prescription charges.</p>
          </main>
        </html>
        """
        document_id = "test-integration-002"

        # Act
        with patch('src.services.file_processor.ChromeStripper') as MockStripper:
            # Mock ChromeStripper behavior
            mock_instance = MockStripper.return_value
            mock_instance.strip_chrome.return_value = (
                "<main><h1>NHS Prescription Charges</h1><p>Guidance content...</p></main>",
                {
                    "original_chars": 250,
                    "chrome_chars": 50,
                    "guidance_chars": 200,
                    "chrome_percentage": 20.0,
                    "patterns_matched": ["cookie-banner"]
                }
            )

            result = file_processor.process_document(html_with_chrome, document_id)

        # Assert - ChromeStripper was called
        mock_instance.strip_chrome.assert_called_once_with(html_with_chrome, document_id)

        # Assert - Cleaned HTML used for chunking
        assert "cookie-banner" not in result["cleaned_content"], \
            "Chrome should be removed before chunking"
        assert "NHS Prescription Charges" in result["cleaned_content"], \
            "Main content should be preserved"

        # Assert - Chrome stats returned
        assert "chrome_removal_stats" in result
        assert result["chrome_removal_stats"]["chrome_percentage"] == 20.0

    def test_batch_processor_queues_reprocessing_jobs(self, db_session):
        """
        Verify BatchProcessor creates ProcessingJob entries for reprocessing.

        This test verifies:
        1. Failed documents fetched from database
        2. ProcessingJob created for each document
        3. reprocessing_batch_id set correctly
        4. Jobs queued in correct status

        Contract reference: data-model.md lines 182-199
        """
        # Arrange - Create multiple failed documents
        failed_docs = [
            Document(
                document_id=f"test-failed-{i:03d}",
                url=f"https://www.gov.uk/test-{i}",
                title=f"Test Document {i}",
                content="<html>Test content</html>",
                processing_success=False
            )
            for i in range(5)
        ]
        for doc in failed_docs:
            db_session.add(doc)
        db_session.commit()

        # Act - Trigger batch reprocessing
        batch_processor = BatchProcessor()
        batch_id = batch_processor.start_reprocessing_batch()

        # Assert - ProcessingJob entries created
        jobs = db_session.query(ProcessingJob).filter_by(
            reprocessing_batch_id=batch_id
        ).all()

        assert len(jobs) == 5, \
            "Should create ProcessingJob for each failed document"

        for job in jobs:
            assert job.reprocessing_batch_id == batch_id, \
                "Job should have correct batch_id"
            assert job.chrome_stripper_version == "1.0.0", \
                "Job should track chrome stripper version"
            assert job.status in ["queued", "pending"], \
                "Job should be queued initially"

    def test_pipeline_updates_document_chrome_stats(self, db_session):
        """
        Verify pipeline updates Document.chrome_removal_stats correctly.

        This test verifies:
        1. Chrome stats stored in JSONB column
        2. Stats structure matches contract
        3. Stats are retrievable and queryable

        Contract reference: data-model.md lines 14-23
        """
        # Arrange
        doc = Document(
            document_id="test-stats-001",
            url="https://www.gov.uk/test-stats",
            title="Test Stats Document",
            content="<html>Content</html>",
            processing_success=False
        )
        db_session.add(doc)
        db_session.commit()

        # Act - Reprocess with chrome stripping
        file_processor = FileProcessor()
        chrome_stats = {
            "original_chars": 1000,
            "chrome_chars": 700,
            "guidance_chars": 300,
            "chrome_percentage": 70.0,
            "patterns_matched": ["cookie-banner", "footer", "navigation"]
        }

        doc.chrome_removed = True
        doc.chrome_removal_stats = chrome_stats
        doc.reprocessed_at = datetime.utcnow()
        db_session.commit()

        # Assert - Stats retrievable from database
        retrieved_doc = db_session.query(Document).filter_by(
            document_id="test-stats-001"
        ).first()

        assert retrieved_doc.chrome_removal_stats is not None
        assert retrieved_doc.chrome_removal_stats["chrome_percentage"] == 70.0
        assert "cookie-banner" in retrieved_doc.chrome_removal_stats["patterns_matched"]

        # Assert - Stats queryable (JSONB operators)
        # This verifies PostgreSQL JSONB column works correctly
        high_chrome_docs = db_session.query(Document).filter(
            Document.chrome_removal_stats["chrome_percentage"].astext.cast(float) > 50.0
        ).all()

        assert len(high_chrome_docs) >= 1, \
            "Should be able to query documents by chrome percentage"
