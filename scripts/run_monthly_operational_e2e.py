from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_EVIDENCE = ROOT / "evidence" / "private" / "knewin-runtime-validation.json"
DEFAULT_COLLECTED = ROOT / "data" / "private" / "knewin-fecap-items.json"
DEFAULT_COLLECT_EVIDENCE = ROOT / "evidence" / "private" / "knewin-authenticated-collector-run.json"
DEFAULT_APPEND_EVIDENCE = ROOT / "evidence" / "private" / "monthly-operational-append.json"
DEFAULT_REPLAY_EVIDENCE = ROOT / "evidence" / "private" / "monthly-operational-replay.json"
DEFAULT_E2E_EVIDENCE = ROOT / "evidence" / "private" / "monthly-operational-e2e.json"


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON deve ser objeto: {path}")
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _run(name: str, command: list[str]) -> dict:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "name": name,
        "exit_code": completed.returncode,
        "ok": completed.returncode == 0,
    }


def _validate_window(start_date: str, end_date: str) -> None:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("end_date deve ser maior ou igual a start_date")


def _validate_append_evidence(payload: dict, *, require_positive: bool) -> tuple[int, int]:
    if payload.get("status") != "PASS":
        raise ValueError("append não retornou status PASS")
    appended = payload.get("appended_count")
    duplicates = payload.get("duplicate_count")
    if isinstance(appended, bool) or not isinstance(appended, int) or appended < 0:
        raise ValueError("appended_count inválido")
    if isinstance(duplicates, bool) or not isinstance(duplicates, int) or duplicates < 0:
        raise ValueError("duplicate_count inválido")
    if require_positive and appended < 1:
        raise ValueError("caso positivo não comprovado: nenhum item novo foi anexado")
    return appended, duplicates


def validate_replay(
    first_output: Path,
    replay_output: Path,
    first_evidence: dict,
    replay_evidence: dict,
) -> dict:
    first_appended, _ = _validate_append_evidence(first_evidence, require_positive=False)
    replay_appended, replay_duplicates = _validate_append_evidence(
        replay_evidence, require_positive=False
    )
    if replay_appended != 0:
        raise ValueError("replay anexou linhas novas")
    if replay_evidence.get("no_op") is not True:
        raise ValueError("replay não confirmou no_op")
    if replay_duplicates < first_appended:
        raise ValueError("replay não reconheceu como duplicados todos os itens anexados")
    first_bytes = first_output.read_bytes()
    replay_bytes = replay_output.read_bytes()
    if replay_bytes != first_bytes:
        raise ValueError("replay alterou os bytes do workbook")
    digest = sha256(first_bytes).hexdigest()
    if replay_evidence.get("input_sha256") != digest:
        raise ValueError("SHA de entrada do replay não corresponde ao workbook persistido")
    if replay_evidence.get("output_sha256") != digest:
        raise ValueError("SHA de saída do replay divergiu do workbook persistido")
    return {
        "replay_no_op": True,
        "replay_duplicate_count": replay_duplicates,
        "workbook_sha256": digest,
    }


