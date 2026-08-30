"""
Direct coverage for Coordinator.backupsPausedForProtonAuth() — the predicate
that drives the "backups paused, sign in to Proton" notification.  It is wired
against a real ProtonSource as the destination so the test exercises the actual
needsConfiguration() logic (upload-enabled + signed-out), not a stubbed boolean.
"""
import pytest

from backup.config import Config, Setting
from backup.exceptions import LogicError, NoBackup, PleaseWait
from backup.model.coordinator import Coordinator
from backup.proton.protonsource import ProtonSource
from backup.time import Time

from tests.fakes import FakeProtonCli, FakeInfo


def _proton_dest(tmp_path, authed, upload=True):
    cfg = Config()
    cfg.override(Setting.PROTON_DATA_PATH, str(tmp_path / "proton"))
    cfg.override(Setting.ENABLE_PROTON_UPLOAD, upload)
    return ProtonSource(cfg, Time(), FakeProtonCli(authenticated=authed), FakeInfo())


class _Info:
    def __init__(self, first_sync):
        self._first_sync = first_sync


class _Model:
    def __init__(self, dest):
        self.dest = dest


def _coord(dest, first_sync):
    c = Coordinator.__new__(Coordinator)
    c._global_info = _Info(first_sync)
    c._model = _Model(dest)
    return c


def test_paused_predicate_suppressed_during_first_sync(tmp_path):
    # Signed out and upload on would otherwise be "paused", but the very first
    # sync must not flap the notification before the session is even checked.
    dest = _proton_dest(tmp_path, authed=False)
    assert _coord(dest, first_sync=True).backupsPausedForProtonAuth() is False


def test_paused_predicate_true_when_signed_out_after_first_sync(tmp_path):
    dest = _proton_dest(tmp_path, authed=False)
    assert _coord(dest, first_sync=False).backupsPausedForProtonAuth() is True


def test_paused_predicate_false_when_signed_in(tmp_path):
    dest = _proton_dest(tmp_path, authed=True)
    assert _coord(dest, first_sync=False).backupsPausedForProtonAuth() is False


def test_paused_predicate_false_when_upload_disabled(tmp_path):
    # With Proton upload off, Proton isn't a required destination, so a missing
    # session is not a "paused" condition even when signed out.
    dest = _proton_dest(tmp_path, authed=False, upload=False)
    assert _coord(dest, first_sync=False).backupsPausedForProtonAuth() is False


# --- Manual HA -> Proton upload ---------------------------------------------

class _SourceCopy:
    """Stands in for an AbstractBackup held by a Backup's sources map."""

    def __init__(self, key, uploadable=True):
        self._key = key
        self._uploadable = uploadable

    def source(self):
        return self._key

    def uploadable(self):
        return self._uploadable


class _Endpoint:
    def __init__(self, name, enabled=True, upload=True, save_error=None):
        self._name = name
        self._enabled = enabled
        self._upload = upload
        self._save_error = save_error
        self.saved_backup = None
        self.saved_stream = None
        self.saved_retain = None
        self.retain_calls = 0

    def name(self):
        return self._name

    def enabled(self):
        return self._enabled

    def upload(self):
        return self._upload

    async def read(self, backup):
        return "stream:" + backup.slug()

    async def save(self, backup, stream):
        self.saved_backup = backup
        self.saved_stream = stream
        # Like the real ProtonSource.save: the retained flag is read from the
        # backup's options and baked into the uploaded copy in the same write.
        opts = backup.getOptions()
        self.saved_retain = bool(opts and opts.retain_sources.get(self._name, False))
        if self._save_error is not None:
            raise self._save_error
        return _SourceCopy(self._name)

    async def retain(self, backup, retain):
        self.retain_calls += 1


class _UploadModel:
    def __init__(self, backup, dest=None):
        self.source = _Endpoint("HomeAssistant")
        self.dest = dest or _Endpoint("ProtonDrive")
        self.backups = {backup.slug(): backup}

    def reinitialize(self, precache):
        pass

    def getNextPurges(self):
        return {}


class _FakeBackup:
    def __init__(self, slug, sources):
        from datetime import datetime
        self._slug = slug
        self._sources = dict(sources)
        self._options = None
        self._date = datetime(2026, 8, 30)

    def slug(self):
        return self._slug

    def date(self):
        return self._date

    def getSource(self, name):
        return self._sources.get(name)

    def addSource(self, source):
        # Mirrors the real Backup.addSource: keyed by the copy's own source().
        self._sources[source.source()] = source

    def getOptions(self):
        return self._options

    def setOptions(self, options):
        self._options = options


def _upload_coord(backup, dest=None, busy=False):
    c = Coordinator.__new__(Coordinator)
    c._precache = None
    c._busy = busy
    c._model = _UploadModel(backup, dest)
    return c


