"""
ChromeStripper Service for GOV.UK Content Cleaning (Feature 019).

This service removes GOV.UK chrome (navigation, cookies, footer, etc.) from
scraped HTML documents before chunking and vectorization.

Contract: .specify/specs/019-process-all-7/contracts/chrome_stripper_contract.md
Patterns: .specify/specs/019-process-all-7/research.md lines 12-73
"""
import logging
from typing import Tuple, Dict, List, Any
from bs4 import BeautifulSoup
import re

# Configure structured logging
logger = logging.getLogger(__name__)


class ChromeDetectionError(Exception):
    """Raised when HTML parsing or chrome detection fails."""
    pass


class ChromeStripper:
    """
    Service for detecting and removing GOV.UK chrome from HTML content.

    Chrome includes:
    - Cookie banners
    - Navigation headers
    - Footer links
    - Breadcrumbs
    - Feedback surveys
    - Related content sidebars
    - Scripts and stylesheets
    """

    VERSION = "1.0.0"

    # GOV.UK chrome patterns from research.md (15 patterns total)
    CHROME_PATTERNS = [
        # Pattern 1: Cookie Banner
        '.gem-c-cookie-banner',
        '#global-cookie-message',

        # Pattern 2: Skip Link
        '.gem-c-skip-link',
        '.govuk-skip-link',
        'a[href="#main-content"]',

        # Pattern 3: Header Navigation
        '.govuk-header',
        '.gem-c-layout-super-navigation-header',

        # Pattern 4: Breadcrumbs
        '.gem-c-breadcrumbs',

        # Pattern 5: Footer
        '.govuk-footer',

        # Pattern 6: Feedback Survey
        '.gem-c-intervention',
        '.gem-c-feedback',

        # Pattern 7: Print Link
        '.gem-c-print-link',

        # Pattern 8: Phase Banner
        '.gem-c-phase-banner',

        # Pattern 9: Related Navigation
        '.gem-c-related-navigation',
        'aside.govuk-related-items',
        'aside',

        # Pattern 10: Step Nav
        '.gem-c-step-nav',
        '.app-step-nav',

        # Pattern 11: Contextual Sidebar
        '.gem-c-contextual-sidebar',

        # Pattern 12: Report Problem
        '.gem-c-report-a-problem-link',

        # Pattern 13: Improvement Banner
        '.gem-c-improvement-banner',

        # Pattern 14: Emergency Banner
        '.gem-c-emergency-banner',

        # Pattern 15: Script/Style Tags
        'script',
        'style',
        'noscript',
        'link[rel="stylesheet"]',
    ]

    def __init__(self):
        """Initialize ChromeStripper with default patterns."""
        self.chrome_patterns = self.CHROME_PATTERNS
        self.version = self.VERSION

    def strip_chrome(
        self,
        html: str,
        document_id: str
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Remove GOV.UK chrome from HTML and return cleaned content + stats.

        Args:
            html: Raw HTML from scraped GOV.UK document
            document_id: Document UUID for logging

        Returns:
            Tuple of (cleaned_html, removal_stats) where:
            - cleaned_html: HTML with chrome removed
            - removal_stats: Dict with original_chars, chrome_chars,
                           guidance_chars, chrome_percentage, patterns_matched

        Raises:
            ChromeDetectionError: If HTML is malformed (rare)

        Contract: chrome_stripper_contract.md lines 14-76
        """
        try:
            # Calculate original length
            original_chars = len(html)

            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(html, 'lxml')

            # Track which patterns matched
            patterns_matched = []

            # Remove all chrome patterns
            for pattern in self.chrome_patterns:
                elements = soup.select(pattern)
                if elements:
                    # Track pattern (normalize pattern name for stats)
                    pattern_name = self._normalize_pattern_name(pattern)
                    if pattern_name not in patterns_matched:
                        patterns_matched.append(pattern_name)

                    # Remove elements
                    for element in elements:
                        element.decompose()

            # Extract main content (prefer main wrapper, fall back to body)
            main_content = (
                soup.find('main', class_='govuk-main-wrapper') or
                soup.find('main') or
                soup.find('div', id='content') or
                soup.find('body') or
                soup
            )

            # Get cleaned HTML
            cleaned_html = str(main_content)
            cleaned_chars = len(cleaned_html)

            # Calculate stats
            chrome_chars = original_chars - cleaned_chars
            guidance_chars = cleaned_chars
            chrome_percentage = (chrome_chars / original_chars * 100) if original_chars > 0 else 0.0

            # Build stats dictionary
            removal_stats = {
                "original_chars": original_chars,
                "chrome_chars": chrome_chars,
                "guidance_chars": guidance_chars,
                "chrome_percentage": round(chrome_percentage, 2),
                "patterns_matched": patterns_matched
            }

            # Log removal
            self.log_removal(document_id, removal_stats)

            return (cleaned_html, removal_stats)

        except Exception as e:
            # Fallback: Return original HTML if parsing fails
            logger.warning(
                f"Chrome detection failed for document {document_id}: {e}",
                extra={"document_id": document_id, "error": str(e)}
            )

            # Return original HTML with zero chrome removal stats
            fallback_stats = {
                "original_chars": len(html),
                "chrome_chars": 0,
                "guidance_chars": len(html),
                "chrome_percentage": 0.0,
                "patterns_matched": []
            }

            return (html, fallback_stats)

    def detect_chrome_percentage(self, html: str) -> float:
        """
        Calculate percentage of content that is chrome.

        Args:
            html: Raw HTML from GOV.UK document

        Returns:
            Float between 0.0 and 100.0 representing chrome percentage

        Contract: chrome_stripper_contract.md lines 95-111
        """
        try:
            _, stats = self.strip_chrome(html, "chrome-detection")
            return stats["chrome_percentage"]
        except Exception as e:
            logger.warning(f"Chrome percentage detection failed: {e}")
            return 0.0

    def log_removal(self, document_id: str, stats: Dict[str, Any]) -> None:
        """
        Log chrome removal to structured log.

        Args:
            document_id: Document UUID
            stats: Chrome removal statistics

        Side Effect:
            Writes to application log with structured data

        Contract: chrome_stripper_contract.md lines 115-142
        """
        logger.info(
            "Chrome removed from document",
            extra={
                "event": "chrome_removed",
                "document_id": document_id,
                "chrome_percentage": stats["chrome_percentage"],
                "original_chars": stats["original_chars"],
                "chrome_chars": stats["chrome_chars"],
                "guidance_chars": stats["guidance_chars"],
                "patterns_matched": stats["patterns_matched"],
                "chrome_stripper_version": self.version
            }
        )

    def _normalize_pattern_name(self, pattern: str) -> str:
        """
        Normalize CSS selector to pattern name for stats tracking.

        Examples:
            '.gem-c-cookie-banner' -> 'cookie-banner'
            '.govuk-footer' -> 'footer'
            'script' -> 'script'
        """
        # Remove leading . and # (class and ID selectors)
        normalized = pattern.lstrip('.#')

        # Remove attribute selectors [...]
        normalized = re.sub(r'\[.*?\]', '', normalized)

        # Extract last component after space (compound selectors)
        if ' ' in normalized:
            normalized = normalized.split()[-1]

        # Remove gem-c- and govuk- prefixes for cleaner names
        normalized = normalized.replace('gem-c-', '')
        normalized = normalized.replace('govuk-', '')

        return normalized
