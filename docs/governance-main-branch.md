# Governança da branch `main`

## Estado evidenciado

Consulta à API do GitHub em 2026-09-20:

| Campo | Valor |
| --- | --- |
| Repositório | `ericson-j-santos/fecap-clipping-automation` |
| Branch padrão | `main` |
| SHA | `daf69d58b48b8a74f74fc0bfca88aca748f1cf1a` |
| `protected` | `false` |

Sem proteção efetiva, o rótulo `draft`, o texto "NUNCA MERGEAR" e o CI verde são **sinalização**,
não barreira. Um push direto ou um merge manual contorna integralmente o fluxo de revisão.

Isto é um bloqueio de governança para enforcement, conforme `rules/github-workflow.md` da fonte
canônica de regras operacionais.

## Configuração alvo

Aplicar em **Settings → Rules → Rulesets → New branch ruleset**, com `Enforcement status: Active`.

| Item | Valor |
| --- | --- |
| Nome | `main-protection` |
| Target branches | `Default branch` |
| Restrict deletions | habilitado |
| Block force pushes | habilitado |
| Require linear history | habilitado |
| Require a pull request before merging | habilitado |
| Required approvals | `0` (repositório de um mantenedor; elevar para `1` ao entrar colaborador) |
| Dismiss stale approvals on push | habilitado |
| Require status checks to pass | habilitado |
| Required check | `tests` (job do workflow `CI` em `.github/workflows/ci.yml`) |
| Require branches to be up to date | habilitado |

Bypass list: vazia. Um mantenedor com bypass reintroduz exatamente o risco que o ruleset remove.

## Por que `tests` é o check correto

`.github/workflows/ci.yml` define um único job, `tests`, que roda em `pull_request` e cobre
contrato do Excel determinístico, publicadores OneDrive e SharePoint, pipeline Pareto one-shot,
sondas Knewin e o E2E público determinístico. É o único check obrigatório necessário hoje.

O workflow `Knewin Live E2E` é `workflow_dispatch` e depende de credencial externa; **não** deve
entrar como check obrigatório.

## Executor

Alteração de ruleset exige permissão administrativa no repositório e não é coberta pelas
ferramentas disponíveis à sessão automatizada. É **ação humana** no painel do GitHub.

## Critério de conclusão

`GET /repos/ericson-j-santos/fecap-clipping-automation/branches/main` retorna `protected: true`,
e uma tentativa controlada de push direto em `main` é rejeitada pelo servidor.
