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
9. **Revisão final** contra a checklist de critérios de aceite, com script.
10. **Iteração:** mais quatro ciclos de revisão crítica, totalizando cinco (ver "Iterações e ajustes"). Cada ciclo começou com uma pré-revisão da IA, e eu decidi item a item o que mudar.

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

### 4. Pré-revisão crítica (ciclos 2 a 5)

O script acima confere se o `[hh:mm] Nome` **existe**, mas não se a fala **sustenta** a frase. Para os ciclos de revisão, passei a pedir uma pré-revisão com estas regras. A IA aponta os problemas e propõe correções; a decisão de cada item é minha.

```text
Faça uma pré-revisão crítica de <documento(s)>. Não altere nada ainda.
Para cada afirmação com origem [hh:mm] Nome, abra a fala na TRANSCRICAO.md e diga se ela
sustenta a frase (ou se a frase atribui ao falante algo que ele não disse).
Para cada arquivo ou linha de código citado, abra o arquivo e confira.
Procure também:
- contradições com os outros documentos do pacote (busque o mesmo fato em todos);
- argumentos, nomes ou limiares sem fonte e sem a marca [D] ou "análise do autor";
- comportamento resultante do desenho que contradiga um objetivo declarado;
- falas que contrariam uma interpretação adotada.
Saída: lista numerada, do mais grave ao mais leve, com o trecho, a evidência
e uma proposta de correção. Eu respondo concordo/discordo/outra coisa por item.
```

## Iterações e ajustes

Foram **5 ciclos** de gerar, revisar criticamente e corrigir. Cada ciclo foi um commit separado (`Ciclo 1` a `Ciclo 5`), e o detalhe de cada um está no [diário](docs/contexto/diario-processo.md). Separei os ciclos de revisão dos ajustes que fiz *durante* a geração: só conta como ciclo quando um documento pronto foi revisado e corrigido.

### Ciclos de revisão

**Ciclo 1: classificação da transcrição e geração do pacote.**
- **Minhas listas contra as da IA.** Comparei as minhas listas de decisões, descartados e adiados com as da IA. A convergência foi quase total. A IA, porém, capturou uma reversão que eu não tinha listado: o `customer_id` foi proposto como "implícito do JWT" ([09:31] Marcos) e revertido um minuto depois ([09:32] Larissa).
- **Resposta errada minha.** Eu disse "5 tentativas no total". A IA mostrou que, assim, o intervalo de 12 h nunca seria usado e a janela cairia para ~2,6 h, contra o "quase 15 horas" de [09:17] Diego. Escolhi **5 reenvios após o envio inicial**.
- Com a classificação revisada, gerei ADRs, RFC, FDD, PRD e Tracker.

**Ciclo 2: ADRs e RFC (13 achados).**
- **Contradições com o FDD:** ADR-002 e RFC prometiam ordem por pedido, mas o FDD mostrava que o retry inverte a ordem. O ADR-006 pedia "observabilidade além de logs", contra o "nada novo" ([09:29] Bruno).
- **Fala atribuída a quem não a disse:** o ADR-005 atribuía ao Diego que "exactly-once não é praticado pelos provedores". Ele só citou Stripe e GitHub.
- **Argumentos sem fonte:** decidi não remover nenhum. Todos ficaram marcados como *(análise do autor)*, convenção documentada no índice dos ADRs.
- **Lição:** o script anti-alucinação aprovava tudo isso. Ele confere se a fala existe, não se ela sustenta a frase. Daí nasceu o prompt 4.

**Ciclo 3: FDD (13 achados).**
- **Todas as linhas de código citadas estavam certas. O erro estava no desenho:**
  - O worker sequencial, com timeout de 10 s, deixa **um cliente lento segurar os outros** por até ~100 s. É o mesmo problema que motivou descartar o envio síncrono ([09:04] Bruno), e a §8 dizia "isolamento entre clientes".
  - O heartbeat do worker era emitido em `debug`, com `LOG_LEVEL` padrão `info`: o alerta "worker caído" dispararia sempre.
- **Detalhes inventados sem marca:** 8 dos 10 códigos de erro ganharam **[D]**. As métricas tinham nomes de Prometheus num projeto sem Prometheus e viraram consultas SQL e agregações de log.
- **Lição:** o texto estava certo frase a frase, mas o *comportamento resultante* contradizia o objetivo. Só simulando o cenário do cliente lento o problema apareceu.

**Ciclo 4: PRD e Tracker (12 achados).**
- **Viés de confirmação.** No resumo final, a Larissa diz "**total 5 tentativas**" ([09:48]), e todos confirmam. A classificação registrava essa fala, mas ela se perdeu até os ADRs. Mantive a leitura do ciclo 1, a única em que os cinco intervalos e as ~15 h fecham. Agora a evidência contrária está registrada em ADR-003, RFC, PRD e FDD, e a contagem vai para o design review.
- **Cenários com nomes de clientes reais** em situações que a reunião não atribuiu a ninguém. Passaram a ser ilustrativos.
- **Cobertura do Tracker medida pela primeira vez.** O total passava, mas os ADRs isolados tinham ~68%. Com 16 linhas novas, chegaram a ~93%.

**Ciclo 5: leitura cruzada de consistência (8 achados).**
- Busquei os mesmos fatos (janela, tentativas, latência, ordem, status, endpoints) nos cinco documentos. Os 8 achados tinham um único padrão: correções que chegaram a uns documentos e não a outros.
- O risco do cliente lento estava em FDD, RFC e PRD, mas **não no ADR-002**, que é justamente a decisão que o causa. Também virou a questão em aberto 10 do RFC.
- Depois deste ciclo, a busca cruzada não encontrou mais nada que se propagasse, e encerrei os ciclos.

### Ajustes durante a geração

Estas correções aconteceram enquanto eu produzia os documentos, antes de qualquer revisão:

- **Plugin grande demais para o problema.** O relatório de arquitetura listou 41 componentes para analisar em profundidade. Agrupei em 6 blocos que a feature toca. No relatório de dependências, os CVEs listados tinham IDs que não consegui verificar, então nenhum foi citado.
- **Formato dos ADRs.** O `adr-generator` proíbe nomes de classes no corpo do ADR, mas o desafio exige um ADR que cite código. Mantive o formato MADR e pus as citações de código na seção Referências. O ADR-006 cita classes no corpo porque elas são o assunto da decisão.
- **O código derrubou suposições do FDD.**
  - `NotFoundError` fixa o código `NOT_FOUND`, então os 404 do módulo usam `AppError` diretamente.
  - O `validate` converte todo erro do Zod em `VALIDATION_ERROR`, então o esquema `https` é validado no service para emitir `WEBHOOK_INVALID_URL`.
  - Detalhes não fixados na reunião ganharam a marca **[D]**.
- **No PRD, nenhuma meta inventada.** Ninguém deu número para a redução do polling, e o PRD diz isso.
- **Setup.** `/plugin install ...@devfullcycle` falhou porque o marketplace se chama `fullcycle-claude-marketplace`.

### Estado final

- **Tracker:** 314 linhas, 0 erros. São 84% com fonte `TRANSCRICAO` e 49 com fonte `CODIGO`. Cobertura medida acima de 80% em cada documento.
- **Critérios de aceite mensuráveis:** 76/76 OK em [check_acceptance.py](docs/contexto/scripts/check_acceptance.py).
- **Pontos deixados explicitamente para o design review** ([09:50] Larissa): contagem de tentativas, ordem por pedido com retries e cliente lento segurando o worker (RFC, questões 6, 9 e 10).

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
