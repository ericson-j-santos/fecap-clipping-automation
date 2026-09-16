from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_EVIDENCE = ROOT / "evidence" / "private" / "knewin-runtime-validation.json"
DEFAULT_COLLECTED = ROOT / "data" / "private" / "knewin-fecap-items.json"
DEFAULT_COLLECT_EVIDENCE = ROOT / "evidence" / "private" / "knewin-authenticated-collector-run.json"
DEFAULT_WORKBOOK = ROOT / "data" / "private" / "fecap-clipping-homologacao.xlsx"
DEFAULT_EXCEL_EVIDENCE = ROOT / "evidence" / "private" / "knewin-excel-homologation.json"
DEFAULT_ONEDRIVE_EVIDENCE = ROOT / "evidence" / "private" / "onedrive-homologation-run.json"
DEFAULT_PIPELINE_EVIDENCE = ROOT / "evidence" / "private" / "homologation-pipeline-run.json"


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON deve ser objeto: {path}")
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(name: str, command: list[str]) -> dict:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "name": name,
        "exit_code": completed.returncode,
        "ok": completed.returncode == 0,
    }


def validate_idempotency(first: dict, second: dict) -> None:
    if first.get("status") != "PASS" or second.get("status") != "PASS":
        raise ValueError("publicação OneDrive não passou nas duas execuções")
    if second.get("action") != "already_present":
        raise ValueError("segunda publicação não confirmou already_present")
    first_sha = first.get("workbook_sha256")
    second_sha = second.get("workbook_sha256")
    if not first_sha or first_sha != second_sha:
        raise ValueError("SHA-256 do workbook divergiu entre as duas publicações")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa Knewin -> Excel -> OneDrive de homologação em modo one-shot e fail-closed"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--term", default="Fecap")
    parser.add_argument("--destination-root", type=Path)
    parser.add_argument("--skip-collect", action="store_true")
    parser.add_argument("--allow-human-login", action="store_true")
    parser.add_argument("--auth-timeout-seconds", type=int, default=600)
    parser.add_argument("--verify-idempotency", action="store_true")
    parser.add_argument("--runtime-evidence", type=Path, default=DEFAULT_RUNTIME_EVIDENCE)
    parser.add_argument("--collected", type=Path, default=DEFAULT_COLLECTED)
    parser.add_argument("--collect-evidence", type=Path, default=DEFAULT_COLLECT_EVIDENCE)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--excel-evidence", type=Path, default=DEFAULT_EXCEL_EVIDENCE)
    parser.add_argument("--onedrive-evidence", type=Path, default=DEFAULT_ONEDRIVE_EVIDENCE)
    parser.add_argument("--pipeline-evidence", type=Path, default=DEFAULT_PIPELINE_EVIDENCE)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    if ns.check:
        print(
            "mode=one_shot pipeline=knewin>excel>onedrive fail_closed=true "
            "scheduled=false production_enabled=false sharepoint_in_critical_path=false"
        )
        return 0
    if not ns.once:
        print("status=BLOCKED reason=one_shot_authorization_missing")
        return 50
    if ns.destination_root is None:
        print("status=BLOCKED reason=destination_root_missing")
        return 50
    if ns.skip_collect and not ns.collected.is_file():
        print("status=BLOCKED reason=collected_input_missing")
        return 50

    stages: list[dict] = []
    if not ns.skip_collect:
        collect = [
            sys.executable,
            "scripts/collect_knewin_publications.py",
            "--once",
            "--term",
            ns.term,
            "--runtime-evidence",
            str(ns.runtime_evidence),
            "--output",
            str(ns.collected),
            "--evidence",
            str(ns.collect_evidence),
        ]
        if ns.allow_human_login:
            collect += ["--allow-human-login", "--auth-timeout-seconds", str(ns.auth_timeout_seconds)]
        result = _run("collect", collect)
        stages.append(result)
        if not result["ok"]:
            _write_json(ns.pipeline_evidence, {"status": "BLOCKED", "failed_stage": "collect", "stages": stages, "scheduled": False, "production_enabled": False})
            return 50

    build = _run(
        "build_excel",
        [
            sys.executable,
            "scripts/build_homologation_excel.py",
            "--input",
            str(ns.collected),
            "--output",
            str(ns.workbook),
            "--evidence",
            str(ns.excel_evidence),
        ],
    )
    stages.append(build)
    if not build["ok"]:
        _write_json(ns.pipeline_evidence, {"status": "BLOCKED", "failed_stage": "build_excel", "stages": stages, "scheduled": False, "production_enabled": False})
        return 50

    publish_command = [
        sys.executable,
        "scripts/publish_onedrive_homologation.py",
        "--once",
        "--input",
        str(ns.workbook),
        "--destination-root",
        str(ns.destination_root),
        "--evidence",
        str(ns.onedrive_evidence),
    ]
    first = _run("publish_onedrive", publish_command)
    stages.append(first)
    if not first["ok"]:
        _write_json(ns.pipeline_evidence, {"status": "BLOCKED", "failed_stage": "publish_onedrive", "stages": stages, "scheduled": False, "production_enabled": False})
        return 50

    first_evidence = _read_json(ns.onedrive_evidence)
    second_evidence = None
    if ns.verify_idempotency:
        second_path = ns.onedrive_evidence.with_name(ns.onedrive_evidence.stem + "-repeat.json")
        repeat_command = publish_command[:-1] + [str(second_path)]
        second = _run("verify_idempotency", repeat_command)
        stages.append(second)
        if not second["ok"]:
            _write_json(ns.pipeline_evidence, {"status": "BLOCKED", "failed_stage": "verify_idempotency", "stages": stages, "scheduled": False, "production_enabled": False})
            return 50
        second_evidence = _read_json(second_path)
        try:
            validate_idempotency(first_evidence, second_evidence)
        except ValueError as exc:
            _write_json(ns.pipeline_evidence, {"status": "BLOCKED", "failed_stage": "verify_idempotency", "reason": str(exc), "stages": stages, "scheduled": False, "production_enabled": False})
            return 50

    excel = _read_json(ns.excel_evidence)
    payload = {
        "status": "PASS",
        "mode": "one_shot",
        "strategy": "pareto_onedrive_first",
        "sharepoint_in_critical_path": False,
        "scheduled": False,
        "production_enabled": False,
        "stages": stages,
        "collector_skipped": bool(ns.skip_collect),
        "workbook_sha256": first_evidence.get("workbook_sha256"),
        "first_publish_action": first_evidence.get("action"),
        "second_publish_action": second_evidence.get("action") if second_evidence else None,
        "include_count": excel.get("include_count"),
        "review_count": excel.get("review_count"),
        "exclude_count": excel.get("exclude_count"),
    }
    _write_json(ns.pipeline_evidence, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
