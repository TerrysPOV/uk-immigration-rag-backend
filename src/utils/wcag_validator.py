"""
T045: WCAGColorValidator
Utility for validating color contrast ratios against WCAG 2.1 AAA standards

WCAG 2.1 AAA Contrast Requirements:
- Normal text: 7:1 contrast ratio
- Large text (18pt+): 4.5:1 contrast ratio
- UI components & focus indicators: 3:1 contrast ratio

GOV.UK Color Palette Constants:
- Primary Blue: #003078
- Black: #0b0c0c
- Yellow: #ffdd00
- White: #ffffff
- Dark Grey: #6f777b
- Mid Grey: #b1b4b6
- Light Grey: #f3f2f1

Usage Example:
    validator = WCAGColorValidator()
    is_valid = validator.validate_text_contrast('#003078', '#ffffff')
    # Returns: True (contrast ratio 12.74:1 exceeds 7:1 requirement)
"""

from typing import Tuple


class WCAGColorValidator:
    """
    Validate color contrast ratios for WCAG 2.1 AAA compliance.

    Calculates relative luminance and contrast ratios.
    Provides validation for text, large text, and UI components.
    """

    # WCAG 2.1 AAA contrast ratio requirements
    NORMAL_TEXT_RATIO = 7.0
    LARGE_TEXT_RATIO = 4.5
    UI_COMPONENT_RATIO = 3.0

    # GOV.UK Design System color palette
    GOV_UK_COLORS = {
        "primary_blue": "#003078",
        "black": "#0b0c0c",
        "yellow": "#ffdd00",
        "white": "#ffffff",
        "dark_grey": "#6f777b",
        "mid_grey": "#b1b4b6",
        "light_grey": "#f3f2f1",
    }

    def __init__(self):
        """Initialize WCAG color validator."""
        print("[WCAGColorValidator] Initialized with WCAG 2.1 AAA standards")

    def hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """
        Convert hex color to RGB tuple.

        Args:
            hex_color: Hex color string (e.g., '#003078' or '003078')

        Returns:
            Tuple of (r, g, b) values (0-255)

        Raises:
            ValueError: If hex color is invalid
        """
        # Remove # if present
        hex_color = hex_color.lstrip("#")

        # Validate length
        if len(hex_color) != 6:
            raise ValueError(f"Invalid hex color: {hex_color} (must be 6 characters)")

        # Convert to RGB
        try:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            return (r, g, b)

        except ValueError:
            raise ValueError(f"Invalid hex color: {hex_color} (not valid hexadecimal)")

    def calculate_relative_luminance(self, rgb: Tuple[int, int, int]) -> float:
        """
        Calculate relative luminance of RGB color.

        Formula from WCAG 2.1:
        L = 0.2126 * R + 0.7152 * G + 0.0722 * B

        Where R, G, B are:
        - If channel/255 <= 0.03928: channel/255 / 12.92
        - Else: ((channel/255 + 0.055) / 1.055) ^ 2.4

        Args:
            rgb: Tuple of (r, g, b) values (0-255)

        Returns:
            Relative luminance (0.0 - 1.0)
        """

        def _channel_luminance(channel: int) -> float:
            """Calculate luminance for single channel."""
            srgb = channel / 255.0

            if srgb <= 0.03928:
                return srgb / 12.92
            else:
                return ((srgb + 0.055) / 1.055) ** 2.4

        r_lum = _channel_luminance(rgb[0])
        g_lum = _channel_luminance(rgb[1])
        b_lum = _channel_luminance(rgb[2])

        # Calculate relative luminance
        luminance = 0.2126 * r_lum + 0.7152 * g_lum + 0.0722 * b_lum

        return luminance

    def calculate_contrast_ratio(self, color1: str, color2: str) -> float:
        """
        Calculate contrast ratio between two colors.

        Formula from WCAG 2.1:
        (L1 + 0.05) / (L2 + 0.05)
        Where L1 is the lighter color's luminance

        Args:
            color1: First hex color
            color2: Second hex color

        Returns:
            Contrast ratio (1:1 to 21:1)

        Logs:
            - INFO: Calculated contrast ratio
        """
        # Convert to RGB
        rgb1 = self.hex_to_rgb(color1)
        rgb2 = self.hex_to_rgb(color2)

        # Calculate luminance
        lum1 = self.calculate_relative_luminance(rgb1)
        lum2 = self.calculate_relative_luminance(rgb2)

        # Ensure lum1 is lighter color
        if lum1 < lum2:
            lum1, lum2 = lum2, lum1

        # Calculate contrast ratio
        contrast = (lum1 + 0.05) / (lum2 + 0.05)

        print(f"[WCAGColorValidator] Contrast ratio: {color1} / {color2} = {contrast:.2f}:1")

        return contrast

    def validate_text_contrast(
        self, foreground: str, background: str, large_text: bool = False
    ) -> bool:
        """
        Validate text contrast ratio.

        Args:
            foreground: Foreground hex color
            background: Background hex color
            large_text: True if text is 18pt+ (or 14pt+ bold)

        Returns:
            True if contrast meets WCAG 2.1 AAA requirements

        Logs:
            - INFO: Validation result with contrast ratio
        """
        contrast = self.calculate_contrast_ratio(foreground, background)
        required_ratio = self.LARGE_TEXT_RATIO if large_text else self.NORMAL_TEXT_RATIO

        is_valid = contrast >= required_ratio

        print(
            f"[WCAGColorValidator] Text contrast validation: "
            f"{contrast:.2f}:1 {'≥' if is_valid else '<'} {required_ratio}:1 "
            f"({'PASS' if is_valid else 'FAIL'})"
        )

        return is_valid

    def validate_ui_component_contrast(self, foreground: str, background: str) -> bool:
        """
        Validate UI component or focus indicator contrast ratio.

        Args:
            foreground: Component foreground hex color
            background: Component background hex color

        Returns:
            True if contrast meets 3:1 requirement

        Logs:
            - INFO: Validation result with contrast ratio
        """
        contrast = self.calculate_contrast_ratio(foreground, background)
        required_ratio = self.UI_COMPONENT_RATIO

        is_valid = contrast >= required_ratio

        print(
            f"[WCAGColorValidator] UI component contrast validation: "
            f"{contrast:.2f}:1 {'≥' if is_valid else '<'} {required_ratio}:1 "
            f"({'PASS' if is_valid else 'FAIL'})"
        )

        return is_valid

    def get_gov_uk_color(self, color_name: str) -> str:
        """
        Get hex code for GOV.UK Design System color.

        Args:
            color_name: Color name (primary_blue, black, yellow, etc.)

        Returns:
            Hex color code

        Raises:
            ValueError: If color name not found
        """
        if color_name not in self.GOV_UK_COLORS:
            raise ValueError(
                f"Color '{color_name}' not found. "
                f"Available colors: {list(self.GOV_UK_COLORS.keys())}"
            )

        return self.GOV_UK_COLORS[color_name]

    def suggest_accessible_color(self, background: str, target_ratio: float = 7.0) -> dict:
        """
        Suggest accessible foreground colors for given background.

        Args:
            background: Background hex color
            target_ratio: Target contrast ratio (default 7.0 for AAA)

        Returns:
            Dict with suggested colors and their contrast ratios

        Logs:
            - INFO: Suggested colors
        """
        suggestions = {}

        # Test GOV.UK colors
        for color_name, hex_color in self.GOV_UK_COLORS.items():
            contrast = self.calculate_contrast_ratio(hex_color, background)

            if contrast >= target_ratio:
                suggestions[color_name] = {
                    "hex": hex_color,
                    "contrast": round(contrast, 2),
                    "meets_aaa": True,
                }

        print(
            f"[WCAGColorValidator] Found {len(suggestions)} accessible colors for background {background}"
        )

        return suggestions


# Convenience functions
def validate_text_contrast(foreground: str, background: str, large_text: bool = False) -> bool:
    """
    Validate text contrast ratio.

    Args:
        foreground: Foreground hex color
        background: Background hex color
        large_text: True if text is 18pt+ (or 14pt+ bold)

    Returns:
        True if contrast meets WCAG 2.1 AAA requirements
    """
    validator = WCAGColorValidator()
    return validator.validate_text_contrast(foreground, background, large_text)


def calculate_contrast_ratio(color1: str, color2: str) -> float:
    """
    Calculate contrast ratio between two colors.

    Args:
        color1: First hex color
        color2: Second hex color

    Returns:
        Contrast ratio (1:1 to 21:1)
    """
    validator = WCAGColorValidator()
    return validator.calculate_contrast_ratio(color1, color2)
