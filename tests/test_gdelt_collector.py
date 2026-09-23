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


def test_collect_payload_is_compatible_and_deduplicated() -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    fixture = [
        {
            "title": "Professor da FECAP comenta cenário econômico",
            "url": "https://example.com/noticia?utm_source=gdelt",
            "domain": "Example.com",
            "seendate": "20260831T120000Z",
        },
        {
            "title": "Professor da FECAP comenta cenário econômico",
            "url": "https://example.com/noticia",
            "domain": "example.com",
            "seendate": "20260831T120000Z",
        },
        {
            "title": "",
            "url": "https://example.com/invalida",
            "domain": "example.com",
            "seendate": "20260830T120000Z",
        },
    ]

    def fake_fetcher(*args, **kwargs):
        return fixture

    payload = collect_fecap_public(start, end, fetcher=fake_fetcher)
    assert payload["format"] == 1
    assert payload["provider"] == "GDELT DOC 2.0"
    assert payload["credentials_persisted"] is False
    assert payload["raw_response_persisted"] is False
    assert payload["production_enabled"] is False
    assert payload["scheduled"] is False
    assert payload["source_article_count"] == 3
    assert payload["rejected_article_count"] == 1
    assert len(payload["items"]) == 1

    item = payload["items"][0]
    assert item["url"] == "https://example.com/noticia"
    assert item["source"] == "example.com"
    assert item["published_at"] == "2026-08-31T12:00:00Z"
    assert "FECAP" in item["text"]


def main() -> int:
    test_build_url()
    test_collect_payload_is_compatible_and_deduplicated()
    print("test_gdelt_collector: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
