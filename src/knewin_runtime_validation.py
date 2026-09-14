from __future__ import annotations

import hashlib
import json
from urllib.parse import urlparse

from src.json_schema_probe import json_shape

TARGET_HOST = "news.knewin.com"
TARGET_ROUTE = "/restful/search/publications"
TARGET_METHOD = "POST"
MAX_HEADER_NAMES = 100
SENSITIVE_HEADER_NAMES = {"authorization", "cookie", "proxy-authorization"}


def _digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _route(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    return (parsed.hostname or "").casefold(), parsed.path.rstrip("/") or "/"


def sanitize_request_contract(url: str, method: str, headers: dict[str, str], body: bytes | None) -> dict:
    host, route = _route(url)
    normalized_headers = {str(key).casefold(): str(value) for key, value in headers.items()}
    names = sorted(normalized_headers)
    truncated = len(names) > MAX_HEADER_NAMES
    names = names[:MAX_HEADER_NAMES]
    content_type = normalized_headers.get("content-type", "").split(";", 1)[0].strip().casefold()

    body_shape = None
    body_shape_sha256 = None
    body_format = "none"
    if body:
        if content_type == "application/json" or content_type.endswith("+json"):
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                body_format = "invalid_json"
            else:
                body_shape = json_shape(payload)
                body_shape_sha256 = _digest(body_shape)
                body_format = "json"
        else:
            body_format = "non_json"

    return {
        "host": host[:180],
        "route_template": route[:240],
        "method": str(method or "").upper()[:16],
        "content_type": content_type[:120],
        "header_count": len(normalized_headers),
        "header_names": names,
        "header_names_truncated": truncated,
        "authorization_present": "authorization" in normalized_headers,
        "cookie_present": "cookie" in normalized_headers,
        "body_format": body_format,
        "body_bytes": 0 if body is None else len(body),
        "body_schema": body_shape,
        "body_schema_sha256": body_shape_sha256,
        "values_persisted": False,
        "secrets_captured": False,
    }


def shape_compatible(actual: object, expected: object) -> bool:
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    actual_type = actual.get("type")
    expected_type = expected.get("type")
    if actual_type != expected_type:
        return False
    if actual_type in {"null", "boolean", "number", "string", "unsupported", "depth_limit"}:
        return True
    if actual_type == "object":
        actual_fields = actual.get("fields")
        expected_fields = expected.get("fields")
        if not isinstance(actual_fields, dict) or not isinstance(expected_fields, dict):
            return False
        for name, actual_shape in actual_fields.items():
            if name not in expected_fields or not shape_compatible(actual_shape, expected_fields[name]):
                return False
        return True
    if actual_type == "array":
        actual_items = actual.get("item_shapes")
        expected_items = expected.get("item_shapes")
        if not isinstance(actual_items, list) or not isinstance(expected_items, list):
            return False
        return all(any(shape_compatible(item, candidate) for candidate in expected_items) for item in actual_items)
    return False


def build_runtime_validation(plan: dict, request_contract: dict, response_url: str, response_status: int, response_payload: object) -> dict:
    errors: list[str] = []
    if plan.get("status") != "READY_FOR_RUNTIME_VALIDATION":
        errors.append("plan_status")
    if plan.get("network_enabled") is not False:
        errors.append("plan_network_enabled")

    endpoint = plan.get("endpoint") if isinstance(plan.get("endpoint"), dict) else {}
    if endpoint.get("host") != TARGET_HOST or endpoint.get("route_template") != TARGET_ROUTE or endpoint.get("method") != TARGET_METHOD:
        errors.append("plan_endpoint")

    if request_contract.get("host") != TARGET_HOST or request_contract.get("route_template") != TARGET_ROUTE or request_contract.get("method") != TARGET_METHOD:
        errors.append("request_endpoint")
    if request_contract.get("body_format") != "json" or not isinstance(request_contract.get("body_schema"), dict):
        errors.append("request_body_schema")
    if request_contract.get("values_persisted") is not False or request_contract.get("secrets_captured") is not False:
        errors.append("request_sanitization")

    response_host, response_route = _route(response_url)
    if response_host != TARGET_HOST or response_route != TARGET_ROUTE:
        errors.append("response_endpoint")
    if not isinstance(response_status, int) or not 200 <= response_status < 300:
        errors.append("response_status")

    actual_shape = json_shape(response_payload)
    schemas = endpoint.get("response_schemas") if isinstance(endpoint.get("response_schemas"), list) else []
    schema_match = any(
        isinstance(item, dict) and shape_compatible(actual_shape, item.get("response_schema"))
        for item in schemas
    )
    if not schema_match:
        errors.append("response_schema")

    status = "RUNTIME_VALIDATED" if not errors else "BLOCKED"
    return {
        "status": status,
        "candidate_rank": plan.get("candidate_rank"),
        "endpoint": {
            "host": TARGET_HOST,
            "route_template": TARGET_ROUTE,
            "method": TARGET_METHOD,
            "observed_status": endpoint.get("observed_status"),
        },
        "request_contract": request_contract,
        "response_validation": {
            "status": response_status,
            "schema_compatible": schema_match,
            "response_schema": actual_shape,
            "response_schema_sha256": _digest(actual_shape),
        },
        "evidence_binding_sha256": plan.get("evidence_binding_sha256"),
        "collector_network_enabled": False,
        "errors": errors,
        "next_gate": "implementar o menor coletor autenticado reutilizando o contexto validado e mantendo credenciais fora da evidência" if status == "RUNTIME_VALIDATED" else "corrigir o gate runtime antes de habilitar qualquer coletor",
        "values_persisted": False,
        "secrets_captured": False,
    }
