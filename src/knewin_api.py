from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import time
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from clipping import Candidate

API_URL = "https://monitoring.knewinapis.com/v3/cliente/"
MAX_WINDOW_DAYS = 14


class KnewinApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class KnewinNews:
    external_id: str
    candidate: Candidate
    tier: int | None
    raw: dict


def split_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("datas devem possuir timezone")
    if end < start:
        raise ValueError("data final anterior à inicial")

    windows: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=MAX_WINDOW_DAYS), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(microseconds=1)
    return windows


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _post(api_key: str, payload: dict, timeout: int = 60) -> dict:
    request = Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise KnewinApiError(f"Knewin respondeu HTTP {exc.code}") from exc
    except URLError as exc:
        raise KnewinApiError("falha de conexão com a Knewin") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise KnewinApiError("resposta Knewin não é JSON válido") from exc
    if not isinstance(data, dict):
        raise KnewinApiError("resposta Knewin possui formato inesperado")
    return data


def fetch_window(
    api_key: str,
    start: datetime,
    end: datetime,
    *,
    rpp: int = 100,
    min_interval_seconds: float = 2.05,
) -> Iterable[dict]:
    page = 1
    returned = 0
    total: int | None = None

    while total is None or returned < total:
        payload = {
            "data_inicial": _iso(start),
            "data_final": _iso(end),
            "rpp": rpp,
            "pagina": page,
        }
        data = _post(api_key, payload)
        news = data.get("noticias") or []
        if not isinstance(news, list):
            raise KnewinApiError("campo noticias possui formato inesperado")

        if total is None:
            total = int(data.get("total") or len(news))

        for item in news:
            if isinstance(item, dict):
                yield item

        returned += len(news)
        if not news or returned >= total:
            break
        page += 1
        time.sleep(min_interval_seconds)


def _contains_fecap(item: dict) -> bool:
    associations = item.get("associacoes") or []
    assoc_text = " ".join(
        str(value)
        for assoc in associations
        if isinstance(assoc, dict)
        for value in assoc.values()
        if value is not None
    )
    haystack = "\n".join(
        str(item.get(field) or "") for field in ("titulo", "resumo", "texto")
    ) + "\n" + assoc_text
    return "fecap" in haystack.casefold()


def to_news(item: dict) -> KnewinNews:
    vehicle = item.get("veiculo") or {}
    if not isinstance(vehicle, dict):
        vehicle = {}
    source = str(vehicle.get("nome") or "").strip()
    title = str(item.get("titulo") or "").strip()
    published = str(item.get("data_publicacao") or "").strip()
    url = str(item.get("url_original") or "").strip()
    text = "\n".join(
        part for part in (
            str(item.get("resumo") or "").strip(),
            str(item.get("texto") or "").strip(),
        ) if part
    )
    external_id = str(item.get("id") or "").strip()

    missing = [name for name, value in {
        "id": external_id,
        "titulo": title,
        "url_original": url,
        "data_publicacao": published,
        "veiculo.nome": source,
    }.items() if not value]
    if missing:
        raise KnewinApiError("notícia sem campos obrigatórios: " + ", ".join(missing))

    tier_value = vehicle.get("tier")
    try:
        tier = int(tier_value) if tier_value is not None else None
    except (TypeError, ValueError):
        tier = None

    return KnewinNews(
        external_id=external_id,
        candidate=Candidate(
            title=title,
            url=url,
            source=source,
            published_at=published,
            text=text,
        ),
        tier=tier,
        raw=item,
    )


def collect_fecap(api_key: str, start: datetime, end: datetime) -> list[KnewinNews]:
    result: list[KnewinNews] = []
    seen_ids: set[str] = set()
    for window_start, window_end in split_windows(start, end):
        for item in fetch_window(api_key, window_start, window_end):
            if not _contains_fecap(item):
                continue
            news = to_news(item)
            if news.external_id in seen_ids:
                continue
            seen_ids.add(news.external_id)
            result.append(news)
    return result
