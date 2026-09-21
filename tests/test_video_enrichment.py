from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.clipping import Candidate, Decision
from src.video_enrichment import enrich_candidate


def main() -> int:
    rules = json.loads((ROOT / "config" / "video_enrichment.json").read_text(encoding="utf-8"))

    direcional = Candidate(
        title="Nota fiscal: condomínio terá de emitir? - Direcional Condomínios",
        url="https://example.invalid/direcional",
        source="DIRECIONAL CONDOMÍNIOS",
        published_at="2026-08-31T00:00:00",
        text="A professora Rosely Schwartz, da FECAP, explica o tema.",
    )
    d1 = Decision(
        "include", "participação editorial explícita de porta-voz FECAP",
        person="Rosely Schwartz", business_unit="Extensão",
    )
    e1 = enrich_candidate(direcional, d1, rules)
    assert e1.status == "include"
    assert e1.tier == 2
    assert e1.media == "Online"
    assert e1.origin == "Menção"
    assert e1.person == "Rosely Schwartz"
    assert e1.business_unit == "Extensão"
    assert e1.subject == direcional.title
    assert e1.missing == ()

    mercado = Candidate(
        title="Déficit nominal das contas públicas brasileiras consolidadas alcançou R$ 1,2 trilhão",
        url="https://mercadocomum.com/deficit-nominal-das-contas-publicas-brasileiras",
        source="Mercado Comum",
        published_at="2026-08-31T00:00:00",
        text="O professor Ahmed El Khatib, da FECAP, comenta os dados.",
    )
    d2 = Decision(
        "include", "participação editorial explícita de porta-voz FECAP",
        person="Ahmed El Khatib", business_unit="Graduação",
    )
    e2 = enrich_candidate(mercado, d2, rules)
    assert e2.status == "include"
    assert e2.tier == 2
    assert e2.media == "Online"
    assert e2.origin == "Proativo"
    assert e2.missing == ()

    unknown = Candidate(
        title="Professor FECAP comenta tema sem regra histórica",
        url="https://example.invalid/unknown",
        source="Veículo sem tier",
        published_at="2026-08-31T00:00:00",
        text="Professor da FECAP comenta.",
    )
    d3 = Decision(
        "include", "participação editorial explícita de porta-voz FECAP",
        person="Pessoa", business_unit="Unidade",
    )
    e3 = enrich_candidate(unknown, d3, rules)
    assert e3.status == "review"
    assert "TIER" in e3.missing and "ORIGEM" in e3.missing

    print("test_video_enrichment: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
