import os
import json
import collections

import pytest

from backup.config import Config, Setting
from backup.const import SOURCE_PROTON_DRIVE
from backup.exceptions import LogicError, UploadFailed
from backup.proton.protonsource import ProtonSource
from backup.proton.protoncli import PROTON_ROOT
from backup.proton.exceptions import ProtonNotAuthenticated, ProtonError
from backup.model.protonbackup import (ProtonBackup, TAR_SUFFIX, METADATA_SUFFIX,
                                       PROP_RETAINED)
from backup.time import Time

from tests.fakes import (FakeProtonCli, FakeInfo, FakeSource, FakeBackup,
                         write_script, make_cli)


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


async def test_presync_reprobes_only_when_flagged_out(tmp_path):
    # While flagged as signed out the sync loop never consults this source, so
    # preSync is the only chance to notice the session became usable again.
    src, cli = make_source(tmp_path, authed=False)
    await src.preSync()
    assert ("checkAuth",) in cli.calls
    # Once authenticated there's nothing to recover; don't add a probe per sync.
    cli.calls.clear()
    cli._authenticated = True
    await src.preSync()
    assert ("checkAuth",) not in cli.calls


async def test_presync_survives_missing_cli(tmp_path):
    # A missing CLI must not fail the sync (HA-side backups included).
    src, _ = make_source(tmp_path, cli=make_cli(tmp_path, str(tmp_path / "nope")))
    await src.preSync()  # must not raise
    assert src.enabled() is False


async def test_presync_recovers_after_outage(tmp_path):
    # An internet outage can leave the CLI wrapper flagged as signed out even
    # though the on-disk session is still valid.  Once connectivity is back,
    # the pre-sync probe must re-enable the destination without user action.
    binary = write_script(tmp_path, 'echo "{\\"name\\": \\"my-files\\"}"\n')
    src, _ = make_source(tmp_path, cli=make_cli(tmp_path, binary))
    assert src.enabled() is False  # flagged out, e.g. by a probe during the outage
    await src.preSync()
    assert src.enabled() is True


async def test_signout_logs_out_and_resets_state(tmp_path):
    src, cli = make_source(tmp_path)
    await src.get()  # ensures the folder and caches state
    assert src._ensured_path == src.folderPath()
    await src.signOut()
    assert ("logout",) in cli.calls
    assert cli.isAuthenticated() is False
    assert src._ensured_path is None
    assert src._meta_cache == {}


async def test_signout_tolerates_already_signed_out(tmp_path):
    src, cli = make_source(tmp_path)
    src._ensured_path = src.folderPath()

    async def dead_session_logout():
        raise ProtonNotAuthenticated("no session")
    cli.logout = dead_session_logout

    await src.signOut()  # must not raise
    assert src._ensured_path is None


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


def test_folder_name_supports_nesting(tmp_path):
    src, _ = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "backups/ha")
    assert src.folderSegments() == ["backups", "ha"]
    assert src.folderName() == "backups/ha"
    assert src.folderPath() == "/my-files/backups/ha"
    # Backslashes separate too, and whitespace is stripped per segment.
    src.config.override(Setting.PROTON_FOLDER_NAME, "  My/ Backups\\here  ")
    assert src.folderSegments() == ["My", "Backups", "here"]
    src.config.override(Setting.PROTON_FOLDER_NAME, "")
    assert src.folderName() == "Home Assistant Backups"


