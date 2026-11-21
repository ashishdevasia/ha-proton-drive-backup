## v0.4.0 [2026-11-22]

- The add-on is now translated into German, Spanish, French, Italian, Dutch, Polish, Brazilian Portuguese and
  Malayalam: its web UI and its Configuration tab in Home Assistant follow your Home Assistant language. For other
  languages the web UI tries your browser's language, then English. Most translations haven't been checked by a
  native speaker yet: corrections are welcome (see the README)
- The Configuration tab shows readable names and descriptions instead of raw option keys
- The web UI shows dates and times in your language and in Home Assistant's time zone
- Removed options that had no effect: `verbose`, `send_error_reports`, `specify_backup_folder`,
  `disable_watchdog_when_stopping` (an add-on's watchdog is always turned off while it's stopped for a backup),
  `maximum_upload_chunk_bytes` and `upload_limit_bytes_per_second` (the Proton Drive CLI does the transfers)
- Fixed: if the web UI was opened while the add-on was still starting, it stayed on "Couldn't reach the add-on"
  instead of recovering on its own
- Fixed: changes to the log levels or "Watch the backup directory for changes" could be silently undone, e.g. turning
  the watch back on, or setting a log level back to "— default —"
- Fixed: in the web UI, a plain number in "Delete ignored backups after" counted as seconds, not days. With the
  default settings that meant every backup the add-on didn't make (Home Assistant's own scheduled, manual and
  pre-update backups) was deleted about that many seconds after it appeared. `30` now means 30 days, as it does in
  the Configuration tab (see **Breaking** below). Apart from a plain number on its own, every number in a duration
  now needs a unit: `30,` or `1d 12` is rejected rather than partly read as seconds
- Fixed: with "Days between backups" under 1 and a time of day set, every sync made a backup and deleted the oldest,
  over and over. With a time of day it's now rounded up to whole days: `0.5` means every day, and `1.5` every 2
  days (it was every day)
- Fixed: a huge "Days between backups" (millions of days, e.g. meant as "never") stopped every sync and broke the
  status page and sensors; it now means no scheduled backups
- Fixed: a large generational count, such as `9999` yearly backups meant as "forever", stopped every sync, and
  large daily or weekly counts slowed each sync down
- Fixed: a very large "Delete ignored backups after", such as `999999 days` meant as "never", stopped every sync;
  now nothing is deleted
- Fixed: a huge duration set in the Configuration tab, such as "Max sync interval", could stop syncs, keep the web
  UI's Settings tab from loading, or make every save there fail
- Fixed: saving the web UI's settings rounded durations set in the Configuration tab, e.g. 0.999 days became 0.99899
- Fixed: the web UI couldn't save its settings when "Days between backups" or a Proton Drive timeout set in the
  Configuration tab had more decimals than the field allowed, e.g. `0.25`. A number field hidden by "Show advanced"
  that held text the browser couldn't read as a number was saved as its default; now the save is refused
- The web UI checks the values you change: "Days between backups" from 0.1 to 36500 (or 0 for none), "Delete
  ignored backups after" at least 1 day (or blank for never), generational counts up to 3650 days, 520 weeks, 1200
  months or 100 years, and "Max sync interval" up to 30 days. The Configuration tab doesn't limit them, and the web
  UI keeps a value set there when you save other changes
- Fixed: the web UI accepted a "Max sync interval" under 5 minutes, which Home Assistant then refused, so the whole
  save failed
- Fixed: the "Max sync interval" help suggested `1:30:00`, which the add-on rejects
- Fixed: after one failed attempt to fetch Proton Drive's backup list ahead of a sync, the add-on stopped doing so
  until it restarted, instead of for a day
- Removed an unused dependency (dnspython)

**Breaking:** a plain number in the web UI's "Delete ignored backups after" now means days, not seconds. When the
  updated add-on first starts, it corrects a value that looks saved that way (`30` saved as 30 seconds becomes 30
  days): one under an hour, or one that nothing you'd likely have meant also saved. For any other value that typing
  a number could have saved, such as `2 hours` (also what typing `7200` saved), it asks you once, in a notification,
  to check it. Whole days and multiples of 6 hours are left alone. It only notifies you if the add-on deletes
  ignored backups.

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
