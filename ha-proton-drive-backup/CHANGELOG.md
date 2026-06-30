## v0.1.0 [2026-07-01]

Initial release of the Proton Drive port. (Supersedes all prior 0.1.0-0.2.12
pre-release iterations, which are summarized here rather than listed
individually since none were ever actually released.)

- Forked from [hassio-google-drive-backup](https://github.com/sabeechen/hassio-google-drive-backup)
  (MIT, © Stephen Beechen), replacing the Google Drive backend with a Proton
  Drive backend that drives the official `proton-drive` CLI.
- Per-backup metadata is stored in a sidecar `*.metadata.json` file next to each
  `*.tar` (Proton Drive has no file-property API).
- Authentication is done through the Web UI's **Sign in** button, which starts
  the browser sign-in flow; the container runs a headless secret service
  (D-Bus + gnome-keyring) and persists the session under `/data` so it
  survives restarts. While signed out, no backups are created (not even
  local ones), and the add-on raises an actionable "sign in to resume"
  notification.
- Debian-based image (the CLI is a glibc binary); supports `amd64` and
  `aarch64`. The downloaded `proton-drive` CLI is verified against a pinned
  per-architecture SHA256 at image build time.
- Rebuilt Web UI: modern, theme-aware single-page app with real-time status,
  sync activity, live upload progress, full settings editor, logs viewer and
  the Proton interactive sign-in flow.
- Reused unchanged: Home Assistant integration, scheduling, retention, and
  generational backup logic.
- Reliability: orphaned `.tar` files from interrupted uploads are reaped on
  the next sync; a disk-space pre-flight check fails fast instead of filling
  `/data` mid-write; upload errors surface their real cause (e.g. low disk
  space, not signed in, timeout) instead of a generic failure message; all
  `proton-drive` CLI invocations are serialized behind a lock so concurrent
  Web UI checks and syncs can't race the same session/keyring.
- Security: hardened the Proton folder name against CLI argument injection
  and `.`/`..` path traversal; sanitized the download filename in the
  `Content-Disposition` header; the metadata sidecar path is derived from the
  trusted remote filename rather than data inside the sidecar; the optional
  direct-access server enables `require_login` by default and is no longer
  published to the host by default; constant-time password comparison for
  direct-access login.
- Cleanup: removed all Google Drive branding, OAuth client identifiers, and
  "phone home" behavior (the upstream daily health check and anonymous error
  reporting against the original author's servers); removed unused legacy UI
  assets and dev/test files from the published image.
- Documentation: added a root README and MIT LICENSE, and documented that the
  Proton session stored under `/data` is captured inside full backups (with
  mitigation steps), plus the signed-out/no-backups behavior.
