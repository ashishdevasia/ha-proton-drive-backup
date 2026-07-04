# Authentication

> **This is a third-party application not officially supported by Proton.** Your
> Proton password and 2FA codes are entered only on Proton's own web sign-in
> page — the app never sees or stores them.

This app (add-on) signs in to Proton Drive through the official `proton-drive`
CLI. Unlike the Google Drive app there is no OAuth token, no hosted auth server,
and nothing to copy and paste into the Web UI.

## Why a keyring is involved

The `proton-drive` CLI stores its session in the operating system's secret store
— on Linux that is **libsecret** (the Secret Service API, normally backed by
GNOME Keyring). A bare container has no secret service running, which is why a
fresh CLI invocation prints:

```
Failed to load session from secrets ... libsecret not available
```

To make the CLI usable inside a headless app, the container's entrypoint
([`run.sh`](run.sh)) does the following on startup:

1. Starts a private **D-Bus** session (`dbus-run-session`).
2. Starts **gnome-keyring** with only the `secrets` component, which provides the
   Secret Service that libsecret talks to.
3. Unlocks the keyring with a key stored at `/data/proton/keyring.key`
   (generated once, on first run).
4. Points `HOME` / `XDG_DATA_HOME` at `/data/proton` so the keyring storage and
   the CLI session live on the app's persistent volume.

Because everything is anchored under `/data`, you only authenticate **once** —
the session survives app restarts and upgrades.

## Signing in

1. Open the app's Web UI. While signed out it shows a **Sign in** button.
2. Click **Sign in**. The app starts the Proton sign-in for you and shows
   the Proton sign-in link it produces.
3. Open that link in any browser — it can be a different device, e.g. your phone —
   and complete sign-in, **including 2-factor authentication** if your account
   has it enabled. (2FA is handled entirely by Proton's web login; the app
   never sees your password or codes.)
4. Leave the Web UI open. It polls in the background and flips to **Signed in**
   automatically once the browser sign-in completes; a backup sync then starts.

Behind the scenes the CLI prints a line like:

```
Open following URL manually (can be on another device) if browser did not open automatically:
https://account.proton.me/desktop/login?app=drive&pv=3#payload=...
```

The app captures that URL and surfaces it as the **Sign in** link. The
`#payload=...` fragment is a short-lived sign-in token — treat the link as
sensitive and don't share it.

## Verifying / re-checking

- The Web UI calls `proton-drive filesystem info /my-files` under the hood to
  determine whether a usable session exists; the **Re-check** button re-runs
  this.

## Security notes

- The keyring key in `/data/proton/keyring.key` only protects the Proton session
  at rest inside the app's already-private `/data` volume. Treat a backup of
  `/data` as sensitive — it effectively contains your Proton Drive session.
- The app never sees or stores your Proton password; sign-in happens entirely
  in your browser against Proton's servers.
