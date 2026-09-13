from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("setup_local", ROOT / "scripts" / "setup_local.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def main() -> int:
    plan = MODULE.command_plan(sys.executable, skip_browser=False)
    assert plan[0][:4] == [sys.executable, "-m", "pip", "install"]
    assert plan[0][-1].endswith("requirements-local.txt")
    assert plan[1] == [sys.executable, "-m", "playwright", "install", "chromium"]
    assert plan[-1][-1].endswith("local_doctor.py")

    without_browser = MODULE.command_plan(sys.executable, skip_browser=True)
    assert len(without_browser) == 2
    assert not any("playwright" in part for command in without_browser for part in command)
    print("test_setup_local: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
