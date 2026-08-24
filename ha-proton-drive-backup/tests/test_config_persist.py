"""
Regression tests for the options written back to Supervisor.

Supervisor validates the whole `addons/self/options` payload against the
add-on's config.json schema and rejects the entire update if it contains a key
the add-on doesn't declare.  Config.validate() legitimately produces some
internal-only Settings (notably the vestigial ``max_backups_in_google_drive``
forced in by Config.ALWAYS_KEEP), so HaRequests.updateConfig must strip anything
not in the schema before sending it.  If it doesn't, saving any setting from the
UI fails on a real Home Assistant install.
"""
from yarl import URL

from backup.config import Config, ADDON_OPTION_KEYS, Setting, _LOOKUP
from backup.ha.harequests import HaRequests


def test_addon_schema_keys_all_map_to_settings():
    # Every option declared in config.json must resolve to a Setting, otherwise
    # settings.py blows up at import building validators.  Guards typos.
    for key in ADDON_OPTION_KEYS:
        assert key in _LOOKUP, "config.json declares unknown option: " + key


def test_validate_emits_internal_key_not_in_schema():
    # Documents the trap the filter exists to defend against: validate() really
    # does produce a key Supervisor would reject.
    validated, _ = Config().validate({"days_between_backups": 5})
    update = {k.key(): validated[k] for k in validated}
    assert "max_backups_in_google_drive" in update
    assert "max_backups_in_google_drive" not in ADDON_OPTION_KEYS


async def test_updateconfig_strips_non_schema_keys():
    req = HaRequests.__new__(HaRequests)
    captured = {}

    async def fake_post(url, data, **kwargs):
        captured["url"] = url
        captured["data"] = data

    req._postHassioData = fake_post
    req.getSupervisorURL = lambda: URL("http://supervisor")

    await req.updateConfig({
        "max_backups_in_ha": 5,             # declared option -> kept
        "max_backups_in_google_drive": 4,   # vestigial internal -> dropped
        "drive_url": "https://example",     # internal endpoint -> dropped
    })

    sent = captured["data"]["options"]
    assert sent == {"max_backups_in_ha": 5}
    assert set(sent).issubset(ADDON_OPTION_KEYS)


async def test_full_validated_config_is_supervisor_safe():
    # The realistic UI save path: take everything validate() would persist and
    # confirm that, once filtered, the payload only contains declared options.
    req = HaRequests.__new__(HaRequests)
    captured = {}

    async def fake_post(url, data, **kwargs):
        captured["data"] = data

    req._postHassioData = fake_post
    req.getSupervisorURL = lambda: URL("http://supervisor")

    validated, _ = Config().validate({
        "days_between_backups": 2,
        "max_backups_in_ha": 6,
        "max_backups_in_proton_drive": 6,
        "proton_folder_name": "backups/My Backups",
    })
    update = {k.key(): validated[k] for k in validated}
    await req.updateConfig(update)

    assert set(captured["data"]["options"]).issubset(ADDON_OPTION_KEYS)
