#!/usr/bin/env python3
"""
Neutralise distrusted CA roots compiled into the proton-drive binary.

The CLI is a Bun executable whose TLS trust store is baked into the binary at
build time, and it never checks revocation.  Pointing it at the OS store
doesn't help: --use-openssl-ca and NODE_USE_SYSTEM_CA only ADD the system
roots to the bundled ones (verified against Bun 1.4.2 with the system store
hidden).  So a root that browsers and Debian have already dropped stays
trusted until Proton rebuilds the CLI on a patched Bun.

Patching rewrites the subject CN of each DISTRUSTED root in place, at the same
length, so no issuer name can match it any more and nothing chains to it.  The
DER structure and every byte offset in the file are unchanged.

Verifying runs the binary as plain Bun and checks the roots its TLS stack
actually trusts, which also catches a root the byte scan no longer recognises
(say, after Bun changes how it embeds them).

Usage:
  distrust_roots.py <binary>            patch the file in place
  distrust_roots.py --verify <binary>   check what the patched binary trusts
"""
import base64
import hashlib
import json
import mmap
import os
import re
import signal
import subprocess
import sys
import tempfile

# eMudhra intermediate CA key compromise, October 2026 (Mozilla's advisory,
# oss-security 2026-10-20): eight intermediates' private keys were
# recoverable.  They chain to the roots in DISTRUSTED and REVIEW_REQUIRED.

# SHA-256 fingerprint of the root's DER -> (its CN, same-length replacement).
DISTRUSTED = {
    # The six compromised TLS intermediates chain to this root.
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b":
        (b"emSign ECC Root CA - G3", b"DISTRUSTED by add-on G3"),
    # Removed from Mozilla's store in the same release (NSS 3.131.1, bug
    # 2083709), though not part of the key compromise.  The CLI only talks to
    # Proton, whose chain is Let's Encrypt, so it has no use for them.
    "125609aa301da0a249b97a8239cb6a34216f44dcac9f3954b14292f2e8c8608f":
        (b"emSign Root CA - C1", b"DISTRUSTED addon C1"),
    "bc4d809b15189d78db3e1d8cf4f9726a795da1643ca5f1358e1ddb0edc0d7eb3":
        (b"emSign ECC Root CA - C3", b"DISTRUSTED by add-on C3"),
}

# SHA-256 fingerprint -> CN of roots the compromised intermediates also chain
# to.  Bun's store doesn't carry them today; if a future CLI does, the build
# stops for a human decision rather than patching blindly (AAA Certificate
# Services also anchors legitimate Sectigo chains).
REVIEW_REQUIRED = {
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4": b"AAA Certificate Services",
    "7dd78d5f4f13459a83dff9abbba62edbaf6f2d102bf257fd712f4d9f2746ed8d": b"emSign Root TLS CA - G3",
}

# A DER certificate: SEQUENCE(long form) { SEQUENCE(long form) { [0] v3 ...
DER_CERT = re.compile(rb"\x30\x82(..)\x30\x82..\xa0\x03\x02\x01\x02", re.S)
# The body may not contain another BEGIN, so a stray header (say, in a string
# literal) can't swallow the real certificate that follows it.
PEM_CERT = re.compile(rb"-----BEGIN CERTIFICATE-----((?:(?!-----BEGIN).)+?)-----END CERTIFICATE-----", re.S)
# String types a CN can use; PrintableString's charset covers the replacements.
CN_STRING_TAGS = (0x13, 0x0c)  # PrintableString, UTF8String

# Bun's tls.rootCertificates is the store its TLS stack uses (it reflects the
# patched bytes).  Bun ships ~120 roots; far fewer means the list wasn't read.
ROOTS_JS = 'process.stdout.write(JSON.stringify(require("tls").rootCertificates))'
MIN_ROOTS = 50


def _fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def _review_error(name: bytes) -> ValueError:
    return ValueError("'{}' is embedded in the CLI; decide whether to distrust it and "
                      "update this script".format(name.decode()))


def _rename(der: bytes, old: bytes, new: bytes) -> bytes:
    assert len(old) == len(new)
    out = bytearray(der)
    start = 0
    renamed = 0
    while (i := der.find(old, start)) != -1:
        # Only touch a complete string value: tag, one-byte length, then the CN.
        if i >= 2 and der[i - 2] in CN_STRING_TAGS and der[i - 1] == len(old):
            out[i:i + len(old)] = new
            renamed += 1
        start = i + len(old)
    if not renamed:
        raise ValueError("root matched by fingerprint but its CN wasn't found")
    return bytes(out)


