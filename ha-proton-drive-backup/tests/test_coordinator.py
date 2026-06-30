"""
Direct coverage for Coordinator.backupsPausedForProtonAuth() — the predicate
that drives the "backups paused, sign in to Proton" notification.  It is wired
against a real ProtonSource as the destination so the test exercises the actual
needsConfiguration() logic (upload-enabled + signed-out), not a stubbed boolean.
"""
from backup.config import Config, Setting
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
