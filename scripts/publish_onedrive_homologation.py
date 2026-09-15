from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.onedrive_homologation import OneDriveHomologationError, publish_workbook

DEFAULT_WORKBOOK = ROOT / "data" / "private" / "fecap-clipping-homologacao.xlsx"
DEFAULT_EVIDENCE = ROOT / "evidence" / "private" / "onedrive-homologation-run.json"


def write_evidence(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publica Excel FECAP em OneDrive sincronizado, one-shot")
    parser.add_argument("--input", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--destination-root", type=Path)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true")
    ns = parser.parse_args()

    if ns.check:
        print("mode=one_shot onedrive_sync=true scheduled=false production_enabled=false")
        return 0
    if not ns.once:
        print("status=BLOCKED reason=one_shot_authorization_missing")
        return 50
    if ns.destination_root is None:
        print("status=BLOCKED reason=destination_root_missing")
        return 50

    try:
        evidence = publish_workbook(ns.input, ns.destination_root)
    except OneDriveHomologationError as exc:
        evidence = {"status": "BLOCKED", "reason": str(exc), "scheduled": False, "production_enabled": False}
        write_evidence(ns.evidence, evidence)
        print(json.dumps(evidence, ensure_ascii=False))
        return 50

    write_evidence(ns.evidence, evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
