import asyncio
import hmac
import re
import ssl
import json
from datetime import timedelta
from os.path import abspath, join
from typing import Any, Dict

import aiohttp_jinja2
import jinja2
from aiohttp import BasicAuth, hdrs, web, ClientResponseError
from aiohttp.web import HTTPException, Request, HTTPNotFound
from injector import inject, singleton

from backup.config import Config, Setting, CreateOptions, BoolValidator, Startable, VERSION, isStaging
from backup.const import SOURCE_PROTON_DRIVE, SOURCE_HA, GITHUB_BUG_TEMPLATE, FOLDERS
from backup.model import Coordinator, Backup, AbstractBackup
from backup.exceptions import KnownError, ensureKey, PleaseWait
from backup.util import GlobalInfo, Estimator, DataCache
from backup.file import File
from backup.ha import HaSource, PendingBackup, BACKUP_NAME_KEYS, HaRequests, HaUpdater
from backup.ha import Password
from backup.time import Time
from backup.worker import Trigger
from backup.logger import getLogger, getHistory, TraceLogger
from backup.debugworker import DebugWorker
from backup.proton import ProtonSource, ProtonCli
from backup.proton.exceptions import ProtonNotAuthenticated, ProtonConnectionError
from .debug import Debug

logger = getLogger(__name__)

MIME_TEXT_HTML = "text/html"
MIME_JSON = "application/json"


