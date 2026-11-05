# Segurança

## Como reportar uma vulnerabilidade

Não abra uma issue pública. Use o [reporte privado de vulnerabilidades](https://github.com/JulianaCosta01/api-personalizacao-inteligente/security/advisories/new) do GitHub, descrevendo o problema, como reproduzi-lo e o impacto esperado.

## Modelo de ameaças

O sistema processa PDFs de terceiros, envia conteúdo a um LLM externo e guarda dados acadêmicos de estudantes. As principais superfícies e as mitigações implementadas:

| Superfície | Risco | Mitigação |
|---|---|---|
| Token de serviço | Quem tiver o token age em nome de qualquer aluno | Comparação em tempo constante, rate limiting por token, envio só por TLS e rotação |
| Upload de PDF | Arquivo malicioso, bomba de descompressão, consumo excessivo | Limite de tamanho, de páginas e de pixels por imagem, timeout por etapa e limites de CPU e memória no contêiner |
| Conteúdo do PDF no prompt | Prompt injection via documento | Instrução do sistema separada do conteúdo; o texto extraído nunca é tratado como comando |
| Criação de processamentos | Abuso de custo com chamadas pagas ao LLM | Rate limiting nas rotas de maior custo e repetição limitada a falhas transitórias |
| Recursos de outros alunos | BOLA/IDOR | IDs UUID v4 e checagem de posse por `aluno_id` nas rotas de acesso e de log |
| Arquivos no Storage | Vazamento do material de outro aluno | Entrega só por URL assinada e temporária, nunca pelo caminho do arquivo |
| Renderização do PDF | SSRF a partir de HTML do conteúdo | WeasyPrint sem acesso à rede: só aceita recursos embutidos (`data:`) |
| Dados de estudantes | Exposição indevida (LGPD) | Coleta mínima, logs sem conteúdo do material e sem respostas dos provedores |

## Controles implementados

- Autenticação e limite de corpo aplicados antes de qualquer parse da requisição.
- Validação estrita de entrada com Pydantic; os schemas de escrita recusam campos desconhecidos.
- Security headers em todas as respostas e CORS configurado por ambiente.
- Documentação interativa (`/docs`, `/redoc`, `/openapi.json`) desligada fora de `development`.
- Segredos lidos só do ambiente, nunca registrados em log nem versionados.
- Role de banco de privilégio mínimo para API e Worker, sem permissão de DDL.
- Erros com mensagens genéricas; detalhes técnicos ficam só no log estruturado.

## Limitações conhecidas

- Há um único token de serviço por instalação. A autorização por aluno é responsabilidade do plugin do Moodle; antes de uso em produção, vale avaliar assinatura por requisição.
- O limite de tempo das etapas locais do pipeline encerra a espera, mas a thread de extração ou de renderização segue até terminar. A contenção fica a cargo dos limites do contêiner.
- O middleware de limite de corpo não substitui os limites de corpo e de tempo do proxy reverso.
