# Diário do processo

Registro cronológico de prompts, resultados e correções. Fonte para a seção "Iterações e ajustes" do README.

## 2026-11-02 — Etapa 1: fork e setup

- `origin` do clone apontava para o repositório do professor, não para um fork. Criado o fork `adilsonab/mba-ia-desafio-design-docs-com-ia`; `origin` → fork, `upstream` → original.
- Os comandos `/plugin install ...@devfullcycle` falharam: o nome do marketplace registrado é `fullcycle-claude-marketplace`. Instalados os 4 plugins (adrs-management, diagrams-generator, project-analizer, development-guidelines).

## 2026-11-02 — Etapa 2A: análise do código

- Ferramenta: plugin `project-analizer:generate-architectural-report` (Claude Code).
- Saída: `docs/contexto/analise-codigo/` (8 relatórios + MANIFEST + overview).
- **Ajuste:** o relatório de arquitetura listou 41 componentes e o fluxo do plugin manda analisar cada um em profundidade. Agrupei em 6 blocos relevantes para a feature (Orders, ErrorHandling, Auth, Observability, Persistence, Composition) — 41 análises seriam caras e majoritariamente irrelevantes.
- **Revisão crítica:** o relatório de dependências cita dezenas de CVEs com IDs não verificáveis; decidido não citar CVEs em nenhum documento (não rastreáveis no Tracker).

## 2026-11-02 — Etapa 2B: classificação da transcrição

- Prompt dirigido (ver README): classificar cada ponto em decisão / RF / RNF / descartado / adiado / gancho com código, exigindo `[hh:mm] Nome`, proibindo inferência e tratando reversões.
- Saída: `docs/contexto/transcricao-classificada.md` (20 decisões, 13 RF, 12 RNF, 16 descartados, 8 adiados, 13 ganchos, 8 ambiguidades).

### Iteração 1 — revisão humana da classificação

- Comparei minhas próprias listas (feitas a partir da leitura da transcrição) com a da IA. Convergência quase total.
- Divergências de categoria: dashboard visual e ordering global (eu: descartado; IA: adiado/fora de escopo) — equivalentes para o PRD.
- A IA capturou uma reversão que eu não listei: `customer_id` implícito do JWT ([09:31] Marcos) revertido para explícito ([09:32] Larissa).
- Decisões minhas sobre ambiguidades: `customer_id` no body (IA apontou que no GET precisa ir por query string); uma linha de outbox por webhook (IA derivou: mesmo `event_id` compartilhado entre as linhas).
- **Conflito detectado:** minha resposta inicial "5 tentativas no total" contradiz [09:17] Diego (~15 h de janela só fecha com 5 intervalos após o envio inicial). Comparadas as duas leituras com linha do tempo de cada uma: (a) 5 retries após o envio inicial (~14,6 h, usa os 5 intervalos) vs. (b) 5 envios no total (~2,6 h, 12h sem uso). **Escolhida (a)** por ser a única em que todos os números da reunião fecham. Lição: a IA também precisa ser questionada quando eu decido — e eu preciso checar a matemática das minhas próprias respostas.

## 2026-11-02 — Etapa 3: ADRs

- Base: `docs/contexto/transcricao-classificada.md` (mapa de ADRs candidatos) + formato MADR do plugin `adrs-management` (agente `adr-generator`).
- **Por que não rodei o plugin direto:** o `adr-identify`/`adr-generate` identificam decisões **já implementadas no código** (via mapeamento do codebase e git). Aqui as decisões vêm da reunião — o webhook ainda não existe. Usei só o formato MADR e as regras de concisão dele.
- **Conflito entre o formato do curso e o enunciado:** o `adr-generator` proíbe nomes de classes, tabelas e endpoints no corpo do ADR; o desafio exige ≥ 1 ADR referenciando arquivos/classes do código. Resolução: caminhos de arquivo na seção Referências de todos; o ADR-006 (reuso de padrões) cita classes e arquivos explicitamente no corpo, porque esse é o assunto da decisão.
- Seções: as 7 do MADR do curso, traduzidas, com títulos que batem com o enunciado (Contexto, Decisão, Alternativas Consideradas, Consequências positivas/negativas + trade-off explícito).
- Toda afirmação cita `[hh:mm] Nome`; interpretações (T-AMB-01 e T-AMB-04) aparecem marcadas como "Interpretação registrada" nos ADRs 003 e 005.
- Verificação automática: todos os 14 caminhos de arquivo citados existem no repositório.