@singleton
class UiServer(Trigger, Startable):
    """
    Trimmed web UI for the Proton Drive backup addon.

    It reuses the original coordinator-backed handlers (create/sync/delete/
    retain/download/upload/config), but the Google OAuth flow is replaced with a
    simple Proton authentication panel that reflects the `proton-drive` CLI
    session state and tells the user how to sign in.
    """

    @inject
    def __init__(self, debug: Debug, coord: Coordinator, ha_source: HaSource, harequests: HaRequests,
                 time: Time, config: Config, global_info: GlobalInfo, estimator: Estimator,
                 proton: ProtonSource, cli: ProtonCli, debug_worker: DebugWorker,
                 data_cache: DataCache, haupdater: HaUpdater):
        super().__init__()
        self.runners = []
        self._coord = coord
        self._time = time
        self.config: Config = config
        self.last_log_index = 0
        self.running = False
        self._harequests = harequests
        self._global_info = global_info
        self._ha_source = ha_source
        self._starts = 0
        self._estimator = estimator
        self._debug = debug
        self.debug_worker = debug_worker
        self._proton = proton
        self._cli = cli
        self.ignore_other_turned_on = False
        self._data_cache = data_cache
        self._haupdater = haupdater
        self._upload_event = asyncio.Event()

    def name(self):
        return "UI Server"

    def base_context(self):
        return {
            'version': VERSION,
            'backgroundColor': self.config.get(Setting.BACKGROUND_COLOR),
            'accentColor': self.config.get(Setting.ACCENT_COLOR),
            'coordEnabled': self._coord.enabled(),
        }

    # --- Status ----------------------------------------------------------------

    async def getstatus(self, request) -> Any:
        return web.json_response(await self.buildStatusInfo())

    async def buildStatusInfo(self):
        status: Dict[Any, Any] = {}
        status['backups'] = [self.getBackupDetails(b) for b in self._coord.backups()]
        status['ha_url_base'] = self._ha_source.getHomeAssistantUrl()
        status['restore_backup_path'] = "hassio/backups"
        next = self._coord.nextBackupTime()
        if next is None:
            status['next_backup_text'] = "Disabled"
            status['next_backup_machine'] = ""
            status['next_backup_detail'] = "Disabled"
        elif next < self._time.now():
            status['next_backup_text'] = self._time.formatDelta(self._time.now())
            status['next_backup_machine'] = self._time.asRfc3339String(self._time.now())
            status['next_backup_detail'] = self._time.toLocal(self._time.now()).strftime("%c")
        else:
            status['next_backup_text'] = self._time.formatDelta(next)
            status['next_backup_machine'] = self._time.asRfc3339String(next)
            status['next_backup_detail'] = self._time.toLocal(next).strftime("%c")
        not_ignored = list(filter(lambda s: not s.ignore(), self._coord.backups()))
        if len(not_ignored) > 0:
            latest = not_ignored[-1].date()
            status['last_backup_text'] = self._time.formatDelta(latest)
            status['last_backup_machine'] = self._time.asRfc3339String(latest)
            status['last_backup_detail'] = self._time.toLocal(latest).strftime("%c")
        else:
            status['last_backup_text'] = "Never"
            status['last_backup_machine'] = ""
            status['last_backup_detail'] = "Never"

        status['last_error'] = None
        if self._global_info._last_error is not None and self._global_info.isErrorSuppressed():
            status['last_error'] = self.processError(self._global_info._last_error)
        status["last_error_count"] = self._global_info.failureCount()
        status["ignore_errors_for_now"] = self._global_info.ignoreErrorsForNow()
        status["syncing"] = self._coord.isSyncing()
        status["ignore_sync_error"] = self._coord.isWorkingThroughUpload()
        status["firstSync"] = self._global_info._first_sync
        status["backup_name_template"] = self.config.get(Setting.BACKUP_NAME)
        status['sources'] = self._coord.buildBackupMetrics()
        status['enable_proton_upload'] = self.config.get(Setting.ENABLE_PROTON_UPLOAD)
        status['proton_authenticated'] = self._cli.isAuthenticated()
        status['proton_auth_warning'] = self._cli.authWarning()
        status['proton_login_in_progress'] = self._cli.loginInProgress()
        status['proton_login_url'] = self._cli.loginUrl()
        status['proton_login_error'] = self._cli.loginError()
        status['proton_folder'] = self._proton.folderName()
        status['backup_cooldown_active'] = self._coord.isWaitingForStartup()
        name_keys = {}
        for key in BACKUP_NAME_KEYS:
            name_keys[key] = BACKUP_NAME_KEYS[key]("Full", self._time.now(), self._ha_source.getHostInfo())
        status['backup_name_keys'] = name_keys
        return status

    def getBackupDetails(self, backup: Backup):
        ha = backup.getSource(SOURCE_HA)
        sources = []
        for source_key in backup.sources:
            source: AbstractBackup = backup.sources[source_key]
            sources.append({
                'name': source.name(),
                'key': source_key,
                'size': source.size(),
                'retained': source.retained(),
                'delete_next': backup.getPurges().get(source_key) or False,
                'slug': backup.slug(),
                'ignored': source.ignore(),
            })
        data = {
            'name': backup.name(),
            'slug': backup.slug(),
            'size': backup.sizeString(),
            'status': backup.status(),
            'date': self._time.toLocal(backup.date()).strftime("%c"),
            'createdAt': self._time.formatDelta(backup.date()),
            'isPending': ha is not None and type(ha) is PendingBackup,
            'protected': backup.protected(),
            'type': backup.backupType(),
            'folders': backup.details().get("folders", []),
            'addons': self.formatAddons(backup.details()),
            'sources': sources,
            'haVersion': False if backup.version() is None else backup.version(),
            'uploadable': backup.getSource(SOURCE_HA) is None and len(backup.sources) > 0,
            'restorable': backup.getSource(SOURCE_HA) is not None,
            'status_detail': backup.getStatusDetail(),
            'upload_info': backup.getUploadInfo(self._time),
            'ignored': backup.ignore(),
            'timestamp': backup.date().timestamp(),
            'note': backup.note()
        }
        if isinstance(ha, PendingBackup):
            data["super_logs"] = ha.error_logs()
        return data

    def formatAddons(self, backup_data):
        addons = []
        for addon in backup_data.get("addons", []):
            addons.append({
                'name': addon.get('name', "Unknown"),
                'slug': addon.get("slug", "unknown"),
                'version': addon.get("version", ""),
                'size': self._estimator.asSizeString(float(addon.get("size", 0)) * 1024 * 1024),
            })
        return addons

    # --- Proton authentication -------------------------------------------------

    async def protonauth(self, request: Request):
        """Re-check (and report) the Proton Drive CLI session state."""
        try:
            authenticated = await self._cli.checkAuth()
        except Exception as e:
            return web.json_response({
                'authenticated': False,
                'message': str(e),
            })
        if authenticated:
            self._coord.markAuthChanged()
        return web.json_response({
            'authenticated': authenticated,
            'message': "Signed in to Proton Drive." if authenticated else
                       "Not signed in. Click Sign in to authorize with Proton Drive.",
        })

    async def protonlogin(self, request: Request):
        """Start an interactive Proton sign-in and return the link to open."""
        try:
            url = await self._cli.startLogin()
        except KnownError as e:
            return web.json_response({'ok': False, 'message': e.message()})
        except Exception as e:
            logger.printException(e)
            return web.json_response({'ok': False, 'message': str(e)})
        return web.json_response({
            'ok': True,
            'url': url,
            'message': "Open this link, sign in to Proton (including 2-factor if "
                       "enabled), then keep this page open — it'll update "
                       "automatically.",
        })

    async def protonlogincancel(self, request: Request):
        await self._cli.cancelLogin()
        return web.json_response({'ok': True})

    async def protonlogout(self, request: Request):
        """Sign out of Proton Drive."""
        try:
            await self._proton.signOut()
        except ProtonConnectionError:
            return web.json_response({
                'ok': False,
                'message': "Couldn't sign out: Proton Drive is unreachable "
                           "(network problem). Try again once you're back online.",
            })
        except KnownError as e:
            return web.json_response({'ok': False, 'message': e.message()})
        self._coord.trigger()
        return web.json_response({'ok': True, 'message': "Signed out of Proton Drive."})

    # --- Backup operations -----------------------------------------------------

    async def backup(self, request: Request) -> Any:
        custom_name = request.query.get("custom_name", None)
        retain_proton = BoolValidator.strToBool(request.query.get("retain_proton", False))
        retain_ha = BoolValidator.strToBool(request.query.get("retain_ha", False))
        note = request.query.get("note", None)
        options = CreateOptions(self._time.now(), custom_name, {
            SOURCE_PROTON_DRIVE: retain_proton,
            SOURCE_HA: retain_ha
        }, note=note)
        backup = await self._coord.startBackup(options)
        return web.json_response({"message": "Requested backup '{0}'".format(backup.name())})

    async def deleteSnapshot(self, request: Request):
        data = await request.json()
        self._coord.getBackup(data['slug'])
        await self._coord.delete(data['sources'], data['slug'])
        return web.json_response({"message": "Deleted from {0} place(s)".format(len(data['sources']))})

    async def ignore(self, request: Request):
        data = await request.json()
        backup = self._coord.getBackup(data['slug'])
        await self._coord.ignore(data['slug'], data['ignore'])
        await self.startSync(request)
        if data['ignore']:
            return web.json_response({"message": "'{0}' will be ignored.".format(backup.name())})
        return web.json_response({"message": "'{0}' will be included.".format(backup.name())})

    async def retain(self, request: Request):
        data = await request.json()
        slug = data['slug']
        self._coord.getBackup(slug)
        await self._coord.retain(data['sources'], slug)
        return web.json_response({'message': "Updated the backup's settings"})

    async def note(self, request: Request):
        data = await request.json()
        slug = data['slug']
        self._coord.getBackup(slug)
        await self._coord.note(data.get("note", None), slug)
        return web.json_response({'message': "Updated the backup's settings"})

    async def confirmdelete(self, request: Request):
        always = BoolValidator.strToBool(request.query.get("always", False))
        self._global_info.allowMultipleDeletes()
        self._global_info.setIngoreErrorsForNow(True)
        if always:
            validated = self.config.validateUpdate({"confirm_multiple_deletes": False})
            await self._updateConfiguration(validated)
            await self.sync()
            return web.json_response({'message': 'Configuration updated, I\'ll never ask again'})
        await self.sync()
        return web.json_response({'message': 'Backups deleted this one time'})

    async def skipspacecheck(self, request: Request):
        self._global_info.setSkipSpaceCheckOnce(True)
        self._global_info.setIngoreErrorsForNow(True)
        await self.startSync(request)
        return web.json_response({'message': 'Done'})

    async def ignorestartupcooldown(self, request: Request):
        self._coord.ignoreStartupDelay()
        return await self.sync(request)

    # --- Sync ------------------------------------------------------------------

    async def sync(self, request: Request = None) -> Any:
        self._coord.clearCaches()
        await self._coord.sync()
        return await self.getstatus(request)

    async def _backgroundSync(self):
        # startSync fires this as a detached task, so its exception would
        # otherwise be unretrieved ("Task exception was never retrieved").  A
        # "sync now" request that arrives while a sync is already running is just
        # a no-op, not an error.
        try:
            await self._coord.sync()
        except PleaseWait:
            logger.debug("Ignoring sync request; a sync is already in progress")
        except Exception as e:
            logger.printException(e)

    async def startSync(self, request) -> Any:
        self._coord.clearCaches()
        asyncio.create_task(self._backgroundSync(), name="Sync from web request")
        await self._coord._sync_start.wait()
        return await self.getstatus(request)

    async def cancelSync(self, request: Request):
        await self._coord.cancel()
        return await self.getstatus(request)

    # --- Config ----------------------------------------------------------------

    async def getconfig(self, request: Request):
        await self._ha_source.refresh()
        current_config = {s.key(): self.config.getForUi(s) for s in Setting}
        default_config = {s.key(): s.default() for s in Setting}
        return web.json_response({
            'config': current_config,
            'addons': self._global_info.addons,
            'folders': FOLDERS,
            'defaults': default_config,
        })

    async def exposeserver(self, request: Request):
        expose = BoolValidator.strToBool(request.query.get("expose", False))
        if expose:
            # The extra server binds 0.0.0.0 and serves the full mutating API
            # (create/delete/download backups, start a Proton login).  Turn login
            # on by default when it's first exposed so it isn't unauthenticated on
            # the LAN out of the box; the user can still disable it deliberately.
            update = {Setting.EXPOSE_EXTRA_SERVER: True, Setting.REQUIRE_LOGIN: True}
        else:
            update = {Setting.EXPOSE_EXTRA_SERVER: False, Setting.USE_SSL: False, Setting.REQUIRE_LOGIN: False}
        validated = self.config.validateUpdate(update)
        await self._updateConfiguration(validated)
        File.touch(self.config.get(Setting.INGRESS_TOKEN_FILE_PATH))
        await self._ha_source.init()
        redirect = ""
        try:
            if request.url.port != self.config.get(Setting.INGRESS_PORT):
                redirect = self._ha_source.getFullAddonUrl()
        except Exception:
            pass
        return web.json_response({'message': 'Configuration updated', 'redirect': redirect})

    async def makeanissue(self, request: Request):
        if self._global_info._last_error is not None:
            error = logger.formatException(self._global_info._last_error)
        else:
            error = "No error could be identified automatically."
        data = await self.debug_worker.buildBugReportData(error)
        body = GITHUB_BUG_TEMPLATE
        for key in data:
            if isinstance(data[key], dict):
                body = body.replace("{" + key + "}", json.dumps(data[key], indent=4))
            else:
                body = body.replace("{" + key + "}", str(data[key]))
        return web.json_response({'markdown': body})

    async def saveconfig(self, request: Request) -> Any:
        data = await request.json()
        update = ensureKey("config", data, "the configuration update request")
        Password(self.config.getConfigFor(update)).resolve()
        validated, needUpdate = self.config.validate(update)
        message = await self._updateConfiguration(validated, trigger=False)
        try:
            await self.cancelSync(request)
            await self.startSync(request)
        except Exception:
            pass
        return web.json_response(message)

    async def _updateConfiguration(self, new_config, trigger=True):
        update = {key.key(): new_config[key] for key in new_config}
        old_proton_option = self.config.get(Setting.ENABLE_PROTON_UPLOAD)
        old_ignore_others_option = self.config.get(Setting.IGNORE_OTHER_BACKUPS)
        await self._harequests.updateConfig(update)
        self.config.update(new_config)
        if not old_ignore_others_option and self.config.get(Setting.IGNORE_OTHER_BACKUPS):
            self.ignore_other_turned_on = True
        self._haupdater.triggerRefresh()
        if trigger:
            self.trigger()
        return {
            'message': 'Settings saved',
            'warning': self._generationalCapWarning(),
            'reload_page': self.config.get(Setting.ENABLE_PROTON_UPLOAD) != old_proton_option
        }

    def _generationalCapWarning(self):
        slots = self.config.generationalSlotCount()
        if not slots:
            return None
        tight = []
        for setting, label in ((Setting.MAX_BACKUPS_IN_HA, "Home Assistant"),
                               (Setting.MAX_BACKUPS_IN_PROTON_DRIVE, "Proton Drive")):
            # With delete-after-upload the HA cap never applies.
            if setting == Setting.MAX_BACKUPS_IN_HA and self.config.get(Setting.DELETE_AFTER_UPLOAD):
                continue
            cap = self.config.get(setting)
            if 0 < cap < slots:
                tight.append('"Keep in {0}" is {1}'.format(label, cap))
        if not tight:
            return None
        warning = ("Your generational settings can keep up to {0} backups but {1}, "
                   "so the oldest generational backups will still be deleted.".format(
                       slots, " and ".join(tight)))
        logger.warning(warning)
        return warning

    # --- Upload / Download / Logs ---------------------------------------------

    async def _doUpload(self, slug):
        await self._coord.uploadBackups(slug)
        self._upload_event.set()

    async def upload(self, request: Request):
        slug = request.query.get("slug", "")
        asyncio.create_task(self._doUpload(slug))
        return web.json_response({'message': "Uploading backup in the background"})

    async def download(self, request: Request):
        slug = request.query.get("slug", "")
        backup = self._coord.getBackup(slug)
        stream = await self._coord.download(slug)
        await stream.setup()
        try:
            resp = web.StreamResponse()
            resp.content_type = 'application/tar'
            # backup.name() comes from the (user-controlled) backup metadata, so
            # strip characters that could break out of the header value before
            # putting it in Content-Disposition.
            safe_name = re.sub(r'[\r\n"\\]', "_", backup.name())
            resp.headers['Content-Disposition'] = 'attachment; filename="{}.tar"'.format(safe_name)
            resp.headers['Content-Length'] = str(stream.size())
            await resp.prepare(request)
            async for chunk in stream.generator(self.config.get(Setting.DEFAULT_CHUNK_SIZE)):
                await resp.write(chunk)
            await resp.write_eof()
            # aiohttp needs the prepared response handed back; returning None
            # makes it call .prepare() on None in finish_response and raise.
            return resp
        finally:
            # The Proton backend stages the backup to a temp file; make sure it
            # (and its temp dir) get cleaned up even if the client disconnects.
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()

    async def addonLogo(self, request: Request):
        slug = request.match_info.get('slug')
        if not self._ha_source.addonHasLogo(slug):
            raise HTTPNotFound()
        try:
            (content_type, data) = await self._harequests.getAddonLogo(slug)
            return web.Response(headers={hdrs.CONTENT_TYPE: content_type}, body=data)
        except ClientResponseError as e:
            return web.Response(status=e.status)

    async def log(self, request: Request) -> Any:
        format = request.query.get("format", "download")
        catchup = BoolValidator.strToBool(request.query.get("catchup", "False"))
        if not catchup:
            self.last_log_index = 0
        resp = web.StreamResponse()
        if format == "html":
            resp.content_type = 'text/html'
        else:
            resp.content_type = 'text/plain'
            resp.headers['Content-Disposition'] = 'attachment; filename="home-assistant-proton-drive-backup.log"'
        await resp.prepare(request)

        def content():
            if format == "html":
                yield "<html><head><title>Home Assistant Proton Drive Backup Log</title></head><body><pre>\n"
            for line in getHistory(self.last_log_index, format == "colored"):
                self.last_log_index = line[0]
                if line:
                    yield line[1].replace("\n", "   \n") + "\n"
            if format == "html":
                yield "</pre></body>\n"
        for line in content():
            await resp.write(line.encode())
        await resp.write_eof()
        return resp

    # --- Pages -----------------------------------------------------------------

    async def index(self, request: Request):
        response = aiohttp_jinja2.render_template("index.jinja2", request, self.base_context())
        response.headers['cache-control'] = 'no-store'
        return response

    async def favicon(self, request: Request):
        return web.FileResponse(abspath(join(__file__, "..", "..", "static", "images", "favicon.png")))

    # --- Server lifecycle ------------------------------------------------------

    async def run(self) -> None:
        await self.stop()
        app = web.Application(middlewares=[self.error_middleware])
        aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(self.filePath()))
        self._addRoutes(app)
        logger.info("Starting server on port {}".format(self.config.get(Setting.INGRESS_PORT)))
        await self._start_site(app, self.config.get(Setting.INGRESS_PORT))

        try:
            if self.config.get(Setting.EXPOSE_EXTRA_SERVER):
                ssl_context = None
                if self.config.get(Setting.USE_SSL):
                    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                    ssl_context.load_cert_chain(self.config.get(Setting.CERTFILE), self.config.get(Setting.KEYFILE))
                middleware = [self.error_middleware]
                if self.config.get(Setting.REQUIRE_LOGIN):
                    middleware.append(makeLoginMiddleware(self._time, self._harequests))
                elif not ssl_context:
                    logger.warning(
                        "The extra server on port %s is exposed without login OR SSL. "
                        "Anyone who can reach this port can create/delete/download your "
                        "backups. Enable 'require_login' unless this is intentional.",
                        self.config.get(Setting.PORT))
                extra_app = web.Application(middlewares=middleware)
                aiohttp_jinja2.setup(extra_app, loader=jinja2.FileSystemLoader(self.filePath()))
                self._addRoutes(extra_app)
                logger.info("Starting server on port {}".format(self.config.get(Setting.PORT)))
                await self._start_site(extra_app, self.config.get(Setting.PORT), ssl_context=ssl_context)
        except FileNotFoundError:
            logger.error("The configured SSL key or certificate files couldn't be found, so the extra server couldn't start. The add-on web UI is still available through ingress.")
        except ssl.SSLError:
            logger.error("Your SSL certificate or key couldn't be loaded, so the extra server couldn't start. The add-on web UI is still available through ingress.")
        logger.info("Server started")
        self.running = True
        self._starts += 1
        # Logs the cap-vs-plan warning for setups configured via YAML, which
        # never hit /saveconfig.
        self._generationalCapWarning()

    def _addRoutes(self, app):
        app.add_routes([web.static('/static/' + str(VERSION), abspath(join(__file__, "..", "..", "static")), append_version=True)])
        app.add_routes([web.get('/', self.index)])
        app.add_routes([web.get('/index.html', self.index)])
        app.add_routes([web.get('/index', self.index)])
        app.add_routes([web.get('/favicon.ico', self.favicon)])
        app.add_routes([web.get('/logo/{slug}', self.addonLogo)])
        handlers = [self.getstatus, self.protonauth, self.protonlogin, self.protonlogincancel,
                    self.protonlogout, self.backup, self.log,
                    self.sync, self.startSync, self.cancelSync,
                    self.getconfig, self.exposeserver, self.saveconfig,
                    self.confirmdelete, self.skipspacecheck, self.ignorestartupcooldown,
                    self.upload, self.download, self.deleteSnapshot, self.retain, self.note,
                    self.ignore, self.makeanissue]
        # The debug endpoints can simulate errors and shift the add-on's clock
        # (which drives backup scheduling/retention).  They're test-only tooling,
        # so only expose them on staging builds, never in a released add-on.
        if isStaging():
            handlers += [self._debug.simerror, self._debug.getTasks, self._debug.timeoffset]
        for handler in handlers:
            self._addRoute(app, handler)

    def _addRoute(self, app, method):
        app.add_routes([
            web.get("/" + method.__name__, method),
            web.post("/" + method.__name__, method)
        ])

    async def start(self):
        await self.run()

    async def _start_site(self, app, port, ssl_context=None):
        aiohttp_logger = TraceLogger("aiohttp.access")
        if self.config.get(Setting.TRACE_REQUESTS):
            runner = web.AppRunner(app, logger=aiohttp_logger, access_log=aiohttp_logger,
                                   access_log_format='%a %t "%r" %s %b "%{Referer}i" "%{User-Agent}i (%Tfs)"')
        else:
            runner = web.AppRunner(app)
        self.runners.append(runner)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port, ssl_context=ssl_context)
        await site.start()

    async def stop(self):
        for runner in self.runners:
            try:
                await runner.shutdown()
            except Exception as e:
                logger.error("Error while trying to shut down server: " + str(e))
            try:
                await runner.cleanup()
            except Exception as e:
                logger.error("Error while trying to shut down server: " + str(e))
        self.runners = []

    async def shutdown(self):
        await self.stop()

    @web.middleware
    async def error_middleware(self, request: Request, handler):
        try:
            log_trace = self.config.get(Setting.TRACE_REQUESTS)
            if log_trace:
                logger.trace("Serving %s %s to %s", request.method, request.url, request.remote)
            handled = await handler(request)
            if log_trace:
                logger.trace("Completed %s %s", request.method, request.url)
            return handled
        except Exception as ex:
            if isinstance(ex, HTTPException):
                raise
            logger.error("Error serving %s %s", request.method, request.url)
            logger.error(logger.formatException(ex))
            data = self.processError(ex)
            return web.json_response(data, status=data['http_status'])

    def processError(self, e):
        if isinstance(e, KnownError):
            known: KnownError = e
            return {
                'http_status': known.httpStatus(),
                'error_type': known.code(),
                'message': known.message(),
                'details': logger.formatException(e),
                'data': known.data()
            }
        return {
            'http_status': 500,
            'error_type': "generic_error",
            'message': "An unexpected error occurred: " + str(e),
            'details': logger.formatException(e)
        }

    def filePath(self, name=None):
        if name is None:
            return abspath(join(__file__, "..", "..", "static"))
        return abspath(join(__file__, "..", "..", "static", name))


