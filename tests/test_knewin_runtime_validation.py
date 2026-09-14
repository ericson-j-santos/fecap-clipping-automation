from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.json_schema_probe import json_shape
from src.knewin_runtime_validation import build_runtime_validation, sanitize_request_contract, shape_compatible


def plan_for(payload: object) -> dict:
    return {
        "status": "READY_FOR_RUNTIME_VALIDATION",
        "network_enabled": False,
        "candidate_rank": 6,
        "endpoint": {
            "host": "news.knewin.com",
            "route_template": "/restful/search/publications",
            "method": "POST",
            "observed_status": 200,
            "response_schemas": [{"response_schema": json_shape(payload)}],
        },
        "evidence_binding_sha256": "a" * 64,
    }


def main() -> int:
    request_payload = {"query": "Fecap", "offset": 0, "filters": {"language": "pt"}}
    headers = {
        "Authorization": "Bearer SECRET-NOT-TO-PERSIST",
        "Cookie": "session=SECRET",
        "Content-Type": "application/json; charset=utf-8",
        "X-Client": "web",
    }
    contract = sanitize_request_contract(
        "https://news.knewin.com/restful/search/publications?ignored=1",
        "POST",
        headers,
        json.dumps(request_payload).encode("utf-8"),
    )
    serialized = json.dumps(contract, ensure_ascii=False)
    assert "SECRET-NOT-TO-PERSIST" not in serialized and "session=SECRET" not in serialized
    assert contract["route_template"] == "/restful/search/publications"
    assert contract["body_format"] == "json"
    assert contract["authorization_present"] is True and contract["cookie_present"] is True
    assert contract["body_schema"]["fields"]["query"]["type"] == "string"
    assert contract["values_persisted"] is False and contract["secrets_captured"] is False

    observed_response = {
        "count": 1,
        "offset": 0,
        "page": [{"title": "x", "url": "https://example.invalid/a", "source": "fonte", "publishedDate": "2026-09-14"}],
        "sinceOptionFilter": "all",
    }
    replay_response = {
        "count": 1,
        "offset": 0,
        "page": [{"title": "y", "url": "https://example.invalid/b", "source": "outra", "publishedDate": "2026-09-14"}],
        "sinceOptionFilter": "all",
    }
    assert shape_compatible(json_shape(replay_response), json_shape(observed_response)) is True

    result = build_runtime_validation(
        plan_for(observed_response),
        contract,
        "https://news.knewin.com/restful/search/publications",
        200,
        replay_response,
    )
    assert result["status"] == "RUNTIME_VALIDATED"
    assert result["collector_network_enabled"] is False
    assert result["response_validation"]["schema_compatible"] is True
    assert result["values_persisted"] is False and result["secrets_captured"] is False

    incompatible = {"count": 1, "offset": 0, "page": [{"unexpected": "x"}], "sinceOptionFilter": "all"}
    blocked = build_runtime_validation(
        plan_for(observed_response), contract,
        "https://news.knewin.com/restful/search/publications", 200, incompatible,
    )
    assert blocked["status"] == "BLOCKED"
    assert "response_schema" in blocked["errors"]

    print("knewin runtime validation tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
