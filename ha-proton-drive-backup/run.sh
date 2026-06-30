#!/usr/bin/env bash
# Entrypoint for the Home Assistant Proton Drive Backup add-on.
#
# The proton-drive CLI keeps its login session in the OS secret store (libsecret
# on Linux).  Containers have no secret service by default, so we start a private
# D-Bus session plus gnome-keyring and unlock it with a key persisted in /data.
# The keyring storage itself also lives under /data, so a single
# `proton-drive auth login` survives add-on restarts and upgrades.
set -e

# Honor the `proton_data_path` add-on option (falls back to the env var, then
# the default) so the keyring/session and the Python side agree on one path.
OPTIONS_FILE="/data/options.json"
if [ -z "${PROTON_DATA_PATH}" ] && [ -f "${OPTIONS_FILE}" ]; then
    PROTON_DATA_PATH="$(python3 -c "import json,sys
try:
    print(json.load(open('${OPTIONS_FILE}')).get('proton_data_path') or '')
except Exception:
    print('')" 2>/dev/null)"
fi
PROTON_DATA="${PROTON_DATA_PATH:-/data/proton}"
export PROTON_DATA_PATH="${PROTON_DATA}"
export HOME="${PROTON_DATA}"
export XDG_DATA_HOME="${PROTON_DATA}/.local/share"
export XDG_CONFIG_HOME="${PROTON_DATA}/.config"
export XDG_CACHE_HOME="${PROTON_DATA}/.cache"
KEYRING_PASS_FILE="${PROTON_DATA}/keyring.key"

mkdir -p "${XDG_DATA_HOME}/keyrings" "${XDG_CONFIG_HOME}" "${XDG_CACHE_HOME}" "${PROTON_DATA}/tmp"

# Generate a stable keyring password the first time the add-on runs.  It only
# protects the Proton session at rest inside the already-private /data volume.
if [ ! -f "${KEYRING_PASS_FILE}" ]; then
    head -c 32 /dev/urandom | base64 > "${KEYRING_PASS_FILE}"
    chmod 600 "${KEYRING_PASS_FILE}"
fi
KEYRING_PASS="$(cat "${KEYRING_PASS_FILE}")"

start_keyring() {
    # Start (or replace) gnome-keyring-daemon and unlock it in a single call.
    # --replace ensures only one daemon runs; --unlock reads the password from
    # stdin and unlocks the "login" keyring (creating it on first run).  The
    # daemon prints GNOME_KEYRING_CONTROL and GNOME_KEYRING_PID which we eval
    # so that libsecret (used by proton-drive) can find the service.
    eval "$(echo -n "${KEYRING_PASS}" | gnome-keyring-daemon --replace --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL GNOME_KEYRING_PID
}

# Run everything under a private D-Bus session so libsecret can find the service.
# KEYRING_PASS is exported (not baked into the command line) so it doesn't show
# up in the child's argv / `ps` output.
export KEYRING_PASS
# Prevent gnome-keyring from trying to open a GUI prompter (there is no display).
export GCR_ALLOW_INTERACTION=false
exec dbus-run-session -- bash -c '
    set -e
    '"$(declare -f start_keyring)"'
    start_keyring
    exec python3 -m backup
'
