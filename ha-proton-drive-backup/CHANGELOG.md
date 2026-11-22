## v0.4.0 [2026-11-23]

- Translated into German, Spanish, French, Italian, Dutch, Polish, Brazilian Portuguese and Malayalam: the web UI
  and the Configuration tab follow your Home Assistant language. Most translations haven't been checked by a native
  speaker yet; corrections are welcome (see the README)
- The Configuration tab shows readable names and descriptions instead of raw option keys
- The web UI shows dates and times in your language and in Home Assistant's time zone
- The web UI is readable with a light "Background color": it switches to dark text on light cards. Text on
  buttons turns dark when the "Accent color" is light
- Fixed: a plain number in the web UI's "Delete ignored backups after" counted as seconds, not days, so backups the
  add-on didn't make could be deleted seconds after they appeared
- Fixed: "Days between backups" under 1 with a time of day set made a backup on every sync; with a time of day it's
  now rounded up to whole days
- Fixed: very large values in the time settings (e.g. `9999` yearly backups) could stop every sync; the web UI now
  checks the values you change
- Fixed: changes to the log levels or "Watch the backup directory for changes" could be silently undone
- Fixed: a "Background color" or "Accent color" saved in the web UI only showed after you reloaded the page
- Removed options that had no effect: `verbose`, `send_error_reports`, `specify_backup_folder`,
  `disable_watchdog_when_stopping`, `maximum_upload_chunk_bytes` and `upload_limit_bytes_per_second`
- Removed an unused dependency
- Bug-fixes

**Breaking:** a plain number in the web UI's "Delete ignored backups after" now means days, not seconds. On its
  first start the add-on corrects a value that looks saved as seconds (`30` becomes 30 days), or asks you once, in
  a notification, to check it.

## v0.3.0 [2026-11-02]

- Security fix: the bundled Proton Drive CLI no longer trusts the compromised eMudhra root certificates
- Security fixes for the web UI: the ingress port only accepts Home Assistant's ingress, the extra server blocks
  requests from other websites, and `require_login` only lets administrators sign in
- Fixed: saving settings with "Show advanced" off reset the advanced settings to their defaults
- Fixed: signing in to the extra server failed for passwords with non-ASCII characters
- Updated the bundled Proton Drive CLI from 0.8.0 to 0.9.0
- Dependency updates

**Breaking:** scripts must call the extra server's API (not the ingress port), and use POST for anything that
  changes something.

## v0.2.2 [2026-09-20]

- Dependency updates

## v0.2.1 [2026-09-05]

- Fixed: v0.2.0 didn't work on older CPUs and some VMs, showing a
  misleading authentication failure
- Better error messages when the Proton Drive CLI crashes

## v0.2.0 [2026-08-31]

- `proton_folder_name` can now be a nested path, e.g. `backups/ha`; missing folder levels are created automatically.
- Updated the bundled Proton Drive CLI from 0.6.0 to 0.8.0
- New `permanently_delete` option (default `true`): backups removed from Proton Drive are also deleted from its
  trash, so they stop counting toward the storage quota.
- Bug-fixes

**Breaking:** a `/` in `proton_folder_name` used to mean a dash-joined folder name (`backups/ha` → `backups-ha`); 
  it now means a nested path — the old folder is left untouched but its backups are no longer visible to the app.

**Breaking:** removed backups are no longer recoverable from Proton Drive's trash by default; 
  set `permanently_delete: false` to keep the old move-to-trash-only behavior.

## v0.1.4 [2026-07-25]

- Updated the bundled Proton Drive CLI from 0.5.0 to 0.6.0
- UI fixes

## v0.1.3 [2026-07-15]

- Fixed: a corrupted proton-drive `events.lock` (after an unclean shutdown) blocked every operation, even sign-in;
  now heals automatically on update/restart
- Updated the bundled Proton Drive CLI from 0.4.6 to 0.5.0

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
