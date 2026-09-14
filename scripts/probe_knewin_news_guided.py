from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.probe_knewin_news as news
import scripts.probe_knewin_session as base
import scripts.probe_knewin_session_auto as auto
from src.session_auth_probe import is_login_like_url, url_fingerprint

GUIDED_TIMEOUT_SECONDS = 600
SETTLE_MILLISECONDS = 5000
CLICK_COUNTER_JS = """
() => {
  window.__knewinGuidedClickCount = 0;
  document.addEventListener('click', () => {
    window.__knewinGuidedClickCount += 1;
  }, true);
  return true;
}
"""


def is_newsstream_observation(item: dict) -> bool:
    return (
        str(item.get("host") or "").casefold() == "news.knewin.com"
        and str(item.get("route_template") or "").startswith("/newsstream/")
        and isinstance(item.get("status"), int)
        and 200 <= item["status"] < 300
    )


def interaction_ready(click_count: int, delta: list[dict]) -> bool:
    return click_count > 0 and any(is_newsstream_observation(item) for item in delta)


def blocked_evidence(phase: str, auth, page, network, schemas, **extra) -> dict:
    payload = {
        "status": "BLOCKED",
        "phase": phase,
        "auth_mode": getattr(auth, "auth_mode", "unknown"),
        "location": url_fingerprint(page.url),
        "network_inventory": base.safe_inventory(network),
        "response_schema_inventory": base.safe_schema_inventory(schemas),
        "schema_probe_diagnostics": base.safe_schema_diagnostics(),
        "session_reused": False,
        "values_persisted": False,
        "secrets_captured": False,
    }
    payload.update(extra)
    return payload


def main() -> int:
    news.configure()
    base.SCHEMA_DIAGNOSTICS.clear()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright não instalado. Execute: python scripts/setup_local.py", file=sys.stderr)
        return 30

    base.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    base.EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        schemes: set[str] = set()
        hosts: set[str] = set()
        network: list[dict] = []
        schemas: list[dict] = []
        context = p.chromium.launch_persistent_context(str(base.PROFILE_DIR), headless=False, args=["--disable-sync"])
        base.attach_request_probe(context, schemes, hosts)
        base.attach_response_probe(context, network, schemas)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(base.PORTAL_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        auth = auto.wait_for_auth(page, context, schemes, hosts, news.AUTH_TIMEOUT_SECONDS)
        if auth is None or auth.auth_mode == "unknown" or is_login_like_url(page.url):
            evidence = blocked_evidence(
                "initial_authentication", auth, page, network, schemas,
                human_login_required=True,
            )
            base.write_evidence(evidence)
            context.close()
            return 32

        page.wait_for_timeout(SETTLE_MILLISECONDS)
        baseline_network = len(network)
        baseline_schemas = len(schemas)
        page.evaluate(CLICK_COUNTER_JS)
        print(
            "Sessão autenticada. No navegador Knewin, clique em uma pesquisa conhecida usada para clipping. "
            "Não é necessário voltar ao terminal; a captura encerra ao observar o tráfego newsstream posterior ao clique.",
            flush=True,
        )

        deadline = time.monotonic() + GUIDED_TIMEOUT_SECONDS
        click_count = 0
        while time.monotonic() < deadline:
            try:
                click_count = int(page.evaluate("() => window.__knewinGuidedClickCount || 0"))
            except Exception:
                click_count = 0
            delta = network[baseline_network:]
            if interaction_ready(click_count, delta):
                page.wait_for_timeout(2500)
                break
            page.wait_for_timeout(1000)
        else:
            delta = network[baseline_network:]
            delta_schemas = schemas[baseline_schemas:]
            evidence = blocked_evidence(
                "guided_interaction_timeout", auth, page, delta, delta_schemas,
                human_login_required=False,
                guided_click_count=min(click_count, 999),
                guided_selection_name_persisted=False,
                interaction_observed=False,
            )
            base.write_evidence(evidence)
            context.close()
            return 37

        delta = network[baseline_network:]
        delta_schemas = schemas[baseline_schemas:]
        newsstream_count = sum(1 for item in delta if is_newsstream_observation(item))
        evidence = {
            "status": "PASS",
            "phase": "guided_interaction_completed",
            "auth_mode": auth.auth_mode,
            "location": url_fingerprint(page.url),
            "interaction_observed": True,
            "guided_click_count": min(click_count, 999),
            "guided_selection_name_persisted": False,
            "newsstream_delta_count": newsstream_count,
            "network_inventory": base.safe_inventory(delta),
            "response_schema_inventory": base.safe_schema_inventory(delta_schemas),
            "schema_probe_diagnostics": base.safe_schema_diagnostics(),
            "session_reused": False,
            "human_login_required": False,
            "values_persisted": False,
            "secrets_captured": False,
        }
        base.write_evidence(evidence)
        context.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
