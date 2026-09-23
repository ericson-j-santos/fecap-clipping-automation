from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import json
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from clipping import Candidate, canonical_url

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_QUERY = '"FECAP"'
MAX_RECORDS = 250


class GdeltError(RuntimeError):
    pass


def _format_gdelt_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("datas devem possuir timezone")
    return value.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def build_url(
    start: datetime,
    end: datetime,
    *,
    query: str = DEFAULT_QUERY,
    max_records: int = MAX_RECORDS,
) -> str:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("datas devem possuir timezone")
    if end < start:
        raise ValueError("data final anterior à inicial")
    if not 1 <= max_records <= MAX_RECORDS:
        raise ValueError("max_records deve estar entre 1 e 250")
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(max_records),
        "startdatetime": _format_gdelt_datetime(start),
        "enddatetime": _format_gdelt_datetime(end),
        "sort": "datedesc",
    }
    return API_URL + "?" + urlencode(params)


def _load_json(
    url: str,
    *,
    attempts: int = 3,
    timeout: int = 45,
    opener: Callable = urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    if attempts < 1:
        raise ValueError("attempts deve ser >= 1")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "fecap-clipping-automation/1.0",
            },
        )
        try:
            with opener(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise GdeltError("GDELT retornou JSON fora do formato esperado")
            return payload
        except HTTPError as exc:
            last_error = exc
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            if not retryable or attempt == attempts:
                raise GdeltError(f"GDELT respondeu HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == attempts:
                raise GdeltError("falha de conexão com GDELT") from exc
        except json.JSONDecodeError as exc:
            raise GdeltError("GDELT retornou JSON inválido") from exc
        sleep(float(2 ** (attempt - 1)))
    raise GdeltError("falha ao consultar GDELT") from last_error


def fetch_articles(
    start: datetime,
    end: datetime,
    *,
    query: str = DEFAULT_QUERY,
    max_records: int = MAX_RECORDS,
) -> list[dict]:
    payload = _load_json(build_url(start, end, query=query, max_records=max_records))
    articles = payload.get("articles", [])
    if not isinstance(articles, list):
        raise GdeltError("campo articles possui formato inesperado")
    return [item for item in articles if isinstance(item, dict)]


def _parse_seen_date(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise GdeltError("artigo GDELT sem seendate")
    formats = ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S")
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return parsed.isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GdeltError("seendate GDELT inválido") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def article_to_candidate(article: dict) -> Candidate:
    title = unescape(str(article.get("title") or "").strip())
    url = str(article.get("url") or "").strip()
    if not title:
        raise GdeltError("artigo GDELT sem title")
    if not url:
        raise GdeltError("artigo GDELT sem url")
    canonical = canonical_url(url)
    domain = str(article.get("domain") or "").strip().lower()
    if not domain:
        domain = urlsplit(canonical).netloc.lower()
    if not domain:
        raise GdeltError("artigo GDELT sem domínio")
    published_at = _parse_seen_date(article.get("seendate"))
    return Candidate(
        title=title,
        url=canonical,
        source=domain,
        published_at=published_at,
        text=f"FECAP — correspondência confirmada pelo índice público GDELT. {title}",
    )


def collect_fecap_public(
    start: datetime,
    end: datetime,
    *,
    query: str = DEFAULT_QUERY,
    max_records: int = MAX_RECORDS,
    fetcher: Callable[..., list[dict]] = fetch_articles,
) -> dict:
    articles = fetcher(start, end, query=query, max_records=max_records)
    items: list[dict] = []
    seen: set[str] = set()
    rejected = 0
    for article in articles:
        try:
            candidate = article_to_candidate(article)
        except (GdeltError, ValueError):
            rejected += 1
            continue
        key = canonical_url(candidate.url)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "title": candidate.title,
                "url": candidate.url,
                "source": candidate.source,
                "published_at": candidate.published_at,
                "text": candidate.text,
            }
        )
    return {
        "format": 1,
        "provider": "GDELT DOC 2.0",
        "query": query,
        "window": {
            "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "items": items,
        "source_article_count": len(articles),
        "rejected_article_count": rejected,
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "production_enabled": False,
        "scheduled": False,
    }
