import asyncio
import math
import aiohttp
from datetime import timedelta
from io import IOBase
from threading import Lock, Thread
from typing import Dict, List, Optional, Any, Tuple, Union

from aiohttp.client_exceptions import ClientResponseError
from injector import inject, singleton

from backup.util import AsyncHttpGetter, GlobalInfo, Estimator, DataCache, KEY_NOTE, KEY_LAST_SEEN, KEY_PENDING, KEY_NAME, KEY_CREATED, KEY_I_MADE_THIS, KEY_IGNORE, UpgradeFlags
from ..config import Config, Setting, CreateOptions, Startable, Version
from ..config.durationparser import formatNumber
from . import oldwebui
from ..const import SOURCE_HA
from ..model import BackupSource, AbstractBackup, HABackup, Backup
from ..exceptions import (LogicError, BackupInProgress, UnknownNetworkStorageError, InactiveNetworkStorageError,
                          UploadFailed, ensureKey)
from .harequests import HaRequests
from .password import Password
from .backupname import BackupName
from ..time import Time
from ..logger import getLogger, StandardLogger
from backup.const import FOLDERS, NECESSARY_OLD_BACKUP_PLURAL_NAME
from .addon_stopper import LOGGER, AddonStopper

logger: StandardLogger = getLogger(__name__)


def deleteIgnoredTypedAsSeconds(options: Dict[str, Any]) -> Optional[Tuple[float, bool]]:
    """
    Up to v0.3.0 the web UI read a plain number typed into "Delete ignored
    backups after" as seconds, so "30" was saved as 30 seconds (30 / 86400
    days) and every ignored backup (by default, all those the add-on didn't
    make) was deleted about 30 seconds after it appeared.  This replays that
    release's web UI (oldwebui) to see whether typing a number there saved
    exactly the stored value.  Returns None if not, otherwise (typed, sure):
    typed is the number that was typed, i.e. the value in seconds.  If sure,
    correct it to that many days.  If not, something the user may have meant
    saved exactly the same value (e.g. "2 hours" and "7200"), so ask them to
    check it.
    """
    value = options.get(Setting.DELETE_IGNORED_AFTER_DAYS.key())
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < math.inf:
        return None
    typed = round(value * oldwebui.DAY_SECONDS, 3)
    if not math.isfinite(typed):
        return None  # e.g. 1e304 days, from the Configuration tab
    # A whole number of quarter days (6 hours, 1 day, 30 days): what typing
    # 21600, 86400 or 2592000 saved too, but nobody typed those meaning days.
    if value * 4 == int(value * 4):
        return None
    # Beyond an hour, a number of days typed in the web UI is whole: no one
    # meant 106665.984 days.  (0.12345 days set in the Configuration tab is
    # 10666.08 seconds.)
    if value >= 1 / 24 and typed != int(typed):
        return None
    try:
        if oldwebui.save(formatNumber(typed)) != value:
            return None
    except (ValueError, OverflowError):
        return None
    if value < 1 / 24:
        # Under an hour, corrected even if it may have been meant (e.g. "30
        # minutes"): deleting every ignored backup within the hour is hardly
        # ever wanted, and a correction only keeps backups longer.
        return typed, True
    return typed, not _deleteIgnoredCouldBeMeant(value)


def _deleteIgnoredCouldBeMeant(value: float) -> bool:
    """Whether something a user may have meant made v0.3.0 save exactly value."""
    # Set in the Configuration tab with up to 4 decimals, e.g. 0.33 or 30 days.
    if round(value, 4) == value:
        return True
    try:
        # A duration typed in whole minutes, e.g. "2 hours" or "90 minutes".
        if oldwebui.save("{0} minutes".format(round(value * 24 * 60))) == value:
            return True
        # Set in the Configuration tab with up to 3 decimals, then saved again
        # by v0.3.0's web UI with any other change: it saved what it showed,
        # whole seconds, so 0.999 became "23 hours, 58 minutes, 33 seconds".
        # Under a day, 4 decimals too: hours as a fraction of a day, e.g.
        # 0.0833 (2 hours) became 7197 seconds.  Not beyond a day, where 1 in 9
        # typed numbers (99999 among them) is also some 4-decimal value re-saved.
        for scale in (1000, 10000) if value < 1 else (1000,):
            nearest = math.ceil(value * scale)
            for candidate in (nearest - 1, nearest, nearest + 1):
                if candidate > 0 and oldwebui.save(oldwebui.show(candidate / scale)) == value:
                    return True
    except (ValueError, OverflowError):
        pass
    return False


