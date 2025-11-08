"""
Unit tests for GOV.UK chrome pattern detection (Feature 019).

These tests verify individual chrome patterns are correctly identified
and removed by ChromeStripper.

According to TDD, these tests MUST FAIL initially because ChromeStripper
has not been implemented yet. They will pass after T009 implementation.

Pattern reference: .specify/specs/019-process-all-7/research.md lines 12-73
"""
import pytest

# This import will fail initially (TDD approach)
# It will succeed after T009: Implement ChromeStripper service
from src.services.chrome_stripper import ChromeStripper


@pytest.mark.chrome
@pytest.mark.unit
class TestChromePatternDetection:
    """Unit tests for individual GOV.UK chrome patterns."""

    def test_strip_cookie_banner(self):
        """
        Verify cookie banner removal (Pattern 1: gem-c-cookie-banner).

        Pattern reference: research.md lines 14-16
        """
        # Arrange
        stripper = ChromeStripper()
        html = """
        <html>
          <div class="gem-c-cookie-banner">
            <h2>Cookies on GOV.UK</h2>
            <p>We use some essential cookies to make this service work.</p>
            <button>Accept additional cookies</button>
            <button>Reject additional cookies</button>
          </div>
          <main class="govuk-main-wrapper">
            <h1>Main Content</h1>
          </main>
        </html>
        """

        # Act
        cleaned_html, stats = stripper.strip_chrome(html, "test-001")

        # Assert - Cookie banner removed
        assert "gem-c-cookie-banner" not in cleaned_html
        assert "Cookies on GOV.UK" not in cleaned_html
        assert "Accept additional cookies" not in cleaned_html

        # Assert - Main content preserved
        assert "Main Content" in cleaned_html

        # Assert - Pattern tracked in stats
        assert "cookie-banner" in stats["patterns_matched"] or \
               "gem-c-cookie-banner" in stats["patterns_matched"]

    def test_strip_footer(self):
        """
        Verify footer removal (Pattern 5: govuk-footer).

        Pattern reference: research.md lines 30-32
        """
        # Arrange
        stripper = ChromeStripper()
        html = """
        <html>
          <main class="govuk-main-wrapper">
            <h1>Content</h1>
          </main>
          <footer class="govuk-footer">
            <div class="govuk-footer__meta">
              <ul>
                <li>Help</li>
                <li>Privacy</li>
                <li>Cookies</li>
                <li>Accessibility statement</li>
                <li>Contact</li>
                <li>Terms and conditions</li>
              </ul>
            </div>
          </footer>
        </html>
        """

        # Act
        cleaned_html, stats = stripper.strip_chrome(html, "test-002")

        # Assert - Footer removed
        assert "govuk-footer" not in cleaned_html
        assert "Privacy" not in cleaned_html
        assert "Terms and conditions" not in cleaned_html

        # Assert - Main content preserved
        assert "Content" in cleaned_html

    def test_strip_navigation(self):
        """
        Verify navigation header removal (Pattern 3: govuk-header).

        Pattern reference: research.md lines 22-24
        """
        # Arrange
        stripper = ChromeStripper()
        html = """
        <html>
          <header class="govuk-header">
            <div class="govuk-header__logo">
              <a href="/">GOV.UK</a>
            </div>
            <button class="govuk-header__menu-button">Menu</button>
            <form class="govuk-header__search">
              <input type="text" placeholder="Search GOV.UK">
            </form>
          </header>
          <main class="govuk-main-wrapper">
            <h1>Guidance Content</h1>
          </main>
        </html>
        """

        # Act
        cleaned_html, stats = stripper.strip_chrome(html, "test-003")

        # Assert - Header navigation removed
        assert "govuk-header" not in cleaned_html
        assert "Menu" not in cleaned_html
        assert "Search GOV.UK" not in cleaned_html

        # Assert - Main content preserved
        assert "Guidance Content" in cleaned_html

    def test_preserve_main_content(self):
        """
        Verify main guidance content is preserved after chrome removal.

        Pattern reference: research.md lines 132-138
        """
        # Arrange
        stripper = ChromeStripper()
        html = """
        <html>
          <div class="gem-c-cookie-banner">Cookies</div>
          <header class="govuk-header">Header</header>
          <div class="gem-c-breadcrumbs">Home > Section</div>
          <main class="govuk-main-wrapper" id="content">
            <h1>How to Apply for a UK Passport</h1>
            <p>You need to have a British nationality to apply for a UK passport.</p>
            <h2>What you'll need</h2>
            <ul>
              <li>A digital photo</li>
              <li>Your birth certificate</li>
              <li>Proof of identity</li>
            </ul>
            <p>The application process takes 3 weeks.</p>
          </main>
          <footer class="govuk-footer">Footer</footer>
        </html>
        """

        # Act
        cleaned_html, stats = stripper.strip_chrome(html, "test-004")

        # Assert - All chrome removed
        assert "gem-c-cookie-banner" not in cleaned_html
        assert "govuk-header" not in cleaned_html
        assert "gem-c-breadcrumbs" not in cleaned_html
        assert "govuk-footer" not in cleaned_html

        # Assert - All main content preserved
        assert "How to Apply for a UK Passport" in cleaned_html
        assert "You need to have a British nationality" in cleaned_html
        assert "What you'll need" in cleaned_html
        assert "A digital photo" in cleaned_html
        assert "Your birth certificate" in cleaned_html
        assert "Proof of identity" in cleaned_html
        assert "The application process takes 3 weeks" in cleaned_html

        # Assert - Stats reflect high chrome percentage
        assert stats["chrome_percentage"] > 0.0
        assert stats["guidance_chars"] > 0

    def test_calculate_chrome_percentage(self):
        """
        Verify chrome percentage calculation is accurate.

        Pattern reference: research.md lines 119-122
        """
        # Arrange
        stripper = ChromeStripper()
        # Create HTML with known chrome/content ratio
        # Approximately 100 chars chrome, 50 chars content = 66.7% chrome
        html = """
        <html>
          <div class="gem-c-cookie-banner">Cookies on GOV.UK - click to accept or reject (100 characters)</div>
          <main class="govuk-main-wrapper">Short guidance (50 chars)</main>
        </html>
        """

        # Act
        cleaned_html, stats = stripper.strip_chrome(html, "test-005")

        # Assert - Percentage calculated
        assert "chrome_percentage" in stats
        assert isinstance(stats["chrome_percentage"], float)
        assert 0.0 <= stats["chrome_percentage"] <= 100.0

        # Assert - Stats are internally consistent
        expected_percentage = (stats["chrome_chars"] / stats["original_chars"]) * 100
        assert abs(stats["chrome_percentage"] - expected_percentage) < 0.1, \
            "chrome_percentage should match calculated value"


