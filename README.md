# FECAP Clipping Automation

Projeto isolado do ReqSys para automatizar clipping FECAP a partir de fontes de notícias, começando pela rotina observada no Knewin.

## Estado
- núcleo de classificação: implementado;
- idempotência SHA-256: implementada;
- fila de revisão: implementada;
- E2E com notícias públicas reais + SQLite de homologação: aprovado;
- coleta autenticada no Knewin: pendente;
- Excel/SharePoint de homologação: pendente.

## Regra inicial
- `include`: porta-voz/professor/coordenador da FECAP participa editorialmente;
- `exclude`: FECAP aparece apenas como formação/currículo incidental;
- `review`: existe referência real à FECAP, mas sem contexto suficiente para decisão automática.

## Executar
`python tests/e2e_public_news.py`

## Evidência
`evidence/e2e-public-real-news.json`
