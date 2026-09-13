from __future__ import annotations

import hashlib
import json
import re

AUTH_HINTS = ("login", "oauth", "oidc", "authorize", "token", "auth", "session", "signin", "sso")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_FIELD_RE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_.-]{0,79}|\{field_sha256:[0-9a-f]{16}\})$")
ALLOWED_METHODS = {"GET", "POST"}
SCALAR_SCHEMA_TYPES = {"null", "boolean", "number", "string", "unsupported", "depth_limit"}


class CollectorPlanError(ValueError):
    pass


def _digest(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_schema_shape(shape: object, *, depth: int = 0) -> dict:
    if depth > 8 or not isinstance(shape, dict):
        raise CollectorPlanError("response_schema inválido")
    schema_type = shape.get("type")
    if schema_type in SCALAR_SCHEMA_TYPES:
        if set(shape) != {"type"}:
            raise CollectorPlanError("response_schema escalar contém dados extras")
        return {"type": schema_type}
    if schema_type == "object":
        if set(shape) != {"type", "fields", "fields_truncated"}:
            raise CollectorPlanError("response_schema object contém dados extras")
        fields = shape.get("fields")
        if not isinstance(fields, dict) or not isinstance(shape.get("fields_truncated"), bool):
            raise CollectorPlanError("response_schema object inválido")
        clean_fields: dict[str, dict] = {}
        for name in sorted(fields):
            if not isinstance(name, str) or not SAFE_FIELD_RE.fullmatch(name):
                raise CollectorPlanError("nome de campo do response_schema não está sanitizado")
            clean_fields[name] = _validate_schema_shape(fields[name], depth=depth + 1)
        return {"type": "object", "fields": clean_fields, "fields_truncated": shape["fields_truncated"]}
    if schema_type == "array":
        if set(shape) != {"type", "item_shapes", "item_shapes_truncated"}:
            raise CollectorPlanError("response_schema array contém dados extras")
        items = shape.get("item_shapes")
        if not isinstance(items, list) or not isinstance(shape.get("item_shapes_truncated"), bool):
            raise CollectorPlanError("response_schema array inválido")
        return {
            "type": "array",
            "item_shapes": [_validate_schema_shape(item, depth=depth + 1) for item in items],
            "item_shapes_truncated": shape["item_shapes_truncated"],
        }
    raise CollectorPlanError("tipo de response_schema não permitido")


def _validate_response_schemas(candidate: dict) -> list[dict]:
    if candidate.get("values_persisted") is not False:
        raise CollectorPlanError("candidato sem garantia values_persisted=false")
    schemas = candidate.get("response_schemas")
    count = candidate.get("response_schema_count")
    if candidate.get("schema_observed") is not True or not isinstance(schemas, list) or not schemas:
        raise CollectorPlanError("candidato sem esquema JSON observado")
    if count != len(schemas):
        raise CollectorPlanError("response_schema_count divergente")
    clean: dict[str, dict] = {}
    for item in schemas:
        if not isinstance(item, dict):
            raise CollectorPlanError("entrada de response_schema inválida")
        if item.get("values_persisted") is not False or item.get("secrets_captured") is not False:
            raise CollectorPlanError("response_schema sem garantias de sanitização")
        digest = str(item.get("response_schema_sha256") or "").lower()
        if not SHA256_RE.fullmatch(digest):
            raise CollectorPlanError("response_schema_sha256 inválido")
        shape = _validate_schema_shape(item.get("response_schema"))
        if _digest(shape) != digest:
            raise CollectorPlanError("response_schema_sha256 não corresponde ao esquema")
        clean[digest] = {
            "response_schema_sha256": digest,
            "response_schema": shape,
            "values_persisted": False,
            "secrets_captured": False,
        }
    return [clean[digest] for digest in sorted(clean)]


def _validate_candidate(candidate: dict) -> dict:
    host = str(candidate.get("host") or "").strip().lower()
    route = str(candidate.get("route_template") or "").strip()
    path_sha256 = str(candidate.get("path_sha256") or "").strip().lower()
    method = str(candidate.get("method") or "").strip().upper()
    status = candidate.get("status")

    if candidate.get("secrets_captured") is not False:
        raise CollectorPlanError("candidato sem garantia secrets_captured=false")
    if not host or "knewin" not in host:
        raise CollectorPlanError("host candidato não pertence ao contexto Knewin")
    if not route.startswith("/") or "?" in route or "#" in route:
        raise CollectorPlanError("route_template não está sanitizado")
    route_lower = route.casefold()
    if any(hint in route_lower or hint in host.casefold() for hint in AUTH_HINTS):
        raise CollectorPlanError("rota candidata parece autenticação")
    if not SHA256_RE.fullmatch(path_sha256):
        raise CollectorPlanError("path_sha256 inválido")
    if method not in ALLOWED_METHODS:
        raise CollectorPlanError("método HTTP não permitido")
    if not isinstance(status, int) or not 200 <= status < 300:
        raise CollectorPlanError("candidato não possui resposta 2xx comprovada")

    return {
        "host": host,
        "route_template": route,
        "path_sha256": path_sha256,
        "method": method,
        "observed_status": status,
        "response_schemas": _validate_response_schemas(candidate),
    }


def build_collector_plan(discovery: dict, *, rank: int = 1) -> dict:
    if not isinstance(discovery, dict):
        raise CollectorPlanError("evidência de descoberta inválida")
    if discovery.get("status") != "PASS" or discovery.get("source_status") != "PASS":
        raise CollectorPlanError("descoberta não possui status PASS")
    if discovery.get("secrets_captured") is not False or discovery.get("values_persisted") is not False:
        raise CollectorPlanError("descoberta sem garantias de sanitização")
    if discovery.get("inventory_truncated") is True:
        raise CollectorPlanError("inventário truncado exige nova captura antes do coletor")
    if discovery.get("schema_inventory_truncated") is True:
        raise CollectorPlanError("inventário de esquemas truncado exige nova captura")
    if rank < 1:
        raise CollectorPlanError("rank deve começar em 1")

    candidates = discovery.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise CollectorPlanError("nenhum candidato observado")
    if rank > len(candidates):
        raise CollectorPlanError("rank solicitado não existe")

    endpoint = _validate_candidate(candidates[rank - 1])
    binding_payload = {
        "source_status": discovery.get("source_status"),
        "candidate_rank": rank,
        "endpoint": endpoint,
    }
    return {
        "status": "READY_FOR_RUNTIME_VALIDATION",
        "network_enabled": False,
        "candidate_rank": rank,
        "endpoint": endpoint,
        "evidence_binding_sha256": _digest(binding_payload),
        "next_gate": "validar chamada real contra endpoint e esquemas observados sem persistir credenciais",
        "values_persisted": False,
        "secrets_captured": False,
    }
