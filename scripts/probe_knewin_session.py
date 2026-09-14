from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.json_schema_probe import (
    build_schema_inventory,
    schema_observation_from_framed_bytes,
)
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
MAX_SCHEMA_DIAGNOSTICS = 100
MAX_FRAMING_OBSERVATIONS = 100
DEFAULT_SCHEMA_BODY_BYTES = 1024 * 1024
KNEWIN_NEWSSTREAM_SCHEMA_BODY_BYTES = 8 * 1024 * 1024
SCHEMA_DIAGNOSTICS: list[dict] = []
SCHEMA_FRAMING: list[dict] = []


def schema_body_limit(endpoint: dict) -> int:
    host = str(endpoint.get("host") or "").casefold()
    route = str(endpoint.get("route_template") or "")
    if host == "news.knewin.com" and route.startswith("/newsstream/"):
        return KNEWIN_NEWSSTREAM_SCHEMA_BODY_BYTES
    return DEFAULT_SCHEMA_BODY_BYTES


def schema_failure_diagnostic(endpoint: dict, body: bytes | None, limit: int, *, error_type: str | None = None) -> dict:
    outcome = "body_error" if body is None else "unknown"
    body_bytes = None if body is None else len(body)
    if body is not None:
        if len(body) > limit:
            outcome = "too_large"
        else:
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                outcome = "invalid_utf8"
            else:
                try:
                    json.loads(text)
                except json.JSONDecodeError:
                    outcome = "invalid_json"
    return {
        "host": str(endpoint.get("host") or "")[:180],
        "route_template": str(endpoint.get("route_template") or "")[:240],
        "path_sha256": str(endpoint.get("path_sha256") or "")[:64],
        "method": str(endpoint.get("method") or "")[:16],
        "status": endpoint.get("status") if isinstance(endpoint.get("status"), int) else None,
        "outcome": outcome,
        "body_bytes": body_bytes,
        "limit_bytes": limit,
        "error_type": (error_type or "")[:80],
        "values_persisted": False,
        "secrets_captured": False,
    }


def safe_schema_diagnostics() -> dict:
    unique: dict[tuple, dict] = {}
    for item in SCHEMA_DIAGNOSTICS:
        key = tuple(item.get(k) for k in (
            "host", "route_template", "path_sha256", "method", "status", "outcome",
            "body_bytes", "limit_bytes", "error_type",
        ))
        unique[key] = item
    items = [unique[key] for key in sorted(unique, key=lambda x: tuple("" if p is None else str(p) for p in x))]
    return {
        "diagnostic_count": len(items),
        "diagnostics": items[:MAX_SCHEMA_DIAGNOSTICS],
        "truncated": len(items) > MAX_SCHEMA_DIAGNOSTICS,
        "values_persisted": False,
        "secrets_captured": False,
    }


def safe_schema_framing() -> dict:
    unique: dict[tuple, dict] = {}
    for item in SCHEMA_FRAMING:
        key = tuple(item.get(k) for k in (
            "host", "route_template", "path_sha256", "method", "status", "mode",
            "body_bytes", "prefix_bytes", "suffix_bytes", "prefix_sha256", "suffix_sha256", "item_count",
        ))
        unique[key] = item
    items = [unique[key] for key in sorted(unique, key=lambda x: tuple("" if p is None else str(p) for p in x))]
    return {
        "framing_count": len(items),
        "framings": items[:MAX_FRAMING_OBSERVATIONS],
        "truncated": len(items) > MAX_FRAMING_OBSERVATIONS,
        "values_persisted": False,
        "secrets_captured": False,
    }


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
            item = network_observation(response.url, response.request.method, response.status, response.headers.get("content-type"))
        except Exception:
            return
        if not item["is_json"]:
            return
        observations.append(item)
        if len(schema_observations) >= MAX_SCHEMA_OBSERVATIONS or is_login_like_url(response.url):
            return
        limit = schema_body_limit(item)
        try:
            body = response.body()
        except Exception as exc:
            if len(SCHEMA_DIAGNOSTICS) < MAX_SCHEMA_DIAGNOSTICS:
                SCHEMA_DIAGNOSTICS.append(schema_failure_diagnostic(item, None, limit, error_type=type(exc).__name__))
            return
        try:
            schema, framing = schema_observation_from_framed_bytes(item, body, max_bytes=limit)
        except Exception as exc:
            if len(SCHEMA_DIAGNOSTICS) < MAX_SCHEMA_DIAGNOSTICS:
                SCHEMA_DIAGNOSTICS.append(schema_failure_diagnostic(item, None, limit, error_type=type(exc).__name__))
            return
        if schema is not None:
            schema_observations.append(schema)
            if framing is not None and framing.get("mode") != "raw" and len(SCHEMA_FRAMING) < MAX_FRAMING_OBSERVATIONS:
                SCHEMA_FRAMING.append({
                    "host": item["host"],
                    "route_template": item["route_template"],
                    "path_sha256": item["path_sha256"],
                    "method": item["method"],
                    "status": item["status"],
                    **framing,
                })
        elif len(SCHEMA_DIAGNOSTICS) < MAX_SCHEMA_DIAGNOSTICS:
            SCHEMA_DIAGNOSTICS.append(schema_failure_diagnostic(item, body, limit))
    context.on("response", on_response)


