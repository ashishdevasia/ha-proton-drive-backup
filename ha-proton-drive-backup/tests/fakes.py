"""Test doubles for the Proton Drive backend."""
import os
import stat
from datetime import datetime

from dateutil.tz import tzutc

from backup.config import Config, Setting
from backup.proton import ProtonCli
from backup.proton.exceptions import ProtonError, ProtonNotAuthenticated
from backup.model.protonbackup import TAR_SUFFIX, METADATA_SUFFIX


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


class FakeProtonCli:
    """
    An in-memory Proton Drive that stages real bytes, mirroring the subset of
    the ProtonCli interface that ProtonSource uses.
    """

    def __init__(self, authenticated=True):
        self._authenticated = authenticated
        self._auth_warning = None
        self.files = {}            # remote_path -> bytes
        self.trashed = {}          # remote_path -> bytes (moved to trash)
        self.folders = set()       # known folder paths
        self.calls = []            # list of (op, *args)
        self.download_count = 0
        self.upload_count = 0

    # -- auth -------------------------------------------------------------------
    def isAuthenticated(self):
        return self._authenticated

    def authWarning(self):
        return self._auth_warning

    async def checkAuth(self):
        self.calls.append(("checkAuth",))
        return self._authenticated

    async def logout(self):
        self.calls.append(("logout",))
        self._authenticated = False
        self._auth_warning = None

    # -- filesystem -------------------------------------------------------------
    def _require_auth(self):
        if not self._authenticated:
            raise ProtonNotAuthenticated("no session")

    async def info(self, path):
        self.calls.append(("info", path))
        self._require_auth()
        if path in self.folders or path in self.files:
            return {"name": os.path.basename(path)}
        raise ProtonError("not found: " + path, 1)

    async def createFolder(self, parent_path, name):
        self.calls.append(("createFolder", parent_path, name))
        self.folders.add(parent_path + "/" + name)
        return {"name": name}

    async def listFolder(self, path):
        self.calls.append(("listFolder", path))
        self._require_auth()
        # The root is always listable; a non-existent sub-folder errors, like the
        # real CLI.
        if path != "/my-files" and path not in self.folders:
            raise ProtonError("folder not found: " + path, 1)
        entries = []
        prefix = path.rstrip("/") + "/"
        for remote, data in self.files.items():
            if remote.startswith(prefix) and "/" not in remote[len(prefix):]:
                entries.append({"name": os.path.basename(remote), "size": len(data)})
        for folder in self.folders:
            if folder.startswith(prefix) and "/" not in folder[len(prefix):]:
                entries.append({"name": os.path.basename(folder), "type": "folder"})
        return entries

    async def upload(self, local_path, parent_path, conflict="replace"):
        self.upload_count += 1
        self.calls.append(("upload", local_path, parent_path, conflict))
        with open(local_path, "rb") as f:
            data = f.read()
        self.files[parent_path.rstrip("/") + "/" + os.path.basename(local_path)] = data

    async def download(self, remote_path, local_folder, conflict="replace"):
        self.download_count += 1
        self.calls.append(("download", remote_path, local_folder, conflict))
        if remote_path not in self.files:
            raise ProtonError("not found: " + remote_path, 1)
        os.makedirs(local_folder, exist_ok=True)
        with open(os.path.join(local_folder, os.path.basename(remote_path)), "wb") as f:
            f.write(self.files[remote_path])

    async def trash(self, path, strict=False):
        # Moves an item out of its folder into the trash (so listFolder no longer
        # shows it), mirroring `proton-drive filesystem trash`.
        self.calls.append(("trash", path))
        if getattr(self, "trash_should_fail", False) and strict:
            raise ProtonError("trash failed: " + path, 1)
        if path in self.files:
            self.trashed[path] = self.files.pop(path)

    async def delete(self, path, strict=False):
        # The real CLI permanently deletes ONLY trashed items.
        self.calls.append(("delete", path))
        if path not in self.trashed:
            if strict:
                raise ProtonError("delete on live item: " + path, 1)
            return
        self.trashed.pop(path, None)

    # -- test helpers -----------------------------------------------------------
    def seed_backup(self, folder, slug, meta_bytes, tar_bytes=b"tarcontents"):
        self.folders.add(folder)
        self.files[folder + "/" + slug + TAR_SUFFIX] = tar_bytes
        self.files[folder + "/" + slug + METADATA_SUFFIX] = meta_bytes


class FakeInfo:
    def __init__(self):
        self.uploaded = []

    def upload(self, size):
        self.uploaded.append(size)


class FakeSource:
    """Async byte source matching what ProtonSource.save() consumes."""

    def __init__(self, data: bytes, chunk=4):
        self._data = data
        self._chunk = chunk
        self._pos = 0

    def size(self):
        return len(self._data)

    async def __aenter__(self):
        self._pos = 0
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._pos >= len(self._data):
            raise StopAsyncIteration
        chunk = self._data[self._pos:self._pos + self._chunk]
        self._pos += len(chunk)
        return chunk


class FakeBackup:
    """Minimal stand-in for model.Backup used by ProtonSource."""

    def __init__(self, slug="abc123", name="Full Backup", retain=False, note=None):
        self._slug = slug
        self._name = name
        self._date = datetime(2026, 6, 27, 1, 2, 3, tzinfo=tzutc())
        self._note = note
        self._options = None
        self._sources = {}
        self.status_log = []
        if retain:
            from backup.config import CreateOptions
            from backup.const import SOURCE_PROTON_DRIVE
            self._options = CreateOptions(self._date, name, {SOURCE_PROTON_DRIVE: True})

    def slug(self):
        return self._slug

    def name(self):
        return self._name

    def date(self):
        return self._date

    def note(self):
        return self._note

    def backupType(self):
        return "full"

    def version(self):
        return "2026.6.0"

    def protected(self):
        return True

    def getOptions(self):
        return self._options

    def getSource(self, name):
        return self._sources.get(name)

    def addSource(self, source):
        # Mirrors model.Backup.addSource, which keys by the source *system*.
        self._sources[source.source()] = source

    def removeSource(self, name):
        self._sources.pop(name, None)

    def setRetained(self, retained):
        pass

    def setNote(self, note):
        self._note = note

    def overrideStatus(self, *a):
        self.status_log.append(a)

    def setUploadSource(self, *a):
        pass

    def clearUploadSource(self):
        pass

    def clearStatus(self):
        pass
