import base64
import hashlib
import json
import re

import pytest

import distrust_roots
from distrust_roots import patch, DISTRUSTED

# The real "emSign ECC Root CA - G3" (public; as embedded in proton-drive 0.9.0).
EMSIGN_ECC_G3 = base64.b64decode("""
MIICTjCCAdOgAwIBAgIKPPYHqWhwDtqLhDAKBggqhkjOPQQDAzBrMQswCQYDVQQG
EwJJTjETMBEGA1UECxMKZW1TaWduIFBLSTElMCMGA1UEChMcZU11ZGhyYSBUZWNo
bm9sb2dpZXMgTGltaXRlZDEgMB4GA1UEAxMXZW1TaWduIEVDQyBSb290IENBIC0g
RzMwHhcNMTgwMjE4MTgzMDAwWhcNNDMwMjE4MTgzMDAwWjBrMQswCQYDVQQGEwJJ
TjETMBEGA1UECxMKZW1TaWduIFBLSTElMCMGA1UEChMcZU11ZGhyYSBUZWNobm9s
b2dpZXMgTGltaXRlZDEgMB4GA1UEAxMXZW1TaWduIEVDQyBSb290IENBIC0gRzMw
djAQBgcqhkjOPQIBBgUrgQQAIgNiAAQjpQy4LRL1KPOxst3iAhKAnjlfSU2fySU0
WXTsuwYc58Byr+iuL+FBVIcUqEqy6HyC5ltqtdyzdc6LBtCGI79G1Y4PPwT01xyS
fvalY8L1X44uT6EYGQIrMgqCZH0Wk9GjQjBAMB0GA1UdDgQWBBR8XQKEE9TMipuB
zhccLikenEhjQjAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0TAQH/BAUwAwEB/zAKBggq
hkjOPQQDAwNpADBmAjEAvvNhzwIQHWSVB7gYboiFBS+DCBeQyh+KTOgNG3qxrdWB
CUfvO6wIBHxcmbHtRwfSAjEAnbpV/KlK6O3t5nYBQnvI+GDZjVGLVTv7jHvrZQnD
+JbNR6iC8hZVdyR+EhCVBCyj
""")
FINGERPRINT = hashlib.sha256(EMSIGN_ECC_G3).hexdigest()


def test_fixture_is_the_distrusted_root():
    assert FINGERPRINT in DISTRUSTED


@pytest.mark.parametrize("fingerprint", sorted(DISTRUSTED))
def test_replacement_names_fit_in_place(fingerprint):
    # Same length keeps every DER length byte and file offset valid; the
    # PrintableString charset keeps the patched certificate parseable.
    old, new = DISTRUSTED[fingerprint]
    assert len(new) == len(old) and new != old
    assert re.fullmatch(rb"[A-Za-z0-9 '()+,\-./:=?]+", new)


def test_patches_der_root_in_place():
    blob = b"\x00" * 100 + EMSIGN_ECC_G3 + b"tail" * 10
    patched, counts = patch(blob)
    assert counts[FINGERPRINT] == 1
    assert len(patched) == len(blob)
    # Only the CN changed: issuer and subject both renamed, nothing else.
    old, new = DISTRUSTED[FINGERPRINT]
    assert patched.count(old) == 0
    assert patched.count(new) == 2
    assert patched[:100] == blob[:100] and patched.endswith(b"tail" * 10)
    # The root is no longer recognisable, so a second pass is a no-op.
    again, counts = patch(patched)
    assert again == patched and counts[FINGERPRINT] == 0


def test_absent_root_is_a_noop():
    blob = b"no certificates in here" * 50
    patched, counts = patch(blob)
    assert patched == blob
    assert counts[FINGERPRINT] == 0


def test_pem_embedded_root_fails_loudly():
    # Bun 1.3 embedded its roots as PEM; silently skipping that form would leave
    # the root trusted, so the build must stop instead.
    pem = (b"-----BEGIN CERTIFICATE-----\n"
           + base64.encodebytes(EMSIGN_ECC_G3)
           + b"-----END CERTIFICATE-----\n")
    with pytest.raises(ValueError, match="PEM"):
        patch(b"junk" + pem + b"junk")


def test_stray_pem_header_doesnt_hide_a_root():
    # A lone BEGIN line (a string literal in the CLI's own code) must not run
    # on into the real certificate after it and hide it from the PEM check.
    pem = (b"-----BEGIN CERTIFICATE-----\n"
           + base64.encodebytes(EMSIGN_ECC_G3)
           + b"-----END CERTIFICATE-----\n")
    with pytest.raises(ValueError, match="PEM"):
        patch(b'"-----BEGIN CERTIFICATE-----";\x00' + pem)


def test_main_rewrites_file(tmp_path, capsys):
    path = tmp_path / "proton-drive"
    path.write_bytes(b"\x7fELF" + EMSIGN_ECC_G3)
    assert distrust_roots.main(str(path)) == 0
    assert DISTRUSTED[FINGERPRINT][1] in path.read_bytes()
    assert "neutralised 1 embedded copy" in capsys.readouterr().out


