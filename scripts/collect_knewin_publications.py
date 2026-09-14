from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.probe_knewin_news as news
import scripts.probe_knewin_session as base
import scripts.probe_knewin_session_auto as auto
from src.knewin_runtime_validation import TARGET_HOST, TARGET_METHOD, TARGET_ROUTE
from src.knewin_session_collector import (
    SessionCollectorError,
    build_run_evidence,
    functional_output,
    session_reuse_ui_is_valid,
    validate_live_response,
    validate_runtime_gate,
)
from src.session_auth_probe import is_login_like_url, url_fingerprint

DEFAULT_RUNTIME_EVIDENCE = ROOT / "evidence" / "private" / "knewin-runtime-validation.json"
DEFAULT_OUTPUT = ROOT / "data" / "private" / "knewin-fecap-items.json"
DEFAULT_RUN_EVIDENCE = ROOT / "evidence" / "private" / "knewin-authenticated-collector-run.json"
SESSION_REUSE_TIMEOUT_SECONDS = 30


def _is_target(response) -> bool:
    try:
        parsed = urlparse(response.url)
        route = parsed.path.rstrip("/") or "/"
        return (
            (parsed.hostname or "").casefold() == TARGET_HOST
            and route == TARGET_ROUTE
            and response.request.method.upper() == TARGET_METHOD
        )
    except Exception:
        return False


def _write_json(path: Path, payload: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def _blocked(path: Path, phase: str, **extra) -> int:
    payload = {
        "status": "BLOCKED",
        "mode": "one_shot",
        "phase": phase,
        "collector_network_enabled": False,
        "scheduled": False,
        "production_enabled": False,
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "values_persisted": False,
        "secrets_captured": False,
    }
    payload.update(extra)
    _write_json(path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 50


def _wait_for_reusable_session(page, context, schemes: set[str], hosts: set[str]):
    deadline = time.monotonic() + SESSION_REUSE_TIMEOUT_SECONDS
    last_auth = None
    last_nav_meta: dict = {}
    while time.monotonic() < deadline:
        try:
            last_auth = base.collect(page, context, schemes, hosts)
            nav, nav_meta = auto.choose_navigation(page)
            last_nav_meta = nav_meta
            if session_reuse_ui_is_valid(last_auth.auth_mode, nav_meta):
                return last_auth, nav, nav_meta, is_login_like_url(page.url)
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return last_auth, None, last_nav_meta, is_login_like_url(page.url)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coletor one-shot autenticado do Knewin News")
    parser.add_argument("--term", default="Fecap")
    parser.add_argument("--runtime-evidence", type=Path, default=DEFAULT_RUNTIME_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_RUN_EVIDENCE)
    parser.add_argument("--once", action="store_true", help="autoriza somente uma coleta interativa, sem agendamento")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    if ns.check:
        print(f"mode=one_shot target={TARGET_METHOD} {TARGET_HOST}{TARGET_ROUTE} production_enabled=false")
        return 0
    if not ns.once:
        return _blocked(ns.evidence, "one_shot_authorization_missing")
    if not ns.runtime_evidence.is_file():
        return _blocked(ns.evidence, "runtime_evidence_missing")

    try:
        runtime = json.loads(ns.runtime_evidence.read_text(encoding="utf-8"))
        validate_runtime_gate(runtime)
    except (OSError, json.JSONDecodeError, SessionCollectorError) as exc:
        return _blocked(ns.evidence, "runtime_gate", error_type=type(exc).__name__)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _blocked(ns.evidence, "playwright_missing")

    news.configure(ns.term)
    base.PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        schemes: set[str] = set()
        hosts: set[str] = set()
        target_responses = []
        context = p.chromium.launch_persistent_context(
            str(base.PROFILE_DIR), headless=False, args=["--disable-sync"]
        )
        try:
            base.attach_request_probe(context, schemes, hosts)
            context.on("response", lambda response: target_responses.append(response) if _is_target(response) else None)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(base.PORTAL_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            auth, nav, nav_meta, stale_login_fragment = _wait_for_reusable_session(
                page, context, schemes, hosts
            )
            if auth is None or nav is None or not session_reuse_ui_is_valid(auth.auth_mode, nav_meta):
                return _blocked(
                    ns.evidence,
                    "initial_authentication",
                    human_login_required=True,
                    navigation=nav_meta,
                    login_like_url=is_login_like_url(page.url),
                )

            nav.click()
            page.wait_for_timeout(3000)
            field, search_meta = news.choose_search_field(page)
            if field is None:
                return _blocked(ns.evidence, "query_field_discovery", navigation=nav_meta, search=search_meta)

            before = len(target_responses)
            field.fill(ns.term)
            field.press("Enter")
            page.wait_for_timeout(4000)
            if len(target_responses) == before:
                submit = auto.choose_submit(page)
                if submit is not None:
                    submit.click()

            deadline = time.monotonic() + 15
            while len(target_responses) == before and time.monotonic() < deadline:
                page.wait_for_timeout(500)
            if len(target_responses) == before:
                return _blocked(ns.evidence, "publications_response_not_observed")

            response = next(
                (item for item in target_responses[before:] if 200 <= item.status < 300),
                target_responses[before],
            )
            try:
                payload = response.json()
                publications, response_shape = validate_live_response(runtime, response.status, payload)
            except Exception as exc:
                return _blocked(
                    ns.evidence,
                    "response_validation",
                    error_type=type(exc).__name__,
                    response_status=getattr(response, "status", None),
                )

            output_payload = functional_output(ns.term, runtime, publications)
            output_raw = _write_json(ns.output, output_payload)
            output_digest = sha256(output_raw).hexdigest()
            run_evidence = build_run_evidence(
                runtime, publications, response.status, response_shape, output_digest
            )
            run_evidence["phase"] = "authenticated_collection"
            run_evidence["auth_mode"] = auth.auth_mode
            run_evidence["location"] = url_fingerprint(page.url)
            run_evidence["human_login_required"] = False
            run_evidence["stale_login_fragment_accepted"] = stale_login_fragment
            run_evidence["functional_output_path"] = str(ns.output)
            _write_json(ns.evidence, run_evidence)
            print(json.dumps(run_evidence, ensure_ascii=False, indent=2))
            return 0
        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
