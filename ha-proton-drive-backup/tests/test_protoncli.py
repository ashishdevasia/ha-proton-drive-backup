import asyncio

import pytest

from backup.config import Setting
from backup.proton.exceptions import (ProtonNotAuthenticated, ProtonCliMissing,
                                      ProtonTimeout, ProtonError,
                                      ProtonConnectionError)
from tests.fakes import write_script, make_cli


def args_log(tmp_path):
    p = tmp_path / "args.log"
    return p.read_text().strip().splitlines() if p.exists() else []


async def test_missing_binary(tmp_path):
    cli = make_cli(tmp_path, str(tmp_path / "nope"))
    with pytest.raises(ProtonCliMissing):
        await cli.checkAuth()


async def test_checkauth_true_on_json(tmp_path):
    binary = write_script(tmp_path, 'echo "{\\"name\\": \\"my-files\\"}"\n')
    cli = make_cli(tmp_path, binary)
    assert await cli.checkAuth() is True
    assert cli.isAuthenticated() is True


async def test_json_flag_is_appended_after_command(tmp_path):
    binary = write_script(tmp_path, 'echo "{}"\n')
    cli = make_cli(tmp_path, binary)
    await cli.info("/my-files")
    line = args_log(tmp_path)[-1]
    assert line.startswith("filesystem info /my-files")
    assert line.endswith("--json")


