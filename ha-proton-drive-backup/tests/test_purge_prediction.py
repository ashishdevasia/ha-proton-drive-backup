"""getNextPurges() must predict the backup the next sync actually deletes."""
from datetime import datetime, timedelta

import pytz

from backup.config import Config, Setting
from backup.model.model import Model
from backup.model.simulatedsource import SimulatedSource
from backup.time import Time
from backup.util.globalinfo import GlobalInfo


class PredictTime(Time):
    def __init__(self):
        super().__init__(local_tz=pytz.utc)
        self._now = datetime(2026, 5, 1, 12, 0, tzinfo=pytz.utc)

    def now(self):
        return self._now

    def advance(self, **kw):
        self._now += timedelta(**kw)


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


def build(config_overrides):
    config = Config()
    config.override(Setting.DAYS_BETWEEN_BACKUPS, 1)
    config.override(Setting.CONFIRM_MULTIPLE_DELETES, False)
    for setting, value in config_overrides.items():
        config.override(setting, value)
    time = PredictTime()
    source = SimulatedSource("HomeAssistant")
    dest = SimulatedSource("ProtonDrive", is_destination=True)
    source.setMax(config.get(Setting.MAX_BACKUPS_IN_HA))
    dest.setMax(config.get(Setting.MAX_BACKUPS_IN_PROTON_DRIVE))
    model = Model(config, time, source, dest, GlobalInfo(time),
                  NoopEstimator(), NoopDataCache())
    model.ignore_startup_delay = True
    return model, time, source, dest


async def assert_predictions_come_true(model, time, source, dest, days):
    """Run daily syncs; each prediction must match the next sync's deletion."""
    predicted = None
    for _ in range(days):
        deleted_before = {"HomeAssistant": len(source.deleted),
                          "ProtonDrive": len(dest.deleted)}
        await model.sync(time.now())
        for name, src in (("HomeAssistant", source), ("ProtonDrive", dest)):
            deleted = src.deleted[deleted_before[name]:]
            if predicted is not None:
                want = predicted[name]
                if deleted:
                    assert want is not None, \
                        "{0}: deleted {1} but nothing was predicted".format(name, deleted[0].date())
                    assert deleted[0].date() == want, \
                        "{0}: predicted {1} but deleted {2}".format(name, want, deleted[0].date())
                else:
                    assert want is None, \
                        "{0}: predicted {1} but nothing was deleted".format(name, want)
        # Snapshot the predicted dates: the Backup objects themselves are
        # emptied when the next sync deletes them.
        purges = model.getNextPurges()
        for purge in purges.values():
            assert purge is None or purge.slug() != "dummy_next_backup"
        predicted = {name: (purge.date() if purge else None) for name, purge in purges.items()}
        time.advance(days=1)


async def test_prediction_plain_oldest_scheme():
    model, time, source, dest = build({
        Setting.MAX_BACKUPS_IN_HA: 4,
        Setting.MAX_BACKUPS_IN_PROTON_DRIVE: 4,
    })
    await assert_predictions_come_true(model, time, source, dest, days=10)


async def test_prediction_generational():
    # The config that surfaced the bug: the old count-1 prediction pinned an
    # old weekly keeper while the real purge deleted yesterday's backup.
    model, time, source, dest = build({
        Setting.MAX_BACKUPS_IN_HA: 4,
        Setting.MAX_BACKUPS_IN_PROTON_DRIVE: 4,
        Setting.GENERATIONAL_DAYS: 0,   # forced to 1 internally
        Setting.GENERATIONAL_WEEKS: 2,
        Setting.GENERATIONAL_MONTHS: 2,
        Setting.GENERATIONAL_YEARS: 2,
    })
    await assert_predictions_come_true(model, time, source, dest, days=45)


async def test_prediction_generational_delete_early():
    model, time, source, dest = build({
        Setting.MAX_BACKUPS_IN_HA: 6,
        Setting.MAX_BACKUPS_IN_PROTON_DRIVE: 6,
        Setting.GENERATIONAL_DAYS: 1,
        Setting.GENERATIONAL_WEEKS: 2,
        Setting.GENERATIONAL_DELETE_EARLY: True,
    })
    await assert_predictions_come_true(model, time, source, dest, days=30)


async def test_prediction_generational_delete_before_new_backup():
    # With DELETE_BEFORE_NEW_BACKUP the pre-purge (count-1, current set) fires
    # before the new backup exists, so it decides the next deletion.
    model, time, source, dest = build({
        Setting.MAX_BACKUPS_IN_HA: 4,
        Setting.MAX_BACKUPS_IN_PROTON_DRIVE: 4,
        Setting.GENERATIONAL_DAYS: 0,
        Setting.GENERATIONAL_WEEKS: 2,
        Setting.GENERATIONAL_MONTHS: 2,
        Setting.GENERATIONAL_YEARS: 2,
        Setting.DELETE_BEFORE_NEW_BACKUP: True,
    })
    await assert_predictions_come_true(model, time, source, dest, days=45)


async def test_prediction_plain_delete_before_new_backup():
    model, time, source, dest = build({
        Setting.MAX_BACKUPS_IN_HA: 4,
        Setting.MAX_BACKUPS_IN_PROTON_DRIVE: 4,
        Setting.DELETE_BEFORE_NEW_BACKUP: True,
    })
    await assert_predictions_come_true(model, time, source, dest, days=10)


async def test_prediction_empty_model():
    model, time, source, dest = build({
        Setting.MAX_BACKUPS_IN_HA: 4,
        Setting.MAX_BACKUPS_IN_PROTON_DRIVE: 4,
    })
    purges = model.getNextPurges()
    assert purges == {"HomeAssistant": None, "ProtonDrive": None}
