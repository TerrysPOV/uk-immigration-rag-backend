"""
Experimental Template Generation Service.

Provides LLM-based template generation with custom system prompts
and artifact context for prompt engineering experiments.

Feature: 021-create-a-dedicated (Prompt Engineering Workspace)
Tasks: T011
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import httpx
import textstat

logger = logging.getLogger(__name__)


class ExperimentalGenerationService:
    """
    LLM-based template generation service for prompt engineering experiments.

    Features:
    - Custom system prompt support (max 5000 chars)
    - Artifact context injection
    - Readability metrics (Flesch score, grade level, reading age)
    - Multiple model support (gpt-4, claude-3-opus, claude-3-sonnet)
    - Render time tracking
    """

    # Model mapping for OpenRouter API
    MODEL_MAP = {
        "gpt-4": "openai/gpt-4",
        "claude-3-opus": "anthropic/claude-3-opus",
        "claude-3-sonnet": "anthropic/claude-3-sonnet",
    }

    def __init__(self):
        """Initialize experimental generation service."""
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.timeout = 60  # 60 seconds for template generation
        self.referer = os.getenv("OPENROUTER_REFERER", "https://vectorgov.poview.ai")

        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not configured - API calls will fail")

    async def generate_template(
        self,
        custom_system_prompt: str,
        artifact_content: Optional[List[str]] = None,
        model_preference: str = "gpt-4",
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """
        Generate template using custom system prompt and optional artifacts.

        Args:
            custom_system_prompt: Custom instructions (max 5000 chars)
            artifact_content: List of artifact text content (optional)
            model_preference: Model to use (gpt-4, claude-3-opus, claude-3-sonnet)
            max_tokens: Maximum tokens for generation
            temperature: Sampling temperature (0.0-1.0)

        Returns:
            Dict with:
            - generated_content: Generated template text
            - readability_metrics: Dict with flesch_score, grade_level, reading_age
            - model_used: Model identifier
            - render_time_ms: Processing time in milliseconds

        Raises:
            ValueError: If custom_system_prompt invalid or exceeds 5000 chars
            httpx.TimeoutException: If API call exceeds timeout
            httpx.HTTPStatusError: If API returns error status
        """
        # Validate custom system prompt
        if not custom_system_prompt or not custom_system_prompt.strip():
            raise ValueError("custom_system_prompt must be non-empty")

        if len(custom_system_prompt) > 5000:
            raise ValueError(
                f"custom_system_prompt exceeds 5000 character limit "
                f"(got {len(custom_system_prompt)} chars)"
            )

        # Validate model preference
        if model_preference not in self.MODEL_MAP:
            raise ValueError(
                f"Invalid model_preference '{model_preference}'. "
                f"Allowed: {list(self.MODEL_MAP.keys())}"
            )

        # Start timing
        start_time = datetime.utcnow()

        try:
            # Build prompt with artifact context
            user_prompt = self._build_prompt_with_artifacts(
                custom_system_prompt,
                artifact_content or []
            )

            # Call LLM API
            generated_content, model_used = await self._call_llm_api(
                user_prompt=user_prompt,
                model=model_preference,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            # Calculate readability metrics
            readability_metrics = self._calculate_readability_metrics(generated_content)

            # Calculate render time
            end_time = datetime.utcnow()
            render_time_ms = (end_time - start_time).total_seconds() * 1000

            logger.info(
                f"Template generated: model={model_used}, "
                f"flesch={readability_metrics['flesch_score']:.1f}, "
                f"render_time={render_time_ms:.0f}ms"
            )

            return {
                "generated_content": generated_content,
                "readability_metrics": readability_metrics,
                "model_used": model_used,
                "render_time_ms": render_time_ms,
            }

        except httpx.TimeoutException:
            logger.error("OpenRouter API timeout during template generation")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter API error: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"Template generation failed: {str(e)}")
            raise RuntimeError(f"Template generation failed: {str(e)}")

    def _build_prompt_with_artifacts(
        self,
        custom_system_prompt: str,
        artifact_content: List[str]
    ) -> str:
        """
        Build user prompt combining custom instructions and artifact context.

        Args:
            custom_system_prompt: Custom instructions
            artifact_content: List of artifact text content

        Returns:
            Combined prompt string
        """
        prompt_parts = [custom_system_prompt]

        if artifact_content:
            prompt_parts.append("\n\n## Sample Documents\n")
            for i, content in enumerate(artifact_content, 1):
                # Limit each artifact to 2000 chars to avoid token limits
                truncated_content = content[:2000]
                if len(content) > 2000:
                    truncated_content += "\n... (truncated)"

                prompt_parts.append(f"\n### Document {i}\n{truncated_content}\n")

        prompt_parts.append(
            "\n\n## Task\n"
            "Generate a template following the instructions above. "
            "Use plain English suitable for reading age 9-13. "
            "Follow GOV.UK Design System patterns."
        )

        return "".join(prompt_parts)

    async def _call_llm_api(
        self,
        user_prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, str]:
        """
        Call OpenRouter API for template generation.

        Args:
            user_prompt: Combined prompt text
            model: Model preference key (gpt-4, claude-3-opus, etc.)
            max_tokens: Maximum tokens
            temperature: Sampling temperature

        Returns:
            Tuple of (generated_content, model_used)

        Raises:
            ValueError: If API key not configured
            httpx.TimeoutException: If request exceeds timeout
            httpx.HTTPStatusError: If API returns error status
        """
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not configured")

        # Map model preference to OpenRouter model identifier
        openrouter_model = self.MODEL_MAP[model]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.referer,
            "Content-Type": "application/json"
        }

        payload = {
            "model": openrouter_model,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()

            data = response.json()
            generated_content = data["choices"][0]["message"]["content"]
            model_used = data.get("model", openrouter_model)

            return generated_content.strip(), model_used

    def _calculate_readability_metrics(self, text: str) -> Dict[str, float]:
        """
        Calculate readability metrics for generated content.

        Args:
            text: Generated template text

        Returns:
            Dict with flesch_score, grade_level, reading_age
        """
        # Calculate Flesch Reading Ease (0-100, higher = easier)
        flesch_score = textstat.flesch_reading_ease(text)

        # Calculate Flesch-Kincaid Grade Level
        grade_level = textstat.flesch_kincaid_grade(text)

        # Estimate reading age (grade level + 5)
        reading_age = grade_level + 5

        return {
            "flesch_score": round(flesch_score, 1),
            "grade_level": round(grade_level, 1),
            "reading_age": round(reading_age, 1),
        }


# Singleton instance
_service_instance: Optional[ExperimentalGenerationService] = None


def get_experimental_generation_service() -> ExperimentalGenerationService:
    """Get or create singleton ExperimentalGenerationService instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = ExperimentalGenerationService()
    return _service_instance
