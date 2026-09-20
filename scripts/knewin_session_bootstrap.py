from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_DIR = Path.home() / ".fecap-clipping"
DEFAULT_PORTAL_URL = "https://news.knewin.com/#/login"
REQUIREMENTS = ROOT / "requirements-local.txt"
PROBE_SCRIPT = ROOT / "scripts" / "probe_knewin_session.py"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def venv_python_path(base_dir: Path, *, windows: bool | None = None) -> Path:
    is_windows = os.name == "nt" if windows is None else windows
    return base_dir / "venv" / ("Scripts/python.exe" if is_windows else "bin/python")


def pip_install_command(python: Path | str, *, offline: bool, wheelhouse: Path | None) -> list[str]:
    command = [str(python), "-m", "pip", "install"]
    if offline:
        if wheelhouse is None:
            raise ValueError("wheelhouse obrigatório em modo offline")
        command += ["--no-index", "--find-links", str(wheelhouse)]
    else:
        command += ["--disable-pip-version-check"]
    command += ["-r", str(REQUIREMENTS)]
    return command


def run(command: list[str], *, env: dict[str, str] | None = None) -> int:
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    return int(completed.returncode)


def append_event(log_path: Path, level: str, step: str, message: str, code: int | None = None) -> None:
    event: dict[str, object] = {
        "timestamp": utc_now(),
        "level": level,
        "step": step,
        "message": message,
    }
    if code is not None:
        event["code"] = code
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def command_ok(command: list[str]) -> bool:
    return run(command) == 0


def chromium_available(python: Path) -> bool:
    snippet = (
        "from pathlib import Path; "
        "from playwright.sync_api import sync_playwright; "
        "p=sync_playwright().start(); x=p.chromium.executable_path; p.stop(); "
        "raise SystemExit(0 if Path(x).is_file() else 1)"
    )
    return command_ok([str(python), "-c", snippet])


