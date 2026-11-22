"""Translations ship in two places, one file per language each:

- translations/<lang>.yaml: names and descriptions for the add-on's
  Configuration tab in Home Assistant (keyed by config.json's schema).
- backup/static/app/locales/<lang>.json: the web UI's strings (keyed by the
  t("…") calls in app.js), English being the reference.

Both must cover everything, in every language listed in i18n.js's SUPPORTED.
"""
import ast
import json
import re
from pathlib import Path

import pytest
import yaml

ADDON = Path(__file__).resolve().parent.parent
APP = ADDON / "backup" / "static" / "app"
LOCALES = APP / "locales"
HA_TRANSLATIONS = ADDON / "translations"
PLURAL_FORMS = {"zero", "one", "two", "few", "many", "other"}


def _read(path):
    return path.read_text(encoding="utf-8")


def _config():
    return json.loads(_read(ADDON / "config.json"))


def _supported():
    block = re.search(r"var SUPPORTED = \{(.*?)\};", _read(APP / "i18n.js"), re.S).group(1)
    return sorted(re.findall(r'"?([A-Za-z][\w-]*)"?\s*:\s*"', block))


def _catalog(lang):
    return json.loads(_read(LOCALES / (lang + ".json")))


def _ha(lang):
    return yaml.safe_load(_read(HA_TRANSLATIONS / (lang + ".yaml")))


def _placeholders(value):
    texts = value.values() if isinstance(value, dict) else [value]
    return {name for text in texts for name in re.findall(r"\{(\w+)\}", text)}


LANGS = _supported()


def test_every_language_ships_both_files():
    assert "en" in LANGS
    assert sorted(p.stem for p in LOCALES.glob("*.json")) == LANGS
    assert sorted(p.stem for p in HA_TRANSLATIONS.glob("*.yaml")) == LANGS


def test_index_loads_i18n_before_the_app():
    page = _read(ADDON / "backup" / "static" / "index.jinja2")
    assert 0 <= page.index("app/i18n.js") < page.index("app/app.js")


# --- Configuration tab --------------------------------------------------------

@pytest.mark.parametrize("lang", LANGS)
def test_configuration_tab_covers_every_option(lang):
    config = _config()
    data = _ha(lang)
    assert set(data) <= {"configuration", "network"}
    # A new option without a translation would show its raw key again.
    assert set(data["configuration"]) == set(config["schema"])
    for key, entry in data["configuration"].items():
        assert set(entry) <= {"name", "description", "fields"}, key
        assert isinstance(entry["name"], str) and entry["name"].strip(), key
        assert entry.get("description") is None or entry["description"].strip(), key
    assert set(data.get("network") or {}) <= set(config["ports"])


# --- Web UI catalogs ----------------------------------------------------------

@pytest.mark.parametrize("lang", LANGS)
def test_catalog_matches_english(lang):
    en, catalog = _catalog("en"), _catalog(lang)
    assert sorted(set(en) - set(catalog)) == [], "missing in " + lang
    assert sorted(set(catalog) - set(en)) == [], "not in en.json"
    for key, value in en.items():
        assert isinstance(catalog[key], dict) == isinstance(value, dict), key + ": plural in one language only"
        assert _placeholders(catalog[key]) == _placeholders(value), key + ": different {placeholders}"


@pytest.mark.parametrize("lang", LANGS)
def test_catalog_values_are_well_formed(lang):
    for key, value in _catalog(lang).items():
        forms = value if isinstance(value, dict) else {"other": value}
        assert "other" in forms and set(forms) <= PLURAL_FORMS, key
        for text in forms.values():
            assert isinstance(text, str) and text.strip(), key
            tags = set(re.findall(r"<[^>]*>", text))
            # Only *_html keys are rendered as HTML (tHtml, which escapes the
            # parameters); everywhere else markup would show up literally.
            assert tags <= ({"<b>", "</b>"} if key.endswith("_html") else set()), key


# --- Keys used by the code ----------------------------------------------------

def _app():
    return _read(APP / "app.js")


def _settings_fields():
    return re.findall(r'\{ key: "(\w+)"', _app())


def _settings_groups():
    return re.findall(r'^\s+id: "(\w+)", icon:', _app(), re.M)


def _tabs():
    return re.findall(r'\{ id: "(\w+)", icon:', _app())


def _literal_keys():
    """Every quoted "area.name" string in app.js whose area is a catalog area."""
    areas = sorted({key.split(".")[0] for key in _catalog("en")})
    pattern = r"""["']((?:%s)\.[a-z0-9_.]*[a-z0-9_])["']""" % "|".join(areas)
    return set(re.findall(pattern, _app()))


def _error_codes():
    codes = set(re.findall(r'^\w+ = "([a-z_]+)"$', _read(ADDON / "backup" / "const.py"), re.M))
    for module in ("backup/exceptions/exceptions.py", "backup/proton/exceptions.py"):
        codes |= set(re.findall(r'def code\(self\):\s*return "([a-z_]+)"', _read(ADDON / module)))
    return codes


def test_every_key_the_app_uses_exists():
    en = _catalog("en")
    assert sorted(k for k in _literal_keys() if k not in en) == []


def test_settings_tabs_and_groups_have_text():
    en = _catalog("en")
    fields, groups, tabs = _settings_fields(), _settings_groups(), _tabs()
    assert fields and groups and tabs
    assert set(fields) <= set(_config()["schema"]), "SETTINGS_GROUPS has a key config.json doesn't"
    assert [k for k in fields if "setting.%s.label" % k not in en] == []
    assert [g for g in groups if "settings.group.%s.title" % g not in en] == []
    assert [t for t in tabs if "tab." + t not in en] == []


