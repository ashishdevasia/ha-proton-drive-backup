import asyncio
import os
import stat

import pytest

from backup.config import Config, Setting
from backup.proton import ProtonCli
from backup.proton.exceptions import (ProtonNotAuthenticated, ProtonCliMissing,
                                      ProtonTimeout, ProtonError)


def write_script(tmp_path, body):
    """Create an executable fake proton-drive that logs its args and runs body."""
    path = tmp_path / "fake-proton"
    script = "#!/usr/bin/env bash\n" + 'echo "$@" >> "' + str(tmp_path / "args.log") + '"\n' + body
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    return str(path)


def make_cli(tmp_path, binary):
    cfg = Config()
    cfg.override(Setting.PROTON_CLI_PATH, binary)
    cfg.override(Setting.PROTON_DATA_PATH, str(tmp_path / "data"))
    cfg.override(Setting.PROTON_DRIVE_TIMEOUT_SECONDS, 5)
    cfg.override(Setting.PROTON_TRANSFER_TIMEOUT_SECONDS, 5)
    return ProtonCli(cfg)


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


async def test_not_authenticated_detected(tmp_path):
    binary = write_script(tmp_path, 'echo "Failed to load session from secrets: libsecret not available" >&2\nexit 1\n')
    cli = make_cli(tmp_path, binary)
    assert await cli.checkAuth() is False
    with pytest.raises(ProtonNotAuthenticated):
        await cli.info("/my-files")


async def test_marker_in_successful_stdout_does_not_flip_auth(tmp_path):
    # A successful (exit 0) command whose JSON payload happens to contain an
    # auth-marker substring (e.g. a backup named "unauthorized.tar" or a folder
    # called "not authenticated") must NOT be treated as a sign-out.
    binary = write_script(tmp_path, 'echo "[{\\"name\\": \\"unauthorized.tar\\"}, {\\"name\\": \\"not-logged-in.tar\\"}]"\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    entries = await cli.listFolder("/my-files/HA")
    assert [e["name"] for e in entries] == ["unauthorized.tar", "not-logged-in.tar"]
    assert cli.isAuthenticated() is True


async def test_marker_only_checked_on_failure(tmp_path):
    # Marker on stderr but exit 0 should not raise (auth errors always exit non-zero).
    binary = write_script(tmp_path, 'echo "note: session expired warning" >&2\necho "{}"\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    await cli.info("/my-files")  # must not raise
    assert cli.isAuthenticated() is True


async def test_checkauth_false_on_unrecognized_failure(tmp_path):
    # A failed probe with no known auth marker should be treated as signed out,
    # not left at a possibly-stale "authenticated" state.
    binary = write_script(tmp_path, 'echo "token refresh failed in an unexpected way" >&2\nexit 2\n')
    cli = make_cli(tmp_path, binary)
    cli._authenticated = True
    assert await cli.checkAuth() is False


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
    assert line == "filesystem upload -c replace /tmp/x.tar /my-files/HA"


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
