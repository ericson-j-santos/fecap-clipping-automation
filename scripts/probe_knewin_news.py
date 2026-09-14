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

PORTAL_URL = "https://news.knewin.com/#/login"
AUTH_TIMEOUT_SECONDS = 600
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
        if isinstance(key, str) and key.strip(): terms.append(key)
        if isinstance(value, str) and value.strip(): terms.append(value)
    return list(dict.fromkeys(terms))


def active_query() -> str:
    if ACTIVE_SEARCH_TERM and ACTIVE_SEARCH_TERM.strip():
        return ACTIVE_SEARCH_TERM.strip()
    return ORIGINAL_LOAD_KNOWN_QUERY()


def choose_saved_search_name(searches, terms: list[str] | None = None) -> tuple[str | None, dict]:
    valid_names = extract_saved_search_names(searches)
    fecap_matches = [name for name in valid_names if "fecap" in auto.normalize_label(name)]
    if len(fecap_matches) == 1:
        return fecap_matches[0], {"mode":"saved_search","match_strategy":"fecap_label","saved_search_count":len(valid_names),"fecap_match_count":1,"configured_term_count":len(terms or []),"configured_term_match_count":0,"selected":True}
    if len(fecap_matches) > 1:
        return None, {"mode":"saved_search","match_strategy":"ambiguous_fecap_label","saved_search_count":len(valid_names),"fecap_match_count":len(fecap_matches),"configured_term_count":len(terms or []),"configured_term_match_count":0,"selected":False}

    configured = terms if terms is not None else configured_search_terms()
    normalized_terms = [auto.normalize_label(term) for term in configured if auto.normalize_label(term)]
    matches: list[str] = []
    for saved_name in valid_names:
        normalized_saved = auto.normalize_label(saved_name)
        if any(term == normalized_saved or term in normalized_saved for term in normalized_terms):
            matches.append(saved_name)
    unique_matches = list(dict.fromkeys(matches))
    meta = {"mode":"saved_search","match_strategy":"configured_term","saved_search_count":len(valid_names),"fecap_match_count":0,"configured_term_count":len(normalized_terms),"configured_term_match_count":len(unique_matches),"selected":len(unique_matches)==1}
    return (unique_matches[0] if len(unique_matches) == 1 else None), meta


def attach_response_probe(context, observations: list[dict], schema_observations: list[dict]) -> None:
    ORIGINAL_ATTACH_RESPONSE_PROBE(context, observations, schema_observations)
    def on_response(response) -> None:
        try:
            parsed = urlparse(response.url)
            if (parsed.hostname or "").casefold() != "news.knewin.com" or (parsed.path.rstrip("/") or "/") != "/restful/searches": return
            if response.status != 200 or response.request.method.upper() != "GET": return
            names = extract_saved_search_names(response.json())
            if names: SAVED_SEARCH_NAMES.clear(); SAVED_SEARCH_NAMES.extend(names)
        except Exception:
            return
    context.on("response", on_response)


class SavedSearchField:
    def __init__(self, page, name: str, meta: dict): self.page=page; self.name=name; self.meta=meta
    def fill(self, _value: str) -> None: self.meta["query_value_persisted"] = False
    def press(self, key: str) -> None:
        if key != "Enter": return
        locator = self.page.get_by_text(self.name, exact=True); visible=[]
        for index in range(min(locator.count(), 50)):
            item=locator.nth(index)
            try:
                if item.is_visible(): visible.append(item)
            except Exception: continue
        self.meta["dom_match_count"]=len(visible); self.meta["clicked"]=len(visible)==1
        if len(visible)==1: visible[0].click()


def choose_search_field(page):
    field, meta = ORIGINAL_CHOOSE_SEARCH_FIELD(page)
    if field is not None:
        meta=dict(meta); meta["mode"]="input"; return field, meta
    name, saved_meta = choose_saved_search_name([{"name": n} for n in SAVED_SEARCH_NAMES])
    merged=dict(meta); merged.update(saved_meta)
    return (SavedSearchField(page, name, merged), merged) if name is not None else (None, merged)


def configure(term: str | None = None) -> None:
    global ACTIVE_SEARCH_TERM
    ACTIVE_SEARCH_TERM = term.strip() if isinstance(term, str) and term.strip() else None
    SAVED_SEARCH_NAMES.clear(); base.PORTAL_URL=PORTAL_URL; auto.AUTH_TIMEOUT_SECONDS=AUTH_TIMEOUT_SECONDS
    base.attach_response_probe=attach_response_probe; auto.choose_search_field=choose_search_field; auto.load_known_query=active_query


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sonda autenticada do Knewin News")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--term", type=str, default=None)
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    if ns.check:
        print(f"portal={PORTAL_URL} timeout={AUTH_TIMEOUT_SECONDS} term={ns.term or ''}")
        return 0
    configure(ns.term)
    return auto.main()


if __name__ == "__main__": raise SystemExit(main())