async def test_not_logged_in_detected(tmp_path):
    # The CLI's pre-command login gate prints exactly this message.
    binary = write_script(tmp_path, 'echo "You need to login first" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    assert await cli.checkAuth() is False
    with pytest.raises(ProtonNotAuthenticated):
        await cli.info("/my-files")


async def test_session_load_failure_detected(tmp_path):
    binary = write_script(
        tmp_path,
        'echo "Failed to load session from secrets (ensure you have secrets'
        ' available, read the README for more information): libsecret error" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    assert await cli.checkAuth() is False


async def test_auth_message_in_successful_stdout_does_not_flip_auth(tmp_path):
    # An exit-0 payload containing the auth message (e.g. as a file name) must
    # NOT be treated as a sign-out.
    binary = write_script(tmp_path, 'echo "[{\\"name\\": \\"You need to login first.tar\\"}]"\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    entries = await cli.listFolder("/my-files/HA")
    assert [e["name"] for e in entries] == ["You need to login first.tar"]
    assert cli.isAuthenticated() is True


async def test_stderr_only_classified_on_failure(tmp_path):
    binary = write_script(tmp_path, 'echo "You need to login first" >&2\necho "{}"\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    await cli.info("/my-files")  # exit 0: must not raise
    assert cli.isAuthenticated() is True


async def test_checkauth_keeps_state_on_unrecognized_failure(tmp_path):
    # Unknown failures (server errors, reworded messages) are not an auth
    # answer; only the CLI's explicit "not logged in" flips the state.
    binary = write_script(tmp_path, 'echo "token refresh failed in an unexpected way" >&2\nexit 2\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    assert await cli.checkAuth() is True


def write_offline_script(tmp_path):
    """Fake CLI failing on network, with the whole body on stderr.

    NOT the real stream split: v0.4.6-v0.8.0 put only the `===` banner on
    stderr and everything below it on stdout, so `_classify_failure` (which
    reads stderr) can't actually see these codes in production.
    """
    return write_script(tmp_path, (
        "cat >&2 <<'EOF'\n"
        "===============================================\n"
        "error: Was there a typo in the url or port?\n"
        '  path: "https://drive-api.proton.me/drive/v2/shares/my-files",\n'
        " errno: 0,\n"
        '  code: "FailedToOpenSocket"\n'
        "\n"
        "      at L_8 (src/cli/run.ts:77:13)\n"
        "      at nr0 (src/cli/run.ts:25:9)\n"
        "Error details:\n"
        "{\n"
        "  code: 'FailedToOpenSocket',\n"
        "  path: 'https://drive-api.proton.me/drive/v2/shares/my-files',\n"
        "  errno: 0\n"
        "}\n"
        "EOF\n"
        "exit 1\n"
    ))


async def test_network_error_is_transient(tmp_path):
    binary = write_offline_script(tmp_path)
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    with pytest.raises(ProtonConnectionError):
        await cli.info("/my-files")
    # A network failure says nothing about the session; it must not sign us out.
    assert cli.isAuthenticated() is True


async def test_checkauth_keeps_state_when_offline(tmp_path):
    binary = write_offline_script(tmp_path)
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    assert await cli.checkAuth() is True  # transient: keep last-known state
    cli._authenticated = False
    assert await cli.checkAuth() is False


async def test_bare_connection_message_is_transient(tmp_path):
    # Bun's fixed message when a fetch can't reach the server, printed bare
    # (observed from `auth login` while offline).
    binary = write_script(
        tmp_path,
        'echo "Unable to connect. Is the computer able to access the url?" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    with pytest.raises(ProtonConnectionError):
        await cli.info("/my-files")
    assert cli.isAuthenticated() is True


async def test_auth_detected_after_other_stderr_lines(tmp_path):
    binary = write_script(
        tmp_path,
        'echo "some warning" >&2\necho "You need to login first" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    assert await cli.checkAuth() is False


async def test_code_outside_details_block_is_not_network(tmp_path):
    # code:-looking text in a plain message (which can embed user-controlled
    # names) must not classify as a network failure.
    binary = write_script(
        tmp_path, 'echo "not found: code: \\"ConnectionRefused\\"" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    with pytest.raises(ProtonError):
        await cli.info("/my-files")
    assert cli.isAuthenticated() is True


async def test_details_code_alone_is_network(tmp_path):
    # Covers codes whose bare message we haven't observed (e.g. ConnectionClosed).
    binary = write_script(tmp_path, (
        "cat >&2 <<'EOF'\n"
        "===============================================\n"
        "error: something went wrong\n"
        "Error details:\n"
        "{ code: 'ConnectionClosed' }\n"
        "EOF\n"
        "exit 1\n"))
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    with pytest.raises(ProtonConnectionError):
        await cli.info("/my-files")
    assert cli.isAuthenticated() is True


async def test_code_inside_quoted_value_is_not_network(tmp_path):
    # A user-controlled name echoed into the details dump must not classify.
    binary = write_script(tmp_path, (
        "cat >&2 <<'EOF'\n"
        "error: not found\n"
        "Error details:\n"
        "{\n"
        "  path: \"/my-files/code: 'ConnectionRefused'\"\n"
        "}\n"
        "EOF\n"
        "exit 1\n"))
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    with pytest.raises(ProtonError):
        await cli.info("/my-files")
    assert cli.isAuthenticated() is True


async def test_connection_message_embedded_midline_is_not_network(tmp_path):
    binary = write_script(
        tmp_path,
        'echo "no file named \'Unable to connect. Is the computer able to access the url?\'" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonError):
        await cli.info("/my-files")


async def test_error_prefixed_connection_message_is_network(tmp_path):
    binary = write_script(
        tmp_path,
        'echo "error: Unable to connect. Is the computer able to access the url?" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonConnectionError):
        await cli.info("/my-files")


async def test_connection_error_not_raised_when_best_effort(tmp_path):
    # check=False callers (best-effort trash, logout) must not fail on a blip.
    binary = write_offline_script(tmp_path)
    cli = make_cli(tmp_path, binary)
    await cli.trash("/my-files/HA/x.tar")  # must not raise


async def test_logout_network_failure_stays_signed_in(tmp_path):
    # A failed sign-out means the session likely survived — don't fake one the
    # next probe undoes.  Only passes on this fixture's stderr shape.
    binary = write_offline_script(tmp_path)
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    with pytest.raises(ProtonConnectionError):
        await cli.logout()
    assert cli.isAuthenticated() is True


async def test_logout_tolerates_benign_failure(tmp_path):
    binary = write_script(tmp_path, 'echo "already logged out" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    await cli.logout()  # must not raise
    assert cli.isAuthenticated() is False


async def test_logout_refuses_while_command_running(tmp_path):
    binary = write_script(tmp_path, 'sleep 2\necho "{}"\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    task = asyncio.create_task(cli.info("/my-files"))
    await asyncio.sleep(0.3)  # let it take the lock
    with pytest.raises(ProtonError):
        await cli.logout()
    assert cli.isAuthenticated() is True
    await task


async def test_unclassified_probe_failure_sets_warning(tmp_path):
    binary = write_script(tmp_path, 'echo "unexpected server error" >&2\nexit 2\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    assert await cli.checkAuth() is True  # state kept
    assert cli.authWarning() is not None


async def test_warning_not_set_when_signed_out(tmp_path):
    binary = write_script(tmp_path, 'echo "unexpected server error" >&2\nexit 2\n')
    cli = make_cli(tmp_path, binary)
    assert await cli.checkAuth() is False
    assert cli.authWarning() is None


async def test_warning_not_set_when_offline(tmp_path):
    binary = write_offline_script(tmp_path)
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    await cli.checkAuth()
    assert cli.authWarning() is None


async def test_warning_cleared_on_successful_probe(tmp_path):
    binary = write_script(tmp_path, 'echo "{\\"name\\": \\"my-files\\"}"\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    cli._auth_warning = "stale"
    assert await cli.checkAuth() is True
    assert cli.authWarning() is None


async def test_warning_cleared_on_definite_signout(tmp_path):
    binary = write_script(tmp_path, 'echo "You need to login first" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    cli._auth_warning = "stale"
    assert await cli.checkAuth() is False
    assert cli.authWarning() is None


async def test_start_login_offline_raises_connection_error(tmp_path):
    binary = write_script(
        tmp_path,
        'echo "Unable to connect. Is the computer able to access the url?"\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonConnectionError):
        await cli.startLogin()
    assert cli.loginInProgress() is False


async def test_checkauth_keeps_state_on_timeout(tmp_path):
    binary = write_script(tmp_path, 'sleep 5\n')
    cli = make_cli(tmp_path, binary)
    cli.config.override(Setting.PROTON_DRIVE_TIMEOUT_SECONDS, 1)
    cli._authenticated = True
    assert await cli.checkAuth() is True  # transient: keep last-known state


async def test_json_after_logline_with_brackets(tmp_path):
    binary = write_script(tmp_path, 'echo "processing batch [3] of 5"\necho "[{\\"name\\": \\"a.tar\\"}]"\n')
    cli = make_cli(tmp_path, binary)
    entries = await cli.listFolder("/my-files/HA")
    assert [e["name"] for e in entries] == ["a.tar"]


async def test_generic_error_maps_to_protonerror(tmp_path):
    binary = write_script(tmp_path, 'echo "something broke" >&2\nexit 3\n')
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonError) as ei:
        await cli.info("/my-files")
    assert ei.value.data().get("returncode") == 3


async def test_timeout(tmp_path):
    binary = write_script(tmp_path, 'sleep 5\n')
    cli = make_cli(tmp_path, binary)
    cli.config.override(Setting.PROTON_DRIVE_TIMEOUT_SECONDS, 1)
    with pytest.raises(ProtonTimeout):
        await cli.info("/my-files")


async def test_list_parses_array(tmp_path):
    binary = write_script(tmp_path, 'echo "[{\\"name\\": \\"a.tar\\"}, {\\"name\\": \\"b.tar\\"}]"\n')
    cli = make_cli(tmp_path, binary)
    entries = await cli.listFolder("/my-files/HA")
    assert [e["name"] for e in entries] == ["a.tar", "b.tar"]


async def test_list_parses_wrapped_object(tmp_path):
    binary = write_script(tmp_path, 'echo "{\\"items\\": [{\\"name\\": \\"a.tar\\"}]}"\n')
    cli = make_cli(tmp_path, binary)
    entries = await cli.listFolder("/my-files/HA")
    assert entries[0]["name"] == "a.tar"


async def test_json_embedded_in_log_lines(tmp_path):
    binary = write_script(tmp_path, 'echo "info: starting"\necho "[{\\"name\\": \\"a.tar\\"}]"\n')
    cli = make_cli(tmp_path, binary)
    entries = await cli.listFolder("/my-files/HA")
    assert entries[0]["name"] == "a.tar"


async def test_upload_command_args(tmp_path):
    binary = write_script(tmp_path, 'exit 0\n')
    cli = make_cli(tmp_path, binary)
    await cli.upload("/tmp/x.tar", "/my-files/HA")
    line = args_log(tmp_path)[-1]
    assert line == "filesystem upload -f replace -d skip /tmp/x.tar /my-files/HA"


async def test_download_command_args(tmp_path):
    binary = write_script(tmp_path, 'exit 0\n')
    cli = make_cli(tmp_path, binary)
    await cli.download("/my-files/HA/x.tar", "/tmp/dl")
    line = args_log(tmp_path)[-1]
    # "remove" (not "replace"): download's own strategy vocabulary.
    assert line == "filesystem download -f remove -d skip /my-files/HA/x.tar /tmp/dl"


LOGIN_BLOCK = (
    'echo "Sign in in your browser. Keep the terminal open."\n'
    'echo "Open following URL manually (can be on another device):"\n'
    'echo "https://account.proton.me/desktop/login?app=drive&pv=3#payload=abc123"\n'
)


async def test_start_login_returns_url_and_completes(tmp_path):
    binary = write_script(tmp_path, LOGIN_BLOCK + "sleep 0.2\nexit 0\n")
    cli = make_cli(tmp_path, binary)
    url = await cli.startLogin()
    assert url == "https://account.proton.me/desktop/login?app=drive&pv=3#payload=abc123"
    assert cli.loginInProgress() is True
    task = cli._login_task
    await task  # let the login "complete"
    assert cli.isAuthenticated() is True
    assert cli.loginInProgress() is False


async def test_start_login_errors_when_no_url(tmp_path):
    binary = write_script(tmp_path, 'echo "libsecret not available" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonError):
        await cli.startLogin()
    assert cli.loginInProgress() is False


async def test_cancel_login_kills_process(tmp_path):
    binary = write_script(tmp_path, LOGIN_BLOCK + "sleep 30\n")
    cli = make_cli(tmp_path, binary)
    url = await cli.startLogin()
    assert url.startswith("https://account.proton.me/")
    assert cli.loginInProgress() is True
    await cli.cancelLogin()
    assert cli.loginInProgress() is False
    assert cli.isAuthenticated() is False


async def test_start_login_missing_binary(tmp_path):
    cli = make_cli(tmp_path, str(tmp_path / "nope"))
    with pytest.raises(ProtonCliMissing):
        await cli.startLogin()


async def test_checkauth_skipped_during_interactive_login(tmp_path):
    # The CLI isn't documented as concurrency-safe; don't race `auth login`.
    binary = write_script(tmp_path, LOGIN_BLOCK + "sleep 30\n")
    cli = make_cli(tmp_path, binary)
    try:
        await cli.startLogin()
        invocations = len(args_log(tmp_path))
        assert await cli.checkAuth() is False  # cached state, no probe
        assert len(args_log(tmp_path)) == invocations
    finally:
        await cli.cancelLogin()


async def test_concurrent_start_login_dedupes(tmp_path):
    # Two near-simultaneous sign-in requests must not spawn two processes or tear
    # down each other's login; the second gets the same URL back.
    binary = write_script(tmp_path, LOGIN_BLOCK + "sleep 30\n")
    cli = make_cli(tmp_path, binary)
    try:
        u1, u2 = await asyncio.gather(cli.startLogin(), cli.startLogin())
        assert u1 == u2
        assert u1.startswith("https://account.proton.me/")
        # Exactly one underlying CLI process should have been launched.
        assert len(args_log(tmp_path)) == 1
        assert cli.loginInProgress() is True
    finally:
        await cli.cancelLogin()
    assert cli.loginInProgress() is False


async def test_login_url_trailing_punctuation_trimmed(tmp_path):
    binary = write_script(
        tmp_path,
        'echo "Open following URL manually:"\n'
        'echo "(https://account.proton.me/desktop/login?app=drive#payload=abc)."\n'
        'sleep 0.2\nexit 0\n')
    cli = make_cli(tmp_path, binary)
    url = await cli.startLogin()
    await cli._login_task
    assert url == "https://account.proton.me/desktop/login?app=drive#payload=abc"


async def test_delete_is_lenient_on_error(tmp_path):
    binary = write_script(tmp_path, 'echo "missing" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    # delete uses check=False, so a non-zero exit should not raise
    await cli.delete("/my-files/HA/x.tar")


async def test_trash_command_args_and_results(tmp_path):
    binary = write_script(tmp_path, 'echo "[{\\"uid\\": \\"abc\\", \\"ok\\": true}]"\n')
    cli = make_cli(tmp_path, binary)
    results = await cli.trash("/my-files/HA/x.tar", strict=True)
    line = args_log(tmp_path)[-1]
    assert line == "filesystem trash /my-files/HA/x.tar --json"
    assert results == [{"uid": "abc", "ok": True}]


async def test_trash_strict_fails_on_ok_false_result(tmp_path):
    # The CLI exits 0 even when a node's trash result is ok=false, so strict
    # mode must catch the failure from the JSON results themselves.
    binary = write_script(tmp_path, 'echo "[{\\"uid\\": \\"abc\\", \\"ok\\": false}]"\n')
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonError):
        await cli.trash("/my-files/HA/x.tar", strict=True)


async def test_trash_lenient_returns_no_results_on_error(tmp_path):
    binary = write_script(tmp_path, 'echo "not found" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    assert await cli.trash("/my-files/HA/x.tar") == []


async def test_json_payload_wins_over_trailing_log_json(tmp_path):
    # A log line printed AFTER the payload — even one ending in valid JSON —
    # must not displace the payload (it would make the folder read as empty or
    # wrong, and downstream sweeps act on listings).
    binary = write_script(
        tmp_path,
        'echo "[{\\"name\\": \\"a.tar\\"}]"\n'
        'echo "LOG done {\\"count\\": 1}"\n')
    cli = make_cli(tmp_path, binary)
    entries = await cli.listFolder("/my-files/HA")
    assert [e["name"] for e in entries] == ["a.tar"]


async def test_trash_parses_log_prefixed_streaming_array(tmp_path):
    # The CLI's --json output is a MULTI-LINE streaming array; stray log lines
    # before it must not collapse the parse to a single item (which would hide
    # an ok=false from strict mode and starve the purge of its uid).
    binary = write_script(
        tmp_path,
        'echo "LOG [warn]: something"\n'
        'printf "[\\n{\\"uid\\": \\"a\\", \\"ok\\": false},\\n{\\"uid\\": \\"b\\", \\"ok\\": true}\\n]\\n"\n')
    cli = make_cli(tmp_path, binary)
    results = await cli.trash("/my-files/HA/x.tar")
    assert results == [{"uid": "a", "ok": False}, {"uid": "b", "ok": True}]
    with pytest.raises(ProtonError):
        await cli.trash("/my-files/HA/x.tar", strict=True)


async def test_trash_strict_catches_ok_false_behind_trailing_log(tmp_path):
    # A trailing log line breaks whole-array recovery, and salvage degrades to
    # the single result object; strict mode must still see the ok=false inside
    # it instead of discarding it as the wrong shape.
    binary = write_script(
        tmp_path,
        'printf "[\\n{\\"uid\\": \\"a\\", \\"ok\\": false}\\n]\\nLOG done\\n"\n')
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonError):
        await cli.trash("/my-files/HA/x.tar", strict=True)


async def test_trash_tolerates_unparseable_output(tmp_path):
    # A CLI output-shape change must degrade to "no results" (which blocks the
    # trash purge downstream), never to an error that fails the removal.
    binary = write_script(tmp_path, 'echo "trashed OK, no json here"\n')
    cli = make_cli(tmp_path, binary)
    assert await cli.trash("/my-files/HA/x.tar", strict=True) == []


# --- Corrupt events.lock self-heal --------------------------------------------
# An unparseable events.lock crashes every CLI run at init (verified against
# the real binary, v0.4.6-v0.8.0).  The wrapper deletes it and retries once.

def _plant_lock(tmp_path, content: bytes):
    # conftest pins XDG_DATA_HOME to tmp_path/"xdg-data" for env isolation.
    lock = tmp_path / "xdg-data" / "proton-drive-cli" / "events.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(content)
    return lock


def write_crash_while_lock_exists_script(tmp_path):
    # Mimics the real crash: only a banner on stderr (the stack goes to
    # stdout), recovering as soon as the lock file is gone.
    return write_script(tmp_path, (
        'if [ -e "$XDG_DATA_HOME/proton-drive-cli/events.lock" ]; then\n'
        '  echo "===============================================" >&2\n'
        '  echo "SyntaxError: JSON Parse error: Unrecognized token" \n'
        '  exit 1\n'
        'fi\n'
        'echo "{}"\n'))


async def test_corrupt_lock_healed_and_retried(tmp_path):
    lock = _plant_lock(tmp_path, b"\x00" * 13)  # what an unclean shutdown leaves
    binary = write_crash_while_lock_exists_script(tmp_path)
    cli = make_cli(tmp_path, binary)
    assert await cli.info("/my-files") == {}
    assert not lock.exists()
    assert len(args_log(tmp_path)) == 2


async def test_corrupt_lock_retry_happens_only_once(tmp_path):
    # The CLI keeps crashing and leaves a corrupt lock behind every run:
    # exactly one heal+retry, then the failure surfaces.
    _plant_lock(tmp_path, b"\x00" * 13)
    binary = write_script(tmp_path, (
        'mkdir -p "$XDG_DATA_HOME/proton-drive-cli"\n'
        'printf \'\\0\\0\\0\' > "$XDG_DATA_HOME/proton-drive-cli/events.lock"\n'
        'exit 1\n'))
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonError):
        await cli.info("/my-files")
    assert len(args_log(tmp_path)) == 2


async def test_no_retry_when_lock_is_healthy(tmp_path):
    lock = _plant_lock(tmp_path, b'{"pid": 999999}')
    binary = write_script(tmp_path, 'echo "unrelated failure" >&2\nexit 2\n')
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonError):
        await cli.info("/my-files")
    assert lock.exists()
    assert len(args_log(tmp_path)) == 1


async def test_no_retry_when_lock_is_absent(tmp_path):
    binary = write_script(tmp_path, 'echo "unrelated failure" >&2\nexit 2\n')
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonError):
        await cli.info("/my-files")
    assert len(args_log(tmp_path)) == 1


async def test_classified_failure_does_not_heal_lock(tmp_path):
    # A classified failure already explains itself, and the lock crash happens
    # before the login gate — so an auth answer means the lock isn't the cause.
    lock = _plant_lock(tmp_path, b"\x00" * 13)
    binary = write_script(tmp_path, 'echo "You need to login first" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonNotAuthenticated):
        await cli.info("/my-files")
    assert lock.exists()
    assert len(args_log(tmp_path)) == 1


async def test_nan_lock_is_treated_as_corrupt(tmp_path):
    # Python's json accepts NaN/Infinity but Bun's JSON.parse (the CLI) crashes.
    lock = _plant_lock(tmp_path, b"NaN")
    binary = write_crash_while_lock_exists_script(tmp_path)
    cli = make_cli(tmp_path, binary)
    assert await cli.info("/my-files") == {}
    assert not lock.exists()
    assert len(args_log(tmp_path)) == 2


async def test_deeply_nested_lock_is_not_deleted(tmp_path):
    # JSC parses deep nesting iteratively and the CLI then heals the non-object
    # lock itself; Python's RecursionError must not be read as corruption.
    lock = _plant_lock(tmp_path, b"[" * 100000 + b"]" * 100000)
    binary = write_script(tmp_path, 'echo "unrelated failure" >&2\nexit 2\n')
    cli = make_cli(tmp_path, binary)
    with pytest.raises(ProtonError):
        await cli.info("/my-files")
    assert lock.exists()
    assert len(args_log(tmp_path)) == 1


def test_events_lock_path_mirrors_cli_resolution(tmp_path):
    cli = make_cli(tmp_path, "unused")
    assert (cli._eventsLockPath({"PROTON_DRIVE_CACHE_DIR": "/cache"})
            == "/cache/events.lock")
    assert (cli._eventsLockPath({"XDG_DATA_HOME": "/xdg", "HOME": "/h"})
            == "/xdg/proton-drive-cli/events.lock")
    # Empty XDG_DATA_HOME falls through to HOME, like the CLI's `||`.
    assert (cli._eventsLockPath({"XDG_DATA_HOME": "", "HOME": "/h"})
            == "/h/.local/share/proton-drive-cli/events.lock")
