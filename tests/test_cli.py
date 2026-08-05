"""End-to-end CLI tests for subcommands implemented through Phase 2."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ams_extract.cli import app as rbm_app
from ams_extract.cli_dev import app as rbm_dev_app

runner = CliRunner()


class TestRbmInfo:
    def test_prints_signature_and_description(self, synthetic_rbm: Path) -> None:
        result = runner.invoke(rbm_app, ["info", str(synthetic_rbm)])
        assert result.exit_code == 0, result.output
        assert "MT4.00" in result.output
        assert "SYNTHETIC FIXTURE" in result.output

    def test_missing_file_exits_nonzero(self, tmp_path: Path) -> None:
        result = runner.invoke(rbm_app, ["info", str(tmp_path / "missing.rbm")])
        assert result.exit_code == 1
        assert "error" in result.output.lower()


class TestRbmTree:
    def test_prints_synthetic_areas_to_stdout(self, synthetic_rbm: Path) -> None:
        result = runner.invoke(rbm_app, ["tree", str(synthetic_rbm)])
        assert result.exit_code == 0, result.output
        assert "5 areas" in result.output
        for name in ("AREA_ALPHA", "AREA_BETA", "AREA_GAMMA", "AREA_DELTA", "AREA_OMEGA"):
            assert name in result.output

    def test_writes_json_when_out_given(
        self, synthetic_rbm: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "tree.json"
        result = runner.invoke(rbm_app, ["tree", str(synthetic_rbm), "--out", str(out)])
        assert result.exit_code == 0, result.output
        assert out.exists()
        document = json.loads(out.read_text(encoding="utf-8"))
        assert document["meta"]["area_count"] == 5
        long_names = [a["long_name"] for a in document["areas"]]
        assert long_names == [
            "AREA_ALPHA",
            "AREA_BETA",
            "AREA_GAMMA",
            "AREA_DELTA",
            "AREA_OMEGA",
        ]

    def test_missing_file_exits_nonzero(self, tmp_path: Path) -> None:
        result = runner.invoke(rbm_app, ["tree", str(tmp_path / "missing.rbm")])
        assert result.exit_code == 1


class TestRbmDevDumpRecord:
    def test_dumps_first_record(self, synthetic_rbm: Path) -> None:
        result = runner.invoke(
            rbm_dev_app, ["dump-record", str(synthetic_rbm), "--rec", "0"]
        )
        assert result.exit_code == 0, result.output
        # The "MT4.00" signature bytes (0x4d 0x54 0x34 0x2e 0x30 0x30) appear
        # at file offset 0x1c. The signature is split across hex-dump rows
        # (rows are 16 bytes wide), so we check the hex column instead.
        assert "4d 54 34 2e" in result.output
        # The header line should mention record 0 and the byte size.
        assert "record 0" in result.output
        assert "512 bytes" in result.output

    def test_out_of_range_record_errors(self, synthetic_rbm: Path) -> None:
        result = runner.invoke(
            rbm_dev_app, ["dump-record", str(synthetic_rbm), "--rec", "9999"]
        )
        assert result.exit_code == 1
        assert "out of range" in result.output


class TestRbmDevFollowChain:
    def test_stops_at_null_pointer(self, synthetic_rbm: Path) -> None:
        # Records 3-15 in the synthetic fixture are zero-padded, so following
        # from record 3 with default offset 0 reads next=0 and stops.
        result = runner.invoke(
            rbm_dev_app, ["follow-chain", str(synthetic_rbm), "--from", "3"]
        )
        assert result.exit_code == 0, result.output
        assert "visited 1 records" in result.output
        assert "null pointer" in result.output

    def test_detects_cycle(self, tmp_path: Path) -> None:
        from ams_extract.reader import RECORD_SIZE

        # Build a 3-record file with a chain that cycles among records 1<->2.
        # Following from record 1 should visit 1, 2, then detect the cycle
        # back to 1. (We avoid 0 as a chain link because 0 means "end".)
        records: list[bytes] = [bytes(RECORD_SIZE)]  # record 0: unused
        record1 = bytearray(RECORD_SIZE)
        record1[0:4] = (2).to_bytes(4, "little")
        record2 = bytearray(RECORD_SIZE)
        record2[0:4] = (1).to_bytes(4, "little")
        records.append(bytes(record1))
        records.append(bytes(record2))
        path = tmp_path / "cycle.rbm"
        path.write_bytes(b"".join(records))

        result = runner.invoke(
            rbm_dev_app, ["follow-chain", str(path), "--from", "1", "--max-steps", "10"]
        )
        assert result.exit_code == 0, result.output
        assert "cycle detected" in result.output
        assert "visited 2 records" in result.output

    def test_respects_max_steps_cap(self, tmp_path: Path) -> None:
        from ams_extract.reader import RECORD_SIZE

        # 4-record file where each record's first u32 points to the next
        # ascending index (1->2->3). With --max-steps=2 we should be capped
        # before reaching the end.
        records: list[bytes] = [bytes(RECORD_SIZE)]
        for next_rec in (2, 3, 0):
            r = bytearray(RECORD_SIZE)
            r[0:4] = next_rec.to_bytes(4, "little")
            records.append(bytes(r))
        path = tmp_path / "chain.rbm"
        path.write_bytes(b"".join(records))

        result = runner.invoke(
            rbm_dev_app, ["follow-chain", str(path), "--from", "1", "--max-steps", "2"]
        )
        assert result.exit_code == 0, result.output
        assert "max-steps" in result.output
        assert "visited 2 records" in result.output


class TestRbmDevScan:
    def test_tag_frequencies_on_synthetic_fixture(
        self, synthetic_rbm: Path
    ) -> None:
        # The synthetic fixture has 16 records; the only record carrying a
        # meaningful tag is record 0 (gddh) and record 2 (gits).
        result = runner.invoke(
            rbm_dev_app, ["scan", str(synthetic_rbm), "--tags"]
        )
        assert result.exit_code == 0, result.output
        assert "gddh" in result.output
        assert "gits" in result.output
        # Most records (13/16) hold padding only — the dominant "tag" should
        # be 4 NUL bytes, rendered as its hex repr.
        assert "00000000" in result.output

    def test_no_tags_flag_exits_zero_with_notice(
        self, synthetic_rbm: Path
    ) -> None:
        result = runner.invoke(rbm_dev_app, ["scan", str(synthetic_rbm)])
        assert result.exit_code == 0
        assert "--tags" in result.output

    def test_missing_file_errors(self, tmp_path: Path) -> None:
        result = runner.invoke(
            rbm_dev_app,
            ["scan", str(tmp_path / "missing.rbm"), "--tags"],
        )
        assert result.exit_code == 1


class TestRbmExport:
    def test_dataset_path_is_repeatable_and_lands_in_the_document(
        self, synthetic_rbm: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "dataset"
        result = runner.invoke(
            rbm_app,
            [
                "export",
                str(synthetic_rbm),
                "--out",
                str(out),
                "--types",
                "fft",
                "--dataset-path",
                "Bunge",
                "--dataset-path",
                "Cartagena",
            ],
        )
        assert result.exit_code == 0, result.output
        document = json.loads((out / "dataset.json").read_text(encoding="utf-8"))
        assert document["path"] == ["Bunge", "Cartagena"]

    def test_without_the_option_nothing_is_claimed(
        self, synthetic_rbm: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "dataset"
        result = runner.invoke(
            rbm_app, ["export", str(synthetic_rbm), "--out", str(out), "--types", "fft"]
        )
        assert result.exit_code == 0, result.output
        document = json.loads((out / "dataset.json").read_text(encoding="utf-8"))
        assert "path" not in document


class TestStats:
    def test_summary_runs_on_synthetic(self, synthetic_rbm: Path) -> None:
        result = runner.invoke(rbm_app, ["stats", "summary", str(synthetic_rbm)])
        assert result.exit_code == 0, result.output
        assert "machines" in result.output

    def test_machines_runs_on_synthetic(self, synthetic_rbm: Path) -> None:
        result = runner.invoke(rbm_app, ["stats", "machines", str(synthetic_rbm)])
        assert result.exit_code == 0, result.output
        assert "TOTAL" in result.output

    def test_machines_rejects_bad_sort(self, synthetic_rbm: Path) -> None:
        result = runner.invoke(
            rbm_app, ["stats", "machines", str(synthetic_rbm), "--sort", "nope"]
        )
        assert result.exit_code == 1

    def test_missing_file_exits_nonzero(self, tmp_path: Path) -> None:
        result = runner.invoke(
            rbm_app, ["stats", "summary", str(tmp_path / "missing.rbm")]
        )
        assert result.exit_code == 1
