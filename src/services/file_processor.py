"""
File processor service with multi-format support and validation.

Feature 011: Document Ingestion & Batch Processing
T037: File processor with PDF/Word/HTML/MD/TXT support, 50MB validation, chunking

Feature 019: Process All Cross-Government Guidance Documents
T012: ChromeStripper integration for GOV.UK chrome removal
"""

import hashlib
import mimetypes
from pathlib import Path
from typing import List, Dict, Optional, BinaryIO
import asyncio

# PDF extraction
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

# Word document extraction
try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

# HTML extraction
from bs4 import BeautifulSoup
import markdown

# Chrome stripping (Feature 019)
from src.services.chrome_stripper import ChromeStripper

# File format validation
ALLOWED_MIME_TYPES = {
    "application/pdf": [".pdf"],
    "application/msword": [".doc"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    "text/html": [".html", ".htm"],
    "text/markdown": [".md", ".markdown"],
    "text/plain": [".txt"],
}

# Magic numbers for format validation (first few bytes)
MAGIC_NUMBERS = {
    "pdf": b"%PDF",
    "docx": b"PK\x03\x04",  # ZIP format (Office Open XML)
    "doc": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",  # OLE format
}

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB (FR-014)


class FileProcessorService:
    """
    Service for processing uploaded documents.

    Features:
    - Multi-format support: PDF, Word, HTML, Markdown, Plain Text
    - 50MB file size validation (FR-014)
    - Format validation via magic numbers and MIME types (FR-016)
    - Parallel upload handling (FR-018)
    - Content chunking per config (FR-032)
    - Content hash deduplication
    """

    def __init__(self, chunk_size_tokens: int = 512):
        self.chunk_size_tokens = chunk_size_tokens
        self.chrome_stripper = ChromeStripper()  # Feature 019: GOV.UK chrome removal
        self._chrome_removal_stats = None  # Stores stats from last HTML processing

    async def process_files(
        self, files: List[Dict], chunk_size_tokens: Optional[int] = None
    ) -> Dict:
        """
        Process multiple files in parallel.

        Args:
            files: List of file dicts with 'filename', 'content' (bytes), 'content_type'
            chunk_size_tokens: Override default chunk size

        Returns:
            Dict with:
            - processed_files: List of successfully processed file objects
            - failed_files: List of failed files with error messages
            - total_chunks: Total number of chunks created
        """
        chunk_size = chunk_size_tokens or self.chunk_size_tokens

        # Process files in parallel (FR-018)
        tasks = [self._process_single_file(file_data, chunk_size) for file_data in files]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_files = []
        failed_files = []
        total_chunks = 0

        for file_data, result in zip(files, results):
            if isinstance(result, Exception):
                failed_files.append(
                    {"filename": file_data.get("filename", "unknown"), "error": str(result)}
                )
            else:
                processed_files.append(result)
                total_chunks += len(result["chunks"])

        return {
            "processed_files": processed_files,
            "failed_files": failed_files,
            "total_chunks": total_chunks,
        }

    async def _process_single_file(self, file_data: Dict, chunk_size_tokens: int) -> Dict:
        """
        Process a single file: validate, extract text, chunk.

        Args:
            file_data: Dict with 'filename', 'content' (bytes), 'content_type'
            chunk_size_tokens: Token count per chunk

        Returns:
            Dict with file metadata and extracted chunks

        Raises:
            ValueError: If file validation fails
        """
        filename = file_data["filename"]
        content = file_data["content"]
        content_type = file_data.get("content_type")

        # Validate file size (FR-014)
        if len(content) > MAX_FILE_SIZE_BYTES:
            size_mb = len(content) / (1024 * 1024)
            raise ValueError(f"File exceeds 50MB limit: {filename} ({size_mb:.1f}MB)")

        # Validate file format (FR-016)
        self._validate_file_format(filename, content, content_type)

        # Extract text content
        text_content = await self._extract_text(filename, content)

        # Calculate content hash for deduplication
        content_hash = hashlib.sha256(text_content.encode()).hexdigest()

        # Chunk text content (FR-032)
        chunks = self._chunk_text(text_content, chunk_size_tokens)

        result = {
            "filename": filename,
            "content_type": content_type,
            "text_content": text_content,
            "content_hash": content_hash,
            "chunks": chunks,
            "chunk_count": len(chunks),
            "file_size_bytes": len(content),
        }

        # Include chrome removal stats if HTML was processed (Feature 019)
        if self._chrome_removal_stats:
            result["chrome_removal_stats"] = self._chrome_removal_stats
            result["chrome_removed"] = True
            self._chrome_removal_stats = None  # Reset for next file
        else:
            result["chrome_removed"] = False

        return result

    def _validate_file_format(
        self, filename: str, content: bytes, content_type: Optional[str]
    ) -> None:
        """
        Validate file format via extension, MIME type, and magic numbers.

        Raises:
            ValueError: If file format is invalid
        """
        # Check file extension
        file_ext = Path(filename).suffix.lower()

        # Validate extension is allowed
        allowed_extensions = set()
        for extensions in ALLOWED_MIME_TYPES.values():
            allowed_extensions.update(extensions)

        if file_ext not in allowed_extensions:
            raise ValueError(
                f"Invalid file format: {filename}. "
                f"Allowed formats: PDF, Word (.doc, .docx), HTML, Markdown, Plain Text"
            )

        # Check MIME type if provided
        if content_type:
            if content_type not in ALLOWED_MIME_TYPES:
                raise ValueError(f"Invalid MIME type: {content_type} for file {filename}")

        # Validate magic numbers for binary formats
        if file_ext == ".pdf":
            if not content.startswith(MAGIC_NUMBERS["pdf"]):
                raise ValueError(f"Corrupted PDF file: {filename}")

        elif file_ext == ".docx":
            if not content.startswith(MAGIC_NUMBERS["docx"]):
                raise ValueError(f"Corrupted DOCX file: {filename}")

        elif file_ext == ".doc":
            if not content.startswith(MAGIC_NUMBERS["doc"]):
                raise ValueError(f"Corrupted DOC file: {filename}")

    async def _extract_text(self, filename: str, content: bytes) -> str:
        """
        Extract text content based on file format.

        Args:
            filename: Original filename
            content: File content as bytes

        Returns:
            Extracted text content

        Raises:
            ValueError: If extraction fails
        """
        file_ext = Path(filename).suffix.lower()

        try:
            if file_ext == ".pdf":
                return await self._extract_pdf(content)

            elif file_ext == ".docx":
                return await self._extract_docx(content)

            elif file_ext == ".doc":
                # .doc files require more complex parsing (python-docx doesn't support them)
                raise ValueError(
                    f"Legacy .doc format not supported: {filename}. "
                    f"Please convert to .docx format"
                )

            elif file_ext in [".html", ".htm"]:
                return await self._extract_html(content)

            elif file_ext in [".md", ".markdown"]:
                return await self._extract_markdown(content)

            elif file_ext == ".txt":
                return content.decode("utf-8")

            else:
                raise ValueError(f"Unsupported file format: {file_ext}")

        except Exception as e:
            raise ValueError(f"Failed to extract text from {filename}: {e}")

    async def _extract_pdf(self, content: bytes) -> str:
        """Extract text from PDF using PyPDF2"""
        if not PyPDF2:
            raise ValueError("PyPDF2 not installed. Cannot process PDF files.")

        from io import BytesIO

        pdf_reader = PyPDF2.PdfReader(BytesIO(content))
        text_parts = []

        for page in pdf_reader.pages:
            text_parts.append(page.extract_text())

        return "\n\n".join(text_parts)

    async def _extract_docx(self, content: bytes) -> str:
        """Extract text from DOCX using python-docx"""
        if not DocxDocument:
            raise ValueError("python-docx not installed. Cannot process DOCX files.")

        from io import BytesIO

        doc = DocxDocument(BytesIO(content))
        text_parts = []

        for paragraph in doc.paragraphs:
            text_parts.append(paragraph.text)

        return "\n\n".join(text_parts)

    async def _extract_html(self, content: bytes) -> str:
        """
        Extract text from HTML using BeautifulSoup.

        Feature 019: Integrates ChromeStripper to remove GOV.UK chrome
        (cookie banners, navigation, footer) before text extraction.
        """
        html = content.decode("utf-8")

        # Feature 019: Strip GOV.UK chrome before processing (FR-004, FR-006)
        # This removes navigation, footers, cookie banners, etc.
        cleaned_html, chrome_stats = self.chrome_stripper.strip_chrome(
            html,
            document_id="html-extraction"  # Actual document_id set by caller
        )

        # Store chrome removal stats for inclusion in result (FR-008)
        self._chrome_removal_stats = chrome_stats

        # Parse cleaned HTML
        soup = BeautifulSoup(cleaned_html, "lxml")

        # Remove any remaining script and style elements (defense in depth)
        for script in soup(["script", "style"]):
            script.decompose()

        # Get text
        text = soup.get_text()

        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = "\n".join(chunk for chunk in chunks if chunk)

        return text

    async def _extract_markdown(self, content: bytes) -> str:
        """Extract text from Markdown (convert to HTML then extract)"""
        md_text = content.decode("utf-8")

        # Convert Markdown to HTML
        html = markdown.markdown(md_text)

        # Extract text from HTML
        return await self._extract_html(html.encode("utf-8"))

    def _chunk_text(self, text: str, chunk_size_tokens: int) -> List[str]:
        """
        Split text into chunks based on token count.

        Simple approximation: 1 token ≈ 4 characters
        For production, use tiktoken or similar tokenizer.

        Args:
            text: Full text content
            chunk_size_tokens: Target token count per chunk

        Returns:
            List of text chunks
        """
        # Approximate characters per chunk (1 token ≈ 4 chars)
        chars_per_chunk = chunk_size_tokens * 4

        # Split into chunks
        chunks = []
        current_chunk = []
        current_length = 0

        # Split by sentences (simple approach)
        sentences = text.split(". ")

        for sentence in sentences:
            sentence_length = len(sentence)

            if current_length + sentence_length > chars_per_chunk and current_chunk:
                # Finalize current chunk
                chunks.append(". ".join(current_chunk) + ".")
                current_chunk = []
                current_length = 0

            current_chunk.append(sentence)
            current_length += sentence_length

        # Add remaining chunk
        if current_chunk:
            chunks.append(". ".join(current_chunk) + ".")

        return chunks

    async def validate_file(
        self, filename: str, content: bytes, content_type: Optional[str] = None
    ) -> Dict:
        """
        Validate file without processing (for upload preview).

        Returns:
            Dict with validation result:
            - valid: bool
            - error: str (if invalid)
            - file_size_mb: float
            - format: str
        """
        try:
            # Check file size
            file_size_mb = len(content) / (1024 * 1024)

            if len(content) > MAX_FILE_SIZE_BYTES:
                return {
                    "valid": False,
                    "error": f"File exceeds 50MB limit ({file_size_mb:.1f}MB)",
                    "file_size_mb": file_size_mb,
                    "format": Path(filename).suffix.lower(),
                }

            # Validate format
            self._validate_file_format(filename, content, content_type)

            return {
                "valid": True,
                "error": None,
                "file_size_mb": file_size_mb,
                "format": Path(filename).suffix.lower(),
            }

        except ValueError as e:
            return {
                "valid": False,
                "error": str(e),
                "file_size_mb": len(content) / (1024 * 1024),
                "format": Path(filename).suffix.lower(),
            }
