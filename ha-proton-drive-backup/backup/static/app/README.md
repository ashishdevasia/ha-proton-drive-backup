# Web UI

Modern, theme-aware single-page UI for the Proton Drive Backup add-on. It is
served inside Home Assistant ingress by the existing aiohttp server
(`backup/ui/uiserver.py`), which renders `backup/static/index.jinja2` as the
entry point.

## Toolchain: none (zero build)

This UI is **vanilla JS + CSS** with **no build step** and **no runtime CDN**.
Everything is committed and served from `backup/static/`:

```
backup/static/
  index.jinja2        entry; injects theme colors + version, loads the app
  app/
    app.css           all styles (dark-first glassmorphism, theme-driven)
    app.js            the SPA (polling, views, modals, actions)
    mock.js           in-browser dev mock (only active with ?mock=1)
    README.md         this file
```

Why no framework: the add-on must run fully offline on low-resource hardware,
so the UI uses the system font stack and inline SVG icons (no web fonts, no
icon font, no npm). Just edit the files — there is nothing to compile.

## How it works

- All network calls and links are built **relative to
  `window.location.pathname`** so the UI works under the opaque Home Assistant
  ingress path prefix (never hard-codes `/`).
- It is a single page driven entirely by polling `GET /getstatus`. The poll
  interval adapts: ~1.5s while syncing/uploading/creating, ~2s while a Proton
  login is pending, ~10s when idle.
- Static assets are served at `/static/<VERSION>/app/...`; `index.jinja2`
  references them via the injected `{{ version }}`.
- Theme: `background_color` / `accent_color` from the add-on config are inlined
  into CSS variables (`--user-bg` / `--user-accent`) with sensible defaults.

## Proton specifics

- Sign-in is the interactive Proton CLI flow (not OAuth): `POST /protonlogin`
  returns a link, the UI shows it (and polls `/getstatus` for
  `proton_authenticated`). The link contains a secret `#payload=` fragment, so
  it is only ever placed in an `<a href>` / `textContent` (never `innerHTML`,
  never logged) and uses `rel="noopener"`.
- No Google folder picker and no free-space UI (Proton has neither).

## Backend changes

**None.** No changes were made to `backup/ui/uiserver.py` or any other backend
file. Every real-time state the UI shows (sync activity, upload progress,
pending creation, cooldown, errors, please-wait) is derived from the existing
`/getstatus` payload and route contract.

## Previewing every state (dev mock)

`mock.js` is **dev-only**: the production add-on (`uiserver.py`) does not include
it, so `?mock=1` does nothing there. Only `devserver.py` renders the template
with `devMock=True`, which loads the stub:

```
python devserver.py            # open http://localhost:8099/?mock=1
```

With `mock.js` loaded, `?mock=1` makes it intercept the API and serve sample
data. Use the floating **Mock states** panel (bottom-right), or deep-link a state:

```
?mock=1&scenario=uploading
```

Scenarios: `normal`, `many`, `empty`, `syncing`, `uploading`, `pending`,
`signed-out`, `login-pending`, `cooldown`, `error-auth`,
`error-multiple-deletes`, `error-low-space`, `please-wait`.
