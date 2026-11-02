# Da Reunião ao Documento: Design Docs Gerados por IA

> Entrega do Desafio Técnico do MBA IA. O enunciado original está no [repositório base](https://github.com/devfullcycle/mba-ia-desafio-design-docs-com-ia).

## Sobre o desafio

Uma empresa que opera um Order Management System (OMS) em Node.js + TypeScript decidiu, numa reunião técnica de ~55 minutos, construir um **Sistema de Webhooks de Notificação de Pedidos**. O único registro da reunião é a transcrição literal (`TRANSCRICAO.md`). O meu trabalho foi transformar essa transcrição, junto com o código existente, num pacote de design docs acionável para o time começar a implementar: PRD, RFC, FDD, 6 ADRs e um Tracker de rastreabilidade.

A regra central foi: **nada pode ser inventado**. Cada requisito, decisão ou restrição precisa apontar para uma fala `[hh:mm] Nome` da reunião ou para um arquivo real do código. Usei a IA como ferramenta principal de produção. O meu papel foi de maestro: decidir a ordem, escrever prompts dirigidos, revisar o que voltava, resolver ambiguidades e corrigir o que estava errado ou inventado.

## Ferramentas de IA utilizadas

| Ferramenta | Papel |
| --- | --- |
| **Claude Code** (extensão do VS Code, modelo Claude Opus) | Ferramenta principal: leitura do código e da transcrição, classificação da reunião, redação de todos os documentos, verificação de linhas e caminhos de arquivo no código |
| **Plugin `project-analizer`** (marketplace do curso) | Análise do código na etapa de contextualização: relatório de arquitetura, auditoria de dependências e análise profunda de 6 componentes. Saída em `docs/contexto/analise-codigo/` |
| **Plugin `adrs-management`** (marketplace do curso) | Referência de formato: o template MADR e as regras de concisão do agente `adr-generator` guiaram a estrutura dos ADRs. Não rodei o fluxo de identificação automática (ver Iterações) |
| **Scripts Python de validação** (gerados com a IA, em [docs/contexto/scripts/](docs/contexto/scripts/)) | `check_tracker.py`: cada `[hh:mm] Nome` do Tracker precisa existir na transcrição e cada arquivo citado precisa existir. `check_acceptance.py`: confere os critérios de aceite mensuráveis (seções, contagens, nomes de ADR, links, caminhos de código) |

Também instalei os plugins `diagrams-generator` e `development-guidelines`, mas não os usei. Os diagramas Mermaid dos documentos foram escritos diretamente no chat.

## Workflow adotado

Segui a ordem sugerida no enunciado. O princípio foi: **as decisões primeiro, a consolidação depois**.

1. **Setup.** Fork em `adilsonab/mba-ia-desafio-design-docs-com-ia`, com `origin` → fork e `upstream` → repositório do professor.
2. **Contextualização**, em duas frentes:
   - **Código:** o plugin `project-analizer` gerou 8 relatórios em `docs/contexto/analise-codigo/`. Com eles, mapeei `changeStatus`, a máquina de estados, as classes de erro, o `requireRole`, o logger e o schema Prisma, e confirmei que **não existe nenhum mecanismo de eventos** hoje.
   - **Transcrição:** primeiro li a reunião inteira. Depois rodei um prompt de classificação dirigida, cujo resultado está em `docs/contexto/transcricao-classificada.md`: 20 decisões, 13 RF, 12 RNF, 16 itens descartados, 8 adiados, 13 ganchos com o código e **8 ambiguidades**. Comparei com as minhas próprias listas e decidi as ambiguidades.
3. **ADRs:** as 6 decisões principais, no formato MADR, cada afirmação com timestamp.
4. **RFC:** a proposta como um todo, com alternativas descartadas, questões em aberto e links para os ADRs.
5. **FDD:** a especificação de implementação, com cada detalhe conferido contra o código antes de ser escrito.
6. **PRD:** consolidação na altura de produto, sem detalhe técnico.
7. **Tracker:** varredura dos 9 documentos e validação automática.
8. **README:** este documento, montado a partir do diário de processo.

**Como organizei a interação com a IA:**
- **Um passo por vez.** Revisei cada etapa antes de autorizar a próxima.
- **Diário de processo.** O arquivo `docs/contexto/diario-processo.md` registra prompts, problemas e correções conforme aconteciam.
- **Artefatos intermediários versionados.** A classificação da transcrição virou a "fonte da verdade" de todos os documentos seguintes e a base do Tracker.
- **Divisão de papéis.** A IA propõe, eu decido. As ambiguidades foram apresentadas como opções com consequências, e a escolha foi minha.

## Prompts customizados

### 1. Classificação dirigida da transcrição

Este é o prompt mais importante do processo. Ele proíbe inferência, exige timestamp e trata reversões, que são as falhas mais comuns da IA ao ler uma transcrição.

```text
Leia TRANSCRICAO.md integralmente. Classifique CADA ponto discutido em exatamente uma categoria:
1. DECISÃO FECHADA (consenso explícito ou palavra final do tech lead)
2. REQUISITO FUNCIONAL
3. REQUISITO NÃO FUNCIONAL / RESTRIÇÃO (números: timeouts, tentativas, limites)
4. DESCARTADO (proposto e rejeitado — registre o motivo do descarte)
5. ADIADO / EM ABERTO (empurrado para fase futura ou sem decisão)
6. GANCHO COM O CÓDIGO (menção a arquivo, classe, padrão existente)

Regras:
- Cada item DEVE ter a localização exata no formato [hh:mm] Nome. Sem timestamp = não entra.
- Não infira, não complete lacunas, não use conhecimento geral sobre webhooks.
  Se algo for ambíguo, marque como AMBÍGUO e cite as falas conflitantes.
- Quando uma ideia for proposta e depois revertida, registre a posição final
  e o timestamp da reversão.
- Para cada GANCHO COM O CÓDIGO, confirme se o arquivo/símbolo existe usando
  os relatórios em docs/contexto/analise-codigo/.
Saída: uma tabela por categoria, salva em docs/contexto/transcricao-classificada.md.
```

### 2. Análise de arquitetura com foco na feature (adaptação do plugin `project-analizer`)

O comando do plugin gera um prompt genérico. Acrescentei um bloco de contexto para o agente cobrir, com linha e arquivo, exatamente os pontos que o FDD precisaria, sem inventar nada além do código.

```text
Execute architectural analysis with the following parameters:
Project scope: entire project root
Output location: docs/contexto/analise-codigo/architectural-analyzer
Folders to ignore: node_modules, dist, .git, docs

Context (useful focus, do not invent beyond the code): this codebase will later receive
an order-notification webhooks feature. Make sure the report precisely covers, with real
file paths and line references: the modular structure, the order state machine
(order.status.ts), the transaction inside OrderService.changeStatus and status-history
auditing, the error classes and error-code pattern (src/shared/errors), the requireRole
middleware, the centralized error middleware, the Pino logger, the response helpers,
the Prisma schema, and the existing test setup. Also state explicitly that there is no
existing eventing/queue/webhook mechanism, if that is what the code shows.
```

### 3. Validação anti-alucinação do Tracker

Não é um prompt de geração. É a verificação que pedi à IA para escrever e rodar depois de montar o Tracker ([docs/contexto/scripts/check_tracker.py](docs/contexto/scripts/check_tracker.py); rode com `python docs/contexto/scripts/check_tracker.py .`). O núcleo da checagem:

```python
spoken = set(re.findall(r"^\[(\d\d:\d\d)\] (\w+):", transcript, re.M))
# para cada linha do tracker com Fonte = TRANSCRICAO:
m = re.fullmatch(r"\[(\d\d:\d\d)\] (\w+)", localizacao)
if (m.group(1), m.group(2)) not in spoken:
    erro(f"{id}: {localizacao} não existe na transcrição")
# para Fonte = CODIGO: os.path.exists(caminho) ou erro
```

## Iterações e ajustes

Foram **5 iterações principais** de gerar, revisar e corrigir, além de ajustes menores de setup.

1. **Plugin de análise grande demais para o problema.** O relatório de arquitetura listou **41 componentes**, e o fluxo do plugin manda analisar cada um em profundidade. Agrupei em **6 blocos** que a feature realmente toca: Pedidos, Erros, Auth, Observabilidade, Persistência e Composição. No relatório de dependências, a IA listou dezenas de CVEs com IDs que não consegui verificar. Decidi **não citar nenhum CVE** nos documentos, porque nenhum seria rastreável no Tracker.

2. **Revisão humana da classificação da transcrição.** Comparei as minhas listas (decisões, descartados, adiados) com as da IA. A convergência foi quase total, com divergências apenas de categoria em "dashboard" e "ordering global". A IA, porém, capturou algo que eu não tinha listado: o `customer_id` foi proposto como "implícito do JWT" ([09:31] Marcos) e **revertido** um minuto depois ([09:32] Larissa). Também decidi três ambiguidades: `customer_id` no body, uma linha de outbox por webhook e a contagem de tentativas. Sobre as duas primeiras, a IA apontou consequências que eu não tinha visto: o GET de listagem não tem body, e todas as linhas do mesmo evento precisam compartilhar o `X-Event-Id`.

3. **A minha própria resposta estava errada: "5 tentativas".** Respondi "5 tentativas no total". A IA mostrou que isso contradizia a transcrição: com 5 envios só cabem 4 intervalos, então o 12h nunca seria usado e a janela cairia para ~2,6 h. O Diego disse "quase 15 horas" ([09:17] Diego). Comparamos as duas leituras numa linha do tempo, e escolhi **5 reenvios após o envio inicial**, a única em que todos os números da reunião fecham. A lição: revisão crítica vale nos dois sentidos.

4. **Conflito entre o formato do curso e o enunciado nos ADRs.** O agente `adr-generator` proíbe nomes de classes, tabelas e endpoints no corpo do ADR, mas o desafio exige pelo menos um ADR que cite código. Além disso, o plugin identifica decisões **já implementadas no código**, e aqui elas vêm da reunião. Usei só o formato MADR do plugin. Os caminhos de arquivo foram para a seção Referências, e o ADR-006 (reuso de padrões) cita as classes no corpo, porque elas são o próprio assunto da decisão.

5. **O código derrubou suposições do FDD.** Antes de escrever, pedi à IA para conferir no código cada detalhe a ser citado. Isso mudou o desenho em quatro pontos:
   - `NotFoundError` fixa o código `NOT_FOUND`, então os 404 do módulo precisam usar `AppError` diretamente para emitir `WEBHOOK_*`.
   - O `validate` middleware converte todo erro do Zod em `VALIDATION_ERROR`. Isso entra em conflito com "HTTPS validado no Zod" ([09:23] Sofia) mais o código `WEBHOOK_INVALID_URL` ([09:28] Bruno). A solução foi Zod para o formato e o service para o esquema `https`.
   - `tests/setup.ts` apaga `customers`, então as novas tabelas com FK precisam ser limpas antes.
   - Ao desenhar o fluxo de retry, apareceu um risco que a reunião não viu: **retries podem inverter a ordem** dos eventos de um mesmo pedido, contrariando a "ordem por `order_id`" ([09:12] Diego). Registrei como risco no FDD.

   Detalhes que a reunião não fixou, mas que são necessários para codar, ficaram marcados com **[D]** (decisão de desenho), para não parecerem decisões da reunião.

**Outros ajustes:**
- **No PRD,** evitei métricas inventadas. Ninguém deu meta numérica para a redução do polling, e o documento diz isso em vez de inventar um percentual.
- **No Tracker,** a validação automática confirmou 278 linhas sem erro: 83% com fonte `TRANSCRICAO` e 46 com fonte `CODIGO`.
- **No setup,** os comandos `/plugin install ...@devfullcycle` falharam porque o marketplace registrado se chama `fullcycle-claude-marketplace`.

## Como navegar a entrega

**Ordem sugerida de leitura:**

| # | Documento | Pergunta que responde |
| --- | --- | --- |
| 1 | [docs/PRD.md](docs/PRD.md) | Por que e o quê? (problema, público, escopo, métricas) |
| 2 | [docs/RFC.md](docs/RFC.md) | O que propomos e o que ainda está em aberto? |
| 3 | [docs/adrs/](docs/adrs/README.md) | Por que decidimos exatamente assim? (6 ADRs) |
| 4 | [docs/FDD.md](docs/FDD.md) | Como construir em detalhe? (fluxos, contratos, erros, integração) |
| 5 | [docs/TRACKER.md](docs/TRACKER.md) | De onde veio cada item? |

**ADRs:**
- [ADR-001 — Padrão Outbox no MySQL](docs/adrs/ADR-001-outbox-no-mysql.md)
- [ADR-002 — Worker separado com polling de 2 s](docs/adrs/ADR-002-worker-separado-com-polling.md)
- [ADR-003 — Retry com backoff exponencial e DLQ](docs/adrs/ADR-003-retry-com-backoff-exponencial-e-dlq.md)
- [ADR-004 — HMAC-SHA256 com secret por endpoint](docs/adrs/ADR-004-assinatura-hmac-sha256-com-secret-por-endpoint.md)
- [ADR-005 — At-least-once com X-Event-Id](docs/adrs/ADR-005-entrega-at-least-once-com-x-event-id.md)
- [ADR-006 — Reuso dos padrões existentes](docs/adrs/ADR-006-reuso-dos-padroes-existentes.md)

**Material de processo** (opcional, mostra como cheguei lá):
- [docs/contexto/transcricao-classificada.md](docs/contexto/transcricao-classificada.md): a reunião classificada, com ambiguidades e resoluções.
- [docs/contexto/diario-processo.md](docs/contexto/diario-processo.md): o diário etapa por etapa.
- [docs/contexto/analise-codigo/](docs/contexto/analise-codigo/README-2026-11-02-1513.md): os relatórios do plugin `project-analizer`.
- [docs/contexto/scripts/](docs/contexto/scripts/): os scripts de validação do Tracker e dos critérios de aceite.

O código da aplicação (`src/`, `prisma/`, `tests/`) **não foi alterado**. A entrega é puramente documental.
