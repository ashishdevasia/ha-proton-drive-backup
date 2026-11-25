# Security policy

## Reporting a vulnerability

Please don't report security problems in public issues, pull requests or
discussions. Report them privately on GitHub instead:
[**Report a vulnerability**](https://github.com/ashishdevasia/ha-proton-drive-backup/security/advisories/new)
(or the Security tab, then **Report a vulnerability**).

Please include:

- what you found and what an attacker could do with it
- how to reproduce it
- the add-on version you tested

I'll reply as soon as I can. The report stays private while it's being
handled. If it leads to a published advisory, you'll be credited unless you'd
rather not be.

## Supported versions

Fixes go into the latest release only. Update the app under **Settings → Apps**
(**Settings → Add-ons** on older Home Assistant versions).

## What's in scope

The code in this repository: the add-on's web UI and API (through ingress and
the optional extra port), `run.sh`, the Docker image, and how the add-on stores
and uses the Proton session.

Report problems in other projects to them directly:

- The Proton Drive CLI or Proton's servers: [Proton's bug bounty](https://proton.me/security/bug-bounty)
- Home Assistant itself: [Home Assistant security](https://www.home-assistant.io/security/)

## Known limits

These are documented trade-offs, not vulnerabilities:

- The Proton session is stored under `/data`, and full backups include `/data`,
  so the backups this add-on creates and uploads contain the session. Set
  `backup_password` to encrypt them. See the
  [security note in DOCS.md](https://github.com/ashishdevasia/ha-proton-drive-backup/blob/main/ha-proton-drive-backup/DOCS.md#security-note-your-proton-session-lives-in-data-and-is-captured-by-backups).
- The keyring key sits next to the keyring in `/data`. It keeps the session
  from being stored in plain text, but anyone who can read `/data` can unlock
  it. See [AUTHENTICATION.md](https://github.com/ashishdevasia/ha-proton-drive-backup/blob/main/ha-proton-drive-backup/AUTHENTICATION.md#security-notes).
