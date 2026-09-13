from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from session_auth_probe import (
    build_network_inventory,
    classify_auth,
    dedupe_network_observations,
    header_scheme,
    is_login_like_url,
    network_observation,
    normalize_content_type,
    session_reuse_is_valid,
    url_fingerprint,
)


def test_bearer_has_priority_and_never_captures_value():
    assert header_scheme("Bearer super-secret-value") == "Bearer"
    result = classify_auth(["Bearer"], ["sessionid"], ["oidc.user"], [], ["login.example.com"])
    assert result.auth_mode == "bearer"
    assert result.authorization_scheme == "Bearer"
    assert result.secrets_captured is False
    assert "super-secret-value" not in str(result.to_dict())


def test_oidc_and_cookie_are_detected_without_values():
    oidc = classify_auth([], [], ["oidc.user:https://issuer:client"], [], ["login.example.com"])
    cookie = classify_auth([], ["JSESSIONID", "route"], [], [], [])
    assert oidc.auth_mode == "oidc"
    assert cookie.auth_mode == "cookie"
    assert cookie.cookie_names == ("JSESSIONID", "route")
    assert oidc.secrets_captured is False and cookie.secrets_captured is False


def test_unknown_fails_closed_when_no_auth_evidence():
    assert classify_auth([], [], [], [], []).auth_mode == "unknown"


def test_reuse_requires_same_authenticated_route_and_known_auth():
    dashboard = "https://monitoring.knewin.com/dashboard?x=secret"
    assert session_reuse_is_valid(dashboard, "https://monitoring.knewin.com/dashboard", "cookie")
    assert not session_reuse_is_valid(dashboard, "https://monitoring.knewin.com/login", "cookie")
    assert not session_reuse_is_valid(dashboard, "https://monitoring.knewin.com/dashboard", "unknown")
    assert not session_reuse_is_valid(dashboard, "https://monitoring.knewin.com/home", "cookie")
    assert is_login_like_url("https://sso.example.com/authorize")


def test_url_evidence_is_fingerprinted_without_query_value():
    first = url_fingerprint("https://monitoring.knewin.com/dashboard?token=secret-value")
    second = url_fingerprint("https://monitoring.knewin.com/dashboard?token=another-secret")
    assert first == second
    assert first["host"] == "monitoring.knewin.com"
    assert len(first["path_sha256"]) == 64
    assert "secret-value" not in str(first)


def test_network_inventory_keeps_only_sanitized_metadata():
    item = network_observation(
        "https://monitoring.knewinapis.com/v3/cliente/noticias?token=super-secret&person=123",
        "post",
        200,
        "application/json; charset=utf-8",
    )
    serialized = json.dumps(item, sort_keys=True)
    assert item["host"] == "monitoring.knewinapis.com"
    assert item["method"] == "POST"
    assert item["status"] == 200
    assert item["content_type"] == "application/json"
    assert item["is_json"] is True
    assert item["secrets_captured"] is False
    assert "super-secret" not in serialized
    assert "person=123" not in serialized
    assert "/v3/cliente/noticias" not in serialized
    assert "authorization" not in serialized.lower()


def test_json_content_types_and_non_json_are_classified():
    assert normalize_content_type(" application/json ; charset=UTF-8") == "application/json"
    vendor = network_observation("https://api.example.com/x", "GET", 201, "application/vnd.example+json")
    html = network_observation("https://api.example.com/x", "GET", 200, "text/html; charset=utf-8")
    assert vendor["is_json"] is True
    assert html["is_json"] is False


def test_network_inventory_is_deduplicated_deterministically():
    a = network_observation("https://api.example.com/a?secret=1", "GET", 200, "application/json")
    a_again = network_observation("https://api.example.com/a?secret=2", "get", 200, "application/json")
    b = network_observation("https://api.example.com/b", "POST", 202, "application/problem+json")
    result = dedupe_network_observations([b, a_again, a])
    assert len(result) == 2
    assert result == dedupe_network_observations([a, b, a_again])
    assert all(item["secrets_captured"] is False for item in result)


def test_network_inventory_filters_caps_and_reports_truncation():
    observations = [
        network_observation(
            f"https://api.example.com/item/{index}?token=leak-value-{index}",
            "GET",
            200,
            "application/json",
        )
        for index in range(4)
    ]
    observations.append(network_observation("https://api.example.com/page", "GET", 200, "text/html"))
    inventory = build_network_inventory(observations, max_entries=2)
    serialized = json.dumps(inventory, sort_keys=True)
    assert inventory["json_endpoint_count"] == 2
    assert len(inventory["json_endpoints"]) == 2
    assert inventory["truncated"] is True
    assert inventory["secrets_captured"] is False
    assert "leak-value-" not in serialized
    assert "token=" not in serialized

    raw_truncated = build_network_inventory(observations[:1], max_entries=10, raw_truncated=True)
    assert raw_truncated["truncated"] is True


if __name__ == "__main__":
    test_bearer_has_priority_and_never_captures_value()
    test_oidc_and_cookie_are_detected_without_values()
    test_unknown_fails_closed_when_no_auth_evidence()
    test_reuse_requires_same_authenticated_route_and_known_auth()
    test_url_evidence_is_fingerprinted_without_query_value()
    test_network_inventory_keeps_only_sanitized_metadata()
    test_json_content_types_and_non_json_are_classified()
    test_network_inventory_is_deduplicated_deterministically()
    test_network_inventory_filters_caps_and_reports_truncation()
    print("session auth probe tests: PASS")
