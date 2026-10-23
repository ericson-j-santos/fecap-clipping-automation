# Knewin Live E2E — gate de workbook privado (issue #53)

## Estado e critério de aceite

Esta implementação **não declara** Clipping_2026 canônico, credencial Knewin
válida ou E2E live aprovado. O teste determinístico de CI não contata a Knewin.

O aceite terminal exige UMA execução manual em main@SHA, com:
1. Aprovação inequívoca do arquivo operacional original por seu responsável.
2. Leitura de uma cópia no mesmo drive_id/item_id aprovado do SharePoint,
   via Graph em escopo somente leitura e hash SHA-256 físico previamente aprovado.
3. Credencial Knewin válida, mês UTC completo, runner autorizado e custo R$ 0,00.
4. Coleta real Knewin, append positivo somente em cópia, releitura independente
   da saída física e replay byte-idêntico sem linhas adicionais.
5. Run/job do SHA com passos executados e estado terminal: não usar fixture,
   GDELT, log 2xx ou artefato anterior como substituto.

## Provisionamento governado sem inserir workbook no GitHub

A origem do arquivo não é escolhida no dispatch. Configurar um ambiente GitHub
knewin-live-e2e com **required reviewers** e restringir deployments à branch
main protegida; confirmar por leitura administrativa estas proteções ANTES de
habilitar segredos. O nome do ambiente, sozinho, não comprova proteção.

Segredos exclusivos do ambiente, não segredos globais de repositório:

| Secret | Significado |
| --- | --- |
| KNEWIN_API_KEY | Chave Knewin em memória |
| KNEWIN_GRAPH_TENANT_ID | Tenant Entra ID |
| KNEWIN_GRAPH_CLIENT_ID | Identidade do aplicativo de leitura |
| KNEWIN_GRAPH_CLIENT_SECRET | Credencial somente do aplicativo |
| KNEWIN_GRAPH_DRIVE_ID | Drive corporativo autorizado |
| KNEWIN_GRAPH_ITEM_ID | Item exato do arquivo aprovado |
| KNEWIN_GRAPH_DOWNLOAD_HOST | Nome DNS exato do redirect SharePoint (sufixo .sharepoint.com) |
| KNEWIN_APPROVED_WORKBOOK_SHA256 | SHA-256 dos bytes XLSX canônicos aprovados em canal privado |

O aplicativo Graph deve possuir somente Sites.Selected com concessão read
no site específico (ou permissão ainda mais restrita). Não conceder
Files.Read.All ou Sites.Read.All para contornar bloqueio. Verificar que
Microsoft 365/Graph estão disponíveis sem cobrança incremental antes de usar.

Aprovar externamente nome, proprietário, origem, versão, estrutura e integridade
do verdadeiro Clipping_2026, não um arquivo de homologação apenas semelhante.
Mudança legítima do workbook exige nova aprovação do SHA. Nunca enviar chave,
IDs privados, URL assinada, hash de aprovação ou workbook para PR/issue.

## Fluxo real

Workflow exclusivamente workflow_dispatch, ubuntu-latest, Python 3.12,
contents: read e concorrência serial; sem Docker, scheduler ou produção.

1. Preflight: chave, identidade de execução, secrets completos, aprovação SHA
   de 64 hex e host SharePoint exato. Branch fora de main, evento diferente,
   repositório diferente ou SHA inválido bloqueia.
2. Prepare: OAuth Graph em memória, solicitação ao endpoint
   /drives/{drive}/items/{item}/content, suporte a resposta Graph 200 direta
   autenticada OU redirect 302 legado HTTPS ao host exato aprovado,
   download sem repassar header Bearer Graph para SharePoint.
3. Verifica tamanho, SHA-256, ZIP/OOXML, 12 abas mensais e cabeçalho com nove
   colunas. Materializa arquivo privado (0600) em RUNNER_TEMP, fornece
   KNEWIN_WORKBOOK_PATH e arquivos de saída somente aos passos do mesmo job.
4. E2E: valida novamente digest e mês UTC completo ANTES da API Knewin, coleta
   notícia real, append em cópia, replay. Nunca sobrescreve o arquivo corporativo.
5. Verify: relê 3 XLSX físicos, exige origem aprovada, append positivo medido
   pela diferença de linhas, recibo do SHA/correlation_id e replay idêntico.
6. Cleanup: remove pasta privada mesmo se uma etapa falhar. Não publica
   XLSX, coletor, arquivos privados ou artifacts. Log só contém estado sanitizado.

Em redirect de host diferente, digest divergente ou alteração inesperada,
bloquear até nova verificação. Antes do único dispatch confirmar também
que GitHub Actions standard hosted e Graph não gerarão custo incremental.

## Testes e limites

O teste tests/test_knewin_live_workbook.py usa workbook e chave sintéticos,
sem Graph ou Knewin reais. Cobre positivo de preparação/readback, ausência de
chave/path/arquivo/secret, origem não aprovada, hash incorreto, host falso,
OOXML corrompido, branch/evento indevido, replay alterado, falso recibo, falta
de append, inexistência de arquivo e cleanup idempotente.

CI verde comprova o contrato local, nunca coleta real. Gate restante:
aprovar Clipping_2026 canônico, validar identidade/escopo Graph, secrets do
ambiente, proteção de branch e capacidade gratuita. Só então disparar um
único live E2E e auditar seus passos e evidência da releitura física. Issue
#53 fica aberta até essa prova.

## Compatibilidade futura comprovada por aviso oficial (outubro de 2026)

A Microsoft anunciou que a partir de 01/04/2027 iniciará a retirada dos
redirects 302 com URLs preautenticadas de downloads no Graph; a resposta
de conteúdo direta autenticada deve substituir o fluxo antigo. Por isso, o
gate aceita tanto HTTP 200 direto do Graph quanto 302 legado, com testes
sintéticos dos dois fluxos. Não repassa Bearer Graph a outro host, nem aceita
URLs externas sem allowlist explícita. A mudança real no tenant corporativo
continua **não verificada**; esse teste não comprova operação Knewin real.

Aviso oficial:
https://devblogs.microsoft.com/microsoft365dev/pre-authenticated-tempauth-urls-are-retiring-move-to-microsoft-entra-id-tokens-before-april-1-2027/
