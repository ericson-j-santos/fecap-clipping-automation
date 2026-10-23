"""Synthetic regression only; no test here performs authenticated Knewin collection."""
from __future__ import annotations
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import e2e_live_knewin as live
from scripts.knewin_live_workbook import (
    WorkbookGateError, _approved_download_url, _verify_approved_bytes, cleanup,
    prepare_workbook, runtime_paths, verify_roundtrip, workbook_row_counts,
)
from src.excel_homologation import build_workbook_bytes
from src.operational_workbook import append_month_rows


def workbook_fixture() -> bytes:
    collector = {
        "format": 1, "mode": "one_shot", "credentials_persisted": False,
        "raw_response_persisted": False, "production_enabled": False,
        "items": [{
            "external_id": "fixture-base",
            "title": "FECAP: Rosely Schwartz comenta a economia",
            "url": "https://example.invalid/base",
            "source": "DIRECIONAL CONDOMÍNIOS",
            "published_at": "2026-08-10T00:00:00",
            "text": "A professora Rosely Schwartz, da FECAP, comenta o tema.",
        }],
    }
    rules = json.loads((ROOT / "config" / "video_enrichment.json").read_text("utf-8"))
    workbook, _ = build_workbook_bytes(
        collector, {"Rosely Schwartz": "Extensão"}, {}, enrichment_rules=rules
    )
    return workbook


def env_fixture(temp: Path, payload: bytes) -> dict[str, str]:
    (temp / "github-env").write_text("", encoding="utf-8")
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "ericson-j-santos/fecap-clipping-automation",
        "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "49201",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_ENV": str(temp / "github-env"), "RUNNER_TEMP": str(temp),
        "KNEWIN_API_KEY": "synthetic-key",
        "KNEWIN_GRAPH_TENANT_ID": "synthetic-tenant",
        "KNEWIN_GRAPH_CLIENT_ID": "synthetic-client",
        "KNEWIN_GRAPH_CLIENT_SECRET": "synthetic-secret",
        "KNEWIN_GRAPH_DRIVE_ID": "synthetic-drive",
        "KNEWIN_GRAPH_ITEM_ID": "synthetic-item",
        "KNEWIN_GRAPH_DOWNLOAD_HOST": "example.sharepoint.com",
        "KNEWIN_APPROVED_WORKBOOK_SHA256": sha256(payload).hexdigest(),
        "CORRELATION_ID": "knewin-gha-49201-1",
    }


def blocked(fn, reason: str) -> None:
    try:
        fn()
    except WorkbookGateError as exc:
        assert exc.code == reason, (exc.code, reason)
    else:
        raise AssertionError("fail-closed gate did not block: " + reason)


def synthetic_readback(paths: dict[str, Path], env: dict[str, str]) -> None:
    source = paths["workbook"].read_bytes()
    row = [
        "31/08/2026", "Mercado Comum", 2, "Online", "Proativo",
        "FECAP: Ahmed El Khatib comenta a economia", "Ahmed El Khatib",
        "Graduação", "https://example.invalid/new",
    ]
    first = append_month_rows(source, {"Agosto": [row]})
    assert first.evidence["appended_count"] == 1
    replay = append_month_rows(first.workbook, {"Agosto": [row]})
    assert replay.evidence["appended_count"] == 0
    assert replay.workbook == first.workbook
    paths["output"].write_bytes(first.workbook)
    paths["replay"].write_bytes(replay.workbook)
    summary = {
        "status": "PASS", "live_knewin_validated": True,
        "workbook_roundtrip_validated": True, "production_enabled": False,
        "scheduled": False, "git_sha": env["GITHUB_SHA"],
        "correlation_id": env["CORRELATION_ID"], "appended_count": 1,
        "collected_fecap": 1, "replay_no_op": True,
        "source_workbook_sha256": sha256(source).hexdigest(),
        "output_workbook_sha256": sha256(first.workbook).hexdigest(),
        "replay_workbook_sha256": sha256(replay.workbook).hexdigest(),
    }
    paths["evidence"].write_text(json.dumps(summary), encoding="utf-8")


