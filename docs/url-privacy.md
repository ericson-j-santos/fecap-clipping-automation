# Privacidade das URLs de notícias

`canonical_url` rejeita URLs HTTP/HTTPS que contenham usuário, senha ou
separador de credenciais vazio na autoridade da URL. A rejeição usa
`ValueError` com mensagem fixa, sem repetir a URL recebida. Erros do parser
também são normalizados sem mostrar a autoridade original.

A rotina não remove credenciais para tentar acessar outra representação do
recurso: ela interrompe esse caminho antes da geração da chave ou da gravação
por `persist`. URLs comuns continuam com a mesma normalização e as mesmas
chaves de idempotência. O caractere `@` no caminho ou na consulta não é tratado
como credencial.

## Validação

`tests/test_clipping_url_security.py` cobre variantes de credenciais,
mensagens de erro, regressão de URLs válidas, classificação e persistência em
SQLite temporário. Uma segunda conexão somente leitura verifica os registros.
Entradas rejeitadas e seu replay não alteram os bytes do banco; links válidos
mantêm replay sem duplicação em `clipping` e `review_queue`. A suíte roda no CI
existente, sem rede ou dependências adicionais.

## Limites

Esta prevenção vale para novas chamadas que passam pelo núcleo validado.
Não remove dados antigos, não varre históricos, não sanitiza títulos/textos
ou todos os possíveis tokens em query strings e não comprova ausência de
credenciais em outras etapas do coletor. Não houve acesso a credenciais reais,
coleta autenticada Knewin, publicação externa ou implantação.
