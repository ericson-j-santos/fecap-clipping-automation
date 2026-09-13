# Validação de reutilização da sessão Knewin

A sonda exige confirmação humana da primeira tela autenticada e não considera cookies isolados como prova suficiente.

Critério de aceite:
- primeira sessão com `auth_mode` diferente de `unknown`;
- URL inicial não pode parecer login/SSO;
- primeiro contexto é fechado;
- novo contexto usa o mesmo perfil persistido;
- nova navegação deve retornar à mesma origem e rota autenticada;
- redirecionamento para login reprova;
- segunda sessão deve continuar com `auth_mode` conhecido;
- `session_reused=true` e `secrets_captured=false` são obrigatórios.

## Inventário de rede sanitizado

Durante a validação, a sonda observa respostas JSON para descobrir quais serviços o portal utiliza. A evidência permite apenas:
- host;
- SHA-256 da origem + caminho, sem expor o caminho em texto;
- método HTTP;
- status HTTP;
- tipo MIME normalizado;
- indicador `is_json`;
- `secrets_captured=false`.

A evidência nunca grava URL completa, query string, parâmetros, cabeçalhos, cookies, Authorization, tokens, corpo de requisição ou corpo de resposta. O inventário é deduplicado, ordenado deterministicamente e limitado a 250 endpoints JSON; `truncated=true` informa quando o limite foi atingido.

A reutilização do portal web não implica que a sessão seja aceita pela Monitoring API v3. Esse uso exige validação separada e não substitui a credencial oficial documentada.
