import asyncio
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from injector import inject, singleton

from ..config import Config, Setting
from ..exceptions import LogicError
from ..logger import getLogger
from .exceptions import (ProtonError, ProtonNotAuthenticated,
                         ProtonCliMissing, ProtonTimeout,
                         ProtonConnectionError)

logger = getLogger(__name__)

# The Proton Drive CLI exposes the user's drive under this virtual root.
PROTON_ROOT = "/my-files"

NOT_LOGGED_IN = "You need to login first"
SESSION_LOAD_FAILED = "Failed to load session from secrets"

NETWORK_ERROR_CODES = {"FailedToOpenSocket", "ConnectionRefused", "ConnectionClosed"}
NETWORK_ERROR_MESSAGES = (
    "Was there a typo in the url or port?",
    "Unable to connect. Is the computer able to access the url?",
)
ERROR_DETAILS_HEADER = "Error details:"

ERROR_DETAILS_CODE = re.compile(r'^[\s{]*code:\s*[\'"]([A-Za-z]\w*)[\'"]', re.MULTILINE)

# The CLI prints the interactive sign-in link on its own line during `auth login`.
LOGIN_URL_RE = re.compile(r"https://\S*proton\.me/\S+", re.IGNORECASE)


def _reject_json_constant(value):
    # Bun's JSON.parse has no NaN/Infinity; a lock file holding them is corrupt.
    raise ValueError("invalid JSON constant: " + value)


def _classify_failure(stderr: str):
    """Map a failed command's stderr to a typed exception class, or None."""
    lines = [line.strip() for line in stderr.splitlines()]
    if any(line == NOT_LOGGED_IN or line.startswith(SESSION_LOAD_FAILED) for line in lines):
        return ProtonNotAuthenticated
    details = stderr.partition(ERROR_DETAILS_HEADER)[2]
    if set(ERROR_DETAILS_CODE.findall(details)) & NETWORK_ERROR_CODES:
        return ProtonConnectionError
    # Whole lines only: free text can embed user-controlled names.
    if any(line.removeprefix("error: ") in NETWORK_ERROR_MESSAGES for line in lines):
        return ProtonConnectionError
    return None