def safe_inventory(*groups: list[dict]) -> dict:
    observations = [item for group in groups for item in group]
    raw_truncated = any(len(group) >= MAX_NETWORK_OBSERVATIONS for group in groups)
    return build_network_inventory(observations, max_entries=MAX_JSON_ENDPOINTS, raw_truncated=raw_truncated)


def safe_schema_inventory(*groups: list[dict]) -> dict:
    observations = [item for group in groups for item in group]
    raw_truncated = any(len(group) >= MAX_SCHEMA_OBSERVATIONS for group in groups)
    return build_schema_inventory(observations, max_entries=MAX_SCHEMA_OBSERVATIONS, raw_truncated=raw_truncated)


def write_evidence(evidence: dict) -> None:
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2), flush=True)


def evidence_common(network, schemas) -> dict:
    return {
        "network_inventory": safe_inventory(network),
        "response_schema_inventory": safe_schema_inventory(schemas),
        "schema_probe_diagnostics": safe_schema_diagnostics(),
        "schema_framing_inventory": safe_schema_framing(),
        "values_persisted": False,
        "secrets_captured": False,
    }


def main() -> int:
    SCHEMA_DIAGNOSTICS.clear()
    SCHEMA_FRAMING.clear()
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
                "status": "BLOCKED", "phase": "initial_authentication",
                "initial_auth": first.to_dict(), "initial_location": url_fingerprint(authenticated_url),
                "session_reused": False, **evidence_common(first_network, first_schemas),
            }
            write_evidence(evidence); context.close(); return 32

        print("Sessão validada. Abra a área usada para clipping/notícias e execute uma consulta conhecida.", flush=True)
        input("Quando a consulta e os resultados estiverem carregados, pressione ENTER aqui... ")
        page.wait_for_timeout(1500)
        exploration_url = page.url
        exploration_location = url_fingerprint(exploration_url)
        if is_login_like_url(exploration_url):
            evidence = {
                "status": "BLOCKED", "phase": "guided_exploration",
                "initial_auth_mode": first.auth_mode, "initial_location": url_fingerprint(authenticated_url),
                "exploration_location": exploration_location, "exploration_completed": False,
                "session_reused": False, **evidence_common(first_network, first_schemas),
            }
            write_evidence(evidence); context.close(); return 34
        context.close()

        second_schemes: set[str] = set(); second_hosts: set[str] = set()
        second_network: list[dict] = []; second_schemas: list[dict] = []
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
            "initial_auth_mode": first.auth_mode, "reopened_auth_mode": second.auth_mode,
            "initial_location": url_fingerprint(authenticated_url), "exploration_location": exploration_location,
            "exploration_completed": True, "reopened_location": url_fingerprint(page2.url),
            "redirected_to_login": is_login_like_url(page2.url),
            "network_inventory": safe_inventory(first_network, second_network),
            "response_schema_inventory": safe_schema_inventory(first_schemas, second_schemas),
            "schema_probe_diagnostics": safe_schema_diagnostics(),
            "schema_framing_inventory": safe_schema_framing(),
            "session_reused": reuse_ok, "profile_persisted": True,
            "values_persisted": False, "secrets_captured": False,
        }
        write_evidence(evidence); reopened.close()
    return 0 if evidence["status"] == "PASS" else 33


if __name__ == "__main__":
    raise SystemExit(main())