def test_folder_name_strips_leading_dash(tmp_path):
    # A leading "-" would be parsed by the CLI as a flag, since each segment is
    # passed to `create-folder` as a positional argv token.
    src, _ = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "-rf nope")
    assert not src.folderName().startswith("-")
    assert src.folderName() == "rf nope"
    src.config.override(Setting.PROTON_FOLDER_NAME, "--all")
    assert src.folderName() == "all"
    # Sanitization applies per segment.
    src.config.override(Setting.PROTON_FOLDER_NAME, "-a/--b")
    assert src.folderSegments() == ["a", "b"]
    # Stripping reaches a fixpoint: a dash hiding behind whitespace must not
    # survive ("- -rf" would otherwise sanitize to "-rf").
    src.config.override(Setting.PROTON_FOLDER_NAME, "- -rf x")
    assert src.folderSegments() == ["rf x"]
    src.config.override(Setting.PROTON_FOLDER_NAME, "a/- --json")
    assert src.folderSegments() == ["a", "json"]
    src.config.override(Setting.PROTON_FOLDER_NAME, "- ..")  # dash then traversal
    assert src.folderSegments() == ["Home Assistant Backups"]
    # Every segment empties out -> falls back to the default name.
    src.config.override(Setting.PROTON_FOLDER_NAME, "/-/-")
    assert src.folderName() == "Home Assistant Backups"


def test_folder_name_rejects_dot_traversal(tmp_path):
    # A segment made entirely of dots would make folderPath() escape toward (or
    # past) the drive root; such segments are dropped.
    src, _ = make_source(tmp_path)
    for traversal in (".", "..", "..."):
        src.config.override(Setting.PROTON_FOLDER_NAME, traversal)
        assert src.folderName() == "Home Assistant Backups"
        assert src.folderPath() == PROTON_ROOT + "/Home Assistant Backups"
    # Dot and empty segments are dropped from nested paths too.
    src.config.override(Setting.PROTON_FOLDER_NAME, "a//./../b")
    assert src.folderSegments() == ["a", "b"]
    # A name that merely contains dots is still allowed.
    src.config.override(Setting.PROTON_FOLDER_NAME, "..backups/ha")
    assert src.folderSegments() == ["..backups", "ha"]


async def test_create_folder_never_receives_leading_dash(tmp_path):
    src, cli = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "-flagish/-nested")
    await src.get()
    create_calls = [c for c in cli.calls if c[0] == "createFolder"]
    assert len(create_calls) == 2, "expected both folders to be created"
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


async def test_ensure_folder_reuses_concurrently_created(tmp_path):
    # If create fails but the folder turns out to exist (concurrent writer),
    # reuse it instead of failing the sync.
    src, cli = make_source(tmp_path)
    real_create = cli.createFolder

    async def race_create(parent, name):
        await real_create(parent, name)
        raise ProtonError("A file or folder with that name already exists", 1)
    cli.createFolder = race_create

    await src.get()  # must not raise
    assert "/my-files/HA Backups" in cli.folders


async def test_ensure_folder_propagates_real_create_errors(tmp_path):
    src, cli = make_source(tmp_path)

    async def failing_create(parent, name):
        raise ProtonError("quota exceeded", 1)
    cli.createFolder = failing_create

    with pytest.raises(ProtonError):
        await src.get()


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


async def test_delete_completes_when_metadata_trash_is_killed(tmp_path):
    # A signal-killed CLI raises even from the best-effort metadata trash;
    # delete() must still drop the local source and purge the tar it already
    # trashed (the metadata sidecar is retried by get()'s orphan sweep later).
    from backup.proton.exceptions import ProtonError
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    real_trash = cli.trash

    async def killed_on_metadata(path, strict=False):
        if path.endswith(METADATA_SUFFIX):
            raise ProtonError("proton-drive was killed by signal 4 (SIGILL)", -4)
        return await real_trash(path, strict)

    cli.trash = killed_on_metadata
    folder = "/my-files/HA Backups"
    await src.delete(backup)
    assert backup.getSource(SOURCE_PROTON_DRIVE) is None
    assert folder + "/abc123" + TAR_SUFFIX not in cli.files
    delete_paths = [c[1] for c in cli.calls if c[0] == "delete"]
    assert "/trash/abc123" + TAR_SUFFIX in delete_paths


async def test_delete_purges_trash_by_default(tmp_path):
    # Trashed items keep counting toward the Proton quota, so by default a
    # deleted backup is trashed and then purged from the trash (tar + sidecar).
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    await src.delete(backup)
    ops = [c[0] for c in cli.calls]
    assert "trash" in ops
    # Permanent delete only ever addresses the trash, never a live path.
    delete_paths = [c[1] for c in cli.calls if c[0] == "delete"]
    assert delete_paths == ["/trash/abc123" + TAR_SUFFIX,
                            "/trash/abc123" + METADATA_SUFFIX]
    assert cli.trashed == []