def makeLoginMiddleware(time, harequests):
    auth_cache: Dict[str, Any] = {}
    realm = "Home Assistant Login"
    # Cap the cache so a flood of distinct usernames can't grow it without bound.
    MAX_CACHED = 1024

    async def check_credentials(username, password):
        if username is None or password is None:
            return False
        cached = auth_cache.get(username)
        if cached and hmac.compare_digest(cached['password'], password) and cached['timeout'] > time.now():
            return True
        try:
            await harequests.auth(username, password)
            if len(auth_cache) >= MAX_CACHED:
                auth_cache.clear()
            auth_cache[username] = {'password': password, 'timeout': time.now() + timedelta(minutes=10)}
            return True
        except Exception as e:
            logger.printException(e)
            return False

    @web.middleware
    async def middleware(request: Request, handler):
        auth_header = request.headers.get(hdrs.AUTHORIZATION)
        auth = None
        if auth_header:
            try:
                auth = BasicAuth.decode(auth_header=auth_header)
            except ValueError:
                auth = None
        if auth is not None and await check_credentials(auth.login, auth.password):
            return await handler(request)
        return web.Response(body=b'', status=401, reason='UNAUTHORIZED', headers={
            hdrs.WWW_AUTHENTICATE: 'Basic realm="%s"' % realm,
            hdrs.CONTENT_TYPE: 'text/html; charset=utf-8',
            hdrs.CONNECTION: 'keep-alive'
        })

    return middleware
