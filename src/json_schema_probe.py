from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

SAFE_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,79}$")
MAX_DEPTH = 6
MAX_FIELDS = 100
MAX_ITEM_SHAPES = 4


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_field_name(value: object) -> str:
    text = str(value)
    if SAFE_FIELD_RE.fullmatch(text):
        return text
    return "{field_sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] + "}"


def json_shape(value: Any, *, depth: int = 0) -> dict:
    if depth >= MAX_DEPTH:
        return {"type": "depth_limit"}
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, dict):
        safe_pairs = sorted((_safe_field_name(key), item) for key, item in value.items())
        selected = safe_pairs[:MAX_FIELDS]
        return {
            "type": "object",
            "fields": {name: json_shape(item, depth=depth + 1) for name, item in selected},
            "fields_truncated": len(safe_pairs) > MAX_FIELDS,
        }
    if isinstance(value, list):
        unique: dict[str, dict] = {}
        for item in value:
            shape = json_shape(item, depth=depth + 1)
            digest = _canonical_digest(shape)
            unique[digest] = shape
            if len(unique) > MAX_ITEM_SHAPES:
                break
        ordered = [unique[key] for key in sorted(unique)[:MAX_ITEM_SHAPES]]
        return {
            "type": "array",
            "item_shapes": ordered,
            "item_shapes_truncated": len(unique) > MAX_ITEM_SHAPES,
        }
    return {"type": "unsupported"}


def schema_observation(endpoint: dict, payload: Any) -> dict:
    shape = json_shape(payload)
    return {
        "host": str(endpoint.get("host") or "")[:180],
        "route_template": str(endpoint.get("route_template") or "")[:240],
        "path_sha256": str(endpoint.get("path_sha256") or "")[:64],
        "method": str(endpoint.get("method") or "")[:16],
        "status": endpoint.get("status") if isinstance(endpoint.get("status"), int) else None,
        "response_schema": shape,
        "response_schema_sha256": _canonical_digest(shape),
        "values_persisted": False,
        "secrets_captured": False,
    }


def dedupe_schema_observations(observations: Iterable[dict]) -> list[dict]:
    unique: dict[tuple, dict] = {}
    for item in observations:
        key = (
            item.get("host", ""),
            item.get("route_template", ""),
            item.get("path_sha256", ""),
            item.get("method", ""),
            item.get("status"),
            item.get("response_schema_sha256", ""),
        )
        unique[key] = {
            "host": key[0],
            "route_template": key[1],
            "path_sha256": key[2],
            "method": key[3],
            "status": key[4],
            "response_schema": item.get("response_schema"),
            "response_schema_sha256": key[5],
            "values_persisted": False,
            "secrets_captured": False,
        }
    return [unique[key] for key in sorted(unique, key=lambda x: tuple("" if p is None else str(p) for p in x))]


def build_schema_inventory(observations: Iterable[dict], *, max_entries: int = 100, raw_truncated: bool = False) -> dict:
    if max_entries < 1:
        raise ValueError("max_entries deve ser maior que zero")
    items = dedupe_schema_observations(observations)
    truncated = raw_truncated or len(items) > max_entries
    items = items[:max_entries]
    return {
        "schema_count": len(items),
        "schemas": items,
        "truncated": truncated,
        "values_persisted": False,
        "secrets_captured": False,
    }
