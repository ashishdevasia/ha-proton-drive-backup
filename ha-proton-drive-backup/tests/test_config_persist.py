"""
Regression tests for the options written back to Supervisor.

Supervisor drops any key in the `addons/self/options` payload that the add-on's
config.json schema doesn't declare, and logs a warning for each one.
Config.validate() legitimately produces some internal-only Settings (those in
Config.NON_UI_SETTING, once they differ from their default), so
HaRequests.updateConfig strips anything not in the schema before sending it.
"""
import asyncio

import pytest
from yarl import URL

from backup.config import Config, ADDON_OPTION_KEYS, Setting, _LOOKUP
from backup.ha.harequests import HaRequests


def test_addon_schema_keys_all_map_to_settings():
    # Every option declared in config.json must resolve to a Setting, otherwise
    # settings.py blows up at import building validators.  Guards typos.
    for key in ADDON_OPTION_KEYS:
        assert key in _LOOKUP, "config.json declares unknown option: " + key


def test_validate_emits_internal_key_not_in_schema():
    # Documents what the filter is for: validate() really does produce a key
    # outside the schema.
    config = Config({Setting.NEW_BACKUP_TIMEOUT_SECONDS: 99})
    validated, _ = config.validate({"days_between_backups": 5})
    update = {k.key(): validated[k] for k in validated}
    assert update["new_backup_timeout_seconds"] == 99
    assert "new_backup_timeout_seconds" not in ADDON_OPTION_KEYS


def test_options_are_not_carried_forward():
    # validate() carries internal NON_UI_SETTINGs forward (no caller passes
    # them), but not options: every caller passes all of them, so a missing one
    # means its default. Carrying log_level / watch_backup_directory forward
    # undid web UI changes, including the second validate() in update() after
    # a save, so e.g. the watch couldn't be turned back on.
    config = Config({Setting.LOG_LEVEL: "INFO", Setting.WATCH_BACKUP_DIRECTORY: False,
                     Setting.NEW_BACKUP_TIMEOUT_SECONDS: 99})
    validated, _ = config.validate({"log_level": "TRACE", "watch_backup_directory": False})
    assert validated[Setting.LOG_LEVEL] == "TRACE"
    assert validated[Setting.WATCH_BACKUP_DIRECTORY] is False
    # Back to the defaults ("— default —", the checkbox on): both left out.
    validated, _ = config.validate({"days_between_backups": 5, "watch_backup_directory": True})
    assert Setting.LOG_LEVEL not in validated
    assert Setting.WATCH_BACKUP_DIRECTORY not in validated
    assert validated[Setting.NEW_BACKUP_TIMEOUT_SECONDS] == 99  # internal: carried
    # What a save does next (UiServer._updateConfiguration), and what Supervisor
    # gives back on the next refresh (HaSource._refreshInfo): still the defaults.
    config.update(validated)
    config.update({k.key(): v for k, v in validated.items() if k.key() in ADDON_OPTION_KEYS})
    assert config.get(Setting.LOG_LEVEL) == Setting.LOG_LEVEL.default()
    assert config.get(Setting.WATCH_BACKUP_DIRECTORY) is True
    assert config.get(Setting.NEW_BACKUP_TIMEOUT_SECONDS) == 99


def test_bare_number_duration_is_in_the_settings_unit():
    # The web UI sends text: "30" in "Delete ignored backups after" used to be
    # 30 seconds, so ignored backups were deleted almost at once, while the
    # Configuration tab's 30 meant 30 days.
    for value in ("30", " 30 ", 30, "30 days", "30d"):
        validated, _ = Config().validate({"delete_ignored_after_days": value})
        assert validated[Setting.DELETE_IGNORED_AFTER_DAYS] == 30, value
    validated, _ = Config().validate({"delete_ignored_after_days": "1.5"})
    assert validated[Setting.DELETE_IGNORED_AFTER_DAYS] == 1.5
    validated, _ = Config().validate({"delete_ignored_after_days": "12 hours"})
    assert validated[Setting.DELETE_IGNORED_AFTER_DAYS] == 0.5
    # Settings counted in seconds read a bare number as seconds, as before.
    validated, _ = Config().validate({"max_sync_interval_seconds": "600"})
    assert validated[Setting.MAX_SYNC_INTERVAL_SECONDS] == 600


