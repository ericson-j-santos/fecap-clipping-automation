from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.probe_knewin_session import (
    DEFAULT_SCHEMA_BODY_BYTES,
    KNEWIN_NEWSSTREAM_SCHEMA_BODY_BYTES,
    schema_body_limit,
    schema_failure_diagnostic,
)
from src.json_schema_probe import (
    build_schema_inventory,
    json_shape,
    schema_observation,
    schema_observation_from_bytes,
    schema_observation_from_framed_bytes,
)


def endpoint() -> dict:
    return {
        "host": "monitoring.knewinapis.com",
        "route_template": "/v3/cliente/{n}/noticias",
        "path_sha256": "a" * 64,
        "method": "POST",
        "status": 200,
    }


def test_shape_never_persists_scalar_values() -> None:
    payload = {"titulo": "SENTINEL_SECRET_TITLE", "total": 987654321, "ativo": True,
               "nulo": None, "noticias": [{"id": "PRIVATE_ID_123", "score": 99.8}]}
    observation = schema_observation(endpoint(), payload)
    serialized = json.dumps(observation, sort_keys=True)
    for secret in ("SENTINEL_SECRET_TITLE", "PRIVATE_ID_123", "987654321", "99.8"):
        assert secret not in serialized
    assert observation["values_persisted"] is False
    assert observation["secrets_captured"] is False


def test_unsafe_dynamic_field_name_is_hashed() -> None:
    shape = json_shape({"user@example.com": "secret", "safe_field": "ok"})
    serialized = json.dumps(shape, sort_keys=True)
    assert "user@example.com" not in serialized
    assert "safe_field" in serialized
    assert "field_sha256" in serialized


def test_schema_from_bytes_is_size_bounded_and_invalid_json_is_skipped() -> None:
    valid = schema_observation_from_bytes(endpoint(), b'{"title":"secret"}', max_bytes=100)
    assert valid is not None
    assert schema_observation_from_bytes(endpoint(), b'{"title":"secret"}', max_bytes=4) is None
    assert schema_observation_from_bytes(endpoint(), b"not-json", max_bytes=100) is None


def test_framed_json_parses_envelope_without_persisting_prefix_or_values() -> None:
    body = b''')]}',\n{"title":"SENTINEL_VALUE","items":[{"id":123}]}\n'''
    observation, framing = schema_observation_from_framed_bytes(endpoint(), body, max_bytes=1000)
    assert observation is not None and framing is not None
    assert framing["mode"] == "trimmed_envelope"
    assert framing["prefix_bytes"] > 0
    assert framing["prefix_sha256"] is not None
    serialized = json.dumps({"observation": observation, "framing": framing}, sort_keys=True)
    assert "SENTINEL_VALUE" not in serialized
    assert ")]}'" not in serialized
    assert framing["values_persisted"] is False


def test_framed_json_handles_bom_and_sequence_structurally() -> None:
    bom = b"\xef\xbb\xbf{\"secret\":\"SENTINEL_BOM\"}"
    observation, framing = schema_observation_from_framed_bytes(endpoint(), bom, max_bytes=1000)
    assert observation is not None and framing["mode"] == "bom_stripped"
    assert "SENTINEL_BOM" not in json.dumps(observation, sort_keys=True)

    sequence = b'{"a":"SENTINEL_SEQUENCE_A"}\n{"b":"SENTINEL_SEQUENCE_B"}'
    observation, framing = schema_observation_from_framed_bytes(endpoint(), sequence, max_bytes=1000)
    assert observation is not None and framing["mode"] == "json_sequence"
    assert framing["item_count"] == 2
    serialized = json.dumps({"observation": observation, "framing": framing}, sort_keys=True)
    assert "SENTINEL_SEQUENCE_A" not in serialized
    assert "SENTINEL_SEQUENCE_B" not in serialized


def test_framed_json_still_fails_closed_for_unparseable_body() -> None:
    observation, framing = schema_observation_from_framed_bytes(endpoint(), b"not-json-SENTINEL", max_bytes=100)
    assert observation is None and framing is None


def test_newsstream_has_larger_but_scoped_schema_limit() -> None:
    newsstream = {"host": "news.knewin.com", "route_template": "/newsstream/appService"}
    admin = {"host": "news.knewin.com", "route_template": "/newsstream/adminService"}
    unrelated = {"host": "news.knewin.com", "route_template": "/restful/searches"}
    external = {"host": "example.com", "route_template": "/newsstream/appService"}
    assert schema_body_limit(newsstream) == KNEWIN_NEWSSTREAM_SCHEMA_BODY_BYTES
    assert schema_body_limit(admin) == KNEWIN_NEWSSTREAM_SCHEMA_BODY_BYTES
    assert schema_body_limit(unrelated) == DEFAULT_SCHEMA_BODY_BYTES
    assert schema_body_limit(external) == DEFAULT_SCHEMA_BODY_BYTES


def test_schema_failure_diagnostic_never_persists_values() -> None:
    item = endpoint()
    invalid = schema_failure_diagnostic(item, b'{"secret":"SENTINEL"', 100)
    serialized = json.dumps(invalid, sort_keys=True)
    assert invalid["outcome"] == "invalid_json"
    assert "SENTINEL" not in serialized
    assert invalid["values_persisted"] is False
    assert schema_failure_diagnostic(item, b"12345", 4)["outcome"] == "too_large"
    body_error = schema_failure_diagnostic(item, None, 100, error_type="Error")
    assert body_error["outcome"] == "body_error" and body_error["body_bytes"] is None


def test_inventory_is_deterministic_and_deduplicated() -> None:
    first = schema_observation(endpoint(), {"a": "x", "items": [{"id": 1}]})
    second = schema_observation(endpoint(), {"a": "y", "items": [{"id": 2}]})
    assert first["response_schema_sha256"] == second["response_schema_sha256"]
    one = build_schema_inventory([first, second]); two = build_schema_inventory([second, first])
    assert one == two and one["schema_count"] == 1 and one["values_persisted"] is False


def test_depth_and_field_limits_do_not_leak_values() -> None:
    nested = current = {}
    for level in range(10):
        current[f"level_{level}"] = {"secret_value": f"S{level}"}
        current = current[f"level_{level}"]
    serialized = json.dumps(json_shape(nested), sort_keys=True)
    assert "S9" not in serialized and "depth_limit" in serialized


if __name__ == "__main__":
    test_shape_never_persists_scalar_values()
    test_unsafe_dynamic_field_name_is_hashed()
    test_schema_from_bytes_is_size_bounded_and_invalid_json_is_skipped()
    test_framed_json_parses_envelope_without_persisting_prefix_or_values()
    test_framed_json_handles_bom_and_sequence_structurally()
    test_framed_json_still_fails_closed_for_unparseable_body()
    test_newsstream_has_larger_but_scoped_schema_limit()
    test_schema_failure_diagnostic_never_persists_values()
    test_inventory_is_deterministic_and_deduplicated()
    test_depth_and_field_limits_do_not_leak_values()
    print("json schema probe tests: PASS")
