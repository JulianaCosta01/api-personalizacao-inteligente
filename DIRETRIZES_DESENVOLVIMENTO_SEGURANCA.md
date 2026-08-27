# Diretriz Oficial de Desenvolvimento e Segurança do Projeto

> **Status:** vigente a partir de 2026-07-28.
> **Escopo:** todo o sistema de Personalização Inteligente de Materiais Didáticos (MPI) — API, Worker, Pipeline de Personalização e integração com o Plugin Moodle — descrito em `Documento_2_Modelagem_Sistema_v2.docx` e `Documento_3_Especificacao_API_v2.docx`.
> **Aplicação:** obrigatória para qualquer código, endpoint, modelo de dados, prompt de IA ou decisão arquitetural adicionados a partir desta data.

Este documento formaliza o padrão de engenharia sob o qual o projeto passa a ser tratado: não como um protótipo acadêmico isolado, mas como um sistema com potencial real de implantação em produção na UFMA, processando dados de estudantes e integrando um LLM de terceiros (Google Gemini). Toda decisão técnica — arquitetura, biblioteca, endpoint, prompt — deve poder ser justificada tecnicamente; nenhuma tecnologia é escolhida apenas por popularidade.

---

## 1. Princípios gerais

Toda decisão técnica deve priorizar, nesta ordem de atenção (não de exclusão mútua): segurança, escalabilidade, manutenibilidade, performance, clareza arquitetural, baixo acoplamento, alta coesão, testabilidade e documentação consistente.

## 2. Segurança (Security by Design / Secure by Default)

A segurança é parte da arquitetura, não uma camada adicionada depois. Para **cada** funcionalidade nova ou alterada — endpoint, campo, prompt, upload — deve-se avaliar explicitamente, antes de implementar:

- vetores de ataque possíveis;
- risco de exposição de dados (de outro aluno, de outro processamento, do token de serviço);
- risco de escalada de privilégios (ex.: um aluno agindo como outro, um plugin agindo fora do escopo esperado);
- risco de injeção (SQL, NoSQL, path traversal em nomes de arquivo, injeção de prompt);
- risco de enumeração de recursos (IDs sequenciais previsíveis, respostas que confirmam existência de recursos de outros usuários);
- risco de negação de serviço (uploads grandes, processamentos em massa, loops de polling agressivo);
- riscos específicos de processamento de arquivos (PDFs maliciosos, arquivos disfarçados, bombas de descompressão);
- riscos específicos de LLM: Prompt Injection, Prompt Leakage, Jailbreak, abuso de contexto.

Nenhuma funcionalidade é considerada concluída sem essa análise. A pergunta de referência é sempre: **como eu, agindo como atacante, tentaria comprometer isto antes de declará-lo pronto?**

### 2.1 Vetores de ataque específicos deste sistema

Esta seção concretiza o princípio acima para a arquitetura já documentada (Documento 3 v2), evitando que a diretriz fique só no nível abstrato:

| Superfície | Risco concreto | Mitigação exigida |
|---|---|---|
| Token de serviço único por instalação (`Authorization: Bearer`) | Se vazar, qualquer requisição pode agir "como" qualquer `aluno_id` informado no corpo/path — hoje a API confia no `aluno_id` repassado pelo Plugin sem verificação criptográfica adicional | Rotação de token, escopo mínimo, rate limiting por token, e — antes de produção real — reavaliar se o Plugin deve assinar cada requisição por aluno (ver Documento 3 §2.2/§7; hoje mantido simples por decisão de escopo, mas é o ponto de maior risco do sistema e deve ser revisitado quando o Plugin for de fato implementado) |
| Upload de Material Didático (`POST /materiais`) | PDF malicioso: bombas de descompressão, arquivos com extensão forjada, payloads que exploram bibliotecas de parsing (`pymupdf4llm`) | Validar MIME real (não só extensão), limite de tamanho, sandboxing/timeout na conversão, nunca executar conteúdo extraído |
| Conteúdo do PDF injetado no prompt (`rewrite.py`, `assuntos_llm.py`) | **Prompt Injection via documento**: o material didático (fornecido pelo docente, mas potencialmente qualquer PDF) vira parte do prompt enviado ao Gemini; um PDF pode conter instruções adversariais tentando sobrescrever o comportamento do rewrite ou extrair o system prompt | Isolar claramente instrução do sistema vs. conteúdo do usuário no prompt; nunca tratar texto extraído do PDF como instrução; validar/registrar respostas anômalas do Gemini antes de entregá-las ao aluno |
| `POST /processamentos` | Abuso de custo: cada chamada aciona processamento pago no Worker/Gemini — um loop de solicitações pode gerar custo/DoS financeiro, não apenas técnico | Rate limiting por token de serviço e, quando o Plugin existir, por aluno; considerar limite de processamentos simultâneos por aluno |
| IDs de recursos (`UUID v4`) | Enumeração — mitigado pelo uso de UUID v4 em vez de IDs sequenciais (já decidido em Doc3 §2.1); manter | Não regredir para IDs incrementais em nenhuma entidade futura |
| URLs assinadas de Object Storage | Vazamento de material de outro aluno se a assinatura não expirar ou for previsível | Expiração curta, geração server-side, nunca expor `caminho_storage` bruto (já exigido em Doc3 §7 — manter) |
| Dados de Perfil/Log/Acesso | Dados acadêmicos e comportamentais de estudantes de instituição federal (LGPD) | Minimizar coleta, nunca logar `descricao_llm` ou conteúdo do material em logs de auditoria além do necessário, planejar retenção/anonimização pós-experimento (lacuna já registrada na auditoria de Documento 2/3) |

