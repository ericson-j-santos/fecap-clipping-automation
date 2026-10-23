# Governança da branch `main`

## Estado atual: leitura independente em 2026-10-23

A API do GitHub confirma a **configuração ativa** de proteção na `main`. Isso altera o estado observado em setembro, mas **não comprova sozinho o E2E administrativo**.

| Verificação | Resultado observado |
| --- | --- |
| Repositório/branch | `ericson-j-santos/fecap-clipping-automation@main` |
| HEAD | `3343684a788404010ade1540662a8f8d158ef73a` |
| API de branch | `protected=true` |
| Ruleset | `main-protection`, ID `24303428`, `enforcement=active`, alvo `~DEFAULT_BRANCH` |
| Exclusão e force-push | Regras `deletion` e `non_fast_forward` configuradas |
| Histórico linear | Regra `required_linear_history` configurada |
| Revisão por PR | Regra `pull_request`; `required_approving_review_count=0`; `dismiss_stale_reviews_on_push=true` |
| Check obrigatório | `required_status_checks`: `tests`; `strict_required_status_checks_policy=true` |
| Bypass | `bypass_actors=[]`; `current_user_can_bypass=never` |
| CI na main | Run [37982728054](https://github.com/ericson-j-santos/fecap-clipping-automation/actions/runs/37982728054), job `tests` concluído com sucesso no mesmo HEAD; etapas executadas |

Fontes: [branch](https://api.github.com/repos/ericson-j-santos/fecap-clipping-automation/branches/main) e [ruleset 24303428](https://api.github.com/repos/ericson-j-santos/fecap-clipping-automation/rulesets/24303428).

**Limite da evidência:** a API comprova a configuração; o teste negativo de rejeição de push direto não foi executado. Não simular rejeição efetuando uma escrita insegura na `main`. A issue [#51](https://github.com/ericson-j-santos/fecap-clipping-automation/issues/51) permanece aberta até os controles faltantes serem comprovados.

## Histórico anterior à ativação (2026-09-20)

Consulta à API do GitHub em 2026-09-20:

| Campo | Valor |
| --- | --- |
| Repositório | `ericson-j-santos/fecap-clipping-automation` |
| Branch padrão | `main` |
| SHA | `daf69d58b48b8a74f74fc0bfca88aca748f1cf1a` |
| `protected` | `false` |

Naquele momento, sem proteção efetiva, o rótulo `draft`, o texto "NUNCA MERGEAR" e o CI verde eram **sinalização**, não barreira. Esse diagnóstico é histórico e não representa o estado atual descrito acima.

## Contrato de configuração do ruleset

Os itens abaixo correspondem à configuração alvo. Em 2026-10-23, os parâmetros correspondentes foram confirmados na API do ruleset ativo. Não recriar nem alterar o ruleset somente para repetir a verificação.

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

## Executor administrativo histórico (não reexecutar sem preflight)

Alteração de ruleset exige permissão administrativa e autorização específica. A execução não faz parte do CI normal e não pode ser disparada por parâmetros livres.

O repositório mantém um runner governado histórico para a ativação inicial; **seu pin de SHA não corresponde mais à `main` atual**. Não tentar reaplicar a configuração já ativa:

- `scripts/configure_fecap_main_protection_risk3.py`: cadastra temporariamente a ação
  `fecap.main-protection.dev` no Owner Risk3 Gateway local;
- `scripts/run_fecap_main_protection_local.py`: opera somente
  `ericson-j-santos/fecap-clipping-automation@main`, ruleset `main-protection` e check `tests`;
- host permitido: `Noteri`;
- SHA alvo histórico do runner: `ad154563e9843ce88810e7826f6547f4da889775` (divergente do HEAD atual);
- source SHA validado do PR #60: `9d3d6afbd0f147057a21a7c93927b34ec2a7aa48`;
- o runner falha fechado se SHA, ancestralidade, check, ruleset ou host divergirem;
- após a escrita, relê branch e ruleset e exige `protected=true` sem alterar o SHA da branch.

O CI valida somente o contrato do runner. A mutação administrativa continua fora do CI e a issue
só pode ser concluída após o E2E administrativo, incluindo o controle negativo de push direto.

## Critério de conclusão da issue #51

1. **Comprovado em 2026-10-23:** a API de branch retorna `protected=true` e o ruleset ativo contém os controles requeridos, sem bypass.
2. **Pendente:** validar uma tentativa controlada de push direto rejeitada pelo servidor, sem deixar mutação indevida na branch protegida.
3. **Pendente de validação específica:** confirmar que uma PR normal continua mergeável com o check `tests` executado e aprovado no HEAD corrente (esta atualização documental pode ser usada como controle positivo após seu próprio CI).
4. **Não obrigatório:** o workflow manual `Knewin Live E2E` permanece fora dos checks de proteção.

Até os itens 2 e 3 serem comprovados, manter a issue aberta e não tratar `protected=true` como conclusão funcional.


## Auditoria one-shot automatizada

A verificação de estado pode ser executada sem alterar qualquer configuração administrativa:

`python scripts/audit_main_governance.py`

Quando a branch estiver desprotegida, o resultado esperado é `status=BLOCKED` e código de saída 50. Com `protected=true`, o auditor retorna `status=PASS` e código 0 **apenas para o critério `branch_protected_flag`**; isso não atesta sozinho os outros controles da issue.

O auditor:

- consulta somente `GET /repos/{owner}/{repo}/branches/main`;
- não usa token para este repositório público;
- não tenta criar/editar ruleset;
- grava somente evidência sanitizada em `evidence/private/main-governance-audit.json`;
- mantém `scheduled=false` e `production_enabled=false`;
- não considera `protected=true` suficiente, sozinho, para fechar a issue: o controle negativo de push direto e o PR normal ainda devem ser validados.

Para validar somente o contrato sem rede:

`python scripts/audit_main_governance.py --check`