def plan(data, distrusted=DISTRUSTED, review_required=REVIEW_REQUIRED):
    """
    Return ([(offset, replacement bytes)], {fingerprint: copies found}).  `data`
    may be an mmap, so a ~100 MB binary is never copied into memory (a 1 GB
    Pi builds this image locally).
    """
    for m in PEM_CERT.finditer(data):
        body = m.group(1).replace(b"\\n", b"")
        try:
            der = base64.b64decode(b"".join(body.split()), validate=True)
        except ValueError:
            continue
        fp = _fingerprint(der)
        if fp in review_required:
            raise _review_error(review_required[fp])
        if fp in distrusted:
            raise ValueError("a distrusted root is embedded as PEM; only the DER "
                             "form is handled, so update this script")
    edits = []
    found = {fp: 0 for fp in distrusted}
    for m in DER_CERT.finditer(data):
        end = m.start() + int.from_bytes(m.group(1), "big") + 4
        der = bytes(data[m.start():end])
        fp = _fingerprint(der)
        if fp in review_required:
            raise _review_error(review_required[fp])
        if fp in distrusted:
            edits.append((m.start(), _rename(der, *distrusted[fp])))
            found[fp] += 1
    return edits, found


def patch(data: bytes, distrusted=DISTRUSTED, review_required=REVIEW_REQUIRED):
    """Return (patched copy of data, {fingerprint: copies neutralised})."""
    edits, found = plan(data, distrusted, review_required)
    out = bytearray(data)
    for offset, new in edits:
        out[offset:offset + len(new)] = new
    return bytes(out), found


def verify(binary: str, distrusted=DISTRUSTED, review_required=REVIEW_REQUIRED,
           minimum: int = MIN_ROOTS) -> None:
    """Raise unless the binary's live trust store excludes every listed root."""
    # Absolute, since it runs from an empty directory.
    binary = os.path.abspath(binary)
    with tempfile.TemporaryDirectory() as home:
        # A bare environment (no session bus, so nothing can touch a keyring)
        # in an empty directory: Bun loads .env and bunfig.toml preloads from
        # the working directory, and a preload could fake the root list.
        env = {"PATH": "/usr/bin:/bin", "HOME": home, "TMPDIR": home, "BUN_BE_BUN": "1"}
        proc = subprocess.run([binary, "-e", ROOTS_JS], env=env, cwd=home,
                              capture_output=True, timeout=120)
    if proc.returncode == -signal.SIGILL:
        # This CPU lacks instructions the CLI needs, so it can't run (or trust
        # anything) here; the add-on reports that at runtime.  Any other
        # signal (a crash, the OOM killer) is a real failure.
        print("distrust_roots: skipped verification: {} can't run on this CPU (SIGILL)".format(binary))
        return
    if proc.returncode < 0:
        raise ValueError("the CLI was killed by signal {} while listing its trusted roots".format(
            -proc.returncode))
    if proc.returncode != 0:
        raise ValueError("couldn't list the CLI's trusted roots (exit {}): {}".format(
            proc.returncode, proc.stderr.decode("utf-8", "replace")[-300:]))
    pems = json.loads(proc.stdout)
    if len(pems) < minimum:
        raise ValueError("the CLI reported only {} trusted roots; expected at least {}".format(
            len(pems), minimum))
    # Collect every hit rather than stopping at the first, so a run on an
    # unpatched CLI shows exactly which roots it still ships.
    trusted = set()
    for pem in pems:
        der = base64.b64decode("".join(line for line in pem.splitlines() if not line.startswith("-----")))
        fp = _fingerprint(der)
        for bad_fp, (name, _) in distrusted.items():
            # By name too: a re-encoded copy has a new fingerprint.
            if fp == bad_fp or name in der:
                trusted.add(name.decode())
        for bad_fp, name in review_required.items():
            if fp == bad_fp or name in der:
                raise _review_error(name)
    if trusted:
        raise ValueError("still trusted by the CLI: {}".format(
            ", ".join("'{}'".format(name) for name in sorted(trusted))))
    print("distrust_roots: verified the CLI's {} trusted roots".format(len(pems)))


def main(path: str) -> int:
    # Patch through a shared mapping: only the changed bytes are written, and
    # the file's pages stay reclaimable page cache rather than process memory.
    with open(path, "r+b") as f, mmap.mmap(f.fileno(), 0) as data:
        edits, found = plan(data)
        for offset, new in edits:
            data[offset:offset + len(new)] = new
        data.flush()
    for fp, count in found.items():
        name = DISTRUSTED[fp][0].decode()
        if count:
            print("distrust_roots: neutralised {} embedded cop{} of '{}'".format(
                count, "y" if count == 1 else "ies", name))
        else:
            print("distrust_roots: '{}' isn't embedded; nothing to do".format(name))
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--verify":
        verify(sys.argv[2])
        sys.exit(0)
    if len(sys.argv) != 2 or sys.argv[1].startswith("-"):
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
