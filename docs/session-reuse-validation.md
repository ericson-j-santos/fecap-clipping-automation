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
- evidência grava somente modo, hosts e hashes de localização; nunca valores de token/cookie/storage;
- `session_reused=true` e `secrets_captured=false` são obrigatórios.

A reutilização do portal web não implica que a sessão seja aceita pela Monitoring API v3. Esse uso exige validação separada e não substitui a credencial oficial documentada.
