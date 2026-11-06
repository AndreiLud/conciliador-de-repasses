"""Writes the results block of README.md and README.pt-BR.md from facts.json.

The block lives between ``<!-- facts -->`` and ``<!-- /facts -->``; everything
else in the READMEs is hand written. Run after run_all.py:
    python -m src.export.readme_facts
"""
from __future__ import annotations

import json
import re

from .. import config
from ..money import format_brl


def _n(x, d=0, lang="pt"):
    s = f"{x:,.{d}f}"
    if lang == "pt":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def _pct(x, lang):
    return _n(x * 100, 1, lang) + "%"


def rows_for(f: dict, lang: str) -> list[tuple[str, str]]:
    r, h = f["resultado"], f["horas"]
    brl = format_brl  # Brazilian reais keep the Brazilian format in both languages
    if lang == "pt":
        rows = [
            ("Erros plantados detectados (revocação)", f"{_pct(r['revocacao_deteccao'], lang)} dos {f['dados']['erros_plantados']}"),
            ("Confirmados automaticamente com a causa certa", f"{r['acertos_automaticos']} de {f['dados']['erros_plantados']} ({_pct(r['revocacao_automatica'], lang)})"),
            ("Precisão das divergências confirmadas", _pct(r["precisao_automatica"], lang)),
            ("Alertas falsos nas armadilhas", f"{r['falsos_positivos']} de {_n(f['dados']['armadilhas'], 0, lang)}"),
            ("Casos na fila de revisão humana", str(r["em_revisao"])),
            ("Dinheiro achado: restaurantes receberam a menos", brl(r["valor_a_menos_centavos"])),
            ("Dinheiro achado: restaurantes receberam a mais", brl(r["valor_a_mais_centavos"])),
            ("Horas por semana economizadas (estimativa)", f"{_n(h['horas_economizadas'], 1, lang)} h ({_n(h['horas_manual'], 1, lang)} h na planilha contra {_n(h['horas_ferramenta'], 1, lang)} h)"),
            ("Tempo para conciliar o mês só com regras", f"{_n(f['execucao']['segundos_so_regras'], 0, lang)} s"),
            ("Custo de API", "R$ 0 (modelo local)"),
        ]
        amb_rows = [("Casos ambíguos, só regras", f["regras"]["ambiguos"]), ("Casos ambíguos, regra e IA local", f.get("ia_ambiguos"))]
        for label, a in amb_rows:
            if a and a.get("casos"):
                x = a["ia"] if "IA" in label else a["regra_base"]
                rows.append((label, f"{x['acertos']} certos, {x['erros']} errados e {x['revisao']} na revisão, de {a['casos']}"))
    else:
        rows = [
            ("Planted errors detected (recall)", f"{_pct(r['revocacao_deteccao'], lang)} of {f['dados']['erros_plantados']}"),
            ("Confirmed automatically with the right cause", f"{r['acertos_automaticos']} of {f['dados']['erros_plantados']} ({_pct(r['revocacao_automatica'], lang)})"),
            ("Precision of confirmed divergences", _pct(r["precisao_automatica"], lang)),
            ("False alarms on traps", f"{r['falsos_positivos']} of {f['dados']['armadilhas']}"),
            ("Cases in the human review queue", str(r["em_revisao"])),
            ("Money found: restaurants underpaid", brl(r["valor_a_menos_centavos"])),
            ("Money found: restaurants overpaid", brl(r["valor_a_mais_centavos"])),
            ("Hours saved per week (estimate)", f"{_n(h['horas_economizadas'], 1, lang)} h ({_n(h['horas_manual'], 1, lang)} h in spreadsheets vs {_n(h['horas_ferramenta'], 1, lang)} h)"),
            ("Time to reconcile the month, rules only", f"{_n(f['execucao']['segundos_so_regras'], 0, lang)} s"),
            ("API cost", "R$ 0 (local model)"),
        ]
        amb_rows = [("Ambiguous cases, rules only", f["regras"]["ambiguos"]), ("Ambiguous cases, rules and local AI", f.get("ia_ambiguos"))]
        for label, a in amb_rows:
            if a and a.get("casos"):
                x = a["ia"] if "AI" in label else a["regra_base"]
                rows.append((label, f"{x['acertos']} right, {x['erros']} wrong and {x['revisao']} sent to review, of {a['casos']}"))
    return rows


def all_strings(f: dict) -> dict:
    """Display strings stored in facts.json, so the text checker can verify the READMEs."""
    return {lang: [b for _, b in rows_for(f, lang)] for lang in ("pt", "en")}


def block(f: dict, lang: str) -> str:
    rows = rows_for(f, lang)
    if lang == "pt":
        head = "| Métrica | Resultado |\n|---|---|"
        note = ("Os números vêm de `docs/data/facts.json`, escrito por `python run_all.py`. A comparação entre regra e IA "
                "nos casos ambíguos está em `project_docs/evaluation.md`.")
    else:
        head = "| Metric | Result |\n|---|---|"
        note = ("Numbers come from `docs/data/facts.json`, written by `python run_all.py`. The rules versus AI "
                "comparison on ambiguous cases is in `project_docs/evaluation.md` (Portuguese).")
    table = head + "\n" + "\n".join(f"| {a} | {b} |" for a, b in rows)
    return f"<!-- facts -->\n{table}\n\n{note}\n<!-- /facts -->"


def main() -> None:
    facts = json.loads((config.SITE_DATA_DIR / "facts.json").read_text(encoding="utf-8"))
    for name, lang in (("README.md", "en"), ("README.pt-BR.md", "pt")):
        p = config.ROOT / name
        text = p.read_text(encoding="utf-8")
        new = re.sub(r"<!-- facts -->.*?<!-- /facts -->", lambda m: block(facts, lang), text, flags=re.S)
        p.write_text(new, encoding="utf-8")
        print(f"{name}: results block updated")


if __name__ == "__main__":
    main()
