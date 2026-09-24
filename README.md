# FECAP Clipping Automation

Projeto isolado do ReqSys para automatizar clipping FECAP a partir de fontes de notícias, começando pela rotina observada no Knewin.

## Estado
- núcleo de classificação: implementado;
- idempotência SHA-256: implementada;
- fila de revisão: implementada;
- E2E com notícias públicas reais + SQLite de homologação: aprovado;
- fallback zero-custo GDELT DOC 2.0: implementado para janela explícita, sem chave e com saída compatível com o mesmo Excel; itens sem contexto suficiente permanecem em `Revisao`;
- evidência live GDELT: vínculo fail-closed entre Git SHA/run, `correlation_id`, SHA-256 do coletor e do workbook, reconstrução determinística e controle negativo;
- sonda de sessão e inventário sanitizado de endpoints JSON: implementados;
- templates de rota com identificadores mascarados: implementados;
- jornada guiada e ranking de endpoints candidatos: implementados;
- esquema estrutural das respostas JSON sem valores: implementado;
- plano do coletor vinculado ao endpoint e aos esquemas observados por SHA-256: implementado;
- sonda automática para `https://news.knewin.com/#/login`: implementada;
- coleta autenticada real no Knewin News: aprovada no desktop pessoal;
- classificação/idempotência sobre lote Knewin real: aprovada;
- Excel local de homologação com contrato de 9 colunas observado no vídeo: implementado e determinístico;
- enriquecimento de TIER/MÍDIA/ORIGEM/ASSUNTO/FONTE/UN. NEG.: fail-closed por regras versionadas; itens sem evidência vão para revisão;
- append no workbook operacional existente: implementado em OOXML, com validação do cabeçalho de 9 colunas e deduplicação global por URL canônica;
- harness E2E mensal operacional: implementado para coleta por período, append em cópia controlada, releitura por SHA-256 e replay byte a byte sem duplicação; a evidência só marca Knewin real quando a coleta não é pulada;
- publicação SharePoint: destino adicional, fora do caminho crítico; site/biblioteca/pasta e workbook canônico validados, com replay sem duplicação (`docs/sharepoint-corporate-discovery.md`);
- governança da branch `main`: sem proteção efetiva; ruleset alvo especificado em `docs/governance-main-branch.md`.

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
6. Faça somente o login humano quando solicitado pelo portal. A sonda espera até 10 minutos e localiza de forma fail-closed a área de clipping/notícias e o campo de busca.
7. Classifique as rotas e esquemas sanitizados observados:
   `python scripts/analyze_knewin_inventory.py`
8. Gere o plano fail-closed do coletor:
   `python scripts/prepare_knewin_collector.py`
9. Após o runtime estar validado, execute uma coleta one-shot. Para reproduzir o recorte mensal do vídeo:
   `python scripts/collect_knewin_publications.py --once --start-date 2026-08-01 --end-date 2026-08-31`

   O coletor reutiliza a requisição autenticada em memória, pagina `/restful/search/publications` até o `count` informado e só então aplica a janela inclusiva por `publishedDate`. Credenciais, headers e corpo bruto da API não são persistidos.

   Se a autenticação Knewin estiver indisponível, use o fallback público sem chave:
   `python scripts/collect_gdelt_publications.py --once --start-date 2026-08-01 --end-date 2026-08-31`

   Em CI, o workflow fornece um `correlation_id` derivado do run e valida o manifesto final com `scripts/validate_gdelt_live_e2e.py`; valores externos de correlação são aceitos somente quando seguem o formato restrito do coletor.

   O fallback consulta o GDELT DOC 2.0 em modo Article List, limita a janela a até 93 dias, deduplica por URL canônica e grava `data/private/gdelt-fecap-items.json` no mesmo contrato `format=1`. Para desambiguar homônimos da sigla, lê no máximo um trecho sanitizado da página pública e confirma a instituição somente por nome institucional conhecido ou porta-voz versionado em `config/people.json`. Homônimos comprovados são excluídos; página inacessível ou identidade incerta vai para `Revisao`. A resposta HTML bruta nunca é persistida.
10. Gere o Excel local de homologação a partir da saída privada do coletor:
    `python scripts/build_homologation_excel.py`
11. Para validar sem gravar o workbook:
    `python scripts/build_homologation_excel.py --dry-run`
12. Quando o `Clipping_2026.xlsx` operacional estiver inequivocamente identificado, valide primeiro em uma cópia:
    `python scripts/append_operational_workbook.py --once --workbook Clipping_2026.xlsx --collector data/private/knewin-fecap-items.json --output Clipping_2026.validado.xlsx`
