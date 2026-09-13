from __future__ import annotations

import hashlib
import json
import re

AUTH_HINTS = ("login", "oauth", "oidc", "authorize", "token", "auth", "session", "signin", "sso")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_METHODS = {"GET", "POST"}


class CollectorPlanError(ValueError):
    pass


def _digest(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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
    }


def build_collector_plan(discovery: dict, *, rank: int = 1) -> dict:
    if not isinstance(discovery, dict):
        raise CollectorPlanError("evidência de descoberta inválida")
    if discovery.get("status") != "PASS" or discovery.get("source_status") != "PASS":
        raise CollectorPlanError("descoberta não possui status PASS")
    if discovery.get("secrets_captured") is not False:
        raise CollectorPlanError("descoberta sem garantia secrets_captured=false")
    if discovery.get("inventory_truncated") is True:
        raise CollectorPlanError("inventário truncado exige nova captura antes do coletor")
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
        "next_gate": "validar endpoint real e esquema da resposta sem persistir credenciais",
        "secrets_captured": False,
    }
