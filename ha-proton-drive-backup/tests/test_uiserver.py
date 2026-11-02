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


# --- Web security ------------------------------------------------------------

def make_config_ui(data=None):
    from backup.config import Config
    ui = UiServer.__new__(UiServer)
    ui.config = Config(data)
    return ui


def test_saveconfig_ignores_internal_settings():
    # supervisor_url is a Setting but not an option: accepting it would send
    # the add-on's Supervisor token to whatever server the request names.
    ui = make_config_ui()
    update = ui._uiConfigUpdate({
        "supervisor_url": "http://attacker.example",
        "hassio_header": "attacker-token",
        "secrets_file_path": "/data/options.json",
        "max_backups_in_ha": 3,
    })
    assert update == {"max_backups_in_ha": 3}


def test_saveconfig_accepts_declared_options():
    ui = make_config_ui()
    submitted = {"proton_cli_path": "/opt/proton-drive", "proton_data_path": "/data/elsewhere",
                 "require_login": True}
    assert ui._uiConfigUpdate(submitted) == submitted


def test_saveconfig_password_placeholder_keeps_saved_password():
    from backup.config import Setting
    from backup.ui.uiserver import PASSWORD_PLACEHOLDER
    ui = make_config_ui({Setting.BACKUP_PASSWORD: "s3cret"})
    assert ui._uiConfigUpdate({"backup_password": PASSWORD_PLACEHOLDER}) == {"backup_password": "s3cret"}
    assert ui._uiConfigUpdate({"backup_password": "new"}) == {"backup_password": "new"}
    # Cleared in the UI: an empty password isn't mistaken for "keep it".
    assert ui._uiConfigUpdate({"backup_password": ""}) == {"backup_password": ""}


@pytest.mark.parametrize("body", ["not json", '{"config": ["max_backups_in_ha", 3]}',
                                  '"config"', "null", "5", '["config"]'])
async def test_saveconfig_rejects_malformed_bodies(body):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    ui = make_config_ui()
    app = web.Application()
    app.router.add_post("/saveconfig", ui.saveconfig)
    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/saveconfig", data=body, headers={"Content-Type": "application/json"})
        assert resp.status == 400


def test_saveconfig_without_login_keeps_code_paths():
    # Every other add-on can reach the extra server: without login it mustn't
    # choose which program the add-on runs, or where that program's state is.
    from aiohttp.web import HTTPForbidden
    from backup.config import Setting
    ui = make_config_ui({Setting.PROTON_CLI_PATH: "/opt/proton-drive"})
    for kept in ({"proton_cli_path": "/opt/proton-drive"}, {"proton_cli_path": "/usr/bin/proton-drive"},
                 {"proton_data_path": "/data/proton"}, {}):
        assert ui._uiConfigUpdate(kept, unauthenticated=True) == kept
    for changed in ({"proton_cli_path": "/share/evil"}, {"proton_data_path": "/share/evil"}):
        with pytest.raises(HTTPForbidden):
            ui._uiConfigUpdate(changed, unauthenticated=True)
        assert ui._uiConfigUpdate(changed) == changed  # through ingress or after login


async def test_unauthenticated_extra_server_refuses_code_path_changes():
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from backup.ui.uiserver import UNAUTHENTICATED
    ui = make_config_ui()
    app = web.Application()
    app[UNAUTHENTICATED] = True
    app.router.add_post("/saveconfig", ui.saveconfig)
    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/saveconfig", json={"config": {"proton_cli_path": "/share/evil"}})
        assert resp.status == 403


async def test_getconfig_masks_password_and_hides_internal_settings():
    from backup.config import Setting
    from backup.ui.uiserver import PASSWORD_PLACEHOLDER
    ui = make_config_ui({Setting.BACKUP_PASSWORD: "s3cret"})

    class HaSource:
        async def refresh(self):
            pass

    class Info:
        addons = []
    ui._ha_source = HaSource()
    ui._global_info = Info()
    data = json.loads((await ui.getconfig(None)).text)
    assert data["config"]["backup_password"] == PASSWORD_PLACEHOLDER
    assert "s3cret" not in json.dumps(data)
    for internal in ("supervisor_url", "hassio_header", "secrets_file_path"):
        assert internal not in data["config"]
        assert internal not in data["defaults"]