async def test_delete_leaves_backup_in_trash_when_disabled(tmp_path):
    # permanently_delete=False restores the old move-to-trash-only behavior.
    src, cli = make_source(tmp_path)
    src.config.override(Setting.PERMANENTLY_DELETE, False)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    await src.delete(backup)
    assert not any(c[0] == "delete" for c in cli.calls)
    assert sorted(t["name"] for t in cli.trashed) == \
        sorted(["abc123" + TAR_SUFFIX, "abc123" + METADATA_SUFFIX])


async def test_purge_skips_when_users_item_is_first_match(tmp_path):
    # `delete /trash/<name>` acts on the FIRST trashed node with that name.
    # When the user already had a same-named item in the trash (so it's the
    # first match), the purge must leave both alone rather than delete the
    # user's item.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    cli.seed_trash("abc123" + TAR_SUFFIX, data=b"the user's own file")
    await src.delete(backup)
    delete_paths = [c[1] for c in cli.calls if c[0] == "delete"]
    # The unblocked sidecar is still purged; the shadowed tar is not.
    assert "/trash/abc123" + TAR_SUFFIX not in delete_paths
    assert "/trash/abc123" + METADATA_SUFFIX in delete_paths
    assert [t["name"] for t in cli.trashed] == \
        ["abc123" + TAR_SUFFIX, "abc123" + TAR_SUFFIX]


async def test_purge_deletes_own_item_when_name_resolves_to_it(tmp_path):
    # A same-named item the user trashes LATER doesn't block the purge: the
    # CLI resolves trash names first-match, so the just-trashed backup file
    # (earlier in the trash) is the one `delete` acts on, confirmed by the
    # info probe.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    src.config.override(Setting.PERMANENTLY_DELETE, False)
    await src.delete(backup)                     # ours land in the trash first
    cli.seed_trash("abc123" + TAR_SUFFIX, data=b"the user's own file")
    our_uid = cli.trashed[0]["uid"]
    await src._purgeFromTrash([("abc123" + TAR_SUFFIX, [{"uid": our_uid, "ok": True}])])
    # Ours is gone; the user's later same-named item is untouched.
    remaining = [t for t in cli.trashed if t["name"] == "abc123" + TAR_SUFFIX]
    assert [t["data"] for t in remaining] == [b"the user's own file"]


async def test_purge_failure_does_not_fail_delete(tmp_path):
    # The removal already succeeded once the trash call went through; a broken
    # purge (e.g. the trash probe fails) must not fail delete() or drop state.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))

    orig_info = cli.info

    async def failing_trash_info(path):
        if path.startswith("/trash/"):
            raise ProtonError("trash probe broke", 1)
        return await orig_info(path)

    cli.info = failing_trash_info
    await src.delete(backup)  # must not raise
    assert backup.getSource(SOURCE_PROTON_DRIVE) is None
    assert sorted(t["name"] for t in cli.trashed) == \
        sorted(["abc123" + TAR_SUFFIX, "abc123" + METADATA_SUFFIX])


async def test_purge_skips_on_uid_mismatch(tmp_path):
    # If the node the trash probe resolves is NOT the one we just trashed
    # (uid differs), the purge must not gamble that `delete` would pick ours.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))

    orig_info = cli.info

    async def foreign_trash_info(path):
        if not path.startswith("/trash/"):
            return await orig_info(path)
        return {"name": {"ok": True, "value": path[len("/trash/"):]},
                "uid": "uid-someone-elses", "type": "file"}

    cli.info = foreign_trash_info
    await src.delete(backup)
    assert not any(c[0] == "delete" for c in cli.calls)


