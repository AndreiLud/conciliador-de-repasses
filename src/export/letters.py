"""Letters to restaurants and weekly executive summaries.

Structure, table and next step are deterministic. The explanatory
paragraphs come from the language model when it is on and its text passes
the checks; otherwise they come from the deterministic descriptions.
"""
from __future__ import annotations

from datetime import timedelta

from .. import config
from ..money import format_brl
from ..reconciliation.classify import TIPO_LABELS
from ..reconciliation.explain import Context, br_date, describe, describe_plain, week_label


def next_payment(wid: str):
    return config.payment_date(wid) + timedelta(days=7)


def letter_facts(rid: str, wid: str, items: list, review_count: int, ctx: Context) -> dict:
    rep_id = f"REP-{wid.replace('-', '')}-{rid}"
    total = int(ctx.repasses.at[rep_id, "valor_total"]) if rep_id in ctx.repasses.index else None
    net = sum(d.valor_centavos for d in items)
    diffs = []
    for d in items:
        diffs.append({
            "tipo": TIPO_LABELS[d.tipo],
            "referencia": (d.pedidos[0] if len(d.pedidos) == 1 else f"{len(d.pedidos)} pedidos") if d.pedidos
                          else (d.repasse_id or d.chave),
            "valor": format_brl(abs(d.valor_centavos)),
            "efeito": "o restaurante recebeu a mais" if d.valor_centavos > 0 else "o restaurante recebeu a menos",
            "o_que_aconteceu": describe(d, ctx),
        })
    return {
        "restaurante": ctx.name(rid),
        "periodo": week_label(wid),
        "repasse": rep_id,
        "data_do_pagamento": br_date(config.payment_date(wid)),
        "valor_do_repasse": format_brl(total) if total is not None else "sem repasse",
        "diferencas": diffs,
        "quantidade_de_diferencas": len(diffs),
        "acerto_no_proximo_repasse": format_brl(abs(net)),
        "sentido_do_acerto": ("crédito para o restaurante" if net < 0 else
                              "desconto para o restaurante" if net > 0 else "sem valor a acertar"),
        "data_do_proximo_repasse": br_date(next_payment(wid)),
        "casos_ainda_em_analise": review_count,
    }


def llm_letter_facts(facts: dict, items: list, ctx: Context) -> dict:
    """What the model sees: causes in plain words, no amounts."""
    return {
        "restaurante": facts["restaurante"], "periodo": facts["periodo"],
        "diferencas": [{"tipo": TIPO_LABELS[d.tipo],
                        "efeito": "o restaurante recebeu a mais" if d.valor_centavos > 0 else "o restaurante recebeu a menos",
                        "o_que_aconteceu": describe_plain(d, ctx)} for d in items],
    }


def fallback_paragraphs(facts: dict) -> list[str]:
    items = [d["o_que_aconteceu"] for d in facts["diferencas"]]
    if len(items) <= 4:
        return items
    return items[:3] + [f"As outras {len(items) - 3} diferenças estão na tabela acima."]


def render_letter(facts: dict, paragraphs: list[str]) -> str:
    rows = "\n".join(f"| {d['referencia']} | {d['tipo']} | {d['valor']} | "
                     f"{'Recebido a mais' if 'a mais' in d['efeito'] else 'Recebido a menos'} |"
                     for d in facts["diferencas"])
    n = len(facts["diferencas"])
    found = "uma diferença" if n == 1 else f"{n} diferenças"
    if facts["sentido_do_acerto"] == "crédito para o restaurante":
        step = (f"Vamos creditar {facts['acerto_no_proximo_repasse']} no próximo repasse, previsto para "
                f"{facts['data_do_proximo_repasse']}.")
    elif facts["sentido_do_acerto"] == "desconto para o restaurante":
        step = (f"O valor de {facts['acerto_no_proximo_repasse']} será compensado no próximo repasse, previsto para "
                f"{facts['data_do_proximo_repasse']}.")
    else:
        step = "As diferenças se compensam e nada muda no próximo repasse."
    review = ""
    if facts["casos_ainda_em_analise"]:
        review = ("\n\nOutros lançamentos desta semana ainda estão em análise. Se algum deles mudar valores, "
                  "você recebe uma nova mensagem.")
    body = "\n\n".join(paragraphs)
    return (f"**Assunto:** Conferência do repasse da semana {facts['periodo']}\n\n"
            f"Olá, equipe {facts['restaurante']}.\n\n"
            f"Conferimos o repasse {facts['repasse']}, de {facts['valor_do_repasse']} no extrato, com pagamento "
            f"previsto para {facts['data_do_pagamento']}. Encontramos {found}:\n\n"
            f"| Pedido ou referência | O que aconteceu | Valor | Efeito |\n|---|---|---|---|\n{rows}\n\n"
            f"{body}\n\n{step}{review}\n\n"
            f"Se tiver qualquer dúvida, responda esta mensagem citando o repasse {facts['repasse']}.\n\n"
            f"Equipe financeira do Talher\n")


