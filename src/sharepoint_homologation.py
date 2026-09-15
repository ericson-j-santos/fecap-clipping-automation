from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata
from urllib.parse import urlparse

TARGET_SITE_TITLE = "FECAP Clipping Homologacao"
TARGET_FOLDER = "FECAP Clipping - Homologacao 2026"
SITE_SCORE_THRESHOLD = 100


class SharePointHomologationError(ValueError):
    pass


@dataclass(frozen=True)
class SiteCandidate:
    title: str
    url: str
    score: int


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().casefold()


def is_sharepoint_site_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()
    return (
        parsed.scheme == "https"
        and host.endswith(".sharepoint.com")
        and ("/sites/" in path or "/teams/" in path)
    )


def score_site(title: str, url: str) -> int:
    haystack = normalize_text(f"{title} {url}")
    score = 0
    if "fecap" in haystack:
        score += 100
    if "clipping" in haystack:
        score += 60
    if "homolog" in haystack:
        score += 30
    if any(token in haystack for token in ("comunicacao", "marketing", "assessoria", "imprensa")):
        score += 25
    return score


def site_candidate(title: str, url: str) -> SiteCandidate | None:
    if not is_sharepoint_site_url(url):
        return None
    return SiteCandidate(title=str(title or "").strip(), url=url, score=score_site(title, url))


def choose_existing_site(candidates: list[SiteCandidate]) -> SiteCandidate | None:
    eligible = sorted(
        (item for item in candidates if item.score >= SITE_SCORE_THRESHOLD),
        key=lambda item: (-item.score, normalize_text(item.title), item.url),
    )
    if not eligible:
        return None
    if len(eligible) > 1 and eligible[0].score == eligible[1].score:
        return None
    return eligible[0]


def validate_sha256(value: str) -> str:
    digest = str(value or "").casefold()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise SharePointHomologationError("SHA-256 inválido")
    return digest


def deterministic_filename(workbook_sha256: str) -> str:
    digest = validate_sha256(workbook_sha256)
    return f"fecap-clipping-homologacao-{digest[:12]}.xlsx"


def workbook_sha256(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def remote_file_decision(names: list[str], expected_name: str) -> str:
    normalized_expected = normalize_text(expected_name)
    matches = [name for name in names if normalize_text(name) == normalized_expected]
    if not matches:
        return "upload"
    if len(matches) == 1:
        return "already_present"
    raise SharePointHomologationError("mais de um arquivo remoto com o mesmo nome determinístico")


def build_evidence(
    *,
    workbook_digest: str,
    site_title: str,
    site_url: str,
    library_name: str,
    folder_name: str,
    file_name: str,
    action: str,
    existing_site_reused: bool,
    site_created: bool,
) -> dict:
    validate_sha256(workbook_digest)
    if action not in {"uploaded", "already_present"}:
        raise SharePointHomologationError("ação de publicação inválida")
    if not is_sharepoint_site_url(site_url):
        raise SharePointHomologationError("URL final não é um site SharePoint permitido")
    return {
        "status": "PASS",
        "mode": "one_shot",
        "workbook_sha256": workbook_digest,
        "site": {"title": site_title, "url": site_url},
        "library": library_name,
        "folder": folder_name,
        "file_name": file_name,
        "action": action,
        "existing_site_reused": existing_site_reused,
        "site_created": site_created,
        "duplicate_prevented": action == "already_present",
        "external_destination_enabled": True,
        "scheduled": False,
        "production_enabled": False,
        "credentials_persisted": False,
        "cookies_persisted_in_evidence": False,
        "tokens_persisted": False,
        "secrets_captured": False,
    }
