## v0.2.1 [2026-09-01]

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