def test_setting_text_stays_in_the_settings_form():
    # setting.<option>.* describe one field of the settings form, which builds
    # these keys from the option name. Other text that reads the same in
    # English needs its own key, because translations differ by context: the
    # "Keep in Home Assistant" count setting and the create dialog's per-backup
    # "Keep in Home Assistant" checkbox are worded differently in fr and ml.
    assert sorted(k for k in _literal_keys() if k.startswith("setting.")) == []


def test_no_unused_keys():
    # Keys app.js builds at runtime: setting.<key>.*, settings.group.<id>.*,
    # tab.<id>, error.<error_type>.*, backups.type.<type>.
    fields, groups, tabs = set(_settings_fields()), set(_settings_groups()), set(_tabs())
    codes = _error_codes() | {"generic"}
    used = _literal_keys()

    def referenced(key):
        if key in used:
            return True
        parts = key.split(".")
        if parts[0] == "setting":
            return parts[1] in fields and parts[2] in ("label", "help", "placeholder")
        if parts[:2] == ["settings", "group"]:
            return parts[2] in groups and parts[3] in ("title", "desc")
        if parts[0] == "tab":
            return parts[1] in tabs
        if parts[0] == "error" and len(parts) == 3:
            return parts[1] in codes and parts[2] in ("title", "message")
        if parts[:2] == ["backups", "type"]:
            return parts[2] in ("full", "partial")
        return False

    assert sorted(k for k in _catalog("en") if not referenced(k)) == []


def test_error_ids_are_backend_error_codes():
    codes = _error_codes() | {"generic"}
    ids = {key.split(".")[1] for key in _catalog("en") if key.startswith("error.") and key.count(".") == 2}
    assert sorted(ids - codes) == []


def _backend_statuses():
    """Every status the backend can give a backup: what the status() methods
    return and what overrideStatus / _markBackupStatus set. Returns the fixed
    strings, the format strings ("Loading {0}%"), and any call this can't read
    (a status that isn't a string literal)."""
    fixed, formats, unreadable = set(), set(), []
    for path in sorted((ADDON / "backup").rglob("*.py")):
        for func in ast.walk(ast.parse(_read(path))):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if func.name == "status" and isinstance(node, ast.Return):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        fixed.add(node.value.value)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr in ("overrideStatus", "_markBackupStatus"):
                    arg = node.args[0 if node.func.attr == "overrideStatus" else 1]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        (formats if "{0}" in arg.value else fixed).add(arg.value)
                    elif func.name != "_markBackupStatus":  # it passes its own argument on
                        unreadable.append("%s:%d" % (path.relative_to(ADDON), node.lineno))
    return fixed, formats, unreadable


def test_every_backend_status_is_translated():
    # app.js maps the backend's English status strings to catalog keys
    # (STATUS_KEYS, plus a pattern for the "Loading N%" kind); an unmapped
    # status would show in English in every language.
    app = _app()
    block = re.search(r"var STATUS_KEYS = \{(.*?)\};", app, re.S).group(1)
    mapped = set(re.findall(r'^\s*"([^"]+)":', block, re.M))
    progress = re.compile(re.search(r"var m = /(.+?)/\.exec\(status\)", app).group(1))
    fixed, formats, unreadable = _backend_statuses()
    assert fixed and formats and mapped
    assert unreadable == [], "statuses this test can't read; give them as string literals"
    assert sorted(s for s in fixed if s not in mapped and not progress.match(s)) == []
    assert sorted(f for f in formats if not progress.match(f.replace("{0}", "42"))) == []
    assert sorted(mapped - fixed) == [], "STATUS_KEYS maps a status the backend never sets"


def test_fixed_error_messages_are_translated():
    # An error whose message() is a fixed string can be translated, and needs
    # error.<code>.message, or it shows in English under a translated title.
    # Error classes nothing raises (Google Drive leftovers) don't count.
    consts = {n.targets[0].id: n.value.value for n in ast.parse(_read(ADDON / "backup" / "const.py")).body
              if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)}
    modules = [ADDON / "backup" / "exceptions" / "exceptions.py", ADDON / "backup" / "proton" / "exceptions.py"]
    code_text = "\n".join(_read(path) for path in sorted((ADDON / "backup").rglob("*.py"))
                          if path not in modules and path.name != "__init__.py")
    en, missing = _catalog("en"), []
    for module in modules:
        for cls in ast.walk(ast.parse(_read(module))):
            if not isinstance(cls, ast.ClassDef) or not re.search(r"\b%s\b" % cls.name, code_text):
                continue
            methods = {f.name: f for f in cls.body if isinstance(f, ast.FunctionDef)}
            returns = {name: next((r.value for r in ast.walk(f) if isinstance(r, ast.Return)), None)
                       for name, f in methods.items()}
            message, code = returns.get("message"), returns.get("code")
            if not (isinstance(message, ast.Constant) and isinstance(message.value, str)) or code is None:
                continue
            code = code.value if isinstance(code, ast.Constant) else consts[code.id]
            if "error.%s.message" % code not in en:
                missing.append("%s (%s)" % (code, cls.name))
    assert sorted(missing) == []


def test_every_folder_is_translated():
    # The settings form shows backup/const.py's FOLDERS by slug (FOLDER_TEXT).
    folders = next(ast.literal_eval(n.value) for n in ast.parse(_read(ADDON / "backup" / "const.py")).body
                   if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "FOLDERS")
    block = re.search(r"var FOLDER_TEXT = \{(.*?)\};", _app(), re.S).group(1)
    mapped = set(re.findall(r'^\s*"([^"]+)":', block, re.M))
    assert sorted(f["slug"] for f in folders) == sorted(mapped)
