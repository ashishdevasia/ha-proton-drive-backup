import pytest

from backup.ui.uiserver import UiServer
from backup.exceptions import PleaseWait


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
