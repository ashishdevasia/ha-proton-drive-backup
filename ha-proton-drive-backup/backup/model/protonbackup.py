from typing import Any, Dict

from .backups import AbstractBackup
from ..const import (SOURCE_PROTON_DRIVE, NECESSARY_PROP_KEY_SLUG,
                     NECESSARY_PROP_KEY_DATE, NECESSARY_PROP_KEY_NAME, PROP_NOTE)
from ..exceptions import ensureKey
from ..config import BoolValidator
from ..time import Time
from ..logger import getLogger

logger = getLogger(__name__)

PROP_TYPE = "type"
PROP_VERSION = "version"
PROP_PROTECTED = "protected"
PROP_RETAINED = "retained"
PROTON_KEY_TEXT = "Proton Drive's backup metadata"

# Suffixes used for the two files we keep on Proton Drive per backup.
TAR_SUFFIX = ".tar"
METADATA_SUFFIX = ".metadata.json"


class ProtonBackup(AbstractBackup):
    """
    Represents a Home Assistant backup stored on Proton Drive.

    Because Proton files carry no queryable properties, all metadata lives in a
    sidecar `<slug>.metadata.json` next to the `<slug>.tar`.  `meta` is that
    parsed sidecar; `remote_name` / `remote_size` come from the CLI listing.
    """

    def __init__(self, meta: Dict[str, Any], remote_name: str, remote_size: int,
                 folder_path: str):
        retained = BoolValidator.strToBool(str(meta.get(PROP_RETAINED, "False")))
        slug = ensureKey(NECESSARY_PROP_KEY_SLUG, meta, PROTON_KEY_TEXT)
        backup_name = meta.get(NECESSARY_PROP_KEY_NAME) or remote_name.replace(TAR_SUFFIX, "")
        super().__init__(
            name=backup_name,
            slug=slug,
            date=Time.parse(ensureKey(NECESSARY_PROP_KEY_DATE, meta, PROTON_KEY_TEXT)),
            size=int(remote_size),
            source=SOURCE_PROTON_DRIVE,
            backupType=meta.get(PROP_TYPE, "?"),
            version=meta.get(PROP_VERSION, None),
            protected=BoolValidator.strToBool(str(meta.get(PROP_PROTECTED, "?"))),
            retained=retained,
            uploadable=False,
            details=None,
            note=meta.get(PROP_NOTE, None),
            pending=False)
        self._meta = meta
        self._remote_name = remote_name
        self._folder_path = folder_path.rstrip("/")

    def remoteName(self) -> str:
        return self._remote_name

    def folderPath(self) -> str:
        return self._folder_path

    def tarPath(self) -> str:
        return self._folder_path + "/" + self._remote_name

    def metadataName(self) -> str:
        # Derive the sidecar name from the (trusted) remote tar filename, NOT
        # from self.slug(): the slug comes from the metadata file's *contents*,
        # so a tampered sidecar with a slug like "../foo" would otherwise make
        # metadataPath() point outside the backup folder and feed that path to a
        # destructive `trash`/upload.  The tar and its sidecar are always
        # uploaded under the same base name, so this is also the correct name.
        base = self._remote_name
        if base.endswith(TAR_SUFFIX):
            base = base[:-len(TAR_SUFFIX)]
        return base + METADATA_SUFFIX

    def metadataPath(self) -> str:
        return self._folder_path + "/" + self.metadataName()

    def metadata(self) -> Dict[str, Any]:
        return self._meta

    def __str__(self) -> str:
        return "<Proton: {0} Name: {1} Path: {2}>".format(self.slug(), self.name(), self.tarPath())

    def __format__(self, format_spec: str) -> str:
        return self.__str__()

    def __repr__(self) -> str:
        return self.__str__()
