from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import re
import time
from typing import Callable
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from clipping import Candidate, canonical_url

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_QUERY = '"FECAP"'
MAX_RECORDS = 250
MAX_PAGE_BYTES = 1_500_000
MAX_CONTEXT_CHARS = 2400

INSTITUTION_MARKERS = (
    "fundacao escola de comercio alvares penteado",
    "centro universitario fecap",
    "colegio fecap",
)
KNOWN_HOMONYMS = (
    "fundo estadual para calamidades publicas",
    "fecap/upe",
    "colegio de aplicacao do recife",
)


class GdeltError(RuntimeError):
    pass


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


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


def fetch_article_text(url: str, *, timeout: int = 20, opener: Callable = urlopen) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (compatible; fecap-clipping-automation/1.0)",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            content_type = str(response.headers.get("Content-Type") or "").casefold()
            if "html" not in content_type:
                raise GdeltError("conteúdo da matéria não é HTML")
            payload = response.read(MAX_PAGE_BYTES + 1)
    except HTTPError as exc:
        raise GdeltError(f"matéria respondeu HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise GdeltError("falha ao ler matéria pública") from exc
    if len(payload) > MAX_PAGE_BYTES:
        raise GdeltError("matéria excede limite de leitura")
    charset_match = re.search(r"charset=([\w.-]+)", content_type)
    charset = charset_match.group(1) if charset_match else "utf-8"
    try:
        html = payload.decode(charset, errors="replace")
    except LookupError:
        html = payload.decode("utf-8", errors="replace")
    parser = _VisibleTextParser()
    parser.feed(html)
    return " ".join(parser.parts)


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


def _identity_state(text: str, known_people: tuple[str, ...]) -> str:
    folded = _fold(text)
    if any(marker in folded for marker in KNOWN_HOMONYMS):
        if not any(marker in folded for marker in INSTITUTION_MARKERS):
            return "homonym"
    if any(marker in folded for marker in INSTITUTION_MARKERS):
        return "confirmed"
    if "fecap" in folded and any(_fold(name) in folded for name in known_people):
        return "confirmed"
    return "ambiguous"


def _context_snippet(text: str, known_people: tuple[str, ...]) -> str:
    clean = " ".join(text.split())
    folded = _fold(clean)
    needles = ["fecap", *(_fold(name) for name in known_people)]
    positions = [folded.find(needle) for needle in needles if needle and folded.find(needle) >= 0]
    if not positions:
        return "FECAP"
    center = min(positions)
    start = max(0, center - 800)
    end = min(len(clean), start + MAX_CONTEXT_CHARS)
    return clean[start:end]


def article_to_candidate(article: dict, *, text: str = "FECAP") -> Candidate:
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
        text=text,
    )


def collect_fecap_public(
    start: datetime,
    end: datetime,
    *,
    query: str = DEFAULT_QUERY,
    max_records: int = MAX_RECORDS,
    known_people: tuple[str, ...] = (),
    fetcher: Callable[..., list[dict]] = fetch_articles,
    article_fetcher: Callable[[str], str] = fetch_article_text,
    sleep: Callable[[float], None] = time.sleep,
    query_pause_seconds: float = 5.0,
) -> dict:
    discovery_queries = [query]
    discovery_queries.extend(
        f'"{name}"' for name in known_people if name.strip()
    )
    articles: list[dict] = []
    discovery_errors: list[dict] = []
    for index, discovery_query in enumerate(discovery_queries):
        if index and query_pause_seconds > 0:
            sleep(query_pause_seconds)
        try:
            articles.extend(
                fetcher(
                    start,
                    end,
                    query=discovery_query,
                    max_records=max_records,
                )
            )
        except GdeltError as exc:
            if index == 0:
                raise
            discovery_errors.append(
                {
                    "query": discovery_query,
                    "error_type": type(exc).__name__,
                    "optional": True,
                }
            )

    items: list[dict] = []
    seen: set[str] = set()
    rejected = 0
    identity_counts = {"confirmed": 0, "homonym": 0, "ambiguous": 0, "fetch_failed": 0}

    for article in articles:
        try:
            base = article_to_candidate(article)
        except (GdeltError, ValueError):
            rejected += 1
            continue
        key = canonical_url(base.url)
        if key in seen:
            continue
        seen.add(key)

        try:
            page_text = article_fetcher(base.url)
            identity = _identity_state(page_text, known_people)
        except (GdeltError, OSError, ValueError):
            page_text = ""
            identity = "fetch_failed"

        identity_counts[identity] += 1
        if identity == "confirmed":
            text = _context_snippet(page_text, known_people)
        elif identity == "homonym":
            text = ""
        else:
            text = "FECAP"

        candidate = article_to_candidate(article, text=text)
        items.append(
            {
                "title": candidate.title,
                "url": candidate.url,
                "source": candidate.source,
                "published_at": candidate.published_at,
                "text": candidate.text,
                "institution_identity": identity,
            }
        )

    return {
        "format": 1,
        "provider": "GDELT DOC 2.0",
        "query": query,
        "discovery_queries": discovery_queries,
        "discovery_errors": discovery_errors,
        "window": {
            "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "items": items,
        "source_article_count": len(articles),
        "rejected_article_count": rejected,
        "identity_counts": identity_counts,
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "production_enabled": False,
        "scheduled": False,
    }
