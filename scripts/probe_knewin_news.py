from __future__ import annotations

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
SAVED_SEARCH_NAMES: list[str] = []


def extract_saved_search_names(payload) -> list[str]:
    names: list[str] = []
    if not isinstance(payload, list):
        return names
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name)
    return names


def configured_person_names() -> list[str]:
    try:
        payload = json.loads((ROOT / "config" / "people.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    return [name for name in payload if isinstance(name, str) and name.strip()]


def choose_saved_search_name(searches, people: list[str] | None = None) -> tuple[str | None, dict]:
    valid_names = extract_saved_search_names(searches)
    fecap_matches = [name for name in valid_names if "fecap" in auto.normalize_label(name)]
    if len(fecap_matches) == 1:
        return fecap_matches[0], {
            "mode": "saved_search", "match_strategy": "fecap_label",
            "saved_search_count": len(valid_names), "fecap_match_count": 1,
            "configured_person_count": len(people or []), "person_match_count": 0, "selected": True,
        }
    if len(fecap_matches) > 1:
        return None, {
            "mode": "saved_search", "match_strategy": "ambiguous_fecap_label",
            "saved_search_count": len(valid_names), "fecap_match_count": len(fecap_matches),
            "configured_person_count": len(people or []), "person_match_count": 0, "selected": False,
        }

    configured = people if people is not None else configured_person_names()
    normalized_people = [auto.normalize_label(name) for name in configured if auto.normalize_label(name)]
    person_matches: list[str] = []
    for saved_name in valid_names:
        normalized_saved = auto.normalize_label(saved_name)
        if any(person == normalized_saved or person in normalized_saved for person in normalized_people):
            person_matches.append(saved_name)
    unique_matches = list(dict.fromkeys(person_matches))
    meta = {
        "mode": "saved_search", "match_strategy": "configured_person",
        "saved_search_count": len(valid_names), "fecap_match_count": 0,
        "configured_person_count": len(normalized_people), "person_match_count": len(unique_matches),
        "selected": len(unique_matches) == 1,
    }
    return (unique_matches[0] if len(unique_matches) == 1 else None), meta


def attach_response_probe(context, observations: list[dict], schema_observations: list[dict]) -> None:
    ORIGINAL_ATTACH_RESPONSE_PROBE(context, observations, schema_observations)
    def on_response(response) -> None:
        try:
            parsed = urlparse(response.url)
            if (parsed.hostname or "").casefold() != "news.knewin.com":
                return
            if (parsed.path.rstrip("/") or "/") != "/restful/searches":
                return
            if response.status != 200 or response.request.method.upper() != "GET":
                return
            names = extract_saved_search_names(response.json())
            if names:
                SAVED_SEARCH_NAMES.clear(); SAVED_SEARCH_NAMES.extend(names)
        except Exception:
            return
    context.on("response", on_response)


class SavedSearchField:
    def __init__(self, page, name: str, meta: dict):
        self.page = page; self.name = name; self.meta = meta
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
                if item.is_visible(): visible.append(item)
            except Exception:
                continue
        self.meta["dom_match_count"] = len(visible)
        self.meta["clicked"] = len(visible) == 1
        if len(visible) == 1:
            visible[0].click()


def choose_search_field(page):
    field, meta = ORIGINAL_CHOOSE_SEARCH_FIELD(page)
    if field is not None:
        meta = dict(meta); meta["mode"] = "input"; return field, meta
    searches = [{"name": name} for name in SAVED_SEARCH_NAMES]
    name, saved_meta = choose_saved_search_name(searches)
    merged = dict(meta); merged.update(saved_meta)
    if name is None:
        return None, merged
    return SavedSearchField(page, name, merged), merged


def configure() -> None:
    SAVED_SEARCH_NAMES.clear()
    base.PORTAL_URL = PORTAL_URL
    auto.AUTH_TIMEOUT_SECONDS = AUTH_TIMEOUT_SECONDS
    base.attach_response_probe = attach_response_probe
    auto.choose_search_field = choose_search_field


def main() -> int:
    if "--check" in sys.argv:
        print(f"portal={PORTAL_URL} timeout={AUTH_TIMEOUT_SECONDS}")
        return 0
    configure()
    return auto.main()


if __name__ == "__main__":
    raise SystemExit(main())
