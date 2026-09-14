# FECAP Clipping Automation

Projeto isolado do ReqSys para automatizar clipping FECAP a partir de fontes de notícias, começando pela rotina observada no Knewin.

## Estado
- núcleo de classificação: implementado;
- idempotência SHA-256: implementada;
- fila de revisão: implementada;
- E2E com notícias públicas reais + SQLite de homologação: aprovado;
- sonda de sessão e inventário sanitizado de endpoints JSON: implementados;
- templates de rota com identificadores mascarados: implementados;
- jornada guiada e ranking de endpoints candidatos: implementados;
- esquema estrutural das respostas JSON sem valores: implementado;
- plano do coletor vinculado ao endpoint e aos esquemas observados por SHA-256: implementado;
- sonda automática para `https://news.knewin.com/#/login`: implementada;
- coleta autenticada de notícias no portal Knewin: pendente de evidência real no desktop/notebook pessoal;
- Excel/SharePoint de homologação: pendente.

## Regra inicial
- `include`: porta-voz/professor/coordenador da FECAP participa editorialmente;
- `exclude`: FECAP aparece apenas como formação/currículo incidental;
- `review`: existe referência real à FECAP, mas sem contexto suficiente para decisão automática.

## Uso local portátil

1. Copie/baixe este repositório para o computador de trabalho.
2. Use Python 3.11 ou superior; o CI usa Python 3.12.
3. Prepare o ambiente em um comando:
   `python scripts/setup_local.py`
4. Execute o E2E público:
   `python tests/e2e_public_news.py`
5. Inicie a sonda autenticada automática no portal correto do Knewin News:
   `python scripts/probe_knewin_news.py`
6. Faça somente o login humano quando solicitado pelo portal. A sonda espera até 10 minutos, detecta a saída de `#/login` e tenta localizar de forma fail-closed a área de clipping/notícias e o campo de busca.
7. Classifique as rotas e esquemas sanitizados observados:
   `python scripts/analyze_knewin_inventory.py`
8. Gere o plano fail-closed do coletor a partir do endpoint e dos esquemas realmente observados:
   `python scripts/prepare_knewin_collector.py`

Para apenas diagnosticar sem instalar dependências:

`python scripts/setup_local.py --check-only`

Para preparar sem instalar o Chromium:

`python scripts/setup_local.py --skip-browser`

Não copie perfil Chromium, cookies, tokens, `localStorage`, `sessionStorage`, arquivos de `evidence/private` ou chaves da API Knewin entre computadores.

A sonda Knewin grava em `evidence/private/knewin-auth-probe.json` somente metadados sanitizados. Para respostas JSON de até 1 MiB, o corpo pode ser inspecionado em memória exclusivamente para extrair nomes estruturais de campos e tipos (`object`, `array`, `string`, `number`, etc.); valores escalares nunca são persistidos. Campos com nomes dinâmicos/inseguros são substituídos por hash. Respostas de login/SSO são excluídas dessa inspeção.

O analisador gera `evidence/private/knewin-endpoint-candidates.json` associando cada candidato às variantes estruturais observadas. `prepare_knewin_collector.py` não acessa a rede e recusa descoberta sem `PASS`, inventários truncados, rota de autenticação, host fora do contexto Knewin, método/status não permitidos, esquema ausente/adulterado ou qualquer evidência sem `values_persisted=false` e `secrets_captured=false`. Quando aprovado, gera `evidence/private/knewin-collector-plan.json` com `network_enabled=false` e `evidence_binding_sha256` determinístico.

## Pacote portátil

Gere um ZIP seguro com somente código, configuração e testes:

`python scripts/build_portable.py`

Saída padrão:

`dist/fecap-clipping-portable.zip`

O ZIP contém `PORTABLE-MANIFEST.json` com tamanho e SHA-256 de cada arquivo e exclui deliberadamente sessão Knewin e evidências privadas. O CI também publica esse ZIP como artefato `fecap-clipping-portable`.

## Executar
`python tests/e2e_public_news.py`

## Evidência
`evidence/e2e-public-real-news.json`
