"""Automatic checks over the final letters and summaries."""
from __future__ import annotations

from ..llm.checks import check_numbers, check_style


def check_letters(letters: list, summaries: list) -> dict:
    total = len(letters)
    by_source = {"ia": 0, "modelo_fixo": 0}
    first_try = 0
    style_problems, number_problems = 0, 0
    for l in letters:
        by_source[l["fonte_texto"]] = by_source.get(l["fonte_texto"], 0) + 1
        if l["fonte_texto"] == "ia" and l["tentativas_ia"] == 1:
            first_try += 1
        style_problems += bool(check_style(l["texto"]))
        number_problems += bool(check_numbers(l["texto"], l["fatos"] | {"repasse": l["repasse_id"]}))
    s_ai = sum(1 for s in summaries if s["fonte_texto"] == "ia")
    s_style = sum(bool(check_style(s["texto"])) for s in summaries)
    s_numbers = sum(bool(check_numbers(s["texto"], s["fatos"])) for s in summaries)
    return {
        "total": total, "texto_da_ia": by_source.get("ia", 0), "modelo_fixo": by_source.get("modelo_fixo", 0),
        "ia_aprovada_na_primeira": first_try,
        "ia_aprovada_na_segunda": by_source.get("ia", 0) - first_try,
        "cartas_finais_com_problema_de_estilo": style_problems,
        "cartas_finais_com_numero_fora_dos_dados": number_problems,
        "resumos": len(summaries), "resumos_com_leitura_da_ia": s_ai,
        "resumos_com_problema": s_style + s_numbers,
    }