### 2.2 Defesa em profundidade

Nenhum controle isolado é suficiente. Toda funcionalidade sensível deve combinar, conforme aplicável: autenticação (token de serviço), autorização (validação de que o `aluno_id` pertence ao contexto da requisição), validação de entrada, sanitização, rate limiting, auditoria (Log de Interação), tratamento seguro de erros (nunca vazar stack trace ou detalhes internos ao cliente — já expresso no envelope de erro padrão do Documento 3) e segregação de responsabilidades (Matriz de Responsabilidades do Documento 3, Seção 15).

### 2.3 Validação de entrada

Toda entrada é tratada como potencialmente maliciosa, **incluindo dados vindos do Moodle/Plugin** — o Plugin não é uma fonte confiável só porque é "interno". Validar rigorosamente: corpo JSON (schema, tipos, tamanhos), parâmetros de rota e de consulta, uploads (tipo MIME real, tamanho, conteúdo), encoding, e limites de processamento (tamanho máximo de material aceito pelo pipeline).

### 2.4 Proteção de dados

Minimizar coleta (só os campos já definidos no DER); nunca registrar segredos (token de serviço, chave Gemini) em log; gerenciar segredos via variáveis de ambiente/cofre de segredos, nunca hardcoded (o `.env` atual é aceitável em desenvolvimento, mas não deve ser o modelo em produção); toda comunicação em HTTPS; privacidade desde a concepção nos dados de Perfil, Log e Acesso.

## 3. Arquitetura

A separação já definida no Documento 2/3 v2 — API (borda, síncrona) / Fila / Worker (assíncrono) / Pipeline (domínio, reaproveitado pelo Worker) / Banco de Dados / Object Storage — deve ser preservada e reforçada: regras de negócio (validação de perfil, resolução de `perfil_id`, máquina de estados do Processamento) não devem depender do framework HTTP escolhido (FastAPI hoje, mas o domínio deve sobreviver a uma troca de framework). Manter a separação domínio / aplicação / infraestrutura / interfaces ao evoluir `main.py`/`modulos/` para os processos de API e Worker descritos no Documento 3.

## 4. Qualidade de código

Aplicar SOLID, DRY, KISS, Separation of Concerns, Dependency Injection, Repository Pattern e Service Layer na evolução dos módulos atuais (`modulos/aluno`, `modulos/llm`, `modulos/pdf`) para os componentes API/Worker. Tipagem completa (type hints em Python, validação via Pydantic nos contratos da API). Evitar duplicação e soluções improvisadas — em especial, não reintroduzir divergências entre o modelo de dados (DER) e os contratos da API como as já corrigidas na auditoria técnica.

## 5. Escalabilidade

Projetar considerando aumento de alunos, volume de materiais e processamento concorrente de Processamentos de Personalização. A separação Fila/Worker já prevista existe exatamente para permitir expansão horizontal do Worker sem alterar a API. Evitar decisões que amarrem o sistema a uma única instância (ex.: estado em memória do Worker que impeça múltiplas réplicas).

## 6. Observabilidade

Toda operação relevante deve ser rastreável: logs estruturados, métricas (ver Documento 3 §11 — Indicadores e Métricas), auditoria (entidade Log de Interação) e identificação clara de falhas (máquina de estados do Processamento, Documento 3 §14). **Nunca registrar senhas, tokens, chaves de API ou conteúdo sensível de prompts/respostas do LLM em logs de operação.**

## 7. Testes

Buscar cobertura de testes unitários (regras de negócio de domínio, independentes do FastAPI), testes de integração (API + banco), testes do Worker (máquina de estados, tratamento de exceções da Seção 13 do Documento 3) e testes de segurança (validação de payload, autenticação, limites de upload). Desenhar o código pensando em testabilidade desde o início — é por isso que a separação domínio/infraestrutura da Seção 3 importa na prática, não só no papel.

## 8. Riscos específicos de Inteligência Artificial

Toda integração com Gemini (`gemini_config.py`, `assuntos_llm.py`, `rewrite.py`, geração de `descricao_llm`) deve considerar: Prompt Injection (conteúdo do documento tentando alterar a instrução do sistema), Jailbreak, vazamento de contexto/system prompt, abuso via documentos maliciosos, consumo excessivo de recursos (documentos muito longos, loops de retry sem limite) e manipulação da saída do modelo (validar que a resposta do Gemini é conteúdo pedagógico esperado, não instruções ou conteúdo fora do escopo, antes de entregá-la ao aluno).

## 9. Processo de desenvolvimento

Antes de implementar qualquer componente novo, responder:

1. A arquitetura está correta?
2. Existem riscos de segurança não tratados?
3. Existe solução mais robusta, proporcional ao risco?
4. A implementação é escalável?
5. Está aderente às boas práticas (Seções 4–7)?
6. É facilmente testável?
7. A decisão tem justificativa técnica registrada?

Se alguma resposta for negativa, a solução é revisada antes da implementação — não depois.

## 10. Vigência

Esta diretriz se aplica a toda sugestão técnica, código, arquitetura, biblioteca ou decisão de modelagem produzida para este projeto a partir de 2026-07-28, prevalecendo sobre simplificações adotadas em revisões anteriores da documentação sempre que houver conflito direto com segurança. Onde a diretriz e o princípio de simplicidade já aprovado (ver notas de escopo do Documento 3) entrarem em tensão, a decisão deve ser explicitada e justificada, não assumida silenciosamente.