13. Para fechar o E2E mensal com caso positivo e replay, use o harness one-shot em uma cópia:
    `python scripts/run_monthly_operational_e2e.py --once --start-date 2026-08-01 --end-date 2026-08-31 --workbook Clipping_2026.xlsx --output Clipping_2026.validado.xlsx --allow-human-login`

   A execução grava um `correlation_id`, exige por padrão pelo menos uma nova linha, relê o workbook persistido por SHA-256 e repete a mesma entrada. O replay só passa se não anexar linha adicional e se os bytes permanecerem idênticos. `--skip-collect` existe para teste determinístico com entrada pré-coletada e registra explicitamente `live_knewin_validated=false`.

O contrato do Excel está em `docs/excel-homologation-contract.md`. Para o fluxo-alvo do vídeo, a ordem é `DATA | VEÍCULO | TIER | MÍDIA | ORIGEM | ASSUNTO | FONTE | UN. NEG. | LINK`. As regras ficam em `config/video_enrichment.json`; com `require_complete=true`, qualquer item sem enriquecimento comprovado vai para `Revisao` em vez de receber valor inventado.

### Windows: bootstrap idempotente da sessão Knewin

No PowerShell 5.1+:

`powershell -ExecutionPolicy Bypass -File scripts/knewin-session-capture.ps1`

O wrapper cria um `venv` isolado em `~/.fecap-clipping/venv`, valida `pip`, instala/repara Python 3.12 pelo `winget` somente quando necessário, garante Playwright/Chromium e reutiliza a sonda versionada `scripts/probe_knewin_session.py`. O log de bootstrap é JSONL e fica em `~/.fecap-clipping/evidence/knewin-session-bootstrap.jsonl`.

Para execução por agente/Command Gateway, use a rota Python governada, sem liberar PowerShell genérico:

`python scripts/knewin_session_bootstrap.py --bootstrap-only`

Esse modo valida/cria o venv, garante `pip`, Playwright e Chromium e encerra antes de abrir a autenticação Knewin. Para seguir até a sonda, remova `--bootstrap-only`. O script exige Python 3.11+ já disponível porque o próprio Command Gateway usa Python; quando Python não existir no host, a rota humana PowerShell permanece responsável pelo bootstrap inicial.

Para ambiente sem rede:

`powershell -ExecutionPolicy Bypass -File scripts/knewin-session-capture.ps1 -Offline -Wheelhouse C:\caminho\wheelhouse`

O modo offline nunca chama `winget` nem índice remoto do `pip`; se Python, wheelhouse ou Chromium local estiverem ausentes, encerra com código explícito em vez de tentar uma instalação parcial.

Para apenas diagnosticar sem instalar dependências:

`python scripts/setup_local.py --check-only`

Para preparar sem instalar o Chromium:

`python scripts/setup_local.py --skip-browser`

Não copie perfil Chromium, cookies, tokens, `localStorage`, `sessionStorage`, arquivos de `evidence/private` ou chaves da API Knewin entre computadores.

A sonda Knewin grava em `evidence/private/knewin-auth-probe.json` somente metadados sanitizados. Para respostas JSON de até 1 MiB, o corpo pode ser inspecionado em memória exclusivamente para extrair nomes estruturais de campos e tipos; valores escalares nunca são persistidos. Respostas de login/SSO são excluídas dessa inspeção.

O analisador gera `evidence/private/knewin-endpoint-candidates.json`. `prepare_knewin_collector.py` não acessa a rede e recusa descoberta sem evidência válida. O coletor one-shot mantém produção e agendamento desabilitados. O gerador Excel mantém `external_destination_enabled=false`; destinos externos são tratados por publicadores one-shot separados e continuam fora de produção/agendamento.

## Pacote portátil

Gere um ZIP seguro com somente código, configuração, documentação e testes:

`python scripts/build_portable.py`

Saída padrão:

`dist/fecap-clipping-portable.zip`

O ZIP contém `PORTABLE-MANIFEST.json` com tamanho e SHA-256 de cada arquivo e exclui deliberadamente sessão Knewin, dados privados, workbooks gerados e evidências privadas. O CI também publica esse ZIP como artefato `fecap-clipping-portable`.

## Executar
`python tests/e2e_public_news.py`

## Evidência
- pública/determinística: `evidence/e2e-public-real-news.json`
- privada Knewin/Excel: `evidence/private/` (não versionada)
- GDELT live auditada: `evidence/private/gdelt-live-e2e.json` (artefato efêmero do workflow, não versionado)