@singleton
class ProtonCli:
    """
    Thin async wrapper around the `proton-drive` CLI binary.

    Proton Drive has no public REST API, so every operation shells out to the
    official CLI.  The CLI works against local files on disk (it can't stream),
    which is why uploads/downloads in ProtonSource stage through a temp file.
    """

    @inject
    def __init__(self, config: Config):
        self.config = config
        self._auth_checked = False
        self._authenticated = False
        # Set when a probe fails unclassified while signed in ("can't verify").
        self._auth_warning: Optional[str] = None
        # Every `proton-drive` invocation shares one on-disk session/keyring/cache
        # under PROTON_DATA_PATH.  The CLI isn't documented as safe to run
        # concurrently against the same session, so serialize all invocations
        # through this lock (a UI "Re-check" or sync can otherwise overlap an
        # in-flight upload).  Interactive `auth login` is long-lived and tracked
        # separately below, so it deliberately does NOT take this lock.
        self._cli_lock = asyncio.Lock()
        # Interactive login session state (driven from the Web UI).
        self._login_proc = None
        self._login_url = None
        self._login_task = None
        self._login_error = None
        self._login_lock = asyncio.Lock()

    def _binary(self) -> str:
        return self.config.get(Setting.PROTON_CLI_PATH)

    def _timeout(self) -> float:
        return self.config.get(Setting.PROTON_DRIVE_TIMEOUT_SECONDS)

    def _env(self) -> Dict[str, str]:
        # The CLI looks up the user's keyring/session via these.  The Docker
        # entrypoint is responsible for actually starting the secret service and
        # unlocking the keyring; here we just make sure the child sees them.
        env = dict(os.environ)
        data_path = self.config.get(Setting.PROTON_DATA_PATH)
        env.setdefault("HOME", data_path)
        env.setdefault("XDG_DATA_HOME", os.path.join(data_path, ".local", "share"))
        env.setdefault("XDG_CONFIG_HOME", os.path.join(data_path, ".config"))
        return env

    async def _run(self, args: List[str], timeout: Optional[float] = None,
                   check: bool = True) -> "ProtonResult":
        binary = self._binary()
        cmd = [binary] + args
        effective_timeout = timeout or self._timeout()
        cmd_str = " ".join(args)
        logger.info("proton-drive: starting '%s' (timeout %ss)", cmd_str, effective_timeout)
        started = time.monotonic()
        async with self._cli_lock:
            return await self._runLocked(cmd, cmd_str, effective_timeout, started, check)

    async def _runLocked(self, cmd, cmd_str, effective_timeout, started, check):
        env = self._env()
        result = await self._execOnce(cmd, cmd_str, effective_timeout, started, env)
        # An unparseable events.lock crashes every CLI run at init (even `auth
        # login`) until it's deleted; verify the file itself, don't match text.
        if (result.returncode != 0 and _classify_failure(result.stderr) is None
                and self._healCorruptEventsLock(env)):
            result = await self._execOnce(cmd, cmd_str, effective_timeout,
                                          time.monotonic(), env)

        # Classify only failed commands, and only from stderr: stdout carries
        # the JSON payload (user-controlled names) and must never be matched.
        if result.returncode != 0:
            error_type = _classify_failure(result.stderr)
            if error_type is ProtonNotAuthenticated:
                self._authenticated = False
                self._auth_warning = None
                raise ProtonNotAuthenticated(result.message())
            # check=False callers are best-effort; don't fail them on a blip.
            if check and error_type is ProtonConnectionError:
                raise ProtonConnectionError(result.message())

        if check and result.returncode != 0:
            raise ProtonError(result.message(), result.returncode)
        return result

    async def _execOnce(self, cmd, cmd_str, effective_timeout, started, env):
        binary = cmd[0]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,   # never let the CLI block on a stdin prompt
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            raise ProtonCliMissing(binary)
        logger.debug("proton-drive: '%s' running as pid %s", cmd_str, proc.pid)
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout)
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - started
            logger.error("proton-drive: '%s' TIMED OUT after %.1fs (killing pid %s)",
                         cmd_str, elapsed, proc.pid)
            try:
                proc.kill()
                # Reap the killed child so we don't leak the subprocess transport.
                await proc.wait()
            except ProcessLookupError:
                pass
            raise ProtonTimeout(cmd_str)

        elapsed = time.monotonic() - started
        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr = (stderr_b or b"").decode("utf-8", errors="replace")
        result = ProtonResult(proc.returncode or 0, stdout, stderr)
        logger.info("proton-drive: finished '%s' in %.1fs (exit %s, %d bytes out, %d bytes err)",
                    cmd_str, elapsed, proc.returncode, len(stdout), len(stderr))
        if result.returncode != 0 and stderr.strip():
            logger.debug("proton-drive: '%s' stderr: %s", cmd_str, stderr.strip()[:500])
        return result

    def _eventsLockPath(self, env: Dict[str, str]) -> str:
        # Mirrors the CLI's dir resolution: PROTON_DRIVE_CACHE_DIR overrides
        # everything; otherwise the lock lives in the XDG data ("app") dir.
        override = env.get("PROTON_DRIVE_CACHE_DIR")
        if override:
            return os.path.join(override, "events.lock")
        data = env.get("XDG_DATA_HOME") or os.path.join(env["HOME"], ".local", "share")
        return os.path.join(data, "proton-drive-cli", "events.lock")

    def _healCorruptEventsLock(self, env: Dict[str, str]) -> bool:
        """
        Delete events.lock iff it exists but isn't parseable JSON — the one
        lock state the CLI (verified v0.4.6-v0.8.0) can't recover from: its
        init tolerates only ENOENT and heals parseable stale locks itself.
        Returns True if the file was deleted.
        """
        path = self._eventsLockPath(env)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read(1 << 20)   # a healthy lock is ~13 bytes; cap garbage
        except OSError:
            return False
        try:
            json.loads(raw, parse_constant=_reject_json_constant)
            return False
        except RecursionError:
            return False   # deep nesting: JSC parses it iteratively, no crash
        except ValueError:
            pass
        try:
            os.unlink(path)
        except OSError:
            return False
        logger.warning("Deleted corrupt proton-drive lock file %s "
                       "(it blocks every Proton Drive command); retrying", path)
        return True

    async def _run_json(self, args: List[str], timeout: Optional[float] = None) -> Any:
        # The CLI treats the first token as the command, so global flags like
        # --json have to come after the subcommand, not before it.
        result = await self._run(args + ["--json"], timeout=timeout)
        text = result.stdout.strip()
        if not text:
            return None
        parsed = _salvage_json(text)
        if parsed is _NO_JSON:
            raise ProtonError("Could not parse CLI JSON output: " + text[:200], result.returncode)
        return parsed

    # --- High level operations -------------------------------------------------

    async def checkAuth(self) -> bool:
        """
        Probe for a usable session.  Only the CLI's explicit "not logged in"
        flips the state to False; other failures keep the last-known state.
        ProtonCliMissing propagates (hard misconfiguration).
        """
        if self._cli_lock.locked() or self.loginInProgress():
            # A command or interactive login is using the session; don't race it.
            logger.debug("Skipping Proton auth probe; a proton-drive command is already running")
            self._auth_checked = True
            return self._authenticated
        try:
            result = await self._run_json(["filesystem", "info", PROTON_ROOT])
            # Exit-0 with no payload is not proof of a session.
            self._authenticated = bool(result)
            self._auth_warning = None
        except ProtonNotAuthenticated:
            self._authenticated = False
            self._auth_warning = None
        except ProtonCliMissing:
            raise
        except (ProtonTimeout, ProtonConnectionError) as e:
            logger.warning("Couldn't reach Proton Drive to verify authentication: " + str(e))
        except Exception as e:
            logger.warning("Couldn't verify Proton Drive authentication: " + str(e))
            # Not an auth answer, but the session may be dead: warn, don't guess.
            if self._authenticated:
                self._auth_warning = str(e)
        finally:
            self._auth_checked = True
        return self._authenticated

    def isAuthenticated(self) -> bool:
        return self._authenticated

    def authWarning(self) -> Optional[str]:
        return self._auth_warning

    # --- Interactive (browser) login, driven from the Web UI -------------------

    def loginInProgress(self) -> bool:
        return self._login_proc is not None and self._login_proc.returncode is None

    def loginUrl(self) -> Optional[str]:
        return self._login_url

    def loginError(self) -> Optional[str]:
        return self._login_error

    async def startLogin(self) -> str:
        """
        Launch `proton-drive auth login`, capture the sign-in URL it prints, and
        return it.  The process is kept running in the background until the user
        completes sign-in in their browser (at which point the session is stored
        and `_authenticated` flips to True), or until it times out.

        Serialized by a lock so concurrent requests (two tabs, a double-click,
        the poll loop) can't tear down each other's login; a second caller that
        arrives while a login is already pending gets the same URL back.
        """
        async with self._login_lock:
            if self.loginInProgress() and self._login_url:
                return self._login_url
            await self._cancelLoginLocked()
            self._login_url = None
            self._login_error = None
            binary = self._binary()
            try:
                proc = await asyncio.create_subprocess_exec(
                    binary, "auth", "login",
                    stdin=asyncio.subprocess.DEVNULL,   # browser-driven; never block on a stdin prompt
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=self._env(),
                )
            except FileNotFoundError:
                raise ProtonCliMissing(binary)
            self._login_proc = proc
            try:
                url = await self._readLoginUrl(proc, timeout=45)
            except Exception:
                # Clean up the process this call created (never shared state).
                await self._killProc(proc)
                if self._login_proc is proc:
                    self._login_proc = None
                    self._login_url = None
                raise
            self._login_url = url
            self._login_task = asyncio.create_task(self._awaitLogin(proc))
            return url

    async def _readLoginUrl(self, proc, timeout: float) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        seen = []
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise ProtonError("Timed out waiting for the Proton sign-in link")
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                raise ProtonError("Timed out waiting for the Proton sign-in link")
            if not line:
                rc = await proc.wait()
                output = "\n".join(seen)
                if _classify_failure(output) is ProtonConnectionError:
                    raise ProtonConnectionError(output[-500:])
                raise ProtonError(
                    "The sign-in process exited before showing a link (exit {}). "
                    "Is the keyring/secret service available?".format(rc))
            text = line.decode("utf-8", errors="replace")
            seen.append(text.strip())
            m = LOGIN_URL_RE.search(text)
            if m:
                # Trim trailing punctuation the CLI might place after the link.
                return m.group(0).strip().rstrip(').,;\'"')

    async def _awaitLogin(self, proc):
        try:
            try:
                await asyncio.wait_for(self._drainAndWait(proc), timeout=600)
            except asyncio.TimeoutError:
                self._login_error = "Sign-in timed out. Please start it again."
                await self._killProc(proc)
                return
            if proc.returncode == 0:
                self._authenticated = True
                self._auth_warning = None
                logger.info("Signed in to Proton Drive")
            else:
                self._login_error = "Sign-in didn't complete (exit {}).".format(proc.returncode)
        finally:
            # If we're unwinding via cancellation (e.g. event-loop shutdown)
            # rather than our own cancelLogin (which already kills first), make
            # sure the child can't outlive us.
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            # Only clear state that still refers to *this* login, so a finishing
            # old login can't clobber a newer one's URL/process.
            if self._login_proc is proc:
                self._login_proc = None
                self._login_url = None
            if self._login_task is asyncio.current_task():
                self._login_task = None

    async def _drainAndWait(self, proc):
        if proc.stdout is not None:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
        await proc.wait()

    async def cancelLogin(self):
        async with self._login_lock:
            await self._cancelLoginLocked()

    async def _cancelLoginLocked(self):
        # Caller must hold self._login_lock.
        task = self._login_task
        proc = self._login_proc
        self._login_task = None
        self._login_proc = None
        self._login_url = None
        if proc is not None:
            await self._killProc(proc)
        if task is not None:
            task.cancel()
            try:
                await task
            except BaseException:
                pass

    async def _killProc(self, proc):
        if proc.returncode is not None:
            return
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass

    async def logout(self) -> None:
        if self._cli_lock.locked():
            # Don't queue behind a long transfer (up to the transfer timeout).
            raise ProtonError("Another Proton Drive operation is in progress. "
                              "Try signing out again in a moment.")
        result = await self._run(["auth", "logout"], check=False)
        if result.returncode != 0 and _classify_failure(result.stderr) is ProtonConnectionError:
            # Can't fire today (the CLI puts network errors on stdout), so a
            # failed sign-out still reads as success; kept for if that changes.
            raise ProtonConnectionError(result.message())
        self._authenticated = False
        self._auth_warning = None

    async def listFolder(self, path: str) -> List[Dict[str, Any]]:
        data = await self._run_json(["filesystem", "list", path])
        return _as_entry_list(data)

    async def info(self, path: str) -> Dict[str, Any]:
        data = await self._run_json(["filesystem", "info", path])
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    async def createFolder(self, parent_path: str, name: str) -> Dict[str, Any]:
        data = await self._run_json(["filesystem", "create-folder", parent_path, name])
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    async def upload(self, local_path: str, parent_path: str,
                     conflict: str = "replace") -> None:
        await self._run(["filesystem", "upload", "-f", conflict, "-d", "skip",
                         local_path, parent_path],
                        timeout=self.config.get(Setting.PROTON_TRANSFER_TIMEOUT_SECONDS))

    async def download(self, remote_path: str, local_folder: str,
                       conflict: str = "remove") -> None:
        await self._run(["filesystem", "download", "-f", conflict, "-d", "skip",
                         remote_path, local_folder],
                        timeout=self.config.get(Setting.PROTON_TRANSFER_TIMEOUT_SECONDS))

    async def trash(self, path: str, strict: bool = False) -> List[Dict[str, Any]]:
        """
        Move an item to the Proton Drive trash, which removes it from its
        folder (so it stops showing up in listings) without a permanent,
        irreversible delete.  strict=True propagates CLI failures so callers
        can keep local state in sync with the remote; strict=False is
        best-effort (used for cleanup).

        Returns the CLI's per-node results ({"uid": ..., "ok": ...}; [] when
        unavailable) so callers know exactly which node was trashed — needed
        to safely purge it from the trash, where the CLI addresses nodes by
        bare (non-unique) name.
        """
        result = await self._run(["filesystem", "trash", path, "--json"], check=strict)
        parsed = _salvage_json(result.stdout.strip()) if result.stdout.strip() else None
        if isinstance(parsed, dict):
            # Salvage of a cluttered payload can recover a single result
            # object instead of the array; keep an ok=false inside it visible
            # to strict mode rather than discarding it as the wrong shape.
            parsed = [parsed]
        results = [e for e in parsed if isinstance(e, dict)] if isinstance(parsed, list) else []
        # The CLI exits 0 even when a node's trash result is ok=false (only
        # thrown errors set the exit code — per the CLI source, v0.8.0), so
        # strict mode must also inspect the results, not just the exit code.
        if strict:
            failed = [r for r in results if r.get("ok") is False]
            if failed:
                raise ProtonError("proton-drive trash failed for '{}': {}".format(
                    path, json.dumps(failed)[:500]), result.returncode)
            if not results:
                # Exit 0 with no parseable per-node results (output-shape
                # drift): fall back to trusting the exit code, but say so —
                # the ok=false channel is blind here.
                logger.warning("proton-drive trash '%s' exited 0 but returned no "
                               "parseable results; trusting the exit code", path)
        return results

    async def delete(self, path: str, strict: bool = False) -> None:
        # NOTE: the CLI's `filesystem delete` only operates on items that are
        # ALREADY in the trash, addressed as "/trash/<name>"; it errors on live
        # paths.  It resolves <name> by scanning the whole trash and acts on
        # the first match, so when several trashed items share the name the
        # caller must rule out ambiguity first (see ProtonSource's purge).
        await self._run(["filesystem", "delete", path], check=strict)


