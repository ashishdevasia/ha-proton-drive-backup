import asyncio
import json
import os
import shutil
import tempfile
import time
from datetime import datetime
from typing import Dict, List, Optional

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
        # Counts save() starts.  get() compares it across its own run so the
        # orphan-tar sweep can tell an upload began mid-sync even if it also
        # finished (and cleared _uploading) before the sweep looked.
        self._upload_starts = 0
        self._warned_typeless_listing = False
        self._account = None
        self._meta_cache: Dict[str, Dict] = {}
        # The folder path that has been verified/created on Proton Drive.  Kept
        # as the resolved path (not a bool) so a runtime change of
        # PROTON_FOLDER_NAME automatically invalidates it.
        self._ensured_path: Optional[str] = None
        self._folder_lock = asyncio.Lock()

    async def start(self):
        # Make the changed "/" semantics visible to migrating users: before
        # nested-path support, separators were collapsed into dashes, so this
        # setting used to point at a different (single, dash-joined) folder.
        raw = self.config.get(Setting.PROTON_FOLDER_NAME) or ""
        if ("/" in raw or "\\" in raw) and len(self.folderSegments()) > 1:
            logger.warning("proton_folder_name contains a path separator; backups "
                           "will be stored in the nested folder '{}'.  Older addon "
                           "versions used a single dash-joined folder instead — "
                           "backups in that folder are left untouched but are no "
                           "longer visible to the addon.".format(self.folderName()))
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
            try:
                await self.cli.checkAuth()
            except Exception as e:
                # Never fail the sync (and HA-side backups) over the probe.
                logger.warning("Couldn't re-check Proton Drive authentication: " + str(e))

    async def signOut(self):
        try:
            await self.cli.logout()
        except ProtonNotAuthenticated:
            pass  # already signed out
        # Drop per-account state in case the next sign-in is a different account.
        self._ensured_path = None
        self._meta_cache.clear()
        self._account = None

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

    def folderSegments(self) -> List[str]:
        raw = self.config.get(Setting.PROTON_FOLDER_NAME) or ""
        segments = []
        # "/" (and "\") nest folders: "backups/ha" resolves to the "ha" folder
        # inside "backups" under the drive root.
        for segment in raw.replace("\\", "/").split("/"):
            # A leading "-" would be parsed by the CLI as a flag, since each
            # segment is handed to `create-folder` as a positional argv token
            # (the CLI is invoked via exec, not a shell, so this is the only
            # injection vector).  Strip to a fixpoint: removing dashes can
            # expose more whitespace and vice versa ("- -rf" must not survive
            # as "-rf").
            segment = segment.strip()
            while segment.startswith("-"):
                segment = segment.lstrip("-").strip()
            # A segment made entirely of dots ("." / ".." / ...) would make the
            # path escape toward (or past) the drive root; empty segments would
            # collapse ("a//b").  Drop both rather than erroring, keeping the
            # setting's sanitize-silently behavior.
            if not segment or set(segment) == {"."}:
                continue
            segments.append(segment)
        return segments or ["Home Assistant Backups"]

    def folderName(self) -> str:
        return "/".join(self.folderSegments())

    def folderPath(self) -> str:
        return PROTON_ROOT + "/" + self.folderName()

    async def _ensureFolder(self) -> str:
        # Returns the ensured path.  Callers must use the return value rather
        # than re-deriving it from config, which may have changed in between.
        target = self.folderPath()
        if self._ensured_path == target:
            return target
        # Serialize so two concurrent callers can't both create a folder
        # (Proton allows duplicate names, which would split backups across two
        # folders and break retention counting).  Double-checked inside the lock.
        async with self._folder_lock:
            # Re-read the config inside the lock so the walked segments and the
            # latched path always come from the same value, even if the setting
            # changed while we waited for the lock.
            segments = self.folderSegments()
            target = PROTON_ROOT + "/" + "/".join(segments)
            if self._ensured_path == target:
                return target
            current = PROTON_ROOT
            for segment in segments:
                current = await self._ensureChildFolder(current, segment)
            self._ensured_path = current
            return current

    async def _ensureChildFolder(self, parent: str, name: str) -> str:
        path = parent + "/" + name
        # List the parent and reuse an existing folder by name.  We deliberately
        # do NOT create on a generic list error (transient/auth/timeout all
        # propagate), because a blind create on a transient failure would
        # split backups across two folders.
        entry = (await self._folderEntries(parent)).get(name)
        if entry is None:
            logger.info("Creating Proton Drive backup folder '{}'".format(path))
            try:
                await self.cli.createFolder(parent, name)
                return path
            except ProtonError:
                # Verify by re-listing instead of parsing the error text:
                # a concurrent writer may have created it since we listed.
                entry = (await self._folderEntries(parent)).get(name)
                if entry is None:
                    raise
                logger.info("Folder '{}' already exists, reusing it".format(path))
        if _entry_is_folder(entry) is False:
            # Never touch the conflicting file, and never create a duplicate
            # folder next to it (Proton allows duplicate names, which would be
            # ambiguous forever after).
            raise ProtonError(
                "'{}' already exists in Proton Drive as a file, so it can't be "
                "used as part of the backup folder path.  Choose a different "
                "proton_folder_name.".format(path))
        return path

    async def _folderEntries(self, path: str) -> Dict[str, Dict]:
        entries = {}
        for entry in await self.cli.listFolder(path):
            name = _entry_name(entry)
            if name is None:
                continue
            # Proton allows duplicate names.  Keep the most folder-like entry
            # (folder > unknown > file) so a same-named file can't shadow the
            # addon's own backup folder in the walk, and so delete()'s
            # ambiguity check sees the folder.
            existing = entries.get(name)
            if existing is None or _folder_rank(entry) >= _folder_rank(existing):
                entries[name] = entry
        return entries

    # --- Reading the current state ---------------------------------------------

    async def get(self) -> Dict[str, ProtonBackup]:
        logger.info("Proton get(): checking authentication")
        await self.cli.checkAuth()
        logger.info("Proton get(): ensuring backup folder exists")
        folder = await self._ensureFolder()
        logger.info("Proton get(): listing '%s'", folder)
        # Latched before the listing: an unpaired tar seen while an upload was
        # in flight may be that upload's tar, whose sidecar can land (and the
        # flag clear) between any later re-list and the sweep.  The start
        # counter additionally catches an upload that both began and finished
        # while this get() was running.  Either signal skips tar sweeping for
        # this whole sync.
        uploading_at_listing = self._uploading
        upload_starts_at_listing = self._upload_starts
        try:
            entries = await self.cli.listFolder(folder)
        except (ProtonNotAuthenticated, ProtonTimeout):
            raise
        except ProtonError:
            # The folder may have been removed out from under us since we last
            # confirmed it.  Re-resolve (recreating it if needed) and retry once
            # rather than failing the whole sync.
            self._ensured_path = None
            folder = await self._ensureFolder()
            entries = await self.cli.listFolder(folder)

        tars = {}
        meta_files = set()
        for entry in entries:
            entry_name = _entry_name(entry)
            if entry_name is None:
                continue
            if _entry_is_folder(entry):
                # Sub-folders are never backups and must never be swept below:
                # trashing a folder-typed entry (even one *named* like a tar)
                # would trash its entire contents.
                logger.debug("Proton get(): ignoring sub-folder '%s'", entry_name)
                continue
            if "/" in entry_name or "\\" in entry_name:
                # os.path.basename() can't strip backslashes on Linux, so a "\"
                # can only come from outside the addon and could smuggle a path
                # separator into a later trash/download.  Never touch such an
                # entry.  ("/" can't actually survive basename(); it's checked
                # only as defense in depth.)
                logger.warning("Proton get(): ignoring entry with path-like name '%s'", entry_name)
                continue
            if entry_name.endswith(METADATA_SUFFIX):
                meta_files.add(entry_name)
            elif entry_name.endswith(TAR_SUFFIX):
                tars[entry_name] = entry

        if entries and not self._warned_typeless_listing and \
                all(_entry_is_folder(e) is None for e in entries):
            # Every destructive path fails closed without type information, so
            # deletion, retention pruning, and orphan cleanup are all disabled.
            # Make that state loud instead of leaving only per-operation errors.
            self._warned_typeless_listing = True
            logger.warning("The Proton Drive CLI listing reported no entry types; "
                           "deletion, retention cleanup, and orphan cleanup are "
                           "disabled until this is resolved (a CLI update may have "
                           "changed its output format)")

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
        live = {b.metadataPath() for b in backups.values()}
        for cached in list(self._meta_cache.keys()):
            if cached not in live:
                self._meta_cache.pop(cached, None)

        tar_slugs = {name[:-len(TAR_SUFFIX)] for name in tars}
        orphan_metas = [m for m in meta_files if m[:-len(METADATA_SUFFIX)] not in tar_slugs]
        if orphan_tars and (uploading_at_listing
                            or self._upload_starts != upload_starts_at_listing):
            logger.info("Skipping Proton orphan-tar cleanup this sync: an upload "
                        "was in progress when the folder was listed, or started since")
            sweep_tars = []
        else:
            sweep_tars = list(orphan_tars)
        unsweepable = set()
        if orphan_metas or sweep_tars:
            # The listing above can be minutes old by now (one sidecar download
            # per backup happened since), so re-list right before trashing.
            # Two things can have changed under us: a name can gain a
            # folder-typed duplicate at any time (which `trash`, resolving its
            # path argument by name, might pick), and a concurrent save() that
            # completed in the meantime pairs its tar — sweeping from the stale
            # listing would trash a live backup.  Without a fresh listing,
            # sweep nothing.
            try:
                fresh = await self.cli.listFolder(folder)
            except Exception as e:
                logger.warning("Skipping Proton orphan cleanup this sync (couldn't "
                               "re-list '{}'): {}".format(folder, e))
                orphan_metas, sweep_tars = [], []
            else:
                unsweepable = _unsweepable_names(fresh)
                fresh_names = {n for n in (_entry_name(e) for e in fresh) if n is not None}
                # Sweep only what is still present and unpaired in BOTH listings.
                orphan_metas = [m for m in orphan_metas if m in fresh_names and
                                m[:-len(METADATA_SUFFIX)] + TAR_SUFFIX not in fresh_names]
                sweep_tars = [t for t in sweep_tars if t in fresh_names and
                              t[:-len(TAR_SUFFIX)] + METADATA_SUFFIX not in fresh_names]

        # Best-effort: trash metadata sidecars whose tar is gone (e.g. a metadata
        # trash failed during a previous delete).  Otherwise they'd leak quota
        # forever, since get() would never iterate them again to retry.
        for meta_name in orphan_metas:
            if meta_name in unsweepable:
                logger.warning("Leaving Proton entry '{}' alone (can't confirm "
                               "it's a plain file)".format(meta_name))
                continue
            try:
                await self._trashInFolder(folder, meta_name)
                self._meta_cache.pop(folder + "/" + meta_name, None)
            except Exception as e:
                logger.debug("Couldn't clean up orphaned metadata '{}': {}".format(meta_name, e))

        # Best-effort: trash tars with no metadata sidecar.  These are left behind
        # when save() is interrupted (process killed) after the tar upload but
        # before the metadata upload — they're invisible to retention (never
        # parsed into a ProtonBackup) so nothing else would ever reap them, and
        # they'd leak quota forever.
        for tar_name in sweep_tars:
            if self._uploading or self._upload_starts != upload_starts_at_listing:
                # An upload is in flight (or ran to completion since we listed);
                # an unpaired tar may simply be one whose sidecar hasn't been
                # written — or was written after our listing snapshots.
                logger.info("Skipping Proton orphan-tar cleanup: an upload is in progress")
                break
            if tar_name in unsweepable:
                logger.warning("Leaving Proton entry '{}' alone (can't confirm "
                               "it's a plain file)".format(tar_name))
                continue
            try:
                await self._trashInFolder(folder, tar_name)
                logger.info("Removed orphaned Proton tar '{}' (no metadata sidecar)".format(tar_name))
            except Exception as e:
                logger.debug("Couldn't clean up orphaned tar '{}': {}".format(tar_name, e))
        logger.info("Proton get(): done, %d backup(s) present in Proton Drive", len(backups))
        return backups

    async def _loadMetadata(self, folder: str, meta_name: str, slug: str) -> Optional[Dict]:
        # Cache by full path, not filename: after a folder change, a same-slug
        # backup in the new folder must not be served the old folder's sidecar
        # (its retained flag could wrongly expose it to retention pruning).
        cache_key = folder + "/" + meta_name
        if cache_key in self._meta_cache:
            return self._meta_cache[cache_key]
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
            self._meta_cache[cache_key] = meta
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
        # `trash` resolves its path argument by name, and Proton allows
        # duplicate names: if a *folder* shares the tar's (or sidecar's) name,
        # the CLI could resolve the path to the folder and trash its whole
        # contents.  Re-list and refuse rather than gamble on resolution order
        # (_folderEntries keeps the most folder-like duplicate, so one lookup
        # per name suffices).
        entries = await self._folderEntries(item.folderPath())
        for name in (item.remoteName(), item.metadataName()):
            entry = entries.get(name)
            if entry is None:
                continue
            is_folder = _entry_is_folder(entry)
            if is_folder:
                raise ProtonError(
                    "Refusing to delete '{}': a folder named '{}' exists in "
                    "'{}', and deleting by that name could trash the folder "
                    "instead.  Rename or remove it in Proton Drive to let "
                    "deletion (and retention cleanup) proceed.".format(
                        item.name(), name, item.folderPath()))
            if is_folder is None:
                raise ProtonError(
                    "Refusing to delete '{}': the Proton Drive CLI listing "
                    "didn't report a type for '{}' in '{}', so it can't be "
                    "confirmed to be the backup's file.  This can happen when "
                    "a CLI update changes its output format.".format(
                        item.name(), name, item.folderPath()))
        # Trash (not permanent-delete): the CLI's `delete` only works on items
        # already in the trash, whereas `trash` moves a live item out of the
        # backup folder so it stops appearing in listings and retention
        # converges.  Trash the tar strictly: if it fails we must NOT drop the
        # local source, else the backup reappears next sync.  Metadata is
        # best-effort.
        tar_results = await self._trashInFolder(item.folderPath(), item.remoteName(), strict=True)
        meta_results = await self._trashInFolder(item.folderPath(), item.metadataName())
        # Purge only what delete() itself just removed — two validated backup
        # files the addon owns.  The orphan sweeps deliberately stay
        # move-to-trash-only, so a user file that merely LOOKS like a leftover
        # is never permanently destroyed.
        if self.config.get(Setting.PERMANENTLY_DELETE):
            await self._purgeFromTrash([(item.remoteName(), tar_results),
                                        (item.metadataName(), meta_results)])
        self._meta_cache.pop(item.metadataPath(), None)
        backup.removeSource(self.name())

    async def save(self, backup: Backup, source) -> ProtonBackup:
        await self.cli.checkAuth()
        folder = await self._ensureFolder()
        slug = backup.slug()
        retain = bool(backup.getOptions() and backup.getOptions().retain_sources.get(self.name(), False))

        meta = self._buildMetadata(backup, retain)

        tmpdir = tempfile.mkdtemp(dir=self._tempDir())
        tar_local = os.path.join(tmpdir, slug + TAR_SUFFIX)
        meta_local = os.path.join(tmpdir, slug + METADATA_SUFFIX)
        self._uploading = True
        self._upload_starts += 1
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

            self._meta_cache[folder + "/" + slug + METADATA_SUFFIX] = meta
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
        name = slug + TAR_SUFFIX
        try:
            # Like delete(): `trash` resolves its path argument by name and
            # Proton allows duplicate names, so confirm the name denotes a
            # plain file first — a same-named folder must never be the casualty
            # of a failed upload's rollback.  A skipped orphan is reaped later
            # by get()'s (equally guarded) sweep.
            entry = (await self._folderEntries(folder)).get(name)
            if entry is None:
                # The tar never actually landed (or the listing lags behind);
                # there's nothing to clean up.
                logger.debug("No orphaned tar '{}' found to clean up".format(name))
                return
            if _entry_is_folder(entry) is not False:
                logger.warning("Leaving Proton entry '{}' alone (can't confirm "
                               "it's a plain file)".format(name))
                return
            await self._trashInFolder(folder, name)
        except Exception as e:
            logger.warning("Couldn't clean up orphaned Proton tar for '{}': {}".format(slug, e))

    async def _trashInFolder(self, folder: str, name: str, strict: bool = False) -> List[Dict]:
        # Defense in depth for every removal: what's trashed must be a plain
        # file name directly inside the backup folder — a separator in the name
        # would let the trash reach outside it.
        if "/" in name or "\\" in name:
            if strict:
                raise ProtonError("Refusing to trash Proton entry with a path-like name '{}'".format(name))
            logger.warning("Refusing to trash Proton entry with a path-like name '{}'".format(name))
            return []
        return await self.cli.trash(folder + "/" + name, strict=strict)

    async def _purgeFromTrash(self, items: List) -> None:
        """
        Permanently delete just-trashed backup files ((name, trash results)
        pairs) so removed backups don't pile up in the Proton trash, where
        they'd keep counting toward the storage quota forever (Proton never
        empties the trash on its own).

        Only delete() calls this — on its two validated backup files — NEVER
        the orphan sweeps: a user file that merely looks like a leftover stays
        recoverable in the trash no matter what.

        Best-effort by design: the removal itself already succeeded (the items
        left the backup folder), so every guard below degrades to the old
        leave-it-in-the-trash behavior rather than failing the caller.
        """
        entries = None
        for name, trash_results in items:
            try:
                # Act only on a positively confirmed trash result: exactly one
                # node, ok=true, with a uid.  Anything else (trash failed,
                # output shape changed) leaves nothing safe to match on.
                uids = {r.get("uid") for r in trash_results
                        if r.get("ok") is True and isinstance(r.get("uid"), str)}
                if len(uids) != 1:
                    logger.debug("Not purging '%s' from the Proton trash: no confirmed trash result", name)
                    continue
                if entries is None:   # one trash listing covers all items
                    # Verified against the CLI source (v0.8.0): `list /trash`
                    # streams iterateTrashedNodes() to completion (no
                    # pagination/cap at the CLI layer), and its entries carry
                    # the same plain-string NodeEntity uid that `trash --json`
                    # reports — so the completeness and uid checks below are
                    # sound.  If either contract drifts, the guards fail safe
                    # (skip the purge, keep the item in the trash).
                    entries = await self.cli.listFolder("/trash")
                # `delete /trash/<name>` resolves the name by scanning the
                # whole trash and acts on the first match, so require the name
                # to denote exactly the node we just trashed: a same-named item
                # the *user* trashed must never be the one permanently deleted.
                matches = [e for e in entries if _entry_name(e) == name]
                if len(matches) != 1 or matches[0].get("uid") not in uids:
                    logger.warning(
                        "Leaving '{}' in the Proton Drive trash: its name doesn't uniquely "
                        "match the item that was just trashed.".format(name))
                    continue
                # Like the sweeps, never permanently delete anything that can't
                # be confirmed to be a plain file: if the name-resolved trash()
                # ever took a same-named folder (the race the pre-trash
                # listings guard against), leaving it recoverable in the trash
                # caps the damage.
                if _entry_is_folder(matches[0]) is not False:
                    logger.warning("Leaving '{}' in the Proton Drive trash: can't confirm "
                                   "it's a plain file.".format(name))
                    continue
                # Residual race: `delete /trash/<name>` re-resolves the name at
                # delete time (first match wins), so an identically named item
                # trashed by another client between the listing above and this
                # call could be the one deleted.  The CLI offers no
                # uid-addressed delete, so this window can't be closed further.
                await self.cli.delete("/trash/" + name, strict=True)
                logger.debug("Permanently deleted '%s' from the Proton Drive trash", name)
            except Exception as e:
                logger.warning("Couldn't permanently delete '{}' from the Proton Drive trash "
                               "(it stays in the trash): {}".format(name, e))

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
        # Upload next to the backup's own tar, not the currently-configured
        # folder: after a proton_folder_name change these differ, and uploading
        # to the new folder would split the tar and its sidecar across folders.
        folder = item.folderPath()
        tmpdir = tempfile.mkdtemp(dir=self._tempDir())
        meta_local = os.path.join(tmpdir, item.metadataName())
        try:
            with open(meta_local, "w", encoding="utf-8") as f:
                json.dump(meta, f)
            await self.cli.upload(meta_local, folder)
            self._meta_cache[item.metadataPath()] = meta
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


