"""Confere os critérios de aceite mensuráveis do desafio. Uso: python check_acceptance.py <raiz-do-repo>"""
import glob
import os
import re
import sys

root = sys.argv[1]


def read(rel):
    return open(os.path.join(root, rel), encoding="utf-8").read()


results = []


def check(name, ok, info=""):
    results.append((ok, name, info))


def headings(text):
    return [h.lower() for h in re.findall(r"^#{2,4} (.+)$", text, re.M)]


def has_section(text, *words):
    hs = headings(text)
    return any(all(w.lower() in h for w in words) for h in hs)


# PRD
prd = read("docs/PRD.md")
for sec in [("resumo",), ("problema",), ("público",), ("objetivos", "métricas"), ("escopo",),
            ("fora de escopo",), ("requisitos funcionais",), ("requisitos não funcionais",),
            ("decisões", "trade-offs"), ("dependências",), ("riscos",), ("critérios de aceitação",),
            ("estratégia de testes",)]:
    check(f"PRD seção {'/'.join(sec)}", has_section(prd, *sec))
fr = set(re.findall(r"PRD-FR-\d+", prd))
check("PRD >= 8 RF", len(fr) >= 8, str(len(fr)))
out = prd.split("### 5.2 Fora de escopo")[1].split("## 6.")[0]
check("PRD fora de escopo >= 2 itens com timestamp", len(re.findall(r"\[\d\d:\d\d\] \w+", out)) >= 2)
risk = prd.split("## 10. Riscos")[1].split("## 11.")[0]
check("PRD riscos com Probabilidade/Impacto/Mitigação", all(w in risk for w in ["Probabilidade", "Impacto", "Mitigação"]),
      f"{risk.count(chr(10) + '| **')} riscos")

# RFC
rfc = read("docs/RFC.md")
for w in ["Autor", "Status", "Data", "Revisores"]:
    check(f"RFC metadado {w}", f"**{w}**" in rfc)
for sec in [("tl;dr",), ("contexto",), ("proposta",), ("alternativas",), ("questões em aberto",),
            ("impacto", "riscos"), ("decisões relacionadas",)]:
    check(f"RFC seção {'/'.join(sec)}", has_section(rfc, *sec))
alts = rfc.split("## 4. Alternativas")[1].split("## 5.")[0]
check("RFC >= 2 alternativas", alts.count("\n| **") >= 2, str(alts.count("\n| **")))
opens = rfc.split("## 5. Questões")[1].split("## 6.")[0]
check("RFC >= 2 questões em aberto", len(re.findall(r"^\d+\. ", opens, re.M)) >= 2)
adr_links = set(re.findall(r"\(adrs/(ADR-\d{3}[^)]*\.md)\)", rfc))
check("RFC links para >= 2 ADRs", len(adr_links) >= 2, str(len(adr_links)))
words = len(re.sub(r"```.*?```", "", rfc, flags=re.S).split())
check("RFC conciso (~2-4 páginas)", words <= 2200, f"{words} palavras")

# FDD
fdd = read("docs/FDD.md")
for sec in [("contexto",), ("objetivos técnicos",), ("escopo", "exclusões"), ("fluxos",),
            ("contratos públicos",), ("matriz de erros",), ("resiliência",), ("observabilidade",),
            ("dependências", "compatibilidade"), ("critérios de aceite",), ("riscos",),
            ("integração com o sistema existente",)]:
    check(f"FDD seção {'/'.join(sec)}", has_section(fdd, *sec))
for flow in ["outbox", "worker", "retry", "dead letter"]:
    check(f"FDD fluxo {flow}", flow.lower() in fdd.lower())
