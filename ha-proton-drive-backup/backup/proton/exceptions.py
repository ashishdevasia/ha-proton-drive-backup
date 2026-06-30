from ..exceptions import KnownError, KnownTransient
from ..const import (ERROR_PROTON_NOT_AUTHENTICATED, ERROR_PROTON_CLI_MISSING,
                     ERROR_PROTON_TIMEOUT, ERROR_PROTON_CLI_ERROR)


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

    def message(self):
        return "The proton-drive CLI couldn't be found at '{}'.".format(self._path)

    def code(self):
        return ERROR_PROTON_CLI_MISSING

    def retrySoon(self):
        return False


class ProtonTimeout(KnownTransient):
    def __init__(self, command: str = None):
        self._command = command

    def message(self):
        return "A Proton Drive operation timed out ({}).".format(self._command)

    def code(self):
        return ERROR_PROTON_TIMEOUT


class ProtonError(KnownError):
    def __init__(self, detail: str = None, returncode: int = None):
        self._detail = detail
        self._returncode = returncode

    def message(self):
        return self._detail or "The proton-drive CLI returned an error."

    def code(self):
        return ERROR_PROTON_CLI_ERROR

    def data(self):
        return {"returncode": self._returncode} if self._returncode is not None else {}
