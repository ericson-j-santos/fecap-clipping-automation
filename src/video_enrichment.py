from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from src.clipping import Candidate, Decision


@dataclass(frozen=True)
class VideoEnrichment:
    status: str
    reason: str
    media: str | None
    tier: int | None
    origin: str | None
    subject: str | None
    person: str | None
    business_unit: str | None
    missing: tuple[str, ...]


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold().strip()


def _ci_lookup(mapping: object, key: str) -> object | None:
    if not isinstance(mapping, dict):
        return None
    target = _norm(key)
    for name, value in mapping.items():
        if _norm(name) == target:
            return value
    return None


def _candidate_field(candidate: Candidate, name: str) -> str:
    if name == "title":
        return candidate.title
    if name == "url":
        return candidate.url
    if name == "source":
        return candidate.source
    if name == "text":
        return candidate.text
    if name == "combined":
        return "\n".join((candidate.title, candidate.text, candidate.url, candidate.source))
    return ""


def _rule_matches(candidate: Candidate, rule: object) -> bool:
    if not isinstance(rule, dict):
        return False
    field = str(rule.get("field") or "combined")
    haystack = _norm(_candidate_field(candidate, field))
    equals = rule.get("equals")
    if equals is not None and haystack != _norm(equals):
        return False
    contains_all = rule.get("contains_all")
    if contains_all is not None:
        if not isinstance(contains_all, list) or not contains_all:
            return False
        if not all(_norm(token) in haystack for token in contains_all):
            return False
    contains_any = rule.get("contains_any")
    if contains_any is not None:
        if not isinstance(contains_any, list) or not contains_any:
            return False
        if not any(_norm(token) in haystack for token in contains_any):
            return False
    return equals is not None or contains_all is not None or contains_any is not None


def _resolve_rule(candidate: Candidate, rules: object, key: str) -> str | None:
    if not isinstance(rules, dict):
        return None
    values = rules.get(key)
    if not isinstance(values, list):
        return None
    matches = [rule for rule in values if _rule_matches(candidate, rule)]
    if len(matches) != 1:
        return None
    value = str(matches[0].get("value") or "").strip()
    return value or None


def enrich_candidate(
    candidate: Candidate,
    decision: Decision,
    rules: dict | None = None,
    *,
    media_hint: str | None = None,
) -> VideoEnrichment:
    rules = rules or {}
    media = str(media_hint or rules.get("default_media") or "").strip() or None

    tier = decision.tier
    if tier is None:
        candidate_tier = _ci_lookup(rules.get("tiers"), candidate.source)
        if isinstance(candidate_tier, int) and not isinstance(candidate_tier, bool):
            tier = candidate_tier

    origin = _resolve_rule(candidate, rules, "origin_rules")
    subject = _resolve_rule(candidate, rules, "subject_rules") or candidate.title.strip() or None
    person = decision.person
    business_unit = decision.business_unit

    required = {
        "TIER": tier,
        "MÍDIA": media,
        "ORIGEM": origin,
        "ASSUNTO": subject,
        "FONTE": person,
        "UN. NEG.": business_unit,
    }
    missing = tuple(name for name, value in required.items() if value in (None, ""))

    status = decision.status
    reason = decision.reason
    if status == "include" and rules.get("require_complete") is True and missing:
        status = "review"
        reason = "enriquecimento incompleto: " + ", ".join(missing)

    return VideoEnrichment(
        status=status,
        reason=reason,
        media=media,
        tier=tier,
        origin=origin,
        subject=subject,
        person=person,
        business_unit=business_unit,
        missing=missing,
    )
