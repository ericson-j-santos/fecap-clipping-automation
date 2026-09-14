from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.probe_knewin_news as news
import scripts.probe_knewin_session as base
import scripts.probe_knewin_session_auto as auto
from src.knewin_runtime_validation import (
    TARGET_HOST,
    TARGET_METHOD,
    TARGET_ROUTE,
    build_runtime_validation,
    sanitize_request_contract,
)
from src.session_auth_probe import is_login_like_url, url_fingerprint

DEFAULT_PLAN = ROOT / "evidence" / "private" / "knewin-collector-plan.json"
DEFAULT_OUTPUT = ROOT / "evidence" / "private" / "knewin-runtime-validation.json"


def _is_target(url: str, method: str) -> bool:
    parsed = urlparse(url)
    route = parsed.path.rstrip("/") or "/"
    return (parsed.hostname or "").casefold() == TARGET_HOST and route == TARGET_ROUTE and method.upper() == TARGET_METHOD


def _write(output: Path, payload: dict) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return 0 if payload.get("status") == "RUNTIME_VALIDATED" else 40


def _blocked(output: Path, phase: str, **extra) -> int:
    payload = {
        "status": "BLOCKED",
        "phase": phase,
        "collector_network_enabled": False,
        "values_persisted": False,
        "secrets_captured": False,
    }
    payload.update(extra)
    return _write(output, payload)


def _replay_headers(request) -> dict[str, str]:
    headers = dict(request.all_headers())
    for name in ("content-length", "host", "connection"):
        headers.pop(name, None)
    return headers


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida /restful/search/publications sem persistir credenciais")
    parser.add_argument("--term", default="Fecap")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    ns = parser.parse_args()
    if ns.check:
        print(f"target={TARGET_METHOD} {TARGET_HOST}{TARGET_ROUTE}")
        return 0
    if not ns.plan.is_file():
        return _blocked(ns.output, "plan_missing")
    try:
        plan = json.loads(ns.plan.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _blocked(ns.output, "plan_invalid", error_type=type(exc).__name__)

    news.configure(ns.term)
    base.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _blocked(ns.output, "playwright_missing")

    with sync_playwright() as p:
        schemes: set[str] = set()
        hosts: set[str] = set()
        target_requests = []
        context = p.chromium.launch_persistent_context(str(base.PROFILE_DIR), headless=False, args=["--disable-sync"])
        base.attach_request_probe(context, schemes, hosts)

        def on_request(request) -> None:
            try:
                if _is_target(request.url, request.method):
                    target_requests.append(request)
            except Exception:
                return

        context.on("request", on_request)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(base.PORTAL_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        auth = auto.wait_for_auth(page, context, schemes, hosts, news.AUTH_TIMEOUT_SECONDS)
        if auth is None or auth.auth_mode == "unknown" or is_login_like_url(page.url):
            context.close()
            return _blocked(ns.output, "initial_authentication", human_login_required=True)

        nav, nav_meta = auto.choose_navigation(page)
        if nav is not None:
            nav.click()
            page.wait_for_timeout(3000)
        field, search_meta = news.choose_search_field(page)
        if field is None:
            context.close()
            return _blocked(ns.output, "query_field_discovery", navigation=nav_meta, search=search_meta)

        before = len(target_requests)
        field.fill(ns.term)
        field.press("Enter")
        page.wait_for_timeout(4000)
        if len(target_requests) == before:
            submit = auto.choose_submit(page)
            if submit is not None:
                submit.click()

        deadline = time.monotonic() + 15
        while len(target_requests) == before and time.monotonic() < deadline:
            page.wait_for_timeout(500)
        if len(target_requests) == before:
            context.close()
            return _blocked(ns.output, "publications_request_not_observed", navigation=nav_meta, search=search_meta)

        request = target_requests[before]
        try:
            raw_headers = dict(request.all_headers())
            body = request.post_data_buffer
            contract = sanitize_request_contract(request.url, request.method, raw_headers, body)
        except Exception as exc:
            context.close()
            return _blocked(ns.output, "request_contract_capture", error_type=type(exc).__name__)

        try:
            replay = context.request.fetch(
                request.url,
                method=request.method,
                headers=_replay_headers(request),
                data=body,
                fail_on_status_code=False,
                timeout=30000,
            )
            response_bytes = replay.body()
            response_payload = json.loads(response_bytes.decode("utf-8"))
            validation = build_runtime_validation(plan, contract, replay.url, replay.status, response_payload)
            validation["phase"] = "runtime_replay"
            validation["auth_mode"] = auth.auth_mode
            validation["location"] = url_fingerprint(page.url)
            validation["query_value_persisted"] = False
            validation["human_login_required"] = False
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            context.close()
            return _blocked(ns.output, "replay_response_json", error_type=type(exc).__name__, request_contract=contract)
        except Exception as exc:
            context.close()
            return _blocked(ns.output, "runtime_replay", error_type=type(exc).__name__, request_contract=contract)

        context.close()
        return _write(ns.output, validation)


if __name__ == "__main__":
    raise SystemExit(main())