@pytest.mark.parametrize("typed, days", [
    ("30", 30), ("30 days", 30), ("30d", 30), ("30 Days", 30), ("30 days,", 30), ("1 day, 12 hours", 1.5),
    ("1d 12h", 1.5), ("1.5 days", 1.5), ("12 hours", 0.5), ("3h", 0.125), ("90 minutes", 0.0625),
])
def test_duration_with_units_is_accepted(typed, days):
    validated, _ = Config().validate({"delete_ignored_after_days": typed})
    assert validated[Setting.DELETE_IGNORED_AFTER_DAYS] == pytest.approx(days)


@pytest.mark.parametrize("typed", [
    # A number without a unit, other than on its own, used to be read as
    # seconds: "30," deleted ignored backups after 30 seconds.
    "30,", "30, ", "7 30", "1 000", "1d 12", "2 days 3", "30 days 30",
    # Not a duration this parser knows.
    "1:30:00", "30 dayz", "3 ms", "3h5m", "days", ",", "thirty days", "-30 days",
])
def test_duration_without_units_is_rejected(typed):
    from backup.exceptions import InvalidConfigurationValue
    with pytest.raises(InvalidConfigurationValue):
        Config().validate({"delete_ignored_after_days": typed})


@pytest.mark.parametrize("seconds", [0, 1, 59, 60, 3599, 3600, 86399, 86400, 90061, 864000])
def test_formatted_duration_parses_back(seconds):
    # The settings form shows durations as format() writes them, and sends
    # them back as they are on save.
    from datetime import timedelta
    from backup.config.durationparser import DurationParser
    duration = timedelta(seconds=seconds)
    assert DurationParser().parse(DurationParser().format(duration)) == duration


def test_new_duration_too_large_is_refused():
    # A plain number skipped the timedelta a value with units goes through, so
    # "1000000000" days was saved and then broke the settings form.  A value
    # changed in the web UI now has a range (NEW_INPUT_LIMITS), typed or sent
    # as a JSON number.
    from backup.exceptions import InvalidConfigurationValue
    config = Config()
    config.update({"delete_ignored_after_days": "999999999"})  # the largest that fits
    assert config.getForUi(Setting.DELETE_IGNORED_AFTER_DAYS) == "999999999 days"
    for key, value in (("delete_ignored_after_days", "1000000000"), ("max_sync_interval_seconds", "100000000000000"),
                       ("delete_ignored_after_days", 1e308), ("max_sync_interval_seconds", 1e308)):
        with pytest.raises(InvalidConfigurationValue):
            Config().validate({key: value}, strict=True)


@pytest.mark.parametrize("key, stored", [("delete_ignored_after_days", 1e300), ("max_sync_interval_seconds", 1e300)])
def test_stored_duration_too_large_to_show_saves_back(key, stored):
    # The Configuration tab takes any number.  The form shows it in full,
    # not as "1e+300", which was refused, so every save failed.
    config = Config()
    config.update({key: stored})
    shown = config.getForUi(_LOOKUP[key])
    assert shown == "1" + "0" * 300
    validated, _ = config.validate({key: shown}, strict=True)
    assert validated[_LOOKUP[key]] == stored


def test_max_sync_interval_has_config_jsons_minimum():
    # Below config.json's minimum, Supervisor would refuse the whole options
    # update; the add-on refuses it first, with a clear error.
    from backup.exceptions import InvalidConfigurationValue
    with pytest.raises(InvalidConfigurationValue) as error:
        Config().validate({"max_sync_interval_seconds": "60"})
    # The web UI words the error from this: the setting's label and the value
    # as typed, not "60.0" (error.illegal_config.message).
    assert error.value.data() == {"key": "max_sync_interval_seconds", "value": "60"}
    validated, _ = Config().validate({"max_sync_interval_seconds": "5 minutes"})
    assert validated[Setting.MAX_SYNC_INTERVAL_SECONDS] == 300


