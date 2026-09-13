from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.knewin_discovery import attach_schema_evidence, rank_candidates

INPUT_PATH = Path(os.environ.get(
    "KNEWIN_AUTH_EVIDENCE",
    str(ROOT / "evidence" / "private" / "knewin-auth-probe.json"),
))
OUTPUT_PATH = Path(os.environ.get(
    "KNEWIN_ENDPOINT_CANDIDATES",
    str(ROOT / "evidence" / "private" / "knewin-endpoint-candidates.json"),
))


def main() -> int:
    if not INPUT_PATH.is_file():
        print(f"DISCOVERY_BLOCKED: evidência ausente: {INPUT_PATH}", file=sys.stderr)
        return 20
    try:
        evidence = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"DISCOVERY_BLOCKED: evidência inválida: {exc}", file=sys.stderr)
        return 21

    inventory = evidence.get("network_inventory")
    if not isinstance(inventory, dict) or not isinstance(inventory.get("json_endpoints"), list):
        print("DISCOVERY_BLOCKED: network_inventory ausente", file=sys.stderr)
        return 22

    schema_inventory = evidence.get("response_schema_inventory")
    schema_items = []
    schema_truncated = False
    if isinstance(schema_inventory, dict) and isinstance(schema_inventory.get("schemas"), list):
        schema_items = schema_inventory["schemas"]
        schema_truncated = bool(schema_inventory.get("truncated"))

    ranked = rank_candidates(inventory["json_endpoints"], limit=10)
    enriched = attach_schema_evidence(ranked["candidates"], schema_items)
    result = {
        "status": "PASS" if ranked["candidate_count"] else "BLOCKED",
        "source_status": evidence.get("status"),
        "inventory_truncated": bool(inventory.get("truncated")),
        "schema_inventory_truncated": schema_truncated,
        "candidate_count": len(enriched),
        "candidates": enriched,
        "values_persisted": False,
        "secrets_captured": False,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 23


if __name__ == "__main__":
    raise SystemExit(main())
