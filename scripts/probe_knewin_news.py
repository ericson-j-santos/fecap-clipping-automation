from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.probe_knewin_session as base
import scripts.probe_knewin_session_auto as auto
from src.session_auth_probe import is_login_like_url, url_fingerprint

PORTAL_URL = "https://news.knewin.com/#/login"
AUTH_TIMEOUT_SECONDS = 600
ADVANCED_TAB_LABELS = {"avançada", "avancada"}
ORIGINAL_CHOOSE_SEARCH_FIELD = auto.choose_search_field
ORIGINAL_ATTACH_RESPONSE_PROBE = base.attach_response_probe
ORIGINAL_LOAD_KNOWN_QUERY = auto.load_known_query
SAVED_SEARCH_NAMES: list[str] = []
ACTIVE_SEARCH_TERM: str | None = None


def extract_saved_search_names(payload) -> list[str]:
    if not isinstance(payload, list):
        return []
    return [item["name"] for item in payload if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip()]


def configured_search_terms() -> list[str]:
    if ACTIVE_SEARCH_TERM and ACTIVE_SEARCH_TERM.strip():
        return [ACTIVE_SEARCH_TERM.strip()]
    try:
        payload = json.loads((ROOT / "config" / "people.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    terms: list[str] = []
    for key, value in payload.items():
        if isinstance(key, str) and key.strip():
            terms.append(key)
        if isinstance(value, str) and value.strip():
            terms.append(value)
    return list(dict.fromkeys(terms))


def active_query() -> str:
    if ACTIVE_SEARCH_TERM and ACTIVE_SEARCH_TERM.strip():
        return ACTIVE_SEARCH_TERM.strip()
    return ORIGINAL_LOAD_KNOWN_QUERY()


def choose_saved_search_name(searches, terms: list[str] | None = None) -> tuple[str | None, dict]:
    valid_names = extract_saved_search_names(searches)
    fecap_matches = [name for name in valid_names if "fecap" in auto.normalize_label(name)]
    if len(fecap_matches) == 1:
        return fecap_matches[0], {
            "mode": "saved_search",
            "match_strategy": "fecap_label",
            "saved_search_count": len(valid_names),
            "fecap_match_count": 1,
            "configured_term_count": len(terms or []),
            "configured_term_match_count": 0,
            "selected": True,
        }
    if len(fecap_matches) > 1:
        return None, {
            "mode": "saved_search",
            "match_strategy": "ambiguous_fecap_label",
            "saved_search_count": len(valid_names),
            "fecap_match_count": len(fecap_matches),
            "configured_term_count": len(terms or []),
            "configured_term_match_count": 0,
            "selected": False,
        }

    configured = terms if terms is not None else configured_search_terms()
    normalized_terms = [auto.normalize_label(term) for term in configured if auto.normalize_label(term)]
    matches: list[str] = []
    for saved_name in valid_names:
        normalized_saved = auto.normalize_label(saved_name)
        if any(term == normalized_saved or term in normalized_saved for term in normalized_terms):
            matches.append(saved_name)
    unique_matches = list(dict.fromkeys(matches))
    meta = {
        "mode": "saved_search",
        "match_strategy": "configured_term",
        "saved_search_count": len(valid_names),
        "fecap_match_count": 0,
        "configured_term_count": len(normalized_terms),
        "configured_term_match_count": len(unique_matches),
        "selected": len(unique_matches) == 1,
    }
    return (unique_matches[0] if len(unique_matches) == 1 else None), meta


def attach_response_probe(context, observations: list[dict], schema_observations: list[dict]) -> None:
    ORIGINAL_ATTACH_RESPONSE_PROBE(context, observations, schema_observations)

    def on_response(response) -> None:
        try:
            parsed = urlparse(response.url)
            if (parsed.hostname or "").casefold() != "news.knewin.com" or (parsed.path.rstrip("/") or "/") != "/restful/searches":
                return
            if response.status != 200 or response.request.method.upper() != "GET":
                return
            names = extract_saved_search_names(response.json())
            if names:
                SAVED_SEARCH_NAMES.clear()
                SAVED_SEARCH_NAMES.extend(names)
        except Exception:
            return

    context.on("response", on_response)


class SavedSearchField:
    def __init__(self, page, name: str, meta: dict):
        self.page = page
        self.name = name
        self.meta = meta

    def fill(self, _value: str) -> None:
        self.meta["query_value_persisted"] = False

    def press(self, key: str) -> None:
        if key != "Enter":
            return
        locator = self.page.get_by_text(self.name, exact=True)
        visible = []
        for index in range(min(locator.count(), 50)):
            item = locator.nth(index)
            try:
                if item.is_visible():
                    visible.append(item)
            except Exception:
                continue
        self.meta["dom_match_count"] = len(visible)
        self.meta["clicked"] = len(visible) == 1
        if len(visible) == 1:
            visible[0].click()


def is_advanced_tab_label(value: str | None) -> bool:
    return auto.normalize_label(value) in ADVANCED_TAB_LABELS


def _control_text(item) -> str:
    try:
        text = item.inner_text(timeout=500)
    except Exception:
        text = ""
    if not text:
        try:
            text = item.get_attribute("aria-label") or item.get_attribute("title") or ""
        except Exception:
            text = ""
    return str(text or "")


def choose_advanced_search_tab(page):
    locator = page.locator("a,button,[role='tab'],[role='button']")
    hits = []
    for index in range(min(locator.count(), 250)):
        item = locator.nth(index)
        try:
            if not item.is_visible() or not item.is_enabled():
                continue
        except Exception:
            continue
        if is_advanced_tab_label(_control_text(item)):
            hits.append(item)
    meta = {
        "candidate_count": len(hits),
        "ambiguous": len(hits) > 1,
        "selected": len(hits) == 1,
        "clicked": False,
    }
    return (hits[0] if len(hits) == 1 else None), meta


def activate_advanced_search(page) -> dict:
    tab, meta = choose_advanced_search_tab(page)
    if tab is None:
        return meta
    try:
        tab.click()
        page.wait_for_timeout(1800)
        meta["clicked"] = True
    except Exception:
        meta["clicked"] = False
    return meta


def choose_search_field(page):
    advanced_meta = activate_advanced_search(page)
    field, meta = ORIGINAL_CHOOSE_SEARCH_FIELD(page)
    if field is not None:
        meta = dict(meta)
        meta["mode"] = "input"
        meta["advanced_tab"] = advanced_meta
        return field, meta
    name, saved_meta = choose_saved_search_name([{"name": n} for n in SAVED_SEARCH_NAMES])
    merged = dict(meta)
    merged["advanced_tab"] = advanced_meta
    merged.update(saved_meta)
    return (SavedSearchField(page, name, merged), merged) if name is not None else (None, merged)


def configure(term: str | None = None) -> None:
    global ACTIVE_SEARCH_TERM
    ACTIVE_SEARCH_TERM = term.strip() if isinstance(term, str) and term.strip() else None
    SAVED_SEARCH_NAMES.clear()
    base.PORTAL_URL = PORTAL_URL
    auto.AUTH_TIMEOUT_SECONDS = AUTH_TIMEOUT_SECONDS
    base.attach_response_probe = attach_response_probe
    auto.choose_search_field = choose_search_field
    auto.load_known_query = active_query


def query_dom_diagnostic(page) -> dict:
    """Retorna somente estrutura técnica ao redor de 'Buscar por'; nunca valores/texto livre."""
    return page.evaluate(
        r"""() => {
            const norm = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const visible = el => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
            };
            const shallow = el => {
                if (!el) return null;
                const r = el.getBoundingClientRect();
                const classes = Array.from(el.classList || []).filter(Boolean).slice(0, 12);
                return {
                    tag: (el.tagName || '').toLowerCase(),
                    classes,
                    role: el.getAttribute && el.getAttribute('role'),
                    type: el.getAttribute && el.getAttribute('type'),
                    contenteditable: el.getAttribute && el.getAttribute('contenteditable'),
                    width: Math.round(r.width || 0),
                    height: Math.round(r.height || 0),
                    child_count: el.children ? el.children.length : 0,
                };
            };
            const structure = el => {
                const base = shallow(el);
                if (!base) return null;
                const descendants = Array.from(el.querySelectorAll('*'));
                const custom = {};
                for (const node of descendants) {
                    const tag = (node.tagName || '').toLowerCase();
                    if (tag.includes('-')) custom[tag] = (custom[tag] || 0) + 1;
                }
                base.descendant_count = descendants.length;
                base.input_descendants = el.querySelectorAll('input').length;
                base.textarea_descendants = el.querySelectorAll('textarea').length;
                base.iframe_descendants = el.querySelectorAll('iframe').length;
                base.contenteditable_descendants = el.querySelectorAll('[contenteditable]').length;
                base.textbox_descendants = el.querySelectorAll('[role="textbox"],[role="searchbox"]').length;
                base.ql_editor_descendants = el.querySelectorAll('.ql-editor').length;
                base.codemirror_descendants = el.querySelectorAll('.CodeMirror').length;
                base.prosemirror_descendants = el.querySelectorAll('.ProseMirror').length;
                base.data_placeholder_descendants = el.querySelectorAll('[data-placeholder]').length;
                base.custom_descendant_tags = Object.entries(custom).slice(0, 20).map(([tag, count]) => ({tag, count}));
                base.children = Array.from(el.children || []).slice(0, 16).map(shallow);
                return base;
            };

            const all = Array.from(document.querySelectorAll('body *')).filter(visible);
            const matches = all.filter(el => {
                const text = norm(el.innerText || el.textContent || '');
                if (!(text === 'buscar por' || text === 'buscar por *' || text.startsWith('buscar por '))) return false;
                return !Array.from(el.children || []).some(child => {
                    const childText = norm(child.innerText || child.textContent || '');
                    return childText === 'buscar por' || childText === 'buscar por *' || childText.startsWith('buscar por ');
                });
            }).slice(0, 8);

            return {
                anchor_count: matches.length,
                anchors: matches.map(anchor => {
                    const ancestors = [];
                    let node = anchor;
                    for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
                        ancestors.push(structure(node));
                    }
                    const parent = anchor.parentElement;
                    const siblings = parent
                        ? Array.from(parent.children || []).slice(0, 20).map(shallow)
                        : [];
                    return {anchor: shallow(anchor), ancestors, siblings};
                }),
                values_persisted: false,
                secrets_captured: false,
            };
        }"""
    )


def run_query_dom_diagnostic() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright não instalado. Execute: python scripts/setup_local.py", file=sys.stderr)
        return 30

    base.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        schemes: set[str] = set()
        hosts: set[str] = set()
        context = p.chromium.launch_persistent_context(
            str(base.PROFILE_DIR), headless=False, args=["--disable-sync"]
        )
        base.attach_request_probe(context, schemes, hosts)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(base.PORTAL_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        auth = auto.wait_for_auth(page, context, schemes, hosts, AUTH_TIMEOUT_SECONDS)
        if auth is None or auth.auth_mode == "unknown" or is_login_like_url(page.url):
            payload = {
                "status": "BLOCKED",
                "phase": "initial_authentication",
                "auth_mode": getattr(auth, "auth_mode", "unknown"),
                "location": url_fingerprint(page.url),
                "human_login_required": True,
                "values_persisted": False,
                "secrets_captured": False,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            context.close()
            return 32

        nav, nav_meta = auto.choose_navigation(page)
        if nav is not None:
            nav.click()
            page.wait_for_timeout(3000)

        advanced_meta = activate_advanced_search(page)
        diagnostic = query_dom_diagnostic(page)
        anchor_count = int(diagnostic.get("anchor_count", 0) or 0)
        payload = {
            "status": "PASS" if anchor_count > 0 else "BLOCKED",
            "phase": "query_dom_diagnostic",
            "auth_mode": auth.auth_mode,
            "location": url_fingerprint(page.url),
            "navigation": nav_meta,
            "advanced_tab": advanced_meta,
            "diagnostic": diagnostic,
            "values_persisted": False,
            "secrets_captured": False,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        context.close()
        return 0 if anchor_count > 0 else 37


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sonda autenticada do Knewin News")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--diagnose-query-dom", action="store_true")
    parser.add_argument("--term", type=str, default=None)
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    if ns.check:
        print(f"portal={PORTAL_URL} timeout={AUTH_TIMEOUT_SECONDS} term={ns.term or ''}")
        return 0
    configure(ns.term)
    if ns.diagnose_query_dom:
        return run_query_dom_diagnostic()
    return auto.main()


if __name__ == "__main__":
    raise SystemExit(main())