def test_hostile_duration_is_rejected_quickly():
    # One /saveconfig with a huge duration used to block the add-on: the
    # number pattern could split a run of digits many ways, so a failed match
    # took time growing with the square of its length.
    import time
    from backup.config.durationparser import DURATION_REGEX
    from backup.exceptions import InvalidConfigurationValue
    start = time.perf_counter()
    assert DURATION_REGEX.fullmatch("1" * 20000 + "x") is None  # the regex itself, without the length cap
    for value in ("1" * 1000000 + "x", "1d " * 300000, " " * 1000000 + "1d"):
        with pytest.raises(InvalidConfigurationValue):
            Config().validate({"delete_ignored_after_days": value})
    assert time.perf_counter() - start < 1
    # Too large for a timedelta: a clean validation error, not a crash.
    with pytest.raises(InvalidConfigurationValue):
        Config().validate({"delete_ignored_after_days": "1" * 99 + "d"})


# (typed, found): what deleteIgnoredTypedAsSeconds makes of what v0.3.0's web
# UI saved for this text: (seconds, sure), or None.
TYPED_IN_THE_OLD_WEB_UI = [
    # A plain number meant as days, saved as seconds: corrected.
    ("30", (30, True)), ("1.5", (1.5, True)), ("3599", (3599, True)), ("3650", (3650, True)),
    ("9999", (9999, True)), ("10000", (10000, True)), ("36500", (36500, True)), ("99999", (99999, True)),
    ("999999", (999999, True)), ("9999999", (9999999, True)), ("30,", (30, True)),
    # Saved exactly as something that may have been meant: the user is asked.
    ("3600", (3600, False)), ("7200", (7200, False)), ("2 hours", (7200, False)), ("8 hours", (28800, False)),
    ("90 minutes", (5400, False)), ("0.33 days", (28512, False)), ("20 hours", (72000, False)),
    # A whole number of quarter days: nobody typed 43200 or 2592000 meaning days.
    ("6 hours", None), ("12 hours", None), ("1d 12h", None), ("30 days", None), ("86400", None),
    # Under an hour: corrected even with units, which only keeps backups longer.
    ("30 minutes", (1800, True)),
]


@pytest.mark.parametrize("typed, found", TYPED_IN_THE_OLD_WEB_UI)
def test_delete_ignored_typed_as_seconds(typed, found):
    # Up to v0.3.0 the web UI saved "30" as 30 seconds.
    from backup.ha import oldwebui
    from backup.ha.hasource import deleteIgnoredTypedAsSeconds
    assert deleteIgnoredTypedAsSeconds({"delete_ignored_after_days": oldwebui.save(typed)}) == found


@pytest.mark.parametrize("stored, as_set, after_old_save", [
    # v0.3.0's web UI saved what it showed, whole seconds, on any save: 0.999
    # became 0.998993 days, also what typing 86313 saved.  Asked, not
    # corrected to 86313 days.
    (0.999, None, (86313, False)), (1.001, None, (86486, False)), (0.333, None, (28771, False)),
    (0.33, (28512, False), (28512, False)),
    # 4 decimals under a day: 0.0833 (2 hours) became 7197 seconds.
    (0.0833, None, (7197, False)), (0.3333, None, (28797, False)), (0.6667, None, (57602, False)),
    # A whole number of quarter days: left alone, not asked about.
    (0.25, None, None), (2.5, None, None), (7, None, None), (30, None, None),
    # Too large for a number of seconds.
    (1e304, None, None), (1.7e308, None, None),
    (1.0025, (86616, False), (86616, False)),  # 4 decimals: not whole minutes, nor 3 decimals re-saved
    # Not whole seconds, so not something typing a number saved.
    (0.12345, None, None), (1.23456, None, None),
    # Under an hour: corrected (864 days), which only keeps backups longer.
    (0.01, (864, True), (864, True)),
])
def test_delete_ignored_set_in_the_configuration_tab(stored, as_set, after_old_save):
    from backup.ha import oldwebui
    from backup.ha.hasource import deleteIgnoredTypedAsSeconds
    assert deleteIgnoredTypedAsSeconds({"delete_ignored_after_days": stored}) == as_set
    if after_old_save is not None:
        resaved = oldwebui.save(oldwebui.show(stored))
        assert deleteIgnoredTypedAsSeconds({"delete_ignored_after_days": resaved}) == after_old_save


