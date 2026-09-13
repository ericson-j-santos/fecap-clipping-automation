from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.knewin_collector_plan import CollectorPlanError, build_collector_plan


def sample_discovery() -> dict:
    return {
        "status": "PASS",
        "source_status": "PASS",
        "inventory_truncated": False,
        "candidate_count": 1,
        "candidates": [
            {
                "host": "monitoring.knewinapis.com",
                "route_template": "/v3/cliente/{n}/noticias",
                "path_sha256": "a" * 64,
                "method": "POST",
                "status": 200,
                "content_type": "application/json",
                "score": 13,
                "reasons": ["resposta JSON"],
                "secrets_captured": False,
            }
        ],
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
    assert len(first["evidence_binding_sha256"]) == 64
    assert first["secrets_captured"] is False


def test_fail_closed_on_untrusted_evidence() -> None:
    for mutate in (
        lambda d: d.update(status="BLOCKED"),
        lambda d: d.update(source_status="BLOCKED"),
        lambda d: d.update(inventory_truncated=True),
        lambda d: d.update(secrets_captured=True),
    ):
        value = sample_discovery()
        mutate(value)
        expect_blocked(value)


def test_fail_closed_on_unsafe_candidate() -> None:
    variants = []
    for field, value in (
        ("host", "example.com"),
        ("route_template", "/oauth/token"),
        ("route_template", "/noticias?token=abc"),
        ("path_sha256", "short"),
        ("method", "DELETE"),
        ("status", 401),
        ("secrets_captured", True),
    ):
        discovery = sample_discovery()
        discovery["candidates"][0][field] = value
        variants.append(discovery)
    for discovery in variants:
        expect_blocked(discovery)


def test_rank_must_exist() -> None:
    expect_blocked(sample_discovery(), rank=0)
    expect_blocked(sample_discovery(), rank=2)


if __name__ == "__main__":
    test_valid_plan_is_deterministic_and_network_disabled()
    test_fail_closed_on_untrusted_evidence()
    test_fail_closed_on_unsafe_candidate()
    test_rank_must_exist()
    print("knewin collector plan tests: PASS")