async def test_purge_skips_unconfirmed_file_type(tmp_path):
    # Never permanently delete anything not confirmed to be a plain file: if
    # the name-resolved trash took a folder (or the probe stops reporting
    # types), the item must stay recoverable in the trash.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))

    orig_info = cli.info

    async def typeless_trash_info(path):
        entry = await orig_info(path)
        if path.startswith("/trash/"):
            entry.pop("type", None)
        return entry

    cli.info = typeless_trash_info
    await src.delete(backup)
    assert not any(c[0] == "delete" for c in cli.calls)
    assert len(cli.trashed) == 2


async def test_orphan_sweep_never_purges_trash(tmp_path):
    # The purge applies ONLY to delete()'s own validated backup files.  The
    # orphan sweeps act on heuristically matched files the addon may not have
    # created (e.g. a user's tar without a sidecar), so even with
    # permanently_delete on they must stay move-to-trash-only.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.files[folder + "/ghost" + METADATA_SUFFIX] = meta_bytes(slug="ghost")
    cli.files[folder + "/personal.tar"] = b"the user's own archive"
    await src.get()
    assert any(c[0] == "trash" for c in cli.calls)
    assert not any(c[0] == "delete" for c in cli.calls)
    assert sorted(t["name"] for t in cli.trashed) == \
        sorted(["ghost" + METADATA_SUFFIX, "personal.tar"])


async def test_failed_trash_never_purges_users_same_named_item(tmp_path):
    # The sidecar's trash is best-effort; when it fails (already gone), a
    # same-named item the USER trashed must not be purged in its place.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    del cli.files["/my-files/HA Backups/abc123" + METADATA_SUFFIX]
    cli.seed_trash("abc123" + METADATA_SUFFIX, data=b"the user's own file")
    await src.delete(backup)
    delete_paths = [c[1] for c in cli.calls if c[0] == "delete"]
    assert delete_paths == ["/trash/abc123" + TAR_SUFFIX]
    assert [t["name"] for t in cli.trashed] == ["abc123" + METADATA_SUFFIX]


async def test_metadata_rewrite_leaves_no_trash_and_delete_still_purges(tmp_path):
    # retain()/note() rewrite the sidecar as a new revision, updating the node
    # in place: with the CLI's "replace" strategy the OLD sidecar would land in
    # the trash (uid unreported), become the name's first match, and block the
    # purge on every later delete of that backup.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    await src.retain(backup, True)
    await src.note(backup, "keep this one")
    rewrite_conflicts = [c[3] for c in cli.calls if c[0] == "upload"
                         and c[1].endswith(METADATA_SUFFIX)][1:]
    assert rewrite_conflicts == ["create-new-revision", "create-new-revision"]
    assert cli.trashed == []          # the rewrites trashed nothing
    await src.delete(backup)
    assert cli.trashed == []          # and the purge still removed both files


async def test_purge_detects_wrong_item_deleted(tmp_path):
    # `delete` re-resolves the name first-match at delete time, so another
    # client's same-named item trashed between the probe and the delete can be
    # the one deleted.  That race can't be closed, but delete's per-node
    # results expose it — the purge must notice and not raise.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))

    orig_delete = cli.delete

    async def racing_delete(path, strict=False):
        await orig_delete(path, strict=strict)
        return [{"uid": "uid-someone-elses", "ok": True}]

    cli.delete = racing_delete
    await src.delete(backup)  # must not raise
    assert backup.getSource(SOURCE_PROTON_DRIVE) is None


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

    async def download(remote_path, local_folder, conflict="remove"):
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


# --- Nested folder support -------------------------------------------------


async def test_nested_folders_created_segment_by_segment(tmp_path):
    src, cli = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "backups/ha")
    await src.get()
    creates = [c for c in cli.calls if c[0] == "createFolder"]
    assert creates == [("createFolder", "/my-files", "backups"),
                       ("createFolder", "/my-files/backups", "ha")]
    assert "/my-files/backups/ha" in cli.folders


