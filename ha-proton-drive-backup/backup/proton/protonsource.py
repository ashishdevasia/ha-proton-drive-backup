import asyncio
import json
import os
import shutil
import tempfile
import time
from datetime import datetime
from typing import Dict, Optional

from injector import inject, singleton

from ..config import Config, Setting, CreateOptions, Startable
from ..const import (SOURCE_PROTON_DRIVE, NECESSARY_PROP_KEY_SLUG,
                     NECESSARY_PROP_KEY_DATE, NECESSARY_PROP_KEY_NAME, PROP_NOTE)
from ..exceptions import LogicError, UploadFailed, LowSpaceError, KnownError
from ..model import BackupDestination, Backup
from ..model.protonbackup import (ProtonBackup, PROP_TYPE, PROP_VERSION,
                                  PROP_PROTECTED, PROP_RETAINED,
                                  TAR_SUFFIX, METADATA_SUFFIX)
from ..util import GlobalInfo
from ..time import Time
from ..logger import getLogger
from .protoncli import ProtonCli, PROTON_ROOT
from .exceptions import ProtonNotAuthenticated, ProtonTimeout, ProtonError
from .localstream import LocalFileStream

logger = getLogger(__name__)

# Extra free space required on the staging volume on top of the archive size,
# to cover the metadata sidecar and filesystem overhead.
STAGING_HEADROOM_BYTES = 64 * 1024 * 1024