@pytest.mark.parametrize("stored", [True, "30", None, float("nan"), float("inf"), -1, 0])
def test_delete_ignored_not_a_saved_number(stored):
    from backup.ha.hasource import deleteIgnoredTypedAsSeconds
    options = {} if stored is None else {"delete_ignored_after_days": stored}
    assert deleteIgnoredTypedAsSeconds(options) is None


def test_delete_ignored_typed_numbers_are_never_missed():
    # Every number typed in v0.3.0's web UI is corrected or asked about, as
    # itself.  (The previous rule silently missed multiples of 216, e.g. 3672.)
    from backup.ha import oldwebui
    from backup.ha.hasource import deleteIgnoredTypedAsSeconds
    for typed in list(range(1, 30000)) + [36500, 99999, 100000, 365000, 1000000]:
        found = deleteIgnoredTypedAsSeconds({"delete_ignored_after_days": oldwebui.save(str(typed))})
        if typed % 21600 == 0:
            assert found is None, typed  # a whole number of quarter days
        else:
            assert found is not None and found[0] == typed, typed


def test_old_web_ui_copy_matches_v030():
    # oldwebui is v0.3.0's parser, kept as it was: a plain number is seconds.
    from datetime import timedelta
    from backup.ha import oldwebui
    assert oldwebui.save("30") == 30 / 86400
    assert oldwebui.save("30,") == oldwebui.save("30 seconds") == 30 / 86400
    assert oldwebui.save("1d 12") == (86400 + 12) / 86400
    assert oldwebui.save("2 hours") == oldwebui.save("120 minutes") == 7200 / 86400
    assert oldwebui.show(0.999) == "23 hours, 58 minutes, 33 seconds"
    assert oldwebui.format(timedelta(days=30)) == "30 days"


class FakeDataCache:
    def __init__(self, first_version="0.3.0", previous_version="0.4.0", current_version="0.4.0"):
        from backup.config import Version
        self.flags, self.saves = set(), 0
        self.firstVersion = Version.parse(first_version)
        self.previousVersion = Version.parse(previous_version)
        self.currentVersion = Version.parse(current_version)

    def checkFlag(self, flag):
        return flag in self.flags

    def addFlag(self, flag):
        self.flags.add(flag)

    def saveIfDirty(self):
        self.saves += 1


class FakeHaRequests:
    """Supervisor and Home Assistant, as far as HaSource._refreshInfo uses them."""

    def __init__(self, stored=None, fail_saves=0, fail_notify=False):
        self.stored = stored or {}
        self.saved, self.notified = [], []
        self.fail_saves, self.fail_notify = fail_saves, fail_notify

    async def selfInfo(self):
        options = dict(self.stored)
        await asyncio.sleep(0)  # as a real request would, letting another refresh run
        return {"slug": "self", "options": options}

    async def info(self):
        return {}

    async def haInfo(self):
        return {"port": 8123, "ssl": False}

    async def supervisorInfo(self):
        return {}

    async def mountInfo(self):
        return {}

    async def getAddons(self):
        return {"addons": []}

    async def updateConfig(self, options):
        await asyncio.sleep(0)
        if self.fail_saves:
            self.fail_saves -= 1
            raise Exception("Supervisor refused the options")
        self.saved.append(options)
        self.stored = dict(options)

    async def sendNotification(self, title, message, notification_id):
        if self.fail_notify:
            raise Exception("Home Assistant didn't answer")
        self.notified.append((title, message, notification_id))