async def test_nested_folders_create_only_missing_tail(tmp_path):
    src, cli = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "backups/ha")
    cli.folders.add("/my-files/backups")
    await src.get()
    creates = [c for c in cli.calls if c[0] == "createFolder"]
    assert creates == [("createFolder", "/my-files/backups", "ha")]


async def test_nested_folders_fully_existing_create_nothing(tmp_path):
    src, cli = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "backups/ha")
    cli.folders.add("/my-files/backups")
    cli.folders.add("/my-files/backups/ha")
    await src.get()
    assert not any(c[0] == "createFolder" for c in cli.calls)


async def test_file_blocking_path_segment_touches_nothing(tmp_path):
    # A *file* named like a path segment must produce a clear error; the addon
    # must not create a duplicate folder next to it and must not trash anything.
    src, cli = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "backups/ha")
    cli.files["/my-files/backups"] = b"i am someone's file"
    with pytest.raises(ProtonError, match="exists in Proton Drive as a file"):
        await src.get()
    assert not any(c[0] in ("createFolder", "trash", "delete") for c in cli.calls)
    assert cli.files["/my-files/backups"] == b"i am someone's file"


async def test_nested_ensure_reuses_concurrently_created(tmp_path):
    # Race handling still works per segment: create fails but a re-list shows
    # a concurrent writer made the folder, so the walk continues.
    src, cli = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "backups/ha")
    real_create = cli.createFolder

    async def race_create(parent, name):
        await real_create(parent, name)
        raise ProtonError("A file or folder with that name already exists", 1)
    cli.createFolder = race_create

    await src.get()  # must not raise
    assert "/my-files/backups/ha" in cli.folders


async def test_subfolder_named_like_tar_is_never_swept(tmp_path):
    # A sub-folder whose name ends in ".tar" must not be classified as an
    # orphaned backup tar: trashing it would trash its entire contents.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.folders.add(folder + "/evil.tar")
    cli.folders.add(folder + "/notes.metadata.json")
    cli.files[folder + "/stray.tar"] = b"stray"  # a real orphan file: still swept
    result = await src.get()
    assert result == {}
    trashed = [c[1] for c in cli.calls if c[0] == "trash"]
    assert folder + "/stray.tar" in trashed
    assert folder + "/evil.tar" not in trashed
    assert folder + "/notes.metadata.json" not in trashed
    assert folder + "/evil.tar" in cli.folders


async def test_folder_change_takes_effect_without_restart(tmp_path):
    # Nothing subscribes to config changes, so the ensured-path latch must
    # invalidate itself when proton_folder_name changes at runtime.
    src, cli = make_source(tmp_path)
    await src.get()
    src.config.override(Setting.PROTON_FOLDER_NAME, "new/spot")
    backup = FakeBackup()
    await src.save(backup, FakeSource(b"payload"))
    assert "/my-files/new/spot" in cli.folders  # actually re-ensured, not just written blind
    assert cli.files["/my-files/new/spot/abc123" + TAR_SUFFIX] == b"payload"


async def test_save_get_delete_stay_inside_nested_folder(tmp_path):
    src, cli = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "backups/ha")
    folder = "/my-files/backups/ha"
    # A sibling file next to the leaf folder must never be touched.
    cli.folders.add("/my-files/backups")
    cli.files["/my-files/backups/unrelated.tar"] = b"not ours"

    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"payload")))
    assert cli.files[folder + "/abc123" + TAR_SUFFIX] == b"payload"
    assert "abc123" in await src.get()
    await src.delete(backup)
    assert folder + "/abc123" + TAR_SUFFIX not in cli.files

    trashed = [c[1] for c in cli.calls if c[0] == "trash"]
    assert all(p.startswith(folder + "/") for p in trashed)
    assert cli.files["/my-files/backups/unrelated.tar"] == b"not ours"


