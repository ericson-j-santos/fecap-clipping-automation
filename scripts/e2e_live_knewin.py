from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.excel_homologation import build_model, classify_items, validate_collector_output
from src.knewin_api import KnewinApiError, KnewinNews, collect_fecap
from src.operational_workbook import OperationalWorkbookError, append_month_rows

DEFAULT_EVIDENCE_DIR = ROOT / "evidence" / "private"
DEFAULT_COLLECTOR = ROOT / "data" / "private" / "knewin-live-api-items.json"
CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class LiveE2EError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_correlation_id(value: str) -> str:
    correlation_id = str(value or "").strip()
    if not CORRELATION_PATTERN.fullmatch(correlation_id):
        raise LiveE2EError("correlation_id_invalid")
    return correlation_id


def collector_payload(collected: list[KnewinNews]) -> dict:
    return {
        "format": 1,
        "mode": "one_shot",
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "production_enabled": False,
        "items": [
            {
                "external_id": item.external_id,
                "title": item.candidate.title,
                "url": item.candidate.url,
                "source": item.candidate.source,
                "published_at": item.candidate.published_at,
                "text": item.candidate.text,
            }
            for item in collected
        ],
    }


def tiers_from_collected(collected: list[KnewinNews]) -> dict[str, int]:
    tiers: dict[str, int] = {}
    for item in collected:
        if item.tier is None:
            continue
        source = item.candidate.source.strip()
        if not source:
            continue
        previous = tiers.get(source)
        if previous is not None and previous != item.tier:
            raise LiveE2EError("tier_conflict")
        tiers[source] = item.tier
    return tiers


def execute_operational_roundtrip(
    workbook_bytes: bytes,
    collected: list[KnewinNews],
    people: dict,
    enrichment_rules: dict,
) -> dict:
    payload = collector_payload(collected)
    candidates = validate_collector_output(payload)
    tiers = tiers_from_collected(collected)
    classified = classify_items(candidates, people, tiers, enrichment_rules)
    model = build_model(classified)

    first = append_month_rows(workbook_bytes, model["month_rows"])
    if first.evidence.get("status") != "PASS":
        raise LiveE2EError("append_not_pass")
    appended_count = first.evidence.get("appended_count")
    if isinstance(appended_count, bool) or not isinstance(appended_count, int):
        raise LiveE2EError("append_count_invalid")
    if appended_count < 1:
        raise LiveE2EError("positive_append_missing")

    replay = append_month_rows(first.workbook, model["month_rows"])
    if replay.evidence.get("status") != "PASS":
        raise LiveE2EError("replay_not_pass")
    if replay.evidence.get("appended_count") != 0:
        raise LiveE2EError("replay_appended_new_rows")
    if replay.evidence.get("no_op") is not True:
        raise LiveE2EError("replay_not_noop")
    if replay.workbook != first.workbook:
        raise LiveE2EError("replay_changed_workbook")
    if replay.evidence.get("input_sha256") != first.evidence.get("output_sha256"):
        raise LiveE2EError("replay_input_sha_mismatch")
    if replay.evidence.get("output_sha256") != first.evidence.get("output_sha256"):
        raise LiveE2EError("replay_output_sha_mismatch")

    return {
        "collector": payload,
        "tiers": tiers,
        "model_counts": model["counts"],
        "first": first,
        "replay": replay,
    }


def _load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LiveE2EError("configuration_not_object")
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _resolve_required_workbook() -> Path:
    raw = os.environ.get("KNEWIN_WORKBOOK_PATH", "").strip()
    if not raw:
        raise LiveE2EError("workbook_path_missing")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    else:
        path = path.resolve()
    if not path.is_file():
        raise LiveE2EError("workbook_missing")
    return path


def _output_paths() -> tuple[Path, Path, Path, Path]:
    evidence = Path(
        os.environ.get(
            "KNEWIN_EVIDENCE_PATH",
            str(DEFAULT_EVIDENCE_DIR / "e2e-live-summary.json"),
        )
    ).expanduser()
    output = Path(
        os.environ.get(
            "KNEWIN_OUTPUT_WORKBOOK_PATH",
            str(DEFAULT_EVIDENCE_DIR / "Clipping_2026.live.validado.xlsx"),
        )
    ).expanduser()
    replay = Path(
        os.environ.get(
            "KNEWIN_REPLAY_WORKBOOK_PATH",
            str(DEFAULT_EVIDENCE_DIR / "Clipping_2026.live.replay.xlsx"),
        )
    ).expanduser()
    collector = Path(
        os.environ.get("KNEWIN_COLLECTOR_PATH", str(DEFAULT_COLLECTOR))
    ).expanduser()
    return evidence.resolve(), output.resolve(), replay.resolve(), collector.resolve()


