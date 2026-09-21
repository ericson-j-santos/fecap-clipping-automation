from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.collect_knewin_publications import effective_auth_timeout_seconds
from src.json_schema_probe import json_shape
from src.knewin_session_collector import (
    SessionCollectorError,
    build_run_evidence,
    filter_publications_by_date,
    functional_output,
    merge_publications,
    next_page_offset,
    normalize_publications,
    parse_date_window,
    request_with_offset,
    saved_login_submission_is_allowed,
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

    assert saved_login_submission_is_allowed(
        explicit_request=True, username_prefilled=True, password_prefilled=True
    ) is True
    assert saved_login_submission_is_allowed(
        explicit_request=False, username_prefilled=True, password_prefilled=True
    ) is False
    assert saved_login_submission_is_allowed(
        explicit_request=True, username_prefilled=False, password_prefilled=True
    ) is False
    assert saved_login_submission_is_allowed(
        explicit_request=True, username_prefilled=True, password_prefilled=False
    ) is False

    assert effective_auth_timeout_seconds(False, 600) == 30
    assert effective_auth_timeout_seconds(True, 600) == 600
    assert effective_auth_timeout_seconds(True, 30) == 30
    for invalid in (29, 601):
        try:
            effective_auth_timeout_seconds(True, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("timeout humano fora do limite deveria bloquear")

    start, end = parse_date_window("2026-09-14", "2026-09-14")
    assert start.isoformat() == "2026-09-14" and end.isoformat() == "2026-09-14"
    try:
        parse_date_window("2026-09-15", "2026-09-14")
    except SessionCollectorError:
        pass
    else:
        raise AssertionError("janela invertida deveria bloquear")

    page1 = sample_payload()
    page1["count"] = 3
    page1["page"] = [page1["page"][0]]
    page2 = sample_payload()
    page2["count"] = 3
    page2["offset"] = 1
    page2["page"] = [page2["page"][1]]
    page3 = sample_payload()
    page3["count"] = 3
    page3["offset"] = 2
    page3["page"] = [{
        "id": "news-3",
        "title": "FECAP fora da janela",
        "url": "https://example.invalid/noticia-3",
        "source": "Veículo C",
        "publishedDate": "2026-09-15T09:00:00Z",
        "content": "FECAP.",
    }]
    assert next_page_offset(page1) == 1
    assert next_page_offset(page2) == 2
    assert next_page_offset(page3) is None

    body = {"query": "Fecap", "offset": 0, "filters": {"language": "pt"}}
    changed = request_with_offset(body, 20)
    assert changed["offset"] == 20
    assert body["offset"] == 0
    try:
        request_with_offset({"a": {"offset": 0}, "b": {"offset": 10}}, 20)
    except SessionCollectorError:
        pass
    else:
        raise AssertionError("offset ambíguo deveria bloquear")

    p1 = normalize_publications(page1)
    p2 = normalize_publications(page2)
    p3 = normalize_publications(page3)
    merged = merge_publications(p1, p2, p3)
    assert [item.external_id for item in merged] == ["news-1", "news-2", "news-3"]
    filtered = filter_publications_by_date(merged, start, end)
    assert [item.external_id for item in filtered] == ["news-1", "news-2"]

    payload = sample_payload()
    runtime = runtime_for(payload)
    expected_shape = validate_runtime_gate(runtime)
    assert expected_shape == json_shape(payload)

    publications, actual_shape = validate_live_response(runtime, 200, payload)
    assert len(publications) == 2
    assert publications[0].external_id == "news-1"
    assert publications[0].candidate.title == "FECAP em destaque"
    assert publications[0].candidate.source == "Veículo A"

    output = functional_output(
        "Fecap", runtime, publications, start_date="2026-09-01", end_date="2026-09-30"
    )
    assert output["mode"] == "one_shot"
    assert output["start_date"] == "2026-09-01"
    assert output["end_date"] == "2026-09-30"
    assert output["scheduled"] is False
    assert output["production_enabled"] is False
    assert output["credentials_persisted"] is False
    assert output["raw_response_persisted"] is False
    assert set(output["items"][0]) == {"external_id", "title", "url", "source", "published_at", "text"}
    assert output["items"][0]["title"] == "FECAP em destaque"
    serialized_output = json.dumps(output, ensure_ascii=False)
    assert "Autor A" not in serialized_output
    assert "educação" not in serialized_output

    evidence = build_run_evidence(
        runtime,
        publications,
        200,
        actual_shape,
        "b" * 64,
        pages_fetched=2,
        source_count=20,
        start_date="2026-09-01",
        end_date="2026-09-30",
    )
    serialized = json.dumps(evidence, ensure_ascii=False)
    assert "FECAP em destaque" not in serialized
    assert "Conteúdo público da notícia" not in serialized
    assert evidence["status"] == "PASS"
    assert evidence["collected_count"] == 2
    assert evidence["pages_fetched"] == 2
    assert evidence["source_count"] == 20
    assert evidence["start_date"] == "2026-09-01"
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
