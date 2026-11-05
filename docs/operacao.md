# Guia de operação

Detalhes de execução, configuração e comportamento do Worker que não cabem no README.

## Migrations

As migrations rodam no host, com `uv run alembic ...`. As imagens `api` e `worker` copiam só `src/`: não têm `alembic.ini` nem `migrations/`, e a role usada nos contêineres não tem permissão de DDL. Por isso `docker compose exec api alembic ...` falha com `No 'script_location' key found`, o que é esperado.

Uma `DATABASE_URL` definida na sessão do shell tem precedência sobre o `.env` e pode apontar o Alembic para outro banco (por exemplo, `mpi_test`). No PowerShell, para conferir a revisão ignorando a variável da sessão:

```powershell
& { $s = $env:DATABASE_URL; Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
    try { uv run --no-sync alembic current; uv run --no-sync alembic heads } finally { if ($null -ne $s) { $env:DATABASE_URL = $s } } }
```

## Contêineres

As imagens embutem o código (`COPY src/`, sem bind mount). Toda mudança em `src/` exige `docker compose build api worker` e a recriação dos contêineres. Aplique a migration antes de subir o código novo. Mudar só o `.env` exige apenas recriar o serviço, por exemplo `docker compose up -d --force-recreate --no-deps worker`.

`api` e `worker` não usam `env_file`: recebem só as variáveis listadas no `docker-compose.yml`. A senha do superusuário do Postgres não chega a nenhum dos dois, e as credenciais da Cloudflare chegam só ao Worker. O Compose também define `mem_limit`, `cpus` e `pids_limit`, ajustáveis por `API_MEM_LIMIT`, `API_CPUS`, `WORKER_MEM_LIMIT` e `WORKER_CPUS`.

Não compartilhe a saída de `docker compose config` nem de `docker inspect`: elas mostram os valores das variáveis.

## Roles do PostgreSQL

| Role | Uso |
|---|---|
| `POSTGRES_USER` | Administração: migrations, backup, restore e manutenção. Nunca usada pela API nem pelo Worker. |
| `mpi_app` | Execução: só `SELECT`, `INSERT`, `UPDATE` e `DELETE` nas tabelas da aplicação, sem `SUPERUSER`, `CREATEDB` ou `CREATEROLE`. |

Depois de definir `POSTGRES_APP_PASSWORD` no `.env`, com o Postgres do Compose no ar, crie ou atualize a role:

```bash
python scripts/setup_postgres_app_role.py
```

O script é idempotente (serve também para rotacionar a senha) e funciona em PowerShell, cmd ou shell Unix.

## Backup e restore

Procedimento manual, não agendado:

```bash
scripts/backup_postgres.sh                          # gera backups/<POSTGRES_DB>_<timestamp>.dump
scripts/restore_postgres.sh backups/arquivo.dump    # restaura e pede confirmação
```

`pg_dump` e `pg_restore` rodam dentro do contêiner `postgres`, então o host não precisa do cliente do Postgres, e a senha não aparece em `ps`, em log ou em arquivo. O restore usa `--clean --if-exists` e recria os objetos do banco alvo, por isso pede o nome do banco como confirmação. A pasta `backups/` é ignorada pelo Git porque os dumps contêm dados reais.

## Worker

### Prazos e recuperação

- Cada job tem prazo máximo de `WORKER_PRAZO_MAXIMO_JOB_SEGUNDOS` (padrão 420 s), que precisa ser menor que `WORKER_IDADE_MAXIMA_PRESOS_SEGUNDOS`.
- Um job em `em_processamento` há mais tempo que `WORKER_IDADE_MAXIMA_PRESOS_SEGUNDOS` volta para `pendente`, na inicialização e periodicamente durante o loop.
- O resultado só é gravado se o Worker ainda for o dono da execução (`UPDATE` condicional por status e `inicio`).
- Depois de `WORKER_TENTATIVAS_MAXIMAS` (padrão 3) reivindicações, um job que continua falhando termina em `erro`.
- `erro` e `concluido` são estados finais. Uma nova tentativa do aluno é sempre um novo `POST /api/v1/processamentos`.

### Falhas transitórias do Gemini

Respostas 503, 429 ou estouro do tempo total, depois das repetições internas do SDK, devolvem o job a `pendente` com espera gravada em `processamento.disponivel_em`. A espera é `WORKER_REPETICAO_ATRASO_BASE_SEGUNDOS` (30 s) × 2^(n−1), com teto em `WORKER_REPETICAO_ATRASO_MAXIMO_SEGUNDOS` (300 s) e jitter que só reduz o valor. Com os padrões, o pior caso de espera é 90 s. Erros de extração, de montagem do PDF, de credencial ou de Storage não são repetidos.

### Etapas locais do pipeline

A extração do PDF e a montagem do PDF final são trabalho de CPU e têm limites próprios, separados do timeout do Gemini (`GEMINI_TIMEOUT_SEGUNDOS`, 5 s por tentativa; `GEMINI_TIMEOUT_TOTAL_SEGUNDOS`, 45 s no total):

| Variável | Padrão | Observação |
|---|---|---|
| `PIPELINE_TIMEOUT_EXTRACAO_SEGUNDOS` | 30 s | PDFs com dezenas de páginas e muitas imagens levaram de 41 a 54 s no contêiner e pedem cerca de 90 s. |
| `PIPELINE_TIMEOUT_PDF_SEGUNDOS` | 60 s | Montagem do PDF final. |

Estourar uma dessas etapas encerra o job em `erro`, sem repetir a chamada paga ao modelo. A soma dos piores casos de uma execução precisa caber no prazo do job, e uma configuração que passe dele é recusada na inicialização do Worker. Com os padrões, incluindo uma chamada de complementação, a soma é 180 s com imagens desligadas e 390 s com imagens ligadas. Download, upload e banco não entram na conta e usam a folga.