def test_review_required_root_stops_the_patch():
    # A root listed for review must stop the build, not be patched or skipped.
    with pytest.raises(ValueError, match="decide whether to distrust"):
        patch(b"junk" + EMSIGN_ECC_G3, distrusted={},
              review_required={FINGERPRINT: b"emSign ECC Root CA - G3"})


# --- verify(): runs the binary (as plain Bun) and checks its live trust store --

def _pem(der):
    return ("-----BEGIN CERTIFICATE-----\n" + base64.encodebytes(der).decode()
            + "-----END CERTIFICATE-----\n")


PATCHED_G3 = patch(EMSIGN_ECC_G3)[0]


def fake_cli(tmp_path, roots=None, script=None):
    """An executable that prints `roots` like Bun's tls.rootCertificates."""
    if script is None:
        (tmp_path / "roots.json").write_text(json.dumps(roots))
        script = '[ "$BUN_BE_BUN" = 1 ] || exit 3\ncat "{}"\n'.format(tmp_path / "roots.json")
    path = tmp_path / "proton-drive"
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(0o755)
    return str(path)


def test_verify_passes_once_patched(tmp_path, capsys):
    distrust_roots.verify(fake_cli(tmp_path, [_pem(PATCHED_G3)] * 60))
    assert "verified the CLI's 60 trusted roots" in capsys.readouterr().out


def test_verify_fails_while_root_is_trusted(tmp_path):
    with pytest.raises(ValueError, match="still trusted"):
        distrust_roots.verify(fake_cli(tmp_path, [_pem(PATCHED_G3)] * 59 + [_pem(EMSIGN_ECC_G3)]))


def test_verify_lists_every_root_still_trusted(tmp_path):
    # So a maintainer can tell which DISTRUSTED entries a new CLI still needs.
    c1 = b"\x30\x82 emSign Root CA - C1 "  # matched by name
    roots = [_pem(PATCHED_G3)] * 58 + [_pem(EMSIGN_ECC_G3), _pem(c1)]
    with pytest.raises(ValueError) as e:
        distrust_roots.verify(fake_cli(tmp_path, roots))
    message = str(e.value)
    assert "emSign ECC Root CA - G3" in message and "emSign Root CA - C1" in message
    assert "C3" not in message


def test_verify_catches_a_reencoded_copy_by_name(tmp_path):
    # Different bytes (so a new fingerprint) but the same distrusted name.
    reencoded = EMSIGN_ECC_G3[:-1] + bytes([EMSIGN_ECC_G3[-1] ^ 1])
    with pytest.raises(ValueError, match="still trusted"):
        distrust_roots.verify(fake_cli(tmp_path, [_pem(PATCHED_G3)] * 59 + [_pem(reencoded)]))


def test_verify_fails_on_review_required_root(tmp_path):
    with pytest.raises(ValueError, match="decide whether to distrust"):
        distrust_roots.verify(fake_cli(tmp_path, [_pem(EMSIGN_ECC_G3)] * 60), distrusted={},
                              review_required={FINGERPRINT: b"emSign ECC Root CA - G3"})


def test_verify_fails_when_roots_look_unread(tmp_path):
    with pytest.raises(ValueError, match="only 3 trusted roots"):
        distrust_roots.verify(fake_cli(tmp_path, [_pem(PATCHED_G3)] * 3))


def test_verify_fails_when_bun_mode_is_ignored(tmp_path):
    # e.g. a future CLI that no longer honours BUN_BE_BUN and treats -e as an argument.
    with pytest.raises(ValueError, match="exit 1"):
        distrust_roots.verify(fake_cli(tmp_path, script="echo 'unknown option -e' >&2\nexit 1\n"))


def test_verify_skips_when_the_cpu_cant_run_the_cli(tmp_path, capsys):
    # A CLI killed by SIGILL can't make TLS connections here at all; the build
    # shouldn't fail, the add-on reports it at runtime.
    distrust_roots.verify(fake_cli(tmp_path, script="kill -ILL $$\n"))
    assert "skipped verification" in capsys.readouterr().out


@pytest.mark.parametrize("sig", ["SEGV", "ABRT", "KILL"])
def test_verify_fails_on_other_signals(tmp_path, sig):
    # A crash or the OOM killer isn't "this CPU can't run it": don't pass the
    # build on an unverified CLI.
    with pytest.raises(ValueError, match="killed by signal"):
        distrust_roots.verify(fake_cli(tmp_path, script="kill -{} $$\n".format(sig)))


def test_verify_runs_in_an_empty_directory(tmp_path, monkeypatch):
    # Bun loads .env / bunfig.toml preloads from its working directory.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "roots.json").write_text(json.dumps([_pem(PATCHED_G3)] * 60))
    script = '[ "$PWD" = "$HOME" ] && [ -z "$(ls -A)" ] || exit 4\ncat "{}"\n'.format(tmp_path / "roots.json")
    distrust_roots.verify(fake_cli(tmp_path, script=script))


@pytest.mark.parametrize("relative", ["proton-drive", "./proton-drive"])
def test_verify_accepts_a_relative_path(tmp_path, monkeypatch, capsys, relative):
    fake_cli(tmp_path, [_pem(PATCHED_G3)] * 60)
    monkeypatch.chdir(tmp_path)
    distrust_roots.verify(relative)
    assert "verified" in capsys.readouterr().out
