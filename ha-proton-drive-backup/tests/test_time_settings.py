"""
Time and duration settings.  Any value config.json allows (the Configuration
tab checks nothing more) must keep the add-on syncing; values changed in the web
UI must also be within NEW_INPUT_LIMITS.
"""
import math
import random
import time as wallclock
from datetime import datetime, timedelta

import pytest
import pytz

from backup.config import Config, Setting, GenConfig, _LOOKUP
from backup.config.settings import _VALIDATORS, ADDON_OPTION_KEYS
from backup.config.durationasstringvalidator import DurationAsStringValidator
from backup.config.floatvalidator import FloatValidator
from backup.config.intvalidator import IntValidator
from backup.exceptions import InvalidConfigurationValue
from backup.model.backupscheme import GenerationalScheme
from backup.model.dummybackup import DummyBackup
from backup.model.model import Model, NO_BACKUP_AFTER
from backup.model.simulatedsource import SimulatedSource
from backup.time import Time
from backup.util.globalinfo import GlobalInfo

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=pytz.utc)


def validator(key):
    return _VALIDATORS[_LOOKUP[key]]


NUMBER_OPTIONS = sorted(key for key in ADDON_OPTION_KEYS
                        if isinstance(validator(key), (IntValidator, FloatValidator, DurationAsStringValidator)))
DURATION_OPTIONS = [key for key in NUMBER_OPTIONS if isinstance(validator(key), DurationAsStringValidator)]


def test_option_kinds():
    # Guards the lists the tests below run over.
    assert DURATION_OPTIONS == ["delete_ignored_after_days", "ha_reporting_interval_seconds",
                                "max_sync_interval_seconds"]
    assert {"days_between_backups", "generational_years", "proton_drive_timeout_seconds",
            "default_sync_interval_variation", "max_backoff_seconds"} <= set(NUMBER_OPTIONS)


@pytest.mark.parametrize("key", NUMBER_OPTIONS)
@pytest.mark.parametrize("value", [True, False, [30], {"days": 30}, float("nan"), float("inf"), float("-inf"),
                                   "nan", "inf", "NaN"])
def test_number_settings_refuse_what_isnt_a_number(key, value):
    # True was read as 1, NaN passed every limit (comparisons with it are all
    # False), infinity broke every date calculated from it, and a list or dict
    # raised a TypeError: an unexpected error that didn't name the setting.
    with pytest.raises(InvalidConfigurationValue) as error:
        Config().validate({key: value})
    assert error.value.data()["key"] == key


@pytest.mark.parametrize("key", [key for key in NUMBER_OPTIONS if not isinstance(validator(key), IntValidator)])
def test_number_too_large_for_a_float_is_refused(key):
    with pytest.raises(InvalidConfigurationValue):
        Config().validate({key: 10 ** 400})


@pytest.mark.parametrize("key, refused, accepted", [
    ("days_between_backups", [0.05, 0.001, 36501, 1e308], [0, 0.1, 0.5, 3, 36500]),
    ("delete_ignored_after_days", ["12 hours", "23 hours, 59 minutes", 0.5, "1000000000", 1e308],
     ["", "0", 0, "1 day", "24 hours", "30", 999999999]),
    ("generational_days", [3651], [0, 3650]),
    ("generational_weeks", [521], [0, 520]),
    ("generational_months", [1201], [0, 1200]),
    ("generational_years", [101, 9999], [0, 100]),
    ("max_sync_interval_seconds", ["30 days, 1 seconds", "100000000000000", 1e308], ["5 minutes", "3h", "30 days"]),
    ("ha_reporting_interval_seconds", ["1.5 seconds", "1 days, 1 seconds"], ["1 seconds", "1 days"]),
])
def test_new_input_limits(key, refused, accepted):
    for value in refused:
        with pytest.raises(InvalidConfigurationValue) as error:
            Config().validate({key: value}, strict=True)
        # The web UI words the error from these (error.illegal_config.message).
        assert error.value.data() == {"key": key, "value": str(value)}
        # Within config.json's schema, so a value Supervisor sends is taken.
        Config().validate({key: value})
    for value in accepted:
        Config().validate({key: value}, strict=True)


