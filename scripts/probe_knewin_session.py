from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.session_auth_probe import (
    classify_auth,
    header_scheme,
    is_login_like_url,
    session_reuse_is_valid,
    url_fingerprint,
)

PORTAL_URL = os.environ.get("KNEWIN_PORTAL_URL", "https://monitoring.knewin.com/")
PROFILE_DIR = Path(os.environ.get("KNEWIN_PROFILE_DIR", str(Path.home() / ".fecap-clipping" / "knewin-profile")))
EVIDENCE_PATH = Path(os.environ.get("KNEWIN_AUTH_EVIDENCE", str(ROOT / "evidence" / "private" / "knewin-auth-probe.json")))
OIDC_HINTS = ("login", "oauth", "oidc", "authorize", "identity", "auth", "sso")


def collect(page, context, schemes: set[str], oidc_hosts: set[str]):
    cookies = [c.get("name", "") for c in context.cookies()]
    local_keys = page.evaluate("Object.keys(localStorage)")
    session_keys = page.evaluate("Object.keys(sessionStorage)")
    return classify_auth(schemes, cookies, local_keys, session_keys, oidc_hosts)


def attach_request_probe(context, schemes: set[str], oidc_hosts: set[str]) -> None:
    def on_request(request) -> None:
        parsed = urlparse(request.url)
        host = parsed.hostname or ""
        scheme = header_scheme(request.headers.get("authorization"))
        if scheme:
            schemes.add(scheme)
        lower_url = request.url.lower()
        if any(hint in lower_url for hint in OIDC_HINTS) and host:
            oidc_hosts.add(host)

    context.on("request", on_request)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright não instalado. Execute: pip install playwright && playwright install chromium", file=sys.stderr)
        return 30

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        first_schemes: set[str] = set()
        first_hosts: set[str] = set()
        context = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False, args=["--disable-sync"])
        attach_request_probe(context, first_schemes, first_hosts)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(PORTAL_URL, wait_until="domcontentloaded")

        print("Autentique-se normalmente na Knewin. Nenhuma senha/token será gravado.", flush=True)
        input("Somente quando a tela autenticada estiver aberta, pressione ENTER aqui... ")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        authenticated_url = page.url
        first = collect(page, context, first_schemes, first_hosts)
        if first.auth_mode == "unknown" or is_login_like_url(authenticated_url):
            evidence = {
                "status": "BLOCKED",
                "phase": "initial_authentication",
                "initial_auth": first.to_dict(),
                "initial_location": url_fingerprint(authenticated_url),
                "session_reused": False,
                "secrets_captured": False,
            }
            EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(evidence, ensure_ascii=False, indent=2), flush=True)
            context.close()
            return 32

        context.close()

        second_schemes: set[str] = set()
        second_hosts: set[str] = set()
        reopened = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False, args=["--disable-sync"])
        attach_request_probe(reopened, second_schemes, second_hosts)
        page2 = reopened.pages[0] if reopened.pages else reopened.new_page()
        page2.goto(authenticated_url, wait_until="domcontentloaded")
        page2.wait_for_timeout(3000)

        second = collect(page2, reopened, second_schemes, second_hosts)
        reuse_ok = session_reuse_is_valid(authenticated_url, page2.url, second.auth_mode)
        evidence = {
            "status": "PASS" if reuse_ok else "BLOCKED",
            "initial_auth_mode": first.auth_mode,
            "reopened_auth_mode": second.auth_mode,
            "initial_location": url_fingerprint(authenticated_url),
            "reopened_location": url_fingerprint(page2.url),
            "redirected_to_login": is_login_like_url(page2.url),
            "session_reused": reuse_ok,
            "profile_persisted": True,
            "secrets_captured": False,
        }
        EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=False, indent=2), flush=True)
        reopened.close()

    return 0 if evidence["status"] == "PASS" else 33


if __name__ == "__main__":
    raise SystemExit(main())
