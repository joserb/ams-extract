"""Shared pytest fixtures for ams-extract."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ams_extract.export.dataset import (
    DATASET_FILE,
    MACHINE_DOC_FILE,
    METRICS_COLUMNS,
    METRICS_FILE,
    SCHEMA_VERSION,
    SPECTRA_COLUMNS,
    SPECTRA_FILE,
    TRENDS_COLUMNS,
    TRENDS_FILE,
    WAVES_COLUMNS,
    WAVES_FILE,
    _add_proc_mode,
    _band_metric_row,
    _band_trend_rows,
    _build_machine_doc,
    _context_metric_row,
    _context_trend_rows,
    _extractor_name,
    _metric_row,
    _spectrum_mode_id,
    _spectrum_row,
    _trend_rows,
    _waveform_mode_id,
    _waveform_row,
    _write_json,
    _write_parquet,
)
from ams_extract.models import Equipment, Point, Spectrum, Trend, TrendBand, Waveform

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def synthetic_rbm() -> Path:
    """Path to the committed minimal synthetic .rbm fixture."""
    path = FIXTURES_DIR / "synthetic_minimal.rbm"
    assert path.exists(), (
        f"missing synthetic fixture {path}; regenerate with "
        "`uv run python scripts/make_synthetic_fixture.py`"
    )
    return path


@pytest.fixture
def real_rbm() -> Path:
    """Path to the real client .rbm. Test is skipped if ``RBM_TEST_FILE`` is unset."""
    env_path = os.environ.get("RBM_TEST_FILE")
    if not env_path:
        pytest.skip("RBM_TEST_FILE not set; integration test skipped")
    path = Path(env_path)
    if not path.exists():
        pytest.skip(f"RBM_TEST_FILE points to a missing path: {path}")
    return path


# --------------------------------------------------------------- VibFrame dataset

_TS = datetime(2020, 2, 19, 10, 2, 50, tzinfo=UTC)


def _sample_point() -> Point:
    return Point(record_num=10, long_name="MOTOR LA HORIZONTAL", short_code="MOTOR_LA_H")


def _sample_spectrum(point: Point) -> Spectrum:
    return Spectrum(
        record_num=20,
        point_record_num=point.record_num,
        timestamp_utc=_TS,
        fmax_hz=1_000.0,
        n_lines=8,
        units="mm/s",
        rpm=1_455.0,
        carga_pct=100.0,
        amplitude=np.arange(8, dtype=np.float32),
    )


def _sample_waveform(point: Point) -> Waveform:
    return Waveform(
        record_num=30,
        point_record_num=point.record_num,
        timestamp_utc=_TS,
        n_samples=8,
        sample_rate_hz=2_560.0,
        rpm=1_455.0,
        units="G's",
        carga_pct=100.0,
        samples=np.linspace(-0.5, 0.5, 8, dtype=np.float32),
        nominal_n_samples=512,
    )


def _sample_trend(point: Point) -> Trend:
    stamps = (_TS, datetime(2020, 2, 20, 10, 2, 50, tzinfo=UTC))
    return Trend(
        record_num=40,
        point_record_num=point.record_num,
        units="mm/s",
        timestamps_utc=stamps,
        overall=np.asarray([1.0, 1.5], dtype=np.float32),
        bands=(
            TrendBand(
                name="SUBSINCRONO",
                units="mm/s",
                timestamps_utc=stamps,
                values=np.asarray([0.4, 0.6], dtype=np.float32),
                low_order=0.0,
                high_order=0.7,
                alert=1.4,
                danger=2.2,
                alarms=(0, 0),
            ),
        ),
        alert=4.5,
        danger=7.1,
        alarms=(0, 0),
    )


def build_vibframe_dataset(root: Path, *, name: str = "ds") -> Path:
    """Write a minimal VibFrame dataset the way ``rbm export`` writes one.

    One machine, one point, one spectrum, one waveform and a trend with a
    named band, plus the machine-level context metrics. Everything goes
    through the same row builders and parquet writer that
    ``_process_equipment`` uses, so what lands on disk is the production
    layout with production values — only the ``.rbm`` reader is missing
    (the committed synthetic fixture carries areas but no equipment, and
    the real database is opt-in through ``RBM_TEST_FILE``).
    """
    point = _sample_point()
    equipment = Equipment(record_num=5, long_name="Bomba EQ", short_code="EQ", points=(point,))
    spectrum = _sample_spectrum(point)
    waveform = _sample_waveform(point)
    trend = _sample_trend(point)
    extracted_at = datetime(2020, 3, 1, tzinfo=UTC)

    proc_modes: dict[tuple[str, str], dict[str, Any]] = {}
    _add_proc_mode(
        proc_modes,
        point_id=point.short_code,
        mode_id=_spectrum_mode_id(spectrum),
        signal_family="velocity",
        fmax_hz=spectrum.fmax_hz,
        lines=spectrum.n_lines,
    )
    _add_proc_mode(
        proc_modes,
        point_id=point.short_code,
        mode_id=_waveform_mode_id(waveform),
        signal_family="acceleration",
        sample_rate_hz=waveform.sample_rate_hz,
        n_samples=waveform.n_samples,
        nominal_n_samples=waveform.nominal_n_samples,
    )

    spectrum_row = _spectrum_row(spectrum, point)
    waveform_row = _waveform_row(waveform, point)
    trend_rows = [*_trend_rows(trend, point), *_band_trend_rows(trend.bands[0], point)]
    metric_rows = [
        _metric_row(trend, point),
        _band_metric_row(trend.bands[0], point),
    ]
    context_rows = _context_trend_rows(
        [
            (spectrum_row["t"], spectrum.rpm, spectrum.carga_pct),
            (waveform_row["t"], waveform.rpm, waveform.carga_pct),
        ]
    )
    trend_rows.extend(context_rows)
    metric_rows.extend(
        _context_metric_row(metric_id, equipment.short_code)
        for metric_id in sorted({row["metric_id"] for row in context_rows})
    )

    dataset = root / name
    _write_json(
        dataset / DATASET_FILE,
        {
            "schema_version": SCHEMA_VERSION,
            "name": name,
            "generator": _extractor_name(),
            "created_at": extracted_at,
            "description": "",
        },
    )
    machine_dir = dataset / f"machine={equipment.short_code}"
    _write_json(
        machine_dir / MACHINE_DOC_FILE,
        _build_machine_doc(
            source_path="fixture.rbm",
            extracted_at=extracted_at,
            area_long="AREA A",
            equipment=equipment,
            proc_modes=sorted(proc_modes.values(), key=lambda m: (m["point_id"], m["id"])),
        ),
    )
    _write_parquet(
        sorted(metric_rows, key=lambda r: r["metric_id"]),
        METRICS_COLUMNS,
        machine_dir / METRICS_FILE,
    )
    _write_parquet([spectrum_row], SPECTRA_COLUMNS, machine_dir / SPECTRA_FILE)
    _write_parquet([waveform_row], WAVES_COLUMNS, machine_dir / WAVES_FILE)
    _write_parquet(trend_rows, TRENDS_COLUMNS, machine_dir / TRENDS_FILE)
    return dataset


@pytest.fixture
def make_dataset() -> Callable[..., Path]:
    """The :func:`build_vibframe_dataset` factory, for tests that need variants."""
    return build_vibframe_dataset


@pytest.fixture
def vibframe_dataset(tmp_path: Path) -> Path:
    """A minimal VibFrame dataset shaped like ``rbm export`` output."""
    return build_vibframe_dataset(tmp_path)