@pytest.mark.chrome
@pytest.mark.unit
class TestAdditionalChromePatterns:
    """Unit tests for additional GOV.UK chrome patterns."""

    def test_strip_skip_link(self):
        """Verify skip link removal (Pattern 2: gem-c-skip-link)."""
        stripper = ChromeStripper()
        html = """
        <a href="#main-content" class="gem-c-skip-link">Skip to main content</a>
        <main id="main-content"><h1>Content</h1></main>
        """
        cleaned_html, stats = stripper.strip_chrome(html, "test-006")

        assert "gem-c-skip-link" not in cleaned_html
        assert "Skip to main content" not in cleaned_html
        assert "Content" in cleaned_html

    def test_strip_breadcrumbs(self):
        """Verify breadcrumbs removal (Pattern 4: gem-c-breadcrumbs)."""
        stripper = ChromeStripper()
        html = """
        <div class="gem-c-breadcrumbs">
          <ol>
            <li><a href="/">Home</a></li>
            <li><a href="/section">Section</a></li>
          </ol>
        </div>
        <main><h1>Content</h1></main>
        """
        cleaned_html, stats = stripper.strip_chrome(html, "test-007")

        assert "gem-c-breadcrumbs" not in cleaned_html
        assert "Content" in cleaned_html

    def test_strip_feedback_survey(self):
        """Verify feedback survey removal (Pattern 6: gem-c-intervention)."""
        stripper = ChromeStripper()
        html = """
        <main><h1>Content</h1></main>
        <div class="gem-c-intervention">
          <p>Is this page useful?</p>
          <button>Yes this page is useful</button>
          <button>No this page is not useful</button>
        </div>
        """
        cleaned_html, stats = stripper.strip_chrome(html, "test-008")

        assert "gem-c-intervention" not in cleaned_html
        assert "Is this page useful?" not in cleaned_html
        assert "Content" in cleaned_html

    def test_strip_print_link(self):
        """Verify print link removal (Pattern 7: gem-c-print-link)."""
        stripper = ChromeStripper()
        html = """
        <main><h1>Content</h1></main>
        <button class="gem-c-print-link">Print this page</button>
        """
        cleaned_html, stats = stripper.strip_chrome(html, "test-009")

        assert "gem-c-print-link" not in cleaned_html
        assert "Print this page" not in cleaned_html

    def test_strip_phase_banner(self):
        """Verify phase banner removal (Pattern 8: gem-c-phase-banner)."""
        stripper = ChromeStripper()
        html = """
        <div class="gem-c-phase-banner">
          <strong>BETA</strong>
          <span>This is a new service</span>
        </div>
        <main><h1>Content</h1></main>
        """
        cleaned_html, stats = stripper.strip_chrome(html, "test-010")

        assert "gem-c-phase-banner" not in cleaned_html
        assert "BETA" not in cleaned_html

    def test_strip_related_navigation(self):
        """Verify related navigation removal (Pattern 9: gem-c-related-navigation)."""
        stripper = ChromeStripper()
        html = """
        <main><h1>Content</h1></main>
        <aside class="gem-c-related-navigation">
          <h2>Related content</h2>
          <ul><li><a href="/related">Related page</a></li></ul>
        </aside>
        """
        cleaned_html, stats = stripper.strip_chrome(html, "test-011")

        assert "gem-c-related-navigation" not in cleaned_html
        assert "Related content" not in cleaned_html

    def test_strip_scripts_and_styles(self):
        """Verify script/style tags removal (Pattern 15)."""
        stripper = ChromeStripper()
        html = """
        <html>
          <style>.test { color: red; }</style>
          <script>console.log('test');</script>
          <main><h1>Content</h1></main>
        </html>
        """
        cleaned_html, stats = stripper.strip_chrome(html, "test-012")

        assert "<script>" not in cleaned_html
        assert "<style>" not in cleaned_html
        assert "Content" in cleaned_html