class FakeInfo:
    slug = None

    def addDebugInfo(self, key, value):
        pass


def make_source(harequests, data_cache=None):
    from backup.ha.hasource import HaSource
    source = HaSource.__new__(HaSource)
    source.config, source._data_cache, source.harequests, source._info = \
        Config(), data_cache or FakeDataCache(), harequests, FakeInfo()
    source._refresh_lock, source._delete_ignored_checked = asyncio.Lock(), False
    source._delete_ignored_notice, source._delete_ignored_notice_tries = None, 0
    return source


async def test_delete_ignored_fix_is_saved_notified_and_runs_once():
    from backup.ha.hasource import DELETE_IGNORED_FIXED_NOTIFICATION_ID
    from backup.util import UpgradeFlags
    source = make_source(FakeHaRequests())
    stored = {"days_between_backups": 3, "delete_ignored_after_days": 30 / 86400}
    options = await source._fixDeleteIgnoredSeconds(stored)
    assert options == {"days_between_backups": 3, "delete_ignored_after_days": 30}
    assert source.harequests.saved == [options]  # written back to Supervisor
    assert stored["delete_ignored_after_days"] == 30 / 86400  # caller's dict untouched
    [(title, message, notification_id)] = source.harequests.notified
    assert "30 seconds" in message and "30 days" in message
    # Its own id: the stale-backups notification's is dismissed automatically.
    assert notification_id == DELETE_IGNORED_FIXED_NOTIFICATION_ID
    assert UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS in source._data_cache.flags
    assert source._data_cache.saves == 1
    # Only once: since the fix, "30 minutes" can be chosen on purpose.
    deliberate = {"delete_ignored_after_days": 30 / (24 * 60)}
    assert await source._fixDeleteIgnoredSeconds(deliberate) == deliberate
    assert len(source.harequests.saved) == 1 and len(source.harequests.notified) == 1


async def test_delete_ignored_fix_skips_installs_after_the_bug():
    # A newer install never had the bug, so a short value there was set on
    # purpose (even before the first start).
    source = make_source(FakeHaRequests())
    source._data_cache = FakeDataCache(first_version="0.3.1")
    deliberate = {"delete_ignored_after_days": 30 / (24 * 60)}
    assert await source._fixDeleteIgnoredSeconds(deliberate) == deliberate
    assert source.harequests.saved == [] and source.harequests.notified == []


async def test_delete_ignored_fix_notifies_only_if_it_was_deleting():
    # With both ignore options off the setting did nothing, so nothing changes
    # for the user: the value is still corrected, but quietly.
    from backup.util import UpgradeFlags
    source = make_source(FakeHaRequests())
    source.config = Config({Setting.IGNORE_OTHER_BACKUPS: False, Setting.IGNORE_UPGRADE_BACKUPS: False})
    options = await source._fixDeleteIgnoredSeconds({"delete_ignored_after_days": 30 / 86400})
    assert options == {"delete_ignored_after_days": 30}
    assert source.harequests.saved == [options] and source.harequests.notified == []
    assert UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS in source._data_cache.flags
    # Either ignore option on: notified.
    for ignoring in (Setting.IGNORE_OTHER_BACKUPS, Setting.IGNORE_UPGRADE_BACKUPS):
        source = make_source(FakeHaRequests())
        source.config = Config({Setting.IGNORE_OTHER_BACKUPS: False, Setting.IGNORE_UPGRADE_BACKUPS: False,
                                ignoring: True})
        await source._fixDeleteIgnoredSeconds({"delete_ignored_after_days": 30 / 86400})
        assert len(source.harequests.notified) == 1, ignoring


