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
)
from src.json_schema_probe import (
    build_schema_inventory,
    json_shape,
    schema_observation,
    schema_observation_from_bytes,
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
    payload = {
        "titulo": "SENTINEL_SECRET_TITLE",
        "total": 987654321,
        "ativo": True,
        "nulo": None,
        "noticias": [{"id": "PRIVATE_ID_123", "score": 99.8}],
    }
    observation = schema_observation(endpoint(), payload)
    serialized = json.dumps(observation, sort_keys=True)
    assert "SENTINEL_SECRET_TITLE" not in serialized
    assert "PRIVATE_ID_123" not in serialized
    assert "987654321" not in serialized
    assert "99.8" not in serialized
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


def test_newsstream_has_larger_but_scoped_schema_limit() -> None:
    newsstream = {
        "host": "news.knewin.com",
        "route_template": "/newsstream/appService",
    }
    admin = {
        "host": "news.knewin.com",
        "route_template": "/newsstream/adminService",
    }
    unrelated = {
        "host": "news.knewin.com",
        "route_template": "/restful/searches",
    }
    external = {
        "host": "example.com",
        "route_template": "/newsstream/appService",
    }
    assert schema_body_limit(newsstream) == KNEWIN_NEWSSTREAM_SCHEMA_BODY_BYTES
    assert schema_body_limit(admin) == KNEWIN_NEWSSTREAM_SCHEMA_BODY_BYTES
    assert schema_body_limit(unrelated) == DEFAULT_SCHEMA_BODY_BYTES
    assert schema_body_limit(external) == DEFAULT_SCHEMA_BODY_BYTES
    assert KNEWIN_NEWSSTREAM_SCHEMA_BODY_BYTES == 8 * 1024 * 1024


def test_inventory_is_deterministic_and_deduplicated() -> None:
    first = schema_observation(endpoint(), {"a": "x", "items": [{"id": 1}]})
    second = schema_observation(endpoint(), {"a": "y", "items": [{"id": 2}]})
    assert first["response_schema_sha256"] == second["response_schema_sha256"]
    one = build_schema_inventory([first, second])
    two = build_schema_inventory([second, first])
    assert one == two
    assert one["schema_count"] == 1
    assert one["values_persisted"] is False


def test_depth_and_field_limits_do_not_leak_values() -> None:
    nested = current = {}
    for level in range(10):
        current[f"level_{level}"] = {"secret_value": f"S{level}"}
        current = current[f"level_{level}"]
    shape = json_shape(nested)
    serialized = json.dumps(shape, sort_keys=True)
    assert "S9" not in serialized
    assert "depth_limit" in serialized


if __name__ == "__main__":
    test_shape_never_persists_scalar_values()
    test_unsafe_dynamic_field_name_is_hashed()
    test_schema_from_bytes_is_size_bounded_and_invalid_json_is_skipped()
    test_newsstream_has_larger_but_scoped_schema_limit()
    test_inventory_is_deterministic_and_deduplicated()
    test_depth_and_field_limits_do_not_leak_values()
    print("json schema probe tests: PASS")