async def test_rewrite_metadata_follows_backups_own_folder(tmp_path):
    # retain/note on a backup uploaded under an old path must update the sidecar
    # NEXT TO ITS TAR, not in the newly-configured folder, or the pair would be
    # split across two folders.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    item = await src.save(backup, FakeSource(b"d"))
    backup.addSource(item)
    src.config.override(Setting.PROTON_FOLDER_NAME, "new/spot")
    await src.note(backup, "keep me")
    meta = json.loads(cli.files["/my-files/HA Backups/abc123" + METADATA_SUFFIX])
    assert meta["note"] == "keep me"
    assert "/my-files/new/spot/abc123" + METADATA_SUFFIX not in cli.files


async def test_meta_cache_does_not_leak_across_folders(tmp_path):
    # The metadata cache is keyed by full path: after a folder change, a
    # same-slug backup in the new folder must not be served the old folder's
    # sidecar (a stale retained flag could expose it to retention pruning).
    src, cli = make_source(tmp_path)
    cli.seed_backup("/my-files/HA Backups", "abc123", meta_bytes(name="from-old"))
    old = await src.get()
    assert old["abc123"].name() == "from-old"
    src.config.override(Setting.PROTON_FOLDER_NAME, "new/spot")
    cli.folders.add("/my-files/new")
    cli.seed_backup("/my-files/new/spot", "abc123", meta_bytes(name="from-new"))
    result = await src.get()
    assert result["abc123"].name() == "from-new"


async def test_orphans_with_unknown_type_are_left_alone(tmp_path):
    # If a listing entry doesn't say whether it's a file, sweeping it could
    # trash a folder and all its contents — the sweeps must fail closed.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.files[folder + "/mystery.tar"] = b"?"
    cli.files[folder + "/mystery" + METADATA_SUFFIX] = b"{}"
    cli.files[folder + "/lonely" + METADATA_SUFFIX] = b"{}"   # orphan sidecar
    cli.files[folder + "/lonesome.tar"] = b"?"                # orphan tar

    real_list = cli.listFolder

    async def typeless_list(path):
        return [{k: v for k, v in e.items() if k != "type"} for e in await real_list(path)]
    cli.listFolder = typeless_list

    await src.get()
    assert not any(c[0] == "trash" for c in cli.calls)


async def test_same_named_file_does_not_shadow_folder(tmp_path):
    # Proton allows duplicate names.  A file with the same name as the addon's
    # folder must not make folder resolution fail, whatever the listing order.
    src, cli = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "backups/ha")
    cli.folders.add("/my-files/backups")
    cli.folders.add("/my-files/backups/ha")

    real_list = cli.listFolder

    async def with_duplicate(path):
        entries = await real_list(path)
        if path == "/my-files":
            # Listed *after* the folder entry, so it would win a naive
            # last-write-wins name lookup.
            entries.append({"name": "backups", "type": "file", "size": 1})
        return entries
    cli.listFolder = with_duplicate

    assert "abc123" not in await src.get()  # resolves the folder; must not raise


async def test_sweep_skips_names_shared_with_a_folder(tmp_path):
    # Proton allows duplicate names, and `trash` resolves its path by name: if
    # a sub-folder shares an orphan file's name, trashing that name could
    # resolve to the folder.  Such names are never swept.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.files[folder + "/dup.tar"] = b"orphan file"
    cli.files[folder + "/dup2" + METADATA_SUFFIX] = b"{}"

    real_list = cli.listFolder

    async def with_dup_folders(path):
        entries = await real_list(path)
        if path == folder:
            entries.append({"name": "dup.tar", "type": "folder"})
            entries.append({"name": "dup2" + METADATA_SUFFIX, "type": "folder"})
        return entries
    cli.listFolder = with_dup_folders

    await src.get()
    assert not any(c[0] == "trash" for c in cli.calls)


async def test_delete_refuses_when_folder_shares_backup_name(tmp_path):
    # Same ambiguity for intentional deletes: if a folder shares the tar's
    # name, refuse rather than let the CLI pick which one to trash.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    folder = "/my-files/HA Backups"

    real_list = cli.listFolder

    async def with_dup_folder(path):
        entries = await real_list(path)
        if path == folder:
            entries.append({"name": "abc123" + TAR_SUFFIX, "type": "folder"})
        return entries
    cli.listFolder = with_dup_folder

    with pytest.raises(ProtonError, match="folder named"):
        await src.delete(backup)
    assert not any(c[0] == "trash" for c in cli.calls)
    assert backup.getSource(SOURCE_PROTON_DRIVE) is not None


