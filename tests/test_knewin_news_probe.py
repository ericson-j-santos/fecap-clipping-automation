from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import probe_knewin_news
from src.session_auth_probe import is_login_like_url


def main() -> int:
    assert probe_knewin_news.PORTAL_URL == "https://news.knewin.com/#/login"
    assert probe_knewin_news.AUTH_TIMEOUT_SECONDS == 600
    assert is_login_like_url("https://news.knewin.com/#/login") is True
    assert is_login_like_url("https://news.knewin.com/#/home") is False
    print("knewin news probe tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