@pytest.mark.parametrize("stored", [{}, {"delete_ignored_after_days": 0}, {"delete_ignored_after_days": 1.23456}])
async def test_delete_ignored_fix_is_silent_when_nothing_changes(stored):
    # Never set, or not something typing a number saved: no write, no
    # notification, but the check is done for good.
    from backup.util import UpgradeFlags
    source = make_source(FakeHaRequests())
    assert await source._fixDeleteIgnoredSeconds(stored) == stored
    assert source.harequests.saved == [] and source.harequests.notified == []
    assert UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS in source._data_cache.flags


async def test_delete_ignored_fix_survives_a_failed_save():
    # Supervisor refusing the write mustn't stop syncs: the corrected value is
    # used anyway, and saved (and notified) on a later refresh.
    from backup.util import UpgradeFlags
    source = make_source(FakeHaRequests({"delete_ignored_after_days": 30 / 86400}, fail_saves=1))
    await source._refreshInfo()
    assert source.config.get(Setting.DELETE_IGNORED_AFTER_DAYS) == 30
    assert source.harequests.saved == [] and source.harequests.notified == []
    assert UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS not in source._data_cache.flags
    await source._refreshInfo()
    assert source.harequests.saved == [{"delete_ignored_after_days": 30}]
    assert len(source.harequests.notified) == 1
    assert UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS in source._data_cache.flags


async def test_delete_ignored_fix_survives_a_failed_notification():
    from backup.util import UpgradeFlags
    source = make_source(FakeHaRequests({"delete_ignored_after_days": 30 / 86400}, fail_notify=True))
    await source._refreshInfo()
    assert source.config.get(Setting.DELETE_IGNORED_AFTER_DAYS) == 30
    assert source.harequests.saved == [{"delete_ignored_after_days": 30}]
    assert UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS in source._data_cache.flags
    # The notification is sent on a later refresh: without it, the change
    # from 30 seconds to 30 days was only in the add-on's log.
    source.harequests.fail_notify = False
    await source._refreshInfo()
    await source._refreshInfo()
    [(_, message, _)] = source.harequests.notified
    assert "now 30 days" in message and len(source.harequests.saved) == 1


@pytest.mark.parametrize("stored", [30 / 86400, 7200 / 86400])
async def test_delete_ignored_notification_gives_up_after_a_few_tries(stored):
    # It used to be tried on every refresh (each /getconfig) with no limit.
    from backup.ha.hasource import DELETE_IGNORED_NOTICE_TRIES
    from backup.util import UpgradeFlags
    source = make_source(FakeHaRequests({"delete_ignored_after_days": stored}, fail_notify=True))
    source.harequests.tries = 0
    send = source.harequests.sendNotification

    async def counted(*args):
        source.harequests.tries += 1
        await send(*args)
    source.harequests.sendNotification = counted
    for _ in range(DELETE_IGNORED_NOTICE_TRIES + 5):
        await source._refreshInfo()
    assert source.harequests.tries == DELETE_IGNORED_NOTICE_TRIES
    assert UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS in source._data_cache.flags


async def test_refresh_applies_the_delete_ignored_fix():
    # The fix must reach the config the add-on runs with, not just Supervisor.
    source = make_source(FakeHaRequests({"delete_ignored_after_days": 30 / 86400}))
    await source._refreshInfo()
    assert source.config.get(Setting.DELETE_IGNORED_AFTER_DAYS) == 30
    assert source.harequests.saved == [{"delete_ignored_after_days": 30}]
    # The next refresh reads the corrected value back and leaves it alone.
    await source._refreshInfo()
    assert source.config.get(Setting.DELETE_IGNORED_AFTER_DAYS) == 30
    assert len(source.harequests.saved) == 1 and len(source.harequests.notified) == 1


