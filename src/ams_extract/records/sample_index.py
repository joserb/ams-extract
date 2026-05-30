"""Parser for the per-point sample-index record (``pdcd``).

Each point's ``vdpm`` record points at offset 0x10 to a ``pdcd`` record
("Set Colección Datos Primar" per the embedded description string).
The ``pdcd`` acts as a per-point index of measurement chains:

- ``pdcd.0x04`` → first ``vcfw`` (early hypothesis; superseded by the
  verified ``vdfw`` descriptor chain below — kept for reference)
- ``pdcd.0x3C`` → first ``vddt`` of the trend chain (oldest), FORMAT §5.7
- ``pdcd.0x40`` → last  ``vddt`` of the trend chain (newest), FORMAT §5.7
- ``pdcd.0x44`` → first ``vdps`` of the FFT chain (oldest spectrum)
- ``pdcd.0x48`` → last  ``vdps`` of the FFT chain (newest spectrum)
- ``pdcd.0x5C`` → first ``vdfw`` waveform descriptor (oldest), sub-fase 5a
- ``pdcd.0x60`` → last  ``vdfw`` waveform descriptor (newest), sub-fase 5a

The FFT spectrum chain runs vdps → vdps via offset 0x14 from the head
returned here; see :mod:`ams_extract.records.sample`. The waveform
descriptor chain runs vdfw → vdfw via offset 0x14; see
:mod:`ams_extract.records.waveform`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ams_extract.reader import RbmReader, decode_inner_pointer

PDCD_TAG = b"pdcd"
TAG_OFFSET = 0x08

PDCD_TREND_FIRST_VDDT_OFFSET = 0x3C
PDCD_TREND_LAST_VDDT_OFFSET = 0x40
PDCD_FFT_FIRST_VDPS_OFFSET = 0x44
PDCD_FFT_LAST_VDPS_OFFSET = 0x48
PDCD_WAVEFORM_FIRST_OFFSET = 0x04
PDCD_WAVEFORM_FIRST_VDFW_OFFSET = 0x5C
PDCD_WAVEFORM_LAST_VDFW_OFFSET = 0x60


class SampleIndexError(ValueError):
    """Raised when a sample-index record has an unexpected tag."""


@dataclass(frozen=True, slots=True)
class PdcdLinks:
    """The chain heads exposed by one ``pdcd`` record.

    Each field is ``None`` when the corresponding pointer is zero (no
    chain of that type recorded for the point).
    """

    record_num: int
    trend_first_vddt: int | None
    trend_last_vddt: int | None
    fft_first_vdps: int | None
    fft_last_vdps: int | None
    waveform_first: int | None
    waveform_first_vdfw: int | None
    waveform_last_vdfw: int | None


def _check_tag(record: bytes, expected: bytes, record_num: int) -> None:
    tag = bytes(record[TAG_OFFSET : TAG_OFFSET + 4])
    if tag != expected:
        raise SampleIndexError(
            f"record {record_num}: expected tag {expected!r}, got {tag!r}"
        )


def parse_pdcd_links(reader: RbmReader, pdcd_record: int) -> PdcdLinks:
    """Return the chain heads stored in a ``pdcd`` record.

    Raises:
        SampleIndexError: If the record's tag is not ``pdcd``.
    """
    record = reader.read_record(pdcd_record)
    _check_tag(record, PDCD_TAG, pdcd_record)

    def _pointer(offset: int) -> int | None:
        (stored,) = struct.unpack_from("<I", record, offset)
        return decode_inner_pointer(stored)

    return PdcdLinks(
        record_num=pdcd_record,
        trend_first_vddt=_pointer(PDCD_TREND_FIRST_VDDT_OFFSET),
        trend_last_vddt=_pointer(PDCD_TREND_LAST_VDDT_OFFSET),
        fft_first_vdps=_pointer(PDCD_FFT_FIRST_VDPS_OFFSET),
        fft_last_vdps=_pointer(PDCD_FFT_LAST_VDPS_OFFSET),
        waveform_first=_pointer(PDCD_WAVEFORM_FIRST_OFFSET),
        waveform_first_vdfw=_pointer(PDCD_WAVEFORM_FIRST_VDFW_OFFSET),
        waveform_last_vdfw=_pointer(PDCD_WAVEFORM_LAST_VDFW_OFFSET),
    )
