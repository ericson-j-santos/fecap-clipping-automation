from __future__ import annotations

import argparse
from datetime import datetime, time, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gdelt_api import GdeltError, collect_fecap_public

DEFAULT_OUTPUT = ROOT / "data" / "private" / "gdelt-fecap-items.json"
DEFAULT_EVIDENCE = ROOT / "evidence" / "private" / "gdelt-public-collector-run.json"


def _parse_day(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("data deve usar YYYY-MM-DD") from exc


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Coleta clipping FECAP via GDELT DOC 2.0 sem chave de API"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--max-records", type=int, default=250)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    if ns.check:
        print(
            "mode=one_shot provider=gdelt-doc-2.0 credentials_required=false "
            "max_records=250 scheduled=false production_enabled=false"
        )
        return 0
    if not ns.once:
        print("BLOCKED: --once obrigatório", file=sys.stderr)
        return 50
    if not ns.start_date or not ns.end_date:
        print("BLOCKED: --start-date e --end-date são obrigatórios", file=sys.stderr)
        return 50
    try:
        start = _parse_day(ns.start_date)
        end_day = _parse_day(ns.end_date)
        end = datetime.combine(end_day.date(), time(23, 59, 59), tzinfo=timezone.utc)
        if end < start:
            raise ValueError("data final anterior à inicial")
        if (end.date() - start.date()).days > 92:
            raise ValueError("janela maior que 93 dias não é suportada pelo GDELT DOC 2.0")
        payload = collect_fecap_public(start, end, max_records=ns.max_records)
    except (ValueError, GdeltError, OSError) as exc:
        evidence = {
            "status": "BLOCKED",
            "provider": "GDELT DOC 2.0",
            "error_type": type(exc).__name__,
            "correlation_id": f"gdelt-{uuid4()}",
            "credentials_persisted": False,
            "raw_response_persisted": False,
            "production_enabled": False,
            "scheduled": False,
        }
        ns.evidence.parent.mkdir(parents=True, exist_ok=True)
        ns.evidence.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 50

    correlation_id = f"gdelt-{uuid4()}"
    payload["correlation_id"] = correlation_id
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    evidence = {
        "status": "PASS",
        "provider": payload["provider"],
        "correlation_id": correlation_id,
        "window": payload["window"],
        "item_count": len(payload["items"]),
        "source_article_count": payload["source_article_count"],
        "rejected_article_count": payload["rejected_article_count"],
        "output_path": str(ns.output),
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "production_enabled": False,
        "scheduled": False,
    }
    ns.evidence.parent.mkdir(parents=True, exist_ok=True)
    ns.evidence.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
