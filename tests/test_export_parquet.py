"""Unit tests for the per-equipment Parquet writers and the manifest writer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from ams_extract.export.manifest import MANIFEST_SCHEMA, write_manifest
from ams_extract.export.parquet_samples import (
    sample_id,
    write_spectra_parquet,
    write_spectrum_parquet,
    write_waveforms_parquet,
)
from ams_extract.models import Point, Spectrum, Waveform


def _point(record_num: int, name: str) -> Point:
    return Point(record_num=record_num, long_name=name, short_code=name.replace(" ", "_"))


def _spectrum(point_rec: int, rec: int, ts: datetime) -> Spectrum:
    return Spectrum(
        record_num=rec,
        point_record_num=point_rec,
        timestamp_utc=ts,
        fmax_hz=1000.0,
        n_lines=1600,
        units="plg/segs",
        carga_pct=100.0,
        amplitude=np.arange(8, dtype=np.float32),
    )


def _waveform(point_rec: int, rec: int, ts: datetime) -> Waveform:
    return Waveform(
        record_num=rec,
        point_record_num=point_rec,
        timestamp_utc=ts,
        n_samples=512,
        sample_rate_hz=2560.0,
        rpm=1455.0,
        units="G's",
        carga_pct=100.0,
        samples=np.linspace(-0.5, 0.5, 8, dtype=np.float32),
    )


class TestSampleId:
    def test_is_deterministic_and_16_hex_chars(self) -> None:
        first = sample_id(336982, 337000, "FFT")
        second = sample_id(336982, 337000, "FFT")
        assert first == second
        assert len(first) == 16
        assert all(c in "0123456789abcdef" for c in first)

    def test_distinguishes_type(self) -> None:
        assert sample_id(1, 2, "FFT") != sample_id(1, 2, "WAVEFORM")


class TestWriteSpectraParquet:
    def test_writes_one_row_per_spectrum(self, tmp_path: Path) -> None:
        p1 = _point(100, "LA H")
        p2 = _point(200, "LA V")
        ts = datetime(2020, 2, 19, 10, 2, 50, tzinfo=UTC)
        items = [
            (_spectrum(100, 101, ts), p1),
            (_spectrum(100, 102, ts), p1),
            (_spectrum(200, 201, ts), p2),
        ]
        out = tmp_path / "eq__fft.parquet"
        write_spectra_parquet(items, out)

        rows = pq.read_table(out).to_pylist()
        assert len(rows) == 3
        assert {r["point_long_name"] for r in rows} == {"LA H", "LA V"}
        assert all(r["sample_type"] == "FFT" for r in rows)
        assert rows[0]["sample_id"] == sample_id(100, 101, "FFT")
        assert rows[0]["amplitude"] == list(range(8))

    def test_empty_batch_writes_zero_row_file_with_schema(self, tmp_path: Path) -> None:
        out = tmp_path / "eq__fft.parquet"
        write_spectra_parquet([], out)
        table = pq.read_table(out)
        assert table.num_rows == 0
        assert "amplitude" in table.column_names
        assert "sample_id" in table.column_names

    def test_single_writer_matches_batch_schema(self, tmp_path: Path) -> None:
        ts = datetime(2020, 2, 19, 10, 2, 50, tzinfo=UTC)
        point = _point(100, "LA H")
        out = tmp_path / "one.parquet"
        write_spectrum_parquet(_spectrum(100, 101, ts), point, out)
        rows = pq.read_table(out).to_pylist()
        assert len(rows) == 1
        assert rows[0]["sample_id"] == sample_id(100, 101, "FFT")


class TestWriteWaveformsParquet:
    def test_writes_one_row_per_waveform(self, tmp_path: Path) -> None:
        point = _point(100, "LA H")
        ts = datetime(2020, 2, 19, 10, 2, 50, tzinfo=UTC)
        items = [(_waveform(100, 301, ts), point), (_waveform(100, 302, ts), point)]
        out = tmp_path / "eq__waveform.parquet"
        write_waveforms_parquet(items, out)

        rows = pq.read_table(out).to_pylist()
        assert len(rows) == 2
        assert all(r["sample_type"] == "WAVEFORM" for r in rows)
        assert rows[0]["rpm"] == 1455.0
        assert rows[0]["sample_id"] == sample_id(100, 301, "WAVEFORM")
        assert len(rows[0]["samples"]) == 8


class TestWriteManifest:
    def test_nullable_type_specific_columns(self, tmp_path: Path) -> None:
        rows = [
            {
                "sample_id": "abc",
                "area": "DEPURADORA",
                "equipment": "AG_100",
                "point_record_num": 336982,
                "sample_type": "FFT",
                "fmax_hz": 1000.0,
                "n_lines": 1600,
                "parquet_path": "samples/area=DEPURADORA/equipment=AG_100__fft.parquet",
            },
            {
                "sample_id": "def",
                "area": "DEPURADORA",
                "equipment": "AG_100",
                "point_record_num": 336982,
                "sample_type": "WAVEFORM",
                "sample_rate_hz": 2560.0,
                "rpm": 1455.0,
                "n_samples": 512,
                "parquet_path": (
                    "samples/area=DEPURADORA/equipment=AG_100__waveform.parquet"
                ),
            },
        ]
        out = tmp_path / "manifest.parquet"
        write_manifest(rows, out)

        table = pq.read_table(out)
        assert table.schema.equals(MANIFEST_SCHEMA)
        loaded = table.to_pylist()
        fft_row = next(r for r in loaded if r["sample_type"] == "FFT")
        wav_row = next(r for r in loaded if r["sample_type"] == "WAVEFORM")
        assert fft_row["fmax_hz"] == 1000.0
        assert fft_row["sample_rate_hz"] is None
        assert wav_row["fmax_hz"] is None
        assert wav_row["rpm"] == 1455.0

    def test_empty_manifest_has_schema(self, tmp_path: Path) -> None:
        out = tmp_path / "manifest.parquet"
        write_manifest([], out)
        table = pq.read_table(out)
        assert table.num_rows == 0
        assert table.schema.equals(MANIFEST_SCHEMA)
