from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.knewin_collector_plan import CollectorPlanError, build_collector_plan

DEFAULT_INPUT = Path(os.environ.get(
    "KNEWIN_ENDPOINT_CANDIDATES",
    str(ROOT / "evidence" / "private" / "knewin-endpoint-candidates.json"),
))
DEFAULT_OUTPUT = Path(os.environ.get(
    "KNEWIN_COLLECTOR_PLAN",
    str(ROOT / "evidence" / "private" / "knewin-collector-plan.json"),
))


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepara coletor somente a partir de endpoint Knewin observado")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rank", type=int, default=1)
    ns = parser.parse_args()

    if not ns.input.is_file():
        print(f"COLLECTOR_PLAN_BLOCKED: evidência ausente: {ns.input}", file=sys.stderr)
        return 30
    try:
        discovery = json.loads(ns.input.read_text(encoding="utf-8"))
        plan = build_collector_plan(discovery, rank=ns.rank)
    except (OSError, json.JSONDecodeError, CollectorPlanError) as exc:
        print(f"COLLECTOR_PLAN_BLOCKED: {exc}", file=sys.stderr)
        return 31

    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
