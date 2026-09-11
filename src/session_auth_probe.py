from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

SENSITIVE_MARKERS = ("token", "auth", "session", "jwt", "bearer", "oidc", "oauth", "msal")


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
    cookie_text = " ".join(cookies).lower()

    if "bearer" in schemes:
        mode = "bearer"
        scheme = "Bearer"
    elif any(marker in storage_text for marker in ("oidc", "oauth", "msal")) or hosts:
        mode = "oidc"
        scheme = None
    elif cookies:
        mode = "cookie"
        scheme = None
    else:
        mode = "unknown"
        scheme = None

    return AuthEvidence(
        auth_mode=mode,
        authorization_scheme=scheme,
        cookie_names=cookies,
        local_storage_keys=local_keys,
        session_storage_keys=session_keys,
        oidc_hosts=hosts,
        secrets_captured=False,
    )


def header_scheme(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(" ", 1)[0].strip() or None
