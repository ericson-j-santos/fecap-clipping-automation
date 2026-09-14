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
        {"name": "FECAP - Clipping", "id": 123}, {"name": "Concorrentes", "id": 456},
        {"name": ""}, {"other": "x"},
    ])
    assert names == ["FECAP - Clipping", "Concorrentes"]

    selected, meta = probe_knewin_news.choose_saved_search_name(
        [{"name": "FECAP - Clipping"}, {"name": "Concorrentes"}], ["Pessoa Um"]
    )
    assert selected == "FECAP - Clipping"
    assert meta["match_strategy"] == "fecap_label" and meta["selected"] is True

    selected, meta = probe_knewin_news.choose_saved_search_name(
        [{"name": "FECAP - Geral"}, {"name": "FECAP - Professores"}], ["Pessoa Um"]
    )
    assert selected is None
    assert meta["match_strategy"] == "ambiguous_fecap_label"
    assert meta["fecap_match_count"] == 2 and meta["selected"] is False

    selected, meta = probe_knewin_news.choose_saved_search_name(
        [{"name": "Monitoramento - Ahmed El Khatib"}, {"name": "Mercado"}],
        ["Ahmed El Khatib", "Rosely Schwartz"],
    )
    assert selected == "Monitoramento - Ahmed El Khatib"
    assert meta["match_strategy"] == "configured_person"
    assert meta["configured_person_count"] == 2
    assert meta["person_match_count"] == 1 and meta["selected"] is True

    selected, meta = probe_knewin_news.choose_saved_search_name(
        [{"name": "Ahmed El Khatib - Geral"}, {"name": "Rosely Schwartz - Geral"}],
        ["Ahmed El Khatib", "Rosely Schwartz"],
    )
    assert selected is None
    assert meta["person_match_count"] == 2 and meta["selected"] is False

    selected, meta = probe_knewin_news.choose_saved_search_name(
        [{"name": "Mercado"}], ["Ahmed El Khatib", "Rosely Schwartz"]
    )
    assert selected is None
    assert meta["fecap_match_count"] == 0
    assert meta["person_match_count"] == 0
    assert meta["selected"] is False

    assert probe_knewin_news.extract_saved_search_names({"name": "FECAP"}) == []
    assert len(probe_knewin_news.configured_person_names()) >= 1
    print("knewin news probe tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
