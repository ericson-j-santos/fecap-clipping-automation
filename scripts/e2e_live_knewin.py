from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clipping import classify, ensure_schema, idempotency_key, persist
from knewin_api import collect_fecap


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> int:
    api_key = os.environ.get("KNEWIN_API_KEY", "").strip()
    if not api_key:
        print("E2E_BLOCKED: KNEWIN_API_KEY ausente", file=sys.stderr)
        return 20

    start = parse_utc(os.environ.get("KNEWIN_START", "2026-08-01T00:00:00Z"))
    end = parse_utc(os.environ.get("KNEWIN_END", "2026-08-31T23:59:59Z"))
    correlation_id = os.environ.get("CORRELATION_ID", "knewin-live-e2e")

    people = json.loads((ROOT / "config" / "people.json").read_text(encoding="utf-8"))
    collected = collect_fecap(api_key, start, end)
    tiers = {
        item.candidate.source: item.tier
        for item in collected
        if item.tier is not None
    }

    classified = [
        (item, classify(item.candidate, people, tiers))
        for item in collected
    ]
    positive = next(((item, d) for item, d in classified if d.status == "include"), None)
    incidental = next(((item, d) for item, d in classified if d.status == "exclude"), None)
    ambiguous = next(((item, d) for item, d in classified if d.status == "review"), None)

    evidence_dir = ROOT / "evidence" / "private"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    db_path = evidence_dir / "homologacao-live.sqlite3"
    if db_path.exists():
        db_path.unlink()

    summary = {
        "correlation_id": correlation_id,
        "source": "Knewin Monitoring API",
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "collected_fecap": len(collected),
        "classified_counts": {
            status: sum(1 for _, decision in classified if decision.status == status)
            for status in ("include", "exclude", "review")
        },
        "status": "BLOCKED",
    }

    missing = [
        name for name, value in (
            ("positive", positive),
            ("incidental", incidental),
            ("ambiguous", ambiguous),
        ) if value is None
    ]
    if missing:
        summary["blocker"] = "casos reais não encontrados: " + ", ".join(missing)
        (evidence_dir / "e2e-live-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 21

    with sqlite3.connect(db_path) as db:
        ensure_schema(db)
        p_item, p_decision = positive
        i_item, i_decision = incidental
        a_item, a_decision = ambiguous

        positive_write = persist(db, p_item.candidate, p_decision)
        incidental_write = persist(db, i_item.candidate, i_decision)
        review_write = persist(db, a_item.candidate, a_decision)
        repeat_write = persist(db, p_item.candidate, p_decision)
        db.commit()

    with sqlite3.connect(db_path) as verify:
        positive_count = verify.execute(
            "SELECT COUNT(*) FROM clipping WHERE idempotency_key=?",
            (idempotency_key(p_item.candidate),),
        ).fetchone()[0]
        incidental_count = verify.execute(
            "SELECT COUNT(*) FROM clipping WHERE idempotency_key=?",
            (idempotency_key(i_item.candidate),),
        ).fetchone()[0]
        review_count = verify.execute(
            "SELECT COUNT(*) FROM review_queue WHERE idempotency_key=?",
            (idempotency_key(a_item.candidate),),
        ).fetchone()[0]

    checks = {
        "positive_inserted": positive_write == "inserted" and positive_count == 1,
        "incidental_not_published": incidental_write == "not_published" and incidental_count == 0,
        "ambiguous_in_review": review_write == "queued" and review_count == 1,
        "idempotent_repeat": repeat_write == "duplicate" and positive_count == 1,
    }
    summary.update(
        {
            "selected_ids": {
                "positive": p_item.external_id,
                "incidental": i_item.external_id,
                "ambiguous": a_item.external_id,
            },
            "checks": checks,
            "status": "PASS" if all(checks.values()) else "FAIL",
        }
    )
    (evidence_dir / "e2e-live-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 22


if __name__ == "__main__":
    raise SystemExit(main())