async def test_failed_save_cleanup_skips_name_shared_with_folder(tmp_path):
    # The rollback after a failed upload must not trash a same-named folder:
    # `trash` resolves by name, so the name must be confirmed a plain file.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    real_upload = cli.upload

    async def failing_meta_upload(local_path, parent_path, conflict="replace"):
        if local_path.endswith(METADATA_SUFFIX):
            raise RuntimeError("metadata upload failed")
        return await real_upload(local_path, parent_path, conflict)
    cli.upload = failing_meta_upload

    real_list = cli.listFolder

    async def with_dup_folder(path):
        entries = await real_list(path)
        if path == folder:
            entries.append({"name": "abc123" + TAR_SUFFIX, "type": "folder"})
        return entries
    cli.listFolder = with_dup_folder

    with pytest.raises(UploadFailed):
        await src.save(FakeBackup(), FakeSource(b"d"))
    assert not any(c[0] == "trash" for c in cli.calls)


async def test_sweep_rechecks_listing_before_trashing(tmp_path):
    # Between get()'s initial listing and the sweep, a name can gain a
    # folder-typed duplicate (sidecar downloads make that window long); the
    # sweep must consult a fresh listing before trashing.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.files[folder + "/stray.tar"] = b"orphan"

    real_list = cli.listFolder
    leaf_listings = []

    async def racy_list(path):
        entries = await real_list(path)
        if path == folder:
            leaf_listings.append(path)
            if len(leaf_listings) >= 2:  # only the fresh pre-sweep listing sees it
                entries.append({"name": "stray.tar", "type": "folder"})
        return entries
    cli.listFolder = racy_list

    await src.get()
    assert len(leaf_listings) >= 2
    assert not any(c[0] == "trash" for c in cli.calls)


async def test_sweep_spares_tar_that_gained_its_sidecar(tmp_path):
    # A concurrent save() can complete between get()'s first listing and the
    # sweep; its tar is then paired in the fresh listing and must not be
    # trashed as an "orphan" (with delete_after_upload that would destroy the
    # only copy of the backup).
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.files[folder + "/racy.tar"] = b"tar"

    real_list = cli.listFolder
    leaf_listings = []

    async def racy_list(path):
        entries = await real_list(path)
        if path == folder:
            leaf_listings.append(path)
            if len(leaf_listings) >= 2:  # the sidecar landed before the re-list
                entries.append({"name": "racy" + METADATA_SUFFIX, "type": "file"})
        return entries
    cli.listFolder = racy_list

    await src.get()
    assert len(leaf_listings) >= 2
    assert not any(c[0] == "trash" for c in cli.calls)
    assert folder + "/racy.tar" in cli.files


async def test_sweep_skips_tars_when_upload_was_in_flight_at_listing(tmp_path):
    # A save() can finish — flipping _uploading off — right after get()'s
    # listing, with its sidecar landing after the pre-sweep re-list snapshot
    # too.  If an upload was in flight when the folder was listed, tar sweeping
    # is skipped for the whole sync; the next sync sees the truth.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.files[folder + "/racy.tar"] = b"tar"
    src._uploading = True

    real_list = cli.listFolder

    async def racy_list(path):
        entries = await real_list(path)
        if path == folder:
            src._uploading = False  # the save finished right after this listing
        return entries
    cli.listFolder = racy_list

    await src.get()
    assert not any(c[0] == "trash" for c in cli.calls)
    assert folder + "/racy.tar" in cli.files


