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
from src.knewin_runtime_validation import TARGET_HOST, TARGET_METHOD, TARGET_ROUTE, headers_for_replay
from src.knewin_session_collector import (
    SessionCollectorError,
    build_run_evidence,
    filter_publications_by_date,
    functional_output,
    merge_publications,
    next_page_offset,
    parse_date_window,
    request_with_offset,
    saved_login_submission_is_allowed,
    session_reuse_ui_is_valid,
    validate_live_response,
    validate_runtime_gate,
)
from src.session_auth_probe import is_login_like_url, url_fingerprint

DEFAULT_RUNTIME_EVIDENCE = ROOT / "evidence" / "private" / "knewin-runtime-validation.json"
DEFAULT_OUTPUT = ROOT / "data" / "private" / "knewin-fecap-items.json"
DEFAULT_RUN_EVIDENCE = ROOT / "evidence" / "private" / "knewin-authenticated-collector-run.json"
SESSION_REUSE_TIMEOUT_SECONDS = 30
MAX_HUMAN_LOGIN_TIMEOUT_SECONDS = 600


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


def _paginate_publications(context, response, runtime: dict, max_pages: int):
    try:
        first_payload = response.json()
        first_publications, first_shape = validate_live_response(runtime, response.status, first_payload)
        total = int(first_payload.get("count"))
        request_payload = response.request.post_data_json
        if not isinstance(request_payload, dict):
            raise SessionCollectorError("requisição publications sem corpo JSON reutilizável")
        replay_headers = headers_for_replay(response.request.headers)
    except Exception as exc:
        raise SessionCollectorError(f"falha ao preparar paginação: {type(exc).__name__}") from exc

    all_publications = list(first_publications)
    pages_fetched = 1
    current_payload = first_payload
    last_shape = first_shape

    while True:
        next_offset = next_page_offset(current_payload)
        if next_offset is None:
            break
        if pages_fetched >= max_pages:
            raise SessionCollectorError("max_pages atingido antes do fim da paginação")

        replay_body = request_with_offset(request_payload, next_offset)
        api_response = context.request.post(
            response.url,
            headers=replay_headers,
            data=replay_body,
            timeout=30000,
        )
        payload = api_response.json()
        page_publications, last_shape = validate_live_response(
            runtime, api_response.status, payload
        )
        if not page_publications:
            raise SessionCollectorError("página vazia antes de atingir o count informado")
        all_publications = merge_publications(all_publications, page_publications)
        pages_fetched += 1
        current_payload = payload

    if len(all_publications) < total:
        raise SessionCollectorError(
            f"paginação incompleta: coletados={len(all_publications)} count={total}"
        )
    return all_publications, last_shape, pages_fetched, total


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


def effective_auth_timeout_seconds(allow_human_login: bool, requested: int) -> int:
    if not allow_human_login:
        return SESSION_REUSE_TIMEOUT_SECONDS
    if requested < SESSION_REUSE_TIMEOUT_SECONDS or requested > MAX_HUMAN_LOGIN_TIMEOUT_SECONDS:
        raise ValueError(
            f"auth-timeout-seconds deve ficar entre {SESSION_REUSE_TIMEOUT_SECONDS} e {MAX_HUMAN_LOGIN_TIMEOUT_SECONDS}"
        )
    return requested


def _visible_enabled(locator, *, max_items: int = 20):
    matches = []
    for index in range(min(locator.count(), max_items)):
        item = locator.nth(index)
        try:
            if item.is_visible() and item.is_enabled():
                matches.append(item)
        except Exception:
            continue
    return matches


def _saved_login_prefill_state(page):
    """Retorna somente booleanos/contagens; nunca traz valores dos campos para o Python."""
    password_candidates = _visible_enabled(page.locator("input[type='password']"))
    username_candidates = _visible_enabled(
        page.locator(
            "input[type='email'],input[type='text'],input[autocomplete='username'],"
            "input[name*='user' i],input[name*='email' i]"
        )
    )
    state = {
        "username_candidate_count": len(username_candidates),
        "password_candidate_count": len(password_candidates),
        "username_prefilled": False,
        "password_prefilled": False,
        "credential_values_exported": False,
    }
    username = username_candidates[0] if len(username_candidates) == 1 else None
    password = password_candidates[0] if len(password_candidates) == 1 else None
    try:
        if username is not None:
            state["username_prefilled"] = bool(
                username.evaluate("el => Boolean(el && typeof el.value === 'string' && el.value.length > 0)")
            )
        if password is not None:
            state["password_prefilled"] = bool(
                password.evaluate("el => Boolean(el && typeof el.value === 'string' && el.value.length > 0)")
            )
    except Exception:
        state["username_prefilled"] = False
        state["password_prefilled"] = False
    return state, password


