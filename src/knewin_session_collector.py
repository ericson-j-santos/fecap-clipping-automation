from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

from clipping import Candidate
from json_schema_probe import json_shape
from knewin_runtime_validation import (
    TARGET_HOST,
    TARGET_METHOD,
    TARGET_ROUTE,
    shape_compatible,
)


class SessionCollectorError(ValueError):
    pass


@dataclass(frozen=True)
class CollectedPublication:
    external_id: str
    candidate: Candidate
    author: str | None = None
    domain: str | None = None
    collection: str | None = None
    terms: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "external_id": self.external_id,
            "title": self.candidate.title,
            "url": self.candidate.url,
            "source": self.candidate.source,
            "published_at": self.candidate.published_at,
            "text": self.candidate.text,
            "author": self.author,
            "domain": self.domain,
            "collection": self.collection,
            "terms": list(self.terms),
        }


def _digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def validate_runtime_gate(runtime: dict) -> dict:
    if not isinstance(runtime, dict) or runtime.get("status") != "RUNTIME_VALIDATED":
        raise SessionCollectorError("runtime ainda não está validado")
    if runtime.get("collector_network_enabled") is not False:
        raise SessionCollectorError("evidência runtime não preserva collector_network_enabled=false")
    if runtime.get("errors") != []:
        raise SessionCollectorError("evidência runtime contém erros")
    if runtime.get("values_persisted") is not False or runtime.get("secrets_captured") is not False:
        raise SessionCollectorError("evidência runtime sem garantias de sanitização")

    endpoint = runtime.get("endpoint") if isinstance(runtime.get("endpoint"), dict) else {}
    expected = {
        "host": TARGET_HOST,
        "route_template": TARGET_ROUTE,
        "method": TARGET_METHOD,
    }
    if any(endpoint.get(key) != value for key, value in expected.items()):
        raise SessionCollectorError("endpoint runtime diverge do contrato validado")

    validation = runtime.get("response_validation") if isinstance(runtime.get("response_validation"), dict) else {}
    if validation.get("schema_compatible") is not True or not isinstance(validation.get("response_schema"), dict):
        raise SessionCollectorError("esquema de resposta runtime não está validado")
    binding = str(runtime.get("evidence_binding_sha256") or "")
    if len(binding) != 64 or any(ch not in "0123456789abcdef" for ch in binding.casefold()):
        raise SessionCollectorError("vínculo da evidência runtime inválido")
    return validation["response_schema"]


def _required_text(item: dict, name: str) -> str:
    value = item.get(name)
    text = str(value or "").strip()
    if not text:
        raise SessionCollectorError(f"notícia sem campo obrigatório: {name}")
    return text


def publication_from_item(item: object) -> CollectedPublication:
    if not isinstance(item, dict):
        raise SessionCollectorError("item de notícia não é objeto")
    external_id = _required_text(item, "id")
    title = _required_text(item, "title")
    url = _required_text(item, "url")
    source = _required_text(item, "source")
    published_at = _required_text(item, "publishedDate")
    content = str(item.get("content") or "").strip()
    terms_value = item.get("terms")
    terms = tuple(str(value) for value in terms_value if isinstance(value, str)) if isinstance(terms_value, list) else ()
    return CollectedPublication(
        external_id=external_id,
        candidate=Candidate(
            title=title,
            url=url,
            source=source,
            published_at=published_at,
            text=content,
        ),
        author=str(item.get("author") or "").strip() or None,
        domain=str(item.get("domain") or "").strip() or None,
        collection=str(item.get("collection") or "").strip() or None,
        terms=terms,
    )


def normalize_publications(payload: object) -> list[CollectedPublication]:
    if not isinstance(payload, dict):
        raise SessionCollectorError("resposta de publications não é objeto")
    page = payload.get("page")
    if not isinstance(page, list):
        raise SessionCollectorError("resposta de publications sem page[]")
    unique: dict[str, CollectedPublication] = {}
    for item in page:
        publication = publication_from_item(item)
        unique[publication.external_id] = publication
    return [unique[key] for key in sorted(unique)]


def validate_live_response(runtime: dict, status: int, payload: object) -> tuple[list[CollectedPublication], dict]:
    expected_shape = validate_runtime_gate(runtime)
    if not isinstance(status, int) or not 200 <= status < 300:
        raise SessionCollectorError(f"publications respondeu HTTP {status}")
    actual_shape = json_shape(payload)
    if not shape_compatible(actual_shape, expected_shape):
        raise SessionCollectorError("resposta atual diverge do esquema runtime validado")
    publications = normalize_publications(payload)
    return publications, actual_shape


def functional_output(term: str, runtime: dict, publications: list[CollectedPublication]) -> dict:
    return {
        "format": 1,
        "mode": "one_shot",
        "term": term,
        "endpoint": {
            "host": TARGET_HOST,
            "route_template": TARGET_ROUTE,
            "method": TARGET_METHOD,
        },
        "evidence_binding_sha256": runtime.get("evidence_binding_sha256"),
        "items": [item.to_dict() for item in publications],
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "scheduled": False,
        "production_enabled": False,
    }


def build_run_evidence(runtime: dict, publications: list[CollectedPublication], status: int, response_shape: dict, output_sha256: str) -> dict:
    identity_digest = _digest(sorted(item.external_id for item in publications))
    return {
        "status": "PASS",
        "mode": "one_shot",
        "runtime_status": runtime.get("status"),
        "candidate_rank": runtime.get("candidate_rank"),
        "endpoint": {
            "host": TARGET_HOST,
            "route_template": TARGET_ROUTE,
            "method": TARGET_METHOD,
        },
        "response_status": status,
        "response_schema_sha256": _digest(response_shape),
        "collected_count": len(publications),
        "item_identity_set_sha256": identity_digest,
        "functional_output_sha256": output_sha256,
        "evidence_binding_sha256": runtime.get("evidence_binding_sha256"),
        "collector_network_enabled": False,
        "scheduled": False,
        "production_enabled": False,
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "values_persisted": False,
        "secrets_captured": False,
        "next_gate": "validar classificação e idempotência com os itens normalizados antes de qualquer destino externo",
    }
