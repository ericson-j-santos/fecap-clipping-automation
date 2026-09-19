# Descoberta do destino SharePoint corporativo — Issue #43

Documento de evidência da etapa de descoberta exigida pela issue #43. Registra o que foi
observado por rota suportada, o que ficou bloqueado e qual é a ação objetiva de desbloqueio.

Nenhum token, cookie, credencial ou segredo é registrado aqui. Os identificadores abaixo são
identificadores de recurso do Microsoft Graph, não credenciais.

## Contexto

A publicação SharePoint é **destino adicional**. O pipeline homologado
(`Knewin -> classificação/idempotência -> Excel determinístico -> OneDrive sincronizado`)
permanece concluído e independente desta issue. Falha aqui não altera o estado da #38.

## Rota avaliada

| Rota | Estado | Observação |
| --- | --- | --- |
| Microsoft Graph via conector Microsoft 365 | autenticada, **somente leitura** | permite descoberta; não permite publicação |
| Playwright + sessão humana (`scripts/publish_sharepoint_homologation.py`) | implementada | exige desktop com sessão interativa; não executável em runner remoto |

## Evidência de descoberta (Microsoft Graph, leitura)

Conta autenticada: `ericsonjosedossantos@tieri659.onmicrosoft.com`
Tenant observado: `tieri659.onmicrosoft.com`

Permissões delegadas efetivamente concedidas ao conector:

`Calendars.Read`, `Calendars.Read.Shared`, `Channel.ReadBasic.All`, `ChannelMessage.Read.All`,
`Chat.Read`, `Chat.ReadBasic`, `ChatMember.Read`, `ChatMessage.Read`, `Files.Read`,
`Files.Read.All`, `Mail.Read`, `Mail.Read.Shared`, `Mail.ReadBasic`, `MailboxFolder.Read`,
`MailboxItem.Read`, `OnlineMeetingAiInsight.Read.All`, `OnlineMeetingArtifact.Read.All`,
`OnlineMeetingRecording.Read.All`, `OnlineMeetings.Read`, `OnlineMeetingTranscript.Read.All`,
`Sites.Read.All`, `User.Read`, `User.ReadBasic.All`.

Não há nenhum escopo de escrita (`Files.ReadWrite*`, `Sites.ReadWrite*`, `Sites.Manage.All`).

### Destino localizado

| Campo | Valor observado |
| --- | --- |
| Biblioteca | `Documentos Compartilhados` (site raiz do tenant) |
| Pasta | `FECAP Clipping - Homologacao 2026` |
| `webUrl` | `https://tieri659.sharepoint.com/Documentos Compartilhados/FECAP Clipping - Homologacao 2026` |
| `driveId` | `b!cWhgn8eIOkmGdZI9ddc72NsF7NNRdDBEpFzHxgQ8PrtWYTvSr7hPSavhStah7Z3z` |
| `itemId` | `01JOSXQLKWG3HKGE5NUJF3XUJKDVLX5WAK` |
| `lastModifiedDateTime` | `2026-09-16T13:58:07Z` |

### Estado do conteúdo (leitura independente)

- listagem da pasta pelo `itemId`: sem itens;
- busca por `fecap-clipping-homologacao` no escopo SharePoint: 0 resultados;
- busca por `clipping` restrita à pasta alvo: 0 resultados.

Conclusão: a pasta alvo existe e está vazia. O workbook determinístico
(`workbook_sha256 = f23f830a5ddd4ad4ca3d57adc4dd2174e2d347cefa2a20512ff8263683e339af`,
arquivo determinístico `fecap-clipping-homologacao-f23f830a5ddd.xlsx`) **não está publicado**.

## Bloqueios evidenciados

1. **Escopo insuficiente.** O conector tem apenas leitura. Publicar exige `Files.ReadWrite.All`
   ou `Sites.ReadWrite.All` com consentimento administrativo no tenant.
2. **Tenant não corporativo.** `tieri659.onmicrosoft.com` é um tenant próprio, não o SharePoint
   corporativo da FECAP. Mesmo com escopo de escrita, publicar aqui não satisfaz o critério da #43.
3. **Artefato ausente no ambiente remoto.** O workbook determinístico vive em `data/private/`
   (ignorado pelo Git) e é produzido pelo coletor autenticado no desktop. Sem os bytes exatos não
   é possível comprovar `already_present` sobre o mesmo `workbook_sha256`.

## Estado da issue #43

`bloqueado` — descoberta concluída por rota suportada; publicação e prova de idempotência não executadas.

## Ação objetiva de desbloqueio

Escolher **uma** das rotas:

- **Rota A (corporativa, preferida).** Obter acesso ao tenant SharePoint corporativo da FECAP e
  conceder ao conector, com aprovação administrativa, escopo de escrita mínimo sobre a biblioteca
  alvo. Repetir a descoberta neste documento contra o tenant correto antes de publicar.
- **Rota B (desktop, já implementada).** Executar `scripts/publish_sharepoint_homologation.py` no
  desktop com sessão SharePoint corporativa ativa e o workbook determinístico presente, duas vezes,
  comprovando `uploaded` e depois `already_present` sobre o mesmo `workbook_sha256`.

Em qualquer rota, mantêm-se obrigatórios: `scheduled=false`, `production_enabled=false`,
`credentials_persisted=false`, `secrets_captured=false`.