Limite conhecido: estourar o tempo de uma etapa local encerra só a espera. A thread de extração ou de montagem não pode ser interrompida em Python e segue até terminar; a contenção fica a cargo dos limites do contêiner.

### Qualidade da reescrita

O prompt pede um material de estudo completo, com exemplos resolvidos, aplicações, erros frequentes e exercícios quando fizer sentido, e explica como adaptar cada dimensão do perfil. A resposta é considerada insuficiente quando:

- vem marcada como incompleta;
- fica abaixo de `GEMINI_REESCRITA_PROPORCAO_MINIMA` (padrão 0,8) do tamanho do original;
- perde mais de 40% dos conceitos essenciais do original;
- em originais com 2.000 caracteres ou mais, tem menos de 2 dos 3 elementos pedagógicos (exemplos, prática, erros comuns).

Originais com menos de 600 caracteres não são avaliados. Nesses casos o Worker faz até `GEMINI_REESCRITA_COMPLEMENTO_TENTATIVAS` chamadas extras (padrão 1; 0 desliga) e fica com a maior resposta. As heurísticas não verificam fidelidade semântica.

## Ilustrações geradas

Desligadas por padrão. Com `IMAGENS_GERADAS_HABILITADAS=true`, o Gemini marca até `IMAGENS_MAX_POR_MATERIAL` conceitos no texto e o Worker gera as imagens na Cloudflare Workers AI. Cada uma entra no PDF como figura com legenda numerada, logo depois do parágrafo que a explica. A imagem (PNG ou JPEG, validada por assinatura, estrutura e tamanho máximo de 10 MB) não é guardada à parte: só o PDF final vai para o Storage.

| Variável | Padrão | Observação |
|---|---|---|
| `IMAGENS_GERADAS_HABILITADAS` | `false` | Liga o recurso. |
| `IMAGENS_PROVEDOR` | `cloudflare` | Único valor aceito. |
| `IMAGENS_MAX_POR_MATERIAL` | `1` | De 1 a 5. |
| `IMAGENS_TIMEOUT_TOTAL_SEGUNDOS` | `120` | Teto de uma imagem, com repetição. |
| `IMAGENS_ORCAMENTO_TOTAL_SEGUNDOS` | `150` | Orçamento de todas as imagens de um material (10 a 600). |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_IMAGE_MODEL` | vazias | Obrigatórias com o recurso ligado. O modelo segue o formato `@cf/<autor>/<modelo>`. |
| `CLOUDFLARE_IMAGE_STEPS` | `4` | Passos de difusão, de 1 a 8. |
| `CLOUDFLARE_IMAGE_TIMEOUT_SEGUNDOS` | `60` | Tempo-limite de uma tentativa (máximo 300). |

O Worker chama `POST https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_IMAGE_MODEL}`, com host fixo no código e sem seguir redirecionamentos. O token precisa das permissões `Workers AI: Read` e `Workers AI: Edit`. O modelo validado é o `@cf/black-forest-labs/flux-1-schnell`.

A cota gratuita da Cloudflare era de 10.000 Neurons por dia quando a integração foi feita, o que dá algo entre 170 e 230 imagens com 4 passos. Acima dela as chamadas falham no plano Free e são cobradas no Workers Paid. Confira os valores atuais no painel da Cloudflare e os termos de uso do modelo antes de usar em produção.

Uma falha de imagem nunca derruba o material: o PDF sai só com o texto e o job termina `concluido`. Se a montagem com a imagem falhar, o Worker refaz o PDF sem ela, sem nova chamada paga. Nada na API indica que a ilustração foi omitida; o motivo aparece no log do Worker (`Imagem não gerada (conceito=..., motivo=...)`). O adaptador não repete em 429, em outros 4xx nem em timeout depois do envio; repete no máximo uma vez em falha de conexão ou 5xx.

As imagens do PDF original não entram no material por padrão. `PDF_ANEXAR_IMAGENS_ORIGINAIS=true` as anexa ao final do documento.

## Contrato de `POST /api/v1/alunos`

Para uma matrícula já cadastrada, a resposta é `200` com somente `id` e `grupo_experimental`. Nome e e-mail saem apenas em `GET /api/v1/alunos/{id}`. O cadastro novo (`201`) devolve o registro completo.

A autorização por aluno é responsabilidade do plugin do Moodle: a API confia no token de serviço. Por isso o token deve trafegar só por TLS, ficar apenas no servidor do plugin e ser rotacionado.

## Limites de entrada

- Corpo das requisições: `MATERIAL_TAMANHO_MAXIMO_BYTES` (mais 256 KiB de multipart) no upload e `CORPO_JSON_TAMANHO_MAXIMO_BYTES` (1 MiB) nas demais rotas.
- `PDF_PAGINAS_MAXIMAS` (padrão 100), verificado no upload e de novo no pipeline.
- `PDF_PIXELS_MAXIMOS_POR_IMAGEM` (padrão 25 milhões); imagens maiores são descartadas.
- Nome, e-mail e matrícula seguem os limites das colunas; `acao` até 100 caracteres e `descricao` até 2.000 no log; `tempo_leitura_incremento_segundos` entre 0 e 86.400; título do material até 255 caracteres.
- O `resumo` devolvido pela API é texto puro.
- Rate limit configurável em `RATE_LIMIT_PROCESSAMENTOS_POR_MINUTO`, `RATE_LIMIT_MATERIAIS_POR_MINUTO` e `RATE_LIMIT_PERFIS_POR_MINUTO`.

O middleware de limite de corpo não substitui o limite de corpo e de tempo do proxy reverso.
