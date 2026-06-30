import os
import json
import collections

import pytest

from backup.config import Config, Setting
from backup.const import SOURCE_PROTON_DRIVE
from backup.exceptions import LogicError, UploadFailed
from backup.proton.protonsource import ProtonSource
from backup.proton.protoncli import PROTON_ROOT
from backup.proton.exceptions import ProtonNotAuthenticated
from backup.model.protonbackup import (ProtonBackup, TAR_SUFFIX, METADATA_SUFFIX,
                                       PROP_RETAINED)
from backup.time import Time

from tests.fakes import FakeProtonCli, FakeInfo, FakeSource, FakeBackup


def make_source(tmp_path, cli=None, authed=True):
    cfg = Config()
    cfg.override(Setting.PROTON_DATA_PATH, str(tmp_path / "proton"))
    cfg.override(Setting.PROTON_FOLDER_NAME, "HA Backups")
    cli = cli or FakeProtonCli(authenticated=authed)
    return ProtonSource(cfg, Time(), cli, FakeInfo()), cli


def meta_bytes(slug="abc123", name="Full Backup", retained="False"):
    from backup.const import (NECESSARY_PROP_KEY_SLUG, NECESSARY_PROP_KEY_DATE,
                              NECESSARY_PROP_KEY_NAME)
    return json.dumps({
        NECESSARY_PROP_KEY_SLUG: slug,
        NECESSARY_PROP_KEY_DATE: "2026-06-27T01:02:03+00:00",
        NECESSARY_PROP_KEY_NAME: name,
        "type": "full", "version": "2026.6.0", "protected": "True",
        PROP_RETAINED: retained,
    }).encode("utf-8")


def test_identity(tmp_path):
    src, _ = make_source(tmp_path)
    assert src.name() == SOURCE_PROTON_DRIVE
    assert src.title() == "Proton Drive"
    assert src.folderName() == "HA Backups"
    assert src.folderPath() == "/my-files/HA Backups"
    assert src.maxCount() == Config().get(Setting.MAX_BACKUPS_IN_PROTON_DRIVE)


def test_enabled_reflects_auth(tmp_path):
    src, cli = make_source(tmp_path, authed=False)
    assert src.enabled() is False
    cli._authenticated = True
    assert src.enabled() is True


def test_needs_configuration_when_upload_disabled(tmp_path):
    src, cli = make_source(tmp_path, authed=False)
    src.config.override(Setting.ENABLE_PROTON_UPLOAD, False)
    assert src.needsConfiguration() is False
    src.config.override(Setting.ENABLE_PROTON_UPLOAD, True)
    assert src.needsConfiguration() is True


async def test_create_not_allowed(tmp_path):
    src, _ = make_source(tmp_path)
    with pytest.raises(LogicError):
        await src.create(None)


async def test_get_pairs_tar_and_metadata(tmp_path):
    src, cli = make_source(tmp_path)
    cli.seed_backup("/my-files/HA Backups", "abc123", meta_bytes())
    result = await src.get()
    assert set(result.keys()) == {"abc123"}
    b = result["abc123"]
    assert isinstance(b, ProtonBackup)
    assert b.name() == "Full Backup"
    assert b.size() == len(b"tarcontents")


def test_folder_name_sanitized(tmp_path):
    src, _ = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "  My/Backups\\here  ")
    assert src.folderName() == "My-Backups-here"
    assert "/" not in src.folderName()
    src.config.override(Setting.PROTON_FOLDER_NAME, "")
    assert src.folderName() == "Home Assistant Backups"


def test_folder_name_strips_leading_dash(tmp_path):
    # A leading "-" would be parsed by the CLI as a flag, since the name is
    # passed to `create-folder` as a positional argv token.
    src, _ = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "-rf nope")
    assert not src.folderName().startswith("-")
    assert src.folderName() == "rf nope"
    src.config.override(Setting.PROTON_FOLDER_NAME, "--all")
    assert src.folderName() == "all"
    # Collapses to dashes then empties out -> falls back to the default name.
    src.config.override(Setting.PROTON_FOLDER_NAME, "/-/-")
    assert src.folderName() == "Home Assistant Backups"


def test_folder_name_rejects_dot_traversal(tmp_path):
    # A name made entirely of dots would make folderPath() resolve to the drive
    # root or its parent; it must fall back to the default name instead.
    src, _ = make_source(tmp_path)
    for traversal in (".", "..", "..."):
        src.config.override(Setting.PROTON_FOLDER_NAME, traversal)
        assert src.folderName() == "Home Assistant Backups"
        assert src.folderPath() == PROTON_ROOT + "/Home Assistant Backups"
    # A name that merely contains dots is still allowed.
    src.config.override(Setting.PROTON_FOLDER_NAME, "..backups")
    assert src.folderName() == "..backups"


async def test_create_folder_never_receives_leading_dash(tmp_path):
    src, cli = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "-flagish")
    await src.get()
    create_calls = [c for c in cli.calls if c[0] == "createFolder"]
    assert create_calls, "expected the folder to be created"
    for _, parent, name in create_calls:
        assert not name.startswith("-")


