from datetime import datetime

from aiohttp import ClientSession
from injector import inject, singleton

from backup.config import Config, Setting, VERSION, _DEFAULTS, PRIVATE
from backup.exceptions import KnownError
from backup.util import GlobalInfo, Resolver
from backup.time import Time
from backup.worker import Worker
from backup.logger import getLogger, getHistory
from backup.ha import HaRequests, HaSource
from backup.model import Coordinator, DestinationPrecache

logger = getLogger(__name__)
ERROR_LOG_LENGTH = 30


@singleton
class DebugWorker(Worker):
    """
    Builds the on-demand bug report used by the Web UI's "make an issue" flow.

    Unlike the upstream Google Drive add-on, this fork deliberately does NOT
    phone home: there is no periodic health check against the upstream author's
    token servers (habackup.io) and no DNS/ping probe of Google's servers, both
    of which made no sense for a Proton Drive backend and would have leaked the
    user's traffic to third parties they never chose.  The only network access
    happens when the user explicitly clicks "make an issue", which assembles the
    report below locally and hands it back to the browser to file by hand.
    """

    @inject
    def __init__(self, time: Time, info: GlobalInfo, config: Config, resolver: Resolver, session: ClientSession, ha: HaRequests, coord: Coordinator, ha_source: HaSource, precache: DestinationPrecache):
        super().__init__("Debug Worker", self.doWork, time, interval=10)
        self.time = time
        self._info = info
        self.config = config
        self.ha = ha
        self.ha_source = ha_source
        self.coord = coord
        self._precache = precache

    async def doWork(self):
        # Intentionally a no-op.  See the class docstring: this fork does not
        # contact any remote server in the background.
        pass

    async def buildErrorReport(self, error):
        config_special = {}
        for setting in Setting:
            if self.config.get(setting) != _DEFAULTS[setting]:
                if setting in PRIVATE:
                    config_special[str(setting)] = "REDACTED"
                else:
                    config_special[str(setting)] = self.config.get(setting)
        report = {}
        report['config'] = config_special
        report['time'] = self.formatDate(self.time.now())
        report['start_time'] = self.formatDate(self._info._start_time)
        report['addon_version'] = VERSION
        report['failure_time'] = self.formatDate(self._info._last_failure_time)
        report['failure_count'] = self._info._failures
        report['sync_last_start'] = self.formatDate(self._info._last_sync_start)
        report['sync_count'] = self._info._syncs
        report['sync_success_count'] = self._info._successes
        report['sync_last_success'] = self.formatDate(self._info._last_sync_success)
        report['upload_count'] = self._info._uploads
        report['upload_last_size'] = self._info._last_upload_size
        report['upload_last_attempt'] = self.formatDate(self._info._last_upload)
        report['next_sync'] = self.formatDate(self.coord.nextSyncAttempt())
        report['next_backup'] = self.formatDate(self.coord.nextBackupTime())
        report['next_cache_warm'] = self.formatDate(self._precache.getNextWarmDate())
        report['time_offset'] = self._time.offset.total_seconds()

        report['debug'] = self._info.debug
        report['version'] = VERSION
        report['error'] = error
        report['client'] = self.config.clientIdentifier()

        if self.ha_source.isInitialized() and self.ha_source.host_info and self.ha_source.super_info and self.ha_source.ha_info:
            report["super_version"] = self.ha_source.host_info.get('supervisor', "None")
            report["hassos_version"] = self.ha_source.host_info.get('hassos', "None")
            report["docker_version"] = self.ha_source.host_info.get('docker', "None")
            report["machine"] = self.ha_source.host_info.get('machine', "None")
            report["supervisor_channel"] = self.ha_source.host_info.get('channel', "None")
            report["arch"] = self.ha_source.super_info.get('arch', "None")
            report["timezone"] = self.ha_source.super_info.get('timezone', "None")
            report["ha_version"] = self.ha_source.ha_info.get('version', "None")
        else:
            report["super_version"] = "Uninitialized"
            report["arch"] = "Uninitialized"
            report["timezone"] = "Uninitialized"
            report["ha_version"] = "Uninitialized"
        report["backups"] = self.coord.buildBackupMetrics()
        return report

    async def buildBugReportData(self, error):
        report = await self.buildErrorReport(error)
        report['addon_logs'] = "\n".join(b for a, b in list(getHistory(0, False))[-ERROR_LOG_LENGTH:])
        try:
            report['super_logs'] = "\n".join((await self.ha.getSuperLogs()).split("\n")[-ERROR_LOG_LENGTH:])
        except Exception as e:
            report['super_logs'] = logger.formatException(e)
        try:
            report['core_logs'] = "\n".join((await self.ha.getCoreLogs()).split("\n")[-ERROR_LOG_LENGTH:])
        except Exception as e:
            report['core_logs'] = logger.formatException(e)
        return report

    def formatDate(self, date: datetime):
        if date is None:
            return "Never"
        else:
            return date.isoformat()
