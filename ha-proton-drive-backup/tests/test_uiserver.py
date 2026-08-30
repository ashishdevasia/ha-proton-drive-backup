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


async def test_upload_to_proton_task_passes_slug_and_signals():
    import asyncio
    ui = UiServer.__new__(UiServer)
    ui._upload_event = asyncio.Event()

    class Coord:
        def __init__(self):
            self.slug = None

        async def uploadToProton(self, slug):
            self.slug = slug
    ui._coord = Coord()

    await ui._doUploadToProton("abc123")
    assert ui._coord.slug == "abc123"
    assert ui._upload_event.is_set()


async def test_upload_to_proton_task_swallows_errors():
    # Fire-and-forget task: a mid-transfer failure must be logged, not raised
    # as an unretrieved task exception.
    import asyncio
    ui = UiServer.__new__(UiServer)
    ui._upload_event = asyncio.Event()

    class Backup:
        def overrideStatus(self, fmt, *args):
            pass

    class Coord:
        def __init__(self):
            self.called = False

        async def uploadToProton(self, slug):
            self.called = True
            raise PleaseWait()

        def getBackup(self, slug):
            return Backup()
    ui._coord = Coord()

    await ui._doUploadToProton("abc123")  # must complete without raising
    assert ui._coord.called is True
    assert ui._upload_event.is_set()


async def test_upload_to_proton_task_marks_backup_on_failure():
    # A mid-transfer failure must leave a visible trace on the card:
    # ProtonSource.save's finally clears the transient status, so the task
    # sets an override afterwards.
    import asyncio
    ui = UiServer.__new__(UiServer)
    ui._upload_event = asyncio.Event()

    class Backup:
        def __init__(self):
            self.status = None

        def overrideStatus(self, fmt, *args):
            self.status = fmt
    backup = Backup()

    class Coord:
        async def uploadToProton(self, slug):
            raise RuntimeError("boom")

        def getBackup(self, slug):
            return backup
    ui._coord = Coord()

    await ui._doUploadToProton("abc123")
    assert backup.status == "Upload to Proton Drive failed"
    assert ui._upload_event.is_set()


def _status_ui(error, sources=("HomeAssistant",), backup_exists=True):
    import asyncio
    ui = UiServer.__new__(UiServer)
    ui._upload_event = asyncio.Event()

    class Backup:
        def __init__(self):
            self.status = None

        def overrideStatus(self, fmt, *args):
            self.status = fmt

        def getSource(self, name):
            return object() if name in sources else None

    class Coord:
        def __init__(self):
            self.backup = Backup()

        async def uploadToProton(self, slug):
            raise error

        def getBackup(self, slug):
            from backup.exceptions import NoBackup
            if not backup_exists:
                raise NoBackup()
            return self.backup
    ui._coord = Coord()
    return ui


async def test_upload_to_proton_pleasewait_marks_didnt_start():
    # A sync stealing the lock before the task runs means no transfer was
    # attempted — the card must not claim one "failed".
    ui = _status_ui(PleaseWait())
    await ui._doUploadToProton("abc123")
    assert ui._coord.backup.status == "Upload to Proton Drive didn't start — try again"


async def test_upload_to_proton_resolved_race_leaves_no_status():
    # The in-task re-check finding the backup already in Proton (a racing
    # sync uploaded it) is a resolved situation, not a failure.
    from backup.exceptions import LogicError
    ui = _status_ui(LogicError("This backup is already in Proton Drive"),
                    sources=("HomeAssistant", "ProtonDrive"))
    await ui._doUploadToProton("abc123")
    assert ui._coord.backup.status is None


async def test_upload_to_proton_midtransfer_logicerror_marks_failed():
    # LogicError isn't only raised by the precondition re-check — the CLI's
    # list parser and the staging stream raise it too.  When the backup is
    # still HA-only, the transfer genuinely failed and the card must say so.
    from backup.exceptions import LogicError
    ui = _status_ui(LogicError("Unexpected CLI list output"), sources=("HomeAssistant",))
    await ui._doUploadToProton("abc123")
    assert ui._coord.backup.status == "Upload to Proton Drive failed"


async def test_upload_to_proton_nobackup_after_delete_is_quiet():
    # Backup deleted mid-flight: NoBackup from the task, and the backup can't
    # be marked because it no longer exists — must complete without raising.
    from backup.exceptions import NoBackup
    ui = _status_ui(NoBackup(), backup_exists=False)
    await ui._doUploadToProton("abc123")
    assert ui._upload_event.is_set()


async def test_download_to_ha_task_swallows_errors():
    # The older /upload task gets the same hygiene: a failure is logged, not
    # left as an unretrieved task exception.
    import asyncio
    ui = UiServer.__new__(UiServer)
    ui._upload_event = asyncio.Event()

    class Coord:
        def __init__(self):
            self.called = False

        async def uploadBackups(self, slug):
            self.called = True
            raise PleaseWait()
    ui._coord = Coord()

    await ui._doUpload("abc123")  # must complete without raising
    assert ui._coord.called is True
    assert ui._upload_event.is_set()


class _Request:
    def __init__(self, **query):
        self.query = query


async def test_upload_to_proton_handler_fails_fast_on_preflight():
    # Pre-flight errors must escape the handler (into the error middleware the
    # UI understands) instead of dying inside a background task.
    ui = UiServer.__new__(UiServer)

    class Coord:
        def checkUploadToProton(self, slug):
            raise PleaseWait()
    ui._coord = Coord()

    with pytest.raises(PleaseWait):
        await ui.uploadToProton(_Request(slug="abc123"))


async def test_upload_to_proton_handler_backgrounds_after_preflight():
    import asyncio
    ui = UiServer.__new__(UiServer)
    ui._upload_event = asyncio.Event()
    ui._background_tasks = set()

    class Coord:
        def __init__(self):
            self.checked = None
            self.uploaded = None

        def checkUploadToProton(self, slug):
            self.checked = slug

        async def uploadToProton(self, slug):
            self.uploaded = slug
    ui._coord = Coord()

    resp = await ui.uploadToProton(_Request(slug="abc123"))
    assert ui._coord.checked == "abc123"
    assert json.loads(resp.text)["message"]
    await ui._upload_event.wait()  # background task ran to completion
    assert ui._coord.uploaded == "abc123"


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
