from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.json_schema_probe import json_shape
from src.knewin_session_collector import (
    SessionCollectorError,
    build_run_evidence,
    functional_output,
    normalize_publications,
    session_reuse_ui_is_valid,
    validate_live_response,
    validate_runtime_gate,
)


def runtime_for(payload: dict) -> dict:
    return {
        "status": "RUNTIME_VALIDATED",
        "candidate_rank": 6,
        "endpoint": {
            "host": "news.knewin.com",
            "route_template": "/restful/search/publications",
            "method": "POST",
            "observed_status": 200,
        },
        "response_validation": {
            "status": 200,
            "schema_compatible": True,
            "response_schema": json_shape(payload),
        },
        "evidence_binding_sha256": "a" * 64,
        "collector_network_enabled": False,
        "errors": [],
        "values_persisted": False,
        "secrets_captured": False,
    }


def sample_payload() -> dict:
    return {
        "count": 2,
        "offset": 0,
        "page": [
            {
                "id": "news-1",
                "title": "FECAP em destaque",
                "url": "https://example.invalid/noticia-1",
                "source": "Veículo A",
                "publishedDate": "2026-09-14T10:00:00Z",
                "content": "Conteúdo público da notícia.",
                "author": "Autor A",
                "domain": "example.invalid",
                "collection": "web",
                "terms": ["fecap", "educação"],
            },
            {
                "id": "news-2",
                "title": "Outra notícia FECAP",
                "url": "https://example.invalid/noticia-2",
                "source": "Veículo B",
                "publishedDate": "2026-09-14T11:00:00Z",
                "content": "Outro conteúdo.",
                "author": None,
                "domain": "example.invalid",
                "collection": "web",
                "terms": ["fecap"],
            },
        ],
        "sinceOptionFilter": "all",
    }


def main() -> int:
    search_nav = {"candidate_count": 1, "top_score": 135, "ambiguous": False}
    assert session_reuse_ui_is_valid("oidc", search_nav) is True
    assert session_reuse_ui_is_valid("cookie", search_nav) is True
    assert session_reuse_ui_is_valid("unknown", search_nav) is False
    assert session_reuse_ui_is_valid("oidc", {"candidate_count": 1, "top_score": 75, "ambiguous": False}) is False
    assert session_reuse_ui_is_valid("oidc", {"candidate_count": 2, "top_score": 135, "ambiguous": True}) is False
    assert session_reuse_ui_is_valid("oidc", None) is False

    payload = sample_payload()
    runtime = runtime_for(payload)
    expected_shape = validate_runtime_gate(runtime)
    assert expected_shape == json_shape(payload)

    publications, actual_shape = validate_live_response(runtime, 200, payload)
    assert len(publications) == 2
    assert publications[0].external_id == "news-1"
    assert publications[0].candidate.title == "FECAP em destaque"
    assert publications[0].candidate.source == "Veículo A"

    output = functional_output("Fecap", runtime, publications)
    assert output["mode"] == "one_shot"
    assert output["scheduled"] is False
    assert output["production_enabled"] is False
    assert output["credentials_persisted"] is False
    assert output["raw_response_persisted"] is False
    assert set(output["items"][0]) == {"external_id", "title", "url", "source", "published_at", "text"}
    assert output["items"][0]["title"] == "FECAP em destaque"
    serialized_output = json.dumps(output, ensure_ascii=False)
    assert "Autor A" not in serialized_output
    assert "educação" not in serialized_output

    evidence = build_run_evidence(runtime, publications, 200, actual_shape, "b" * 64)
    serialized = json.dumps(evidence, ensure_ascii=False)
    assert "FECAP em destaque" not in serialized
    assert "Conteúdo público da notícia" not in serialized
    assert evidence["status"] == "PASS"
    assert evidence["collected_count"] == 2
    assert evidence["collector_network_enabled"] is False
    assert evidence["values_persisted"] is False
    assert evidence["secrets_captured"] is False

    bad_runtime = dict(runtime)
    bad_runtime["status"] = "READY_FOR_RUNTIME_VALIDATION"
    try:
        validate_runtime_gate(bad_runtime)
    except SessionCollectorError:
        pass
    else:
        raise AssertionError("runtime não validado deveria bloquear")

    malformed = {"count": 1, "offset": 0, "page": [{"id": "x"}], "sinceOptionFilter": "all"}
    try:
        normalize_publications(malformed)
    except SessionCollectorError:
        pass
    else:
        raise AssertionError("item sem campos obrigatórios deveria bloquear")

    print("knewin session collector tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