# The last release whose web UI read a plain number as seconds.
LAST_SECONDS_BUG_VERSION = Version.parse("0.3.0")

# Sent only when deleteIgnoredTypedAsSeconds finds the bug.
DELETE_IGNORED_FIXED_NOTIFICATION_ID = "proton_delete_ignored_fixed"
DELETE_IGNORED_FIXED_TITLE = "Proton Drive Backup corrected a setting"
DELETE_IGNORED_FIXED_MESSAGE = (
    "\"Delete ignored backups after\" was {typed} seconds: what an earlier version of the add-on saved when {typed} "
    "was typed in its web UI, since it read a plain number as seconds.  Ignored backups (by default, every backup the "
    "add-on didn't make) were being deleted that soon after they appeared.  It's now {typed} days.  If you meant a "
    "shorter time, set it again.")
DELETE_IGNORED_NOTICE_TRIES = 5
DELETE_IGNORED_CHECK_TITLE = "Proton Drive Backup: check a setting"
DELETE_IGNORED_CHECK_MESSAGE = (
    "Up to v0.3.0, the add-on's web UI read a plain number in \"Delete ignored backups after\" as seconds; it now "
    "means days.  Yours is {shown}, which is also what typing {typed} there saved.  If you typed {typed} meaning "
    "days, set it again: ignored backups (by default, every backup the add-on didn't make) are being deleted after "
    "{shown}.  Otherwise there's nothing to do.")


class PendingBackup(AbstractBackup):
    def __init__(self, backupType, protected, options: CreateOptions, request_info, config, time):
        super().__init__(
            name=request_info['name'],
            slug="pending",
            date=options.when,
            size="pending",
            source=SOURCE_HA,
            backupType=backupType,
            version="",
            protected=protected,
            retained=False,
            uploadable=False,
            details=None,
            note=options.note,
            pending=True)
        self._config = config
        self._failed = False
        self._complete = False
        self._exception = None
        self._failed_at = None
        self.setOptions(options)
        self._request_info = request_info
        self._completed_slug = None
        self._time = time
        self._pending_subverted = False
        self._start_time = time.now()
        self._logs = None

    def considerForPurge(self) -> bool:
        return False

    def startTime(self):
        return self._start_time

    def failed(self, exception, time):
        self._failed = True
        self._exception = exception
        self._failed_at = time

    def getFailureTime(self):
        return self._failed_at

    def complete(self, slug):
        self._complete = True
        self._completed_slug = slug

    def setPendingUnknown(self):
        self._name = "Pending Backup"
        self._backupType = "unknown"
        self._protected = False
        self._pending_subverted = True
        self._note = None

    def createdSlug(self):
        return self._completed_slug

    def isComplete(self):
        return self._complete

    def isFailed(self):
        return self._failed

    def status(self):
        if self._complete:
            return "Created"
        if self._failed:
            return "Failed!"
        return "Pending"

    def raiseIfNeeded(self):
        if self.isFailed():
            raise self._exception
        if self._pending_subverted:
            raise BackupInProgress()

    def isStale(self):
        if self._pending_subverted:
            delta = timedelta(seconds=self._config.get(
                Setting.BACKUP_STALE_SECONDS))
            if self._time.now() > self.startTime() + delta:
                return True
        if not self.isFailed():
            return False
        delta = timedelta(seconds=self._config.get(
            Setting.FAILED_BACKUP_TIMEOUT_SECONDS))
        staleTime = self.getFailureTime() + delta
        return self._time.now() >= staleTime
    
    def attach_logs(self, logs):
        self._logs = logs

    def error_logs(self):
        if self._logs:
            return self._logs
        else:
            return None

    def madeByTheAddon(self):
        return True