## 2026-11-02 — Etapa 4: RFC

- Construído sobre os 6 ADRs; cada seção da proposta aponta para o ADR correspondente em vez de repetir o detalhamento.
- Fronteira com o FDD: RFC lista a superfície de API em uma frase, sem payloads, headers detalhados ou códigos de erro.
- Questões em aberto em dois grupos: (1) adiadas/não decididas na reunião (5 itens, todos com timestamp); (2) interpretações minhas a confirmar na revisão (contagem de tentativas, `customer_id`, granularidade da outbox) — transparência sobre o que não veio literalmente da reunião.
- Riscos combinam transcrição e achados da análise de código (concorrência em `changeStatus`, cadastro público aceitando ADMIN, falta de vínculo user↔customer), sempre indicando a fonte.

## 2026-11-02 — Etapa 5: FDD

- Antes de escrever, conferi no código os detalhes que o FDD cita (assinaturas, linhas, schema). Achados que mudaram o desenho:
  - `NotFoundError` fixa o código `NOT_FOUND` → 404 do módulo usam `AppError` direto para emitir `WEBHOOK_*`.
  - `validate.middleware` sempre converte Zod em `VALIDATION_ERROR` → conflito entre "validação https no Zod" ([09:23] Sofia) e o código `WEBHOOK_INVALID_URL` ([09:28] Bruno); resolvido com Zod para formato + service para o esquema https.
  - `tests/setup.ts` apaga `customers` — novas tabelas com FK precisam entrar no `beforeEach` antes.
  - `Customer.address` já é `Json` → precedente para guardar o snapshot do payload em Json.
- Convenção **[D]** para detalhes de implementação não fixados na reunião (nomes de tabelas auxiliares, rota de rotação, tamanho do lote, assinatura dupla na rotação, recuperação de `PROCESSING` após crash, etc.) — evita apresentar invenção como decisão da reunião e deixa claro o que confirmar no design review ([09:50] Larissa).
- Observabilidade: a reunião não discutiu métricas/tracing e decidiu "nada novo" ([09:29] Bruno). Métricas derivadas de logs/tabelas e tracing por correlação de IDs (`X-Request-Id` → `eventId` → entregas), sem OpenTelemetry.
- Risco que surgiu ao desenhar o fluxo: retries podem inverter a ordem de eventos do mesmo pedido, contrariando a "ordem por order_id" ([09:12] Diego). Registrado no FDD como risco com proposta para o design review.
- Opção do payload > 64 KB: checado no worker (vai direto para DLQ), e não na inserção — se fosse na inserção, um payload grande desfaria uma mudança de status válida.

## 2026-11-02 — Etapa 6: PRD

- Consolidação de RFC, FDD e ADRs, reescrita na altura de produto: sem tabelas, headers, códigos de erro ou nomes de classes no corpo (só nas dependências/riscos que vêm do código).
- **Cuidado com métricas inventadas:** só entraram metas com origem na reunião (< 10 s, zero perda, ~15 h, 3 clientes até fim de novembro, retenção da Atlas). A redução do polling em `GET /orders` ficou sem meta numérica porque ninguém deu número — registrado explicitamente no PRD em vez de inventar um percentual.
- "Fora de escopo" com 8 itens, cada um marcado como adiado/descartado/fora e com timestamp.
- IDs `PRD-FR-xx` / `PRD-NFR-xx` pensados para o Tracker.

## 2026-11-02 — Etapa 7: Tracker

