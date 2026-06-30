#!/usr/bin/env python3
"""Tiny standalone dev server for previewing the web UI without a running
Home Assistant Supervisor.

It renders ``backup/static/index.jinja2`` and serves everything under
``backup/static`` at ``/static/<version>/...`` — exactly the path layout the
real add-on (``backup/ui/uiserver.py``) uses.

The UI runs entirely against the in-browser mock (``backup/static/app/mock.js``)
when opened with ``?mock=1``, so no backend API is needed here.

    python devserver.py            # then open http://localhost:8099/?mock=1
    python devserver.py 9000       # custom port

Pick any state from the floating "Mock states" panel (bottom-right), or jump
straight to one:  http://localhost:8099/?mock=1&scenario=uploading

Scenarios: normal, many, empty, syncing, uploading, pending, signed-out,
login-pending, cooldown, error-auth, error-multiple-deletes, error-low-space,
please-wait.
"""
import os
import sys
import http.server
import socketserver
from functools import partial

import jinja2

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "backup", "static")
VERSION = "dev"

_env = jinja2.Environment(loader=jinja2.FileSystemLoader(STATIC), autoescape=True)


def render_index() -> bytes:
    html = _env.get_template("index.jinja2").render(
        version=VERSION,
        backgroundColor="",   # empty -> UI defaults kick in
        accentColor="",
        coordEnabled=True,
        devMock=True,         # load mock.js so ?mock=1 works in the dev preview
    )
    return html.encode("utf-8")


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index", "/index.html"):
            body = render_index()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        prefix = "/static/%s/" % VERSION
        if path.startswith(prefix):
            rel = path[len(prefix):]
            full = os.path.normpath(os.path.join(STATIC, rel))
            if not full.startswith(STATIC) or not os.path.isfile(full):
                self.send_error(404)
                return
            ctype = self.guess_type(full)
            with open(full, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def log_message(self, fmt, *args):  # quieter output
        sys.stderr.write("  " + (fmt % args) + "\n")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    with socketserver.ThreadingTCPServer(("0.0.0.0", port), partial(Handler)) as httpd:
        httpd.allow_reuse_address = True
        print("Proton Drive Backup — UI dev preview")
        print("  open:  http://localhost:%d/?mock=1" % port)
        print("  (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nbye")


if __name__ == "__main__":
    main()