def test_settings_form_saves_stored_values_beyond_the_limits():
    # The Configuration tab only checks config.json's schema.  The settings
    # form sends every value back on each save, so one stored beyond the web
    # UI's limits mustn't block saving something else.
    stored = {
        Setting.DAYS_BETWEEN_BACKUPS: 50000.0,
        Setting.DELETE_IGNORED_AFTER_DAYS: 0.999,
        Setting.GENERATIONAL_YEARS: 9999,
        Setting.MAX_SYNC_INTERVAL_SECONDS: 1e300,
        Setting.HA_REPORTING_INTERVAL_SECONDS: 8.64e13,
    }
    config = Config(dict(stored))
    form = {setting.key(): config.getForUi(setting) for setting in stored}
    validated, _ = config.validate(form, strict=True)
    for setting, value in stored.items():
        assert validated[setting] == value, setting
    # A changed value still has to be within them.
    with pytest.raises(InvalidConfigurationValue):
        config.validate(dict(form, days_between_backups=50001), strict=True)


def _sample_values():
    rng = random.Random(1)
    values = [0, 1, 59, 60, 61, 0.5, 0.999, 1.1, 300, 300.0001, 3599, 3600, 86399, 86400, 999999999, 1e10,
              1e300, 5e-324, 1.7976931348623157e308, 30 / 86400, 3650.5]
    for _ in range(3000):
        exponent = rng.uniform(-8, 16)
        values.append(10 ** exponent)
        values.append(round(10 ** exponent, rng.randint(0, 6)))
    values += [n / 86400 for n in range(0, 200000, 97)]
    return values


@pytest.mark.parametrize("key", DURATION_OPTIONS)
def test_settings_form_shows_durations_exactly(key):
    # The settings form shows a duration that reads back as exactly the stored
    # value: "23 hours, 58 minutes, 33 seconds" saved 0.999 days back as
    # 0.99899, under a second showed as "0 seconds" (saved as 0, "never"), and
    # "1e+300" was refused, so every save failed.
    v = validator(key)
    for value in _sample_values():
        if v.min is not None and value < v.min:
            continue  # config.json refuses it
        shown = v.formatForUi(value)
        if shown == "":
            assert value == v.default_as_empty
            continue
        assert v.validate(shown) == value, (value, shown)


class ZoneTime(Time):
    def __init__(self, zone, now):
        super().__init__(local_tz=pytz.timezone(zone))
        self._now = now

    def now(self):
        return self._now


class NoopEstimator:
    def refresh(self):
        return self

    def checkSpace(self, backups):
        pass


class NoopDataCache:
    def saveIfDirty(self):
        pass

    def backup(self, slug):
        return {}


