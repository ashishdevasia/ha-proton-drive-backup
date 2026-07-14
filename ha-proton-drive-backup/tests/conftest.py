import os

import pytest

# Force the Config() default path (no /data/options.json) during tests.
os.environ.setdefault("PYTEST_CURRENT_TEST", "conftest")


@pytest.fixture(autouse=True)
def isolated_proton_env(tmp_path, monkeypatch):
    # Keep ProtonCli's env mirror (and any fake CLI it spawns) inside the test
    # tmpdir so nothing reads or heals the developer's real lock/session files.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.delenv("PROTON_DRIVE_CACHE_DIR", raising=False)
