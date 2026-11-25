# Contributing

Thanks for helping out! Bug reports, translation fixes and pull requests are
all welcome.

## Branches

- `main` is what Home Assistant installs, so it only changes when there's a
  release.
- `dev` collects changes for the next release. **Please open pull requests
  against `dev`.**

You don't need to edit `CHANGELOG.md` or bump the version. That's done when a
release is made.

## Reporting problems

- **Bugs:** use the [bug report form](https://github.com/ashishdevasia/ha-proton-drive-backup/issues/new?template=bug_report.yml).
  The add-on's web UI can build most of the report for you: open **About**,
  then **Create a bug report**.
- **Security problems:** report them privately, as described in
  [SECURITY.md](https://github.com/ashishdevasia/ha-proton-drive-backup/blob/main/.github/SECURITY.md).
- **Questions:** ask in [Discussions](https://github.com/ashishdevasia/ha-proton-drive-backup/discussions).
- **Feature requests and translation fixes:** open a
  [blank issue](https://github.com/ashishdevasia/ha-proton-drive-backup/issues/new),
  or send a pull request.

## Running the tests

The add-on runs on Python 3.11 (the Debian bookworm image), so 3.11 is the
closest match, but the tests also pass on 3.12 and 3.14. From the repository
root:

```bash
python3.11 -m venv .venv    # no Python 3.11? uv venv --seed --python 3.11 .venv
. .venv/bin/activate
cd ha-proton-drive-backup
pip install --require-hashes -r requirements-addon.lock
pip install -r requirements-dev.txt
python -m pytest
shellcheck run.sh           # if you changed run.sh
```

Every pull request runs the tests and `shellcheck` on GitHub. For a
first-time contributor, the run starts once a maintainer approves it.

## Making changes

- **Web UI:** there's no build step. See the
  [web UI README](https://github.com/ashishdevasia/ha-proton-drive-backup/blob/main/ha-proton-drive-backup/backup/static/app/README.md)
  for how it works and how to preview every state with `devserver.py`.
- **Translations:** see
  [Translations](https://github.com/ashishdevasia/ha-proton-drive-backup/blob/main/ha-proton-drive-backup/backup/static/app/README.md#translations)
  in the web UI README. Write the way people actually talk about apps in that
  language. `tests/test_translations.py` checks that every language has the
  same keys and placeholders.
- **Dependencies:** `requirements-addon.txt` pins each package. After changing
  it, regenerate `requirements-addon.lock` by running the `uv` command at the
  top of that file from `ha-proton-drive-backup/`. A test checks that the two
  match.
- **Line endings:** a few Python files (for example
  `backup/config/config.py`) use CRLF line endings. Keep each file's line
  endings as they are, so the diff only shows your change.
- **Secrets:** never put credentials, Proton sign-in links or session data in
  code, tests, logs or screenshots.

## Testing in Home Assistant

The tests can't cover the real add-on: the keyring, the Proton Drive CLI and
the Supervisor API. For changes to those parts, please also run your branch as
a [local app](https://contributors.home-assistant.io/apps/guides/testing/)
and say in the pull request what you checked. If you can't test it that way,
say so in the pull request.