def build_letters(divs, ctx: Context, client=None, progress=None) -> list[dict]:
    from ..llm.tasks import write_letter

    groups: dict[tuple, list] = {}
    reviews: dict[tuple, int] = {}
    for d in divs:
        if not d.restaurante_id or not d.semana:
            continue
        if d.status == "confirmada":
            groups.setdefault((d.restaurante_id, d.semana), []).append(d)
        elif d.status == "revisao":
            reviews[(d.restaurante_id, d.semana)] = reviews.get((d.restaurante_id, d.semana), 0) + 1
    letters = []
    ordered = sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    for n, ((rid, wid), items) in enumerate(ordered, 1):
        if progress:
            progress(n, len(ordered))
        items = sorted(items, key=lambda d: -abs(d.valor_centavos))
        facts = letter_facts(rid, wid, items, reviews.get((rid, wid), 0), ctx)
        source, problems, attempts = "modelo_fixo", "", 0
        paragraphs = fallback_paragraphs(facts)
        # Letter text by the model is off by default: in a human review of 20 letters written by the 2B
        # model, 12 had a wrong or invented fact (project_docs/revisao_cartas_ia.csv). LETTERS_AI=1 turns it on.
        if client is not None and config.env("LETTERS_AI") == "1":
            res = write_letter(client, llm_letter_facts(facts, items, ctx))
            attempts = res.get("tentativas", 0)
            if res.get("ok"):
                paragraphs, source = res["paragrafos"], "ia"
            else:
                problems = res.get("motivo", "")
        letters.append({
            "restaurante_id": rid, "semana": wid, "repasse_id": facts["repasse"], "restaurante": facts["restaurante"],
            "texto": render_letter(facts, paragraphs), "fonte_texto": source, "tentativas_ia": attempts,
            "problemas_ia": problems, "revisar": True,
            "divergencias": [d.div_id for d in items], "fatos": facts,
        })
    return letters


def summary_facts(wid: str, con, divs) -> dict:
    row = con.sql(f"SELECT * FROM summary_by_week WHERE semana = '{wid}'").df().iloc[0]
    conf = [d for d in divs if d.semana == wid and d.status == "confirmada"]
    by_type: dict[str, list] = {}
    for d in conf:
        by_type.setdefault(d.tipo, []).append(d)
    top = sorted(by_type.items(), key=lambda kv: -sum(abs(x.valor_centavos) for x in kv[1]))[:4]
    return {
        "semana": week_label(wid),
        "repasses_conferidos": int(row["repasses"]),
        "valor_total_repassado": format_brl(int(row["total_repassado"])),
        "divergencias_confirmadas": int(row["divergencias"]),
        "restaurantes_afetados": int(row["restaurantes_afetados"]),
        "restaurantes_receberam_a_mais": format_brl(int(row["a_mais_restaurante"])),
        "restaurantes_receberam_a_menos": format_brl(int(row["a_menos_restaurante"])),
        "tipos_que_mais_pesaram": [{"tipo": TIPO_LABELS[t], "casos": len(v),
                                    "valor": format_brl(sum(abs(x.valor_centavos) for x in v))} for t, v in top],
        "casos_em_revisao_humana": int(row["em_revisao"]),
        "classificadas_por_regra": sum(1 for d in conf if d.classificado_por in ("regra", "regra_base")),
        "classificadas_pela_ia": sum(1 for d in conf if d.classificado_por == "ia"),
    }