def write_evidence(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def blocked(evidence_path: Path, log_path: Path, phase: str, code: int, message: str) -> int:
    append_event(log_path, "ERROR", phase, message, code)
    write_evidence(
        evidence_path,
        {
            "status": "BLOCKED",
            "phase": phase,
            "code": code,
            "scheduled": False,
            "production_enabled": False,
            "credentials_persisted": False,
            "tokens_persisted": False,
            "secrets_captured": False,
        },
    )
    print(f"BOOTSTRAP_BLOCKED:{phase}:{code}", file=sys.stderr)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Knewin governável pelo Command Gateway")
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--portal-url", default=DEFAULT_PORTAL_URL)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--bootstrap-only", action="store_true")
    parser.add_argument("--check", action="store_true")
    ns = parser.parse_args()

    if ns.check:
        print(
            "mode=gateway_native bootstrap=true scheduled=false production_enabled=false "
            f"offline={str(ns.offline).lower()} bootstrap_only={str(ns.bootstrap_only).lower()}"
        )
        return 0

    base_dir = ns.base_dir.expanduser().resolve()
    evidence_dir = base_dir / "evidence"
    profile_dir = base_dir / "knewin-profile"
    log_path = evidence_dir / "knewin-gateway-bootstrap.jsonl"
    bootstrap_evidence = evidence_dir / "knewin-gateway-bootstrap.json"
    auth_evidence = evidence_dir / "knewin-auth-probe.json"

    evidence_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    append_event(log_path, "INFO", "bootstrap", "Início do bootstrap Python governado.")

    if sys.version_info < (3, 11):
        return blocked(bootstrap_evidence, log_path, "python", 11, "Python 3.11+ é obrigatório.")

    venv_dir = base_dir / "venv"
    venv_python = venv_python_path(base_dir)
    if not venv_python.is_file():
        append_event(log_path, "INFO", "venv", "Criando venv isolado.")
        code = run([sys.executable, "-m", "venv", str(venv_dir)])
        if code != 0 or not venv_python.is_file():
            return blocked(bootstrap_evidence, log_path, "venv", 20, "Falha ao criar venv isolado.")

    if not command_ok([str(venv_python), "-m", "pip", "--version"]):
        append_event(log_path, "WARN", "pip", "pip ausente; executando ensurepip.")
        if run([str(venv_python), "-m", "ensurepip", "--upgrade"]) != 0:
            return blocked(bootstrap_evidence, log_path, "pip", 23, "ensurepip falhou.")
        if not command_ok([str(venv_python), "-m", "pip", "--version"]):
            return blocked(bootstrap_evidence, log_path, "pip", 24, "pip continua indisponível.")

    playwright_installed = command_ok([str(venv_python), "-c", "import playwright"])
    if not playwright_installed:
        if ns.skip_install:
            return blocked(bootstrap_evidence, log_path, "playwright", 30, "Playwright ausente e --skip-install ativo.")
        if ns.offline:
            wheelhouse = ns.wheelhouse or (ROOT / "dist" / "wheelhouse")
            if not wheelhouse.is_dir():
                return blocked(bootstrap_evidence, log_path, "playwright", 31, "Wheelhouse local não encontrado.")
        else:
            wheelhouse = None
        append_event(log_path, "INFO", "playwright", "Instalando requirements-local.txt.")
        if run(pip_install_command(venv_python, offline=ns.offline, wheelhouse=wheelhouse)) != 0:
            return blocked(bootstrap_evidence, log_path, "playwright", 32, "Falha ao instalar dependências.")
        playwright_installed = command_ok([str(venv_python), "-c", "import playwright"])
        if not playwright_installed:
            return blocked(bootstrap_evidence, log_path, "playwright", 33, "Playwright não importável após instalação.")

    has_chromium = chromium_available(venv_python)
    if not has_chromium:
        if ns.offline:
            return blocked(bootstrap_evidence, log_path, "chromium", 40, "Chromium ausente em modo offline.")
        if ns.skip_install:
            return blocked(bootstrap_evidence, log_path, "chromium", 41, "Chromium ausente e --skip-install ativo.")
        append_event(log_path, "INFO", "chromium", "Instalando Chromium do Playwright.")
        if run([str(venv_python), "-m", "playwright", "install", "chromium"]) != 0:
            return blocked(bootstrap_evidence, log_path, "chromium", 42, "Falha ao instalar Chromium.")
        has_chromium = chromium_available(venv_python)
        if not has_chromium:
            return blocked(bootstrap_evidence, log_path, "chromium", 43, "Chromium não localizado após instalação.")

    evidence = {
        "status": "PASS",
        "phase": "bootstrap",
        "bootstrap_only": bool(ns.bootstrap_only),
        "python_supported": True,
        "playwright_installed": playwright_installed,
        "chromium_available": has_chromium,
        "scheduled": False,
        "production_enabled": False,
        "credentials_persisted": False,
        "tokens_persisted": False,
        "secrets_captured": False,
    }
    write_evidence(bootstrap_evidence, evidence)
    append_event(log_path, "INFO", "bootstrap", "Bootstrap Python governado concluído.")

    if ns.bootstrap_only:
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
        return 0

    if not PROBE_SCRIPT.is_file():
        return blocked(bootstrap_evidence, log_path, "probe", 50, "Sonda Knewin não encontrada.")

    env = os.environ.copy()
    env["KNEWIN_PORTAL_URL"] = ns.portal_url
    env["KNEWIN_PROFILE_DIR"] = str(profile_dir)
    env["KNEWIN_AUTH_EVIDENCE"] = str(auth_evidence)
    append_event(log_path, "INFO", "probe", "Executando sonda Knewin; credenciais não são persistidas.")
    code = run([str(venv_python), str(PROBE_SCRIPT)], env=env)
    if code != 0:
        append_event(log_path, "WARN", "probe", "Sonda encerrou sem PASS.", code)
        return code
    append_event(log_path, "INFO", "complete", "Bootstrap e sonda concluídos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
