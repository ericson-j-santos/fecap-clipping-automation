from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

SAFE_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,79}$")
MAX_DEPTH = 6
MAX_FIELDS = 100
MAX_ITEM_SHAPES = 4
MAX_SCHEMA_BODY_BYTES = 1024 * 1024
MAX_JSON_SEQUENCE_ITEMS = 20


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


def schema_observation_from_bytes(endpoint: dict, body: bytes, *, max_bytes: int = MAX_SCHEMA_BODY_BYTES) -> dict | None:
    if max_bytes < 1 or len(body) > max_bytes:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return schema_observation(endpoint, payload)


def _framing_meta(mode: str, body: bytes, prefix: bytes = b"", suffix: bytes = b"", *, item_count: int | None = None) -> dict:
    result = {
        "mode": mode,
        "body_bytes": len(body),
        "prefix_bytes": len(prefix),
        "suffix_bytes": len(suffix),
        "prefix_sha256": hashlib.sha256(prefix).hexdigest() if prefix else None,
        "suffix_sha256": hashlib.sha256(suffix).hexdigest() if suffix else None,
        "values_persisted": False,
        "secrets_captured": False,
    }
    if item_count is not None:
        result["item_count"] = item_count
    return result


def _parse_json_sequence(text: str) -> list[Any] | None:
    decoder = json.JSONDecoder()
    items: list[Any] = []
    index = 0
    size = len(text)
    while index < size:
        while index < size and text[index].isspace():
            index += 1
        if index >= size:
            break
        try:
            value, next_index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            return None
        items.append(value)
        if len(items) > MAX_JSON_SEQUENCE_ITEMS:
            return None
        index = next_index
    return items if len(items) > 1 else None


def schema_observation_from_framed_bytes(
    endpoint: dict,
    body: bytes,
    *,
    max_bytes: int = MAX_SCHEMA_BODY_BYTES,
) -> tuple[dict | None, dict | None]:
    if max_bytes < 1 or len(body) > max_bytes:
        return None, None

    raw = schema_observation_from_bytes(endpoint, body, max_bytes=max_bytes)
    if raw is not None:
        return raw, _framing_meta("raw", body)

    if body.startswith(b"\xef\xbb\xbf"):
        stripped = body[3:]
        observation = schema_observation_from_bytes(endpoint, stripped, max_bytes=max_bytes)
        if observation is not None:
            return observation, _framing_meta("bom_stripped", body, prefix=body[:3])

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None, None

    starts = [pos for pos in (text.find("{"), text.find("[")) if pos >= 0]
    ends = [pos for pos in (text.rfind("}"), text.rfind("]")) if pos >= 0]
    if starts and ends:
        start = min(starts)
        end = max(ends)
        if start <= end:
            candidate = text[start:end + 1]
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                pass
            else:
                prefix = text[:start].encode("utf-8")
                suffix = text[end + 1:].encode("utf-8")
                return schema_observation(endpoint, payload), _framing_meta(
                    "trimmed_envelope", body, prefix=prefix, suffix=suffix
                )

    sequence = _parse_json_sequence(text)
    if sequence is not None:
        observation = schema_observation(endpoint, sequence)
        return observation, _framing_meta("json_sequence", body, item_count=len(sequence))

    return None, None


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
