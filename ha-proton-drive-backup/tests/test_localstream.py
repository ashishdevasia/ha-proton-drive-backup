import os

import pytest

from backup.proton.localstream import LocalFileStream
from backup.proton.protonsource import _SelfCleaningStream
from backup.time import Time


def make_file(tmp_path, data: bytes, name="x.tar"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


async def test_reads_all_bytes_via_iteration(tmp_path):
    path = make_file(tmp_path, b"0123456789" * 10)
    stream = LocalFileStream(path, Time(), chunk_size=8)
    collected = bytearray()
    async with stream:
        async for chunk in stream:
            collected += chunk
    assert bytes(collected) == b"0123456789" * 10


async def test_generator_matches_content(tmp_path):
    path = make_file(tmp_path, b"abcdefgh")
    stream = LocalFileStream(path, Time(), chunk_size=3, cleanup=False)
    out = bytearray()
    await stream.setup()
    async for chunk in stream.generator(3):
        out += chunk
    assert bytes(out) == b"abcdefgh"


async def test_size_and_len(tmp_path):
    path = make_file(tmp_path, b"12345")
    stream = LocalFileStream(path, Time(), cleanup=False)
    assert stream.size() == 5
    assert len(stream) == 5


async def test_progress_reaches_100(tmp_path):
    path = make_file(tmp_path, b"abcd")
    stream = LocalFileStream(path, Time(), chunk_size=2)
    assert stream.progress() == 0
    async with stream:
        async for _ in stream:
            pass
    assert stream.progress() == 100


async def test_progress_empty_file_is_100(tmp_path):
    path = make_file(tmp_path, b"")
    stream = LocalFileStream(path, Time(), cleanup=False)
    assert stream.progress() == 100


async def test_format_returns_progress_int(tmp_path):
    path = make_file(tmp_path, b"abcdefghij")
    stream = LocalFileStream(path, Time(), chunk_size=5)
    async with stream:
        await stream.read(5)
        assert "{0}".format(stream) == "50"


async def test_cleanup_removes_file_on_exit(tmp_path):
    path = make_file(tmp_path, b"data")
    stream = LocalFileStream(path, Time(), cleanup=True)
    async with stream:
        pass
    assert not os.path.exists(path)


async def test_no_cleanup_keeps_file(tmp_path):
    path = make_file(tmp_path, b"data")
    stream = LocalFileStream(path, Time(), cleanup=False)
    async with stream:
        pass
    assert os.path.exists(path)


async def test_speed_is_nonnegative(tmp_path):
    path = make_file(tmp_path, b"x" * 100)
    stream = LocalFileStream(path, Time(), chunk_size=10)
    async with stream:
        async for _ in stream:
            pass
    assert stream.speed() >= 0


async def test_self_cleaning_stream_removes_tmpdir(tmp_path):
    sub = tmp_path / "dl"
    sub.mkdir()
    path = make_file(sub, b"data", name="x.tar")
    stream = _SelfCleaningStream(path, Time(), str(sub))
    async with stream:
        pass
    assert not os.path.exists(str(sub))
