from __future__ import annotations

import importlib.util
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "src/clipping.py",
    "src/github_governance.py",
    "src/knewin_api.py",
    "src/session_auth_probe.py",
    "config/people.json",
    "scripts/audit_main_governance.py",
    "scripts/probe_knewin_session.py",
    "scripts/probe_knewin_session_auto.py",
    "scripts/probe_knewin_news.py",
    "scripts/e2e_live_knewin.py",
    "tests/e2e_public_news.py",
)


def diagnose(root: Path = ROOT) -> dict:
    missing = [rel for rel in REQUIRED_FILES if not (root / rel).is_file()]
    evidence_dir = root / "evidence" / "private"
    writable = True
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        probe = evidence_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        writable = False

    playwright = importlib.util.find_spec("playwright") is not None
    result = {
        "status": "READY" if not missing and writable else "BLOCKED",
        "python": platform.python_version(),
        "python_supported": sys.version_info >= (3, 11),
        "required_files_missing": missing,
        "evidence_private_writable": writable,
        "playwright_installed": playwright,
        "knewin_profile_exists": (Path.home() / ".fecap-clipping" / "knewin-profile").exists(),
    }
    if not result["python_supported"]:
        result["status"] = "BLOCKED"
    return result


def main() -> int:
    result = diagnose()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "READY" else 20


if __name__ == "__main__":
    raise SystemExit(main())