async def test_getconfig_shows_secret_reference():
    # "!secret name" is a pointer into secrets.yaml, not the password itself.
    from backup.config import Setting
    ui = make_config_ui({Setting.BACKUP_PASSWORD: "!secret backup_pw"})

    class HaSource:
        async def refresh(self):
            pass

    class Info:
        addons = []
    ui._ha_source = HaSource()
    ui._global_info = Info()
    data = json.loads((await ui.getconfig(None)).text)
    assert data["config"]["backup_password"] == "!secret backup_pw"


@pytest.mark.parametrize("remote,allowed", [
    ("172.30.32.2", True),
    ("127.0.0.1", True),
    ("::1", True),
    ("::ffff:172.30.32.2", True),
    ("172.30.33.7", False),      # another add-on on the hassio network
    ("192.168.1.20", False),
    (None, False),
])
def test_ingress_source(remote, allowed):
    from backup.ui.uiserver import isIngressSource
    assert isIngressSource(remote) is allowed


def mocked_request(method, path, remote="127.0.0.1", headers=None):
    from unittest.mock import Mock
    from aiohttp.test_utils import make_mocked_request
    transport = Mock()
    transport.get_extra_info.side_effect = lambda name, default=None: (
        (remote, 12345) if name == "peername" else default)
    return make_mocked_request(method, path, headers=headers or {}, transport=transport)


async def ok_handler(request):
    from aiohttp import web
    return web.Response(text="ok")


async def test_ingress_middleware_refuses_other_containers():
    from aiohttp.web import HTTPForbidden
    from backup.ui.uiserver import ingress_source_middleware
    with pytest.raises(HTTPForbidden):
        await ingress_source_middleware(mocked_request("GET", "/download", remote="172.30.33.7"), ok_handler)
    resp = await ingress_source_middleware(mocked_request("GET", "/download", remote="172.30.32.2"), ok_handler)
    assert resp.text == "ok"


@pytest.mark.parametrize("headers,cross_site", [
    # Scripts, curl, Home Assistant rest_command: no browser headers at all.
    ({}, False),
    ({"Sec-Fetch-Site": "same-origin"}, False),
    ({"Sec-Fetch-Site": "none"}, True),             # user-started navigation: reads only
    ({"Sec-Fetch-Site": "cross-site"}, True),       # form on another site
    ({"Sec-Fetch-Site": "same-site"}, True),        # e.g. HA on :8123 -> :8471
    # Sec-Fetch-Site wins over Origin when both are present.
    ({"Sec-Fetch-Site": "same-origin", "Origin": "https://evil.example"}, False),
    # Plain HTTP or an old browser: Origin only.
    ({"Origin": "http://ha.local:8471", "Host": "ha.local:8471"}, False),
    ({"Origin": "https://ha.example.com", "Host": "172.30.33.4:8099",
      "X-Forwarded-Host": "ha.example.com"}, False),  # behind ingress
    ({"Origin": "https://ha.example.com", "Host": "ha.example.com:443"}, False),
    ({"Origin": "http://HA.local", "Host": "ha.local:80"}, False),
    ({"Origin": "http://[::1]:8471", "Host": "[::1]:8471"}, False),
    ({"Origin": "https://ha.example.com", "Host": "ha.example.com:8443"}, True),
    ({"Origin": "https://evil.example", "Host": "ha.local:8471"}, True),
    ({"Origin": "null", "Host": "ha.local:8471"}, True),
    ({"Origin": "http://[::1", "Host": "ha.local:8471"}, True),  # malformed: refused, not a 500
    ({"Origin": "http://ha.local:8471"}, True),     # nothing to compare against
])
def test_cross_site_detection(headers, cross_site):
    from backup.ui.uiserver import isCrossSiteRequest
    assert isCrossSiteRequest(mocked_request("POST", "/confirmdelete", headers=headers)) is cross_site


