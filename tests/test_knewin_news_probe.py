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

    names = probe_knewin_news.extract_saved_search_names([
        {"name": "FECAP - Clipping", "id": 123},
        {"name": "Concorrentes", "id": 456},
        {"name": ""},
        {"other": "x"},
    ])
    assert names == ["FECAP - Clipping", "Concorrentes"]

    selected, meta = probe_knewin_news.choose_saved_search_name([
        {"name": "FECAP - Clipping"},
        {"name": "Concorrentes"},
    ])
    assert selected == "FECAP - Clipping"
    assert meta == {
        "mode": "saved_search",
        "saved_search_count": 2,
        "fecap_match_count": 1,
        "selected": True,
    }

    selected, meta = probe_knewin_news.choose_saved_search_name([
        {"name": "FECAP - Geral"},
        {"name": "FECAP - Professores"},
    ])
    assert selected is None
    assert meta["fecap_match_count"] == 2
    assert meta["selected"] is False

    selected, meta = probe_knewin_news.choose_saved_search_name([{"name": "Mercado"}])
    assert selected is None
    assert meta["fecap_match_count"] == 0
    assert meta["selected"] is False

    assert probe_knewin_news.extract_saved_search_names({"name": "FECAP"}) == []
    print("knewin news probe tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
