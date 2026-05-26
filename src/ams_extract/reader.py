"""Low-level access to a .rbm database via memory mapping.

A .rbm file is a sequence of 512-byte records, addressed by zero-based record
number (see ``docs/DECISIONS.md`` ADR-0001). ``RbmReader`` mmaps the file and
exposes ``read_record(n)`` and a couple of typed numeric helpers.

The reader is a context manager; iterating after ``close()`` raises ``ValueError``.
"""

from __future__ import annotations

import mmap
import os
import struct
from pathlib import Path
from types import TracebackType
from typing import Self

RECORD_SIZE = 512
"""Size in bytes of every record in a .rbm file."""


class RbmFileError(ValueError):
    """Raised when a .rbm file fails structural validation."""


class RbmReader:
    """Memory-mapped, read-only access to a .rbm database.

    Records are indexed from zero (see ADR-0001). The file must be a non-empty
    multiple of ``RECORD_SIZE``; otherwise ``RbmFileError`` is raised on open.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path: Path = Path(path)
        self._fd: int | None = None
        self._mmap: mmap.mmap | None = None
        self._size: int = 0
        self._open()

    def _open(self) -> None:
        size = self.path.stat().st_size
        if size == 0:
            raise RbmFileError(f"{self.path}: file is empty")
        if size % RECORD_SIZE != 0:
            raise RbmFileError(
                f"{self.path}: size {size} is not a multiple of {RECORD_SIZE}"
            )
        fd = os.open(self.path, os.O_RDONLY)
        try:
            self._mmap = mmap.mmap(fd, size, prot=mmap.PROT_READ)
        except Exception:
            os.close(fd)
            raise
        self._fd = fd
        self._size = size

    @property
    def size(self) -> int:
        """File size in bytes."""
        return self._size

    @property
    def record_count(self) -> int:
        """Total number of 512-byte records in the file."""
        return self._size // RECORD_SIZE

    def _mm(self) -> mmap.mmap:
        if self._mmap is None:
            raise ValueError("RbmReader is closed")
        return self._mmap

    def read_record(self, n: int) -> bytes:
        """Return the raw 512 bytes of record ``n`` (zero-based).

        Args:
            n: Record index, in ``[0, record_count)``.

        Raises:
            IndexError: If ``n`` is out of range.
        """
        if n < 0 or n >= self.record_count:
            raise IndexError(
                f"record {n} out of range [0, {self.record_count})"
            )
        offset = n * RECORD_SIZE
        return bytes(self._mm()[offset : offset + RECORD_SIZE])

    def read_u32(self, record: int, offset: int) -> int:
        """Read a little-endian unsigned 32-bit integer at the given record offset."""
        data = self.read_record(record)
        if offset < 0 or offset + 4 > RECORD_SIZE:
            raise IndexError(f"offset {offset} out of range for u32 read")
        return struct.unpack_from("<I", data, offset)[0]

    def close(self) -> None:
        """Close the mmap and underlying file descriptor."""
        if self._mmap is not None:
            self._mmap.close()
            self._mmap = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
