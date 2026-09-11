from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
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
