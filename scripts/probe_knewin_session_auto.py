from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.probe_knewin_session as base
from src.session_auth_probe import is_login_like_url, session_reuse_is_valid, url_fingerprint

AUTH_TIMEOUT_SECONDS = 180
NAVIGATION_TERMS = (
    ("busca", 130),
    ("buscar", 130),
    ("pesquisa", 125),
    ("pesquisar", 125),
    ("clipping", 100),
    ("notícias", 90),
    ("noticias", 90),
    ("monitoramento", 70),
)
SEARCH_TERMS = ("buscar", "busca", "pesquisar", "pesquisa", "termo", "palavra", "search")
FIELD_CONTEXT_TERMS = SEARCH_TERMS + (
    "consulta", "consultar", "query", "keyword", "palavra-chave", "expressão", "expressao", "conteúdo", "conteudo",
)
SUBMIT_TERMS = ("buscar", "pesquisar", "consultar", "aplicar")
SENSITIVE_FIELD_TYPES = {"password", "email", "hidden", "checkbox", "radio", "file"}
TEXT_FALLBACK_TYPES = {"", "text"}


def normalize_label(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def score_navigation_label(label: str | None) -> int:
    value = normalize_label(label)
    best = 0
    for term, score in NAVIGATION_TERMS:
        if value == term:
            best = max(best, score + 5)
        elif term in value:
            best = max(best, score)
    return best


def score_search_attrs(attrs: dict[str, str | None]) -> int:
    field_type = normalize_label(attrs.get("type"))
    if field_type in SENSITIVE_FIELD_TYPES:
        return 0
    score = 0
    if field_type == "search":
        score += 60
    role = normalize_label(attrs.get("role"))
    if role == "searchbox":
        score += 60
    for key in ("placeholder", "aria-label", "name", "title"):
        value = normalize_label(attrs.get(key))
        if any(term in value for term in SEARCH_TERMS):
            score += 40
    return score


def score_field_context(value: str | None) -> int:
    text = normalize_label(value)
    return 50 if any(term in text for term in FIELD_CONTEXT_TERMS) else 0


def associated_field_text(item) -> str:
    try:
        return str(item.evaluate("""el => {
            const parts = [];
            if (el.labels) for (const label of Array.from(el.labels)) parts.push(label.innerText || label.textContent || '');
            const parent = el.closest('label');
            if (parent) parts.push(parent.innerText || parent.textContent || '');
            return parts.join(' ');
        }""") or "")
    except Exception:
        return ""


def is_safe_text_fallback(attrs: dict[str, str | None], tag_name: str) -> bool:
    field_type = normalize_label(attrs.get("type"))
    if field_type in SENSITIVE_FIELD_TYPES:
        return False
    if tag_name.casefold() == "textarea":
        return True
    return field_type in TEXT_FALLBACK_TYPES


def load_known_query() -> str:
    payload = json.loads((ROOT / "config" / "people.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError("config/people.json sem pessoa para consulta conhecida")
    return next(iter(payload.keys()))


def wait_for_auth(page, context, schemes: set[str], oidc_hosts: set[str], timeout_seconds: int):
    deadline = time.monotonic() + timeout_seconds
    last = None
    while time.monotonic() < deadline:
        try:
            last = base.collect(page, context, schemes, oidc_hosts)
            if last.auth_mode != "unknown" and not is_login_like_url(page.url):
                return last
        except Exception:
            pass
        page.wait_for_timeout(1500)
    return last


def _visible_text(locator) -> str:
    try:
        text = locator.inner_text(timeout=500)
    except Exception:
        text = ""
    if not text:
        try:
            text = locator.get_attribute("aria-label") or locator.get_attribute("title") or ""
        except Exception:
            text = ""
    return text


def choose_navigation(page):
    locator = page.locator("a,button,[role='link'],[role='button']")
    candidates = []
    for index in range(min(locator.count(), 300)):
        item = locator.nth(index)
        try:
            if not item.is_visible():
                continue
        except Exception:
            continue
        score = score_navigation_label(_visible_text(item))
        if score:
            candidates.append((score, index, item))
    if not candidates:
        return None, {"candidate_count": 0, "top_score": 0, "ambiguous": False}
    candidates.sort(key=lambda value: (-value[0], value[1]))
    top_score = candidates[0][0]
    tied = [item for item in candidates if item[0] == top_score]
    meta = {"candidate_count": len(candidates), "top_score": top_score, "ambiguous": len(tied) != 1}
    return (tied[0][2] if len(tied) == 1 else None), meta


def choose_search_field(page):
    locator = page.locator("input,textarea,[role='searchbox']")
    candidates = []
    fallbacks = []
    context_match_count = 0
    for index in range(min(locator.count(), 200)):
        item = locator.nth(index)
        try:
            if not item.is_visible() or not item.is_enabled():
                continue
            attrs = {
                "type": item.get_attribute("type"),
                "role": item.get_attribute("role"),
                "placeholder": item.get_attribute("placeholder"),
                "aria-label": item.get_attribute("aria-label"),
                "name": item.get_attribute("name"),
                "title": item.get_attribute("title"),
            }
            tag_name = item.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            continue
        score = score_search_attrs(attrs)
        context_score = score_field_context(associated_field_text(item))
        if context_score:
            context_match_count += 1
            score += context_score
        if score:
            candidates.append((score, index, item))
        elif is_safe_text_fallback(attrs, str(tag_name)):
            fallbacks.append((index, item))
    if candidates:
        candidates.sort(key=lambda value: (-value[0], value[1]))
        top_score = candidates[0][0]
        tied = [item for item in candidates if item[0] == top_score]
        meta = {
            "candidate_count": len(candidates),
            "top_score": top_score,
            "ambiguous": len(tied) != 1,
            "selection_mode": "scored",
            "context_match_count": context_match_count,
            "fallback_candidate_count": len(fallbacks),
        }
        return (tied[0][2] if len(tied) == 1 else None), meta
    meta = {
        "candidate_count": 0,
        "top_score": 0,
        "ambiguous": len(fallbacks) > 1,
        "selection_mode": "unique_text_fallback" if len(fallbacks) == 1 else "none",
        "context_match_count": context_match_count,
        "fallback_candidate_count": len(fallbacks),
    }
    return (fallbacks[0][1] if len(fallbacks) == 1 else None), meta


def choose_submit(page):
    locator = page.locator("button,[role='button']")
    hits = []
    for index in range(min(locator.count(), 200)):
        item = locator.nth(index)
        try:
            if not item.is_visible() or not item.is_enabled():
                continue
        except Exception:
            continue
        label = normalize_label(_visible_text(item))
        if label in SUBMIT_TERMS:
            hits.append(item)
    return hits[0] if len(hits) == 1 else None


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
    base.SCHEMA_DIAGNOSTICS.clear()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright não instalado. Execute: python scripts/setup_local.py", file=sys.stderr)
        return 30

    query = load_known_query()
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

        auth = wait_for_auth(page, context, schemes, hosts, AUTH_TIMEOUT_SECONDS)
        if auth is None or auth.auth_mode == "unknown" or is_login_like_url(page.url):
            evidence = blocked_evidence("initial_authentication", auth, page, network, schemas, human_login_required=True)
            base.write_evidence(evidence)
            context.close()
            return 32

        authenticated_url = page.url
        nav, nav_meta = choose_navigation(page)
        if nav is not None:
            nav.click()
            page.wait_for_timeout(3000)

        field, search_meta = choose_search_field(page)
        if field is None:
            evidence = blocked_evidence(
                "query_field_discovery", auth, page, network, schemas,
                human_login_required=False, navigation=nav_meta, search=search_meta,
            )
            base.write_evidence(evidence)
            context.close()
            return 35

        before_query = len(network)
        field.fill(query)
        field.press("Enter")
        page.wait_for_timeout(5000)
        if len(network) == before_query:
            submit = choose_submit(page)
            if submit is not None:
                submit.click()
                page.wait_for_timeout(5000)

        new_json_observations = max(0, len(network) - before_query)
        if is_login_like_url(page.url) or new_json_observations == 0:
            evidence = blocked_evidence(
                "query_execution", auth, page, network, schemas,
                human_login_required=False, navigation=nav_meta, search=search_meta,
                query_submitted=True, query_value_persisted=False,
                query_json_observations=new_json_observations,
            )
            base.write_evidence(evidence)
            context.close()
            return 36

        exploration_location = url_fingerprint(page.url)
        context.close()

        second_schemes: set[str] = set()
        second_hosts: set[str] = set()
        second_network: list[dict] = []
        second_schemas: list[dict] = []
        reopened = p.chromium.launch_persistent_context(str(base.PROFILE_DIR), headless=False, args=["--disable-sync"])
        base.attach_request_probe(reopened, second_schemes, second_hosts)
        base.attach_response_probe(reopened, second_network, second_schemas)
        page2 = reopened.pages[0] if reopened.pages else reopened.new_page()
        page2.goto(authenticated_url, wait_until="domcontentloaded")
        page2.wait_for_timeout(3000)
        second = base.collect(page2, reopened, second_schemes, second_hosts)
        reuse_ok = session_reuse_is_valid(authenticated_url, page2.url, second.auth_mode)
        evidence = {
            "status": "PASS" if reuse_ok else "BLOCKED",
            "phase": "completed" if reuse_ok else "session_reuse",
            "initial_auth_mode": auth.auth_mode,
            "reopened_auth_mode": second.auth_mode,
            "initial_location": url_fingerprint(authenticated_url),
            "exploration_location": exploration_location,
            "reopened_location": url_fingerprint(page2.url),
            "redirected_to_login": is_login_like_url(page2.url),
            "navigation": nav_meta,
            "search": search_meta,
            "query_submitted": True,
            "query_value_persisted": False,
            "query_json_observations": new_json_observations,
            "network_inventory": base.safe_inventory(network, second_network),
            "response_schema_inventory": base.safe_schema_inventory(schemas, second_schemas),
            "schema_probe_diagnostics": base.safe_schema_diagnostics(),
            "session_reused": reuse_ok,
            "profile_persisted": True,
            "values_persisted": False,
            "secrets_captured": False,
        }
        base.write_evidence(evidence)
        reopened.close()

    return 0 if evidence["status"] == "PASS" else 33


if __name__ == "__main__":
    raise SystemExit(main())
