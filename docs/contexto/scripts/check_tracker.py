"""Valida docs/TRACKER.md contra TRANSCRICAO.md e o código. Uso: python check_tracker.py <raiz-do-repo>"""
import os
import re
import sys

root = sys.argv[1]
transcript = open(os.path.join(root, "TRANSCRICAO.md"), encoding="utf-8").read()
spoken = set(re.findall(r"^\[(\d\d:\d\d)\] (\w+):", transcript, re.M))

rows = []
for line in open(os.path.join(root, "docs", "TRACKER.md"), encoding="utf-8"):
    if not line.startswith("| ") or line.startswith("| ID") or line.startswith("| ---"):
        continue
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    rows.append(cells)

errors = []
ids = set()
n_tx = n_code = 0
for cells in rows:
    if len(cells) != 6:
        errors.append(f"colunas != 6: {cells[0]}")
        continue
    rid, doc, _tipo, _conteudo, fonte, loc = cells
    if rid in ids:
        errors.append(f"ID duplicado: {rid}")
    ids.add(rid)
    if not os.path.exists(os.path.join(root, doc.strip("`"))):
        errors.append(f"{rid}: documento inexistente {doc}")
    if fonte == "TRANSCRICAO":
        m = re.fullmatch(r"\[(\d\d:\d\d)\] (\w+)", loc)
        if not m:
            errors.append(f"{rid}: localização fora do formato: {loc}")
        elif (m.group(1), m.group(2)) not in spoken:
            errors.append(f"{rid}: {loc} não existe na transcrição")
        else:
            n_tx += 1
    elif fonte == "CODIGO":
        path = loc.strip("`")
        if not os.path.exists(os.path.join(root, path)):
            errors.append(f"{rid}: arquivo inexistente {path}")
        else:
            n_code += 1
    else:
        errors.append(f"{rid}: fonte inválida {fonte}")

total = len(rows)
print(f"linhas: {total}  TRANSCRICAO válidas: {n_tx} ({n_tx / total:.0%})  CODIGO válidas: {n_code}")
print("\n".join(errors) if errors else "nenhum erro")
