from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.excel_homologation import CONTRACT_VERSION, build_workbook_bytes

DEFAULT_INPUT = ROOT / "data" / "private" / "knewin-fecap-items.json"
DEFAULT_PEOPLE = ROOT / "config" / "people.json"
DEFAULT_ENRICHMENT = ROOT / "config" / "video_enrichment.json"
DEFAULT_OUTPUT = ROOT / "data" / "private" / "fecap-clipping-homologacao.xlsx"
DEFAULT_EVIDENCE = ROOT / "evidence" / "private" / "knewin-excel-homologation.json"


def _load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON deve ser objeto: {path}")
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera Excel determinístico de homologação do clipping FECAP")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--people", type=Path, default=DEFAULT_PEOPLE)
    parser.add_argument("--tiers", type=Path)
    parser.add_argument("--enrichment", type=Path, default=DEFAULT_ENRICHMENT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    if ns.check:
        print(
            f"contract=excel-homologation/{CONTRACT_VERSION} "
            "external_destination_enabled=false scheduled=false production_enabled=false"
        )
        return 0
    if not ns.input.is_file() or not ns.people.is_file() or not ns.enrichment.is_file():
        print("BLOCKED: input, people.json ou video_enrichment.json ausente", file=sys.stderr)
        return 50

    try:
        collector = _load_object(ns.input)
        people = _load_object(ns.people)
        tiers = _load_object(ns.tiers) if ns.tiers else {}
        enrichment = _load_object(ns.enrichment)
        input_payload = ns.input.read_bytes()
        workbook, evidence = build_workbook_bytes(
            collector, people, tiers, enrichment_rules=enrichment
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 50

    evidence["dry_run"] = bool(ns.dry_run)
    evidence["external_destination_enabled"] = False
    evidence["source_payload_sha256"] = sha256(input_payload).hexdigest()
    evidence["source_correlation_id"] = collector.get("correlation_id")
    evidence["source_provider"] = collector.get("provider")
    if ns.dry_run:
        evidence["output_path"] = None
    else:
        ns.output.parent.mkdir(parents=True, exist_ok=True)
        ns.output.write_bytes(workbook)
        evidence["output_path"] = str(ns.output)
    _write_json(ns.evidence, evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
