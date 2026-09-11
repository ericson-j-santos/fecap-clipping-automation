from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.session_auth_probe import classify_auth, header_scheme

PORTAL_URL = os.environ.get("KNEWIN_PORTAL_URL", "https://monitoring.knewin.com/")
PROFILE_DIR = Path(os.environ.get("KNEWIN_PROFILE_DIR", str(Path.home() / ".fecap-clipping" / "knewin-profile")))
EVIDENCE_PATH = Path(os.environ.get("KNEWIN_AUTH_EVIDENCE", str(ROOT / "evidence" / "private" / "knewin-auth-probe.json")))

OIDC_HINTS = ("login", "oauth", "oidc", "authorize", "identity", "auth")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright não instalado. Execute: pip install playwright && playwright install chromium", file=sys.stderr)
        return 30

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)

    authorization_schemes: set[str] = set()
    oidc_hosts: set[str] = set()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            args=["--disable-sync"],
        )

        def on_request(request) -> None:
            parsed = urlparse(request.url)
            host = parsed.hostname or ""
            scheme = header_scheme(request.headers.get("authorization"))
            if scheme:
                authorization_schemes.add(scheme)
            lower_url = request.url.lower()
            if any(hint in lower_url for hint in OIDC_HINTS) and host:
                oidc_hosts.add(host)

        context.on("request", on_request)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(PORTAL_URL, wait_until="domcontentloaded")

        print("Autentique-se normalmente na Knewin nesta janela. Nenhuma senha/token será gravado.")
        input("Quando a tela autenticada estiver aberta, pressione ENTER aqui para executar a sonda... ")

        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        cookies = context.cookies()
        cookie_names = [c.get("name", "") for c in cookies]
        local_keys = page.evaluate("Object.keys(localStorage)")
        session_keys = page.evaluate("Object.keys(sessionStorage)")

        evidence = classify_auth(
            authorization_schemes,
            cookie_names,
            local_keys,
            session_keys,
            oidc_hosts,
        ).to_dict()
        evidence.update({
            "portal_host": urlparse(page.url).hostname,
            "authenticated_url_observed": page.url.split("?", 1)[0],
            "profile_persisted": True,
        })

        EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        context.close()

    return 0 if evidence["auth_mode"] != "unknown" else 31


if __name__ == "__main__":
    raise SystemExit(main())