def _entry_is_folder(entry: Dict) -> Optional[bool]:
    # Real CLI listings carry a "type" field ("file"/"folder").  Returns None
    # when the entry doesn't say, so callers can decide how to degrade on a CLI
    # output-shape change: the folder walk falls back to name-only matching,
    # while the orphan sweeps fail closed (never trash an unknown type).
    entry_type = entry.get("type")
    # Tolerate the {"ok": ..., "value": ...} result wrapper the CLI already
    # uses for the (E2EE) name field, in case type gets wrapped the same way.
    if isinstance(entry_type, dict):
        entry_type = entry_type.get("value")
    if isinstance(entry_type, str) and entry_type:
        return entry_type.lower() in ("folder", "dir", "directory")
    return None


def _unsweepable_names(entries: List[Dict]) -> set:
    # Names that can't be confirmed to denote a plain file: the entry is
    # folder-typed, or its type is unknown.  Proton allows duplicate names, so
    # any one such entry poisons the name for `trash` (which resolves its path
    # argument by name) — trashing it could take a folder and all its contents.
    names = set()
    for entry in entries:
        name = _entry_name(entry)
        if name is not None and _entry_is_folder(entry) is not False:
            names.add(name)
    return names


def _folder_rank(entry: Dict) -> int:
    # Orders duplicate-name listing entries by how folder-like they are, so
    # ambiguity-sensitive callers always see the most dangerous interpretation.
    is_folder = _entry_is_folder(entry)
    if is_folder:
        return 2
    if is_folder is None:
        return 1
    return 0


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
