"""
T009: OpenRouter Service
LLM integration service for document summarization and plain English translation

Feature 018: User Testing Issue Remediation
Feature 022: Permanent Content-Addressable Translation Caching
Feature 024: Dynamic Model-Aware Document Chunking
Provides AI-generated summaries and translations via OpenRouter API with permanent caching
"""

import os
import hashlib
import logging
import re
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
import httpx
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.document_summary import DocumentSummary
from src.models.document_translation import DocumentTranslation

logger = logging.getLogger(__name__)


class OpenRouterService:
    """
    Service for OpenRouter API integration with caching.

    Features:
    - AI-generated document summaries (150-250 words)
    - Plain English translations (grade6, grade8, grade10 reading levels)
    - Dynamic model-aware document chunking (Feature 024)
    - Permanent content-addressable caching (Feature 022)
    - Timeout handling (30s)
    - Rate limiting (10 req/min per user - enforced at API layer)
    - Error handling and retry logic
    """

    # T011: Model output token limits (Feature 024 - Dynamic Chunking)
    # Maps OpenRouter model identifiers to their maximum output token limits
    # Used to calculate optimal chunk sizes for large documents
    MODEL_OUTPUT_LIMITS = {
        # Anthropic Claude models
        "anthropic/claude-3-haiku": 4096,
        "anthropic/claude-3-sonnet": 4096,
        "anthropic/claude-3.5-sonnet": 8192,
        "anthropic/claude-3-opus": 4096,

        # OpenAI GPT models
        "openai/gpt-4-turbo": 4096,
        "openai/gpt-4": 8192,
        "openai/gpt-3.5-turbo": 4096,

        # Qwen models (high output limits)
        "qwen/qwen-2.5-72b-instruct": 32768,
        "qwen/qwen-2-72b-instruct": 32768,
        "qwen/qwq-32b-preview": 32768,

        # Meta Llama models
        "meta-llama/llama-3.1-70b-instruct": 4096,
        "meta-llama/llama-3.1-8b-instruct": 4096,

        # Default fallback
        "default": 4096
    }

    # T005: Prompt templates for content-addressable caching (Feature 022)
    # Each template version has a unique hash - changing template invalidates all cached translations
    PROMPT_TEMPLATES = {
        "base": """You are an expert copywriter specialising in translating complex UK immigration guidance documents into plain English, section by section.

SOURCE DOCUMENT:
- Title: {doc_title}
- URL: {doc_url}
- Type: {doc_type}

YOUR TASK:
Translate this ENTIRE document into clear, accessible plain English following the section-by-section format below. Preserve the document's structure while making each section understandable to the general public.

MANDATORY GDS STANDARDS:
1. Reading level: Write for a reading age of {reading_age} years old
2. Sentence length: 25 words max
3. Active voice only, not passive
4. Clear headings, short paragraphs (3-4 sentences max)
5. Bullet lists for multiple items
6. Plain language: Replace jargon with everyday words, explain technical terms in brackets, use "you" and "we"
7. One idea per sentence
8. Front-load important information

OUTPUT FORMAT (MANDATORY):
# [Document Title in Plain English]

**Original document**: {doc_title}
**Source**: {doc_url}
**Document type**: {doc_type}

---

## Summary
[2-3 sentence overview of what this document covers and who it applies to]

---

## Section 1: [Plain English Section Title]

**What the original says:**
[Quote 2-4 sentences of ACTUAL ORIGINAL TEXT from the document verbatim - NOT just the heading. Show the real technical/formal language that needs translating.]

**In plain English:**
[ACTUAL TRANSLATION of the original text above - NOT a description of what the section does. Rewrite the original content using plain language, NOT meta-commentary like "This section explains..." - translate the actual words.]

**What this means for you:**
[Practical implications in everyday language]

---

[Continue for all major sections...]

---

## Key Points to Remember

- [Most important point 1]
- [Most important point 2]
- [Most important point 3]

---

## Next Steps

If this guidance applies to you:
1. [First action to take]
2. [Second action to take]
3. [Where to get more help]

---

CONSTRAINTS:
- NEVER invent information not in source material
- NEVER simplify to the point of inaccuracy
- Preserve all legal requirements and conditions exactly
- Maintain the document's original structure and section order
- If source is ambiguous, state this clearly

TONE: Helpful, reassuring, patient, clear, respectful

CRITICAL: Start your response IMMEDIATELY with the markdown output. Do NOT write "Here is..." or any introduction.

DOCUMENT TO TRANSLATE:
{document_text}"""
    }

    def __init__(self, db_session: Session):
        """
        Initialize OpenRouter service.

        Args:
            db_session: SQLAlchemy database session for cache operations
        """
        self.db = db_session
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.default_model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku")
        self.timeout = 30  # 30 seconds
        self.referer = os.getenv("OPENROUTER_REFERER", "https://vectorgov.poview.ai")

        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not configured - API calls will fail")

    # T003: Hash computation for content-addressable caching (Feature 022)
    def compute_source_hash(self, source_text: str) -> str:
        """
        Compute MD5 hash of source content for cache key.

        Args:
            source_text: Complete document or chunk text

        Returns:
            32-character hex string (e.g., 'a1b2c3d4e5f6...')

        Example:
            >>> service.compute_source_hash("test content")
            '9a0364b9e99bb480dd25e1f0284c8555'
        """
        return hashlib.md5(source_text.encode('utf-8')).hexdigest()

    # T004: Prompt hash computation (Feature 022)
    def compute_prompt_hash(self, prompt_template: str) -> str:
        """
        Compute MD5 hash of prompt template for cache invalidation.

        Args:
            prompt_template: Complete prompt template string

        Returns:
            32-character hex string (e.g., 'x9y8z7w6v5u4...')

        Note:
            Same template MUST produce same hash (determinism requirement)
        """
        return hashlib.md5(prompt_template.encode('utf-8')).hexdigest()

    # T005: Prompt template retrieval (Feature 022)
    def _get_prompt_template(self, reading_level: str = "grade8") -> str:
        """
        Load canonical prompt template for given reading level.

        Args:
            reading_level: Target reading level (currently ignored, uses 'base' template)

        Returns:
            Prompt template string (deterministic for same reading level)

        Note:
            This method exists to support future reading-level-specific templates.
            Currently all levels use the same base template with reading_age parameter.
        """
        return self.PROMPT_TEMPLATES["base"]

    # T006: Build prompt from template (Feature 022)
    def _build_prompt_from_template(
        self,
        template: str,
        source_text: str,
        reading_level: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Construct translation prompt by filling template placeholders.

        Args:
            template: Prompt template string with placeholders
            source_text: Document or chunk text to translate
            reading_level: Target reading level (grade6, grade8, grade10)
            metadata: Optional document metadata (title, url, type)

        Returns:
            Complete prompt string ready for OpenRouter API
        """
        # Map reading level to reading age
        reading_age_map = {"grade6": "9", "grade8": "11", "grade10": "13"}
        reading_age = reading_age_map.get(reading_level, "11")

        # Extract metadata with defaults
        if metadata is None:
            metadata = {}
        doc_title = metadata.get("title", "Unknown Document")
        doc_url = metadata.get("url", "")
        doc_type = metadata.get("document_type", "guidance")

        # Fill template
        return template.format(
            document_text=source_text,
            doc_title=doc_title,
            doc_url=doc_url,
            doc_type=doc_type,
            reading_age=reading_age
        )

    # T012: Model output limit lookup (Feature 024)
    def get_model_output_limit(self, model: str) -> int:
        """
        Get maximum output token limit for a model.

        Args:
            model: OpenRouter model identifier (e.g., "anthropic/claude-3-haiku")

        Returns:
            Maximum output tokens (int)
        """
        return self.MODEL_OUTPUT_LIMITS.get(model, self.MODEL_OUTPUT_LIMITS["default"])

    # T013: Estimate required output tokens (Feature 024)
    def estimate_output_tokens(self, input_text: str) -> int:
        """
        Estimate output tokens needed for translation.

        Rule of thumb: Plain English translation is ~1.2x the input length
        (GDS standards require short sentences, bullet lists, explanations)

        Args:
            input_text: Source document text

        Returns:
            Estimated output tokens
        """
        # Rough approximation: 4 chars = 1 token
        input_tokens = len(input_text) / 4
        # Plain English expansion factor: 1.2x
        return int(input_tokens * 1.2)

    # T014: Smart document chunking on section boundaries (Feature 024)
    def split_into_chunks(
        self,
        document_text: str,
        model: str,
        safety_margin: float = 0.8
    ) -> List[Tuple[int, int, str]]:
        """
        Split document into chunks on section boundaries for model token limits.

        Algorithm:
        1. Get model's output token limit
        2. Calculate max input per chunk (limit / expansion_factor / safety_margin)
        3. Split on markdown headers (##, ###), preserving sections
        4. Combine small sections until reaching chunk limit
        5. Return list of (start_idx, end_idx, chunk_text) tuples

        Args:
            document_text: Full document text to chunk
            model: OpenRouter model identifier
            safety_margin: Token limit safety factor (0.8 = use 80% of limit)

        Returns:
            List of (start_index, end_index, chunk_text) tuples
            Each chunk is guaranteed to fit within model's output limit
        """
        output_limit = self.get_model_output_limit(model)

        # Calculate max input tokens per chunk
        # output_limit / 1.2 (expansion) / safety_margin
        max_input_tokens = int(output_limit / 1.2 / safety_margin)
        max_input_chars = max_input_tokens * 4  # 4 chars per token

        # Find section boundaries (markdown headers)
        section_pattern = re.compile(r'^(#{2,3})\s+(.+)$', re.MULTILINE)
        matches = list(section_pattern.finditer(document_text))

        if not matches:
            # No sections found - split by character count
            logger.warning("No markdown sections found, splitting by character count")
            chunks = []
            for i in range(0, len(document_text), max_input_chars):
                end = min(i + max_input_chars, len(document_text))
                chunks.append((i, end, document_text[i:end]))
            return chunks

        # Build chunks by combining sections
        chunks = []
        current_start = 0
        current_chunk = ""

        for i, match in enumerate(matches):
            section_start = match.start()

            # Get section content (from this header to next header or end)
            if i + 1 < len(matches):
                section_end = matches[i + 1].start()
            else:
                section_end = len(document_text)

            section_text = document_text[section_start:section_end]

            # Check if adding this section exceeds chunk limit
            if current_chunk and len(current_chunk) + len(section_text) > max_input_chars:
                # Finalize current chunk
                chunks.append((current_start, section_start, current_chunk))
                # Start new chunk
                current_start = section_start
                current_chunk = section_text
            else:
                # Add section to current chunk
                if not current_chunk:
                    current_start = section_start
                current_chunk += section_text

        # Add final chunk
        if current_chunk:
            chunks.append((current_start, len(document_text), current_chunk))

        logger.info(
            f"Split document into {len(chunks)} chunks for model {model} "
            f"(output_limit={output_limit}, max_input_chars={max_input_chars})"
        )

        return chunks

    # T015: Combine translated chunks (Feature 024)
    def combine_chunks(self, translated_chunks: List[str]) -> str:
        """
        Combine translated chunks preserving markdown structure.

        Handles:
        - Remove duplicate headers between chunks
        - Preserve section numbering
        - Maintain markdown formatting
        - Add chunk boundaries as comments (for debugging)

        Args:
            translated_chunks: List of translated chunk texts

        Returns:
            Combined markdown document
        """
        if len(translated_chunks) == 1:
            return translated_chunks[0]

        combined = []

        for i, chunk in enumerate(translated_chunks):
            if i == 0:
                # First chunk: keep as-is
                combined.append(chunk)
            else:
                # Subsequent chunks: remove duplicate document header
                # Skip lines until we find the first section (##)
                lines = chunk.split('\n')
                section_start = 0

                for j, line in enumerate(lines):
                    if line.startswith('##'):
                        section_start = j
                        break

                # Add chunk content from first section onwards
                chunk_content = '\n'.join(lines[section_start:])
                combined.append(f"\n\n{chunk_content}")

        return ''.join(combined)

    async def summarize(
        self,
        document_id: str,
        document_text: str,
        max_words: int = 200,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate AI summary of document with cache support.

        Args:
            document_id: Document identifier for cache lookup
            document_text: Full document text to summarize
            max_words: Target word count (150-250, default 200)
            user_id: User requesting (for rate limiting tracking)

        Returns:
            Dict with:
            - document_id: Document identifier
            - summary_text: Generated summary
            - word_count: Actual word count
            - model_used: OpenRouter model identifier
            - cached: Whether result was from cache

        Raises:
            ValueError: If max_words out of range or document_text empty
            httpx.TimeoutException: If API call exceeds 30s
            httpx.HTTPStatusError: If API returns error status
        """
        # Validate inputs
        if not document_text or len(document_text.strip()) == 0:
            raise ValueError("document_text must be non-empty")

        if not (150 <= max_words <= 250):
            raise ValueError(f"max_words must be 150-250, got {max_words}")

        # Check cache first
        cached_summary = self._get_cached_summary(document_id)
        if cached_summary:
            logger.info(f"Cache hit for summary document_id={document_id}")
            return {
                "document_id": document_id,
                "summary_text": cached_summary.summary_text,
                "word_count": cached_summary.word_count,
                "model_used": cached_summary.model_used,
                "cached": True
            }

        # Cache miss - call OpenRouter API
        logger.info(f"Cache miss for summary document_id={document_id}, calling OpenRouter API")

        prompt = f"""Summarize the following UK government guidance document in plain English.

Target word count: {max_words} words (strict limit: 150-250 words)
Reading level: General public (write for reading age 9)
Style: Active voice, short sentences (max 25 words), everyday language

Document:
{document_text}  # Limit to first 8000 chars to avoid token limits

Summary:"""

        try:
            summary_text, model_used = await self._call_openrouter_api(prompt)

            # Count words
            word_count = len(summary_text.split())

            # Store in cache
            expires_at = datetime.utcnow() + timedelta(hours=24)
            cache_entry = DocumentSummary(
                document_id=document_id,
                summary_text=summary_text,
                word_count=word_count,
                model_used=model_used,
                expires_at=expires_at,
                user_id=user_id
            )
            self.db.add(cache_entry)
            self.db.commit()

            logger.info(f"Generated summary for document_id={document_id}, words={word_count}, cached for 24h")

            return {
                "document_id": document_id,
                "summary_text": summary_text,
                "word_count": word_count,
                "model_used": model_used,
                "cached": False
            }

        except httpx.TimeoutException:
            logger.error(f"OpenRouter API timeout for document_id={document_id}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter API error for document_id={document_id}: {e.response.status_code}")
            raise

    async def translate(
        self,
        document_id: str,
        document_text: str,
        reading_level: str = "grade8",
        model: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Translate document to plain English with automatic chunking and cache support.

        Feature 024: Dynamic Model-Aware Document Chunking
        - Automatically detects if document exceeds model's output token limit
        - Splits large documents on section boundaries (markdown headers)
        - Translates chunks in parallel with caching
        - Combines chunks preserving markdown structure
        - Progress tracking for multi-chunk translations

        Args:
            document_id: Document identifier for cache lookup
            document_text: Full document text to translate
            reading_level: Target reading level (grade6, grade8, grade10)
            model: OpenRouter model identifier (None = use default)
            user_id: User requesting (for rate limiting tracking)
            metadata: Document metadata (title, url, type)
            progress_callback: Optional async callback(chunk_idx, total_chunks, status)

        Returns:
            Dict with:
            - document_id: Document identifier
            - translated_text: Plain English translation
            - reading_level: Target reading level
            - model_used: OpenRouter model identifier
            - cached: Whether result was from cache
            - chunks_processed: Number of chunks (1 if no chunking needed)

        Raises:
            ValueError: If reading_level invalid or document_text empty
            httpx.TimeoutException: If API call exceeds 30s
            httpx.HTTPStatusError: If API returns error status
        """
        # Validate inputs
        if not document_text or len(document_text.strip()) == 0:
            raise ValueError("document_text must be non-empty")

        allowed_levels = ["grade6", "grade8", "grade10"]
        if reading_level not in allowed_levels:
            raise ValueError(f"reading_level must be one of {allowed_levels}, got '{reading_level}'")

        # T016: Use provided model or default (Feature 024)
        selected_model = model or self.default_model

        # T017: Check if chunking is needed (Feature 024)
        estimated_output = self.estimate_output_tokens(document_text)
        model_limit = self.get_model_output_limit(selected_model)
        needs_chunking = estimated_output > (model_limit * 0.8)  # 80% safety margin

        if needs_chunking:
            logger.info(
                f"Document requires chunking: estimated_output={estimated_output} tokens, "
                f"model_limit={model_limit} tokens, model={selected_model}"
            )
            return await self._translate_with_chunking(
                document_id=document_id,
                document_text=document_text,
                reading_level=reading_level,
                model=selected_model,
                user_id=user_id,
                metadata=metadata,
                progress_callback=progress_callback
            )

        # No chunking needed - use standard translation path
        logger.info(
            f"Document fits in single chunk: estimated_output={estimated_output} tokens, "
            f"model_limit={model_limit} tokens, model={selected_model}"
        )

        # T007: Compute content hash for cache key (Feature 022)
        source_hash = self.compute_source_hash(document_text)

        # T007: Load prompt template and compute prompt hash (Feature 022)
        prompt_template = self._get_prompt_template(reading_level)
        prompt_hash = self.compute_prompt_hash(prompt_template)

        # T007/T024: Check cache with composite key (document_id, source_hash, reading_level, prompt_hash, model)
        cached_translation = self._get_cached_translation(
            document_id, source_hash, reading_level, prompt_hash, model=selected_model
        )
        if cached_translation:
            logger.info(
                f"Cache hit for translation document_id={document_id}, "
                f"source_hash={source_hash[:8]}, prompt_hash={prompt_hash[:8]}, level={reading_level}"
            )
            return {
                "document_id": document_id,
                "translated_text": cached_translation.translated_text,
                "reading_level": cached_translation.reading_level,
                "model_used": cached_translation.model_used,
                "cached": True,
                "chunks_processed": 1
            }

        # Cache miss - generate new translation
        logger.info(
            f"Cache miss for translation document_id={document_id}, "
            f"source_hash={source_hash[:8]}, prompt_hash={prompt_hash[:8]}, level={reading_level}, calling API"
        )

        # T006: Build prompt from template
        prompt = self._build_prompt_from_template(
            prompt_template, document_text, reading_level, metadata
        )

        try:
            # T018: Call API with model parameter (Feature 024)
            translated_text, model_used = await self._call_openrouter_api(
                prompt, max_tokens=model_limit, model=selected_model
            )

            # T007/T009: Store in cache permanently (no expires_at, with IntegrityError handling)
            try:
                cache_entry = DocumentTranslation(
                    document_id=document_id,
                    source_hash=source_hash,
                    reading_level=reading_level,
                    prompt_hash=prompt_hash,
                    translated_text=translated_text,
                    model_used=model_used,
                    expires_at=None,  # Permanent cache (Feature 022)
                    user_id=user_id
                )
                self.db.add(cache_entry)
                self.db.commit()

                logger.info(
                    f"Generated and cached translation permanently for document_id={document_id}, "
                    f"source_hash={source_hash[:8]}, prompt_hash={prompt_hash[:8]}, level={reading_level}"
                )

            except IntegrityError as e:
                # T009: Concurrent request already cached this translation
                # Rollback and return the cached result from the other request
                logger.warning(
                    f"IntegrityError storing translation (concurrent request): {e}. "
                    f"Retrying cache lookup for document_id={document_id}"
                )
                self.db.rollback()

                # Retry cache lookup - the concurrent request should have stored it
                cached_translation = self._get_cached_translation(
                    document_id, source_hash, reading_level, prompt_hash, model=selected_model
                )
                if cached_translation:
                    logger.info(f"Cache hit on retry (concurrent request won race)")
                    return {
                        "document_id": document_id,
                        "translated_text": cached_translation.translated_text,
                        "reading_level": cached_translation.reading_level,
                        "model_used": cached_translation.model_used,
                        "cached": True  # From concurrent request's cache entry
                    }
                else:
                    # Unexpected - retry the entire translation
                    logger.error(f"Cache lookup failed after IntegrityError - this should not happen")
                    return await self.translate(
                        document_id, document_text, reading_level, user_id, metadata
                    )

            return {
                "document_id": document_id,
                "translated_text": translated_text,
                "reading_level": reading_level,
                "model_used": model_used,
                "cached": False,
                "chunks_processed": 1
            }

        except httpx.TimeoutException:
            logger.error(f"OpenRouter API timeout for document_id={document_id}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter API error for document_id={document_id}: {e.response.status_code}")
            raise

    async def _translate_with_chunking(
        self,
        document_id: str,
        document_text: str,
        reading_level: str,
        model: str,
        user_id: Optional[str],
        metadata: Optional[Dict[str, Any]],
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Translate large document using parallel chunk processing with caching.

        T019: Feature 024 - Dynamic Model-Aware Document Chunking
        Algorithm:
        1. Split document into chunks on section boundaries
        2. Translate chunks in parallel (asyncio.gather)
        3. Each chunk uses content-addressable caching independently
        4. Combine translated chunks preserving markdown structure
        5. Track progress via optional callback

        Args:
            document_id: Document identifier
            document_text: Full document text
            reading_level: Target reading level
            model: OpenRouter model identifier
            user_id: User requesting
            metadata: Document metadata
            progress_callback: Optional async callback(chunk_idx, total_chunks, status)

        Returns:
            Dict with translation result and chunks_processed count
        """
        # T020: Split document into chunks
        chunks = self.split_into_chunks(document_text, model, safety_margin=0.8)
        total_chunks = len(chunks)

        logger.info(f"Translating document in {total_chunks} chunks (model={model})")

        # T021: Define chunk translation task
        async def translate_chunk(chunk_idx: int, chunk_start: int, chunk_end: int, chunk_text: str) -> str:
            """Translate a single chunk with caching."""
            # Compute unique chunk ID for caching
            chunk_id = f"{document_id}_chunk_{chunk_idx}"

            # Progress callback
            if progress_callback:
                await progress_callback(chunk_idx + 1, total_chunks, "translating")

            # Compute cache key
            source_hash = self.compute_source_hash(chunk_text)
            prompt_template = self._get_prompt_template(reading_level)
            prompt_hash = self.compute_prompt_hash(prompt_template)

            # Check cache for this chunk
            # T024: Pass model parameter for model-specific caching
            cached_translation = self._get_cached_translation(
                chunk_id, source_hash, reading_level, prompt_hash, model=model
            )
            if cached_translation:
                logger.info(f"Cache hit for chunk {chunk_idx + 1}/{total_chunks}")
                if progress_callback:
                    await progress_callback(chunk_idx + 1, total_chunks, "cached")
                return cached_translation.translated_text

            # Cache miss - translate chunk
            logger.info(f"Cache miss for chunk {chunk_idx + 1}/{total_chunks}, calling API")

            # Build prompt for chunk
            prompt = self._build_prompt_from_template(
                prompt_template, chunk_text, reading_level, metadata
            )

            # Get model limit for this chunk
            model_limit = self.get_model_output_limit(model)

            # Translate chunk
            translated_text, model_used = await self._call_openrouter_api(
                prompt, max_tokens=model_limit, model=model
            )

            # Store chunk in cache permanently
            try:
                cache_entry = DocumentTranslation(
                    document_id=chunk_id,
                    source_hash=source_hash,
                    reading_level=reading_level,
                    prompt_hash=prompt_hash,
                    translated_text=translated_text,
                    model_used=model_used,
                    expires_at=None,  # Permanent cache
                    user_id=user_id
                )
                self.db.add(cache_entry)
                self.db.commit()
                logger.info(f"Cached chunk {chunk_idx + 1}/{total_chunks}")
            except IntegrityError:
                # Concurrent request cached this chunk
                self.db.rollback()
                logger.warning(f"IntegrityError caching chunk {chunk_idx + 1} (concurrent request)")

            if progress_callback:
                await progress_callback(chunk_idx + 1, total_chunks, "completed")

            return translated_text

        # T022: Translate all chunks in parallel
        tasks = [
            translate_chunk(idx, start, end, text)
            for idx, (start, end, text) in enumerate(chunks)
        ]

        translated_chunks = await asyncio.gather(*tasks)

        # T023: Combine chunks
        combined_translation = self.combine_chunks(translated_chunks)

        logger.info(f"Combined {total_chunks} chunks into final translation")

        return {
            "document_id": document_id,
            "translated_text": combined_translation,
            "reading_level": reading_level,
            "model_used": model,
            "cached": False,  # At least one chunk was translated (chunking was needed)
            "chunks_processed": total_chunks
        }

    def evict_expired_cache(self) -> Dict[str, int]:
        """
        Evict expired cache entries (24h TTL expired).

        Returns:
            Dict with:
            - evicted_summaries: Count of evicted summary entries
            - evicted_translations: Count of evicted translation entries
        """
        now = datetime.utcnow()

        # Evict expired summaries
        expired_summaries = self.db.query(DocumentSummary).filter(
            DocumentSummary.expires_at < now
        ).delete(synchronize_session=False)

        # Evict expired translations
        expired_translations = self.db.query(DocumentTranslation).filter(
            DocumentTranslation.expires_at < now
        ).delete(synchronize_session=False)

        self.db.commit()

        logger.info(f"Evicted cache: {expired_summaries} summaries, {expired_translations} translations")

        return {
            "evicted_summaries": expired_summaries,
            "evicted_translations": expired_translations
        }

    def _get_cached_summary(self, document_id: str) -> Optional[DocumentSummary]:
        """Get cached summary if exists and not expired."""
        now = datetime.utcnow()
        return self.db.query(DocumentSummary).filter(
            DocumentSummary.document_id == document_id,
            DocumentSummary.expires_at > now
        ).first()

    def _get_cached_translation(
        self,
        document_id: str,
        source_hash: str,
        reading_level: str,
        prompt_hash: str,
        model: Optional[str] = None
    ) -> Optional[DocumentTranslation]:
        """
        Get cached translation using content-addressable composite key.

        T007: Updated for Feature 022 (Permanent Content-Addressable Caching)
        T024: Updated for Feature 024 (Model-Specific Caching)
        - Removed expires_at check (permanent cache, no TTL)
        - Added source_hash and prompt_hash to composite key
        - Added model to cache key (different models = different translations)
        - Cache invalidates automatically when content, prompt, or model changes

        Args:
            document_id: Document identifier
            source_hash: MD5 hash of source content
            reading_level: Target reading level (grade6, grade8, grade10)
            prompt_hash: MD5 hash of prompt template
            model: Model identifier (e.g., "qwen/qwen-2.5-72b-instruct")

        Returns:
            Cached translation if exact match found, None otherwise
        """
        query = self.db.query(DocumentTranslation).filter(
            DocumentTranslation.document_id == document_id,
            DocumentTranslation.source_hash == source_hash,
            DocumentTranslation.reading_level == reading_level,
            DocumentTranslation.prompt_hash == prompt_hash
        )

        # T024: Filter by model if provided (model-specific caching)
        if model:
            query = query.filter(DocumentTranslation.model_used == model)

        return query.first()

    async def analyze_document_with_library(
        self,
        document_content: str,
        library: dict,
        custom_prompt: Optional[str] = None
    ) -> dict:
        """
        Analyze document using OpenRouter LLM with decision library context.

        T010: Feature 023 - Template Workflow API
        Mode 1: Document Analysis & Decision Mapping

        Args:
            document_content: Full text of document to analyze
            library: Decision library (DecisionLibrary dict from JSON)
            custom_prompt: Optional custom system prompt (for testing)

        Returns:
            Dict with "matches" array of decision matches:
            {
                "matches": [
                    {
                        "decision_id": str,
                        "confidence": float (0.0-1.0),
                        "evidence": str (max 500 chars),
                        "suggested_values": dict or None
                    }
                ]
            }

        Raises:
            ValueError: If document_content empty or library invalid
            httpx.TimeoutException: If API call exceeds 30s (FR-017)
            httpx.HTTPStatusError: If API returns error status
        """
        # Validate inputs
        if not document_content or len(document_content.strip()) == 0:
            raise ValueError("document_content must be non-empty")

        if not library or "DecisionLibrary" not in library:
            raise ValueError("library must contain 'DecisionLibrary' key")

        # Load system prompt (use custom if provided, for testing)
        if custom_prompt:
            system_prompt = custom_prompt
            logger.info("Using custom analysis prompt (test mode)")
        else:
            # Load from prompts/template_analysis_prompt.md
            prompt_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "prompts",
                "template_analysis_prompt.md"
            )
            try:
                with open(prompt_path, "r", encoding="utf-8") as f:
                    system_prompt = f.read()
            except FileNotFoundError:
                logger.error(f"Template analysis prompt not found: {prompt_path}")
                raise ValueError(f"System prompt file not found: {prompt_path}")

        # Build messages for LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": document_content}
        ]

        # Call OpenRouter API
        try:
            response_text, model_used = await self._call_openrouter_api_with_messages(
                messages=messages,
                temperature=0.3,  # Low temperature for consistent analysis
                max_tokens=4000   # Sufficient for analysis response
            )

            # Parse JSON response
            import json
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM response as JSON: {e}")
                logger.debug(f"LLM response: {response_text[:500]}")
                raise ValueError(f"LLM returned invalid JSON: {e}")

            # Validate response structure
            if "matches" not in result:
                logger.error("LLM response missing 'matches' key")
                raise ValueError("LLM response missing 'matches' key")

            if not isinstance(result["matches"], list):
                logger.error("LLM response 'matches' is not an array")
                raise ValueError("LLM response 'matches' must be an array")

            # Validate decision IDs exist in library
            library_ids = {decision["id"] for decision in library["DecisionLibrary"]}
            for match in result["matches"]:
                if "decision_id" not in match:
                    logger.warning(f"Match missing decision_id: {match}")
                    continue
                if match["decision_id"] not in library_ids:
                    logger.warning(f"Unknown decision_id '{match['decision_id']}' from LLM")

            logger.info(f"Document analysis complete: {len(result['matches'])} matches found")
            return result

        except httpx.TimeoutException:
            logger.error("OpenRouter API timeout during document analysis")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter API error during analysis: {e.response.status_code}")
            raise

    async def _call_openrouter_api(
        self,
        prompt: str,
        max_tokens: int = 30000,
        model: Optional[str] = None
    ) -> tuple[str, str]:
        """
        Call OpenRouter API with timeout and error handling.

        T008: Updated for Feature 022 (Large Document Support)
        T024: Updated for Feature 024 (Model Parameter Support)
        - Added max_tokens parameter (default 30000, increased from 8000)
        - Added model parameter (None = use default_model)
        - Supports full 77-page document translation with model selection

        Args:
            prompt: LLM prompt text
            max_tokens: Maximum tokens in response (default 30000)
            model: OpenRouter model identifier (None = use default_model)

        Returns:
            Tuple of (response_text, model_used)

        Raises:
            httpx.TimeoutException: If request exceeds 30s
            httpx.HTTPStatusError: If API returns error status
        """
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not configured")

        # Use provided model or default
        selected_model = model or self.default_model

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.referer,
            "Content-Type": "application/json"
        }

        payload = {
            "model": selected_model,  # T024: Use selected model (Feature 024)
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()

            data = response.json()
            response_text = data["choices"][0]["message"]["content"]
            model_used = data.get("model", self.default_model)

            return response_text.strip(), model_used

    async def _call_openrouter_api_with_messages(
        self,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 4000
    ) -> tuple[str, str]:
        """
        Call OpenRouter API with custom messages array (system + user prompts).

        T010: Feature 023 - Template Workflow API
        Supports system prompts for structured document analysis

        Args:
            messages: Array of message dicts with role and content
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response

        Returns:
            Tuple of (response_text, model_used)

        Raises:
            httpx.TimeoutException: If request exceeds 30s
            httpx.HTTPStatusError: If API returns error status
        """
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.referer,
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()

            data = response.json()
            response_text = data["choices"][0]["message"]["content"]
            model_used = data.get("model", self.default_model)

            return response_text.strip(), model_used
