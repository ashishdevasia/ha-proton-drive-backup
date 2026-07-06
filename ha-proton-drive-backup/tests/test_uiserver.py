import json

import pytest

from backup.ui.uiserver import UiServer
from backup.exceptions import PleaseWait
from backup.proton.exceptions import ProtonCliMissing, ProtonConnectionError


async def test_background_sync_swallows_pleasewait():
    # A detached "sync now" task that hits a sync-already-running condition must
    # not raise (which would log "Task exception was never retrieved").
    ui = UiServer.__new__(UiServer)

    class Coord:
        async def sync(self):
            raise PleaseWait()
    ui._coord = Coord()

    await ui._backgroundSync()  # must complete without raising


async def test_background_sync_swallows_other_errors():
    ui = UiServer.__new__(UiServer)

    class Coord:
        async def sync(self):
            raise RuntimeError("boom")
    ui._coord = Coord()

    await ui._backgroundSync()  # logged, not raised


def make_logout_ui(proton):
    ui = UiServer.__new__(UiServer)

    class Coord:
        def __init__(self):
            self.triggered = False

        def trigger(self):
            self.triggered = True
    ui._proton = proton
    ui._coord = Coord()
    return ui


async def test_protonlogout_signs_out_and_triggers_sync():
    class Proton:
        def __init__(self):
            self.signed_out = False

        async def signOut(self):
            self.signed_out = True
    proton = Proton()
    ui = make_logout_ui(proton)
    resp = await ui.protonlogout(None)
    assert json.loads(resp.text)["ok"] is True
    assert proton.signed_out is True
    assert ui._coord.triggered is True


async def test_protonlogout_reports_known_errors():
    class Proton:
        async def signOut(self):
            raise ProtonCliMissing("/bin/nope")
    ui = make_logout_ui(Proton())
    resp = await ui.protonlogout(None)
    data = json.loads(resp.text)
    assert data["ok"] is False
    assert data["message"]
    assert ui._coord.triggered is False


async def test_protonlogout_offline_message_is_specific():
    class Proton:
        async def signOut(self):
            raise ProtonConnectionError("offline")
    ui = make_logout_ui(Proton())
    data = json.loads((await ui.protonlogout(None)).text)
    assert data["ok"] is False
    assert "sign out" in data["message"].lower()
    # Not the generic "will keep retrying automatically" transient message.
    assert "retrying" not in data["message"].lower()


def make_warning_ui(**overrides):
    from backup.config import Config, Setting
    ui = UiServer.__new__(UiServer)
    config = Config()
    for key, value in overrides.items():
        config.override(Setting(key), value)
    ui.config = config
    return ui


def test_generational_cap_warning_fires_when_max_is_too_small():
    # The user-reported setup: plan wants 7 slots (days 0->1 + 2+2+2), max is 4.
    ui = make_warning_ui(generational_days=0, generational_weeks=2,
                         generational_months=2, generational_years=2)
    warning = ui._generationalCapWarning()
    assert "up to 7 backups" in warning
    assert "Home Assistant" in warning
    assert "Proton Drive" in warning


def test_generational_cap_warning_silent_when_max_fits():
    ui = make_warning_ui(generational_days=0, generational_weeks=2,
                         generational_months=2, generational_years=2,
                         max_backups_in_ha=8, max_backups_in_proton_drive=8)
    assert ui._generationalCapWarning() is None


def test_generational_cap_warning_ignores_never_delete():
    # 0 means "never delete", so it can't conflict with the plan.
    ui = make_warning_ui(generational_days=0, generational_weeks=2,
                         generational_months=2, generational_years=2,
                         max_backups_in_ha=0, max_backups_in_proton_drive=8)
    assert ui._generationalCapWarning() is None


def test_generational_cap_warning_silent_without_generational():
    ui = make_warning_ui(max_backups_in_ha=1)
    assert ui._generationalCapWarning() is None


def test_generational_cap_warning_skips_ha_when_delete_after_upload():
    # The HA cap never applies under delete-after-upload, so it can't conflict.
    ui = make_warning_ui(generational_days=0, generational_weeks=2,
                         generational_months=2, generational_years=2,
                         delete_after_upload=True, max_backups_in_proton_drive=8)
    assert ui._generationalCapWarning() is None
    # The Proton cap still warns on its own.
    ui = make_warning_ui(generational_days=0, generational_weeks=2,
                         generational_months=2, generational_years=2,
                         delete_after_upload=True)
    warning = ui._generationalCapWarning()
    assert "Proton Drive" in warning
    assert "Home Assistant" not in warning
