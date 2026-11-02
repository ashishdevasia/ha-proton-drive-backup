import re
from pathlib import Path

ADDON = Path(__file__).resolve().parent.parent
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)")


def _normalize(name):
    # PEP 503: names compare case-insensitively with -, _ and . equivalent.
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements():
    pins = {}
    for line in (ADDON / "requirements-addon.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            m = PIN.match(line)
            assert m, "requirements-addon.txt must pin with ==: " + line
            pins[_normalize(m.group(1))] = m.group(2)
    return pins


def _lock():
    """{name: (version, listed directly in requirements-addon.txt?)}"""
    entries = {}
    current = None
    for line in (ADDON / "requirements-addon.lock").read_text().splitlines():
        m = PIN.match(line)
        if m:
            current = _normalize(m.group(1))
            entries[current] = [m.group(2), False]
        elif current and "-r requirements-addon.txt" in line:
            entries[current][1] = True
    return {name: tuple(entry) for name, entry in entries.items()}


def test_lock_matches_requirements():
    # The image installs only the lock, so a requirements-addon.txt edit that
    # isn't followed by regenerating the lock would silently not ship.
    requirements = _requirements()
    lock = _lock()
    for name, version in requirements.items():
        assert name in lock, "{} is missing from requirements-addon.lock; regenerate it".format(name)
        assert lock[name][0] == version, "{}: requirements-addon.txt pins {}, the lock has {}; regenerate it".format(
            name, version, lock[name][0])
    direct = {name for name, (_, is_direct) in lock.items() if is_direct}
    assert direct == set(requirements), "lock lists different direct dependencies; regenerate it"