def reading_facts(f: dict, wid: str, divs) -> dict:
    """What the model sees for the weekly reading: names and order only, no numbers to copy."""
    conf = [d for d in divs if d.semana == wid and d.status == "confirmada"]
    by_type: dict[str, list] = {}
    for d in conf:
        by_type.setdefault(TIPO_LABELS[d.tipo], []).append(d)
    by_value = sorted(by_type, key=lambda t: -sum(abs(x.valor_centavos) for x in by_type[t]))
    by_count = sorted(by_type, key=lambda t: -len(by_type[t]))
    more = sum(d.valor_centavos for d in conf if d.valor_centavos > 0)
    less = -sum(d.valor_centavos for d in conf if d.valor_centavos < 0)
    return {
        "tipos_do_maior_para_o_menor_valor": by_value,
        "tipo_com_mais_casos": by_count[0] if by_count else None,
        "lado_com_mais_dinheiro": ("restaurantes receberam a mais" if more > less else
                                   "restaurantes receberam a menos" if less > more else "equilibrado"),
        "ha_casos_em_revisao_humana": f["casos_em_revisao_humana"] > 0,
    }


def fallback_summary(f: dict) -> tuple[str, list[str]]:
    title = "Resumo da conciliação de repasses"
    tipos = "; ".join(f"{t['tipo'].lower()} ({t['casos']} {'caso' if t['casos'] == 1 else 'casos'}, {t['valor']})"
                      for t in f["tipos_que_mais_pesaram"])
    p1 = (f"Conferimos {f['repasses_conferidos']} repasses, que somam {f['valor_total_repassado']}. Encontramos "
          f"{f['divergencias_confirmadas']} divergências em {f['restaurantes_afetados']} restaurantes.")
    p2 = (f"Os restaurantes receberam {f['restaurantes_receberam_a_mais']} a mais e "
          f"{f['restaurantes_receberam_a_menos']} a menos do que deviam. Pesaram mais: {tipos}.")
    n_rev = f["casos_em_revisao_humana"]
    p3 = ("Nenhum caso espera revisão humana nesta semana." if n_rev == 0 else
          "Um caso espera revisão humana antes de qualquer contato com o restaurante." if n_rev == 1 else
          f"{n_rev} casos esperam revisão humana antes de qualquer contato com o restaurante.")
    return title, [p1, p2, p3]


def render_summary(f: dict, paragraphs: list[str], reading: list[str] | None, reading_title: str | None) -> str:
    rows = "\n".join(f"| {t['tipo']} | {t['casos']} | {t['valor']} |" for t in f["tipos_que_mais_pesaram"])
    body = "\n\n".join(paragraphs)
    read = ""
    if reading:
        read = f"\n\n## Leitura da semana: {reading_title}\n\n" + "\n\n".join(reading)
    return (f"# Resumo da conciliação de repasses\n\nSemana {f['semana']}\n\n{body}{read}"
            f"\n\n| Indicador | Valor |\n|---|---|\n"
            f"| Repasses conferidos | {f['repasses_conferidos']} |\n"
            f"| Total repassado | {f['valor_total_repassado']} |\n"
            f"| Divergências confirmadas | {f['divergencias_confirmadas']} |\n"
            f"| Restaurantes afetados | {f['restaurantes_afetados']} |\n"
            f"| Restaurantes receberam a mais | {f['restaurantes_receberam_a_mais']} |\n"
            f"| Restaurantes receberam a menos | {f['restaurantes_receberam_a_menos']} |\n"
            f"| Casos em revisão humana | {f['casos_em_revisao_humana']} |\n\n"
            f"| Tipo | Casos | Valor |\n|---|---|---|\n{rows}\n")


def build_summaries(con, divs, client=None) -> list[dict]:
    """Numbers come from the code; the model, when on, adds a short reading without numbers."""
    from ..llm.tasks import write_summary

    out = []
    for wid in config.week_ids():
        f = summary_facts(wid, con, divs)
        title, paragraphs = fallback_summary(f)
        reading, reading_title, source, problems = None, None, "modelo_fixo", ""
        # The weekly reading by the model is off by default: in the test, the 2B model stated wrong
        # facts even without numbers (see project_docs/evaluation.md). SUMMARY_AI=1 turns it on.
        if client is not None and config.env("SUMMARY_AI") == "1":
            res = write_summary(client, reading_facts(f, wid, divs))
            if res.get("ok"):
                reading, reading_title, source = res["paragrafos"], res["titulo"], "ia"
            else:
                problems = res.get("motivo", "")
        out.append({"semana": wid, "titulo": title, "texto": render_summary(f, paragraphs, reading, reading_title),
                    "paragrafos": paragraphs, "leitura": reading, "titulo_leitura": reading_title,
                    "fonte_texto": source, "problemas_ia": problems, "fatos": f})
    return out
