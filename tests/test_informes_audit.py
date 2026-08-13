from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _observation(index: int, text: str, weight: float = 1.0) -> dict[str, object]:
    return {
        "observation_id": f"o-{index}",
        "record_kind": "primary",
        "machine": {"external_tag": "M.1"},
        "modality": "vibration",
        "diagnosis_text": text,
        "findings": [
            {
                "label_quality": "unmapped",
                "weight": weight,
            }
        ],
    }


def test_the_unmapped_audit_is_reproducible_and_classifies_clauses(tmp_path: Path) -> None:
    document = {
        "provenance": {"extractor": "informes-gt-extract 0.4.0"},
        "observations": [
            _observation(1, "Posible suciedad en la válvula"),
            _observation(2, "Informar a Preditec si se ha intervenido"),
            _observation(3, "Estable"),
        ],
    }
    (tmp_path / "sample.diaggt.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/audit_informes_unmapped.py",
            str(tmp_path),
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)

    assert report["documents"] == 1
    assert report["observations"] == 3
    assert report["unmapped_findings"] == 3
    assert report["distinct_texts"] == 3
    assert report["published_unmapped_mass"] == 3.0
    assert report["current_unmapped_findings"] == 1
    assert report["current_unmapped_mass"] == 1.0
    assert report["classification_observations"] == {
        "true_fault": 1,
        "healthy_or_stable": 1,
        "administrative_request": 1,
        "insufficient_context": 0,
    }
    assert report["classification_published_mass"] == {
        "true_fault": 1.0,
        "healthy_or_stable": 1.0,
        "administrative_request": 1.0,
        "insufficient_context": 0.0,
    }
    by_text = {entry["diagnosis_text"]: entry for entry in report["texts"]}
    assert by_text["Posible suciedad en la válvula"]["clauses"][0]["rules"][0]["rule"] == (
        "GT026"
    )
    assert by_text["Informar a Preditec si se ha intervenido"]["current_findings"][0][
        "label_quality"
    ] == "unmapped"
    assert by_text["Estable"]["current_findings"] == []


def _matrix_audit_module():
    path = Path("scripts/audit_informes_status_matrix.py")
    spec = importlib.util.spec_from_file_location("audit_informes_status_matrix", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_matrix_audit_uses_a_closed_icon_catalog() -> None:
    module = _matrix_audit_module()

    assert set(module.ICON_STATUS.values()) == {
        "OK",
        "WATCH",
        "ALERT",
        "DANGER",
        "STOPPED",
        "NOT_MEASURED",
        "OUT_OF_SERVICE",
    }
    assert module._machine_ref("PM.100 - Bomba Centrifuga") == (
        "PM.100",
        "Bomba Centrifuga",
    )
    assert module._machine_ref("BOMBA CENTRIFUGA PM.2001") == (
        "PM.2001",
        "BOMBA CENTRIFUGA",
    )
    assert module._machine_ref("Máquina ruta Fuera de Ruta") == (
        "Máquina ruta Fuera de Ruta",
        "Máquina ruta Fuera de Ruta",
    )


@pytest.mark.integration
def test_the_status_matrix_corpus_has_no_unknown_icons(tmp_path: Path) -> None:
    import os

    source = os.environ.get("INFORMES_TEST_DIR")
    if not source:
        pytest.skip("INFORMES_TEST_DIR not set; integration test skipped")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/audit_informes_status_matrix.py",
            source,
            "--out",
            str(tmp_path / "matrix.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)
    assert report["documents"] == 6
    assert report["unknown_icon_signatures"] == []
