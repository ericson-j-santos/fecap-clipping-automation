from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from session_auth_probe import (
    classify_auth,
    header_scheme,
    is_login_like_url,
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
    evidence = url_fingerprint("https://monitoring.knewin.com/dashboard?token=secret-value")
    assert evidence["host"] == "monitoring.knewin.com"
    assert len(evidence["path_sha256"]) == 64
    assert "secret-value" not in str(evidence)


if __name__ == "__main__":
    test_bearer_has_priority_and_never_captures_value()
    test_oidc_and_cookie_are_detected_without_values()
    test_unknown_fails_closed_when_no_auth_evidence()
    test_reuse_requires_same_authenticated_route_and_known_auth()
    test_url_evidence_is_fingerprinted_without_query_value()
    print("session auth probe tests: PASS")