def build_model(zone, days, time_of_day, now=NOW):
    config = Config()
    config.override(Setting.DAYS_BETWEEN_BACKUPS, days)
    config.override(Setting.BACKUP_TIME_OF_DAY, time_of_day)
    config.override(Setting.MAX_BACKUPS_IN_HA, 100)
    config.override(Setting.MAX_BACKUPS_IN_PROTON_DRIVE, 100)
    config.override(Setting.CONFIRM_MULTIPLE_DELETES, False)
    time = ZoneTime(zone, now)
    source = SimulatedSource("HomeAssistant")
    dest = SimulatedSource("ProtonDrive", is_destination=True)
    source.setMax(100)
    dest.setMax(100)
    model = Model(config, time, source, dest, GlobalInfo(time), NoopEstimator(), NoopDataCache())
    model.ignore_startup_delay = True
    return model, time, source


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "America/Santiago", "Asia/Kolkata", "Pacific/Kiritimati"])
@pytest.mark.parametrize("time_of_day", ["", "00:00", "03:00", "23:59"])
@pytest.mark.parametrize("days", [0.001, 0.1, 0.5, 0.999, 1, 1.5, 2.9, 36500, 2.9e6, 3e6, 1e308])
def test_next_backup_for_any_days_between_backups(days, time_of_day, zone):
    model, time, _ = build_model(zone, days, time_of_day)
    last = NOW - timedelta(minutes=1)  # a backup was just made
    next = model._nextBackup(NOW, last)
    if not time_of_day:
        expected = last + timedelta(days=days) if days < NO_BACKUP_AFTER.days else None
    else:
        # At the time of day, a whole number of days later: rounded up.
        whole = max(1, math.ceil(days))
        hour, minute = (int(part) for part in time_of_day.split(":"))
        local = time.toLocal(last)
        if (local.hour, local.minute) < (hour, minute):
            day = local.date()  # that day's time hasn't come yet
        elif whole < NO_BACKUP_AFTER.days:
            day = local.date() + timedelta(days=whole)
        else:
            day = None
        expected = time.toUtc(time.localize(datetime(day.year, day.month, day.day, hour, minute))) if day else None
        # Never a time already passed: with days under 1 it was, so every sync
        # made another backup.  (Huge values used to raise instead, failing
        # every sync and the status page.)
        assert next is None or next > NOW
    assert next == expected


@pytest.mark.parametrize("days", [0.1, 0.5, 0.999, 1.5])
async def test_fraction_of_a_day_with_a_time_of_day_backs_up_once_per_whole_day(days):
    start = datetime(2026, 5, 1, 12, 0, tzinfo=pytz.utc)
    model, time, source = build_model("America/New_York", days, "03:00", start)

    async def syncs(count):
        for _ in range(count):
            await model.sync(time.now())
            time._now += timedelta(minutes=1)
    await syncs(10)
    assert len(source.created) == 1
    # 03:01 the next day: one more only if a whole day has passed.
    time._now = time.toUtc(time.localize(datetime(2026, 5, 2, 3, 1)))
    await syncs(10)
    assert len(source.created) == (2 if days <= 1 else 1)
    time._now = time.toUtc(time.localize(datetime(2026, 5, 3, 3, 1)))
    await syncs(10)
    assert len(source.created) == (3 if days <= 1 else 2)


@pytest.mark.parametrize("counts", [dict(years=9999), dict(months=30000), dict(days=740000), dict(weeks=106000),
                                    dict(days=3650, weeks=520, months=1200, years=100)])
def test_generational_counts_beyond_any_backup(counts):
    # "years: 9999" meant as "forever" failed every purge with "year 0 is out
    # of range", and large day or week counts took seconds to minutes per
    # purge, several times per sync.
    time = ZoneTime("Europe/Paris", NOW)
    backups = [DummyBackup("b%d" % i, NOW - timedelta(days=3 * i), "HomeAssistant", "slug%d" % i)
               for i in range(400)]  # one every 3 days, over 3 years
    scheme = GenerationalScheme(time, GenConfig(**counts), count=10)
    started = wallclock.perf_counter()
    scheme.getOldest(backups)
    scheme.handleNaming(backups)
    assert wallclock.perf_counter() - started < 2


def test_cache_warmup_pauses_a_day_after_an_error():
    # cache_warmup_error_timeout is in seconds, but was read as days: after
    # one error, cache warm-up stopped for 86400 days.
    from backup.model.destinationprecache import DestinationPrecache

    class Coordinator:
        def nextSyncAttempt(self):
            return NOW + timedelta(hours=1)
    precache = DestinationPrecache.__new__(DestinationPrecache)
    precache._coord, precache._config, precache._offset, precache._last_error = Coordinator(), Config(), 0, NOW
    assert precache.getNextWarmDate() == NOW + timedelta(days=1)