def test_user_started_navigation_may_read():
    from backup.ui.uiserver import isCrossSiteRequest
    request = mocked_request("GET", "/download", headers={"Sec-Fetch-Site": "none"})
    assert isCrossSiteRequest(request, read_only=True) is False
    request = mocked_request("GET", "/download", headers={"Sec-Fetch-Site": "cross-site"})
    assert isCrossSiteRequest(request, read_only=True) is True


async def test_state_changing_routes_are_post_only_and_guarded():
    # Over plain HTTP a cross-site GET carries neither Sec-Fetch-Site nor
    # Origin, so only POST (which always carries Origin cross-site) is safe.
    from aiohttp import web
    ui = UiServer.__new__(UiServer)
    app = web.Application()

    async def confirmdelete(request):
        return web.Response(text="deleted")

    async def getstatus(request):
        return web.Response(text="status")
    ui._addRoute(app, confirmdelete)
    ui._addRoute(app, getstatus)
    methods = {}
    for route in app.router.routes():
        methods.setdefault(route.resource.canonical, {})[route.method] = route.handler
    assert set(methods["/confirmdelete"]) == {"POST"}
    assert {"GET", "POST"} <= set(methods["/getstatus"])
    post = methods["/confirmdelete"]["POST"]
    assert (await post(mocked_request("POST", "/confirmdelete"))).text == "deleted"
    with pytest.raises(web.HTTPForbidden):
        await post(mocked_request("POST", "/confirmdelete",
                                  headers={"Origin": "http://evil.example", "Host": "ha.local:8471"}))
    get = methods["/getstatus"]["GET"]
    assert (await get(mocked_request("GET", "/getstatus", headers={"Sec-Fetch-Site": "none"}))).text == "status"


def test_real_handler_names_split_as_intended():
    from backup.ui.uiserver import READ_ONLY_HANDLERS
    ui = UiServer.__new__(UiServer)
    for name in READ_ONLY_HANDLERS - {"getTasks"}:
        assert callable(getattr(ui, name)), name
    for mutating in ("saveconfig", "confirmdelete", "backup", "exposeserver", "protonlogout",
                     "deleteSnapshot", "upload", "uploadToProton", "startSync", "sync", "cancelSync"):
        assert mutating not in READ_ONLY_HANDLERS


class FakeAuthRequests:
    def __init__(self, users, auth_ok=True, list_error=None):
        self.users = users
        self.auth_ok = auth_ok
        self.list_error = list_error
        self.passwords = []

    async def auth(self, username, password):
        self.passwords.append(password)
        if not self.auth_ok:
            raise Exception("bad credentials")

    async def listUsers(self):
        if self.list_error:
            raise self.list_error
        return {"users": self.users}


def basic_auth_request(username, password="pw", remote="127.0.0.1"):
    from aiohttp import encode_basic_auth
    return mocked_request("GET", "/getstatus", remote=remote,
                          headers={"Authorization": encode_basic_auth(username, password)})


def make_login(harequests):
    from backup.time import Time
    from backup.ui.uiserver import makeLoginMiddleware
    return makeLoginMiddleware(Time(), harequests)


async def run_login(harequests, username, password="pw", remote="127.0.0.1", middleware=None):
    middleware = middleware or make_login(harequests)
    return await middleware(basic_auth_request(username, password, remote), ok_handler)


async def test_login_allows_admins():
    users = [{"username": "alice", "is_active": True, "is_owner": False, "group_ids": ["system-admin"]}]
    resp = await run_login(FakeAuthRequests(users), "Alice")  # HA usernames are case-insensitive
    assert resp.status == 200


async def test_login_allows_owner():
    users = [{"username": "owner", "is_active": True, "is_owner": True, "group_ids": []}]
    assert (await run_login(FakeAuthRequests(users), "owner")).status == 200


async def test_login_refuses_non_admin_users():
    # Supervisor's /auth accepts any user's password; that alone isn't enough.
    users = [{"username": "bob", "is_active": True, "is_owner": False, "group_ids": ["system-users"]}]
    assert (await run_login(FakeAuthRequests(users), "bob")).status == 401


async def test_login_refuses_when_users_cant_be_listed():
    resp = await run_login(FakeAuthRequests([], list_error=Exception("supervisor down")), "alice")
    assert resp.status == 401


