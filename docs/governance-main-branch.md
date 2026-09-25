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

Alteração de ruleset exige permissão administrativa e autorização específica. A execução não faz
parte do CI normal e não pode ser disparada por parâmetros livres.

O repositório possui um runner governado e fixo para esta única operação:

- `scripts/configure_fecap_main_protection_risk3.py`: cadastra temporariamente a ação
  `fecap.main-protection.dev` no Owner Risk3 Gateway local;
- `scripts/run_fecap_main_protection_local.py`: opera somente
  `ericson-j-santos/fecap-clipping-automation@main`, ruleset `main-protection` e check `tests`;
- host permitido: `Noteri`;
- SHA alvo atual: `ad154563e9843ce88810e7826f6547f4da889775`;
- source SHA validado do PR #60: `9d3d6afbd0f147057a21a7c93927b34ec2a7aa48`;
- o runner falha fechado se SHA, ancestralidade, check, ruleset ou host divergirem;
- após a escrita, relê branch e ruleset e exige `protected=true` sem alterar o SHA da branch.

O CI valida somente o contrato do runner. A mutação administrativa continua fora do CI e a issue
só pode ser concluída após o E2E administrativo, incluindo o controle negativo de push direto.

## Critério de conclusão

`GET /repos/ericson-j-santos/fecap-clipping-automation/branches/main` retorna `protected: true`,
e uma tentativa controlada de push direto em `main` é rejeitada pelo servidor.


## Auditoria one-shot automatizada

A verificação de estado pode ser executada sem alterar qualquer configuração administrativa:

`python scripts/audit_main_governance.py`

Com a `main` ainda desprotegida, o resultado esperado é `status=BLOCKED` e código de saída 50.
Depois da aplicação do ruleset, o mesmo comando deve retornar `status=PASS` e código 0.

O auditor:

- consulta somente `GET /repos/{owner}/{repo}/branches/main`;
- não usa token para este repositório público;
- não tenta criar/editar ruleset;
- grava somente evidência sanitizada em `evidence/private/main-governance-audit.json`;
- mantém `scheduled=false` e `production_enabled=false`;
- não considera `protected=true` suficiente, sozinho, para fechar a issue: o controle negativo de push direto e o PR normal ainda devem ser validados.

Para validar somente o contrato sem rede:

`python scripts/audit_main_governance.py --check`
