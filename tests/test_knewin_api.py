from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from clipping import Candidate
from excel_homologation import build_workbook_bytes
from knewin_api import KnewinApiError, KnewinNews, split_windows, to_news
from scripts.e2e_live_knewin import (
    LiveE2EError,
    collector_payload,
    execute_operational_roundtrip,
    tiers_from_collected,
    validate_correlation_id,
)

start = datetime(2026, 8, 1, tzinfo=timezone.utc)
end = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)
windows = split_windows(start, end)

assert len(windows) == 3
assert all((window_end - window_start).days <= 14 for window_start, window_end in windows)
assert windows[0][0] == start
assert windows[-1][1] == end

sample = {
    "id": 123,
    "titulo": "FECAP comenta cenário econômico",
    "resumo": "Resumo",
    "texto": "Professor da FECAP comenta o tema.",
    "data_publicacao": "2026-08-31T12:00:00Z",
    "url_original": "https://example.org/noticia",
    "veiculo": {"nome": "Veículo Exemplo", "tier": "2"},
}
news = to_news(sample)
assert news.external_id == "123"
assert news.candidate.source == "Veículo Exemplo"
assert news.tier == 2

invalid = dict(sample)
invalid["url_original"] = ""
try:
    to_news(invalid)
except KnewinApiError:
    pass
else:
    raise AssertionError("notícia incompleta deveria falhar fechada")

payload = collector_payload([news])
assert payload["format"] == 1
assert payload["credentials_persisted"] is False
assert payload["raw_response_persisted"] is False
assert payload["production_enabled"] is False
assert payload["items"][0]["external_id"] == "123"
assert "raw" not in payload["items"][0]
assert tiers_from_collected([news]) == {"Veículo Exemplo": 2}
assert validate_correlation_id("knewin-gha-123-1") == "knewin-gha-123-1"

try:
    validate_correlation_id("../../invalid")
except LiveE2EError as exc:
    assert exc.code == "correlation_id_invalid"
else:
    raise AssertionError("correlation_id inválido deveria falhar fechado")

conflicting = KnewinNews(
    external_id="124",
    candidate=Candidate(
        title="Outro item",
        url="https://example.org/outro",
        source="Veículo Exemplo",
        published_at="2026-08-31T13:00:00Z",
        text="FECAP",
    ),
    tier=3,
    raw={},
)
try:
    tiers_from_collected([news, conflicting])
except LiveE2EError as exc:
    assert exc.code == "tier_conflict"
else:
    raise AssertionError("tiers conflitantes deveriam falhar fechado")

people = json.loads((ROOT / "config" / "people.json").read_text(encoding="utf-8"))
rules = json.loads((ROOT / "config" / "video_enrichment.json").read_text(encoding="utf-8"))
base_collector = {
    "format": 1,
    "mode": "one_shot",
    "credentials_persisted": False,
    "raw_response_persisted": False,
    "production_enabled": False,
    "items": [{
        "external_id": "https://example.invalid/direcional",
        "title": "Nota fiscal: condomínio terá de emitir? - Direcional Condomínios",
        "url": "https://example.invalid/direcional",
        "source": "DIRECIONAL CONDOMÍNIOS",
        "published_at": "2026-08-01T00:00:00Z",
        "text": "A professora Rosely Schwartz, da FECAP, comenta o tema.",
    }],
}
base_workbook, _ = build_workbook_bytes(
    base_collector,
    people,
    {},
    enrichment_rules=rules,
)
live_news = KnewinNews(
    external_id="live-mercado-comum",
    candidate=Candidate(
        title="Déficit nominal das contas públicas brasileiras consolidadas alcançou R$ 1,2 trilhão",
        url="https://mercadocomum.com/deficit-nominal-das-contas-publicas-brasileiras",
        source="Mercado Comum",
        published_at="2026-08-31T00:00:00Z",
        text="O professor Ahmed El Khatib, da FECAP, comenta o tema.",
    ),
    tier=2,
    raw={"sensitive": "must-not-be-persisted"},
)
roundtrip = execute_operational_roundtrip(
    base_workbook,
    [live_news],
    people,
    rules,
)
assert roundtrip["model_counts"]["include"] == 1
assert roundtrip["first"].evidence["appended_count"] == 1
assert roundtrip["replay"].evidence["appended_count"] == 0
assert roundtrip["replay"].evidence["no_op"] is True
assert roundtrip["first"].workbook == roundtrip["replay"].workbook
assert "raw" not in roundtrip["collector"]["items"][0]

print("knewin_api_contract=PASS")