def _blocked(
    evidence_path: Path,
    *,
    correlation_id: str,
    reason: str,
    git_sha: str | None,
) -> int:
    payload = {
        "status": "BLOCKED",
        "contract": "fecap-knewin-live-operational-e2e/2.0.0",
        "correlation_id": correlation_id,
        "reason": reason,
        "git_sha": git_sha,
        "live_knewin_validated": False,
        "workbook_roundtrip_validated": False,
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "scheduled": False,
        "production_enabled": False,
    }
    _write_json(evidence_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 20


def main() -> int:
    raw_correlation = os.environ.get("CORRELATION_ID", "knewin-live-e2e")
    try:
        correlation_id = validate_correlation_id(raw_correlation)
    except LiveE2EError:
        correlation_id = "invalid-correlation-id"

    evidence_path, output_path, replay_path, collector_path = _output_paths()
    git_sha = os.environ.get("GITHUB_SHA") or None

    api_key = os.environ.get("KNEWIN_API_KEY", "").strip()
    if not api_key:
        return _blocked(
            evidence_path,
            correlation_id=correlation_id,
            reason="knewin_api_key_missing",
            git_sha=git_sha,
        )

    try:
        correlation_id = validate_correlation_id(raw_correlation)
        workbook_path = _resolve_required_workbook()
        start = parse_utc(os.environ.get("KNEWIN_START", "2026-08-01T00:00:00Z"))
        end = parse_utc(os.environ.get("KNEWIN_END", "2026-08-31T23:59:59Z"))
        if end < start:
            raise LiveE2EError("invalid_date_window")

        people = _load_object(ROOT / "config" / "people.json")
        enrichment = _load_object(ROOT / "config" / "video_enrichment.json")
        collected = collect_fecap(api_key, start, end)
        if not collected:
            raise LiveE2EError("no_knewin_items")

        source_bytes = workbook_path.read_bytes()
        source_sha = sha256(source_bytes).hexdigest()
        result = execute_operational_roundtrip(
            source_bytes,
            collected,
            people,
            enrichment,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        replay_path.parent.mkdir(parents=True, exist_ok=True)
        result["first"].workbook and output_path.write_bytes(result["first"].workbook)
        result["replay"].workbook and replay_path.write_bytes(result["replay"].workbook)
        _write_json(collector_path, result["collector"])

        output_sha = sha256(output_path.read_bytes()).hexdigest()
        replay_sha = sha256(replay_path.read_bytes()).hexdigest()
        if output_sha != replay_sha:
            raise LiveE2EError("persisted_replay_sha_mismatch")

        summary = {
            "status": "PASS",
            "contract": "fecap-knewin-live-operational-e2e/2.0.0",
            "correlation_id": correlation_id,
            "git_sha": git_sha,
            "source": "Knewin Monitoring API",
            "window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            "collected_fecap": len(collected),
            "classified_counts": result["model_counts"],
            "tier_source_count": len(result["tiers"]),
            "source_workbook_sha256": source_sha,
            "output_workbook_sha256": output_sha,
            "replay_workbook_sha256": replay_sha,
            "appended_count": result["first"].evidence["appended_count"],
            "initial_duplicate_count": result["first"].evidence["duplicate_count"],
            "replay_duplicate_count": result["replay"].evidence["duplicate_count"],
            "replay_no_op": True,
            "live_knewin_validated": True,
            "workbook_roundtrip_validated": True,
            "credentials_persisted": False,
            "raw_response_persisted": False,
            "scheduled": False,
            "production_enabled": False,
        }
        _write_json(evidence_path, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except LiveE2EError as exc:
        reason = exc.code
    except KnewinApiError:
        reason = "knewin_api_failed"
    except (OperationalWorkbookError, ValueError):
        reason = "workbook_validation_failed"
    except (OSError, json.JSONDecodeError):
        reason = "io_or_configuration_failed"

    return _blocked(
        evidence_path,
        correlation_id=correlation_id,
        reason=reason,
        git_sha=git_sha,
    )


if __name__ == "__main__":
    raise SystemExit(main())
