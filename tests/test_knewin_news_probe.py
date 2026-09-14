from pathlib import Path
import inspect
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
        {"name":"FECAP - Clipping"},{"name":"Concorrentes"},{"name":""},{"other":"x"}
    ])
    assert names == ["FECAP - Clipping", "Concorrentes"]

    selected, meta = probe_knewin_news.choose_saved_search_name(
        [{"name":"FECAP - Clipping"},{"name":"Mercado"}], ["Graduação"])
    assert selected == "FECAP - Clipping"
    assert meta["match_strategy"] == "fecap_label" and meta["selected"] is True

    selected, meta = probe_knewin_news.choose_saved_search_name(
        [{"name":"Monitoramento - Extensão"},{"name":"Mercado"}], ["Ahmed El Khatib","Extensão"])
    assert selected == "Monitoramento - Extensão"
    assert meta["match_strategy"] == "configured_term"
    assert meta["configured_term_count"] == 2
    assert meta["configured_term_match_count"] == 1 and meta["selected"] is True

    selected, meta = probe_knewin_news.choose_saved_search_name(
        [{"name":"Graduação - A"},{"name":"Extensão - B"}], ["Graduação","Extensão"])
    assert selected is None
    assert meta["configured_term_match_count"] == 2 and meta["selected"] is False

    selected, meta = probe_knewin_news.choose_saved_search_name(
        [{"name":"Mercado"}], ["Graduação","Extensão"])
    assert selected is None
    assert meta["configured_term_match_count"] == 0 and meta["selected"] is False

    assert probe_knewin_news.extract_saved_search_names({"name":"FECAP"}) == []
    terms = probe_knewin_news.configured_search_terms()
    assert "Ahmed El Khatib" in terms
    assert "Rosely Schwartz" in terms
    assert "Graduação" in terms
    assert "Extensão" in terms

    probe_knewin_news.configure("  Fecap  ")
    assert probe_knewin_news.ACTIVE_SEARCH_TERM == "Fecap"
    assert probe_knewin_news.configured_search_terms() == ["Fecap"]
    assert probe_knewin_news.active_query() == "Fecap"

    args = probe_knewin_news.parse_args(["--term", "Fecap"])
    assert args.term == "Fecap" and args.check is False
    assert args.diagnose_query_dom is False

    diagnostic_args = probe_knewin_news.parse_args(["--diagnose-query-dom"])
    assert diagnostic_args.diagnose_query_dom is True

    source = inspect.getsource(probe_knewin_news.query_dom_diagnostic)
    assert "anchor_count" in source
    assert "input_descendants" in source
    assert "iframe_descendants" in source
    assert "custom_descendant_tags" in source
    assert "el.value" not in source
    assert "localStorage" not in source and "sessionStorage" not in source
    assert "document.cookie" not in source

    probe_knewin_news.configure(None)

    print("knewin news probe tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
