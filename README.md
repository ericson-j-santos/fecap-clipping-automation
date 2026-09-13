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
- plano do coletor vinculado à evidência por SHA-256: implementado;
- coleta autenticada de notícias no portal Knewin: pendente de evidência real e validação do endpoint;
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
5. Inicie a sonda autenticada:
   `python scripts/probe_knewin_session.py`
6. Após autenticar, navegue até a área real de clipping/notícias, execute uma consulta conhecida e confirme no terminal quando os resultados estiverem carregados.
7. Classifique as rotas sanitizadas observadas:
   `python scripts/analyze_knewin_inventory.py`
8. Gere o plano fail-closed do coletor a partir do endpoint realmente observado:
   `python scripts/prepare_knewin_collector.py`

Para apenas diagnosticar sem instalar dependências:

`python scripts/setup_local.py --check-only`

Para preparar sem instalar o Chromium:

`python scripts/setup_local.py --skip-browser`

Não copie perfil Chromium, cookies, tokens, `localStorage`, `sessionStorage`, arquivos de `evidence/private` ou chaves da API Knewin entre computadores.

A sonda Knewin grava em `evidence/private/knewin-auth-probe.json` apenas metadados sanitizados. O inventário de rede mantém host, template de rota mascarado, hash da rota, método, status e tipo MIME de respostas JSON; não grava URL completa, query string, cabeçalhos nem corpos. O analisador gera `evidence/private/knewin-endpoint-candidates.json` apenas a partir desses metadados.

`prepare_knewin_collector.py` não acessa a rede. Ele recusa evidência sem `PASS`, inventário truncado, rotas de autenticação, host fora do contexto Knewin, método não permitido, status não-2xx ou qualquer registro sem `secrets_captured=false`. Quando aprovado, gera `evidence/private/knewin-collector-plan.json` com `network_enabled=false` e um `evidence_binding_sha256` determinístico. A rede só deve ser habilitada em incremento posterior, depois da validação real do endpoint e do esquema de resposta.

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
