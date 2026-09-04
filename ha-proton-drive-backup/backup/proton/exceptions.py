from ..exceptions import KnownError, KnownTransient
from ..const import (ERROR_PROTON_NOT_AUTHENTICATED, ERROR_PROTON_CLI_MISSING,
                     ERROR_PROTON_TIMEOUT, ERROR_PROTON_CLI_ERROR,
                     ERROR_PROTON_CONNECTION)


class ProtonNotAuthenticated(KnownError):
    def __init__(self, detail: str = None):
        self._detail = detail

    def message(self):
        return ("The addon isn't signed in to Proton Drive.  Open the addon's "
                "Web UI and click Sign in to authorize with Proton Drive.")

    def code(self):
        return ERROR_PROTON_NOT_AUTHENTICATED

    def retrySoon(self):
        return False

    def data(self):
        return {"detail": self._detail} if self._detail else {}


class ProtonCliMissing(KnownError):
    def __init__(self, path: str = None):
        self._path = path

    def __str__(self):
        # Readable in logs/UI, not just the bare path.  Overriding __str__
        # (rather than passing the text to super().__init__) leaves args
        # untouched, so pickle/copy reconstruction can't double-wrap.
        return self.message()

    def message(self):
        return "The proton-drive CLI couldn't be found at '{}'.".format(self._path)

    def code(self):
        return ERROR_PROTON_CLI_MISSING

    def retrySoon(self):
        return False


class ProtonTimeout(KnownTransient):
    def __init__(self, command: str = None):
        self._command = command

    def __str__(self):
        return self.message()  # readable, not just the command; see ProtonCliMissing

    def message(self):
        return "A Proton Drive operation timed out ({}).".format(self._command)

    def code(self):
        return ERROR_PROTON_TIMEOUT


class ProtonConnectionError(KnownTransient):
    """The CLI couldn't reach Proton's servers; says nothing about the session."""

    def __init__(self, detail: str = None):
        self._detail = detail

    def message(self):
        return ("Couldn't reach Proton Drive (network problem).  The addon "
                "will keep retrying automatically.")

    def code(self):
        return ERROR_PROTON_CONNECTION

    def data(self):
        return {"detail": self._detail} if self._detail else {}


class ProtonError(KnownError):
    def __init__(self, detail: str = None, returncode: int = None):
        self._detail = detail
        self._returncode = returncode

    def __str__(self):
        # Without this, a two-arg ProtonError stringifies as the args tuple,
        # which leaks into logs and the UI's auth warning.  See ProtonCliMissing
        # for why __str__ and not super().__init__(message).
        return self.message()

    def message(self):
        return self._detail or "The proton-drive CLI returned an error."

    def code(self):
        return ERROR_PROTON_CLI_ERROR

    def data(self):
        return {"returncode": self._returncode} if self._returncode is not None else {}
