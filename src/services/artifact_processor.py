"""
Artifact Processing Service for Experimental Template Generation.

Handles file upload validation, text extraction, and temporary storage
for artifacts used in prompt engineering experiments.

Feature: 021-create-a-dedicated (Prompt Engineering Workspace)
Tasks: T008-T010
"""

import os
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import uuid
import json
from bs4 import BeautifulSoup
from fastapi import UploadFile

logger = logging.getLogger(__name__)

# Configuration
ALLOWED_EXTENSIONS = {".txt", ".md", ".json", ".html"}
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
TEMP_ARTIFACT_DIR = Path("/tmp/gov-ai-artifacts")
ARTIFACT_EXPIRY_HOURS = 1


@dataclass
class Artifact:
    """Temporary artifact metadata."""
    file_id: str
    original_filename: str
    temp_path: Path
    size_bytes: int
    upload_timestamp: datetime
    content_preview: str  # First 200 chars


class ArtifactProcessor:
    """
    Processes uploaded artifacts for experimental template generation.

    Responsibilities:
    - Validate file size and type
    - Extract text content from various formats
    - Save to temporary storage
    - Clean up expired artifacts
    """

    def __init__(self):
        """Initialize artifact processor and ensure temp directory exists."""
        TEMP_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"ArtifactProcessor initialized. Temp dir: {TEMP_ARTIFACT_DIR}")

    def validate_file(self, file: UploadFile) -> bool:
        """
        Validate uploaded file meets requirements.

        Args:
            file: FastAPI UploadFile instance

        Returns:
            True if valid

        Raises:
            ValueError: If validation fails with user-friendly message
        """
        # Check file extension
        filename = file.filename or "unknown"
        file_ext = Path(filename).suffix.lower()

        if file_ext not in ALLOWED_EXTENSIONS:
            allowed_str = ", ".join(ALLOWED_EXTENSIONS)
            raise ValueError(
                f"File type '{file_ext}' not supported. "
                f"Allowed types: {allowed_str}"
            )

        # Check file size (read into memory to get accurate size)
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()
        file.file.seek(0)  # Reset to beginning

        if file_size > MAX_FILE_SIZE_BYTES:
            size_mb = file_size / (1024 * 1024)
            raise ValueError(
                f"File exceeds {MAX_FILE_SIZE_MB}MB limit. "
                f"Size: {size_mb:.2f}MB"
            )

        logger.debug(f"File validated: {filename} ({file_size} bytes)")
        return True

    def extract_text(self, file: UploadFile) -> str:
        """
        Extract text content from uploaded file.

        Args:
            file: FastAPI UploadFile instance

        Returns:
            Extracted text content

        Raises:
            ValueError: If text extraction fails
        """
        filename = file.filename or "unknown"
        file_ext = Path(filename).suffix.lower()

        try:
            # Read file content
            content_bytes = file.file.read()
            file.file.seek(0)  # Reset for potential re-reading

            # Decode with UTF-8, fallback to error replacement
            try:
                content_str = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                logger.warning(f"UTF-8 decode failed for {filename}, using error replacement")
                content_str = content_bytes.decode('utf-8', errors='replace')

            # Extract text based on file type
            if file_ext in {".txt", ".md"}:
                # Direct text files - return as-is
                extracted_text = content_str

            elif file_ext == ".json":
                # JSON files - pretty-print for readability
                try:
                    parsed_json = json.loads(content_str)
                    extracted_text = json.dumps(parsed_json, indent=2, ensure_ascii=False)
                except json.JSONDecodeError:
                    # If invalid JSON, return raw content
                    logger.warning(f"Invalid JSON in {filename}, using raw content")
                    extracted_text = content_str

            elif file_ext == ".html":
                # HTML files - strip tags to get text
                soup = BeautifulSoup(content_str, 'html.parser')
                extracted_text = soup.get_text(separator='\n', strip=True)

            else:
                # Should never reach here due to validation, but handle gracefully
                extracted_text = content_str

            # Validate extracted text is non-empty
            if not extracted_text.strip():
                raise ValueError(f"File '{filename}' contains no extractable text")

            logger.debug(f"Extracted {len(extracted_text)} chars from {filename}")
            return extracted_text

        except Exception as e:
            if isinstance(e, ValueError):
                raise  # Re-raise ValueError as-is
            raise ValueError(f"Failed to extract text from '{filename}': {str(e)}")

    def save_temp_artifact(self, file: UploadFile) -> Artifact:
        """
        Save uploaded file to temporary storage.

        Args:
            file: FastAPI UploadFile instance

        Returns:
            Artifact metadata

        Raises:
            ValueError: If save fails
        """
        # Validate first
        self.validate_file(file)

        # Generate unique file ID and path
        file_id = str(uuid.uuid4())
        original_filename = file.filename or "unknown"
        file_ext = Path(original_filename).suffix.lower()
        temp_filename = f"{file_id}_{original_filename}"
        temp_path = TEMP_ARTIFACT_DIR / temp_filename

        try:
            # Extract text content
            text_content = self.extract_text(file)

            # Save extracted text to temp file
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(text_content)

            # Get file size
            file_size = temp_path.stat().st_size

            # Create artifact metadata
            artifact = Artifact(
                file_id=file_id,
                original_filename=original_filename,
                temp_path=temp_path,
                size_bytes=file_size,
                upload_timestamp=datetime.utcnow(),
                content_preview=text_content[:200]  # First 200 chars
            )

            logger.info(
                f"Artifact saved: {artifact.file_id} "
                f"(original: {original_filename}, size: {file_size} bytes)"
            )

            return artifact

        except Exception as e:
            # Clean up temp file if save failed
            if temp_path.exists():
                temp_path.unlink()

            if isinstance(e, ValueError):
                raise  # Re-raise ValueError as-is
            raise ValueError(f"Failed to save artifact '{original_filename}': {str(e)}")

    def cleanup_expired_artifacts(self) -> int:
        """
        Delete temporary artifact files older than expiry threshold.

        Returns:
            Number of files deleted
        """
        if not TEMP_ARTIFACT_DIR.exists():
            return 0

        expiry_cutoff = datetime.utcnow() - timedelta(hours=ARTIFACT_EXPIRY_HOURS)
        deleted_count = 0

        try:
            for file_path in TEMP_ARTIFACT_DIR.iterdir():
                if not file_path.is_file():
                    continue

                # Get file modification time
                file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

                # Delete if older than expiry
                if file_mtime < expiry_cutoff:
                    file_path.unlink()
                    deleted_count += 1
                    logger.debug(f"Deleted expired artifact: {file_path.name}")

            if deleted_count > 0:
                logger.info(f"Cleanup: deleted {deleted_count} expired artifacts")

            return deleted_count

        except Exception as e:
            logger.error(f"Artifact cleanup failed: {str(e)}")
            return deleted_count

    def get_artifact_content(self, artifact: Artifact) -> str:
        """
        Read content from saved artifact.

        Args:
            artifact: Artifact metadata

        Returns:
            File content as string

        Raises:
            FileNotFoundError: If artifact file doesn't exist
        """
        if not artifact.temp_path.exists():
            raise FileNotFoundError(
                f"Artifact file not found: {artifact.original_filename}"
            )

        with open(artifact.temp_path, 'r', encoding='utf-8') as f:
            return f.read()

    def delete_artifact(self, artifact: Artifact) -> None:
        """
        Delete a specific artifact file.

        Args:
            artifact: Artifact metadata
        """
        if artifact.temp_path.exists():
            artifact.temp_path.unlink()
            logger.debug(f"Deleted artifact: {artifact.file_id}")


# Singleton instance
_processor_instance: Optional[ArtifactProcessor] = None


def get_artifact_processor() -> ArtifactProcessor:
    """Get or create singleton ArtifactProcessor instance."""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = ArtifactProcessor()
    return _processor_instance
