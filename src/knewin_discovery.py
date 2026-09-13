from __future__ import annotations

from typing import Iterable

ROUTE_HINTS = {
    "noticia": 5,
    "noticias": 5,
    "news": 5,
    "clipping": 5,
    "search": 3,
    "busca": 3,
    "resultado": 2,
    "results": 2,
    "cliente": 1,
    "monitor": 1,
}
AUTH_HINTS = ("login", "oauth", "oidc", "authorize", "token", "auth", "session")


def score_endpoint(item: dict) -> dict:
    host = str(item.get("host", ""))[:180]
    route = str(item.get("route_template", ""))[:240]
    method = str(item.get("method", ""))[:16]
    status = item.get("status")
    content_type = item.get("content_type")
    path_sha256 = str(item.get("path_sha256", ""))[:64]
    score = 0
    reasons: list[str] = []

    if item.get("is_json"):
        score += 3
        reasons.append("resposta JSON")
    if isinstance(status, int) and 200 <= status < 300:
        score += 2
        reasons.append("status 2xx")
    if "knewin" in host.lower():
        score += 2
        reasons.append("host Knewin")
    if method.upper() in {"GET", "POST"}:
        score += 1
        reasons.append(f"método {method.upper()}")

    route_lower = route.lower()
    for hint, weight in ROUTE_HINTS.items():
        if hint in route_lower:
            score += weight
            reasons.append(f"rota contém {hint}")

    if any(hint in route_lower or hint in host.lower() for hint in AUTH_HINTS):
        score -= 10
        reasons.append("parece autenticação")

    return {
        "host": host,
        "route_template": route,
        "path_sha256": path_sha256,
        "method": method,
        "status": status if isinstance(status, int) else None,
        "content_type": content_type,
        "score": score,
        "reasons": reasons,
        "secrets_captured": False,
    }


def rank_candidates(endpoints: Iterable[dict], *, limit: int = 10) -> dict:
    if limit < 1:
        raise ValueError("limit deve ser maior que zero")
    scored = [score_endpoint(item) for item in endpoints if item.get("is_json")]
    scored.sort(
        key=lambda item: (
            -item["score"],
            item["host"],
            item["route_template"],
            item["method"],
            item["status"] if item["status"] is not None else -1,
        )
    )
    selected = scored[:limit]
    return {
        "candidate_count": len(selected),
        "candidates": selected,
        "secrets_captured": False,
    }


def attach_schema_evidence(candidates: Iterable[dict], schema_observations: Iterable[dict]) -> list[dict]:
    index: dict[tuple, list[dict]] = {}
    for item in schema_observations:
        key = (
            str(item.get("host") or ""),
            str(item.get("path_sha256") or ""),
            str(item.get("method") or ""),
            item.get("status"),
        )
        schema = item.get("response_schema")
        digest = str(item.get("response_schema_sha256") or "")
        if not isinstance(schema, dict) or not digest:
            continue
        entry = {
            "response_schema_sha256": digest,
            "response_schema": schema,
            "values_persisted": False,
            "secrets_captured": False,
        }
        index.setdefault(key, []).append(entry)

    enriched: list[dict] = []
    for candidate in candidates:
        key = (
            str(candidate.get("host") or ""),
            str(candidate.get("path_sha256") or ""),
            str(candidate.get("method") or ""),
            candidate.get("status"),
        )
        unique = {
            item["response_schema_sha256"]: item
            for item in index.get(key, [])
        }
        schemas = [unique[digest] for digest in sorted(unique)]
        enriched.append(
            {
                **candidate,
                "response_schema_count": len(schemas),
                "response_schemas": schemas,
                "schema_observed": bool(schemas),
                "values_persisted": False,
                "secrets_captured": False,
            }
        )
    return enriched