# Sentinel distinguishing "no JSON found" from a legitimately parsed None/null.
_NO_JSON = object()


def _salvage_json(text: str) -> Any:
    """Parse CLI stdout as JSON; returns _NO_JSON when no parse succeeds."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Some CLI builds surround the payload with log lines (which may
    # themselves contain stray brackets).  The payload can be a MULTI-LINE
    # streaming array ("[", one item per line, "]"), so first try each
    # line-START bracket as the payload's beginning, running to the end of the
    # output.  Restricting candidates to line starts keeps JSON embedded at
    # the tail of a log line from beating the real payload, while a stray
    # bracket candidate simply fails to parse (json.loads demands the whole
    # remainder) and the scan moves on.
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped[:1] in ("[", "{"):
            try:
                return json.loads(text[offset + len(line) - len(stripped):])
            except json.JSONDecodeError:
                pass
        offset += len(line)
    # Then a whole line that is itself valid JSON (a single-line payload with
    # log lines before and/or after it).
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line[:1] in ("[", "{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    # Last resort: any bracket anywhere in the text.
    for i, ch in enumerate(text):
        if ch in "[{":
            try:
                return json.loads(text[i:])
            except json.JSONDecodeError:
                continue
    return _NO_JSON


def _as_entry_list(data: Any) -> List[Dict[str, Any]]:
    """Normalize the various shapes `filesystem list --json` may return."""
    if data is None:
        return []
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)]
    if isinstance(data, dict):
        for key in ("items", "entries", "children", "files", "nodes", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [e for e in value if isinstance(e, dict)]
        # A single-item response.
        return [data]
    raise LogicError("Unexpected CLI list output: " + str(type(data)))


class ProtonResult:
    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def message(self) -> str:
        parts = []
        if self.stderr.strip():
            parts.append(self.stderr.strip())
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        body = " | ".join(parts) if parts else "(no output)"
        return "proton-drive exited {}: {}".format(self.returncode, body)
