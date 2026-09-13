from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.json_schema_probe import schema_observation
from src.knewin_collector_plan import CollectorPlanError, build_collector_plan


def sample_discovery() -> dict:
    endpoint = {
        "host": "monitoring.knewinapis.com",
        "route_template": "/v3/cliente/{n}/noticias",
        "path_sha256": "a" * 64,
        "method": "POST",
        "status": 200,
    }
    schema = schema_observation(endpoint, {"noticias": [{"id": "sentinel", "titulo": "secret-title"}], "total": 1})
    return {
        "status": "PASS",
        "source_status": "PASS",
        "inventory_truncated": False,
        "schema_inventory_truncated": False,
        "candidate_count": 1,
        "candidates": [
            {
                **endpoint,
                "content_type": "application/json",
                "score": 13,
                "reasons": ["resposta JSON"],
                "response_schema_count": 1,
                "response_schemas": [
                    {
                        "response_schema_sha256": schema["response_schema_sha256"],
                        "response_schema": schema["response_schema"],
                        "values_persisted": False,
                        "secrets_captured": False,
                    }
                ],
                "schema_observed": True,
                "values_persisted": False,
                "secrets_captured": False,
            }
        ],
        "values_persisted": False,
        "secrets_captured": False,
    }


def expect_blocked(value: dict, *, rank: int = 1) -> None:
    try:
        build_collector_plan(value, rank=rank)
    except CollectorPlanError:
        return
    raise AssertionError("plano inseguro foi aceito")


def test_valid_plan_is_deterministic_and_network_disabled() -> None:
    discovery = sample_discovery()
    first = build_collector_plan(discovery)
    second = build_collector_plan(deepcopy(discovery))
    assert first == second
    assert first["status"] == "READY_FOR_RUNTIME_VALIDATION"
    assert first["network_enabled"] is False
    assert first["endpoint"]["route_template"] == "/v3/cliente/{n}/noticias"
    assert first["endpoint"]["response_schemas"]
    assert len(first["evidence_binding_sha256"]) == 64
    assert "sentinel" not in str(first)
    assert "secret-title" not in str(first)
    assert first["values_persisted"] is False
    assert first["secrets_captured"] is False


def test_fail_closed_on_untrusted_evidence() -> None:
    for mutate in (
        lambda d: d.update(status="BLOCKED"),
        lambda d: d.update(source_status="BLOCKED"),
        lambda d: d.update(inventory_truncated=True),
        lambda d: d.update(schema_inventory_truncated=True),
        lambda d: d.update(values_persisted=True),
        lambda d: d.update(secrets_captured=True),
    ):
        value = sample_discovery()
        mutate(value)
        expect_blocked(value)


def test_fail_closed_on_unsafe_candidate() -> None:
    for field, value in (
        ("host", "example.com"),
        ("route_template", "/oauth/token"),
        ("route_template", "/noticias?token=abc"),
        ("path_sha256", "short"),
        ("method", "DELETE"),
        ("status", 401),
        ("values_persisted", True),
        ("secrets_captured", True),
        ("schema_observed", False),
    ):
        discovery = sample_discovery()
        discovery["candidates"][0][field] = value
        expect_blocked(discovery)


def test_fail_closed_on_tampered_schema() -> None:
    discovery = sample_discovery()
    discovery["candidates"][0]["response_schemas"][0]["response_schema"]["raw_value"] = "leak"
    expect_blocked(discovery)

    discovery = sample_discovery()
    discovery["candidates"][0]["response_schemas"][0]["response_schema_sha256"] = "0" * 64
    expect_blocked(discovery)

    discovery = sample_discovery()
    discovery["candidates"][0]["response_schema_count"] = 2
    expect_blocked(discovery)


def test_rank_must_exist() -> None:
    expect_blocked(sample_discovery(), rank=0)
    expect_blocked(sample_discovery(), rank=2)


if __name__ == "__main__":
    test_valid_plan_is_deterministic_and_network_disabled()
    test_fail_closed_on_untrusted_evidence()
    test_fail_closed_on_unsafe_candidate()
    test_fail_closed_on_tampered_schema()
    test_rank_must_exist()
    print("knewin collector plan tests: PASS")
