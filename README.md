# Home Assistant Proton Drive Backup

A Home Assistant app (add-on) repository that automatically creates Home Assistant
backups and keeps copies of them in your end-to-end encrypted
[Proton Drive](https://proton.me/drive).

It is a Proton Drive port of the excellent
[Home Assistant Google Drive Backup](https://github.com/sabeechen/hassio-google-drive-backup)
app by Stephen Beechen (MIT licensed). The scheduling, retention,
generational backup, and Home Assistant integration logic is reused unchanged;
only the storage backend has been replaced.

> **This is a third-party application not officially supported by Proton.** It is
> an unofficial project and is not affiliated with, endorsed by, or operated by
> Proton AG. "Proton" and "Proton Drive" are trademarks of Proton AG, used here
> only to describe interoperability.

## Installation

1. In Home Assistant, go to **Settings → Apps → App Store** (called
   **Settings → Add-ons → Add-on Store** on older Home Assistant versions).
2. Open the **⋮** menu (top right) → **Repositories**, and add:

   ```
   https://github.com/ashishdevasia/ha-proton-drive-backup
   ```

3. Install **Home Assistant Proton Drive Backup** from the store and start it.
4. Open the Web UI and click **Sign in** to authenticate with Proton Drive.

[![Add repository to your Home Assistant instance.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fashishdevasia%2Fha-proton-drive-backup)

## Documentation

The app and its full documentation live in
[`ha-proton-drive-backup/`](ha-proton-drive-backup/):

- [App overview](ha-proton-drive-backup/README.md)
- [Configuration / options](ha-proton-drive-backup/DOCS.md)
- [Authentication](ha-proton-drive-backup/AUTHENTICATION.md)
- [Backups & snapshots](ha-proton-drive-backup/BACKUP_AND_SNAPSHOT.md)
- [Generational backups](ha-proton-drive-backup/GENERATIONAL_BACKUP.md)
- [Changelog](ha-proton-drive-backup/CHANGELOG.md)

## How it differs from the Google Drive app

Proton Drive has **no public API** — it is end-to-end encrypted and the only
supported integration is the official
[`proton-drive` CLI](https://proton.me/support/drive-cli), which the app
bundles. As a result:

- Authentication is an interactive browser sign-in (with 2FA), not OAuth.
- Per-backup metadata is stored in a sidecar `*.metadata.json` file next to each
  archive, since Proton Drive has no file-property API.
- Only `aarch64` and `amd64` are supported (the CLI only ships these).

## License

MIT. Derived from
[sabeechen/hassio-google-drive-backup](https://github.com/sabeechen/hassio-google-drive-backup)
(© Stephen Beechen). See [LICENSE](LICENSE).
