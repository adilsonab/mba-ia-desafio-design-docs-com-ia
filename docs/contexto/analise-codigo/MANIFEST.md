# MANIFEST - mba-ia-desafio-design-docs-com-ia (OMS)
Generated on: 2026-11-02 15:13:09

## Parameters
- Project folder: entire project root
- Output folder: docs/contexto/analise-codigo
- Ignore folders: node_modules, dist, .git, docs

## Execution Status: COMPLETED
Completed on: 2026-11-02 (8 relatórios: 1 dependências, 1 arquitetura, 6 componentes)

## Reports

### dependency-auditor
- Status: COMPLETED
- Started: 2026-11-02 15:13
- Completed: 2026-11-02
- Output: dependency-auditor/dependencies-report-2026-11-02-1513.md

### architectural-analyzer
- Status: COMPLETED
- Started: 2026-11-02 15:13
- Completed: 2026-11-02
- Output: architectural-analyzer/architectural-report-2026-11-02-1513.md
- Components Found: 41 (agrupados em 6 para a análise profunda, focando nos pontos de integração da feature de webhooks)

### Components (to be populated after architectural analysis)

Os 41 componentes do relatório foram agrupados em 6 unidades coesas; análise profunda restrita ao que a feature de webhooks vai tocar.

#### OrdersModule (order.service, order.status, order.repository, order.controller, order.routes, order.schemas)
- Status: COMPLETED
- Output: component-deep-analyzer/component-analysis-OrdersModule-2026-11-02-1513.md

#### ErrorHandling (src/shared/errors/*, error.middleware)
- Status: COMPLETED
- Output: component-deep-analyzer/component-analysis-ErrorHandling-2026-11-02-1513.md

#### AuthAndAuthorization (auth.middleware: authenticate/requireRole, auth module)
- Status: COMPLETED
- Output: component-deep-analyzer/component-analysis-AuthAndAuthorization-2026-11-02-1513.md

#### Observability (src/shared/logger, request-logger.middleware)
- Status: COMPLETED
- Output: component-deep-analyzer/component-analysis-Observability-2026-11-02-1513.md

#### PersistenceLayer (prisma/schema.prisma, migration, src/config/database.ts)
- Status: COMPLETED
- Output: component-deep-analyzer/component-analysis-PersistenceLayer-2026-11-02-1513.md

#### CompositionAndConfig (src/app.ts, src/server.ts, src/routes/index.ts, src/config/env.ts, validate.middleware, response helpers, tests/setup)
- Status: COMPLETED
- Output: component-deep-analyzer/component-analysis-CompositionAndConfig-2026-11-02-1513.md
