"""
URL scraper service with BFS traversal and content validation.

Feature 011: Document Ingestion & Batch Processing
T036: URL scraper with 20-degree limit, deduplication, rate limiting
"""

import asyncio
import hashlib
import re
import socket
import ipaddress
from collections import deque
from typing import Set, List, Dict, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

# Content validation keywords for UK government guidance (Feature 019: expanded to all departments)
# Removed immigration-only filters (FR-001, FR-002, FR-003)
GUIDANCE_KEYWORDS = [
    "guidance",
    "instruction",
    "application",
    "service",
    "how to",
    "eligibility",
    "apply",
    "rules",
    "regulations",
]

# URL patterns indicating guidance content (Feature 019: general patterns only)
# Removed immigration-specific patterns (FR-003)
GUIDANCE_URL_PATTERNS = [
    r"/guidance/",
    r"/how-to",
    r"/apply-",
]


class URLScraperService:
    """
    Service for scraping UK government guidance documents.

    Features:
    - BFS traversal with 20-degree limit (FR-008)
    - Content validation via keywords+URL patterns (FR-008a)
    - Rate limiting (1 req/s)
    - Deduplication via SHA-256
    - gov.uk domain restriction (FR-009)
    """

    def __init__(self, rate_limit_per_second: float = 1.0):
        self.rate_limit = rate_limit_per_second
        self.visited_urls: Set[str] = set()
        self.url_hashes: Set[str] = set()  # SHA-256 hashes for deduplication

    async def scrape_urls_with_nested(
        self, initial_urls: List[str], max_depth: int = 20, validate_content: bool = True
    ) -> Dict:
        """
        Scrape URLs with nested discovery using BFS traversal.

        Args:
            initial_urls: List of starting URLs
            max_depth: Maximum degrees of separation (default 20 per FR-008)
            validate_content: Whether to filter non-guidance pages (FR-008a)

        Returns:
            Dict with:
            - discovered_urls: List of all discovered URLs
            - scraped_documents: List of scraped document objects
            - filtered_urls: Count of URLs filtered out by content validation
            - max_depth_reached: Actual maximum depth reached
        """
        queue = deque()

        # Initialize queue with initial URLs at depth 0
        for url in initial_urls:
            try:
                if self._is_valid_gov_url(url):
                    queue.append((url, 0))
            except ValueError as e:
                # Log security validation failure
                print(f"URL validation failed for {url}: {e}")

        discovered_urls = []
        scraped_documents = []
        filtered_count = 0
        max_depth_reached = 0

        async with httpx.AsyncClient(timeout=30.0) as client:
            while queue:
                url, depth = queue.popleft()

                # Skip if already visited
                if url in self.visited_urls:
                    continue

                # Stop if max depth reached (FR-008)
                if depth > max_depth:
                    continue

                max_depth_reached = max(max_depth_reached, depth)

                # Mark as visited
                self.visited_urls.add(url)

                try:
                    # Rate limiting (1 req/s)
                    await asyncio.sleep(1 / self.rate_limit)

                    # Fetch page
                    response = await client.get(url)
                    response.raise_for_status()

                    html_content = response.text

                    # Content validation (FR-008a)
                    if validate_content and not self._is_guidance_content(url, html_content):
                        filtered_count += 1
                        continue

                    # Parse with BeautifulSoup
                    soup = BeautifulSoup(html_content, "lxml")

                    # Extract text content
                    text_content = self._extract_text(soup)

                    # Calculate content hash for deduplication
                    content_hash = hashlib.sha256(text_content.encode()).hexdigest()

                    if content_hash not in self.url_hashes:
                        self.url_hashes.add(content_hash)

                        # Store scraped document
                        document = {
                            "url": url,
                            "title": soup.find("title").text if soup.find("title") else url,
                            "content": text_content,
                            "content_hash": content_hash,
                            "depth": depth,
                        }

                        scraped_documents.append(document)
                        discovered_urls.append(url)

                    # Discover nested URLs (if not at max depth)
                    if depth < max_depth:
                        nested_urls = self._extract_links(soup, url)
                        for nested_url in nested_urls:
                            if nested_url not in self.visited_urls:
                                try:
                                    if self._is_valid_gov_url(nested_url):
                                        queue.append((nested_url, depth + 1))
                                except ValueError:
                                    # Silently skip invalid nested URLs (expected behavior)
                                    pass

                except httpx.HTTPError as e:
                    # Log error (FR-011)
                    print(f"HTTP error scraping {url}: {e}")
                except Exception as e:
                    # Log error (FR-011)
                    print(f"Error scraping {url}: {e}")

        return {
            "discovered_urls": discovered_urls,
            "scraped_documents": scraped_documents,
            "filtered_urls": filtered_count,
            "max_depth_reached": max_depth_reached,
            "stopped_at_depth": max_depth_reached >= max_depth,
        }

    def _is_valid_gov_url(self, url: str) -> bool:
        """
        Validate URL is from gov.uk domain with SSRF protection (FR-009).

        Security checks:
        1. HTTPS only (no HTTP)
        2. gov.uk domain whitelist
        3. DNS resolution to public IP (blocks 127.0.0.1, 10.x.x.x, 192.168.x.x)
        4. No localhost or internal hostnames

        Raises:
            ValueError: If URL fails security validation
        """
        parsed = urlparse(url)

        # 1. Require HTTPS scheme (SSRF protection)
        if parsed.scheme != "https":
            raise ValueError(f"Only HTTPS URLs allowed (got {parsed.scheme}): {url}")

        # 2. Domain whitelist: gov.uk only (FR-009)
        netloc = parsed.netloc.lower()
        if not (netloc.endswith(".gov.uk") or netloc == "www.gov.uk" or netloc == "gov.uk"):
            raise ValueError(f"URL must be from gov.uk domain (got {netloc}): {url}")

        # 3. Block localhost and internal hostnames (SSRF protection)
        if netloc in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
            raise ValueError(f"Localhost URLs are not allowed: {url}")

        # 4. DNS resolution check: block private IP addresses (SSRF protection)
        try:
            # Resolve hostname to IP address
            ip_str = socket.gethostbyname(parsed.netloc)
            ip = ipaddress.ip_address(ip_str)

            # Block private IP ranges (RFC 1918)
            # - 10.0.0.0/8 (10.0.0.0 - 10.255.255.255)
            # - 172.16.0.0/12 (172.16.0.0 - 172.31.255.255)
            # - 192.168.0.0/16 (192.168.0.0 - 192.168.255.255)
            # - 127.0.0.0/8 (loopback)
            # - 169.254.0.0/16 (link-local)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise ValueError(
                    f"Private/internal IP addresses not allowed: {netloc} resolves to {ip_str}"
                )

            # Block multicast and reserved ranges
            if ip.is_multicast or ip.is_reserved:
                raise ValueError(f"Invalid IP address range: {netloc} resolves to {ip_str}")

        except socket.gaierror:
            raise ValueError(f"DNS resolution failed for: {netloc}")
        except ValueError as e:
            # Re-raise ValueError from IP checks
            raise
        except Exception as e:
            raise ValueError(f"DNS validation error for {netloc}: {e}")

        return True

    def _is_guidance_content(self, url: str, html_content: str) -> bool:
        """
        Validate URL contains caseworker guidance content (FR-008a).

        Uses both URL patterns and content keywords.
        """
        # Check URL patterns
        for pattern in GUIDANCE_URL_PATTERNS:
            if re.search(pattern, url, re.IGNORECASE):
                return True

        # Check content keywords
        lower_content = html_content.lower()
        keyword_matches = sum(1 for keyword in GUIDANCE_KEYWORDS if keyword in lower_content)

        # Require at least 3 keyword matches
        return keyword_matches >= 3

    def _extract_text(self, soup: BeautifulSoup) -> str:
        """Extract main text content from HTML (FR-010)"""
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()

        # Get text
        text = soup.get_text()

        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = "\n".join(chunk for chunk in chunks if chunk)

        return text

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract all links from page"""
        links = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]

            # Convert relative URLs to absolute
            absolute_url = urljoin(base_url, href)

            # Remove fragments and query params for deduplication
            parsed = urlparse(absolute_url)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

            links.append(clean_url)

        return links

    async def scrape_single_url(self, url: str) -> Dict:
        """
        Scrape a single URL without nested discovery.

        Returns:
            Dict with document content
        """
        if not self._is_valid_gov_url(url):
            raise ValueError(f"URL must be from gov.uk domain: {url}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")
            text_content = self._extract_text(soup)

            return {
                "url": url,
                "title": soup.find("title").text if soup.find("title") else url,
                "content": text_content,
                "content_hash": hashlib.sha256(text_content.encode()).hexdigest(),
            }