def test_workflow() -> None:
    workflow = (ROOT / ".github/workflows/knewin-live-e2e.yml").read_text("utf-8")
    assert "workflow_dispatch:" in workflow
    assert "\n  push:" not in workflow and "\n  pull_request:" not in workflow
    assert "environment: knewin-live-e2e" in workflow
    assert "KNEWIN_API_KEY: $" + "{{ secrets.KNEWIN_API_KEY }}" in workflow
    assert "KNEWIN_APPROVED_WORKBOOK_SHA256: $" + "{{ secrets.KNEWIN_APPROVED_WORKBOOK_SHA256 }}" in workflow
    assert "knewin_live_workbook.py prepare" in workflow
    assert "knewin_live_workbook.py verify" in workflow
    assert "knewin_live_workbook.py cleanup" in workflow
    assert workflow.index("knewin_live_workbook.py prepare") < workflow.index("e2e_live_knewin.py")
    assert workflow.index("e2e_live_knewin.py") < workflow.index("knewin_live_workbook.py verify")
    assert "upload-artifact" not in workflow


def test_digest_schema_origin() -> None:
    original = workbook_fixture()
    assert len(workbook_row_counts(original)) == 12
    _verify_approved_bytes(original, sha256(original).hexdigest())
    blocked(lambda: _verify_approved_bytes(original, "0" * 64), "workbook_digest_mismatch")
    blocked(lambda: _verify_approved_bytes(original, "invalid"), "workbook_approval_digest_invalid")
    blocked(lambda: workbook_row_counts(b"not xlsx"), "workbook_contract_invalid")
    dst = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original), "r") as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "xl/worksheets/sheet8.xml":
                data = data.replace(b"ORIGEM", b"ORIGEM_INVALID", 1)
            zout.writestr(info, data)
    blocked(lambda: workbook_row_counts(dst.getvalue()), "workbook_contract_invalid")
    _approved_download_url("https://example.sharepoint.com/dl?token=dummy", "example.sharepoint.com")
    for url in (
        "http://example.sharepoint.com/a", "https://evil.test/a",
        "https://example.sharepoint.com.evil.test/a",
        "https://example.sharepoint.com:444/a",
        "https://u:p@example.sharepoint.com/a",
    ):
        blocked(lambda url=url: _approved_download_url(url, "example.sharepoint.com"),
                "download_origin_rejected")


