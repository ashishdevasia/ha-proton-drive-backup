"""Picks the web UI's palette from the colours the user configured.

Imports nothing from the add-on, so devserver.py can use it without the
add-on's dependencies.
"""
import re

_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")

# The WCAG relative luminance at which black and white text contrast equally.
# Above it, dark text is the more readable of the two.
_LIGHT_ABOVE = 0.179


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    """WCAG relative luminance of a #RRGGBB colour: 0 is black, 1 is white."""
    red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _linear(red) + 0.7152 * _linear(green) + 0.0722 * _linear(blue)


def isLight(color) -> bool:
    """True when dark text reads better than light text on this colour.

    An empty value (the settings' default) or a malformed one counts as dark,
    which is what the built-in default colours are.
    """
    # The settings' validator lets a trailing newline through.
    color = str(color or "").strip()
    if not _HEX_COLOR.fullmatch(color):
        return False
    return luminance(color) > _LIGHT_ABOVE


def themeContext(background, accent) -> dict:
    """What index.jinja2 needs to know about the two configured colours."""
    return {
        'lightTheme': isLight(background),
        'darkOnAccent': isLight(accent),
    }
