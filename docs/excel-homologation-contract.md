# Contrato do Excel de homologação — v2.0.0

## Fonte do contrato

O alvo funcional deste contrato é a gravação original da rotina Knewin/FECAP enviada em 11/09/2026. O vídeo mostra o workbook `Clipping_2026`, aba mensal `Agosto`, com nove colunas:

`DATA | VEÍCULO | TIER | MÍDIA | ORIGEM | ASSUNTO | FONTE | UN. NEG. | LINK`

Os workbooks históricos do Drive continuam como evidência auxiliar para valores de TIER, unidade de negócio, fonte e assunto. Eles não substituem o contrato visual do fluxo alvo quando houver divergência de estrutura.

## Mapeamento alvo

| Coluna | Origem | Regra |
| --- | --- | --- |
| DATA | `published_at` | `dd/mm/aaaa` |
| VEÍCULO | `source` | valor observado no Knewin |
| TIER | classificação/configuração | somente por configuração evidenciada |
| MÍDIA | `config/video_enrichment.json` | alvo do vídeo: `Online`; pode ser substituído por regra explícita futura |
| ORIGEM | regras versionadas | somente `Menção`/`Proativo` quando uma regra evidenciada casar de forma inequívoca |
| ASSUNTO | regra versionada ou título | quando não houver normalização específica, usa o título da notícia, sem inventar tema |
| FONTE | porta-voz identificado | nome conhecido em `config/people.json` |
| UN. NEG. | `config/people.json` | unidade associada ao porta-voz |
| LINK | `url` | URL canônica da notícia |

## Fail-closed

O fluxo de vídeo exige enriquecimento completo para publicação automática. Quando `require_complete=true`, qualquer item `include` sem TIER, MÍDIA, ORIGEM, ASSUNTO, FONTE ou UN. NEG. é rebaixado para `review`.

Nada é preenchido por palpite silencioso.

As duas combinações registradas inicialmente em `config/video_enrichment.json` vêm diretamente do vídeo:

- Direcional Condomínios / Rosely Schwartz → TIER 2, Online, Menção, Extensão;
- Mercado Comum / Ahmed El Khatib → TIER 2, Online, Proativo, Graduação.

Novas regras precisam de evidência antes de entrar no arquivo de configuração.

## Estados

- `include`: enriquecimento completo e publicação na aba mensal.
- `review`: referência válida, mas decisão editorial ou enriquecimento incompleto.
- `exclude`: item não publicado.

## Idempotência

O gerador continua determinístico: mesma entrada + mesmas regras produzem os mesmos bytes e o mesmo `workbook_sha256`.

A chave por item permanece `SHA-256(canonical_url | published_at | source)`.

## Segurança

O workbook continua de homologação. `external_destination_enabled=false`, `scheduled=false` e `production_enabled=false` permanecem obrigatórios até o E2E do `Clipping_2026` operacional passar.


## Atualização do workbook operacional

O módulo `src/operational_workbook.py` atualiza um workbook existente sem reconstruir o pacote inteiro:

- valida o cabeçalho de nove colunas da aba mensal;
- lê links existentes, inclusive hyperlinks externos OOXML;
- deduplica por URL canônica entre as abas mensais;
- anexa somente linhas `include` completas;
- copia os identificadores de estilo da última linha existente;
- atualiza `dimension`, `autoFilter` e referência de tabela quando presentes;
- grava hyperlink externo para a nova coluna `LINK`;
- em replay sem novidade, devolve exatamente os mesmos bytes.

A entrada one-shot é:

`python scripts/append_operational_workbook.py --once --workbook Clipping_2026.xlsx --collector data/private/knewin-fecap-items.json --output Clipping_2026.validado.xlsx`

`--in-place` existe, mas só deve ser usado depois de comprovar a identidade do workbook operacional atual. Até lá, a validação usa cópia controlada.
