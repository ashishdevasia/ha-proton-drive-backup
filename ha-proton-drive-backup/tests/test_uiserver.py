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
