"""One-shot, fail-closed handoff of an approved private SharePoint workbook.

No corporate workbook, access token, preauthenticated URL or collector output is
written to the repository, GitHub artifacts or runner logs.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import hmac
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.excel_homologation import MONTHS
from src.operational_workbook import (
    MAIN_NS, _find_header_row, _shared_strings, _workbook_sheets,
)

REPOSITORY = "ericson-j-santos/fecap-clipping-automation"
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
HEX_SHA = re.compile(r"^[0-9a-f]{64}$")
GRAPH_ID = re.compile(r"^[A-Za-z0-9._!:-]{1,200}$")
RUN_ID = re.compile(r"^[1-9][0-9]{0,18}$")


class WorkbookGateError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _required(env: dict[str, str], name: str) -> str:
    value = str(env.get(name) or "").strip()
    if not value:
        raise WorkbookGateError(name.lower() + "_missing")
    return value


def _runtime_gate(env: dict[str, str], *, require_secrets: bool = True) -> tuple[Path, str]:
    if (env.get("GITHUB_ACTIONS") != "true"
            or env.get("GITHUB_REPOSITORY") != REPOSITORY
            or env.get("GITHUB_REF") != "refs/heads/main"
            or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise WorkbookGateError("unapproved_workflow_context")
    if not re.fullmatch(r"[0-9a-f]{40}", _required(env, "GITHUB_SHA")):
        raise WorkbookGateError("github_sha_invalid")
    run = _required(env, "GITHUB_RUN_ID")
    attempt = _required(env, "GITHUB_RUN_ATTEMPT")
    if not RUN_ID.fullmatch(run) or not RUN_ID.fullmatch(attempt):
        raise WorkbookGateError("run_identity_invalid")
    root = Path(_required(env, "RUNNER_TEMP"))
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise WorkbookGateError("runner_temp_invalid")
    root = root.resolve(strict=True)
    if root == ROOT or ROOT in root.parents:
        raise WorkbookGateError("runner_temp_inside_repository")
    approved = _required(env, "KNEWIN_APPROVED_WORKBOOK_SHA256").lower() if require_secrets else ""
    if require_secrets:
        if not HEX_SHA.fullmatch(approved):
            raise WorkbookGateError("workbook_approval_digest_invalid")
        _required(env, "KNEWIN_API_KEY")
        for name in (
            "KNEWIN_GRAPH_TENANT_ID", "KNEWIN_GRAPH_CLIENT_ID",
            "KNEWIN_GRAPH_CLIENT_SECRET", "KNEWIN_GRAPH_DRIVE_ID",
            "KNEWIN_GRAPH_ITEM_ID", "KNEWIN_GRAPH_DOWNLOAD_HOST",
        ):
            _required(env, name)
        for name in (
            "KNEWIN_GRAPH_TENANT_ID", "KNEWIN_GRAPH_CLIENT_ID",
            "KNEWIN_GRAPH_DRIVE_ID", "KNEWIN_GRAPH_ITEM_ID",
        ):
            if not GRAPH_ID.fullmatch(env[name].strip()):
                raise WorkbookGateError("graph_identifier_invalid")
        host = env["KNEWIN_GRAPH_DOWNLOAD_HOST"].strip().lower()
        if (not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,250}", host)
                or not host.endswith(".sharepoint.com")
                or ".." in host):
            raise WorkbookGateError("download_host_invalid")
    return root / ("fecap-knewin-" + run + "-" + attempt), approved


def runtime_paths(env: dict[str, str], *, require_secrets: bool = True) -> dict[str, Path]:
    root, _ = _runtime_gate(env, require_secrets=require_secrets)
    return {
        "root": root,
        "workbook": root / "Clipping_2026.aprovado.xlsx",
        "output": root / "Clipping_2026.validado.xlsx",
        "replay": root / "Clipping_2026.replay.xlsx",
        "collector": root / "knewin-collector.json",
        "evidence": root / "knewin-e2e-summary.json",
    }


def workbook_row_counts(payload: bytes) -> dict[str, int]:
    """Read monthly rows independently; reject incomplete or wrong 9-column books."""
    if len(payload) > MAX_DOWNLOAD_BYTES:
        raise WorkbookGateError("workbook_too_large")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if (len(infos) > 10000
                    or sum(item.file_size for item in infos) > MAX_UNCOMPRESSED_BYTES):
                raise WorkbookGateError("workbook_archive_limits")
            names = set(archive.namelist())
            required = {"xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
            if not required.issubset(names):
                raise WorkbookGateError("workbook_ooxml_incomplete")
            files = {name: archive.read(name) for name in required}
            if "xl/sharedStrings.xml" in names:
                files["xl/sharedStrings.xml"] = archive.read("xl/sharedStrings.xml")
            sheets = _workbook_sheets(files)
            if any(month not in sheets for month in MONTHS):
                raise WorkbookGateError("workbook_month_sheets_missing")
            shared = _shared_strings(files)
            counts = {}
            for month in MONTHS:
                sheet_path = sheets[month]
                if (not sheet_path.startswith("xl/worksheets/")
                        or sheet_path not in names
                        or ".." in Path(sheet_path).parts):
                    raise WorkbookGateError("workbook_sheet_path_invalid")
                xml = ET.fromstring(archive.read(sheet_path))
                header_row, _ = _find_header_row(xml, shared)
                sheet_data = xml.find(f"{{{MAIN_NS}}}sheetData")
                if sheet_data is None:
                    raise WorkbookGateError("workbook_sheet_data_missing")
                counts[month] = sum(
                    int(row.get("r", "0")) > header_row
                    for row in sheet_data.findall(f"{{{MAIN_NS}}}row")
                )
            return counts
    except WorkbookGateError:
        raise
    except (ValueError, KeyError, OSError, RuntimeError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise WorkbookGateError("workbook_contract_invalid") from exc


def _verify_approved_bytes(payload: bytes, approved_sha: str) -> None:
    if not HEX_SHA.fullmatch(approved_sha):
        raise WorkbookGateError("workbook_approval_digest_invalid")
    if not hmac.compare_digest(sha256(payload).hexdigest(), approved_sha):
        raise WorkbookGateError("workbook_digest_mismatch")
    workbook_row_counts(payload)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener():
    return build_opener(_NoRedirect)


def _token(env: dict[str, str]) -> str:
    tenant = env["KNEWIN_GRAPH_TENANT_ID"].strip()
    url = "https://login.microsoftonline.com/" + quote(tenant, safe="") + "/oauth2/v2.0/token"
    data = urlencode({
        "client_id": env["KNEWIN_GRAPH_CLIENT_ID"].strip(),
        "client_secret": env["KNEWIN_GRAPH_CLIENT_SECRET"],
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode("utf-8")
    req = Request(url, data=data, method="POST",
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with _opener().open(req, timeout=25) as response:
            obj = json.loads(response.read(131073))
        token = obj.get("access_token") if isinstance(obj, dict) else None
        if not isinstance(token, str) or not 20 <= len(token) <= 16384:
            raise WorkbookGateError("graph_access_token_invalid")
        return token
    except WorkbookGateError:
        raise
    except (HTTPError, URLError, ValueError, OSError) as exc:
        raise WorkbookGateError("graph_authentication_failed") from exc


def _approved_download_url(url: str, host: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != host
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment):
        raise WorkbookGateError("download_origin_rejected")


def _graph_download(env: dict[str, str]) -> bytes:
    token = _token(env)
    drive = quote(env["KNEWIN_GRAPH_DRIVE_ID"].strip(), safe="")
    item = quote(env["KNEWIN_GRAPH_ITEM_ID"].strip(), safe="")
    req = Request(
        "https://graph.microsoft.com/v1.0/drives/" + drive + "/items/" + item + "/content",
        headers={"Authorization": "Bearer " + token},
    )
    # Graph responds with a short-lived preauthenticated SharePoint URL.
    # No Authorization header is ever forwarded to the download origin.
    try:
        try:
            with _opener().open(req, timeout=30):
                raise WorkbookGateError("graph_download_redirect_missing")
        except HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise WorkbookGateError("graph_workbook_unavailable") from exc
            location = exc.headers.get("Location") or ""
        _approved_download_url(location, env["KNEWIN_GRAPH_DOWNLOAD_HOST"].strip().lower())
        with _opener().open(Request(location, method="GET"), timeout=60) as response:
            if response.status != 200:
                raise WorkbookGateError("graph_workbook_unavailable")
            payload = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(payload) > MAX_DOWNLOAD_BYTES:
                raise WorkbookGateError("workbook_too_large")
            return payload
    except WorkbookGateError:
        raise
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise WorkbookGateError("graph_workbook_unavailable") from exc


def prepare_workbook(env: dict[str, str], *, downloader=None) -> dict[str, Path]:
    """Only the real CLI uses _graph_download. Tests inject synthetic bytes."""
    paths = runtime_paths(env)
    approved = _runtime_gate(env)[1]
    envfile = Path(_required(env, "GITHUB_ENV"))
    if not envfile.is_absolute() or not envfile.is_file():
        raise WorkbookGateError("github_env_unavailable")
    payload = _graph_download(env) if downloader is None else downloader(env)
    _verify_approved_bytes(payload, approved)
    root = paths["root"]
    if root.exists() or root.is_symlink():
        raise WorkbookGateError("runtime_directory_exists")
    root.mkdir(mode=0o700)
    try:
        with paths["workbook"].open("xb") as handle:
            os.chmod(paths["workbook"], 0o600)
            handle.write(payload)
        if sha256(paths["workbook"].read_bytes()).hexdigest() != approved:
            raise WorkbookGateError("workbook_persisted_digest_mismatch")
        assignments = {
            "KNEWIN_WORKBOOK_PATH": paths["workbook"],
            "KNEWIN_OUTPUT_WORKBOOK_PATH": paths["output"],
            "KNEWIN_REPLAY_WORKBOOK_PATH": paths["replay"],
            "KNEWIN_COLLECTOR_PATH": paths["collector"],
            "KNEWIN_EVIDENCE_PATH": paths["evidence"],
        }
        with envfile.open("a", encoding="utf-8") as handle:
            for key, path in assignments.items():
                handle.write(f"{key}={path}\n")
        return paths
    except Exception:
        shutil.rmtree(root)
        raise


def verify_roundtrip(env: dict[str, str]) -> None:
    paths = runtime_paths(env)
    approved = _runtime_gate(env)[1]
    expected_env = {
        "KNEWIN_WORKBOOK_PATH": "workbook",
        "KNEWIN_OUTPUT_WORKBOOK_PATH": "output",
        "KNEWIN_REPLAY_WORKBOOK_PATH": "replay",
        "KNEWIN_EVIDENCE_PATH": "evidence",
    }
    for name, key in expected_env.items():
        if env.get(name) != str(paths[key]):
            raise WorkbookGateError("runtime_path_mismatch")
    if any(not paths[name].is_file() or paths[name].is_symlink()
           for name in ("workbook", "output", "replay", "evidence")):
        raise WorkbookGateError("runtime_file_missing")
    before = paths["workbook"].read_bytes()
    output = paths["output"].read_bytes()
    replay = paths["replay"].read_bytes()
    _verify_approved_bytes(before, approved)
    if not hmac.compare_digest(sha256(output).digest(), sha256(replay).digest()):
        raise WorkbookGateError("replay_digest_mismatch")
    if output != replay:
        raise WorkbookGateError("replay_bytes_changed")
    initial = workbook_row_counts(before)
    final = workbook_row_counts(output)
    appended = sum(final.values()) - sum(initial.values())
    if appended < 1:
        raise WorkbookGateError("positive_append_missing")
    try:
        summary = json.loads(paths["evidence"].read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise WorkbookGateError("evidence_invalid") from exc
    expected_correlation = "knewin-gha-" + env["GITHUB_RUN_ID"] + "-" + env["GITHUB_RUN_ATTEMPT"]
    if (not isinstance(summary, dict)
            or summary.get("status") != "PASS"
            or summary.get("live_knewin_validated") is not True
            or summary.get("workbook_roundtrip_validated") is not True
            or summary.get("production_enabled") is not False
            or summary.get("scheduled") is not False
            or summary.get("git_sha") != env["GITHUB_SHA"]
            or summary.get("correlation_id") != expected_correlation
            or summary.get("appended_count") != appended
            or summary.get("replay_no_op") is not True
            or not isinstance(summary.get("collected_fecap"), int)
            or isinstance(summary.get("collected_fecap"), bool)
            or summary["collected_fecap"] < 1
            or summary.get("source_workbook_sha256") != sha256(before).hexdigest()
            or summary.get("output_workbook_sha256") != sha256(output).hexdigest()
            or summary.get("replay_workbook_sha256") != sha256(replay).hexdigest()):
        raise WorkbookGateError("evidence_readback_mismatch")


def cleanup(env: dict[str, str]) -> None:
    paths = runtime_paths(env, require_secrets=False)
    root = paths["root"]
    if root.is_symlink():
        raise WorkbookGateError("runtime_directory_symlink")
    if root.exists():
        if not root.is_dir():
            raise WorkbookGateError("runtime_directory_invalid")
        shutil.rmtree(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "verify", "cleanup"))
    action = parser.parse_args().action
    try:
        if action == "prepare":
            prepare_workbook(dict(os.environ))
            print("KNEWIN_WORKBOOK_GATE=PASS;approved_digest=true;schema=true")
        elif action == "verify":
            verify_roundtrip(dict(os.environ))
            print("KNEWIN_LIVE_E2E_READBACK=PASS;append_positive=true;replay_identical=true")
        else:
            cleanup(dict(os.environ))
            print("KNEWIN_RUNTIME_CLEANUP=PASS")
        return 0
    except WorkbookGateError as exc:
        print("E2E_BLOCKED:" + exc.code, file=sys.stderr)
        return 20
    except Exception:
        # No traceback: network exceptions and URLs may contain preauthorized data.
        print("E2E_BLOCKED:runtime_failure", file=sys.stderr)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
