from pathlib import Path
import json
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clipping import Candidate, classify, ensure_schema, idempotency_key, persist

DB = ROOT / "data" / "homologacao.sqlite3"
DB.parent.mkdir(exist_ok=True)
if DB.exists():
    DB.unlink()

people = {"Ahmed El Khatib": "Graduação"}
tiers = {"Mercado Comum": 2}

positive = Candidate(
    title="Déficit nominal das contas públicas brasileiras consolidadas alcançou R$ 1.239,8 bilhões...",
    url="https://mercadocomum.com/deficit-nominal-das-contas-publicas-brasileiras-consolidadas-alcancou-r-1-2398-bilhoes-934-do-pib-no-acumulado-dos-doze-meses-ate-julho-deste-ano-pagamento-de-juros-sobre-a-divida-publica-foi-re/?utm_source=e2e",
    source="Mercado Comum",
    published_at="2026-08-31",
    text="Para o professor e coordenador do Centro de Estudos em Finanças da Fundação Escola de Comércio Álvares Penteado (FECAP), Ahmed El Khatib, é necessário observar a trajetória do endividamento.",
)

incidental = Candidate(
    title="EMPRESA SIMPLES NACIONAL E TORNOU LUCRO PRESUMIDO",
    url="https://www.contabeis.com.br/forum/Tributos%20Federais/413456/empresa-simples-nacional-e-tornou-lucro-presumido/",
    source="Portal Contábeis",
    published_at="2026-03-24",
    text="Resposta de usuário. Graduado em Ciências Contábeis e Pós-Graduado em Normas Internacionais de Contabilidade pela FECAP.",
)

ambiguous = Candidate(
    title="FinancIEB 2026 – Sistema Nacional de Educação: impactos, governança e sustentabilidade",
    url="https://semesb.org.br/agenda-e-eventos-2/",
    source="SEMESB",
    published_at="2026-08-26",
    text="Evento acontece no Colégio FECAP, em São Paulo. A página lista o local, mas não apresenta porta-voz da FECAP nem esclarece participação editorial.",
)

with sqlite3.connect(DB) as db:
    ensure_schema(db)
    d1 = classify(positive, people, tiers)
    r1 = persist(db, positive, d1)
    d2 = classify(incidental, people, tiers)
    r2 = persist(db, incidental, d2)
    d3 = classify(ambiguous, people, tiers)
    r3 = persist(db, ambiguous, d3)
    r4 = persist(db, positive, d1)
    db.commit()

with sqlite3.connect(DB) as verify:
    clipping = verify.execute(
        "SELECT title,source,published_at,person,business_unit,tier,url FROM clipping"
    ).fetchall()
    review = verify.execute(
        "SELECT title,source,published_at,reason FROM review_queue"
    ).fetchall()
    incidental_count = verify.execute(
        "SELECT COUNT(*) FROM clipping WHERE source='Portal Contábeis'"
    ).fetchone()[0]
    positive_count = verify.execute(
        "SELECT COUNT(*) FROM clipping WHERE idempotency_key=?", (idempotency_key(positive),)
    ).fetchone()[0]

assert d1.status == "include" and r1 == "inserted"
assert len(clipping) == 1
assert incidental_count == 0 and d2.status == "exclude" and r2 == "not_published"
assert d3.status == "review" and r3 == "queued" and len(review) == 1
assert r4 == "duplicate" and positive_count == 1

evidence = {
    "correlation_id": "clipping-public-e2e-20260911-001",
    "environment": "sandbox-homologacao",
    "cases": {
        "positive": {"decision": d1.__dict__, "persist_result": r1, "independent_read": clipping},
        "incidental": {"decision": d2.__dict__, "persist_result": r2, "published_count": incidental_count},
        "ambiguous": {"decision": d3.__dict__, "persist_result": r3, "independent_read": review},
        "idempotency_repeat": {"persist_result": r4, "final_count": positive_count},
    },
    "status": "PASS",
    "limitations": [
        "Coleta real feita em fontes públicas da web, não pela sessão autenticada da Knewin.",
        "Destino de homologação usado: SQLite isolado; Excel/SharePoint ainda não conectado.",
    ],
}
(ROOT / "evidence").mkdir(exist_ok=True)
(ROOT / "evidence" / "e2e-public-real-news.json").write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(evidence, ensure_ascii=False, indent=2))
