from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knewin_discovery import rank_candidates, score_endpoint


def endpoint(route: str, *, host: str = "monitoring.knewinapis.com", method: str = "POST", status: int = 200) -> dict:
    return {
        "host": host,
        "route_template": route,
        "path_sha256": "a" * 64,
        "method": method,
        "status": status,
        "content_type": "application/json",
        "is_json": True,
        "secrets_captured": False,
    }


def test_news_route_ranks_above_auth_route():
    news = endpoint("/v3/cliente/{n}/noticias")
    auth = endpoint("/oauth/token", host="login.knewin.com")
    ranked = rank_candidates([auth, news], limit=2)
    assert ranked["candidate_count"] == 2
    assert ranked["candidates"][0]["route_template"] == "/v3/cliente/{n}/noticias"
    assert ranked["candidates"][0]["score"] > ranked["candidates"][1]["score"]


def test_ranking_is_deterministic_and_sanitized():
    items = [
        endpoint("/search/results", method="GET"),
        endpoint("/clipping/noticias", method="POST"),
    ]
    first = rank_candidates(items, limit=10)
    second = rank_candidates(list(reversed(items)), limit=10)
    assert first == second
    serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)
    assert "Authorization" not in serialized
    assert "cookie" not in serialized.lower()
    assert first["secrets_captured"] is False


def test_limit_and_invalid_limit():
    ranked = rank_candidates([endpoint("/news"), endpoint("/noticias")], limit=1)
    assert ranked["candidate_count"] == 1
    try:
        rank_candidates([], limit=0)
    except ValueError:
        pass
    else:
        raise AssertionError("limit=0 deveria falhar")


def test_non_json_endpoint_is_ignored():
    item = endpoint("/noticias")
    item["is_json"] = False
    assert rank_candidates([item])["candidate_count"] == 0


if __name__ == "__main__":
    test_news_route_ranks_above_auth_route()
    test_ranking_is_deterministic_and_sanitized()
    test_limit_and_invalid_limit()
    test_non_json_endpoint_is_ignored()
    print("knewin discovery tests: PASS")