async def test_delete_ignored_whole_minutes_are_only_asked_about():
    # 7200 seconds is what a bare "7200" meant as days saved, but also "2
    # hours": left as it is, and the user is asked, once.
    from backup.ha.hasource import DELETE_IGNORED_CHECK_TITLE, DELETE_IGNORED_FIXED_NOTIFICATION_ID
    from backup.util import UpgradeFlags
    source = make_source(FakeHaRequests({"delete_ignored_after_days": 7200 / 86400}))
    await source._refreshInfo()
    assert source.config.get(Setting.DELETE_IGNORED_AFTER_DAYS) == 7200 / 86400
    assert source.harequests.saved == []
    [(title, message, notification_id)] = source.harequests.notified
    assert title == DELETE_IGNORED_CHECK_TITLE and notification_id == DELETE_IGNORED_FIXED_NOTIFICATION_ID
    assert "Yours is 2 hours, which is also what typing 7200 there saved" in message
    assert "If you typed 7200 meaning days" in message
    assert UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS in source._data_cache.flags
    await source._refreshInfo()
    assert len(source.harequests.notified) == 1
    # Not asked when the setting has no effect.
    source = make_source(FakeHaRequests({"delete_ignored_after_days": 7200 / 86400}))
    source.config = Config({Setting.IGNORE_OTHER_BACKUPS: False, Setting.IGNORE_UPGRADE_BACKUPS: False})
    await source._refreshInfo()
    assert source.harequests.notified == [] and source.harequests.saved == []


async def test_delete_ignored_that_may_be_meant_is_checked_once():
    # The breaking change: 0.33 days, as set in the Configuration tab, is also
    # what typing 28512 saved, so the user is asked to check it, once.
    from backup.ha.hasource import DELETE_IGNORED_CHECK_TITLE
    source = make_source(FakeHaRequests({"delete_ignored_after_days": 0.33}))
    await source._refreshInfo()
    await source._refreshInfo()
    assert source.harequests.saved == []
    [(title, message, _)] = source.harequests.notified
    assert title == DELETE_IGNORED_CHECK_TITLE and "Yours is 7 hours, 55 minutes, 12 seconds" in message
    assert source.config.get(Setting.DELETE_IGNORED_AFTER_DAYS) == 0.33


async def test_delete_ignored_check_is_asked_again_if_the_notification_fails():
    # Nothing is changed in this case, so the notification is all the user
    # gets; it was sent once, and a failure only logged.
    from backup.util import UpgradeFlags
    source = make_source(FakeHaRequests({"delete_ignored_after_days": 7200 / 86400}, fail_notify=True))
    await source._refreshInfo()
    assert UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS not in source._data_cache.flags
    source.harequests.fail_notify = False
    await source._refreshInfo()
    await source._refreshInfo()
    assert len(source.harequests.notified) == 1 and source.harequests.saved == []
    assert UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS in source._data_cache.flags


@pytest.mark.parametrize("typed, text", [(9999999, "9999999"), (1234567, "1234567"), (1.5, "1.5"), (0.001, "0.001")])
async def test_delete_ignored_fix_writes_numbers_in_full(typed, text):
    # "{:g}" wrote 9999999 as "1e+07" and 1234567 as "1.23457e+06".
    source = make_source(FakeHaRequests({"delete_ignored_after_days": typed / 86400}))
    await source._refreshInfo()
    [(_, message, _)] = source.harequests.notified
    assert "was {0} seconds".format(text) in message and "now {0} days".format(text) in message


async def test_concurrent_refreshes_correct_once():
    # getconfig, init and create each refresh.  At the same time, each one
    # corrected and notified; and one that read the options before another's
    # correction could apply the old value again (syncs don't refresh), or
    # correct it twice: "0.01" (days) saved as 0.01 seconds became 0.01 days,
    # still under an hour, then 864 days.
    source = make_source(FakeHaRequests({"delete_ignored_after_days": 0.01 / 86400}))
    await asyncio.gather(source._refreshInfo(), source._refreshInfo(), source._refreshInfo())
    assert source.harequests.saved == [{"delete_ignored_after_days": 0.01}]
    assert len(source.harequests.notified) == 1
    assert source.config.get(Setting.DELETE_IGNORED_AFTER_DAYS) == 0.01


