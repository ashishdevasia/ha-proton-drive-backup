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
    i18n.js           translations: picks the language, loads locales/, t()
    locales/          one JSON catalog per language (en.json is the reference)
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
  There is no light/dark setting: `backup/theme.py` measures the two colours,
  and `index.jinja2` sets `data-theme="light"` for a light background (the
  light palette is the "Light theme" section of `app.css`) and `--user-on-accent` to
  dark text for a light accent. New colours belong in a variable that both
  palettes define. Preview with `devserver.py`: `?mock=1&bg=f4ead9&accent=e0b030`.

## Proton specifics

- Sign-in is the interactive Proton CLI flow (not OAuth): `POST /protonlogin`
  returns a link, the UI shows it (and polls `/getstatus` for
  `proton_authenticated`). The link contains a secret `#payload=` fragment, so
  it is only ever placed in an `<a href>` / `textContent` (never `innerHTML`,
  never logged) and uses `rel="noopener"`.
- No Google folder picker and no free-space UI (Proton has neither).

## Translations

Every string the UI shows comes from `locales/<lang>.json` through `t(key,
params)` (`i18n.js`). The UI ships English, German, Spanish, French, Italian,
Dutch, Polish, Brazilian Portuguese, Czech, Swedish, Ukrainian and Malayalam.
Most were written without a native speaker's review: corrections are welcome.

**Which language.** The first match wins:
1. `?lang=xx`, for previews (`devserver.py`: `?mock=1&lang=ml`).
2. The Home Assistant user's language. Ingress shows this page in a
   same-origin iframe, and Home Assistant sets its own `<html lang>` to the
   user's profile language. The extra server is a different origin, so this
   step is skipped there.
3. The browser's languages.
4. English.

Matching is by exact code, then by base language (`fr-CA` → `fr`), then by any
variant of the same language (`pt` → `pt-BR`).

**Catalogs.** Keys are flat and dotted, grouped by area (`dashboard.*`,
`toast.*`, …). Text is interpolated as `{name}`. A plural message is an object
of CLDR forms (`{"one": …, "other": …}`) picked from `params.n`. Keys a
translation lacks fall back to English. Some keys are built at runtime:
- `setting.<option>.label` / `.help` / `.placeholder`: the settings form
  (`SETTINGS_GROUPS` holds only keys and types).
- `settings.group.<id>.title` / `.desc` and `tab.<id>`.
- `error.<error_type>.title` / `.message`: backend errors whose message is
  fixed text, filled from the error's `data`. Errors with dynamic text show
  the backend's English message.

Only `*_html` keys are rendered as HTML (`I18n.tHtml`, `<b>` only, every
parameter escaped). Everything else is set as text.

**What stays English:** text the backend writes that has no fixed form. That
covers Proton CLI output (`proton_auth_warning`, `proton_login_error`), dynamic
error messages, backup names, sizes, and the add-on log. Dates are rendered
here from the epoch fields (`*_timestamp`), in Home Assistant's time zone
(`time_zone`).

**Adding a language** (use Home Assistant's language code, e.g. `de`, `pt-BR`):
1. Copy `locales/en.json` to `locales/<code>.json` and translate the values.
   Write it the way people actually talk about apps in that language, not in
   dictionary terms: the Malayalam says ബാക്കപ്പ്, സെറ്റിങ്സ്, ഡൗൺലോഡ്, not
   മറുപകർപ്പ്, ക്രമീകരണങ്ങൾ, കീഴിറക്കുക. When the text names one of Home
   Assistant's own menus, use the label Home Assistant shows in that language.
   Keep the keys and `{placeholders}`, and the plural objects. Example values
   that people type into a field must still parse. Durations accept English
   units only ("30 days", "3h"), so keep those in English with a note, as fr
   and ml do.
2. Add `translations/<code>.yaml` (the add-on's Configuration tab in Home
   Assistant), covering every option in `config.json`.
3. Add the code to `SUPPORTED` in `i18n.js`.

`tests/test_translations.py` checks that every language has both files with
the same keys and placeholders, and that the keys `app.js` uses exist.

## Backend changes

Everything the UI shows comes from the existing `/getstatus` payload and route
contract: sync activity, upload progress, pending creation, cooldown, errors and
please-wait. For translations, `/getstatus` also sends:
- `next_backup_timestamp` / `last_backup_timestamp` and
  `upload_info.started_timestamp`, in epoch seconds.
- `now_timestamp`, the add-on's clock, so relative times ("5 minutes ago")
  don't depend on the viewer's clock being right.
- `time_zone`, the IANA name of the add-on's zone.

The existing English text fields are unchanged, for API scripts.

## Previewing every state (dev mock)

`mock.js` is **dev-only**: the production add-on (`uiserver.py`) does not include
it, so `?mock=1` does nothing there. Only `devserver.py` renders the template
with `devMock=True`, which loads the stub:

```
python devserver.py            # open http://localhost:8099/?mock=1
                               # add &lang=fr or &lang=ml for another language
```

With `mock.js` loaded, `?mock=1` makes it intercept the API and serve sample
data. Use the floating **Mock states** panel (bottom-right), or deep-link a state:

```
?mock=1&scenario=uploading
```

Scenarios: `normal`, `many`, `empty`, `syncing`, `uploading`, `pending`,
`signed-out`, `login-pending`, `cooldown`, `error-auth`,
`error-multiple-deletes`, `error-low-space`, `please-wait`.
