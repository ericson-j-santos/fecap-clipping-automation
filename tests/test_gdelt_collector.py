from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gdelt_api import GdeltError, build_url, collect_fecap_public

sys.path.insert(0, str(ROOT / "scripts"))
from collect_gdelt_publications import _safe_error_code

SCRIPT = ROOT / "scripts" / "collect_gdelt_publications.py"


def test_build_url() -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)
    url = build_url(start, end)
    query = parse_qs(urlsplit(url).query)
    assert query["query"] == ['"FECAP"']
    assert query["mode"] == ["artlist"]
    assert query["format"] == ["json"]
    assert query["maxrecords"] == ["250"]
    assert query["startdatetime"] == ["20260801000000"]
    assert query["enddatetime"] == ["20260831235959"]


def test_collect_payload_is_compatible_deduplicated_and_disambiguated() -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    fixture = [
        {
            "title": "Recuperação judicial cresce no país",
            "url": "https://example.com/positiva?utm_source=gdelt",
            "domain": "Example.com",
            "seendate": "20260831T120000Z",
        },
        {
            "title": "Recuperação judicial cresce no país",
            "url": "https://example.com/positiva",
            "domain": "example.com",
            "seendate": "20260831T120000Z",
        },
        {
            "title": "Prêmio de educação",
            "url": "https://example.com/homonimo",
            "domain": "example.com",
            "seendate": "20260830T120000Z",
        },
        {
            "title": "Menção sem contexto",
            "url": "https://example.com/ambigua",
            "domain": "example.com",
            "seendate": "20260829T120000Z",
        },
        {
            "title": "",
            "url": "https://example.com/invalida",
            "domain": "example.com",
            "seendate": "20260828T120000Z",
        },
    ]

    pages = {
        "https://example.com/positiva": (
            "O professor Ahmed El Khatib, da FECAP, explicou o cenário de recuperação judicial."
        ),
        "https://example.com/homonimo": (
            "O Colégio de Aplicação do Recife (Fecap/UPE) recebeu prêmio estadual."
        ),
        "https://example.com/ambigua": "A sigla FECAP foi citada sem contexto adicional.",
    }

    seen_queries = []

    def fake_fetcher(*args, **kwargs):
        query = kwargs["query"]
        seen_queries.append(query)
        if query == '"FECAP"':
            return fixture
        if query == '"Ahmed El Khatib"':
            return fixture[:2]
        if query == '"Rosely Schwartz"':
            raise GdeltError("rate limit simulado")
        return []

    def fake_article_fetcher(url: str) -> str:
        return pages[url]

    payload = collect_fecap_public(
        start,
        end,
        known_people=("Ahmed El Khatib", "Rosely Schwartz"),
        fetcher=fake_fetcher,
        article_fetcher=fake_article_fetcher,
        sleep=lambda _: None,
    )
    assert payload["format"] == 1
    assert payload["provider"] == "GDELT DOC 2.0"
    assert payload["credentials_persisted"] is False
    assert payload["raw_response_persisted"] is False
    assert payload["production_enabled"] is False
    assert payload["scheduled"] is False
    assert payload["source_article_count"] == 7
    assert payload["discovery_queries"] == [
        '"FECAP"',
        '"Ahmed El Khatib"',
        '"Rosely Schwartz"',
    ]
    assert seen_queries == payload["discovery_queries"]
    assert payload["discovery_errors"] == [
        {
            "query": '"Rosely Schwartz"',
            "error_type": "GdeltError",
            "optional": True,
        }
    ]
    assert payload["rejected_article_count"] == 1
    assert len(payload["items"]) == 3
    assert payload["identity_counts"] == {
        "confirmed": 1,
        "homonym": 1,
        "ambiguous": 1,
        "fetch_failed": 0,
    }

    by_url = {item["url"]: item for item in payload["items"]}
    positive = by_url["https://example.com/positiva"]
    assert positive["institution_identity"] == "confirmed"
    assert "Ahmed El Khatib" in positive["text"]
    assert "professor" in positive["text"].casefold()

    homonym = by_url["https://example.com/homonimo"]
    assert homonym["institution_identity"] == "homonym"
    assert homonym["text"] == ""

    ambiguous = by_url["https://example.com/ambigua"]
    assert ambiguous["institution_identity"] == "ambiguous"
    assert ambiguous["text"] == "FECAP"


def test_safe_gdelt_error_codes_do_not_echo_raw_details() -> None:
    assert _safe_error_code(GdeltError("GDELT respondeu HTTP 429")) == "gdelt_http_429"
    assert _safe_error_code(GdeltError("GDELT respondeu HTTP 503")) == "gdelt_http_503"
    assert _safe_error_code(GdeltError("falha de conexão com GDELT")) == "gdelt_connection"
    assert _safe_error_code(GdeltError("detalhe não permitido")) == "gdelt_error"


def test_invalid_external_correlation_fails_closed_without_echo() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        evidence = Path(temp_dir) / "evidence.json"
        secret_like_value = "invalid correlation value"
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--once",
                "--start-date",
                "2026-08-01",
                "--end-date",
                "2026-08-31",
                "--correlation-id",
                secret_like_value,
                "--evidence",
                str(evidence),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 50
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        assert payload["status"] == "BLOCKED"
        assert payload["error_type"] == "ValueError"
        assert payload["error_code"] == "input_validation"
        assert completed.stderr.strip() == "BLOCKED: input_validation"
        assert secret_like_value not in completed.stderr


def main() -> int:
    test_build_url()
    test_collect_payload_is_compatible_deduplicated_and_disambiguated()
    test_safe_gdelt_error_codes_do_not_echo_raw_details()
    test_invalid_external_correlation_fails_closed_without_echo()
    print("test_gdelt_collector: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
