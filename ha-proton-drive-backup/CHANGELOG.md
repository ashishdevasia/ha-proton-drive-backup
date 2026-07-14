## v0.1.3 [2026-07-15]

- Fixed: a corrupted proton-drive `events.lock` file (NUL-filled after an
  unclean host shutdown, e.g. a power loss) made every Proton Drive operation
  fail with `SyntaxError: JSON Parse error` — including signing in again. The
  add-on now clears the stale lock at startup and self-heals if the corruption
  appears while running, so affected installs recover by updating or
  restarting the add-on. See DOCS.md for a manual workaround on older
  versions.
- Updated the bundled Proton Drive CLI from 0.4.6 to 0.5.0 (fixes a memory
  leak during uploads — relevant on low-RAM hosts — and honors the account's
  telemetry preference). Existing sign-ins carry over.

## v0.1.2 [2026-07-06]

- Fixed the "next to delete" tag pointing at the wrong backup when
  generational backups are enabled

## v0.1.1 [2026-07-04]

- Fixed getting stuck "signed out" (with backups paused) after an internet
  outage: offline CLI errors were misread as a sign-out and never re-checked.
  Every sync now re-probes a signed-out session, so the add-on recovers on
  its own once connectivity returns.
- Added a Sign out button (About page) — previously the only way to switch
  accounts was wiping the add-on's data.
- Fixed the three-dots menu on ignored backups being rendered semi-transparent.

## v0.1.0 [2026-07-01]

Initial release of the Proton Drive port.

- Forked from [hassio-google-drive-backup](https://github.com/sabeechen/hassio-google-drive-backup)
  (MIT, © Stephen Beechen), replacing the Google Drive backend with a Proton
  Drive backend that drives the official `proton-drive` CLI.
