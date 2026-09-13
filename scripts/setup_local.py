from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command_plan(python: str, skip_browser: bool = False) -> list[list[str]]:
    commands = [
        [python, "-m", "pip", "install", "-r", str(ROOT / "requirements-local.txt")],
    ]
    if not skip_browser:
        commands.append([python, "-m", "playwright", "install", "chromium"])
    commands.append([python, str(ROOT / "scripts" / "local_doctor.py")])
    return commands


def run_command(command: list[str]) -> int:
    completed = subprocess.run(command, cwd=ROOT, check=False)
    return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepara o ambiente local da automação FECAP")
    parser.add_argument("--skip-browser", action="store_true", help="Não instala Chromium")
    parser.add_argument("--check-only", action="store_true", help="Executa apenas o diagnóstico")
    ns = parser.parse_args()

    if sys.version_info < (3, 11):
        print("Python 3.11 ou superior é obrigatório.", file=sys.stderr)
        return 20

    if ns.check_only:
        return run_command([sys.executable, str(ROOT / "scripts" / "local_doctor.py")])

    for command in command_plan(sys.executable, ns.skip_browser):
        code = run_command(command)
        if code != 0:
            print(f"SETUP_BLOCKED: comando retornou {code}", file=sys.stderr)
            return code

    print("SETUP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
