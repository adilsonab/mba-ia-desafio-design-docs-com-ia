# ADR-004: Assinatura HMAC-SHA256 com secret por endpoint e rotação

**Status:** Aceito
**Data:** 02-11-2026 (registro da decisão tomada na reunião técnica de quinta-feira, 09:00)
**ADRs relacionados:** [ADR-005](ADR-005-entrega-at-least-once-com-x-event-id.md), [ADR-006](ADR-006-reuso-dos-padroes-existentes.md)

## Contexto e Problema

Os webhooks enviam dados de pedidos para endpoints **fora da infraestrutura** da empresa. O fluxo é só de saída: os clientes recebem, não enviam ([09:02] Marcos, [09:03] Sofia). O cliente precisa conseguir verificar que a requisição veio da plataforma e que o conteúdo não foi adulterado no caminho ([09:19] Sofia).

A equipe já teve cliente que vazou um segredo em log da própria aplicação ([09:22] Diego). O mecanismo precisa limitar o estrago de um vazamento e permitir a troca do segredo sem interromper a integração.

## Fatores de Decisão

- Autenticidade e integridade verificáveis pelo cliente ([09:19] Sofia).
- Padrão de mercado, com bibliotecas disponíveis em qualquer stack ([09:20] Sofia).
- Vazamento de um segredo não pode comprometer todos os clientes ([09:21] Sofia).
- Troca de segredo sem janela de quebra para o cliente ([09:21] Sofia).
- Revisão de segurança dedicada antes do deploy ([09:46] Sofia).

## Alternativas Consideradas

1. **Secret global** da plataforma, compartilhada por todos os endpoints.
2. **HMAC-SHA256 com secret única por endpoint**, com rotação e período de convivência.

## Decisão

Toda requisição de webhook é assinada com **HMAC-SHA256 sobre o corpo da requisição**, e a assinatura vai em um header dedicado ([09:20] Sofia). Fechado em [09:22] Sofia: "Decidido: HMAC-SHA256 sobre o corpo do request, secret por endpoint, suporte a rotação com grace period de 24h".

- **Secret única por endpoint** de webhook, nunca global ([09:21] Sofia). A secret é armazenada junto com a configuração do endpoint ([09:21] Bruno, [09:21] Sofia).
- A secret é **gerada pela plataforma** e devolvida ao cliente na criação do webhook ([09:31] Marcos).
- **Rotação via API**: o cliente pede uma nova secret, e a antiga **continua válida por 24 h** em paralelo para dar tempo de migrar. Depois disso, é invalidada ([09:21] Sofia).

**Requisitos relacionados (não fazem parte desta decisão):**
- **Somente HTTPS**: URLs `http` são recusadas na validação de entrada. A própria Sofia disse que isso "nem é decisão arquitetural, é só uma validação no schema Zod" ([09:23] Sofia).
- **Carimbo de tempo do envio**: acompanha a requisição para o cliente poder detectar ataques de repetição, se quiser ([09:44] Diego). É detalhe do contrato de envio, especificado no [FDD](../FDD.md).

## Prós e Contras das Alternativas

### Secret global
- ✅ Uma única chave para gerenciar.
- ❌ "Se vaza uma, vaza tudo" ([09:21] Sofia).
- ❌ Rotação afeta todos os clientes ao mesmo tempo.

### HMAC-SHA256 com secret por endpoint (escolhida)
- ✅ Padrão de mercado; "todo cliente sério tem biblioteca pra isso" ([09:20] Sofia).
- ✅ Vazamento fica restrito a um endpoint.
- ✅ Rotação com 24 h de convivência evita quebrar a integração do cliente.
- ❌ A plataforma precisa guardar e proteger uma secret por endpoint.
- ❌ Durante a rotação, duas secrets ficam válidas ao mesmo tempo.

## Consequências

### Positivas
- O cliente valida origem e integridade de cada requisição com ferramentas comuns.
- Um incidente de vazamento, como o já ocorrido ([09:22] Diego), é contido a um endpoint e resolvido pelo próprio cliente via rotação.

### Negativas
- A geração e o armazenamento de secrets viram ponto sensível. Exigem revisão de segurança de pelo menos 2 dias úteis antes do deploy ([09:46] Sofia).
- A rotação adiciona estado (secret anterior com validade) e um fluxo a mais na API.
- A proteção depende de o cliente de fato verificar a assinatura do lado dele.

### Trade-off explícito
Aceita-se **mais estado e complexidade de gestão de chaves** (uma secret por endpoint, mais a rotação) em troca de **isolamento de vazamentos e troca de chave sem interrupção**.

## Referências

- `src/middlewares/validate.middleware.ts`: validação de entrada com Zod, onde a regra de URL HTTPS será aplicada.
- `src/shared/logger/index.ts`: redaction de campos sensíveis nos logs, relevante para não registrar secrets.
- Transcrição: [09:02] Marcos, [09:03] Sofia, [09:19] Sofia, [09:20] Sofia, [09:20] Bruno, [09:21] Sofia, [09:21] Bruno, [09:22] Diego, [09:22] Sofia, [09:23] Sofia, [09:31] Marcos, [09:44] Diego, [09:46] Sofia.
