# Validação do destino SharePoint — Issue #43

Este documento registra o estado evidenciado do destino SharePoint adicional do clipping FECAP.
O pipeline principal permanece independente:

`Knewin -> classificação/idempotência -> Excel determinístico -> OneDrive`.

Nenhum token, cookie, credencial ou segredo é registrado aqui.

## Destino validado

| Campo | Valor evidenciado |
| --- | --- |
| Host | `tieri659.sharepoint.com` |
| Site | raiz (`/`) |
| Biblioteca | `Documentos` |
| Pasta | `FECAP Clipping - Homologacao 2026` |
| Arquivo canônico | `fecap-clipping-homologacao-f23f830a5ddd.xlsx` |
| SHA-256 lógico de origem | `f23f830a5ddd4ad4ca3d57adc4dd2174e2d347cefa2a20512ff8263683e339af` |
| Estado operacional | destino adicional, fora do caminho crítico |
| Agendamento | desabilitado |
| Produção | desabilitada |

## Leitura independente do artefato remoto

Em 2026-09-20, o arquivo foi relido pelo conector SharePoint como XLSX bruto e inspecionado
independentemente.

Conteúdo funcional confirmado:

- cabeçalho mensal: `DATA | MÍDIA | VEÍCULO | TIER | UNID. NEGÓCIO | FONTE | ASSUNTO | LINK`;
- 10 itens classificados;
- 3 itens publicados nas abas mensais;
- 6 itens na aba `Revisao`;
- 1 item excluído;
- contrato `excel-homologation/1.0.0`.

O arquivo remoto possui 21.988 bytes. O SHA-256 dos bytes baixados é
`60af1e094dd92142a51f92d18ccc014ea7df8b54095f62c2384c28c0eac656c4`.
Esse hash físico difere do SHA lógico de origem incorporado ao nome do arquivo; a validação
de idempotência usa o nome determinístico derivado do artefato de origem e a leitura
estrutural independente do workbook remoto.

## Replay / controle contra falso positivo

A segunda passagem foi revalidada em 2026-09-20:

1. a pasta foi listada antes da tentativa;
2. havia exatamente um item chamado
   `fecap-clipping-homologacao-f23f830a5ddd.xlsx`;
3. uma tentativa controlada de upload do mesmo nome com
   `conflict_behavior=fail` retornou HTTP 409 / `nameAlreadyExists`;
4. a pasta foi relida e continuou contendo exatamente um item com o nome canônico;
5. o histórico do item continuou contendo somente a versão `1.0`, com 21.988 bytes;
6. datas de criação e modificação permaneceram `2026-09-19T23:14:08Z`.

Conclusão: o replay não criou duplicata nem nova versão e não sobrescreveu o workbook.

## Critério da Issue #43

Atendido. O SharePoint foi validado como destino adicional com descoberta inequívoca,
artefato remoto relido, replay idempotente e controle negativo independente.

Mantêm-se obrigatórios:

- `scheduled=false`;
- `production_enabled=false`;
- `sharepoint_in_critical_path=false`;
- ausência de segredos/credenciais na evidência.
