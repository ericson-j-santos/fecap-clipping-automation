from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json

from src.clipping import Candidate
from src.json_schema_probe import json_shape
from src.knewin_runtime_validation import (
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

    def to_dict(self) -> dict:
        return {
            "external_id": self.external_id,
            "title": self.candidate.title,
            "url": self.candidate.url,
            "source": self.candidate.source,
            "published_at": self.candidate.published_at,
            "text": self.candidate.text,
        }


def _digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def session_reuse_ui_is_valid(auth_mode: str, navigation_meta: object) -> bool:
    """Aceita reuso somente com autenticação e navegação Busca/Pesquisa inequívoca."""
    if str(auth_mode or "").casefold() == "unknown":
        return False
    if not isinstance(navigation_meta, dict):
        return False
    count = navigation_meta.get("candidate_count")
    score = navigation_meta.get("top_score")
    ambiguous = navigation_meta.get("ambiguous")
    return (
        isinstance(count, int)
        and count >= 1
        and isinstance(score, int)
        and score >= 125
        and ambiguous is False
    )


def saved_login_submission_is_allowed(
    *,
    explicit_request: bool,
    username_prefilled: bool,
    password_prefilled: bool,
) -> bool:
    """Autoriza Enter somente quando o pedido é explícito e ambos os campos estão preenchidos."""
    return (
        explicit_request is True
        and username_prefilled is True
        and password_prefilled is True
    )


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


def parse_date_window(start_date: str | None, end_date: str | None) -> tuple[date | None, date | None]:
    if not start_date and not end_date:
        return None, None
    if not start_date or not end_date:
        raise SessionCollectorError("start_date e end_date devem ser informados juntos")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise SessionCollectorError("janela de datas inválida; use YYYY-MM-DD") from exc
    if start > end:
        raise SessionCollectorError("start_date não pode ser posterior a end_date")
    return start, end


def publication_date(value: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise SessionCollectorError("publishedDate vazio")
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise SessionCollectorError("publishedDate inválido") from exc


def filter_publications_by_date(
    publications: list["CollectedPublication"],
    start: date | None,
    end: date | None,
) -> list["CollectedPublication"]:
    if start is None and end is None:
        return list(publications)
    if start is None or end is None:
        raise SessionCollectorError("janela de datas incompleta")
    return [
        item
        for item in publications
        if start <= publication_date(item.candidate.published_at) <= end
    ]


def pagination_meta(payload: object) -> tuple[int, int, int]:
    if not isinstance(payload, dict):
        raise SessionCollectorError("resposta de paginação não é objeto")
    count = payload.get("count")
    offset = payload.get("offset")
    page = payload.get("page")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise SessionCollectorError("count inválido na resposta")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise SessionCollectorError("offset inválido na resposta")
    if not isinstance(page, list):
        raise SessionCollectorError("page inválido na resposta")
    return count, offset, len(page)


def next_page_offset(payload: object) -> int | None:
    count, offset, page_size = pagination_meta(payload)
    if page_size == 0:
        return None
    candidate = offset + page_size
    return candidate if candidate < count else None


def request_with_offset(payload: object, offset: int) -> dict:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise SessionCollectorError("offset solicitado inválido")
    if not isinstance(payload, dict):
        raise SessionCollectorError("corpo da requisição não é objeto JSON")
    cloned = deepcopy(payload)
    matches: list[dict] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).casefold() == "offset" and isinstance(child, int) and not isinstance(child, bool):
                    matches.append(value)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(cloned)
    if len(matches) != 1:
        raise SessionCollectorError(
            f"corpo da requisição deve conter exatamente um offset inteiro; encontrados={len(matches)}"
        )
    key = next(key for key in matches[0] if str(key).casefold() == "offset")
    matches[0][key] = offset
    return cloned


def merge_publications(*groups: list["CollectedPublication"]) -> list["CollectedPublication"]:
    unique: dict[str, CollectedPublication] = {}
    for group in groups:
        for item in group:
            unique[item.external_id] = item
    return sorted(
        unique.values(),
        key=lambda item: (publication_date(item.candidate.published_at), item.external_id),
    )


def publication_from_item(item: object) -> CollectedPublication:
    if not isinstance(item, dict):
        raise SessionCollectorError("item de notícia não é objeto")
    external_id = _required_text(item, "id")
    title = _required_text(item, "title")
    url = _required_text(item, "url")
    source = _required_text(item, "source")
    published_at = _required_text(item, "publishedDate")
    content = str(item.get("content") or "").strip()
    return CollectedPublication(
        external_id=external_id,
        candidate=Candidate(
            title=title,
            url=url,
            source=source,
            published_at=published_at,
            text=content,
        ),
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


def functional_output(
    term: str,
    runtime: dict,
    publications: list[CollectedPublication],
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    return {
        "format": 1,
        "mode": "one_shot",
        "term": term,
        "start_date": start_date,
        "end_date": end_date,
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


def build_run_evidence(
    runtime: dict,
    publications: list[CollectedPublication],
    status: int,
    response_shape: dict,
    output_sha256: str,
    *,
    pages_fetched: int = 1,
    source_count: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
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
        "source_count": source_count if source_count is not None else len(publications),
        "pages_fetched": pages_fetched,
        "start_date": start_date,
        "end_date": end_date,
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
