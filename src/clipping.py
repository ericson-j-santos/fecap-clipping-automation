from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid",
}


@dataclass(frozen=True)
class Candidate:
    title: str
    url: str
    source: str
    published_at: str
    text: str


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str
    person: str | None = None
    business_unit: str | None = None
    tier: int | None = None


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("url inválida")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), "")
    )


def idempotency_key(candidate: Candidate) -> str:
    payload = "|".join(
        [canonical_url(candidate.url), candidate.published_at, candidate.source.strip().lower()]
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def classify(candidate: Candidate, people: dict[str, str], tiers: dict[str, int]) -> Decision:
    text = f"{candidate.title}\n{candidate.text}".lower()

    incidental_markers = (
        "graduado em", "pós-graduado", "formado pela fecap", "pela fecap."
    )
    if "fecap" in text and any(marker in text for marker in incidental_markers):
        return Decision("exclude", "menção biográfica/curricular sem participação editorial")

    spokesperson_markers = (
        "professor", "coordenador", "especialista", "vice-reitor", "pró-reitor"
    )
    if "fecap" in text and any(marker in text for marker in spokesperson_markers):
        person = next((name for name in people if name.lower() in text), None)
        return Decision(
            "include",
            "participação editorial explícita de porta-voz FECAP",
            person=person,
            business_unit=people.get(person) if person else None,
            tier=tiers.get(candidate.source),
        )

    if "fecap" in text:
        return Decision(
            "review", "referência real à FECAP sem contexto suficiente para decisão automática"
        )

    return Decision("exclude", "sem referência à FECAP")


def ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS clipping (
            id INTEGER PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            source TEXT NOT NULL,
            published_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status='include'),
            person TEXT,
            business_unit TEXT,
            tier INTEGER
        );
        CREATE TABLE IF NOT EXISTS review_queue (
            id INTEGER PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            source TEXT NOT NULL,
            published_at TEXT NOT NULL,
            reason TEXT NOT NULL
        );
        """
    )


def persist(db: sqlite3.Connection, candidate: Candidate, decision: Decision) -> str:
    key = idempotency_key(candidate)
    url = canonical_url(candidate.url)

    if decision.status == "include":
        before = db.total_changes
        db.execute(
            """INSERT OR IGNORE INTO clipping
            (idempotency_key,title,url,source,published_at,status,person,business_unit,tier)
            VALUES (?,?,?,?,?,'include',?,?,?)""",
            (
                key, candidate.title, url, candidate.source, candidate.published_at,
                decision.person, decision.business_unit, decision.tier,
            ),
        )
        return "inserted" if db.total_changes > before else "duplicate"

    if decision.status == "review":
        before = db.total_changes
        db.execute(
            """INSERT OR IGNORE INTO review_queue
            (idempotency_key,title,url,source,published_at,reason)
            VALUES (?,?,?,?,?,?)""",
            (key, candidate.title, url, candidate.source, candidate.published_at, decision.reason),
        )
        return "queued" if db.total_changes > before else "duplicate"

    return "not_published"
