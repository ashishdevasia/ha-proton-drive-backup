import asyncio
import json
import os

import pytest

from backup.config import Config, Setting
from backup.proton import ProtonCli
from backup.proton.protoncli import _as_entry_list
from backup.proton.protonsource import _entry_name, _entry_size, _entry_is_folder
from backup.proton.exceptions import ProtonNotAuthenticated, ProtonCliMissing
from backup.model.protonbackup import ProtonBackup, TAR_SUFFIX, METADATA_SUFFIX
from backup.const import (NECESSARY_PROP_KEY_SLUG, NECESSARY_PROP_KEY_DATE,
                          NECESSARY_PROP_KEY_NAME, SOURCE_PROTON_DRIVE)


def _meta():
    return {
        NECESSARY_PROP_KEY_SLUG: "abc123",
        NECESSARY_PROP_KEY_DATE: "2026-06-27T01:02:03+00:00",
        NECESSARY_PROP_KEY_NAME: "Full Backup",
        "type": "full",
        "version": "2026.6.0",
        "protected": "True",
        "retained": "False",
    }


def test_entry_list_normalization():
    assert len(_as_entry_list([{"name": "a"}, {"name": "b"}])) == 2
    assert len(_as_entry_list({"items": [{"name": "a"}]})) == 1
    assert len(_as_entry_list({"children": [{"name": "a"}, {"name": "b"}]})) == 2
    assert _as_entry_list(None) == []


def test_entry_name_and_size():
    assert _entry_name({"name": "/my-files/HA/abc123.tar"}) == "abc123.tar"
    assert _entry_name({"path": "x/y/z.metadata.json"}) == "z.metadata.json"
    assert _entry_name({}) is None
    assert _entry_size({"size": "1048576"}) == 1048576
    assert _entry_size({"fileSize": 42}) == 42
    assert _entry_size({}) == 0


def test_entry_name_and_size_real_proton_shape():
    # The Proton CLI wraps the (E2EE) name in a result object and reports the
    # true content size under activeRevision.value.claimedSize.  Verified against
    # the real `proton-drive filesystem list --json` output.
    file_node = {
        "name": {"ok": True, "value": "e2e0001.tar"},
        "type": "file",
        "totalStorageSize": 96,
        "activeRevision": {"ok": True, "value": {"storageSize": 96, "claimedSize": 18}},
    }
    assert _entry_name(file_node) == "e2e0001.tar"
    assert _entry_size(file_node) == 18  # claimedSize, not the encrypted 96
    assert _entry_is_folder(file_node) is False

    folder_node = {"name": {"ok": True, "value": "Home Assistant Backups"}, "type": "folder"}
    assert _entry_name(folder_node) == "Home Assistant Backups"
    assert _entry_is_folder(folder_node) is True

    # An entry that doesn't say its type is "unknown", not file or folder, so
    # callers can decide how to degrade on a CLI output-shape change.
    assert _entry_is_folder({"name": "x"}) is None

    # If a future CLI wraps type in the same result object it uses for name,
    # it must still be understood (the sweeps fail closed on unknown types).
    assert _entry_is_folder({"type": {"ok": True, "value": "folder"}}) is True
    assert _entry_is_folder({"type": {"ok": True, "value": "file"}}) is False

    # A name that couldn't be decrypted should be skipped, not crash.
    assert _entry_name({"name": {"ok": False, "error": "x"}}) is None


def test_protonbackup_from_sidecar():
    b = ProtonBackup(_meta(), "abc123" + TAR_SUFFIX, 1048576, "/my-files/Home Assistant Backups")
    assert b.slug() == "abc123"
    assert b.name() == "Full Backup"
    assert b.size() == 1048576
    assert b.protected() is True
    assert b.retained() is False
    assert b.source() == SOURCE_PROTON_DRIVE
    assert b.tarPath() == "/my-files/Home Assistant Backups/abc123.tar"
    assert b.metadataName() == "abc123" + METADATA_SUFFIX
    assert b.metadataPath() == "/my-files/Home Assistant Backups/abc123.metadata.json"


def test_metadata_path_ignores_tampered_slug():
    # The slug lives in the (potentially tampered) sidecar contents, but the
    # metadata path must be derived from the trusted remote tar filename so a
    # slug like "../evil" can't make trash/upload escape the backup folder.
    meta = _meta()
    meta[NECESSARY_PROP_KEY_SLUG] = "../../evil"
    b = ProtonBackup(meta, "abc123" + TAR_SUFFIX, 10, "/my-files/Home Assistant Backups")
    assert b.metadataName() == "abc123" + METADATA_SUFFIX
    assert b.metadataPath() == "/my-files/Home Assistant Backups/abc123.metadata.json"
    assert ".." not in b.metadataPath()


def test_protonbackup_falls_back_to_filename_when_no_name():
    meta = _meta()
    del meta[NECESSARY_PROP_KEY_NAME]
    b = ProtonBackup(meta, "abc123" + TAR_SUFFIX, 10, "/folder")
    assert b.name() == "abc123"


def test_metadata_json_roundtrips(tmp_path):
    meta = _meta()
    path = tmp_path / ("abc123" + METADATA_SUFFIX)
    path.write_text(json.dumps(meta))
    loaded = json.loads(path.read_text())
    b = ProtonBackup(loaded, "abc123" + TAR_SUFFIX, 10, "/folder")
    assert b.slug() == "abc123"


def _cli():
    cfg = Config()
    binary = os.environ.get("PROTON_CLI_PATH")
    cfg.override(Setting.PROTON_CLI_PATH, binary or "/no/such/proton-drive")
    cfg.override(Setting.PROTON_DATA_PATH, "/tmp/proton-test")
    return ProtonCli(cfg), bool(binary)


@pytest.mark.asyncio
async def test_missing_binary_raises():
    cfg = Config()
    cfg.override(Setting.PROTON_CLI_PATH, "/no/such/proton-drive")
    cfg.override(Setting.PROTON_DATA_PATH, "/tmp/proton-test")
    cli = ProtonCli(cfg)
    with pytest.raises(ProtonCliMissing):
        await cli.checkAuth()


@pytest.mark.asyncio
async def test_checkauth_does_not_block_on_running_command():
    # While another CLI command holds the lock (e.g. a long upload), checkAuth
    # must return the cached state immediately instead of queueing a probe
    # behind it — otherwise a Web UI poll could hang for the whole transfer.
    cli, _ = _cli()
    cli._authenticated = True
    await cli._cli_lock.acquire()
    try:
        result = await asyncio.wait_for(cli.checkAuth(), timeout=1.0)
    finally:
        cli._cli_lock.release()
    assert result is True


@pytest.mark.asyncio
async def test_real_cli_unauthenticated():
    """If PROTON_CLI_PATH points at the real binary (no session), checkAuth is False."""
    binary = os.environ.get("PROTON_CLI_PATH")
    if not binary or not os.path.exists(binary):
        pytest.skip("PROTON_CLI_PATH not set to a real binary")
    cfg = Config()
    cfg.override(Setting.PROTON_CLI_PATH, binary)
    cfg.override(Setting.PROTON_DATA_PATH, "/tmp/proton-test")
    cli = ProtonCli(cfg)
    assert await cli.checkAuth() is False
    with pytest.raises(ProtonNotAuthenticated):
        await cli.info("/my-files")
