from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.excel_homologation import build_workbook_bytes

SCRIPT = ROOT / "scripts" / "validate_gdelt_live_e2e.py"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture() -> tuple[dict, dict, dict]:
    collector = {
        "format": 1,
        "provider": "GDELT DOC 2.0",
        "correlation_id": "gdelt-live-test-123",
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "production_enabled": False,
        "scheduled": False,
        "items": [
            {
                "external_id": "https://mercadocomum.com/exemplo",
                "title": "Déficit nominal das contas públicas brasileiras",
                "url": "https://mercadocomum.com/exemplo",
                "source": "Mercado Comum",
                "published_at": "2026-08-31T12:00:00Z",
                "text": "O professor Ahmed El Khatib, da FECAP, comentou os dados.",
                "institution_identity": "confirmed",
            }
        ],
    }
    collector_evidence = {
        "status": "PASS",
        "provider": "GDELT DOC 2.0",
        "correlation_id": collector["correlation_id"],
        "item_count": 1,
        "identity_counts": {
            "confirmed": 1,
            "homonym": 0,
            "ambiguous": 0,
            "fetch_failed": 0,
        },
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "production_enabled": False,
        "scheduled": False,
    }
    people = json.loads((ROOT / "config" / "people.json").read_text(encoding="utf-8"))
    enrichment = json.loads(
        (ROOT / "config" / "video_enrichment.json").read_text(encoding="utf-8")
    )
    return collector, collector_evidence, {"people": people, "enrichment": enrichment}


def _prepare(temp: Path) -> dict[str, Path]:
    collector, collector_evidence, config = _fixture()
    collector_path = temp / "collector.json"
    collector_evidence_path = temp / "collector-evidence.json"
    workbook_path = temp / "workbook.xlsx"
    excel_evidence_path = temp / "excel-evidence.json"
    output_evidence = temp / "gold-evidence.json"

    _write_json(collector_path, collector)
    _write_json(collector_evidence_path, collector_evidence)

    workbook, excel_evidence = build_workbook_bytes(
        collector,
        config["people"],
        {},
        enrichment_rules=config["enrichment"],
    )
    workbook_path.write_bytes(workbook)
    excel_evidence.update(
        {
            "source_correlation_id": collector["correlation_id"],
            "source_payload_sha256": sha256(collector_path.read_bytes()).hexdigest(),
            "source_provider": collector["provider"],
            "external_destination_enabled": False,
        }
    )
    _write_json(excel_evidence_path, excel_evidence)

    return {
        "collector": collector_path,
        "collector_evidence": collector_evidence_path,
        "workbook": workbook_path,
        "excel_evidence": excel_evidence_path,
        "evidence": output_evidence,
    }


def _run(paths: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--collector",
            str(paths["collector"]),
            "--collector-evidence",
            str(paths["collector_evidence"]),
            "--workbook",
            str(paths["workbook"]),
            "--excel-evidence",
            str(paths["excel_evidence"]),
            "--evidence",
            str(paths["evidence"]),
            "--git-sha",
            "a" * 40,
            "--run-id",
            "12345",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_check_contract() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "correlation_binding=true" in completed.stdout
    assert "negative_control=true" in completed.stdout


def test_live_e2e_manifest_passes_with_bound_evidence() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        paths = _prepare(Path(temp_dir))
        completed = _run(paths)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        payload = json.loads(paths["evidence"].read_text(encoding="utf-8"))
        assert payload["status"] == "PASS"
        assert payload["git_sha"] == "a" * 40
        assert payload["run_id"] == "12345"
        assert payload["correlation_id"] == "gdelt-live-test-123"
        assert payload["item_count"] == 1
        assert payload["deterministic_rebuild"] is True
        assert payload["negative_control_passed"] is True
        assert payload["independent_file_hash_verified"] is True


def test_tampered_workbook_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        paths = _prepare(Path(temp_dir))
        paths["workbook"].write_bytes(paths["workbook"].read_bytes() + b"tamper")
        completed = _run(paths)
        assert completed.returncode == 50
        payload = json.loads(paths["evidence"].read_text(encoding="utf-8"))
        assert payload["status"] == "BLOCKED"
        assert payload["error_code"] == "workbook_sha_mismatch"


def main() -> int:
    test_check_contract()
    test_live_e2e_manifest_passes_with_bound_evidence()
    test_tampered_workbook_fails_closed()
    print("test_gdelt_live_e2e: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