async def test_sweep_skips_tars_when_upload_started_mid_get(tmp_path):
    # A save() can start after get()'s flag latch was read and finish entirely
    # within get() — the upload-start counter catches what the flag can't.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.files[folder + "/racy.tar"] = b"tar"

    real_list = cli.listFolder

    async def racy_list(path):
        entries = await real_list(path)
        if path == folder:
            src._upload_starts += 1  # a save started (and may have finished)
        return entries
    cli.listFolder = racy_list

    await src.get()
    assert not any(c[0] == "trash" for c in cli.calls)
    assert folder + "/racy.tar" in cli.files


async def test_sweep_skips_orphan_tars_while_uploading(tmp_path):
    # While an upload is in flight, an unpaired tar may simply be one whose
    # sidecar hasn't been written yet.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.files[folder + "/pending.tar"] = b"mid-upload"
    src._uploading = True
    await src.get()
    assert not any(c[0] == "trash" for c in cli.calls)
    src._uploading = False
    await src.get()  # no upload anymore: now it really is an orphan
    assert folder + "/pending.tar" not in cli.files


async def test_subfolder_tar_never_becomes_a_backup(tmp_path):
    # A folder-typed "x.tar" with a *file* sidecar next to it must not be
    # parsed into a backup (it would show in the UI with a bogus size and fail
    # read/delete), and neither of the pair may be trashed.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.folders.add(folder + "/abc123" + TAR_SUFFIX)
    cli.files[folder + "/abc123" + METADATA_SUFFIX] = meta_bytes()
    result = await src.get()
    assert result == {}
    assert cli.download_count == 0
    assert not any(c[0] == "trash" for c in cli.calls)
    assert folder + "/abc123" + METADATA_SUFFIX in cli.files


async def test_delete_refuses_when_unknown_typed_entry_shares_name(tmp_path):
    # A duplicate whose listing entry carries no type at all must also make
    # delete() refuse (fail closed), not just a folder-typed one.
    src, cli = make_source(tmp_path)
    backup = FakeBackup()
    backup.addSource(await src.save(backup, FakeSource(b"d")))
    folder = "/my-files/HA Backups"

    real_list = cli.listFolder

    async def with_typeless_dup(path):
        entries = await real_list(path)
        if path == folder:
            entries.append({"name": "abc123" + TAR_SUFFIX})  # no type key
        return entries
    cli.listFolder = with_typeless_dup

    with pytest.raises(ProtonError, match="can't be confirmed"):
        await src.delete(backup)
    assert not any(c[0] == "trash" for c in cli.calls)
    assert backup.getSource(SOURCE_PROTON_DRIVE) is not None


async def test_trash_in_folder_refuses_path_like_names(tmp_path):
    # The last line of defense on every removal: a separator in the name could
    # reach outside the backup folder, so it must never hit the CLI.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    await src._trashInFolder(folder, "a\\b.tar")   # best-effort: warn and skip
    await src._trashInFolder(folder, "a/b.tar")
    with pytest.raises(ProtonError):
        await src._trashInFolder(folder, "a\\b.tar", strict=True)
    assert not any(c[0] == "trash" for c in cli.calls)


async def test_backslash_named_entries_are_never_touched(tmp_path):
    # os.path.basename() doesn't strip "\" on Linux, so a remote name like
    # "evil\..\x.tar" (creatable via the web UI) could smuggle a separator into
    # a trash path.  Such entries are ignored entirely.
    src, cli = make_source(tmp_path)
    folder = "/my-files/HA Backups"
    cli.folders.add(folder)
    cli.files[folder + "/evil\\..\\x.tar"] = b"foreign"
    result = await src.get()
    assert result == {}
    assert not any(c[0] == "trash" for c in cli.calls)
    assert cli.files[folder + "/evil\\..\\x.tar"] == b"foreign"


async def test_get_self_heals_when_nested_folder_vanishes(tmp_path):
    src, cli = make_source(tmp_path)
    src.config.override(Setting.PROTON_FOLDER_NAME, "backups/ha")
    await src.get()  # creates + latches the chain
    cli.folders.discard("/my-files/backups/ha")
    cli.folders.discard("/my-files/backups")  # a middle segment vanished too
    result = await src.get()
    assert result == {}
    assert "/my-files/backups/ha" in cli.folders
