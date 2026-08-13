"""Production of safe, atomic VibFrame ``.vibframe.zip`` packages."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner
from vibsynth_contracts.validate import validate_package

from ams_extract.cli import app as rbm_app
from ams_extract.export import package as package_module
from ams_extract.export.package import (
    PACKAGE_SUFFIX,
    InvalidDatasetError,
    PackagePublicationError,
    PackageWriteError,
    UnsafePackageEntryError,
    default_package_path,
    package_dataset,
)

runner = CliRunner()


def _archive_hashes(archive: Path) -> dict[str, str]:
    with zipfile.ZipFile(archive) as zipped:
        return {
            info.filename: hashlib.sha256(zipped.read(info)).hexdigest()
            for info in zipped.infolist()
        }


def _source_hashes(dataset: Path, *, excluded: set[Path] | None = None) -> dict[str, str]:
    excluded = {path.resolve() for path in (excluded or set())}
    return {
        path.relative_to(dataset).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(dataset.rglob("*"))
        if path.is_file() and path.resolve() not in excluded
    }


def test_default_and_explicit_package_paths(vibframe_dataset: Path, tmp_path: Path) -> None:
    default = package_dataset(vibframe_dataset)
    assert default.package == default_package_path(vibframe_dataset)
    assert default.package.name == vibframe_dataset.name + PACKAGE_SUFFIX

    explicit = tmp_path / "delivery" / "snapshot.zip"
    summary = package_dataset(vibframe_dataset, explicit)
    assert summary.package == explicit
    assert explicit.is_file()


def test_package_is_a_strictly_valid_vibframe_envelope(vibframe_dataset: Path) -> None:
    archive = package_dataset(vibframe_dataset).package
    report = validate_package(archive)
    assert report.errors == [], [issue.format() for issue in report.errors]
    assert report.warnings == [], [issue.format() for issue in report.warnings]
    assert report.ok(strict=True)


def test_installed_validator_cli_accepts_package(vibframe_dataset: Path) -> None:
    archive = package_dataset(vibframe_dataset).package
    script = Path(sys.executable).parent / "vibframe-validate"
    argv = (
        [str(script)]
        if script.exists()
        else [sys.executable, "-m", "vibsynth_contracts.validate.cli"]
    )
    process = subprocess.run(
        [*argv, str(archive), "--strict", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    report = json.loads(process.stdout)
    assert report["ok"] and report["counts"]["error"] == 0


def test_viewer_report_is_identical_from_directory_and_package(
    vibframe_dataset: Path, tmp_path: Path
) -> None:
    from vibframe_viewer.cli import main as viewer_main

    archive = package_dataset(vibframe_dataset).package
    from_directory = tmp_path / "directory.html"
    from_package = tmp_path / "package.html"
    assert (
        viewer_main(
            ["report", str(vibframe_dataset), "-o", str(from_directory), "--title", "T"]
        )
        == 0
    )
    assert (
        viewer_main(["report", str(archive), "-o", str(from_package), "--title", "T"])
        == 0
    )
    assert from_package.read_bytes() == from_directory.read_bytes()


def test_entries_are_sorted_rooted_and_byte_identical(vibframe_dataset: Path) -> None:
    (vibframe_dataset / "ground-truth").mkdir()
    (vibframe_dataset / "ground-truth" / "diagnóstico.json").write_bytes(b'{"ok": true}\n')
    (vibframe_dataset / "analysis" / "layer").mkdir(parents=True)
    (vibframe_dataset / "analysis" / "layer" / "result.bin").write_bytes(b"\x00\xffsidecar")

    archive = package_dataset(vibframe_dataset).package
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        methods = {info.compress_type for info in zipped.infolist()}
        versions = {info.extract_version for info in zipped.infolist()}
    assert names == sorted(names)
    assert all(not name.startswith("/") and "\\" not in name for name in names)
    assert _archive_hashes(archive) == _source_hashes(vibframe_dataset)
    assert methods <= {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
    # The writer requests ZIP64 up front, so large inputs never require a
    # second pass or fail after crossing the classic ZIP limit.
    assert versions == {45}


def test_summary_reports_files_and_sizes(vibframe_dataset: Path) -> None:
    expected = _source_hashes(vibframe_dataset)
    summary = package_dataset(vibframe_dataset)
    assert summary.entries == len(expected)
    assert summary.expanded_bytes == sum(
        path.stat().st_size for path in vibframe_dataset.rglob("*") if path.is_file()
    )
    assert summary.package_bytes == summary.package.stat().st_size
    assert summary.duration_seconds >= 0


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink"])
def test_dataset_json_must_be_a_regular_file(tmp_path: Path, kind: str) -> None:
    dataset = tmp_path / kind
    dataset.mkdir()
    document = dataset / "dataset.json"
    if kind == "directory":
        document.mkdir()
    elif kind == "symlink":
        target = tmp_path / "document.json"
        target.write_text("{}", encoding="utf-8")
        document.symlink_to(target)
    with pytest.raises(InvalidDatasetError, match=r"dataset\.json"):
        package_dataset(dataset)
    assert not default_package_path(dataset).exists()


def test_source_directory_symlink_is_rejected(vibframe_dataset: Path) -> None:
    alias = vibframe_dataset.parent / "alias"
    alias.symlink_to(vibframe_dataset, target_is_directory=True)
    with pytest.raises(InvalidDatasetError, match="symlink"):
        package_dataset(alias)


def test_symlink_entry_is_rejected_and_named(vibframe_dataset: Path) -> None:
    link = vibframe_dataset / "machine=unsafe"
    # A loop proves the census reports the link itself instead of resolving it.
    link.symlink_to(link.name)
    with pytest.raises(UnsafePackageEntryError, match="machine=unsafe"):
        package_dataset(vibframe_dataset)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is unavailable on this platform")
def test_special_entry_is_rejected_and_named(vibframe_dataset: Path) -> None:
    fifo = vibframe_dataset / "analysis.pipe"
    os.mkfifo(fifo)
    with pytest.raises(UnsafePackageEntryError, match=r"analysis\.pipe"):
        package_dataset(vibframe_dataset)


def test_unsafe_backslash_name_is_rejected(vibframe_dataset: Path) -> None:
    unsafe = vibframe_dataset / "machine=bad\\machine.json"
    unsafe.write_text("{}", encoding="utf-8")
    with pytest.raises(UnsafePackageEntryError, match="unsafe package entry"):
        package_dataset(vibframe_dataset)


def test_package_inside_dataset_never_contains_itself_or_its_temp(vibframe_dataset: Path) -> None:
    target = vibframe_dataset / "delivery.vibframe.zip"
    package_dataset(vibframe_dataset, target)
    package_dataset(vibframe_dataset, target)
    with zipfile.ZipFile(target) as zipped:
        names = zipped.namelist()
    assert target.name not in names
    assert not any(name.startswith(f".{target.name}.") and name.endswith(".tmp") for name in names)
    assert not list(vibframe_dataset.glob(f".{target.name}.*.tmp"))


def test_target_cannot_overwrite_an_existing_dataset_member(vibframe_dataset: Path) -> None:
    document = vibframe_dataset / "dataset.json"
    before = document.read_bytes()
    with pytest.raises(PackageWriteError, match="non-package dataset entry"):
        package_dataset(vibframe_dataset, document)
    assert document.read_bytes() == before


def test_target_symlink_is_rejected_without_touching_its_referent(
    vibframe_dataset: Path, tmp_path: Path
) -> None:
    referent = tmp_path / "existing.vibframe.zip"
    referent.write_bytes(b"keep")
    target = tmp_path / "delivery.vibframe.zip"
    target.symlink_to(referent)
    with pytest.raises(PackageWriteError, match="destination is a symlink"):
        package_dataset(vibframe_dataset, target)
    assert referent.read_bytes() == b"keep"


def test_write_failure_preserves_previous_package_and_cleans_temp(
    vibframe_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = default_package_path(vibframe_dataset)
    target.write_bytes(b"previous-package")

    def fail_write(*args: object, **kwargs: object) -> int:
        raise OSError("injected write failure")

    monkeypatch.setattr(package_module, "_write_entry", fail_write)
    with pytest.raises(PackageWriteError, match="injected write failure"):
        package_dataset(vibframe_dataset, target)
    assert target.read_bytes() == b"previous-package"
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


def test_publication_failure_preserves_previous_package_and_cleans_temp(
    vibframe_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = default_package_path(vibframe_dataset)
    target.write_bytes(b"previous-package")

    def fail_replace(*args: object, **kwargs: object) -> None:
        raise OSError("injected publication failure")

    monkeypatch.setattr(package_module.os, "replace", fail_replace)
    with pytest.raises(PackagePublicationError, match="injected publication failure"):
        package_dataset(vibframe_dataset, target)
    assert target.read_bytes() == b"previous-package"
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


class TestPackageCli:
    def test_packages_existing_dataset_with_default_path(self, vibframe_dataset: Path) -> None:
        result = runner.invoke(rbm_app, ["package", str(vibframe_dataset)])
        assert result.exit_code == 0, result.output
        archive = default_package_path(vibframe_dataset)
        assert archive.exists()
        assert f"package: {archive}" in result.output
        assert "entries:" in result.output

    def test_honours_explicit_output(self, vibframe_dataset: Path, tmp_path: Path) -> None:
        target = tmp_path / "delivery" / "named.zip"
        result = runner.invoke(
            rbm_app, ["package", str(vibframe_dataset), "--out", str(target)]
        )
        assert result.exit_code == 0, result.output
        assert target.exists()

    def test_invalid_dataset_is_a_clean_cli_error(self, tmp_path: Path) -> None:
        result = runner.invoke(rbm_app, ["package", str(tmp_path / "missing")])
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_export_can_package_the_completed_dataset(
        self, synthetic_rbm: Path, tmp_path: Path
    ) -> None:
        dataset = tmp_path / "dataset"
        target = tmp_path / "delivery" / "export.vibframe.zip"
        result = runner.invoke(
            rbm_app,
            [
                "export",
                str(synthetic_rbm),
                "--out",
                str(dataset),
                "--types",
                "fft",
                "--zip",
                "--zip-out",
                str(target),
            ],
        )
        assert result.exit_code == 0, result.output
        assert dataset.is_dir()
        assert target.is_file()
        assert f"package: {target}" in result.output

    def test_zip_out_requires_zip(self, synthetic_rbm: Path, tmp_path: Path) -> None:
        target = tmp_path / "should-not-exist.vibframe.zip"
        result = runner.invoke(
            rbm_app,
            [
                "export",
                str(synthetic_rbm),
                "--out",
                str(tmp_path / "dataset"),
                "--zip-out",
                str(target),
            ],
        )
        assert result.exit_code == 1
        assert "--zip-out requires --zip" in result.output
        assert not target.exists()

    def test_failed_export_does_not_create_package(self, tmp_path: Path) -> None:
        dataset = tmp_path / "dataset"
        result = runner.invoke(
            rbm_app,
            ["export", str(tmp_path / "missing.rbm"), "--out", str(dataset), "--zip"],
        )
        assert result.exit_code == 1
        assert not default_package_path(dataset).exists()
