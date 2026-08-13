"""Safe, atomic writer for VibFrame ``.vibframe.zip`` packages.

A package is a byte-for-byte snapshot of a dataset directory: files keep
their relative POSIX names and live at the archive root.  This module is kept
stdlib-only so producing a package does not make ``vibsynth-contracts`` a
runtime dependency.  The normative envelope is documented in
``vibsynth-contracts/docs/VIBFRAME.md`` (Packaging — ``.vibframe.zip``).
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
import time
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DATASET_FILE = "dataset.json"
PACKAGE_SUFFIX = ".vibframe.zip"
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:$")
_COPY_BUFFER_BYTES = 1024 * 1024
_O_BINARY = int(getattr(os, "O_BINARY", 0))
_O_NOFOLLOW = int(getattr(os, "O_NOFOLLOW", 0))


class PackageError(Exception):
    """Base class for errors raised while producing a package."""


class InvalidDatasetError(PackageError):
    """The source is not a directory containing a regular dataset document."""


class UnsafePackageEntryError(PackageError):
    """A dataset entry is a symlink, special file, or has an unsafe name."""


class PackageWriteError(PackageError):
    """The temporary archive could not be written completely."""


class PackagePublicationError(PackageError):
    """A complete temporary archive could not be atomically published."""


@dataclass(frozen=True)
class PackageSummary:
    """Counts and paths for a completed package."""

    package: Path
    entries: int
    expanded_bytes: int
    package_bytes: int
    duration_seconds: float


@dataclass(frozen=True)
class _Entry:
    path: Path
    name: str


def default_package_path(dataset_dir: Path) -> Path:
    """Return ``<dataset>.vibframe.zip`` next to ``dataset_dir``."""
    dataset_dir = Path(dataset_dir)
    return dataset_dir.with_name(dataset_dir.name + PACKAGE_SUFFIX)


def _validate_entry_name(name: str) -> None:
    """Enforce the normalized relative POSIX-name portion of the envelope."""
    pure = PurePosixPath(name)
    parts = pure.parts
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or _WINDOWS_DRIVE.fullmatch(parts[0]) is not None
        or pure.as_posix() != name
    ):
        raise UnsafePackageEntryError(f"unsafe package entry name: {name!r}")


def _collect_files(dataset_dir: Path, excluded: set[Path]) -> list[_Entry]:
    """Collect regular files without following symlinks, in archive order."""
    entries: list[_Entry] = []
    pending = [dataset_dir]
    while pending:
        directory = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise UnsafePackageEntryError(
                f"cannot inspect dataset directory {directory}: {exc}"
            ) from exc
        child_directories: list[Path] = []
        for path in children:
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise UnsafePackageEntryError(
                    f"cannot inspect dataset entry {path}: {exc}"
                ) from exc

            # ``resolve`` would itself follow a symlink (and can fail on a
            # symlink loop), which is precisely what this census forbids.
            lexical_absolute = Path(os.path.abspath(path))
            if lexical_absolute in excluded:
                continue
            relative = path.relative_to(dataset_dir).as_posix()
            _validate_entry_name(relative)
            if stat.S_ISLNK(metadata.st_mode):
                raise UnsafePackageEntryError(f"dataset entry is a symlink: {relative}")
            if stat.S_ISDIR(metadata.st_mode):
                child_directories.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                entries.append(_Entry(path=path, name=relative))
            else:
                raise UnsafePackageEntryError(
                    f"dataset entry is not a regular file or directory: {relative}"
                )
        # Stack order is irrelevant because the final file list is sorted, but
        # reversing keeps traversal itself lexicographic for clearer failures.
        pending.extend(reversed(child_directories))
    entries.sort(key=lambda entry: entry.name)
    return entries


def _zip_timestamp(timestamp: float) -> tuple[int, int, int, int, int, int]:
    """Return a ZIP-representable local timestamp for filesystem metadata."""
    fields = time.localtime(timestamp)[:6]
    if fields[0] < 1980:
        return (1980, 1, 1, 0, 0, 0)
    if fields[0] > 2107:
        return (2107, 12, 31, 23, 59, 58)
    return fields


def _write_entry(archive: zipfile.ZipFile, entry: _Entry) -> int:
    """Stream one regular file into ``archive`` without following a final symlink."""
    flags = os.O_RDONLY | _O_BINARY | _O_NOFOLLOW
    try:
        descriptor = os.open(entry.path, flags)
    except OSError as exc:
        raise UnsafePackageEntryError(f"cannot open dataset entry {entry.name}: {exc}") from exc

    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafePackageEntryError(f"dataset entry is not a regular file: {entry.name}")
        info = zipfile.ZipInfo(entry.name, _zip_timestamp(metadata.st_mtime))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | stat.S_IMODE(metadata.st_mode)) << 16
        info.file_size = metadata.st_size
        with archive.open(info, "w", force_zip64=True) as destination:
            shutil.copyfileobj(source, destination, length=_COPY_BUFFER_BYTES)
        return metadata.st_size


def package_dataset(dataset_dir: Path, target: Path | None = None) -> PackageSummary:
    """Atomically package an existing VibFrame dataset and return its summary.

    The source directory is never modified.  A temporary sibling of the
    destination is written first, then published with :func:`os.replace` only
    after the ZIP closes successfully.  If publication fails, any prior
    destination is left untouched and the temporary is removed.
    """
    started = time.perf_counter()
    dataset_dir = Path(dataset_dir)
    if dataset_dir.is_symlink():
        raise InvalidDatasetError(f"dataset directory is a symlink: {dataset_dir}")
    if not dataset_dir.is_dir():
        raise InvalidDatasetError(f"dataset directory not found: {dataset_dir}")
    dataset_document = dataset_dir / DATASET_FILE
    try:
        document_metadata = dataset_document.lstat()
    except FileNotFoundError as exc:
        raise InvalidDatasetError(
            f"not a VibFrame dataset (missing {DATASET_FILE}): {dataset_dir}"
        ) from exc
    except OSError as exc:
        raise InvalidDatasetError(f"cannot inspect {dataset_document}: {exc}") from exc
    if not stat.S_ISREG(document_metadata.st_mode):
        raise InvalidDatasetError(f"{DATASET_FILE} is not a regular file: {dataset_document}")

    target = Path(target) if target is not None else default_package_path(dataset_dir)
    absolute_target = Path(os.path.abspath(target))
    absolute_dataset = Path(os.path.abspath(dataset_dir))
    if target.is_symlink():
        raise PackageWriteError(f"package destination is a symlink: {target}")
    # Refreshing a previous ZIP is safe. Never turn dataset.json,
    # machine.json or another arbitrary member into a ZIP merely because it
    # was also supplied as --out.
    if (
        absolute_target.is_relative_to(absolute_dataset)
        and target.exists()
        and (not target.is_file() or not zipfile.is_zipfile(target))
    ):
        raise PackageWriteError(
            f"refusing to overwrite a non-package dataset entry: {target}"
        )
    # Census the source before creating a destination directory or temporary,
    # so invalid sources have no output-side effects.  An existing destination
    # inside the dataset is deliberately excluded as a previous package.
    entries = _collect_files(dataset_dir, {absolute_target})

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        os.close(descriptor)
    except OSError as exc:
        raise PackageWriteError(f"cannot create temporary package beside {target}: {exc}") from exc

    temporary = Path(temporary_name)
    expanded_bytes = 0
    try:
        try:
            with zipfile.ZipFile(
                temporary,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                allowZip64=True,
            ) as archive:
                for entry in entries:
                    expanded_bytes += _write_entry(archive, entry)
        except PackageError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise PackageWriteError(f"cannot write package {target}: {exc}") from exc

        try:
            os.replace(temporary, target)
        except OSError as exc:
            raise PackagePublicationError(f"cannot publish package {target}: {exc}") from exc
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)

    return PackageSummary(
        package=target,
        entries=len(entries),
        expanded_bytes=expanded_bytes,
        package_bytes=target.stat().st_size,
        duration_seconds=time.perf_counter() - started,
    )


__all__ = [
    "PACKAGE_SUFFIX",
    "InvalidDatasetError",
    "PackageError",
    "PackagePublicationError",
    "PackageSummary",
    "PackageWriteError",
    "UnsafePackageEntryError",
    "default_package_path",
    "package_dataset",
]
