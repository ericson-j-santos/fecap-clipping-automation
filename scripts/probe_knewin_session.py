from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.json_schema_probe import build_schema_inventory, schema_observation_from_bytes
from src.session_auth_probe import (
    build_network_inventory,
    classify_auth,
    header_scheme,
    is_login_like_url,
    network_observation,
    session_reuse_is_valid,
    url_fingerprint,
)

PORTAL_URL = os.environ.get("KNEWIN_PORTAL_URL", "https://monitoring.knewin.com/")
PROFILE_DIR = Path(os.environ.get("KNEWIN_PROFILE_DIR", str(Path.home() / ".fecap-clipping" / "knewin-profile")))
EVIDENCE_PATH = Path(os.environ.get("KNEWIN_AUTH_EVIDENCE", str(ROOT / "evidence" / "private" / "knewin-auth-probe.json")))
OIDC_HINTS = ("login", "oauth", "oidc", "authorize", "identity", "auth", "sso")
MAX_JSON_ENDPOINTS = 250
MAX_NETWORK_OBSERVATIONS = 1000
MAX_SCHEMA_OBSERVATIONS = 100


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


def attach_response_probe(context, observations: list[dict], schema_observations: list[dict]) -> None:
    def on_response(response) -> None:
        if len(observations) >= MAX_NETWORK_OBSERVATIONS:
            return
        try:
            item = network_observation(
                response.url,
                response.request.method,
                response.status,
                response.headers.get("content-type"),
            )
        except Exception:
            return
        if not item["is_json"]:
            return
        observations.append(item)

        if len(schema_observations) >= MAX_SCHEMA_OBSERVATIONS or is_login_like_url(response.url):
            return
        try:
            schema = schema_observation_from_bytes(item, response.body())
        except Exception:
            return
        if schema is not None:
            schema_observations.append(schema)

    context.on("response", on_response)


def safe_inventory(*groups: list[dict]) -> dict:
    observations = [item for group in groups for item in group]
    raw_truncated = any(len(group) >= MAX_NETWORK_OBSERVATIONS for group in groups)
    return build_network_inventory(
        observations,
        max_entries=MAX_JSON_ENDPOINTS,
        raw_truncated=raw_truncated,
    )


def safe_schema_inventory(*groups: list[dict]) -> dict:
    observations = [item for group in groups for item in group]
    raw_truncated = any(len(group) >= MAX_SCHEMA_OBSERVATIONS for group in groups)
    return build_schema_inventory(
        observations,
        max_entries=MAX_SCHEMA_OBSERVATIONS,
        raw_truncated=raw_truncated,
    )


def write_evidence(evidence: dict) -> None:
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2), flush=True)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright não instalado. Execute: python scripts/setup_local.py", file=sys.stderr)
        return 30

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        first_schemes: set[str] = set()
        first_hosts: set[str] = set()
        first_network: list[dict] = []
        first_schemas: list[dict] = []
        context = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False, args=["--disable-sync"])
        attach_request_probe(context, first_schemes, first_hosts)
        attach_response_probe(context, first_network, first_schemas)
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
                "network_inventory": safe_inventory(first_network),
                "response_schema_inventory": safe_schema_inventory(first_schemas),
                "session_reused": False,
                "values_persisted": False,
                "secrets_captured": False,
            }
            write_evidence(evidence)
            context.close()
            return 32

        print(
            "Sessão validada. No navegador, abra a área usada para clipping/notícias e execute uma consulta conhecida. "
            "A sonda guarda somente rotas sanitizadas, tipos e nomes estruturais dos campos JSON; valores não são persistidos.",
            flush=True,
        )
        input("Quando a consulta e os resultados estiverem carregados, pressione ENTER aqui... ")
        page.wait_for_timeout(1500)
        exploration_url = page.url
        exploration_location = url_fingerprint(exploration_url)
        if is_login_like_url(exploration_url):
            evidence = {
                "status": "BLOCKED",
                "phase": "guided_exploration",
                "initial_auth_mode": first.auth_mode,
                "initial_location": url_fingerprint(authenticated_url),
                "exploration_location": exploration_location,
                "exploration_completed": False,
                "network_inventory": safe_inventory(first_network),
                "response_schema_inventory": safe_schema_inventory(first_schemas),
                "session_reused": False,
                "values_persisted": False,
                "secrets_captured": False,
            }
            write_evidence(evidence)
            context.close()
            return 34

        context.close()

        second_schemes: set[str] = set()
        second_hosts: set[str] = set()
        second_network: list[dict] = []
        second_schemas: list[dict] = []
        reopened = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False, args=["--disable-sync"])
        attach_request_probe(reopened, second_schemes, second_hosts)
        attach_response_probe(reopened, second_network, second_schemas)
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
            "exploration_location": exploration_location,
            "exploration_completed": True,
            "reopened_location": url_fingerprint(page2.url),
            "redirected_to_login": is_login_like_url(page2.url),
            "network_inventory": safe_inventory(first_network, second_network),
            "response_schema_inventory": safe_schema_inventory(first_schemas, second_schemas),
            "session_reused": reuse_ok,
            "profile_persisted": True,
            "values_persisted": False,
            "secrets_captured": False,
        }
        write_evidence(evidence)
        reopened.close()

    return 0 if evidence["status"] == "PASS" else 33


if __name__ == "__main__":
    raise SystemExit(main())