def test_preflight_and_readback() -> None:
    base = workbook_fixture()
    with tempfile.TemporaryDirectory() as tmp:
        temp = Path(tmp)
        env = env_fixture(temp, base)
        for key, reason in (
            ("KNEWIN_API_KEY", "knewin_api_key_missing"),
            ("KNEWIN_GRAPH_CLIENT_SECRET", "knewin_graph_client_secret_missing"),
            ("KNEWIN_APPROVED_WORKBOOK_SHA256", "knewin_approved_workbook_sha256_missing"),
        ):
            broken = {**env, key: ""}
            blocked(lambda broken=broken: prepare_workbook(broken, downloader=lambda _: base), reason)
        for key, value in (
            ("GITHUB_REF", "refs/heads/feature"),
            ("GITHUB_EVENT_NAME", "pull_request"),
            ("GITHUB_REPOSITORY", "untrusted/repo"),
        ):
            broken = {**env, key: value}
            blocked(lambda broken=broken: prepare_workbook(broken, downloader=lambda _: base),
                    "unapproved_workflow_context")
        broken = {**env, "KNEWIN_APPROVED_WORKBOOK_SHA256": "0" * 64}
        blocked(lambda: prepare_workbook(broken, downloader=lambda _: base), "workbook_digest_mismatch")
        assert not runtime_paths(env)["root"].exists()
        paths = prepare_workbook(env, downloader=lambda _: base)
        assert paths["workbook"].read_bytes() == base
        exported = (temp / "github-env").read_text("utf-8")
        for name, key in (
            ("KNEWIN_WORKBOOK_PATH", "workbook"), ("KNEWIN_OUTPUT_WORKBOOK_PATH", "output"),
            ("KNEWIN_REPLAY_WORKBOOK_PATH", "replay"), ("KNEWIN_EVIDENCE_PATH", "evidence"),
        ):
            assert f"{name}={paths[key]}\n" in exported
            env[name] = str(paths[key])
        blocked(lambda: prepare_workbook(env, downloader=lambda _: base), "runtime_directory_exists")
        synthetic_readback(paths, env)
        verify_roundtrip(env)  # validates fixtures, NOT live Knewin
        paths["replay"].write_bytes(b"tampered")
        blocked(lambda: verify_roundtrip(env), "replay_digest_mismatch")
        paths["replay"].write_bytes(paths["output"].read_bytes())
        summary = json.loads(paths["evidence"].read_text("utf-8"))
        summary["live_knewin_validated"] = False
        paths["evidence"].write_text(json.dumps(summary), encoding="utf-8")
        blocked(lambda: verify_roundtrip(env), "evidence_readback_mismatch")
        synthetic_readback(paths, env)
        paths["output"].write_bytes(base)
        paths["replay"].write_bytes(base)
        blocked(lambda: verify_roundtrip(env), "positive_append_missing")
        paths["workbook"].unlink()
        blocked(lambda: verify_roundtrip(env), "runtime_file_missing")
        cleanup(env)
        cleanup(env)
        assert not paths["root"].exists()


def test_executor_preflight_avoids_knewin_request() -> None:
    base = workbook_fixture()
    with tempfile.TemporaryDirectory() as tmp:
        temp = Path(tmp)
        env = env_fixture(temp, base)
        env.update({
            "KNEWIN_EVIDENCE_PATH": str(temp / "blocked.json"),
            "KNEWIN_OUTPUT_WORKBOOK_PATH": str(temp / "out.xlsx"),
            "KNEWIN_REPLAY_WORKBOOK_PATH": str(temp / "replay.xlsx"),
            "KNEWIN_COLLECTOR_PATH": str(temp / "collector.json"),
        })
        for overrides, reason in (
            ({"KNEWIN_API_KEY": ""}, "knewin_api_key_missing"),
            ({"KNEWIN_WORKBOOK_PATH": ""}, "workbook_path_missing"),
            ({"KNEWIN_WORKBOOK_PATH": str(temp / "missing.xlsx")}, "workbook_missing"),
        ):
            with patch.dict(os.environ, {**env, **overrides}, clear=True):
                with patch.object(live, "collect_fecap",
                                  side_effect=AssertionError("unexpected external call")):
                    assert live.main() == 20
            summary = json.loads((temp / "blocked.json").read_text("utf-8"))
            assert summary["reason"] == reason
        paths = prepare_workbook(env, downloader=lambda _: base)
        env["KNEWIN_WORKBOOK_PATH"] = str(paths["workbook"])
        env["KNEWIN_APPROVED_WORKBOOK_SHA256"] = "0" * 64
        with patch.dict(os.environ, env, clear=True):
            with patch.object(live, "collect_fecap",
                              side_effect=AssertionError("unexpected external call")):
                assert live.main() == 20
        assert json.loads((temp / "blocked.json").read_text("utf-8"))["reason"] == "workbook_digest_mismatch"
        env["KNEWIN_APPROVED_WORKBOOK_SHA256"] = sha256(base).hexdigest()
        cleanup(env)


def main() -> int:
    test_workflow()
    test_digest_schema_origin()
    test_preflight_and_readback()
    test_executor_preflight_avoids_knewin_request()
    print("test_knewin_live_workbook: OK (synthetic only; live Knewin NOT validated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
