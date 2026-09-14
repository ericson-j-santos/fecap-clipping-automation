from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.probe_knewin_session as base
import scripts.probe_knewin_session_auto as auto

PORTAL_URL = "https://news.knewin.com/#/login"
AUTH_TIMEOUT_SECONDS = 600


def configure() -> None:
    base.PORTAL_URL = PORTAL_URL
    auto.AUTH_TIMEOUT_SECONDS = AUTH_TIMEOUT_SECONDS


def main() -> int:
    if "--check" in sys.argv:
        print(f"portal={PORTAL_URL} timeout={AUTH_TIMEOUT_SECONDS}")
        return 0
    configure()
    return auto.main()


if __name__ == "__main__":
    raise SystemExit(main())
