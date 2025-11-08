"""
T038: FilterService
Service for computing filter facets and preview counts from search results

Features:
- Calculate facet counts for document_type, date_range, source
- Preview result counts for filter combinations
- Optimized queries for fast filter preview (<200ms target)
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import Counter

logger = logging.getLogger(__name__)


class FilterService:
    """
    Service for filter facet calculation and preview counts.

    Methods:
        get_facets(results): Extract available filter facets from search results
        get_preview_count(results, filter_combination): Calculate result count for filter combination
    """

    # Allowed document types (from UK Immigration guidance corpus)
    DOCUMENT_TYPES = [
        "guidance",
        "form",
        "appendix",
        "caseworker_instruction",
        "policy",
        "other",
    ]

    # Date range presets
    DATE_RANGES = {
        "last_30_days": timedelta(days=30),
        "last_6_months": timedelta(days=180),
        "last_year": timedelta(days=365),
        "all_time": None,
    }

    @classmethod
    def get_facets(cls, results: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Extract filter facets from search results with counts.

        Args:
            results: List of search result documents with metadata

        Returns:
            Dict with facet_type → list of {label, value, count} objects
            {
                "document_type": [{"label": "Guidance", "value": "guidance", "count": 42}, ...],
                "date_range": [{"label": "Last 30 days", "value": "last_30_days", "count": 10}, ...],
                "source": [{"label": "Home Office", "value": "home_office", "count": 25}, ...]
            }

        Example:
            results = [{"document_type": "guidance", "source": "home_office", ...}, ...]
            facets = FilterService.get_facets(results)
        """
        logger.info(f"Calculating facets for {len(results)} results")

        # Extract document types
        document_type_counts = Counter(
            result.get("document_type", "other") for result in results
        )
        document_type_facets = [
            {
                "label": cls._humanize_document_type(doc_type),
                "value": doc_type,
                "count": count,
            }
            for doc_type, count in document_type_counts.items()
        ]

        # Extract sources
        source_counts = Counter(result.get("source", "unknown") for result in results)
        source_facets = [
            {"label": cls._humanize_source(source), "value": source, "count": count}
            for source, count in source_counts.items()
        ]

        # Calculate date range counts
        date_range_facets = cls._calculate_date_range_facets(results)

        return {
            "document_type": sorted(document_type_facets, key=lambda x: -x["count"]),
            "date_range": date_range_facets,
            "source": sorted(source_facets, key=lambda x: -x["count"]),
        }

    @classmethod
    def get_preview_count(
        cls,
        results: List[Dict],
        filter_combination: Dict[str, Any],
    ) -> int:
        """
        Calculate result count for a filter combination.

        Args:
            results: List of search result documents
            filter_combination: Filters to apply
                {
                    "document_type": ["guidance", "form"],
                    "date_range": {"start": "2024-01-01", "end": "2024-06-30"},
                    "source": ["home_office"]
                }

        Returns:
            Number of results matching the filter combination

        Example:
            count = FilterService.get_preview_count(
                results,
                {"document_type": ["guidance"], "source": ["home_office"]}
            )
        """
        logger.debug(f"Calculating preview count for filters: {filter_combination}")

        filtered_results = cls._apply_filters(results, filter_combination)
        count = len(filtered_results)

        logger.debug(f"Preview count: {count} results")
        return count

    @classmethod
    def _apply_filters(cls, results: List[Dict], filters: Dict[str, Any]) -> List[Dict]:
        """
        Apply filter combination to results list.

        Args:
            results: List of search result documents
            filters: Filters to apply

        Returns:
            Filtered list of results
        """
        filtered = results

        # Filter by document type
        if "document_type" in filters and filters["document_type"]:
            doc_types = set(filters["document_type"])
            filtered = [
                r for r in filtered if r.get("document_type", "other") in doc_types
            ]

        # Filter by date range
        if "date_range" in filters and filters["date_range"]:
            filtered = cls._filter_by_date_range(filtered, filters["date_range"])

        # Filter by source
        if "source" in filters and filters["source"]:
            sources = set(filters["source"])
            filtered = [r for r in filtered if r.get("source", "unknown") in sources]

        return filtered

    @classmethod
    def _filter_by_date_range(
        cls, results: List[Dict], date_range: Dict[str, str]
    ) -> List[Dict]:
        """
        Filter results by date range.

        Args:
            results: List of search result documents
            date_range: {"start": "2024-01-01", "end": "2024-06-30"} or {"preset": "last_30_days"}

        Returns:
            Filtered list of results within date range
        """
        # Handle preset date ranges
        if "preset" in date_range:
            preset = date_range["preset"]
            if preset == "all_time":
                return results  # No filtering

            if preset in cls.DATE_RANGES:
                cutoff_date = datetime.utcnow() - cls.DATE_RANGES[preset]
                return [
                    r
                    for r in results
                    if cls._parse_date(r.get("publication_date")) >= cutoff_date
                ]

        # Handle custom date range
        if "start" in date_range and "end" in date_range:
            start_date = cls._parse_date(date_range["start"])
            end_date = cls._parse_date(date_range["end"])

            return [
                r
                for r in results
                if start_date <= cls._parse_date(r.get("publication_date")) <= end_date
            ]

        return results

    @classmethod
    def _calculate_date_range_facets(cls, results: List[Dict]) -> List[Dict]:
        """
        Calculate facet counts for preset date ranges.

        Args:
            results: List of search result documents

        Returns:
            List of date range facets with counts
        """
        now = datetime.utcnow()
        facets = []

        for preset, delta in cls.DATE_RANGES.items():
            if delta is None:  # all_time
                count = len(results)
            else:
                cutoff_date = now - delta
                count = sum(
                    1
                    for r in results
                    if cls._parse_date(r.get("publication_date")) >= cutoff_date
                )

            facets.append(
                {
                    "label": cls._humanize_date_range(preset),
                    "value": preset,
                    "count": count,
                }
            )

        return facets

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> datetime:
        """
        Parse date string to datetime object.

        Args:
            date_str: ISO-8601 date string

        Returns:
            datetime object (defaults to epoch if parsing fails)
        """
        if not date_str:
            return datetime(1970, 1, 1)  # Epoch

        try:
            # Try ISO-8601 format
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            logger.warning(f"Failed to parse date: {date_str}")
            return datetime(1970, 1, 1)

    @staticmethod
    def _humanize_document_type(doc_type: str) -> str:
        """Convert document type to human-readable label."""
        labels = {
            "guidance": "Guidance",
            "form": "Form",
            "appendix": "Appendix",
            "caseworker_instruction": "Caseworker Instruction",
            "policy": "Policy",
            "other": "Other",
        }
        return labels.get(doc_type, doc_type.title())

    @staticmethod
    def _humanize_source(source: str) -> str:
        """Convert source to human-readable label."""
        labels = {
            "home_office": "Home Office",
            "passport_office": "Passport Office",
            "ukvi": "UK Visas and Immigration",
            "border_force": "Border Force",
            "unknown": "Unknown",
        }
        return labels.get(source, source.replace("_", " ").title())

    @staticmethod
    def _humanize_date_range(preset: str) -> str:
        """Convert date range preset to human-readable label."""
        labels = {
            "last_30_days": "Last 30 days",
            "last_6_months": "Last 6 months",
            "last_year": "Last year",
            "all_time": "All time",
        }
        return labels.get(preset, preset.replace("_", " ").title())
