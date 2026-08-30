# Home Assistant App (Add-on): Proton Drive Backup

Automatically create Home Assistant backups and keep copies of them in your
end-to-end encrypted [Proton Drive](https://proton.me/drive).

This app (add-on) is a Proton Drive port of the excellent
[Home Assistant Google Drive Backup](https://github.com/sabeechen/hassio-google-drive-backup)
app by Stephen Beechen (MIT licensed). All of the scheduling, retention,
generational backup, and Home Assistant integration logic is reused; only the
storage backend has been replaced.

> **This is a third-party application not officially supported by Proton.** It is
> an unofficial project and is not affiliated with, endorsed by, or operated by
> Proton AG. "Proton" and "Proton Drive" are trademarks of Proton AG, used here
> only to describe interoperability.

## How it differs from the Google Drive app

Proton Drive has **no public API** — it is end-to-end encrypted and the only
supported integration is the official
[`proton-drive` CLI](https://proton.me/support/drive-cli). That leads to a few
deliberate differences from the original app:

| | Google Drive app | This app |
|---|---|---|
| Backend | Google Drive REST API | `proton-drive` CLI (bundled in the image) |
| Auth | OAuth via a hosted server | interactive browser sign-in from the Web UI |
| Per-backup metadata | Drive file `appProperties` | a sidecar `*.metadata.json` file |
| Architectures | armhf/armv7/aarch64/amd64/i386 | aarch64/amd64 (the CLI only ships these) |

Because the CLI works on local files (it can't stream), uploads/downloads are
staged through a temp file under `/data/proton/tmp`.

## Installation

1. Add this repository to the Home Assistant app store (add-on store).
2. Install **Home Assistant Proton Drive Backup** and start it.
3. Open the Web UI. It will report that Proton Drive is **Not signed in**.

## Authenticating with Proton Drive

Sign-in is interactive (browser based) and only has to be done once — the
session is stored in a keyring under `/data` and survives restarts and upgrades.
2-factor authentication is fully supported (it happens on Proton's web login).

1. Open the app's Web UI and click **Sign in**.
2. Open the Proton sign-in link it shows (on any device) and complete sign-in,
   including 2FA if enabled.
3. Leave the Web UI open — it flips to **Signed in** automatically and starts
   syncing.

See [AUTHENTICATION.md](AUTHENTICATION.md) for details on how the headless
secret service works.

## Configuration

The options mirror the original app. The Proton-specific ones are:

| Option | Default | Description |
|---|---|---|
| `max_backups_in_proton_drive` | `4` | How many backups to keep in Proton Drive. |
| `enable_proton_upload` | `true` | Upload backups to Proton Drive. |
| `proton_folder_name` | `Home Assistant Backups` | Folder created under `/my-files`. Use `/` to nest, e.g. `backups/ha`. The app manages this folder, so give it one of its own. |
| `proton_cli_path` | `/usr/bin/proton-drive` | Path to the bundled CLI binary. |
| `proton_data_path` | `/data/proton` | Where the CLI session/keyring/temp live. |
| `proton_drive_timeout_seconds` | `180` | Timeout for metadata/list operations. |
| `proton_transfer_timeout_seconds` | `3600` | Timeout for uploads/downloads. |

See [DOCS.md](DOCS.md) for the full option list.

## License

MIT. Derived from
[sabeechen/hassio-google-drive-backup](https://github.com/sabeechen/hassio-google-drive-backup)
(© Stephen Beechen), see [LICENSE](LICENSE).