def _wait_for_reusable_session(
    page,
    context,
    schemes: set[str],
    hosts: set[str],
    timeout_seconds: int,
):
    deadline = time.monotonic() + timeout_seconds
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
    parser.add_argument("--start-date", help="data inicial inclusiva no formato YYYY-MM-DD")
    parser.add_argument("--end-date", help="data final inclusiva no formato YYYY-MM-DD")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--runtime-evidence", type=Path, default=DEFAULT_RUNTIME_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_RUN_EVIDENCE)
    parser.add_argument("--once", action="store_true", help="autoriza somente uma coleta interativa, sem agendamento")
    parser.add_argument(
        "--allow-human-login",
        action="store_true",
        help="mantém o mesmo navegador aberto para login humano e continua automaticamente após autenticação",
    )
    parser.add_argument(
        "--submit-saved-login",
        action="store_true",
        help="envia Enter somente se login e senha estiverem ambos preenchidos; os valores nunca são exportados",
    )
    parser.add_argument(
        "--auth-timeout-seconds",
        type=int,
        default=MAX_HUMAN_LOGIN_TIMEOUT_SECONDS,
        help="tempo máximo para login humano; usado somente com --allow-human-login",
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    if ns.check:
        timeout = effective_auth_timeout_seconds(ns.allow_human_login, ns.auth_timeout_seconds)
        parse_date_window(ns.start_date, ns.end_date)
        if ns.max_pages < 1 or ns.max_pages > 1000:
            raise ValueError("max_pages deve ficar entre 1 e 1000")
        print(
            f"mode=one_shot target={TARGET_METHOD} {TARGET_HOST}{TARGET_ROUTE} "
            f"production_enabled=false allow_human_login={str(ns.allow_human_login).lower()} "
            f"submit_saved_login={str(ns.submit_saved_login).lower()} auth_timeout_seconds={timeout} "
            f"date_window={str(bool(ns.start_date)).lower()} max_pages={ns.max_pages}"
        )
        return 0
    if not ns.once:
        return _blocked(ns.evidence, "one_shot_authorization_missing")
    try:
        auth_timeout_seconds = effective_auth_timeout_seconds(
            ns.allow_human_login, ns.auth_timeout_seconds
        )
        start_date, end_date = parse_date_window(ns.start_date, ns.end_date)
        if ns.max_pages < 1 or ns.max_pages > 1000:
            raise ValueError("max_pages deve ficar entre 1 e 1000")
    except (ValueError, SessionCollectorError) as exc:
        return _blocked(ns.evidence, "invalid_collection_window", error=str(exc))
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
        saved_login_state = {
            "username_candidate_count": 0,
            "password_candidate_count": 0,
            "username_prefilled": False,
            "password_prefilled": False,
            "credential_values_exported": False,
        }
        saved_login_submit_attempted = False
        context = p.chromium.launch_persistent_context(
            str(base.PROFILE_DIR), headless=False, args=["--disable-sync"]
        )
        try:
            base.attach_request_probe(context, schemes, hosts)
            context.on("response", lambda response: target_responses.append(response) if _is_target(response) else None)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(base.PORTAL_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            if ns.submit_saved_login and is_login_like_url(page.url):
                saved_login_state, password_field = _saved_login_prefill_state(page)
                if saved_login_submission_is_allowed(
                    explicit_request=True,
                    username_prefilled=saved_login_state["username_prefilled"],
                    password_prefilled=saved_login_state["password_prefilled"],
                ) and password_field is not None:
                    password_field.press("Enter")
                    saved_login_submit_attempted = True
                    page.wait_for_timeout(1500)

            auth, nav, nav_meta, stale_login_fragment = _wait_for_reusable_session(
                page, context, schemes, hosts, auth_timeout_seconds
            )
            if auth is None or nav is None or not session_reuse_ui_is_valid(auth.auth_mode, nav_meta):
                return _blocked(
                    ns.evidence,
                    "initial_authentication",
                    human_login_required=True,
                    human_login_flow_enabled=ns.allow_human_login,
                    saved_login_submission_requested=ns.submit_saved_login,
                    saved_login_submit_attempted=saved_login_submit_attempted,
                    saved_login=saved_login_state,
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
                publications, response_shape, pages_fetched, source_count = _paginate_publications(
                    context, response, runtime, ns.max_pages
                )
                filtered_publications = filter_publications_by_date(
                    publications, start_date, end_date
                )
            except Exception as exc:
                return _blocked(
                    ns.evidence,
                    "response_validation",
                    error_type=type(exc).__name__,
                    response_status=getattr(response, "status", None),
                )

            output_payload = functional_output(
                ns.term,
                runtime,
                filtered_publications,
                start_date=ns.start_date,
                end_date=ns.end_date,
            )
            output_raw = _write_json(ns.output, output_payload)
            output_digest = sha256(output_raw).hexdigest()
            run_evidence = build_run_evidence(
                runtime,
                filtered_publications,
                response.status,
                response_shape,
                output_digest,
                pages_fetched=pages_fetched,
                source_count=source_count,
                start_date=ns.start_date,
                end_date=ns.end_date,
            )
            run_evidence["phase"] = "authenticated_collection"
            run_evidence["auth_mode"] = auth.auth_mode
            run_evidence["location"] = url_fingerprint(page.url)
            run_evidence["human_login_required"] = False
            run_evidence["human_login_flow_enabled"] = ns.allow_human_login
            run_evidence["saved_login_submission_requested"] = ns.submit_saved_login
            run_evidence["saved_login_submit_attempted"] = saved_login_submit_attempted
            run_evidence["saved_login"] = saved_login_state
            run_evidence["stale_login_fragment_accepted"] = stale_login_fragment
            run_evidence["functional_output_path"] = str(ns.output)
            _write_json(ns.evidence, run_evidence)
            print(json.dumps(run_evidence, ensure_ascii=False, indent=2))
            return 0
        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
