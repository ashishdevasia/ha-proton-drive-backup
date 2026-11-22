import re
from os.path import dirname, join

import jinja2
import pytest

from backup.config import Config, Setting
from backup.theme import isLight, luminance, themeContext
from backup.ui.uiserver import UiServer

STATIC = join(dirname(dirname(__file__)), "backup", "static")


@pytest.mark.parametrize("color, light", [
    ("#0b1020", False),   # the default background
    ("#1a5fb4", False),   # the default accent
    ("#000000", False),
    ("#ffffff", True),
    ("#fafafa", True),    # Home Assistant's light theme
    ("#ead9c5", True),    # the beige from issue #26
    ("#e0b030", True),    # ... and its yellow accent
    ("#FFEB3B", True),    # upper-case hex is valid too
    ("#757575", False),   # either side of where black and white text tie
    ("#777777", True),
])
def test_is_light(color, light):
    assert isLight(color) is light


@pytest.mark.parametrize("color", ["", None, "#fff", "ffffff", "white", "#ffffff; x", "#gggggg"])
def test_empty_or_malformed_colors_count_as_dark(color):
    # Empty is the settings' default (a dark built-in colour). A malformed
    # value must not break the page that would let the user fix it.
    assert isLight(color) is False


def test_trailing_newline_is_judged_like_the_color_itself():
    # RegexValidator matches with `$`, which accepts "#ffffff\n" (a YAML block
    # scalar gives one), and the browser reads that as plain white.
    assert isLight("#ffffff\n") is True
    assert isLight("#0b1020\n") is False


def test_luminance_endpoints():
    assert luminance("#000000") == 0
    assert luminance("#ffffff") == pytest.approx(1)


def test_theme_context_judges_each_color_on_its_own():
    assert themeContext("#ead9c5", "#1a5fb4") == {'lightTheme': True, 'darkOnAccent': False}
    assert themeContext("", "#e0b030") == {'lightTheme': False, 'darkOnAccent': True}
    assert themeContext("", "") == {'lightTheme': False, 'darkOnAccent': False}


class _Coordinator:
    def enabled(self):
        return True


def _context(**overrides):
    ui = UiServer.__new__(UiServer)
    ui.config = Config()
    for key, value in overrides.items():
        ui.config.override(Setting(key), value)
    ui._coord = _Coordinator()
    return ui.base_context()


def _render(context):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(STATIC), autoescape=True)
    return env.get_template("index.jinja2").render(**context)


def test_index_defaults_to_the_dark_theme():
    html = _render(_context())
    assert '<html lang="en">' in html
    assert '<meta name="color-scheme" content="dark">' in html
    assert "--user-on-accent: #fff;" in html


def test_index_switches_to_the_light_theme_for_a_light_background():
    html = _render(_context(background_color="#ead9c5"))
    assert '<html lang="en" data-theme="light">' in html
    assert '<meta name="color-scheme" content="light">' in html
    assert "--user-bg: #ead9c5;" in html
    # The accent is still the dark default, so text on it stays white.
    assert "--user-on-accent: #fff;" in html


def test_index_puts_dark_text_on_a_light_accent():
    html = _render(_context(accent_color="#e0b030"))
    assert '<html lang="en">' in html
    assert "--user-on-accent: #141826;" in html


def _css_variables(selector):
    with open(join(STATIC, "app", "app.css"), encoding="utf-8") as f:
        css = f.read()
    start = css.index(selector + " {")
    declarations = {}
    for line in css[start:css.index("\n}", start)].splitlines():
        if line.strip().startswith("--"):
            name, value = line.strip().rstrip(";").split(":", 1)
            declarations[name] = value.strip()
    return declarations


def test_light_palette_overrides_every_color_the_dark_one_hard_codes():
    # A colour the light block forgets keeps its dark-theme value, which is
    # how light-on-light text comes back. Colours taken from another variable
    # (the user's accent and background) follow the user instead.
    dark = _css_variables(":root")
    light = _css_variables(':root[data-theme="light"]')
    hard_coded = {name for name, value in dark.items()
                  if re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", value) and "var(" not in value}
    assert len(hard_coded) > 15
    assert hard_coded - set(light) == set()
    # ... and the light block defines nothing :root doesn't know (a typo).
    assert set(light) - set(dark) == set()


def _contrast(a, b):
    lighter, darker = sorted((luminance(a), luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_each_palette_has_text_that_contrasts_with_its_background():
    # WCAG AA (4.5:1) against the default dark background and against white.
    dark = _css_variables(":root")
    light = _css_variables(':root[data-theme="light"]')
    for name in ("--text", "--text-dim", "--text-faint", "--ok", "--warn", "--bad", "--info", "--ha"):
        assert _contrast(dark[name], "#0b1020") >= 4.5, name
        assert _contrast(light[name], "#ffffff") >= 4.5, name
