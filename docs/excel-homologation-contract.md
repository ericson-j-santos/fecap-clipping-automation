# Contrato do Excel de homologação — v1.0.0

## Fonte do contrato

O layout foi recuperado da gravação original da rotina Knewin/FECAP e não foi inventado pelo gerador.

As abas mensais seguem o padrão `Janeiro` a `Dezembro` e usam, nesta ordem:

`DATA | VEÍCULO | TIER | MÍDIA | ORIGEM | ASSUNTO | FONTE | UN.NEG | LINK`

## Mapeamento atual

| Coluna | Origem | Regra |
| --- | --- | --- |
| DATA | `published_at` | `dd/mm/aaaa` |
| VEÍCULO | `source` | valor observado no Knewin |
| TIER | classificação | preencher somente quando existir configuração evidenciada |
| MÍDIA | — | manter em branco; não inferir |
| ORIGEM | — | manter em branco até regra de negócio ser confirmada |
| ASSUNTO | — | manter em branco; a gravação evidencia curadoria manual |
| FONTE | porta-voz identificado | preencher quando a classificação identificar pessoa conhecida |
| UN.NEG | `config/people.json` | unidade associada ao porta-voz identificado |
| LINK | `url` | URL canônica da notícia |

## Estados

- `include`: publicado na aba mensal correspondente.
- `review`: não entra na aba mensal; vai para `Revisao` com motivo e chave SHA-256.
- `exclude`: não é publicado no workbook.

A aba `Controle` registra somente contagens e estado dos gates. Conteúdo integral da notícia, cookies, tokens, credenciais e resposta bruta do Knewin não fazem parte do workbook.

## Idempotência

O gerador é determinístico: mesma entrada classificada + mesma configuração produzem exatamente os mesmos bytes e o mesmo `workbook_sha256`.

A chave por item continua sendo a SHA-256 já usada pelo domínio (`canonical_url | published_at | source`).

## Segurança e promoção

O Excel é destino **local de homologação**. `external_destination_enabled=false`, `scheduled=false` e `production_enabled=false` permanecem obrigatórios.

SharePoint só pode ser habilitado depois de evidenciar os três identificadores do destino: site, biblioteca e caminho/arquivo. Nenhum deles deve ser inventado ou inferido de outro projeto.
