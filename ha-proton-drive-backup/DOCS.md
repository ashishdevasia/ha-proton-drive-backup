# Home Assistant App (Add-on): Proton Drive Backup

This app creates Home Assistant backups on a schedule and keeps copies of
them in your end-to-end encrypted Proton Drive. It is a port of the
[Google Drive Backup app](https://github.com/sabeechen/hassio-google-drive-backup);
the scheduling, retention, and Home Assistant integration are unchanged.

> **This is a third-party application not officially supported by Proton.** It is
> not affiliated with, endorsed by, or operated by Proton AG.

## Getting started

1. Install and start the app.
2. Open the Web UI and click **Sign in**. Open the Proton link it shows in any
   browser and complete sign-in (including 2-factor). The UI flips to **Signed
   in** automatically. See [AUTHENTICATION.md](AUTHENTICATION.md).

Once signed in, backups sync automatically.

## Options

### Core backup options

- `max_backups_in_ha` (default `4`): how many backups to keep in Home Assistant;
  the oldest is deleted first. `0` means never delete from Home Assistant (to
  keep no local copies, use `delete_after_upload` instead). Backups marked
  "keep forever" or ignored don't count toward this limit.
- `max_backups_in_proton_drive` (default `4`): how many backups to keep in
  Proton Drive; the oldest is deleted first. `0` means never delete from
  Proton Drive.
- `days_between_backups` (default `3`): how often to create a new backup. `0` disables automatic backups.
- `backup_name`: template for backup names (e.g. `{type} Backup {year}-{month}-{day}`).
- `backup_time_of_day`: `HH:MM` time of day to create backups.
- `delete_after_upload`: delete a backup from Home Assistant once it reaches Proton Drive.
- `delete_before_new_backup`: purge old backups before creating a new one.
- `ignore_other_backups` / `ignore_upgrade_backups`: ignore backups not created by this app.

### Proton Drive options

- `enable_proton_upload` (default `true`): upload backups to Proton Drive. When
  `false`, the app only manages backups inside Home Assistant.
- `proton_folder_name` (default `Home Assistant Backups`): the folder created
  under Proton Drive's `/my-files` root.
- `proton_cli_path` (default `/usr/bin/proton-drive`): path to the bundled CLI.
- `proton_data_path` (default `/data/proton`): where the CLI session, keyring,
  and temporary transfer files are stored.
- `proton_drive_timeout_seconds` (default `180`): timeout for list/metadata operations.
- `proton_transfer_timeout_seconds` (default `3600`): timeout for uploads/downloads.

### Generational backups

`generational_days`, `generational_weeks`, `generational_months`,
`generational_years` and the related `generational_*` options enable a
grandfather-father-son retention scheme. See
[GENERATIONAL_BACKUP.md](GENERATIONAL_BACKUP.md).

Two things to know when any of these are set:

- `generational_days: 0` is treated as `1` — the newest backup is always kept.
  Any backup that isn't a daily/weekly/monthly/yearly keeper is deleted as soon
  as a newer backup exists, so with `days` at 0/1 yesterday's backup is usually
  the next to go.
- `max_backups_in_ha` / `max_backups_in_proton_drive` still apply. If the
  generational plan wants more slots than the max allows (days + weeks +
  months + years), the oldest keepers are deleted to stay under the max, so
  set the max at least that high.

### Web server / UI

- `ingress`: the UI is served through Home Assistant ingress by default.
- `expose_extra_server`, `port`, `use_ssl`, `certfile`, `keyfile`,
  `require_login`: optionally expose the UI directly on a port.

## How backups are stored

Each backup becomes two files in the Proton Drive folder:

- `<slug>.tar` — the backup archive.
- `<slug>.metadata.json` — a small sidecar describing the backup (name, date,
  type, version, protected/retained flags, note). Proton Drive has no
  file-property API, so this sidecar is how the app tracks backups.

The Proton Drive CLI cannot stream, so each upload and download is staged
through a temporary file under `proton_data_path` (default `/data/proton/tmp`).
This means a transfer briefly needs free disk space equal to the size of the
backup being uploaded or downloaded, on top of the copy Home Assistant already
keeps. The temporary file is removed as soon as the transfer finishes.

## Security note: your Proton session lives in `/data` and is captured by backups

To stay signed in across restarts, the `proton-drive` CLI keeps its session in a
keyring under `proton_data_path` (default `/data/proton`). Home Assistant
includes every app's `/data` in a **full backup**, so the Proton session is
captured inside the backup archives this app creates — including the copies
it uploads to Proton Drive.

The copy stored in Proton Drive is end-to-end encrypted by Proton, so Proton (or
anyone seeing it at rest there) can't read it. The risk is local: an unencrypted
`.tar` you download, or that sits on your `/backup` share, would contain a
session that can access your Proton Drive.

**If this bothers you:**

1. Set a **`backup_password`**. This encrypts the whole archive, so the embedded
   session can't be read out of it. (Recommended regardless.)
2. Treat any backup `.tar` you download as sensitive, and keep your `/backup`
   share private.
3. After **restoring** a backup (especially onto a new machine), sign in to
   Proton again from the Web UI rather than relying on the restored session, and
   consider revoking old sessions from your Proton Account's security settings.

## When the Proton session expires, backups pause

While `enable_proton_upload` is on (the default) and the app is **not** signed
in to Proton, the destination counts as "not configured" and the app creates
**no new backups at all** — not even local Home Assistant ones. The session
normally survives restarts and upgrades, but it can lapse (you sign out, or
Proton invalidates it).

To warn you, the app (with `notify_for_stale_backups` on, the default) raises
a **prompt, dedicated notification** as soon as it detects this paused state —
"Proton Drive Backup is paused — sign in needed" — with a link to re-sign in. It
clears automatically once you're signed back in. The stale-backup sensor and
notification ship **on by default** too, as a longer-horizon safety net. To avoid
being caught out:

1. Leave `notify_for_stale_backups` and `enable_backup_stale_sensor` enabled, and
   optionally add an automation that alerts on `binary_sensor.backups_stale`.
2. Re-sign in from the Web UI's **Sign in** button when alerted (the paused
   notification links straight to it).
3. If you'd rather local backups keep running independently of Proton, either set
   `enable_proton_upload: false` (the app then manages Home Assistant backups
   only), or keep a separate Home Assistant scheduled-backup automation as a
   safety net.

## Limitations vs. the Google Drive app

- Authentication is interactive (a browser-based Proton sign-in) rather than
  OAuth. You start it from the Web UI's **Sign in** button.
- Only `amd64` and `aarch64` are supported (the Proton CLI ships only these).
- Proton Drive storage quota / free space is not surfaced in the UI.
