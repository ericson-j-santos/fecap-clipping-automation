from __future__ import annotations

import argparse
from datetime import datetime, time, timezone
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gdelt_api import GdeltError, collect_fecap_public

DEFAULT_OUTPUT = ROOT / "data" / "private" / "gdelt-fecap-items.json"
DEFAULT_EVIDENCE = ROOT / "evidence" / "private" / "gdelt-public-collector-run.json"
DEFAULT_PEOPLE = ROOT / "config" / "people.json"


def _parse_day(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("data deve usar YYYY-MM-DD") from exc


def _load_people(path: Path) -> tuple[str, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError("people.json deve ser objeto não vazio")
    return tuple(str(name).strip() for name in payload if str(name).strip())


def _resolve_correlation_id(value: str | None) -> str:
    if value is None or not value.strip():
        return f"gdelt-{uuid4()}"
    text = value.strip()
    if re.fullmatch(r"[A-Za-z0-9._:-]{8,160}", text) is None:
        raise ValueError("correlation_id inválido")
    return text


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "json_decode"
    if isinstance(exc, GdeltError):
        message = str(exc)
        http_match = re.fullmatch(r"GDELT respondeu HTTP ([0-9]{3})", message)
        if http_match:
            return f"gdelt_http_{http_match.group(1)}"
        return {
            "GDELT retornou JSON fora do formato esperado": "gdelt_json_shape",
            "GDELT retornou JSON inválido": "gdelt_json_invalid",
            "falha de conexão com GDELT": "gdelt_connection",
            "falha ao consultar GDELT": "gdelt_request_failed",
            "campo articles possui formato inesperado": "gdelt_articles_shape",
        }.get(message, "gdelt_error")
    if isinstance(exc, ValueError):
        return "input_validation"
    if isinstance(exc, OSError):
        return "filesystem_error"
    return "unexpected_error"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Coleta clipping FECAP via GDELT DOC 2.0 sem chave de API"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--max-records", type=int, default=250)
    parser.add_argument("--correlation-id")
    parser.add_argument("--people", type=Path, default=DEFAULT_PEOPLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    if ns.check:
        print(
            "mode=one_shot provider=gdelt-doc-2.0 credentials_required=false "
            "article_context=true identity_gate=true max_records=250 "
            "external_correlation_supported=true scheduled=false production_enabled=false"
        )
        return 0
    if not ns.once:
        print("BLOCKED: --once obrigatório", file=sys.stderr)
        return 50
    if not ns.start_date or not ns.end_date:
        print("BLOCKED: --start-date e --end-date são obrigatórios", file=sys.stderr)
        return 50
    correlation_id = f"gdelt-{uuid4()}"
    try:
        correlation_id = _resolve_correlation_id(ns.correlation_id)
        start = _parse_day(ns.start_date)
        end_day = _parse_day(ns.end_date)
        end = datetime.combine(end_day.date(), time(23, 59, 59), tzinfo=timezone.utc)
        if end < start:
            raise ValueError("data final anterior à inicial")
        if (end.date() - start.date()).days > 92:
            raise ValueError("janela maior que 93 dias não é suportada pelo GDELT DOC 2.0")
        known_people = _load_people(ns.people)
        payload = collect_fecap_public(
            start,
            end,
            max_records=ns.max_records,
            known_people=known_people,
        )
    except (ValueError, GdeltError, OSError, json.JSONDecodeError) as exc:
        error_code = _safe_error_code(exc)
        evidence = {
            "status": "BLOCKED",
            "provider": "GDELT DOC 2.0",
            "error_type": type(exc).__name__,
            "error_code": error_code,
            "correlation_id": correlation_id,
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
        print(f"BLOCKED: {error_code}", file=sys.stderr)
        return 50

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
        "identity_counts": payload["identity_counts"],
        "discovery_error_count": len(payload["discovery_errors"]),
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
