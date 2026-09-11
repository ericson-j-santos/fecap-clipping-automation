from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from session_auth_probe import classify_auth, header_scheme


def test_bearer_has_priority_and_never_captures_value():
    assert header_scheme("Bearer super-secret-value") == "Bearer"
    result = classify_auth(["Bearer"], ["sessionid"], ["oidc.user"], [], ["login.example.com"])
    assert result.auth_mode == "bearer"
    assert result.authorization_scheme == "Bearer"
    assert result.secrets_captured is False
    assert "super-secret-value" not in str(result.to_dict())


def test_oidc_detected_from_storage_or_identity_host():
    result = classify_auth([], [], ["oidc.user:https://issuer:client"], [], ["login.example.com"])
    assert result.auth_mode == "oidc"
    assert result.authorization_scheme is None
    assert result.secrets_captured is False


def test_cookie_session_detected_without_cookie_values():
    result = classify_auth([], ["JSESSIONID", "route"], [], [], [])
    assert result.auth_mode == "cookie"
    assert result.cookie_names == ("JSESSIONID", "route")
    assert result.secrets_captured is False


def test_unknown_fails_closed_when_no_auth_evidence():
    result = classify_auth([], [], [], [], [])
    assert result.auth_mode == "unknown"
    assert result.secrets_captured is False


if __name__ == "__main__":
    test_bearer_has_priority_and_never_captures_value()
    test_oidc_detected_from_storage_or_identity_host()
    test_cookie_session_detected_without_cookie_values()
    test_unknown_fails_closed_when_no_auth_evidence()
    print("session auth probe tests: PASS")