- Varredura dos 9 documentos (PRD, RFC, FDD, 6 ADRs) seção por seção; 278 linhas.
- Itens **[D]** do FDD entram como "Decisão de desenho (derivada)" apontando para a fala da qual derivam; interpretações (T-AMB-01/02/04) como tipo "Interpretação".
- **Validação automática anti-alucinação** (script Python, fora do repositório): para cada linha, confere se o par `[hh:mm] Nome` existe literalmente na transcrição (mesmo minuto e mesmo falante), se o arquivo de código existe e se o documento existe. Resultado: 278 linhas, 0 erros; 232 (83%) TRANSCRICAO, 46 CODIGO.

## 2026-11-02 — Etapa 8: README

- README substituído pela documentação do processo, montado a partir deste diário; mantido link para o enunciado original.
- Registrado com honestidade que `diagrams-generator` e `development-guidelines` foram instalados mas não usados.

## 2026-11-02 — Etapa 9: revisão final contra a checklist

- Scripts de validação copiados para `docs/contexto/scripts/` como evidência do processo.
- Script de verificação automática dos critérios de aceite mensuráveis (seções, contagens, nomes de ADR, links, caminhos de código): **76/76 OK**.
- Tracker revalidado: 278 linhas, 0 erros (83% TRANSCRICAO, 46 CODIGO).
- `git status`: só `README.md` e `docs/` alterados; `src/`, `prisma/`, `tests/`, `package.json` e `TRANSCRICAO.md` intactos.
- Pendente para a etapa 10: revisão crítica humana do conteúdo (genérico? repetido entre documentos? origem que não sustenta o texto?) — o script verifica estrutura e existência, não qualidade.

## 2026-11-03 — Etapa 10, ciclo 2: revisão crítica de ADRs e RFC

- **Pergunta que motivou o ciclo:** as "5 iterações" do README eram, na maioria, ajustes feitos pela IA durante a geração. Só a revisão da classificação foi um ciclo real de gerar → revisar → corrigir. ADRs e RFC ainda não tinham passado por revisão crítica.
- **Método:** pedi à IA uma pré-revisão que conferisse cada afirmação contra a fala citada na transcrição, em vez de só checar o formato. Ela trouxe 13 achados com o trecho e uma proposta de correção para cada. Li tudo e decidi item a item. Aceitei todos, com uma regra minha: **nada de remover** argumentos sem fonte; eles ficam, mas marcados como *(análise do autor)*.
- **Contradições entre documentos (as mais graves):**
  - ADR-002 e RFC prometiam ordem por pedido com um único worker, mas o FDD já mostrava que **retry inverte a ordem**. A ressalva entrou nos dois, e o tema virou a questão em aberto 9 do RFC, para o design review.
  - ADR-006 dizia que o módulo teria de "introduzir observabilidade além de logs", contra o FDD e o "nada novo" ([09:29] Bruno). Alinhado ao FDD.
- **Falas atribuídas a quem não as disse:** o ADR-005 punha na boca do Diego que "exactly-once não é praticado pelos provedores". Ele só citou Stripe e GitHub. Corrigido para a fala literal.
- **Argumentos sem fonte** (ADR-001, 002, 003 e a alternativa "abordagem própria" do ADR-006, que ninguém propôs) passaram a ser marcados como *(análise do autor)*. A convenção ficou documentada em `docs/adrs/README.md`.
- **Fonte real no lugar de frase genérica:** o "volume pesa no banco" do ADR-001 virou a troca real entre [09:07] Bruno e [09:08] Diego.
- **Ajustes menores:**
  - ADR-004: HTTPS e timestamp saíram da decisão e foram para "requisitos relacionados", porque a própria Sofia disse que HTTPS "nem é decisão arquitetural" ([09:23]).
  - RFC: Prob/Impacto marcados como estimativa do autor.
  - RFC: prazo com as duas falas ("fim do trimestre" e "fim de novembro").
  - RFC: a tabela de alternativas enxugada para uma linha mais o link do ADR, para não repetir os ADRs.
  - Status "Aceito" dos ADRs mantido, com a justificativa registrada no índice.