def _blocked(path: Path, correlation_id: str, phase: str, stages: list[dict], **extra) -> int:
    payload = {
        "status": "BLOCKED",
        "contract": "fecap-monthly-operational-e2e/1.0.0",
        "correlation_id": correlation_id,
        "phase": phase,
        "stages": stages,
        "scheduled": False,
        "production_enabled": False,
    }
    payload.update(extra)
    _write_json(path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 50


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa o E2E mensal Knewin -> Clipping_2026 em cópia controlada e valida replay"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--term", default="Fecap")
    parser.add_argument("--start-date", required=False)
    parser.add_argument("--end-date", required=False)
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay-output", type=Path)
    parser.add_argument("--runtime-evidence", type=Path, default=DEFAULT_RUNTIME_EVIDENCE)
    parser.add_argument("--collector", type=Path, default=DEFAULT_COLLECTED)
    parser.add_argument("--collect-evidence", type=Path, default=DEFAULT_COLLECT_EVIDENCE)
    parser.add_argument("--append-evidence", type=Path, default=DEFAULT_APPEND_EVIDENCE)
    parser.add_argument("--replay-evidence", type=Path, default=DEFAULT_REPLAY_EVIDENCE)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_E2E_EVIDENCE)
    parser.add_argument("--skip-collect", action="store_true")
    parser.add_argument("--allow-human-login", action="store_true")
    parser.add_argument("--submit-saved-login", action="store_true")
    parser.add_argument("--auth-timeout-seconds", type=int, default=600)
    parser.add_argument("--allow-no-new-items", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    if ns.check:
        print(
            "contract=fecap-monthly-operational-e2e/1.0.0 mode=one_shot "
            "positive_case_required=true replay_required=true scheduled=false "
            "production_enabled=false"
        )
        return 0

    correlation_id = uuid4().hex
    stages: list[dict] = []

    if not ns.once:
        return _blocked(ns.evidence, correlation_id, "authorization", stages, reason="one_shot_required")
    if not ns.start_date or not ns.end_date:
        return _blocked(ns.evidence, correlation_id, "date_window", stages, reason="start_and_end_required")
    try:
        _validate_window(ns.start_date, ns.end_date)
    except ValueError as exc:
        return _blocked(ns.evidence, correlation_id, "date_window", stages, reason=str(exc))
    if ns.workbook is None or not ns.workbook.is_file():
        return _blocked(ns.evidence, correlation_id, "source_workbook", stages, reason="workbook_missing")
    if ns.output is None:
        return _blocked(ns.evidence, correlation_id, "output_workbook", stages, reason="output_required")

    replay_output = ns.replay_output or ns.output.with_name(
        ns.output.stem + ".replay" + ns.output.suffix
    )
    source_resolved = ns.workbook.resolve()
    output_resolved = ns.output.resolve()
    replay_resolved = replay_output.resolve()
    if len({source_resolved, output_resolved, replay_resolved}) != 3:
        return _blocked(
            ns.evidence,
            correlation_id,
            "path_safety",
            stages,
            reason="source_output_and_replay_must_be_distinct",
        )

    if ns.skip_collect:
        if not ns.collector.is_file():
            return _blocked(
                ns.evidence, correlation_id, "collector_input", stages, reason="collector_missing"
            )
    else:
        collect = [
            sys.executable,
            "scripts/collect_knewin_publications.py",
            "--once",
            "--term",
            ns.term,
            "--start-date",
            ns.start_date,
            "--end-date",
            ns.end_date,
            "--runtime-evidence",
            str(ns.runtime_evidence),
            "--output",
            str(ns.collector),
            "--evidence",
            str(ns.collect_evidence),
        ]
        if ns.allow_human_login:
            collect += [
                "--allow-human-login",
                "--auth-timeout-seconds",
                str(ns.auth_timeout_seconds),
            ]
        if ns.submit_saved_login:
            collect += ["--submit-saved-login"]
        collect_stage = _run("collect_month", collect)
        stages.append(collect_stage)
        if not collect_stage["ok"] or not ns.collector.is_file():
            return _blocked(
                ns.evidence,
                correlation_id,
                "collect_month",
                stages,
                live_knewin_validated=False,
            )

    source_sha = _sha256_file(ns.workbook)
    append_command = [
        sys.executable,
        "scripts/append_operational_workbook.py",
        "--once",
        "--workbook",
        str(ns.workbook),
        "--collector",
        str(ns.collector),
        "--output",
        str(ns.output),
        "--evidence",
        str(ns.append_evidence),
    ]
    append_stage = _run("append_operational_workbook", append_command)
    stages.append(append_stage)
    if not append_stage["ok"] or not ns.output.is_file():
        return _blocked(ns.evidence, correlation_id, "append_operational_workbook", stages)

    try:
        first_evidence = _read_json(ns.append_evidence)
        appended_count, duplicate_count = _validate_append_evidence(
            first_evidence, require_positive=not ns.allow_no_new_items
        )
        output_sha = _sha256_file(ns.output)
        if appended_count > 0 and output_sha == source_sha:
            raise ValueError("workbook não mudou apesar de appended_count positivo")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _blocked(
            ns.evidence,
            correlation_id,
            "append_validation",
            stages,
            reason=str(exc),
        )

    replay_command = [
        sys.executable,
        "scripts/append_operational_workbook.py",
        "--once",
        "--workbook",
        str(ns.output),
        "--collector",
        str(ns.collector),
        "--output",
        str(replay_output),
        "--evidence",
        str(ns.replay_evidence),
    ]
    replay_stage = _run("replay", replay_command)
    stages.append(replay_stage)
    if not replay_stage["ok"] or not replay_output.is_file():
        return _blocked(ns.evidence, correlation_id, "replay", stages)

    try:
        replay_evidence = _read_json(ns.replay_evidence)
        replay_result = validate_replay(
            ns.output, replay_output, first_evidence, replay_evidence
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _blocked(
            ns.evidence,
            correlation_id,
            "replay_validation",
            stages,
            reason=str(exc),
        )

    payload = {
        "status": "PASS",
        "contract": "fecap-monthly-operational-e2e/1.0.0",
        "correlation_id": correlation_id,
        "mode": "one_shot",
        "start_date": ns.start_date,
        "end_date": ns.end_date,
        "collector_skipped": bool(ns.skip_collect),
        "live_knewin_validated": not ns.skip_collect,
        "source_workbook_sha256": source_sha,
        "output_workbook_sha256": output_sha,
        "replay_workbook_sha256": replay_result["workbook_sha256"],
        "appended_count": appended_count,
        "initial_duplicate_count": duplicate_count,
        "replay_duplicate_count": replay_result["replay_duplicate_count"],
        "replay_no_op": replay_result["replay_no_op"],
        "stages": stages,
        "scheduled": False,
        "production_enabled": False,
    }
    _write_json(ns.evidence, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
