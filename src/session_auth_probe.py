from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import re
from typing import Iterable
from urllib.parse import urlparse


@dataclass(frozen=True)
class AuthEvidence:
    auth_mode: str
    authorization_scheme: str | None
    cookie_names: tuple[str, ...]
    local_storage_keys: tuple[str, ...]
    session_storage_keys: tuple[str, ...]
    oidc_hosts: tuple[str, ...]
    secrets_captured: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_names(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value)[:120] for value in values if value}))


def classify_auth(
    authorization_schemes: Iterable[str],
    cookie_names: Iterable[str],
    local_storage_keys: Iterable[str],
    session_storage_keys: Iterable[str],
    oidc_hosts: Iterable[str],
) -> AuthEvidence:
    schemes = {s.strip().lower() for s in authorization_schemes if s}
    cookies = _safe_names(cookie_names)
    local_keys = _safe_names(local_storage_keys)
    session_keys = _safe_names(session_storage_keys)
    hosts = _safe_names(oidc_hosts)
    storage_text = " ".join((*local_keys, *session_keys)).lower()

    if "bearer" in schemes:
        mode, scheme = "bearer", "Bearer"
    elif any(marker in storage_text for marker in ("oidc", "oauth", "msal")) or hosts:
        mode, scheme = "oidc", None
    elif cookies:
        mode, scheme = "cookie", None
    else:
        mode, scheme = "unknown", None

    return AuthEvidence(mode, scheme, cookies, local_keys, session_keys, hosts, False)


def header_scheme(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(" ", 1)[0].strip() or None


def is_login_like_url(url: str) -> bool:
    parsed = urlparse(url)
    text = f"{parsed.hostname or ''}{parsed.path}".lower()
    return any(marker in text for marker in ("login", "signin", "sign-in", "oauth", "oidc", "authorize", "sso"))


def session_reuse_is_valid(initial_url: str, reopened_url: str, auth_mode: str) -> bool:
    if auth_mode == "unknown" or is_login_like_url(reopened_url):
        return False
    first, second = urlparse(initial_url), urlparse(reopened_url)
    first_path = (first.path or "/").rstrip("/") or "/"
    second_path = (second.path or "/").rstrip("/") or "/"
    return first.scheme == second.scheme and first.netloc == second.netloc and first_path == second_path


def url_fingerprint(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return {
        "host": parsed.hostname or "",
        "path_sha256": sha256(normalized.encode("utf-8")).hexdigest(),
    }


def _sanitize_path_segment(segment: str) -> str:
    if not segment:
        return ""
    if "%" in segment:
        return "{encoded}"
    if "@" in segment:
        return "{email}"
    if re.fullmatch(r"[0-9]+", segment):
        return "{n}"
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}", segment):
        return "{uuid}"
    if re.fullmatch(r"[0-9a-fA-F]{12,}", segment):
        return "{id}"
    if len(segment) >= 20 and re.search(r"[A-Za-z]", segment) and re.search(r"[0-9]", segment):
        return "{id}"
    if len(segment) > 40:
        return "{opaque}"
    if not re.fullmatch(r"[A-Za-z0-9._~-]+", segment):
        return "{opaque}"
    return segment


def sanitize_route_template(url: str) -> str:
    parsed = urlparse(url)
    parts = [_sanitize_path_segment(segment) for segment in (parsed.path or "/").split("/") if segment]
    return "/" + "/".join(parts) if parts else "/"


def normalize_content_type(value: str | None) -> str | None:
    if not value:
        return None
    mime = value.split(";", 1)[0].strip().lower()
    return mime[:120] or None


def network_observation(
    url: str,
    method: str,
    status: int | None,
    content_type: str | None,
) -> dict:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    route_template = sanitize_route_template(url)
    normalized_route = f"{parsed.scheme.lower()}://{host}{route_template}"
    mime = normalize_content_type(content_type)
    try:
        safe_status = int(status) if status is not None else None
    except (TypeError, ValueError):
        safe_status = None
    return {
        "host": host,
        "route_template": route_template,
        "path_sha256": sha256(normalized_route.encode("utf-8")).hexdigest(),
        "method": (method or "UNKNOWN").strip().upper()[:16],
        "status": safe_status,
        "content_type": mime,
        "is_json": bool(mime and (mime == "application/json" or mime.endswith("+json"))),
        "secrets_captured": False,
    }


def dedupe_network_observations(observations: Iterable[dict]) -> list[dict]:
    unique: dict[tuple, dict] = {}
    for item in observations:
        key = (
            item.get("host", ""),
            item.get("route_template", ""),
            item.get("path_sha256", ""),
            item.get("method", ""),
            item.get("status"),
            item.get("content_type"),
            bool(item.get("is_json")),
        )
        unique[key] = {
            "host": key[0],
            "route_template": key[1],
            "path_sha256": key[2],
            "method": key[3],
            "status": key[4],
            "content_type": key[5],
            "is_json": key[6],
            "secrets_captured": False,
        }
    return [unique[key] for key in sorted(unique, key=lambda value: tuple("" if part is None else str(part) for part in value))]


def build_network_inventory(
    observations: Iterable[dict],
    *,
    max_entries: int = 250,
    raw_truncated: bool = False,
) -> dict:
    if max_entries < 1:
        raise ValueError("max_entries deve ser maior que zero")
    endpoints = [item for item in dedupe_network_observations(observations) if item["is_json"]]
    truncated = raw_truncated or len(endpoints) > max_entries
    endpoints = endpoints[:max_entries]
    return {
        "json_endpoint_count": len(endpoints),
        "json_endpoints": endpoints,
        "truncated": truncated,
        "secrets_captured": False,
    }
