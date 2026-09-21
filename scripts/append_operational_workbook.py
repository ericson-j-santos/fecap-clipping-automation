from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.excel_homologation import build_model, classify_items, validate_collector_output
from src.operational_workbook import OperationalWorkbookError, append_month_rows

DEFAULT_PEOPLE = ROOT / "config" / "people.json"
DEFAULT_ENRICHMENT = ROOT / "config" / "video_enrichment.json"
DEFAULT_EVIDENCE = ROOT / "evidence" / "private" / "operational-workbook-append.json"


def _load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON deve ser objeto: {path}")
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Anexa clipping classificado a um workbook operacional existente, de forma idempotente"
    )
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--collector", type=Path)
    parser.add_argument("--people", type=Path, default=DEFAULT_PEOPLE)
    parser.add_argument("--tiers", type=Path)
    parser.add_argument("--enrichment", type=Path, default=DEFAULT_ENRICHMENT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    if ns.check:
        print(
            "mode=one_shot contract=clipping-operational-append/1.0.0 "
            "headers=9 fail_closed=true scheduled=false production_enabled=false"
        )
        return 0
    if not ns.once:
        print("BLOCKED: --once obrigatório", file=sys.stderr)
        return 50
    if ns.workbook is None or ns.collector is None:
        print("BLOCKED: --workbook e --collector são obrigatórios", file=sys.stderr)
        return 50
    if ns.output is not None and ns.in_place:
        print("BLOCKED: use --output ou --in-place, não ambos", file=sys.stderr)
        return 50
    if ns.output is None and not ns.in_place:
        print("BLOCKED: destino ausente; informe --output ou --in-place", file=sys.stderr)
        return 50

    required = [ns.workbook, ns.collector, ns.people, ns.enrichment]
    if any(path is None or not path.is_file() for path in required):
        print("BLOCKED: workbook/collector/configuração ausente", file=sys.stderr)
        return 50

    try:
        collector = _load_object(ns.collector)
        people = _load_object(ns.people)
        tiers = _load_object(ns.tiers) if ns.tiers else {}
        enrichment = _load_object(ns.enrichment)
        candidates = validate_collector_output(collector)
        classified = classify_items(candidates, people, tiers, enrichment)
        model = build_model(classified)
        original = ns.workbook.read_bytes()
        result = append_month_rows(original, model["month_rows"])
    except (OSError, json.JSONDecodeError, ValueError, OperationalWorkbookError) as exc:
        payload = {
            "status": "BLOCKED",
            "phase": "operational_workbook_append",
            "error_type": type(exc).__name__,
            "scheduled": False,
            "production_enabled": False,
            "secrets_captured": False,
        }
        _write_json(ns.evidence, payload)
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 50

    target = ns.workbook if ns.in_place else ns.output
    assert target is not None
    if not result.evidence["no_op"] or target != ns.workbook:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target == ns.workbook:
            fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
            os.close(fd)
            temp = Path(temp_name)
            try:
                temp.write_bytes(result.workbook)
                os.replace(temp, target)
            finally:
                if temp.exists():
                    temp.unlink()
        else:
            target.write_bytes(result.workbook)

    evidence = dict(result.evidence)
    evidence.update({
        "status": "PASS",
        "output_path": str(target),
        "input_item_count": model["counts"]["items"],
        "classified_include_count": model["counts"]["include"],
        "classified_review_count": model["counts"]["review"],
        "classified_exclude_count": model["counts"]["exclude"],
        "in_place": bool(ns.in_place),
        "scheduled": False,
        "production_enabled": False,
    })
    _write_json(ns.evidence, evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
