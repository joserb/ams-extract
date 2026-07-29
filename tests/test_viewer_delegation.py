"""``rbm serve <dataset>`` delegates to the external ``vibframe-viewer``.

The dataset viewer lives in the ecosystem repo ``vibframe-viewer`` (Parts 1
and 4 of t8-extract's workplan 03); ams-extract's own ``export/viewer.py``
was dropped on 2026-07-29. What is left here is a thin wrapper, and these
tests guard that boundary: that the package is installed, that the ``rbm``
options reach its CLI correctly translated, and that a dataset shaped like
the ones ``rbm export`` writes is actually readable by it. The viewer's own
coverage lives in its repo.

The ``.rbm`` backend (``rbm serve FILE.rbm``) is *not* delegated: it renders
straight from the database with no export, and stays as this repo's own
debugging tool (see ``tests/test_live_viewer.py``).

The dataset comes from the shared ``vibframe_dataset`` fixture (conftest),
which writes one through the very row builders and parquet writer of
``rbm export`` — the same dataset ``tests/test_vibframe_conformance.py``
puts through ``vibframe-validate``.
"""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from urllib.request import urlopen

import pytest
from typer.testing import CliRunner

from ams_extract.cli import app as rbm_app

runner = CliRunner()


class TestServeDelegation:
    def test_dataset_directory_delegates_translating_the_arguments(
        self, vibframe_dataset: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import vibframe_viewer.cli as viewer_cli

        ds = vibframe_dataset
        seen: dict[str, argparse.Namespace] = {}

        def _fake_serve(args: argparse.Namespace) -> int:
            seen["args"] = args
            return 0

        monkeypatch.setattr(viewer_cli, "_cmd_serve", _fake_serve)
        result = runner.invoke(
            rbm_app, ["serve", str(ds), "--port", "0", "--host", "0.0.0.0", "--no-browser"]
        )

        assert result.exit_code == 0, result.output
        args = seen["args"]
        assert args.path == ds
        assert (args.host, args.port, args.no_browser) == ("0.0.0.0", 0, True)

    def test_delegation_propagates_the_viewer_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import vibframe_viewer.cli as viewer_cli

        ds = tmp_path / "empty"
        ds.mkdir()
        monkeypatch.setattr(viewer_cli, "_cmd_serve", lambda args: 1)
        result = runner.invoke(rbm_app, ["serve", str(ds), "--no-browser"])
        assert result.exit_code == 1

    def test_missing_source_is_rejected(self, tmp_path: Path) -> None:
        result = runner.invoke(rbm_app, ["serve", str(tmp_path / "nope"), "--no-browser"])
        assert result.exit_code == 1
        assert "not a .rbm file or dataset directory" in result.output


class TestViewerReadsOurLayout:
    """The exported layout is readable by the ecosystem viewer, end to end."""

    def test_index_and_tree_are_served(self, vibframe_dataset: Path) -> None:
        from vibframe_viewer.server import serve as viewer_serve

        server = viewer_serve(vibframe_dataset, host="127.0.0.1", port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urlopen(f"{base}/") as resp:
                assert resp.status == 200
                assert b"<!DOCTYPE html>" in resp.read()
            with urlopen(f"{base}/api/tree") as resp:
                assert resp.status == 200
                tree = json.loads(resp.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert "Bomba EQ" in json.dumps(tree, ensure_ascii=False)
