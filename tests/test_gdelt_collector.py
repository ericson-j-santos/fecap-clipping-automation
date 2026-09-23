from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gdelt_api import build_url, collect_fecap_public


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


def main() -> int:
    test_build_url()
    test_collect_payload_is_compatible_deduplicated_and_disambiguated()
    print("test_gdelt_collector: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