- **Lição:** o script anti-alucinação só confere se o `[hh:mm] Nome` **existe**, não se a fala **sustenta** a frase. Os dois tipos de erro deste ciclo (atribuição inflada e argumento sem fonte) passaram no script. Só a leitura cruzada fala × frase os pegou.
- Tracker: +6 linhas (RFC-CTX-04, RFC-OPEN-09, ADR-001-CONS-02, ADR-002-CONS-03, ADR-005-ALT-02, ADR-006-CONS-01) e tipo do HTTPS no ADR-004 corrigido. Revalidação: **284 linhas, 0 erros (84% TRANSCRICAO)**; critérios de aceite **76/76 OK**.

## 2026-11-03 — Etapa 10, ciclo 3: revisão crítica do FDD

- **Método:** mesmo do ciclo 2, com um passo a mais: como o FDD cita muito código, a pré-revisão abriu cada arquivo citado e conferiu linhas e assinaturas. **Todas as linhas citadas estavam corretas**; os problemas estavam no desenho e em detalhes inventados sem marca. Foram 13 achados. Aceitei todos, com as opções sugeridas.
- **Falhas de desenho que nenhum script pegaria:**
  - **Worker sequencial reintroduz o problema que a outbox resolveu.** Com timeout de 10 s e lote de 10, um cliente lento segura o worker por até ~100 s e atrasa todos os outros clientes: o "cliente lento trava os outros" de [09:04] Bruno, só que no worker. A §8 afirmava "isolamento entre clientes", o que era falso. Corrigida para "parcial", e o risco entrou no FDD e no RFC com duas opções para o design review (paralelizar entre pedidos diferentes, ou aceitar e monitorar).
  - **Heartbeat invisível:** emitido em `debug`, com `LOG_LEVEL` padrão `info` (`src/config/env.ts:6`). O alerta "worker caído" dispararia sempre. Passou para `info` a cada 30 ciclos.
- **Contradições com outros documentos e com a reunião:**
  - O RFC dizia que "a única mudança" no código atual era uma chamada na transação, mas a integração do FDD lista ajustes em 7 arquivos existentes. RFC §6 corrigido.
  - `publishWebhookEvent` tinha 4 parâmetros na fala do Bruno ([09:41]) e na §5.1, mas 5 no diagrama e na §10. O `requestId` foi mantido, agora marcado como **[D]** e justificado.
- **Invenção sem marca:**
  - Só 2 dos 10 códigos de erro vieram da reunião ([09:28] Bruno); os outros 8 receberam **[D]**.
  - As métricas tinham nomes e tipos de Prometheus (`_total{...}`, histograma, gauge) num projeto sem Prometheus. Viraram indicadores com "como obter" (SQL ou log), e o "p95 < 10 s" foi marcado como **[D]**.
  - Paginação da listagem marcada como **[D]**.
  - "Últimos 100" do histórico: registrado como interpretação (tentativas e não eventos), com a origem do payload explicada.
- **Ajustes técnicos:**
  - O worker usa o `prisma` exportado, em vez de `createPrismaClient()`, que criaria um 2º cliente no mesmo processo.
  - A ordem de limpeza em `tests/setup.ts` agora inclui a FK `replayedById` → `users`.
  - Nota sobre o worker herdar a exigência de `JWT_SECRET`.
  - Prob./Impacto marcados como estimativa do autor.
  - Risco de ordem ligado à questão 9 do RFC.
- **Lição:** no ciclo 2, o erro era a fala não sustentar a frase. Aqui foi outro tipo: o texto estava todo "certo" localmente, mas o **comportamento resultante** contradizia o objetivo. Só simulando o worker com um cliente lento o problema apareceu.
- Tracker: +8 linhas (FDD-INT-19/20, FDD-OBS-06, FDD-RISK-10/11, FDD-FLUXO-20, FDD-ERRO-13, RFC-RISK-08) e 2 corrigidas (FDD-INT-13, FDD-INT-18). Revalidação: **292 linhas, 0 erros (84% TRANSCRICAO, 48 CODIGO)**; critérios de aceite **76/76 OK**.
