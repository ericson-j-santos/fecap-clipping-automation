# Contrato do Excel de homologação — v1.0.0

## Fonte do contrato

O contrato foi reconciliado com duas evidências: a gravação original da rotina Knewin/FECAP e os workbooks históricos reais de clipping encontrados no Drive (`Clipping - Maio.xlsx`, `Clipping - Junho.xlsx`, etc.).

O cabeçalho efetivamente observado nos arquivos reais é:

`DATA | MÍDIA | VEÍCULO | TIER | UNID. NEGÓCIO | FONTE | ASSUNTO | LINK`

A homologação mantém abas mensais no mesmo artefato para facilitar o E2E atual, mas preserva exatamente esse contrato de linha.

## Mapeamento atual

| Coluna | Origem | Regra |
| --- | --- | --- |
| DATA | `published_at` | `dd/mm/aaaa` |
| MÍDIA | — | manter em branco enquanto o coletor não persistir o tipo de mídia |
| VEÍCULO | `source` | valor observado no Knewin |
| TIER | classificação/configuração | preencher somente quando existir configuração evidenciada |
| UNID. NEGÓCIO | `config/people.json` | unidade associada ao porta-voz identificado |
| FONTE | porta-voz identificado | preencher quando a classificação identificar pessoa conhecida |
| ASSUNTO | — | manter em branco; não inferir tema automaticamente neste incremento |
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

Os workbooks históricos localizados no Google Drive servem como evidência do contrato, não como autorização para substituir arquivos existentes. SharePoint só pode ser habilitado depois de evidenciar site, biblioteca e caminho/arquivo do destino atual. Nenhum identificador deve ser inventado ou herdado de outro projeto.