async def test_get_trashes_orphan_metadata(tmp_path):
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    # A metadata sidecar with no matching tar (e.g. a prior delete half-failed).
    cli.files[folder + "/ghost" + METADATA_SUFFIX] = meta_bytes(slug="ghost")
    result = await src.get()
    assert result == {}
    assert ("trash", folder + "/ghost" + METADATA_SUFFIX) in cli.calls
    assert folder + "/ghost" + METADATA_SUFFIX not in cli.files


async def test_get_skips_tar_without_metadata(tmp_path):
    src, cli = make_source(tmp_path)
    cli.folders.add("/my-files/HA Backups")
    cli.files["/my-files/HA Backups/orphan" + TAR_SUFFIX] = b"x"
    result = await src.get()
    assert result == {}


async def test_get_creates_folder_when_missing(tmp_path):
    src, cli = make_source(tmp_path)
    await src.get()
    assert ("createFolder", "/my-files", "HA Backups") in cli.calls


async def test_get_unauthenticated_raises(tmp_path):
    src, cli = make_source(tmp_path, authed=False)
    with pytest.raises(ProtonNotAuthenticated):
        await src.get()


async def test_save_uploads_tar_and_metadata(tmp_path):
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    result = await src.save(backup, FakeSource(b"hello-world-payload"))
    assert isinstance(result, ProtonBackup)
    folder = "/my-files/HA Backups"
    assert cli.files[folder + "/abc123" + TAR_SUFFIX] == b"hello-world-payload"
    meta = json.loads(cli.files[folder + "/abc123" + METADATA_SUFFIX])
    assert meta["snapshot_slug"] == "abc123"
    assert meta["protected"] == "True"
    assert cli.upload_count == 2


async def test_save_then_get_roundtrip(tmp_path):
    src, cli = make_source(tmp_path)
    await src.save(FakeBackup(slug="zzz999", name="Nightly"), FakeSource(b"data"))
    result = await src.get()
    assert "zzz999" in result
    assert result["zzz999"].name() == "Nightly"


async def test_save_records_retain_flag(tmp_path):
    src, cli = make_source(tmp_path)
    await src.save(FakeBackup(retain=True), FakeSource(b"d"))
    meta = json.loads(cli.files["/my-files/HA Backups/abc123" + METADATA_SUFFIX])
    assert meta[PROP_RETAINED] == "True"


async def test_save_failure_wraps_uploadfailed(tmp_path):
    src, cli = make_source(tmp_path)

    async def boom(*a, **k):
        raise RuntimeError("disk full")
    cli.upload = boom
    with pytest.raises(UploadFailed):
        await src.save(FakeBackup(), FakeSource(b"d"))


async def test_save_surfaces_low_space_error(tmp_path):
    # The disk-space pre-flight raises a typed LowSpaceError; it must reach the
    # caller with its actionable message/data rather than being flattened into a
    # generic UploadFailed.
    import shutil as _shutil
    from backup.exceptions import LowSpaceError
    from backup.proton import protonsource as ps

    src, cli = make_source(tmp_path)
    Usage = collections.namedtuple("Usage", ["total", "used", "free"])
    orig_disk_usage = ps.shutil.disk_usage

    def tiny_free(path):
        return Usage(total=1024, used=1024, free=1)
    ps.shutil.disk_usage = tiny_free
    try:
        with pytest.raises(LowSpaceError) as exc:
            await src.save(FakeBackup(), FakeSource(b"some-backup-bytes"))
    finally:
        ps.shutil.disk_usage = orig_disk_usage
    assert exc.value.space_remaining == 1


async def test_read_downloads_and_streams(tmp_path):
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    proton = await src.save(backup, FakeSource(b"the-actual-tar-bytes"))
    backup.addSource(proton)
    stream = await src.read(backup)
    collected = bytearray()
    async with stream:
        async for chunk in stream:
            collected += chunk
    assert bytes(collected) == b"the-actual-tar-bytes"


async def test_read_then_aclose_cleans_temp(tmp_path):
    # Mirrors the UI download path: setup() + generator() + aclose(), no
    # `async with`.  The staged temp file and its temp dir must be removed.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"payload-bytes")))
    stream = await src.read(backup)
    await stream.setup()
    out = bytearray()
    async for chunk in stream.generator(4):
        out += chunk
    await stream.aclose()
    assert bytes(out) == b"payload-bytes"
    # The proton temp dir should have no leftover staging directories.
    assert os.listdir(src._tempDir()) == []


async def test_save_orphan_tar_cleaned_when_metadata_fails(tmp_path):
    src, cli = make_source(tmp_path)
    real_upload = cli.upload
    folder = "/my-files/HA Backups"

    async def upload(local_path, parent_path, conflict="replace"):
        if local_path.endswith(METADATA_SUFFIX):
            raise RuntimeError("metadata upload failed")
        return await real_upload(local_path, parent_path, conflict)
    cli.upload = upload

    with pytest.raises(UploadFailed):
        await src.save(FakeBackup(slug="orph01"), FakeSource(b"d"))
    # The tar was uploaded then rolled back (trashed); no orphan tar should remain.
    assert folder + "/orph01" + TAR_SUFFIX not in cli.files
    assert ("trash", folder + "/orph01" + TAR_SUFFIX) in cli.calls


