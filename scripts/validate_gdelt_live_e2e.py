from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.excel_homologation import build_workbook_bytes, validate_collector_output

DEFAULT_COLLECTOR = ROOT / "data" / "private" / "gdelt-fecap-items.json"
DEFAULT_COLLECTOR_EVIDENCE = ROOT / "evidence" / "private" / "gdelt-public-collector-run.json"
DEFAULT_WORKBOOK = ROOT / "data" / "private" / "gdelt-fallback-homologacao.xlsx"
DEFAULT_EXCEL_EVIDENCE = ROOT / "evidence" / "private" / "gdelt-fallback-excel.json"
DEFAULT_PEOPLE = ROOT / "config" / "people.json"
DEFAULT_ENRICHMENT = ROOT / "config" / "video_enrichment.json"
DEFAULT_EVIDENCE = ROOT / "evidence" / "private" / "gdelt-live-e2e.json"
CONTRACT = "fecap-gdelt-live-e2e/1.0.0"


def _read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("json_not_object")
    return value


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _require_false(payload: dict, key: str) -> None:
    if payload.get(key) is not False:
        raise ValueError(f"{key}_must_be_false")


def _blocked(path: Path, *, phase: str, error_code: str, git_sha: str | None, run_id: str | None) -> int:
    payload = {
        "status": "BLOCKED",
        "contract": CONTRACT,
        "phase": phase,
        "error_code": error_code,
        "git_sha": git_sha,
        "run_id": run_id,
        "scheduled": False,
        "production_enabled": False,
    }
    _write_json(path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 50


def _validate_git_sha(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    text = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", text) is None:
        raise ValueError("git_sha_invalid")
    return text


def _validate_run_id(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    if re.fullmatch(r"[0-9]+", text) is None:
        raise ValueError("run_id_invalid")
    return text


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valida a evidência live GDELT -> Excel com vínculo de execução e controles contra falso positivo"
    )
    parser.add_argument("--collector", type=Path, default=DEFAULT_COLLECTOR)
    parser.add_argument("--collector-evidence", type=Path, default=DEFAULT_COLLECTOR_EVIDENCE)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--excel-evidence", type=Path, default=DEFAULT_EXCEL_EVIDENCE)
    parser.add_argument("--people", type=Path, default=DEFAULT_PEOPLE)
    parser.add_argument("--enrichment", type=Path, default=DEFAULT_ENRICHMENT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--git-sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"))
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    if ns.check:
        print(
            f"contract={CONTRACT} provider=gdelt-doc-2.0 "
            "live_items_required=true correlation_binding=true deterministic_rebuild=true "
            "negative_control=true scheduled=false production_enabled=false"
        )
        return 0

    try:
        git_sha = _validate_git_sha(ns.git_sha)
        run_id = _validate_run_id(ns.run_id)
    except ValueError as exc:
        return _blocked(
            ns.evidence,
            phase="execution_identity",
            error_code=str(exc),
            git_sha=None,
            run_id=None,
        )

    required = (
        ns.collector,
        ns.collector_evidence,
        ns.workbook,
        ns.excel_evidence,
        ns.people,
        ns.enrichment,
    )
    if any(not path.is_file() for path in required):
        return _blocked(
            ns.evidence,
            phase="precondition",
            error_code="required_file_missing",
            git_sha=git_sha,
            run_id=run_id,
        )

    try:
        collector = _read_object(ns.collector)
        collector_evidence = _read_object(ns.collector_evidence)
        excel_evidence = _read_object(ns.excel_evidence)
        people = _read_object(ns.people)
        enrichment = _read_object(ns.enrichment)

        if collector.get("provider") != "GDELT DOC 2.0":
            raise ValueError("collector_provider_invalid")
        if collector_evidence.get("status") != "PASS":
            raise ValueError("collector_status_not_pass")
        if collector_evidence.get("provider") != collector.get("provider"):
            raise ValueError("provider_mismatch")

        correlation_id = str(collector.get("correlation_id") or "").strip()
        if not correlation_id:
            raise ValueError("correlation_id_missing")
        if collector_evidence.get("correlation_id") != correlation_id:
            raise ValueError("collector_correlation_mismatch")

        items = collector.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("live_items_missing")
        item_count = collector_evidence.get("item_count")
        if isinstance(item_count, bool) or not isinstance(item_count, int) or item_count != len(items):
            raise ValueError("collector_item_count_mismatch")

        validate_collector_output(collector)
        for payload in (collector, collector_evidence):
            _require_false(payload, "credentials_persisted")
            _require_false(payload, "raw_response_persisted")
            _require_false(payload, "production_enabled")
            _require_false(payload, "scheduled")

        collector_sha = _sha256_file(ns.collector)
        workbook_sha = _sha256_file(ns.workbook)

        if excel_evidence.get("status") != "PASS":
            raise ValueError("excel_status_not_pass")
        if excel_evidence.get("source_correlation_id") != correlation_id:
            raise ValueError("excel_correlation_mismatch")
        if excel_evidence.get("source_payload_sha256") != collector_sha:
            raise ValueError("excel_source_sha_mismatch")
        if excel_evidence.get("source_provider") != "GDELT DOC 2.0":
            raise ValueError("excel_source_provider_invalid")
        counts = excel_evidence.get("counts")
        if not isinstance(counts, dict) or counts.get("items") != len(items):
            raise ValueError("excel_item_count_mismatch")
        if excel_evidence.get("workbook_sha256") != workbook_sha:
            raise ValueError("workbook_sha_mismatch")
        for key in (
            "credentials_persisted",
            "raw_response_persisted",
            "production_enabled",
            "scheduled",
            "external_destination_enabled",
        ):
            _require_false(excel_evidence, key)

        rebuilt, rebuilt_evidence = build_workbook_bytes(
            collector,
            people,
            {},
            enrichment_rules=enrichment,
        )
        if sha256(rebuilt).hexdigest() != workbook_sha or rebuilt != ns.workbook.read_bytes():
            raise ValueError("deterministic_rebuild_mismatch")
        if rebuilt_evidence.get("counts") != counts:
            raise ValueError("deterministic_counts_mismatch")

        negative = json.loads(json.dumps(collector))
        negative["credentials_persisted"] = True
        try:
            build_workbook_bytes(negative, people, {}, enrichment_rules=enrichment)
        except ValueError:
            negative_control_passed = True
        else:
            negative_control_passed = False
        if not negative_control_passed:
            raise ValueError("negative_control_failed")

        payload = {
            "status": "PASS",
            "contract": CONTRACT,
            "provider": "GDELT DOC 2.0",
            "git_sha": git_sha,
            "run_id": run_id,
            "correlation_id": correlation_id,
            "item_count": len(items),
            "identity_counts": collector_evidence.get("identity_counts"),
            "source_payload_sha256": collector_sha,
            "workbook_sha256": workbook_sha,
            "deterministic_rebuild": True,
            "negative_control_passed": True,
            "independent_file_hash_verified": True,
            "scheduled": False,
            "production_enabled": False,
        }
        _write_json(ns.evidence, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        error_code = str(exc)
        if not re.fullmatch(r"[a-z0-9_]+", error_code):
            error_code = type(exc).__name__.lower()
        return _blocked(
            ns.evidence,
            phase="validation",
            error_code=error_code,
            git_sha=git_sha,
            run_id=run_id,
        )


if __name__ == "__main__":
    raise SystemExit(main())