async def test_delete_ignored_checked_again_after_running_the_buggy_version():
    # After going back to v0.3.0 and up again, a value saved meanwhile may
    # have the bug, though the check had run.
    from backup.util import UpgradeFlags
    cache = FakeDataCache(previous_version="0.3.0", current_version="0.4.0")
    cache.flags.add(UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS)
    source = make_source(FakeHaRequests({"delete_ignored_after_days": 30 / 86400}), cache)
    await source._refreshInfo()
    assert source.config.get(Setting.DELETE_IGNORED_AFTER_DAYS) == 30
    # Once per start: a short value set afterwards is left alone.
    source.harequests.stored = {"delete_ignored_after_days": 30 / 1440}
    await source._refreshInfo()
    assert source.config.get(Setting.DELETE_IGNORED_AFTER_DAYS) == 30 / 1440
    # A later start, or one where the previous version is this one, isn't from
    # the buggy version.
    for previous, current in (("0.4.0", "0.4.0"), ("0.3.0", "0.3.0")):
        cache = FakeDataCache(previous_version=previous, current_version=current)
        cache.flags.add(UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS)
        source = make_source(FakeHaRequests({"delete_ignored_after_days": 30 / 86400}), cache)
        await source._refreshInfo()
        assert source.config.get(Setting.DELETE_IGNORED_AFTER_DAYS) == 30 / 86400, (previous, current)


async def test_delete_ignored_check_with_the_real_data_cache(tmp_path, monkeypatch):
    # The versions and the flag as DataCache records them in data_cache.json.
    import json
    from backup.config import Version
    from backup.time import Time
    from backup.util import data_cache

    def start(path):
        config = Config()
        config.override(Setting.DATA_CACHE_FILE_PATH, str(path))
        return data_cache.DataCache(config, Time())

    async def refreshed(path, stored_days):
        source = make_source(FakeHaRequests({"delete_ignored_after_days": stored_days}), start(path))
        await source._refreshInfo()
        return source.config.get(Setting.DELETE_IGNORED_AFTER_DAYS)

    path = tmp_path / "data_cache.json"
    path.write_text(json.dumps({"last_verison": "0.3.0", "upgrades": [
        {"prev_version": "0", "new_version": "0.2.1", "date": "2026-09-05T00:00:00+00:00"},
        {"prev_version": "0.2.1", "new_version": "0.3.0", "date": "2026-11-02T00:00:00+00:00"}]}))
    monkeypatch.setattr(data_cache, "VERSION", "0.4.0")
    cache = start(path)
    assert (cache.firstVersion, cache.previousVersion) == (Version.parse("0.2.1"), Version.parse("0.3.0"))
    # The first start after upgrading from v0.3.0 corrects it.
    assert await refreshed(path, 30 / 86400) == 30
    # The next start doesn't: a short value set since was set on purpose.
    assert await refreshed(path, 30 / 1440) == 30 / 1440
    # Back to v0.3.0 and up again: checked again.
    monkeypatch.setattr(data_cache, "VERSION", "0.3.0")
    start(path)
    monkeypatch.setattr(data_cache, "VERSION", "0.4.0")
    assert await refreshed(path, 45 / 86400) == 45
    # A fresh install never had the bug.
    assert await refreshed(tmp_path / "fresh.json", 30 / 1440) == 30 / 1440


def test_validate_drops_removed_options():
    # Options removed from config.json (they had no effect) may still be in a
    # user's saved options; they must be dropped, not raise or be written back.
    validated, _ = Config().validate({
        "days_between_backups": 5,
        "verbose": True,
        "send_error_reports": True,
        "specify_backup_folder": True,
        "disable_watchdog_when_stopping": True,
        "maximum_upload_chunk_bytes": "10 MB",
        "upload_limit_bytes_per_second": "5 MB",
    })
    assert {k.key() for k in validated} == {"days_between_backups", "max_backups_in_ha"}


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
        "new_backup_timeout_seconds": 99,   # internal timeout -> dropped
        "supervisor_url": "https://example",  # internal endpoint -> dropped
        "verbose": True,                    # removed option -> dropped
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