async def test_delete_removes_both_files(tmp_path):
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    folder = "/my-files/HA Backups"
    await src.delete(backup)
    assert folder + "/abc123" + TAR_SUFFIX not in cli.files
    assert folder + "/abc123" + METADATA_SUFFIX not in cli.files
    assert backup.getSource(SOURCE_PROTON_DRIVE) is None


async def test_delete_failure_keeps_local_source(tmp_path):
    # If the remote tar delete fails, we must NOT drop the local source,
    # otherwise the backup reappears next sync and retention never converges.
    from backup.proton.exceptions import ProtonError
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    cli.trash_should_fail = True
    folder = "/my-files/HA Backups"
    with pytest.raises(ProtonError):
        await src.delete(backup)
    assert backup.getSource(SOURCE_PROTON_DRIVE) is not None
    assert folder + "/abc123" + TAR_SUFFIX in cli.files


async def test_delete_uses_trash_not_permanent_delete(tmp_path):
    # The CLI's permanent `delete` only works on already-trashed items, so the
    # source must remove backups via `trash`, never a live `delete`.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    await src.delete(backup)
    ops = [c[0] for c in cli.calls]
    assert "trash" in ops
    assert "delete" not in ops


async def test_ensure_folder_reuses_existing(tmp_path):
    src, cli = make_source(tmp_path)
    cli.seed_backup("/my-files/HA Backups", "abc123", meta_bytes())
    await src.get()
    assert not any(c[0] == "createFolder" for c in cli.calls)


async def test_ensure_folder_only_checks_once(tmp_path):
    src, cli = make_source(tmp_path)
    await src.get()
    await src.get()
    assert sum(1 for c in cli.calls if c[0] == "createFolder") == 1


async def test_get_self_heals_when_folder_vanishes(tmp_path):
    src, cli = make_source(tmp_path)
    await src.get()  # creates + latches the folder
    folder = "/my-files/HA Backups"
    cli.folders.discard(folder)  # folder removed out from under us
    result = await src.get()      # listFolder(folder) errors -> re-ensure + retry
    assert result == {}
    assert folder in cli.folders  # recreated
    assert sum(1 for c in cli.calls if c[0] == "createFolder") == 2


async def test_delete_without_source_raises(tmp_path):
    src, _ = make_source(tmp_path)
    with pytest.raises(LogicError):
        await src.delete(FakeBackup())


async def test_retain_rewrites_metadata(tmp_path):
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    item = await src.save(backup, FakeSource(b"d"))
    backup.addSource(item)
    assert item.retained() is False
    await src.retain(backup, True)
    meta = json.loads(cli.files["/my-files/HA Backups/abc123" + METADATA_SUFFIX])
    assert meta[PROP_RETAINED] == "True"
    assert item.retained() is True


async def test_retain_noop_when_unchanged(tmp_path):
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    item = await src.save(backup, FakeSource(b"d"))
    backup.addSource(item)
    before = cli.upload_count
    await src.retain(backup, False)  # already False
    assert cli.upload_count == before


async def test_note_rewrites_metadata(tmp_path):
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    item = await src.save(backup, FakeSource(b"d"))
    backup.addSource(item)
    await src.note(backup, "important")
    meta = json.loads(cli.files["/my-files/HA Backups/abc123" + METADATA_SUFFIX])
    assert meta["note"] == "important"


async def test_loadmetadata_filename_fallback(tmp_path):
    # If the CLI writes the downloaded sidecar under a different name, the lone
    # file in the temp dir is still used.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.files[folder + "/abc123" + TAR_SUFFIX] = b"tar"
    cli.files[folder + "/abc123" + METADATA_SUFFIX] = meta_bytes()

    orig_download = cli.download

    async def download(remote_path, local_folder, conflict="replace"):
        # Simulate the CLI writing the sidecar under a decrypted/different name.
        if remote_path.endswith(METADATA_SUFFIX):
            os.makedirs(local_folder, exist_ok=True)
            with open(os.path.join(local_folder, "decrypted-name.json"), "wb") as f:
                f.write(cli.files[remote_path])
            return
        return await orig_download(remote_path, local_folder, conflict)
    cli.download = download

    result = await src.get()
    assert "abc123" in result


async def test_metadata_cache_avoids_redownload(tmp_path):
    src, cli = make_source(tmp_path)
    cli.seed_backup("/my-files/HA Backups", "abc123", meta_bytes())
    await src.get()
    after_first = cli.download_count
    assert after_first >= 1
    await src.get()
    assert cli.download_count == after_first  # served from cache


async def test_start_checks_auth(tmp_path):
    src, cli = make_source(tmp_path)
    await src.start()
    assert ("checkAuth",) in cli.calls