@singleton
class HaSource(BackupSource[HABackup], Startable):
    """
    Stores logic for interacting with the supervisor add-on API
    """
    @inject
    def __init__(self, config: Config, time: Time, ha: HaRequests, info: GlobalInfo, stopper: AddonStopper, estimator: Estimator, data_cache: DataCache):
        super().__init__()
        self.config: Config = config
        self._data_cache = data_cache
        self.backup_thread: Optional[Thread] = None
        self.pending_backup_error: Optional[Exception] = None
        self.pending_backup_slug: Optional[str] = None
        self.self_info = None
        self.host_info = None
        self.ha_info = None
        self.super_info = None
        self.mount_info = {}
        self.lock: Lock = Lock()
        self.time = time
        self.harequests = ha
        self.last_slugs = set()
        self.retained = []
        self.cached_retention = {}
        self._info = info
        self.pending_options = {}
        self.stopper = stopper
        self.estimator = estimator
        self._addons = {}
        self._changes_from_last_query = False

        # This lock should be used for _ANYTHING_ that interacts with self._pending_backup
        self._pending_backup_lock = asyncio.Lock()
        self.pending_backup: Optional[PendingBackup] = None
        self._pending_backup_task = None
        self._initialized = False
        # One refresh at a time: getconfig, init and create each start one.
        # Otherwise a refresh that read the options before another one
        # corrected "Delete ignored backups after" applied the old value again,
        # or corrected it twice.
        self._refresh_lock = asyncio.Lock()
        # _fixDeleteIgnoredSeconds has run since the add-on started.
        self._delete_ignored_checked = False
        # Its notification, (title, message), until sent: retried on each
        # refresh, DELETE_IGNORED_NOTICE_TRIES times in all.
        self._delete_ignored_notice: Optional[Tuple[str, str]] = None
        self._delete_ignored_notice_tries = 0

    def isInitialized(self):
        return self._initialized

    async def check(self) -> bool:
        pending = self.pending_backup
        if pending and pending.isStale():
            self.trigger()
        return await super().check()

    def icon(self) -> str:
        return "home-assistant"

    def name(self) -> str:
        return SOURCE_HA

    def title(self) -> str:
        return "Home Assistant"

    def maxCount(self) -> None:
        return self.config.get(Setting.MAX_BACKUPS_IN_HA)

    def enabled(self) -> bool:
        return True

    def freeSpace(self):
        return self.estimator.getBytesFree()

    async def create(self, options: CreateOptions) -> AbstractBackup:
        # Make sure instance info is up-to-date, for the backup name
        await self._refreshInfo()

        # Set a default name if it was unspecified
        if options.name_template is None or len(options.name_template) == 0:
            options.name_template = self.config.get(Setting.BACKUP_NAME)

        # Build the backup request json, get type, etc
        request, type_name, protected = self._buildBackupInfo(
            options)

        async with self._pending_backup_lock:
            # Check if a backup is already in progress
            if self.pending_backup:
                if not self.pending_backup.isFailed() and not self.pending_backup.isComplete():
                    logger.info("A backup was already in progress")
                    raise BackupInProgress()

            # try to stop addons
            await self.stopper.stopAddons(self.self_info['slug'])

            # Create the backup palceholder object
            self.pending_backup = PendingBackup(
                type_name, protected, options, request, self.config, self.time)
            logger.info("Requesting a new backup")
            self._pending_backup_task = asyncio.create_task(self._requestAsync(
                self.pending_backup), name="Pending Backup Requester")
            await asyncio.wait({self._pending_backup_task}, timeout=self.config.get(Setting.NEW_BACKUP_TIMEOUT_SECONDS))
            self.pending_backup.raiseIfNeeded()

            # There is not other backup in progress, so assume its been requested.
            pending = self._data_cache.backup(KEY_PENDING)
            pending[KEY_NAME] = request['name']
            pending[KEY_CREATED] = options.when.isoformat()
            pending[KEY_LAST_SEEN] = self.time.now().isoformat()
            self._data_cache.makeDirty()
            if self.pending_backup.isComplete():
                # It completed while we waited, so just query the new backup
                ret = await self.harequests.backup(self.pending_backup.createdSlug())
                if options.note is not None:
                    ret.setNote(options.note)
                self.setDataCacheInfo(ret)
                self._data_cache.backup(ret.slug())[KEY_I_MADE_THIS] = True
                return ret
            else:
                return self.pending_backup

    def _isHttp400(self, e):
        if isinstance(e, ClientResponseError):
            return e.status == 400
        return False

    async def start(self):
        try:
            await self.init()
        except Exception:
            pass

    async def stop(self):
        if self._pending_backup_task:
            self._pending_backup_task.cancel()
            await asyncio.wait([self._pending_backup_task])

    @property
    def needsSpaceCheck(self):
        if not self.harequests.supportsMountInfo:
            return True
        if self.config.get(Setting.BACKUP_STORAGE) == 'local-disk':
            return True
        if self.mount_info.get("default_backup_mount") is None and len(self.config.get(Setting.BACKUP_STORAGE)) == 0:
            return True
        return False

    @property
    def query_had_changes(self):
        return self._changes_from_last_query

    async def get(self) -> Dict[str, AbstractBackup]:
        if not self._initialized:
            await self.init()
        else:
            # Always ensure the supervisor version is fresh before makign any other requests
            self.super_info = await self.harequests.supervisorInfo()
        slugs = set()
        retained = []
        backups: Dict[str, AbstractBackup] = {}
        query = await self.harequests.backups()

        # Different supervisor version use different names for the list of backups
        backup_list = []
        if NECESSARY_OLD_BACKUP_PLURAL_NAME in query:
            backup_list = query[NECESSARY_OLD_BACKUP_PLURAL_NAME]
        if 'backups' in query:
            backup_list = query['backups']

        for backup in backup_list:
            slug = backup['slug']
            slugs.add(slug)
            item = await self.harequests.backup(slug)
            if slug in self.pending_options:
                item.setOptions(self.pending_options[slug])
            backups[slug] = item
            if item.retained():
                retained.append(item.slug())
            self.setDataCacheInfo(item)
        if self.pending_backup:
            async with self._pending_backup_lock:
                if self.pending_backup:
                    if self.pending_backup.isStale():
                        # The backup is stale, so just let it die.
                        self._killPending()
                    elif self.pending_backup.isComplete() and self.pending_backup.createdSlug() in backups:
                        # Copy over options if we got the requested backup.
                        backups[str(self.pending_backup.createdSlug())].setOptions(
                            self.pending_backup.getOptions())
                        if self.pending_backup.note() is not None:
                            # Save the note with the now known slug
                            await self.note(backups[str(self.pending_backup.createdSlug())], self.pending_backup.note())
                        self._killPending()
                    elif self.last_slugs.symmetric_difference(slugs).intersection(slugs):
                        # New backup added, ignore pending backup.
                        sorted = list(backups.values())
                        sorted.sort(key=lambda b: b.date())
                        if self.pending_backup.note() is not None and len(sorted) > 0:
                            # Save the note with the newest backup
                            await self.note(sorted[-1], self.pending_backup.note())
                        self._killPending()
            if self.pending_backup:
                backups[self.pending_backup.slug()] = self.pending_backup
        for slug in retained:
            if not self.config.isRetained(slug):
                self.config.setRetained(slug, False)
        self._changes_from_last_query = self.last_slugs != slugs
        self.last_slugs = slugs
        return backups

    def setDataCacheInfo(self, backup: HABackup):
        if backup.slug() not in self._data_cache.backups:
            # its a new backup, so we need to create a record for it
            pending = self._data_cache.backups.get(KEY_PENDING, {})
            pending_created = self.time.parse(pending.get(KEY_CREATED, self.time.now().isoformat()))

            # If the backup has the same name as the one we created and it was created within a day
            # of the requested time, then assume the addon created it.
            self_created = backup.name() == pending.get(KEY_NAME, None) and abs((pending_created - backup.date()).total_seconds()) < timedelta(days=1).total_seconds()

            stored_backup = self._data_cache.backup(backup.slug())
            stored_backup[KEY_I_MADE_THIS] = self_created
            stored_backup[KEY_CREATED] = backup.date().isoformat()
            stored_backup[KEY_NAME] = backup.name()
            stored_backup[KEY_NOTE] = backup.note()
            if self_created:
                # Remove the pending backup info from the cache so it doesn't get reused.
                del self._data_cache.backups[KEY_PENDING]
        # bump the last seen time
        self._data_cache.backup(backup.slug())[KEY_LAST_SEEN] = self.time.now().isoformat()
        self._data_cache.makeDirty()

    async def delete(self, backup: Backup):
        slug = self._validateBackup(backup).slug()
        logger.info("Deleting '{0}' from Home Assistant".format(backup.name()))
        await self.harequests.delete(slug)
        backup.removeSource(self.name())

    async def ignore(self, backup: Backup, ignore: bool):
        slug = self._validateBackup(backup).slug()
        logger.info("Updating ignore settings for '{0}'".format(backup.name()))
        self._data_cache.backup(slug)[KEY_IGNORE] = ignore
        self._data_cache.makeDirty()

    async def note(self, backup, note: Union[str, None]) -> None:
        if isinstance(backup, HABackup):
            validated = backup
        else:
            validated = self._validateBackup(backup)
        logger.debug(f"Adding a note to ha backup '{validated.name()}'")
        if isinstance(validated, PendingBackup):
            # The ntoe will get set once the backup is created and we know the slug
            validated.setNote(note)
        else:
            self._data_cache.backup(validated.slug())[KEY_NOTE] = note
            self._data_cache.makeDirty()
            validated.setNote(note)
        return await super().note(backup, note)

    async def save(self, backup: Backup, source: AsyncHttpGetter) -> HABackup:
        logger.info("Downloading '{0}'".format(backup.name()))
        self._info.upload(0)
        resp = None
        try:
            backup.overrideStatus("Loading {0}%", source)
            backup.setUploadSource(self.title(), source)
            async with source:
                with aiohttp.MultipartWriter('mixed') as mpwriter:
                    mpwriter.append(source, {'CONTENT-TYPE': 'application/tar'})  # type: ignore
                    resp = await self.harequests.upload(mpwriter)
            backup.clearStatus()
            backup.clearUploadSource()
        except Exception as e:
            logger.printException(e)
            backup.overrideStatus("Failed!")
            backup.uploadFailure(logger.formatException(e))
        if resp and 'slug' in resp and resp['slug'] == backup.slug():
            self.config.setRetained(backup.slug(), True)
            return await self.harequests.backup(backup.slug())
        else:
            raise UploadFailed()

    async def read(self, backup: Backup) -> IOBase:
        item = self._validateBackup(backup)
        return await self.harequests.download(item.slug())

    async def retain(self, backup: Backup, retain: bool) -> None:
        item: HABackup = self._validateBackup(backup)
        item._retained = retain
        self.config.setRetained(backup.slug(), retain)

    async def init(self):
        await self._refreshInfo()
        self._initialized = True

    async def refresh(self):
        await self._refreshInfo()

    async def _refreshInfo(self) -> None:
        async with self._refresh_lock:
            try:
                self.self_info = await self.harequests.selfInfo()
                self.host_info = await self.harequests.info()
                self.ha_info = await self.harequests.haInfo()
                self.super_info = await self.harequests.supervisorInfo()
                self.mount_info = await self.harequests.mountInfo()

                addon_info = ensureKey("addons", await self.harequests.getAddons(), "Supervisor Metadata")
                self.config.update(await self._fixDeleteIgnoredSeconds(
                    ensureKey("options", self.self_info, "addon metdata")))
                if self.config.mustSaveUpgradeChanges():
                    LOGGER.info("The configuration format has changed in this version of the addon and your configuration will be automatically updated")
                    options = {}
                    for option in self.config.getAllConfig().keys():
                        options[option.value] = self.config.get(option)
                    await self.harequests.updateConfig(options)
                    self.config.persistedChanges()

                self._info.ha_port = ensureKey(
                    "port", self.ha_info, "Home Assistant metadata")
                self._info.ha_ssl = ensureKey(
                    "ssl", self.ha_info, "Home Assistant metadata")
                self._info.addons = addon_info
                self._info.slug = ensureKey(
                    "slug", self.self_info, "addon metdata")
                self._info.url = self.getAddonUrl()

                self._addons = {}
                for addon in addon_info:
                    self._addons[addon.get('slug', "default")] = addon

                self._info.addDebugInfo("self_info", self.self_info)
                self._info.addDebugInfo("host_info", self.host_info)
                self._info.addDebugInfo("ha_info", self.ha_info)
                self._info.addDebugInfo("super_info", self.super_info)
            except Exception as e:
                logger.debug("Failed to connect to supervisor")
                logger.debug(logger.formatException(e))
                raise e

    def _mustCheckDeleteIgnored(self) -> bool:
        if self._delete_ignored_checked:
            return False
        cache = self._data_cache
        # This start upgraded from a version with the bug, e.g. after going back
        # to v0.3.0 and up again: a value saved meanwhile may have it.
        if Version.default() < cache.previousVersion <= LAST_SECONDS_BUG_VERSION \
                and cache.previousVersion < cache.currentVersion:
            return True
        # Otherwise once per install, and only one that ran a version with the
        # bug: since the fix, a value can be chosen on purpose.
        return not cache.checkFlag(UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS) \
            and cache.firstVersion <= LAST_SECONDS_BUG_VERSION

    @staticmethod
    def _deleteIgnoredShown(options: Dict[str, Any]) -> str:
        """The value as the settings form shows it, e.g. "30 days" or "2 hours"."""
        return Setting.DELETE_IGNORED_AFTER_DAYS.validator().formatForUi(
            options[Setting.DELETE_IGNORED_AFTER_DAYS.key()])

    async def _fixDeleteIgnoredSeconds(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """See deleteIgnoredTypedAsSeconds."""
        if self._delete_ignored_notice is not None:
            # A notification from an earlier refresh still has to be sent.
            if await self._sendDeleteIgnoredNotice():
                self._deleteIgnoredChecked()
            return options
        if not self._mustCheckDeleteIgnored():
            return options
        found = deleteIgnoredTypedAsSeconds(options)
        sure = False
        if found is not None:
            typed, sure = found
            if sure:
                options = dict(options)
                options[Setting.DELETE_IGNORED_AFTER_DAYS.key()] = typed
                try:
                    await self.harequests.updateConfig(options)
                except Exception as e:
                    # Run with the corrected value anyway, and save it on the
                    # next refresh: failing here would stop every sync.
                    logger.warning("Couldn't save the corrected 'Delete ignored backups after' ({0} days); will try "
                                   "again.  {1}".format(formatNumber(typed), logger.formatException(e)))
                    return options
                logger.warning("'Delete ignored backups after' was saved as {0} seconds, because an earlier "
                               "version's web UI read a plain number as seconds.  Changed it to {0} days."
                               .format(formatNumber(typed)))
                title, message = DELETE_IGNORED_FIXED_TITLE, DELETE_IGNORED_FIXED_MESSAGE
            else:
                logger.warning("'Delete ignored backups after' is {0}, which is also what typing {1} in an earlier "
                               "version's web UI saved, reading it as seconds.  If {1} was meant as days, set it "
                               "again.".format(self._deleteIgnoredShown(options), formatNumber(typed)))
                title, message = DELETE_IGNORED_CHECK_TITLE, DELETE_IGNORED_CHECK_MESSAGE
            # Tell the user only if it was deleting backups: with both ignore
            # options off the setting has no effect.  (self.config still holds
            # the options from startup or the last refresh: the same ignore
            # settings, since only this one value is being corrected.)
            if self.config.get(Setting.IGNORE_OTHER_BACKUPS) or self.config.get(Setting.IGNORE_UPGRADE_BACKUPS):
                self._delete_ignored_notice = (title, message.format(
                    typed=formatNumber(typed), shown=self._deleteIgnoredShown(options)))
                self._delete_ignored_notice_tries = 0
        # A corrected value is done with, whether or not the notification got
        # through (it's sent again on later refreshes).  A value only asked
        # about isn't until the user has been told: nothing else tells them,
        # so after a restart the check runs again.
        if await self._sendDeleteIgnoredNotice() or sure:
            self._deleteIgnoredChecked()
        return options

    async def _sendDeleteIgnoredNotice(self) -> bool:
        """True once there's nothing left to send: sent, or given up on."""
        if self._delete_ignored_notice is None:
            return True
        title, message = self._delete_ignored_notice
        try:
            await self.harequests.sendNotification(title, message, DELETE_IGNORED_FIXED_NOTIFICATION_ID)
        except Exception as e:
            self._delete_ignored_notice_tries += 1
            if self._delete_ignored_notice_tries < DELETE_IGNORED_NOTICE_TRIES:
                logger.warning("Couldn't send the notification about 'Delete ignored backups after'; will try "
                               "again.  {0}".format(logger.formatException(e)))
                return False
            logger.warning("Couldn't send the notification about 'Delete ignored backups after' in {0} tries; "
                           "giving up.  It said: {1}".format(DELETE_IGNORED_NOTICE_TRIES, message))
        self._delete_ignored_notice = None
        return True

    def _deleteIgnoredChecked(self):
        self._delete_ignored_checked = True
        self._data_cache.addFlag(UpgradeFlags.FIXED_DELETE_IGNORED_SECONDS)
        self._data_cache.saveIfDirty()

    def addonHasLogo(self, slug):
        return self._addons.get(slug, {}).get('logo', False)

    def getAddonUrl(self):
        """
        Returns the relative path to the add-on, for the purpose of linking to the add-on page from within Home Assistant.
        """
        if self._info.slug is None:
            return ""
        return "/hassio/ingress/" + str(self._info.slug)

    def getHostInfo(self):
        if not self.isInitialized():
            return {}
        return self.host_info

    def getFullAddonUrl(self):
        if not self.isInitialized():
            return ""
        return self._haUrl() + "hassio/ingress/" + str(self._info.slug)

    def getHomeAssistantUrl(self):
        if not self.isInitialized():
            return ""
        return self._haUrl()

    def _haUrl(self):
        if self._info.ha_ssl:
            protocol = "https://"
        else:
            protocol = "http://"
        return "".join([protocol, "{host}:", str(self._info.ha_port), "/"])

    def _validateBackup(self, backup) -> HABackup:
        item: HABackup = backup.getSource(self.name())
        if not item:
            raise LogicError(
                "Requested to do something with a backup from Home Assistant, but the backup has no Home Assistant source")
        return item

    def _killPending(self):
        self.pending_backup = None
        if self._pending_backup_task and not self._pending_backup_task.done():
            self._pending_backup_task.cancel()

    def postSync(self):
        self.stopper.allowRun()
        self.stopper.isBackingUp(self.pending_backup is not None)

    async def _requestAsync(self, pending: PendingBackup, start=[]) -> None:
        try:
            result = await asyncio.wait_for(self.harequests.createBackup(pending._request_info), timeout=self.config.get(Setting.PENDING_BACKUP_TIMEOUT_SECONDS))
            slug = ensureKey(
                "slug", result, "supervisor's create backup response")
            pending.complete(slug)
            self.config.setRetained(
                slug, pending.getOptions().retain_sources.get(self.name(), False))
            logger.info("Backup finished")
        except Exception as e:
            if self._isHttp400(e):
                logger.warning("A backup was already in progress")
                pending.setPendingUnknown()
            else:
                logger.error("Backup failed:")
                logger.printException(e)
                pending.failed(e, self.time.now())
            try:
                pending.attach_logs(await self.harequests.getSuperLogs())
            except Exception as e:
                logger.error("Failed to get sueprvisor logs after failed backup request")
                logger.printException(e)
        finally:
            await self.stopper.startAddons()
            self.trigger()

    def _buildBackupInfo(self, options: CreateOptions):
        addons: List[str] = []
        for addon in self.super_info.get('addons', {}):
            addons.append(addon['slug'])
        request_info: Dict[str, Any] = {
            'addons': [],
            'folders': [],
        }
        if self.config.get(Setting.EXCLUDE_HA_DATABASE):
            request_info['homeassistant_exclude_database'] = True
        folders = list(map(lambda f: f['slug'], FOLDERS))
        type_name = "Full"
        for folder in folders:
            if folder not in self.config.get(Setting.EXCLUDE_FOLDERS):
                request_info['folders'].append(folder)
            else:
                type_name = "Partial"
        for addon in addons:
            if addon not in self.config.get(Setting.EXCLUDE_ADDONS):
                request_info['addons'].append(addon)
            else:
                type_name = "Partial"
        if type_name == "Full":
            del request_info['addons']
            del request_info['folders']
        protected = False
        password = Password(self.config).resolve()
        if password:
            request_info['password'] = password
        name = BackupName().resolve(type_name, options.name_template,
                                    self.time.toLocal(options.when), self.host_info)
        request_info['name'] = name

        if self.harequests.supportsMountInfo:
            # Validate the mount location and set it if necessary
            mount_name = self.config.get(Setting.BACKUP_STORAGE)

            # Default is to use Home Assistant's default configured mount
            if not mount_name or len(mount_name) == 0:
                ha_default = self.mount_info.get("default_backup_mount", None)
                if ha_default:
                    mount_name = ha_default
                else:
                    mount_name = "local-disk"

            if mount_name != "local-disk":
                # check to make sure the mount location is valid
                for mount in self.mount_info.get("mounts", []):
                    if mount.get("name", None) == mount_name:
                        if mount.get("state", False) != "active":
                            raise InactiveNetworkStorageError(mount_name)
                        request_info['location'] = mount_name
                        break
                if request_info.get('location', None) is None:
                    raise UnknownNetworkStorageError(mount_name)
            else:
                request_info['location'] = None
        return request_info, type_name, protected