@singleton
class ProtonSource(BackupDestination, Startable):
    """
    Stores Home Assistant backups in Proton Drive by driving the `proton-drive`
    CLI.  This is the Proton-Drive analogue of the original Google DriveSource;
    everything else in the addon (scheduling, retention, the HA side) is reused
    unchanged.
    """

    @inject
    def __init__(self, config: Config, time: Time, cli: ProtonCli, info: GlobalInfo):
        super().__init__()
        self.config = config
        self.time = time
        self.cli = cli
        self._info = info
        self._uploading = False
        self._account = None
        self._meta_cache: Dict[str, Dict] = {}
        self._folder_ensured = False
        self._folder_lock = asyncio.Lock()

    async def start(self):
        # Establish whether we already have a usable Proton session so the very
        # first sync knows if the destination is configured.
        try:
            await self.cli.checkAuth()
        except Exception as e:
            logger.warning("Couldn't check Proton Drive authentication on startup: " + str(e))

    async def preSync(self):
        # While flagged as signed out, the sync loop never consults this
        # destination, so this re-probe is the only path back to enabled.
        if not self.cli.isAuthenticated():
            await self.cli.checkAuth()

    def name(self) -> str:
        return SOURCE_PROTON_DRIVE

    def title(self) -> str:
        return "Proton Drive"

    def icon(self) -> str:
        return "folder-lock"

    def maxCount(self) -> int:
        return self.config.get(Setting.MAX_BACKUPS_IN_PROTON_DRIVE)

    def upload(self) -> bool:
        return self.config.get(Setting.ENABLE_PROTON_UPLOAD)

    def enabled(self) -> bool:
        return self.cli.isAuthenticated()

    def needsConfiguration(self) -> bool:
        if not self.config.get(Setting.ENABLE_PROTON_UPLOAD):
            return False
        return super().needsConfiguration()

    def isWorking(self):
        return self._uploading

    def detail(self):
        return self._account or super().detail()

    def freeSpace(self):
        # The CLI doesn't expose quota in a stable, machine-readable way yet.
        return super().freeSpace()

    async def create(self, options: CreateOptions) -> ProtonBackup:
        raise LogicError("Backups can't be created in Proton Drive")

    def checkBeforeChanges(self):
        pass

    # --- Folder management -----------------------------------------------------

    def folderName(self) -> str:
        name = (self.config.get(Setting.PROTON_FOLDER_NAME) or "").strip()
        # A "/" in the name would make the CLI treat it as nested paths and would
        # never match the single-segment listing in _ensureFolder, so collapse
        # path separators to keep this a single folder under the root.
        name = name.replace("/", "-").replace("\\", "-")
        # A leading "-" would be parsed by the CLI as a flag, since the folder
        # name is handed to `create-folder` as a positional argv token (the CLI
        # is invoked via exec, not a shell, so this is the only injection vector).
        # Strip leading dashes/whitespace so the name can't become an option.
        name = name.lstrip("-").strip()
        # Once "/" and "\" are collapsed, the only remaining traversal tokens are
        # a name made entirely of dots ("." / ".." / ...), which would make
        # folderPath() resolve to the drive root or its parent.  Reject those.
        if name and set(name) == {"."}:
            name = ""
        return name or "Home Assistant Backups"

    def folderPath(self) -> str:
        return PROTON_ROOT + "/" + self.folderName()

    async def _ensureFolder(self):
        if self._folder_ensured:
            return
        # Serialize so two concurrent callers can't both create the folder
        # (Proton allows duplicate names, which would split backups across two
        # folders and break retention counting).  Double-checked inside the lock.
        async with self._folder_lock:
            if self._folder_ensured:
                return
            # List the root and reuse an existing folder by name.  We deliberately
            # do NOT create on a generic error (transient/auth/timeout all
            # propagate), because a blind create on a transient failure would
            # split backups across two folders.
            entries = await self.cli.listFolder(PROTON_ROOT)
            names = {_entry_name(e) for e in entries}
            if self.folderName() not in names:
                logger.info("Creating Proton Drive backup folder '{}'".format(self.folderName()))
                try:
                    await self.cli.createFolder(PROTON_ROOT, self.folderName())
                except ProtonError:
                    # Verify by re-listing instead of parsing the error text:
                    # a concurrent writer may have created it since we listed.
                    entries = await self.cli.listFolder(PROTON_ROOT)
                    if self.folderName() not in {_entry_name(e) for e in entries}:
                        raise
                    logger.info("Folder '{}' already exists, reusing it".format(self.folderName()))
            self._folder_ensured = True

    # --- Reading the current state ---------------------------------------------

    async def get(self) -> Dict[str, ProtonBackup]:
        logger.info("Proton get(): checking authentication")
        await self.cli.checkAuth()
        logger.info("Proton get(): ensuring backup folder exists")
        await self._ensureFolder()
        folder = self.folderPath()
        logger.info("Proton get(): listing '%s'", folder)
        try:
            entries = await self.cli.listFolder(folder)
        except (ProtonNotAuthenticated, ProtonTimeout):
            raise
        except ProtonError:
            # The folder may have been removed out from under us since we last
            # confirmed it.  Re-resolve (recreating it if needed) and retry once
            # rather than failing the whole sync.
            self._folder_ensured = False
            await self._ensureFolder()
            entries = await self.cli.listFolder(folder)

        tars = {}
        meta_files = set()
        for entry in entries:
            entry_name = _entry_name(entry)
            if entry_name is None:
                continue
            if entry_name.endswith(METADATA_SUFFIX):
                meta_files.add(entry_name)
            elif entry_name.endswith(TAR_SUFFIX):
                tars[entry_name] = entry

        logger.info("Proton get(): folder has %d entries (%d tar, %d metadata)",
                    len(entries), len(tars), len(meta_files))

        backups: Dict[str, ProtonBackup] = {}
        orphan_tars = []
        for tar_name, entry in tars.items():
            slug = tar_name[:-len(TAR_SUFFIX)]
            meta_name = slug + METADATA_SUFFIX
            if meta_name not in meta_files:
                logger.warning("Proton backup '{}' has no metadata sidecar; skipping".format(tar_name))
                orphan_tars.append(tar_name)
                continue
            logger.info("Proton get(): loading metadata for '%s'", tar_name)
            meta = await self._loadMetadata(folder, meta_name, slug)
            if meta is None:
                continue
            try:
                backup = ProtonBackup(meta, tar_name, _entry_size(entry), folder)
            except Exception as e:
                logger.warning("Couldn't parse Proton backup '{}': {}".format(tar_name, e))
                continue
            backups[backup.slug()] = backup

        # Drop cache entries for backups that no longer exist.
        live = {slug + METADATA_SUFFIX for slug in (b.slug() for b in backups.values())}
        for cached in list(self._meta_cache.keys()):
            if cached not in live:
                self._meta_cache.pop(cached, None)

        # Best-effort: trash metadata sidecars whose tar is gone (e.g. a metadata
        # trash failed during a previous delete).  Otherwise they'd leak quota
        # forever, since get() would never iterate them again to retry.
        tar_slugs = {name[:-len(TAR_SUFFIX)] for name in tars}
        for meta_name in meta_files:
            if meta_name[:-len(METADATA_SUFFIX)] not in tar_slugs:
                try:
                    await self.cli.trash(folder + "/" + meta_name)
                    self._meta_cache.pop(meta_name, None)
                except Exception as e:
                    logger.debug("Couldn't clean up orphaned metadata '{}': {}".format(meta_name, e))

        # Best-effort: trash tars with no metadata sidecar.  These are left behind
        # when save() is interrupted (process killed) after the tar upload but
        # before the metadata upload — they're invisible to retention (never
        # parsed into a ProtonBackup) so nothing else would ever reap them, and
        # they'd leak quota forever.  Skip while an upload is in flight, since
        # that tar may simply be one whose sidecar hasn't been written yet.
        if orphan_tars and not self._uploading:
            for tar_name in orphan_tars:
                try:
                    await self.cli.trash(folder + "/" + tar_name)
                    logger.info("Removed orphaned Proton tar '{}' (no metadata sidecar)".format(tar_name))
                except Exception as e:
                    logger.debug("Couldn't clean up orphaned tar '{}': {}".format(tar_name, e))
        logger.info("Proton get(): done, %d backup(s) present in Proton Drive", len(backups))
        return backups

    async def _loadMetadata(self, folder: str, meta_name: str, slug: str) -> Optional[Dict]:
        if meta_name in self._meta_cache:
            return self._meta_cache[meta_name]
        tmpdir = tempfile.mkdtemp(dir=self._tempDir())
        try:
            await self.cli.download(folder + "/" + meta_name, tmpdir)
            local = os.path.join(tmpdir, meta_name)
            if not os.path.exists(local):
                # Same defensive fallback as read(): if the CLI wrote the file
                # under a different (decrypted) node name, use the lone file.
                files = [f for f in os.listdir(tmpdir) if os.path.isfile(os.path.join(tmpdir, f))]
                if len(files) == 1:
                    local = os.path.join(tmpdir, files[0])
            with open(local, "r", encoding="utf-8") as f:
                meta = json.load(f)
            self._meta_cache[meta_name] = meta
            return meta
        except ProtonNotAuthenticated:
            raise
        except Exception as e:
            logger.warning("Couldn't read metadata for Proton backup '{}': {}".format(slug, e))
            return None
        finally:
            _rmtree(tmpdir)

    # --- Mutations -------------------------------------------------------------

    async def delete(self, backup: Backup):
        item = self._validate(backup)
        logger.info("Deleting '{}' from Proton Drive".format(item.name()))
        # Trash (not permanent-delete): the CLI's `delete` only works on items
        # already in the trash, whereas `trash` moves a live item out of the
        # backup folder so it stops appearing in listings and retention
        # converges.  Trash the tar strictly: if it fails we must NOT drop the
        # local source, else the backup reappears next sync.  Metadata is
        # best-effort.
        await self.cli.trash(item.tarPath(), strict=True)
        await self.cli.trash(item.metadataPath())
        self._meta_cache.pop(item.metadataName(), None)
        backup.removeSource(self.name())

    async def save(self, backup: Backup, source) -> ProtonBackup:
        await self.cli.checkAuth()
        await self._ensureFolder()
        folder = self.folderPath()
        slug = backup.slug()
        retain = bool(backup.getOptions() and backup.getOptions().retain_sources.get(self.name(), False))

        meta = self._buildMetadata(backup, retain)

        tmpdir = tempfile.mkdtemp(dir=self._tempDir())
        tar_local = os.path.join(tmpdir, slug + TAR_SUFFIX)
        meta_local = os.path.join(tmpdir, slug + METADATA_SUFFIX)
        self._uploading = True
        tar_uploaded = False
        succeeded = False
        try:
            # Stage the backup to a local file (the CLI can't stream).
            async with source:
                size = source.size()
                self._info.upload(size)
                backup.overrideStatus("Downloading {0}%", source)
                backup.setUploadSource(self.title(), source)

                # The CLI can't stream, so the whole archive is staged to disk
                # under proton_data_path before it's uploaded.  Fail fast with a
                # clear error if there isn't room, rather than filling /data
                # mid-write (which can wedge Home Assistant itself).
                self._checkStagingSpace(size)

                logger.info("Proton save(): staging '%s' (%s bytes) from Home Assistant to %s",
                            backup.name(), size, tar_local)
                stage_start = time.monotonic()
                written = 0
                with open(tar_local, "wb") as out:
                    async for chunk in source:
                        out.write(chunk)
                        written += len(chunk)
                logger.info("Proton save(): staged %s bytes in %.1fs; uploading tar to Proton Drive",
                            written, time.monotonic() - stage_start)

            backup.overrideStatus("Uploading to Proton Drive")
            await self.cli.upload(tar_local, folder)
            tar_uploaded = True

            logger.info("Proton save(): tar uploaded; uploading metadata sidecar")
            with open(meta_local, "w", encoding="utf-8") as f:
                json.dump(meta, f)
            await self.cli.upload(meta_local, folder)

            self._meta_cache[slug + METADATA_SUFFIX] = meta
            uploaded_size = os.path.getsize(tar_local)
            logger.info("Finished uploading '{}' to Proton Drive".format(backup.name()))
            succeeded = True
            return ProtonBackup(meta, slug + TAR_SUFFIX, uploaded_size, folder)
        except KnownError:
            # Let typed errors (not-authenticated, timeout, the pre-flight
            # LowSpaceError, a surfaced CLI ProtonError) propagate with their own
            # message/code instead of being flattened into a generic
            # "upload failed", which hides actionable detail like "low on disk
            # space".  Only genuinely unexpected errors become UploadFailed.
            raise
        except Exception as e:
            logger.printException(e)
            raise UploadFailed()
        finally:
            self._uploading = False
            backup.clearUploadSource()
            backup.clearStatus()
            # If we didn't finish (error, auth failure, or cancellation), make
            # sure a tar that made it up without its metadata sidecar doesn't
            # linger as an orphan.  Cleaning up here (not in the except blocks)
            # also covers asyncio.CancelledError, which bypasses `except Exception`.
            if not succeeded:
                await self._cleanupOrphanTar(tar_uploaded, folder, slug)
            _rmtree(tmpdir)

    async def _cleanupOrphanTar(self, tar_uploaded: bool, folder: str, slug: str):
        # If the tar made it up but the metadata sidecar didn't, remove the tar
        # so we don't leave an unusable orphan consuming quota.
        if not tar_uploaded:
            return
        try:
            await self.cli.trash(folder + "/" + slug + TAR_SUFFIX)
        except Exception as e:
            logger.warning("Couldn't clean up orphaned Proton tar for '{}': {}".format(slug, e))

    async def read(self, backup: Backup) -> LocalFileStream:
        item = self._validate(backup)
        tmpdir = tempfile.mkdtemp(dir=self._tempDir())
        logger.info("Proton read(): downloading '%s' from Proton Drive", item.tarPath())
        try:
            await self.cli.download(item.tarPath(), tmpdir)
        except Exception:
            _rmtree(tmpdir)
            raise
        logger.info("Proton read(): download complete for '%s'", item.name())
        local = os.path.join(tmpdir, item.remoteName())
        if not os.path.exists(local):
            # Fall back to whatever single file landed in the temp dir.
            files = [f for f in os.listdir(tmpdir) if os.path.isfile(os.path.join(tmpdir, f))]
            if len(files) == 1:
                local = os.path.join(tmpdir, files[0])
            else:
                _rmtree(tmpdir)
                raise LogicError("Proton download didn't produce the expected file for " + item.name())
        # LocalFileStream removes the file on close; remove the temp dir afterwards too.
        return _SelfCleaningStream(local, self.time, tmpdir)

    async def retain(self, backup: Backup, retain: bool) -> None:
        item = self._validate(backup)
        if item.retained() == retain:
            return
        meta = dict(item.metadata())
        meta[PROP_RETAINED] = str(retain)
        await self._rewriteMetadata(item, meta)
        item.setRetained(retain)

    async def note(self, backup, note: str) -> None:
        item = self._validate(backup)
        meta = dict(item.metadata())
        meta[PROP_NOTE] = note
        await self._rewriteMetadata(item, meta)
        item.setNote(note)

    async def _rewriteMetadata(self, item: ProtonBackup, meta: Dict):
        folder = self.folderPath()
        tmpdir = tempfile.mkdtemp(dir=self._tempDir())
        meta_local = os.path.join(tmpdir, item.metadataName())
        try:
            with open(meta_local, "w", encoding="utf-8") as f:
                json.dump(meta, f)
            await self.cli.upload(meta_local, folder)
            self._meta_cache[item.metadataName()] = meta
            item._meta = meta
        finally:
            _rmtree(tmpdir)

    # --- Helpers ---------------------------------------------------------------

    def _buildMetadata(self, backup: Backup, retain: bool) -> Dict:
        meta = {
            NECESSARY_PROP_KEY_SLUG: backup.slug(),
            NECESSARY_PROP_KEY_DATE: str(backup.date()),
            NECESSARY_PROP_KEY_NAME: str(backup.name()),
            PROP_TYPE: str(backup.backupType()),
            PROP_VERSION: str(backup.version()),
            PROP_PROTECTED: str(backup.protected()),
            PROP_RETAINED: str(retain),
        }
        if backup.note() is not None:
            meta[PROP_NOTE] = backup.note()
        return meta

    def _validate(self, backup: Backup) -> ProtonBackup:
        item = backup.getSource(self.name())
        if not item:
            raise LogicError(
                "Requested an operation on a Proton Drive backup that has no Proton Drive source")
        return item

    def _tempDir(self) -> str:
        base = self.config.get(Setting.PROTON_DATA_PATH)
        path = os.path.join(base, "tmp")
        os.makedirs(path, exist_ok=True)
        return path

    def _checkStagingSpace(self, size: int) -> None:
        # Refuse to stage if the temp volume can't hold the archive (plus a small
        # headroom for the metadata sidecar and filesystem overhead).  size <= 0
        # means the source couldn't report a size, so we can't check; let it run.
        if not size or size <= 0:
            return
        try:
            free = shutil.disk_usage(self._tempDir()).free
        except OSError as e:
            logger.warning("Couldn't check free space before staging a Proton upload: " + str(e))
            return
        needed = size + STAGING_HEADROOM_BYTES
        if free < needed:
            logger.error("Not enough space under %s to stage a %d byte backup (%d bytes free)",
                         self._tempDir(), size, free)
            raise LowSpaceError(space_remaining=free)

    def _timeToRfc3339String(self, time: datetime) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ")


