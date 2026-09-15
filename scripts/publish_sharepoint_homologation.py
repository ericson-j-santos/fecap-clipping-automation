from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.sharepoint_homologation import (
    TARGET_FOLDER,
    TARGET_SITE_TITLE,
    SharePointHomologationError,
    SiteCandidate,
    build_evidence,
    choose_existing_site,
    deterministic_filename,
    normalize_text,
    remote_file_decision,
    site_candidate,
)

PORTAL_URL = "https://www.microsoft365.com/launch/sharepoint"
PROFILE_DIR = Path.home() / ".fecap-clipping" / "sharepoint-profile"
DEFAULT_WORKBOOK = ROOT / "data" / "private" / "fecap-clipping-homologacao.xlsx"
DEFAULT_EVIDENCE = ROOT / "evidence" / "private" / "sharepoint-homologation-run.json"
SESSION_REUSE_TIMEOUT_SECONDS = 30
MAX_HUMAN_LOGIN_TIMEOUT_SECONDS = 600


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _blocked(path: Path, phase: str, **extra) -> int:
    payload = {
        "status": "BLOCKED",
        "mode": "one_shot",
        "phase": phase,
        "external_destination_enabled": False,
        "scheduled": False,
        "production_enabled": False,
        "credentials_persisted": False,
        "cookies_persisted_in_evidence": False,
        "tokens_persisted": False,
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


def _is_login_like(page) -> bool:
    host = (urlparse(page.url).hostname or "").casefold()
    if host in {
        "login.microsoftonline.com",
        "login.live.com",
        "account.live.com",
        "login.windows.net",
    }:
        return True
    try:
        password = page.locator("input[type='password']")
        for index in range(min(password.count(), 10)):
            if password.nth(index).is_visible():
                return True
    except Exception:
        pass
    return False


def _authenticated_surface(page) -> bool:
    if _is_login_like(page):
        return False
    host = (urlparse(page.url).hostname or "").casefold()
    if host.endswith(".sharepoint.com"):
        return True
    if host in {"www.microsoft365.com", "m365.cloud.microsoft", "www.office.com"}:
        try:
            body = normalize_text(page.locator("body").inner_text(timeout=2000))
        except Exception:
            return False
        return "sharepoint" in body or "sites" in body or "sites" in normalize_text(page.title())
    return False


def _wait_for_auth(page, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _authenticated_surface(page):
            return True
        page.wait_for_timeout(1000)
    return False


def _visible_enabled(locator, max_items: int = 100):
    items = []
    for index in range(min(locator.count(), max_items)):
        item = locator.nth(index)
        try:
            if item.is_visible() and item.is_enabled():
                items.append(item)
        except Exception:
            continue
    return items


def _click_named(page, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        rx = re.compile(pattern, re.I)
        for role in ("button", "link", "menuitem", "option"):
            try:
                locator = page.get_by_role(role, name=rx)
                visible = _visible_enabled(locator, 20)
                if len(visible) == 1:
                    visible[0].click()
                    return True
            except Exception:
                continue
    return False


def _collect_site_candidates(page) -> list[SiteCandidate]:
    candidates: dict[str, SiteCandidate] = {}
    current = site_candidate(page.title(), page.url)
    if current is not None:
        candidates[current.url] = current
    try:
        anchors = page.locator("a[href]")
        for index in range(min(anchors.count(), 400)):
            item = anchors.nth(index)
            try:
                if not item.is_visible():
                    continue
                href = item.get_attribute("href") or ""
                text = (item.inner_text(timeout=500) or "").strip()
                candidate = site_candidate(text, href)
                if candidate is not None:
                    previous = candidates.get(candidate.url)
                    if previous is None or candidate.score > previous.score:
                        candidates[candidate.url] = candidate
            except Exception:
                continue
    except Exception:
        pass
    return sorted(candidates.values(), key=lambda item: (-item.score, normalize_text(item.title), item.url))


def _find_text_input(page, tokens: tuple[str, ...]):
    for item in _visible_enabled(page.locator("input"), 60):
        try:
            meta = " ".join(
                filter(
                    None,
                    [
                        item.get_attribute("aria-label"),
                        item.get_attribute("placeholder"),
                        item.get_attribute("name"),
                        item.get_attribute("id"),
                    ],
                )
            )
        except Exception:
            continue
        normalized = normalize_text(meta)
        if any(normalize_text(token) in normalized for token in tokens):
            return item
    return None


def _wait_for_site_url(page, timeout_seconds: int = 120) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        parsed = urlparse(page.url)
        if (parsed.hostname or "").casefold().endswith(".sharepoint.com") and (
            "/sites/" in parsed.path.casefold() or "/teams/" in parsed.path.casefold()
        ):
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        page.wait_for_timeout(1000)
    return None


def _create_communication_site(page) -> SiteCandidate | None:
    if not _click_named(page, (r"^criar site$", r"^create site$", r"criar.*site", r"create.*site")):
        return None
    page.wait_for_timeout(1500)
    if not _click_named(
        page,
        (
            r"site de comunica[cç][aã]o",
            r"communication site",
            r"comunica[cç][aã]o",
            r"communication",
        ),
    ):
        return None
    page.wait_for_timeout(1200)
    field = _find_text_input(page, ("nome do site", "site name", "titulo do site", "site title"))
    if field is None:
        return None
    field.fill(TARGET_SITE_TITLE)
    page.wait_for_timeout(1000)
    for _ in range(4):
        if _click_named(page, (r"^criar$", r"^create$", r"^concluir$", r"^finish$", r"^pr[oó]ximo$", r"^next$")):
            page.wait_for_timeout(1800)
            site_url = _wait_for_site_url(page, 20)
            if site_url:
                return site_candidate(TARGET_SITE_TITLE, site_url)
        else:
            break
    site_url = _wait_for_site_url(page, 90)
    return site_candidate(TARGET_SITE_TITLE, site_url) if site_url else None


def _library_candidate(page):
    scored = []
    try:
        anchors = page.locator("a[href]")
        for index in range(min(anchors.count(), 400)):
            item = anchors.nth(index)
            try:
                if not item.is_visible():
                    continue
                href = item.get_attribute("href") or ""
                text = (item.inner_text(timeout=500) or "").strip()
                normalized = normalize_text(f"{text} {unquote(href)}")
                score = 0
                if normalize_text(text) in {
                    "documents",
                    "documentos",
                    "shared documents",
                    "documentos compartilhados",
                }:
                    score += 100
                if "shared documents" in normalized or "documentos compartilhados" in normalized:
                    score += 70
                if "forms/allitems.aspx" in normalized:
                    score += 20
                if score:
                    scored.append((score, text or "Documents", href, item))
            except Exception:
                continue
    except Exception:
        pass
    scored.sort(key=lambda value: (-value[0], normalize_text(value[1]), value[2]))
    if not scored:
        return None
    if len(scored) > 1 and scored[0][0] == scored[1][0] and scored[0][2] != scored[1][2]:
        return None
    return scored[0]


def _folder_or_file_names(page, max_items: int = 500) -> list[str]:
    names = []
    try:
        anchors = page.locator("a")
        for index in range(min(anchors.count(), max_items)):
            item = anchors.nth(index)
            try:
                if item.is_visible():
                    text = (item.inner_text(timeout=500) or "").strip()
                    if text:
                        names.append(text)
            except Exception:
                continue
    except Exception:
        pass
    return names


def _open_or_create_folder(page) -> bool:
    names = _folder_or_file_names(page)
    if any(normalize_text(name) == normalize_text(TARGET_FOLDER) for name in names):
        locator = page.get_by_text(TARGET_FOLDER, exact=True)
        visible = _visible_enabled(locator, 20)
        if len(visible) != 1:
            return False
        visible[0].click()
        page.wait_for_timeout(1500)
        return True

    if not _click_named(page, (r"^novo$", r"^new$")):
        return False
    page.wait_for_timeout(600)
    if not _click_named(page, (r"^pasta$", r"^folder$")):
        return False
    page.wait_for_timeout(600)
    field = _find_text_input(page, ("nome da pasta", "folder name", "nome", "name"))
    if field is None:
        return False
    field.fill(TARGET_FOLDER)
    if not _click_named(page, (r"^criar$", r"^create$")):
        return False
    page.wait_for_timeout(1500)
    locator = page.get_by_text(TARGET_FOLDER, exact=True)
    visible = _visible_enabled(locator, 20)
    if len(visible) != 1:
        return False
    visible[0].click()
    page.wait_for_timeout(1500)
    return True


def _upload_or_reuse(page, workbook: Path, remote_name: str) -> str:
    decision = remote_file_decision(_folder_or_file_names(page), remote_name)
    if decision == "already_present":
        return decision

    if not _click_named(page, (r"^carregar$", r"^upload$", r"carregar.*", r"upload.*")):
        return "blocked"
    page.wait_for_timeout(500)
    _click_named(page, (r"^arquivos$", r"^files$"))
    page.wait_for_timeout(500)
    inputs = page.locator("input[type='file']")
    if inputs.count() < 1:
        return "blocked"
    inputs.last.set_input_files(str(workbook))
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if any(normalize_text(name) == normalize_text(remote_name) for name in _folder_or_file_names(page)):
            return "uploaded"
        page.wait_for_timeout(1000)
    return "blocked"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publica Excel FECAP em SharePoint, one-shot e fail-closed")
    parser.add_argument("--input", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--create-if-missing", action="store_true")
    parser.add_argument("--allow-human-login", action="store_true")
    parser.add_argument("--auth-timeout-seconds", type=int, default=MAX_HUMAN_LOGIN_TIMEOUT_SECONDS)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    try:
        timeout = effective_auth_timeout_seconds(ns.allow_human_login, ns.auth_timeout_seconds)
    except ValueError as exc:
        return _blocked(ns.evidence, "invalid_auth_timeout", error=str(exc))

    if ns.check:
        print(
            "mode=one_shot sharepoint=true scheduled=false production_enabled=false "
            f"create_if_missing={str(ns.create_if_missing).lower()} auth_timeout_seconds={timeout}"
        )
        return 0
    if not ns.once:
        return _blocked(ns.evidence, "one_shot_authorization_missing")
    if not ns.input.is_file():
        return _blocked(ns.evidence, "workbook_missing")

    workbook_payload = ns.input.read_bytes()
    workbook_digest = sha256(workbook_payload).hexdigest()
    remote_name = deterministic_filename(workbook_digest)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _blocked(ns.evidence, "playwright_missing")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, args=["--disable-sync"]
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(PORTAL_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if not _wait_for_auth(page, timeout):
                return _blocked(
                    ns.evidence,
                    "microsoft_authentication",
                    human_login_required=True,
                    human_login_flow_enabled=ns.allow_human_login,
                    login_like_url=_is_login_like(page),
                )

            _click_named(page, (r"ver todos os sites", r"see all sites", r"meus sites", r"my sites"))
            page.wait_for_timeout(1200)
            candidates = _collect_site_candidates(page)
            selected = choose_existing_site(candidates)
            existing_site_reused = selected is not None
            site_created = False

            if selected is None:
                if not ns.create_if_missing:
                    return _blocked(
                        ns.evidence,
                        "site_discovery",
                        candidate_count=len(candidates),
                        create_if_missing=False,
                    )
                selected = _create_communication_site(page)
                if selected is None:
                    return _blocked(
                        ns.evidence,
                        "site_creation",
                        candidate_count=len(candidates),
                        communication_site_required=True,
                    )
                site_created = True
            else:
                page.goto(selected.url, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)

            library = _library_candidate(page)
            if library is None:
                return _blocked(ns.evidence, "document_library_discovery", site_url=selected.url)
            _, library_name, library_url, library_locator = library
            if library_url:
                page.goto(library_url, wait_until="domcontentloaded")
            else:
                library_locator.click()
            page.wait_for_timeout(1500)

            if not _open_or_create_folder(page):
                return _blocked(
                    ns.evidence,
                    "folder_creation",
                    site_url=selected.url,
                    library=library_name,
                    folder=TARGET_FOLDER,
                )

            action = _upload_or_reuse(page, ns.input, remote_name)
            if action == "blocked":
                return _blocked(
                    ns.evidence,
                    "file_publication",
                    site_url=selected.url,
                    library=library_name,
                    folder=TARGET_FOLDER,
                    file_name=remote_name,
                )

            evidence = build_evidence(
                workbook_digest=workbook_digest,
                site_title=selected.title or TARGET_SITE_TITLE,
                site_url=selected.url,
                library_name=library_name or "Documents",
                folder_name=TARGET_FOLDER,
                file_name=remote_name,
                action=action,
                existing_site_reused=existing_site_reused,
                site_created=site_created,
            )
            evidence["profile_persisted"] = True
            evidence["human_login_required"] = False
            evidence["human_login_flow_enabled"] = ns.allow_human_login
            _write_json(ns.evidence, evidence)
            print(json.dumps(evidence, ensure_ascii=False, indent=2))
            return 0
        except SharePointHomologationError as exc:
            return _blocked(ns.evidence, "safety_gate", error_type=type(exc).__name__, error=str(exc))
        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
