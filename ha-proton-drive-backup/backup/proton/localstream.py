import os
from collections import deque
from datetime import timedelta

import aiofiles

from ..time import Time
from ..logger import getLogger

logger = getLogger(__name__)

DEFAULT_CHUNK_SIZE = 1024 * 1024


class LocalFileStream:
    """
    An async, byte-yielding view over a local file that exposes the same surface
    the addon expects from an upload source (size/progress/speed/position).

    ProtonSource.read() downloads a backup from Proton Drive to a temp file via
    the CLI, then hands HomeAssistant one of these so the existing multipart
    upload + progress UI work without changes.  The temp file is removed when
    the stream's context manager exits.
    """

    def __init__(self, path: str, time: Time, chunk_size: int = DEFAULT_CHUNK_SIZE,
                 cleanup: bool = True):
        self._path = path
        self._time = time
        self._chunk_size = chunk_size
        self._cleanup = cleanup
        self._size = os.path.getsize(path)
        self._position = 0
        self._handle = None
        self._history = deque()
        self._start_time = time.now()

    async def setup(self):
        if self._handle is None:
            self._handle = await aiofiles.open(self._path, "rb")
        self._history.append([self._time.now(), 0])
        return self._size

    def size(self) -> int:
        return self._size

    def __len__(self):
        return self._size

    def position(self, pos=None):
        if pos is not None:
            self._position = pos
        return self._position

    def progress(self):
        if self._size == 0:
            return 100
        return 100 * float(self._position) / float(self._size)

    def startTime(self):
        return self._start_time

    def speed(self, period: timedelta = timedelta(seconds=20)):
        if len(self._history) < 2:
            return 0
        now = self._time.now()
        window_start = now - period
        recent = [h for h in self._history if h[0] >= window_start]
        if len(recent) < 2:
            recent = list(self._history)[-2:]
        elapsed = (recent[-1][0] - recent[0][0]).total_seconds()
        if elapsed <= 0:
            return 0
        moved = recent[-1][1] - recent[0][1]
        return moved / elapsed

    def __format__(self, format_spec: str) -> str:
        return str(int(self.progress()))

    async def generator(self, chunk_size):
        while True:
            chunk = await self.read(chunk_size)
            if not chunk:
                break
            yield chunk

    async def read(self, count=None):
        if self._handle is None:
            await self.setup()
        data = await self._handle.read(count or self._chunk_size)
        if data:
            self._position += len(data)
            self._history.append([self._time.now(), self._position])
            if len(self._history) > 50:
                self._history.popleft()
        return data

    async def aclose(self):
        """Public close, for consumers that drive the stream without `async with`."""
        await self._close()

    async def _close(self):
        if self._handle is not None:
            try:
                await self._handle.close()
            finally:
                self._handle = None
        if self._cleanup:
            try:
                os.remove(self._path)
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.warning("Couldn't remove temp file {}: {}".format(self._path, e))

    async def __aenter__(self):
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._close()

    def __aiter__(self):
        return self

    async def __anext__(self):
        chunk = await self.read()
        if not chunk:
            raise StopAsyncIteration
        return chunk
