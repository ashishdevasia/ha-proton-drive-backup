"""
The HA sensor the add-on publishes must not leak "google_drive" branding (this
is a Proton Drive add-on) and must expose the Proton counts/sizes instead.
"""
from datetime import datetime

from dateutil.tz import tzutc

import pytest

from backup.config import Config, Setting
from backup.const import SOURCE_HA, SOURCE_PROTON_DRIVE
from backup.ha.haupdater import (HaUpdater, NOTIFICATION_TITLE,
                                 PAUSED_NOTIFICATION_TITLE)
from backup.ha.harequests import NOTIFICATION_ID, PAUSED_NOTIFICATION_ID


class _Backup:
    def __init__(self, sources):
        self._sources = set(sources)

    def ignore(self):
        return False

    def date(self):
        return datetime(2026, 6, 27, 1, 2, 3, tzinfo=tzutc())

    def name(self):
        return "Nightly"

    def status(self):
        return "Backed Up"

    def sizeString(self):
        return "1.0 B"

    def sizeInt(self):
        return 1

    def slug(self):
        return "slug1"

    def getSource(self, name):
        return object() if name in self._sources else None


class _Coord:
    def backups(self):
        return [_Backup({SOURCE_HA, SOURCE_PROTON_DRIVE})]

    def buildBackupMetrics(self):
        return {SOURCE_PROTON_DRIVE: {"free_space": "5 GB"}}

    def nextBackupTime(self, include_pending=True):
        return datetime(2026, 6, 28, tzinfo=tzutc())


def _updater(snapshot_mode=False):
    u = HaUpdater.__new__(HaUpdater)
    u._coordinator = _Coord()
    cfg = Config()
    cfg.override(Setting.CALL_BACKUP_SNAPSHOT, snapshot_mode)
    u._config = cfg
    u._state = lambda: "backed_up"  # bypass staleness machinery
    return u


def test_backup_state_attributes_are_proton_branded():
    attr = _updater()._buildBackupUpdate()["attributes"]
    assert "backups_in_proton_drive" in attr
    assert "size_in_proton_drive" in attr
    assert "free_space_in_proton_drive" in attr
    assert attr["backups_in_proton_drive"] == 1
    assert attr["free_space_in_proton_drive"] == "5 GB"
    assert not any("google" in k for k in attr), attr


def test_snapshot_mode_attributes_are_proton_branded():
    attr = _updater(snapshot_mode=True)._buildBackupUpdate()["attributes"]
    assert "snapshots_in_proton_drive" in attr
    assert "size_in_proton_drive" in attr
    assert not any("google" in k for k in attr), attr


def test_notification_title_not_google_branded():
    assert "Google" not in NOTIFICATION_TITLE
    assert "Proton" in NOTIFICATION_TITLE


class _FakeRequests:
    def __init__(self):
        self.sent = []        # (title, message, notification_id)
        self.dismissed = []   # notification_id

    async def sendNotification(self, title, message, notification_id=NOTIFICATION_ID):
        self.sent.append((title, message, notification_id))

    async def dismissNotification(self, notification_id=NOTIFICATION_ID):
        self.dismissed.append(notification_id)


class _FakeInfo:
    url = ""


def _notify_updater(paused=False, stale=False):
    u = HaUpdater.__new__(HaUpdater)
    u._requests = _FakeRequests()
    u._info = _FakeInfo()
    u._notified = False
    u._paused_notified = False
    u._stale = lambda: stale
    u._coordinator = type("C", (), {"backupsPausedForProtonAuth": lambda self: paused})()
    return u


async def test_paused_raises_distinct_signin_notification():
    u = _notify_updater(paused=True)
    await u._updateNotifications()
    assert len(u._requests.sent) == 1
    title, _msg, nid = u._requests.sent[0]
    assert title == PAUSED_NOTIFICATION_TITLE
    assert nid == PAUSED_NOTIFICATION_ID
    assert u._paused_notified is True


async def test_paused_notification_includes_signin_link_when_url_known():
    u = _notify_updater(paused=True)
    u._info.url = "http://homeassistant.local:8123/addon"
    await u._updateNotifications()
    _title, message, _nid = u._requests.sent[0]
    assert "http://homeassistant.local:8123/addon" in message


async def test_paused_notification_is_not_resent_each_cycle():
    u = _notify_updater(paused=True)
    await u._updateNotifications()
    await u._updateNotifications()
    assert len(u._requests.sent) == 1


async def test_paused_notification_dismissed_on_recovery():
    u = _notify_updater(paused=True)
    await u._updateNotifications()
    u._coordinator = type("C", (), {"backupsPausedForProtonAuth": lambda self: False})()
    await u._updateNotifications()
    assert PAUSED_NOTIFICATION_ID in u._requests.dismissed
    assert u._paused_notified is False


async def test_paused_takes_precedence_over_generic_stale():
    # When both conditions hold, only the actionable paused notification is shown,
    # and any lingering generic one is dismissed.
    u = _notify_updater(paused=True, stale=True)
    u._notified = True  # a generic "having trouble" notification was already up
    await u._updateNotifications()
    assert NOTIFICATION_ID in u._requests.dismissed
    assert u._notified is False
    assert [s[2] for s in u._requests.sent] == [PAUSED_NOTIFICATION_ID]


async def test_generic_stale_still_fires_when_not_paused():
    u = _notify_updater(paused=False, stale=True)
    await u._updateNotifications()
    assert len(u._requests.sent) == 1
    assert u._requests.sent[0][2] == NOTIFICATION_ID
    assert u._notified is True