class _SelfCleaningStream(LocalFileStream):
    """LocalFileStream that also removes the temp directory it was staged in."""

    def __init__(self, path, time, tmpdir):
        super().__init__(path, time, cleanup=True)
        self._tmpdir = tmpdir

    async def _close(self):
        await super()._close()
        _rmtree(self._tmpdir)


def _entry_name(entry: Dict) -> Optional[str]:
    # The Proton CLI returns the (end-to-end encrypted) name wrapped in a result
    # object: {"name": {"ok": true, "value": "file.tar"}}.  Unwrap it; fall back
    # to a plain string for forward/backward compatibility.
    name = entry.get("name")
    if isinstance(name, dict):
        value = name.get("value")
        if isinstance(value, str) and value:
            return os.path.basename(value)
        return None
    if isinstance(name, str) and name:
        return os.path.basename(name)
    for key in ("filename", "fileName", "path"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            return os.path.basename(value)
    return None


def _entry_size(entry: Dict) -> int:
    # The true (decrypted) content size is activeRevision.value.claimedSize;
    # totalStorageSize/storageSize are the larger encrypted-on-disk sizes.
    revision = entry.get("activeRevision")
    if isinstance(revision, dict):
        value = revision.get("value")
        if isinstance(value, dict):
            for key in ("claimedSize", "storageSize", "size"):
                v = value.get(key)
                if isinstance(v, (int, float)):
                    return int(v)
    for key in ("size", "fileSize", "sizeBytes", "bytes", "totalSize",
                "totalStorageSize", "storageSize"):
        value = entry.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


def _rmtree(path: str):
    import shutil
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
