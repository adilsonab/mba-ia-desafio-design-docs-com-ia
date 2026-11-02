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