contracts = fdd.split("## 6. Contratos")[1].split("## 7.")[0]
eps = re.findall(r"^### 6\.\d `(GET|POST|PATCH|DELETE) ", contracts, re.M)
check("FDD >= 4 endpoints", len(eps) >= 4, str(len(eps)))
check("FDD exemplos request/response", contracts.count("```json") + contracts.count("```http") >= 8)
matrix = fdd.split("## 7. Matriz")[1].split("## 8.")[0]
codes = set(re.findall(r"`(WEBHOOK_[A-Z_]+)`", matrix))
check("FDD matriz WEBHOOK_*", len(codes) >= 5, str(len(codes)))
integ = fdd.split("## 10. Integração")[1].split("## 11.")[0]
paths = set(re.findall(r"`((?:src|prisma|tests)/[\w./-]+\.\w+|package\.json)`", integ))
real = [p for p in paths if os.path.exists(os.path.join(root, p))]
check("FDD integração >= 4 arquivos reais", len(real) >= 4, f"{len(real)} reais / {len(paths)} citados")
obs = fdd.split("## 9. Observabilidade")[1].split("## 10.")[0].lower()
check("FDD observabilidade métricas/logs/tracing", all(w in obs for w in ["métricas", "logs", "tracing"]))

# ADRs
adrs = sorted(glob.glob(os.path.join(root, "docs/adrs/ADR-*.md")))
check("ADRs entre 5 e 8", 5 <= len(adrs) <= 8, str(len(adrs)))
for a in adrs:
    name = os.path.basename(a)
    check(f"{name} nome", bool(re.fullmatch(r"ADR-\d{3}-[a-z0-9]+(-[a-z0-9]+)*\.md", name)))
    t = open(a, encoding="utf-8").read()
    ok = "**Status:**" in t and all(has_section(t, s) for s in ["contexto", "decisão", "alternativas consideradas", "consequências"])
    ok = ok and "positivas" in t.lower() and "negativas" in t.lower()
    check(f"{name} seções", ok)
code_ref = [a for a in adrs if re.search(r"`src/[\w./-]+`", open(a, encoding="utf-8").read())]
check("ADR referenciando código", len(code_ref) >= 1, str(len(code_ref)))
alladr = " ".join(open(a, encoding="utf-8").read().lower() for a in adrs)
topics = {"outbox": "outbox", "retry/dlq": "dead letter", "hmac": "hmac-sha256",
          "at-least-once": "at-least-once", "worker polling": "polling", "reuso": "reuso"}
covered = [k for k, v in topics.items() if v in alladr]
check("ADRs cobrem >= 5 das 6 decisões", len(covered) >= 5, ", ".join(covered))

# README
readme = read("README.md")
for sec in ["sobre o desafio", "ferramentas de ia", "workflow", "prompts customizados", "iterações e ajustes", "como navegar"]:
    check(f"README seção {sec}", has_section(readme, sec))
prompts = readme.split("## Prompts customizados")[1].split("## Iterações")[0]
check("README >= 2 prompts em bloco de código", prompts.count("```") // 2 >= 2)

# Consistência: arquivos de código citados em todos os docs existem; links relativos resolvem
docs = ["README.md", "docs/PRD.md", "docs/RFC.md", "docs/FDD.md", "docs/TRACKER.md", "docs/adrs/README.md"] + \
       [os.path.relpath(a, root) for a in adrs]
missing = set()
broken = set()
for d in docs:
    t = read(d)
    for p in re.findall(r"`((?:src|prisma|tests)/[\w./-]+?)(?::[\d-]+)?`", t):
        if "webhooks" in p or p == "src/worker.ts":
            continue
        if not os.path.exists(os.path.join(root, p)):
            missing.add(f"{d}: {p}")
    for link in re.findall(r"\]\(([^)#:]+?)(?:#[^)]*)?\)", t):
        if not os.path.exists(os.path.normpath(os.path.join(root, os.path.dirname(d), link))):
            broken.add(f"{d}: {link}")
check("Nenhum arquivo de código inexistente citado", not missing, "; ".join(sorted(missing)))
check("Links relativos resolvem", not broken, "; ".join(sorted(broken)))

for ok, name, info in results:
    print(("OK   " if ok else "FAIL ") + name + (f"  [{info}]" if info else ""))
print(f"\n{sum(r[0] for r in results)}/{len(results)} critérios OK")