async def test_upload_to_proton_saves_and_pins_atomically(tmp_path):
    backup = _FakeBackup("slug1", {"HomeAssistant": _SourceCopy("HomeAssistant")})
    coord = _upload_coord(backup)
    await coord._uploadToProton("slug1")
    dest = coord._model.dest
    assert dest.saved_backup is backup
    assert dest.saved_stream == "stream:slug1"
    assert backup.getSource("ProtonDrive") is not None
    # The pin must ride along in the save itself (metadata written
    # retained=True in one upload), not as a separate retain() call that can
    # fail after the transfer succeeded.
    assert dest.saved_retain is True
    assert dest.retain_calls == 0


async def test_upload_to_proton_does_not_poison_shared_options_default(tmp_path):
    from backup.config import CreateOptions
    backup = _FakeBackup("slug1", {"HomeAssistant": _SourceCopy("HomeAssistant")})
    await _upload_coord(backup)._uploadToProton("slug1")
    # CreateOptions' retain_sources default is a shared dict; the upload must
    # not have added its pin to it, or every later backup would be pinned.
    assert CreateOptions(backup.date(), "").retain_sources == {}


async def test_upload_to_proton_rejects_existing_proton_copy(tmp_path):
    backup = _FakeBackup("slug1", {"HomeAssistant": _SourceCopy("HomeAssistant"),
                                   "ProtonDrive": _SourceCopy("ProtonDrive")})
    coord = _upload_coord(backup)
    with pytest.raises(LogicError):
        await coord._uploadToProton("slug1")
    assert coord._model.dest.saved_backup is None


async def test_upload_to_proton_requires_ha_copy(tmp_path):
    backup = _FakeBackup("slug1", {"ProtonDrive": _SourceCopy("ProtonDrive")})
    coord = _upload_coord(backup)
    with pytest.raises(NoBackup):
        await coord._uploadToProton("slug1")


async def test_upload_to_proton_rejects_pending_backup(tmp_path):
    backup = _FakeBackup("pending", {"HomeAssistant": _SourceCopy("HomeAssistant", uploadable=False)})
    coord = _upload_coord(backup)
    with pytest.raises(LogicError):
        await coord._uploadToProton("pending")


def test_check_upload_to_proton_pleasewait_when_busy(tmp_path):
    backup = _FakeBackup("slug1", {"HomeAssistant": _SourceCopy("HomeAssistant")})
    with pytest.raises(PleaseWait):
        _upload_coord(backup, busy=True).checkUploadToProton("slug1")


def test_check_upload_to_proton_requires_upload_enabled(tmp_path):
    backup = _FakeBackup("slug1", {"HomeAssistant": _SourceCopy("HomeAssistant")})
    coord = _upload_coord(backup, dest=_Endpoint("ProtonDrive", upload=False))
    with pytest.raises(LogicError):
        coord.checkUploadToProton("slug1")


def test_check_upload_to_proton_requires_auth(tmp_path):
    backup = _FakeBackup("slug1", {"HomeAssistant": _SourceCopy("HomeAssistant")})
    coord = _upload_coord(backup, dest=_Endpoint("ProtonDrive", enabled=False))
    with pytest.raises(LogicError):
        coord.checkUploadToProton("slug1")


def test_check_upload_to_proton_passes_when_valid(tmp_path):
    backup = _FakeBackup("slug1", {"HomeAssistant": _SourceCopy("HomeAssistant")})
    _upload_coord(backup).checkUploadToProton("slug1")  # must not raise


async def test_failed_upload_to_proton_rolls_back_pin_when_no_prior_options(tmp_path):
    backup = _FakeBackup("slug1", {"HomeAssistant": _SourceCopy("HomeAssistant")})
    coord = _upload_coord(backup, dest=_Endpoint("ProtonDrive", save_error=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        await coord._uploadToProton("slug1")
    # The pin must not survive a failed transfer: the next automatic sync
    # would upload the backup itself and bake retained=True into it.
    assert backup.getOptions() is None
    assert backup.getSource("ProtonDrive") is None


async def test_failed_upload_to_proton_restores_prior_retain_sources(tmp_path):
    from backup.config import CreateOptions
    backup = _FakeBackup("slug1", {"HomeAssistant": _SourceCopy("HomeAssistant")})
    original = {"HomeAssistant": True}
    backup.setOptions(CreateOptions(backup.date(), "", retain_sources=original))
    coord = _upload_coord(backup, dest=_Endpoint("ProtonDrive", save_error=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        await coord._uploadToProton("slug1")
    assert backup.getOptions().retain_sources == {"HomeAssistant": True}


async def test_cancelled_upload_to_proton_rolls_back_pin(tmp_path):
    # Cancellation (BaseException) must roll back too — an interrupted sync or
    # shutdown mid-transfer is a realistic path.
    import asyncio
    backup = _FakeBackup("slug1", {"HomeAssistant": _SourceCopy("HomeAssistant")})
    coord = _upload_coord(backup, dest=_Endpoint("ProtonDrive", save_error=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await coord._uploadToProton("slug1")
    assert backup.getOptions() is None