async def test_login_refuses_inactive_admins():
    users = [{"username": "alice", "is_active": False, "group_ids": ["system-admin"]}]
    assert (await run_login(FakeAuthRequests(users), "alice")).status == 401


async def test_login_refuses_bad_password():
    users = [{"username": "alice", "is_active": True, "group_ids": ["system-admin"]}]
    assert (await run_login(FakeAuthRequests(users, auth_ok=False), "alice")).status == 401


async def test_login_refuses_ambiguous_usernames():
    # HA checks the password against the LAST user whose name case-folds to
    # the login, so with "Admin" (admin) and "admin" (not) a non-admin's
    # password could pass Supervisor for either spelling.
    users = [{"username": "Admin", "is_active": True, "group_ids": ["system-admin"]},
             {"username": "admin", "is_active": True, "group_ids": ["system-users"]}]
    for login in ("Admin", "admin"):
        assert (await run_login(FakeAuthRequests(users), login)).status == 401, login


async def test_login_limits_local_only_admins_to_the_lan():
    users = [{"username": "alice", "is_active": True, "local_only": True, "group_ids": ["system-admin"]}]
    harequests = FakeAuthRequests(users)
    middleware = make_login(harequests)
    assert (await run_login(harequests, "alice", remote="192.168.1.20", middleware=middleware)).status == 200
    # Also once the login is cached.
    assert (await run_login(harequests, "alice", remote="203.0.113.9", middleware=middleware)).status == 401
    assert (await run_login(FakeAuthRequests(users), "alice", remote="203.0.113.9")).status == 401


@pytest.mark.parametrize("remote,local", [
    ("192.168.1.20", True), ("10.1.2.3", True), ("172.30.32.1", True), ("127.0.0.1", True),
    ("169.254.10.1", True), ("fd12:3456::1", True), ("fe80::1", True), ("::1", True),
    ("::ffff:192.168.1.5", True),
    ("203.0.113.9", False),   # documentation range: ipaddress calls it private, HA doesn't
    ("100.64.1.1", False),    # carrier-grade NAT
    ("8.8.8.8", False), ("2001:4860::8888", False), (None, False),
])
def test_local_address_matches_home_assistant(remote, local):
    from backup.ui.uiserver import isLocalAddress
    assert isLocalAddress(remote) is local


async def test_login_handles_non_ascii_passwords():
    users = [{"username": "alice", "is_active": True, "group_ids": ["system-admin"]}]
    harequests = FakeAuthRequests(users)
    middleware = make_login(harequests)
    for _ in range(2):  # the second request is answered from the cache
        assert (await run_login(harequests, "alice", "pässwörd", middleware=middleware)).status == 200
    assert harequests.passwords == ["pässwörd"]  # decoded as UTF-8, checked once


async def test_login_accepts_latin1_credentials():
    # Clients that don't use UTF-8 send latin-1, which isn't valid UTF-8.
    import base64
    users = [{"username": "alice", "is_active": True, "group_ids": ["system-admin"]}]
    harequests = FakeAuthRequests(users)
    header = "Basic " + base64.b64encode("alice:pässwörd".encode("latin1")).decode()
    request = mocked_request("GET", "/getstatus", headers={"Authorization": header})
    assert (await make_login(harequests)(request, ok_handler)).status == 200
    assert harequests.passwords == ["pässwörd"]


async def test_html_log_view_is_escaped(monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    import backup.ui.uiserver as uiserver
    monkeypatch.setattr(uiserver, "getHistory",
                        lambda index, html: iter([(1, "<img src=x onerror=alert(1)>")]))
    ui = UiServer.__new__(UiServer)
    ui.last_log_index = 0
    app = web.Application()
    app.router.add_get("/log", ui.log)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/log", params={"format": "html"})
        body = await resp.text()
    assert resp.content_type == "text/html"
    assert "<img" not in body and "&lt;img src=x" in body


def test_colored_log_history_is_escaped():
    import logging
    from backup.logger import HistoryHandler
    handler = HistoryHandler()
    handler.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "<img src=x onerror=alert(1)>", None, None))
    (_, line), = list(handler.getHistory(0, html=True))
    assert "<img" not in line and "&lt;img" in line
