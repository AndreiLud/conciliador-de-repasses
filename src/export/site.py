"""Exports light JSON files for the static site (docs/data).

The site never calls an API: everything it shows comes from these files.
``facts.json`` holds every number quoted on the site and in the READMEs.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .. import config
from ..money import format_brl
from ..reconciliation.classify import TIPO_LABELS
from ..reconciliation.explain import Context, br_date, describe, week_label

HOURS_PREMISES = {
    "restaurantes_por_semana": {"valor": 200, "rotulo": "Restaurantes conferidos por semana"},
    "min_conferir_repasse": {"valor": 6, "rotulo": "Minutos para conferir um repasse na planilha"},
    "min_investigar_divergencia": {"valor": 20, "rotulo": "Minutos para investigar uma divergência na planilha"},
    "min_escrever_carta": {"valor": 15, "rotulo": "Minutos para escrever uma carta ao restaurante"},
    "min_revisar_divergencia": {"valor": 3, "rotulo": "Minutos para conferir uma divergência já explicada pela ferramenta"},
    "min_revisar_fila": {"valor": 12, "rotulo": "Minutos para resolver um caso da fila de revisão"},
    "min_revisar_carta": {"valor": 2, "rotulo": "Minutos para revisar uma carta pronta"},
}


def hours_estimate(premises: dict, per_week: dict) -> dict:
    """Same formula as docs/js/calculator.js. It is an estimate, not a measurement."""
    p = {k: v["valor"] for k, v in premises.items()}
    scale = p["restaurantes_por_semana"] / per_week["restaurantes"]
    d = per_week["divergencias"] * scale
    q = per_week["revisao"] * scale
    c = per_week["cartas"] * scale
    manual = (p["restaurantes_por_semana"] * p["min_conferir_repasse"] + (d + q) * p["min_investigar_divergencia"]
              + c * p["min_escrever_carta"]) / 60
    tool = (d * p["min_revisar_divergencia"] + q * p["min_revisar_fila"] + c * p["min_revisar_carta"]) / 60
    manual, tool = round(manual, 1), round(tool, 1)
    return {"horas_manual": manual, "horas_ferramenta": tool, "horas_economizadas": round(manual - tool, 1)}


def _bank_net(con) -> dict:
    rows = con.sql("""
        SELECT m.repasse_id, m.status, b.valor
        FROM bank_matches m JOIN stg_bank b USING (banco_linha_id)
    """).df()
    out: dict[str, int] = {}
    for r in rows.to_dict("records"):
        out[r["repasse_id"]] = out.get(r["repasse_id"], 0) - int(r["valor"])
    return out


FAMILY_LABELS = {
    "estorno_ausente_dono_indefinido": "Estorno sem responsável",
    "pedido_nao_esperado": "Pedido pago sem estar previsto",
    "estorno_nao_esperado": "Estorno sem correspondência",
    "repasse_sem_pagamento": "Repasse sem pagamento no banco",
    "banco_nao_identificado": "Pagamento não identificado no banco",
    "residuo_repasse": "Diferença sem explicação",
    "linha_pedido": "Linha do extrato com mais de uma causa possível",
    "banco_devolucao_sem_par": "Devolução no banco sem pagamento correspondente",
}


def _enrich_evidence(evs: list[dict], ctx: Context) -> list[dict]:
    """Bank and payout evidence carry only ids in the engine; add the fields for display."""
    out = []
    for e in evs:
        e = dict(e)
        if e["id"].startswith("banco:") and not e.get("dados"):
            bl = e["id"].split(":", 1)[1]
            if bl in ctx.bank.index:
                b = ctx.bank.loc[bl]
                e["dados"] = {"data": br_date(b["data"]), "historico": b["historico"],
                              "valor": format_brl(int(b["valor"]), signed=True)}
        elif e["id"].startswith("repasse:") and e["id"].split(":", 1)[1] in ctx.repasses.index \
                and not e.get("dados", {}).get("valor_total"):
            rp = ctx.repasses.loc[e["id"].split(":", 1)[1]]
            e["dados"] = {**e.get("dados", {}), "valor_total": format_brl(int(rp["valor_total"])),
                          "data_prevista": br_date(rp["data_pagamento_prevista"])}
        out.append(e)
    return out


def divergence_payload(d, ctx: Context) -> dict:
    return {
        "id": d.div_id, "restaurante_id": d.restaurante_id, "nome": ctx.name(d.restaurante_id) if d.restaurante_id else "",
        "semana": d.semana, "repasse_id": d.repasse_id, "tipo": d.tipo, "tipo_label": (TIPO_LABELS.get(d.tipo, d.tipo) if d.status == "confirmada" and d.tipo
                                        else FAMILY_LABELS.get(d.familia) or TIPO_LABELS.get(d.tipo or "", "Sem sugestão")),
        "sugestao": TIPO_LABELS.get(d.tipo) if d.status == "revisao" and d.tipo and d.ia else None,
        "valor_centavos": d.valor_centavos,
        "direcao": "a_mais" if d.valor_centavos > 0 else "a_menos",
        "status": d.status, "classificado_por": d.classificado_por, "confianca": d.confianca,
        "descricao": describe(d, ctx), "explicacao_ia": (d.explicacao or None) if d.ia else None,
        "motivo_revisao": d.motivo_revisao, "familia": d.familia,
        "regra_base": d.tipo_regra_base, "ambigua": bool(d.opcoes) or d.classificado_por == "ia",
        "pedidos": d.pedidos[:12], "qtd_pedidos": len(d.pedidos),
        "evidencias": _enrich_evidence(d.evidencias[:8], ctx), "hipoteses": d.hipoteses[:6],
    }


def export(result, metrics_rules: dict, metrics_ai: dict | None, letters: list, summaries: list,
           llm_info: dict, run_info: dict, ambiguous: list, out_dir: Path = config.SITE_DATA_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    con, divs = result.con, result.divergences
    ctx = Context(con)
    bank_net = _bank_net(con)
    overview = con.sql("SELECT * FROM repasse_overview").df()
    letters_by = {(l["restaurante_id"], l["semana"]): l for l in letters}
    summaries_by = {s["semana"]: s for s in summaries}
    final = metrics_ai or metrics_rules

    weeks_index = []
    for wid in config.week_ids():
        wdivs = [d for d in divs if d.semana == wid and d.status in ("confirmada", "revisao")]
        conf_value: dict[str, int] = {}
        for d in wdivs:
            if d.status == "confirmada" and d.repasse_id and d.tipo not in ("transferencia_divergente", "repasse_duplicado"):
                conf_value[d.repasse_id] = conf_value.get(d.repasse_id, 0) + d.valor_centavos
        reps = []
        for r in overview[overview["semana"] == wid].to_dict("records"):
            rid = r["restaurante_id"]
            reps.append({
                "repasse_id": r["repasse_id"], "restaurante_id": rid, "nome": ctx.name(rid),
                "cidade": str(ctx.restaurants.at[rid, "cidade"]), "categoria": str(ctx.restaurants.at[rid, "categoria"]),
                "total_extrato": int(r["total_extrato"]),
                "total_devido": int(r["total_extrato"]) - conf_value.get(r["repasse_id"], 0),
                "total_banco": bank_net.get(r["repasse_id"], 0),
                "pedidos": int(r["qtd_pedidos"]), "ajustes": int(r["qtd_ajustes"]),
                "divergencias": int(r["divergencias"]), "em_revisao": int(r["em_revisao"]),
            })
        s = summaries_by[wid]
        payload = {
            "semana": wid, "rotulo": week_label(wid), "data_pagamento": br_date(config.payment_date(wid)),
            "resumo": {"titulo": s["titulo"], "paragrafos": s["paragrafos"], "fonte_texto": s["fonte_texto"],
                       "leitura": s.get("leitura"), "titulo_leitura": s.get("titulo_leitura"), "fatos": s["fatos"]},
            "repasses": sorted(reps, key=lambda x: (-x["divergencias"] - x["em_revisao"], x["nome"])),
            "divergencias": [divergence_payload(d, ctx) for d in sorted(wdivs, key=lambda x: -abs(x.valor_centavos))],
            "cartas": {rid: {"texto": l["texto"], "fonte_texto": l["fonte_texto"]}
                       for (rid, w), l in letters_by.items() if w == wid},
        }
        (out_dir / f"semana_{wid}.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                                                    encoding="utf-8")
        weeks_index.append({"semana": wid, "rotulo": week_label(wid), "repasses": len(reps),
                            "divergencias": sum(1 for d in wdivs if d.status == "confirmada"),
                            "em_revisao": sum(1 for d in wdivs if d.status == "revisao")})

    n_weeks = config.N_WEEKS
    flagged_conf = final["divergencias_confirmadas"]
    per_week = {"restaurantes": int(result.tables["restaurants"].shape[0]),
                "divergencias": round(flagged_conf / n_weeks, 2),
                "revisao": round(final["em_revisao"] / n_weeks, 2),
                "cartas": round(len(letters) / n_weeks, 2)}
    hours = hours_estimate(HOURS_PREMISES, per_week)
    tables = result.tables
    facts = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y"),
        "marketplace": config.MARKETPLACE_NAME,
        "periodo": {"inicio": br_date(config.PERIOD_START), "fim": br_date(config.week_bounds(config.week_ids()[-1])[1]),
                    "semanas": n_weeks},
        "dados": {
            "restaurantes": int(tables["restaurants"].shape[0]), "pedidos": int(tables["orders"].shape[0]),
            "linhas_extrato": int(tables["statement"].shape[0]), "repasses": int(tables["repasses"].shape[0]),
            "lancamentos_banco": int(tables["bank"].shape[0]), "estornos": int(tables["refunds"].shape[0]),
            "valor_repassado_centavos": int(tables["repasses"]["valor_total"].sum()),
            "erros_plantados": final["erros_plantados"], "armadilhas": final["armadilhas"]["casos"],
            "verificacoes_qualidade": len(result.quality_log.entries),
        },
        "resultado": {
            "revocacao_deteccao": final["deteccao"]["revocacao"], "precisao_deteccao": final["deteccao"]["precisao"],
            "revocacao_automatica": final["automatico"]["revocacao"], "precisao_automatica": final["automatico"]["precisao"],
            "acertos_automaticos": final["automatico"]["acertos"],
            "divergencias_confirmadas": final["divergencias_confirmadas"], "em_revisao": final["em_revisao"],
            "falsos_positivos": final["armadilhas"]["falso_positivo"],
            "armadilhas_em_revisao": final["armadilhas"]["em_revisao"],
            "taxa_falso_positivo": final["armadilhas"]["taxa_falso_positivo"],
            "valor_a_mais_centavos": final["valor"]["a_mais_restaurante_achado"],
            "valor_a_menos_centavos": final["valor"]["a_menos_restaurante_achado"],
            "valor_a_mais_real_centavos": final["valor"]["a_mais_restaurante_real"],
            "valor_a_menos_real_centavos": final["valor"]["a_menos_restaurante_real"],
            "cartas": len(letters), "restaurantes_com_carta": len({l["restaurante_id"] for l in letters}),
        },
        "regras": {
            "revocacao_automatica": metrics_rules["automatico"]["revocacao"],
            "precisao_automatica": metrics_rules["automatico"]["precisao"],
            "falsos_positivos": metrics_rules["armadilhas"]["falso_positivo"],
            "em_revisao": metrics_rules["em_revisao"],
            "ambiguos": metrics_rules["ambiguos"],
        },
        "ia": llm_info,
        "ia_ambiguos": (metrics_ai or {}).get("ambiguos"),
        "execucao": run_info,
        "constantes": {
            "limiar_confianca": config.REVIEW_CONFIDENCE_THRESHOLD,
            "tolerancia_linha": config.TOLERANCE_LINE_CENTS,
            "tolerancia_repasse": config.TOLERANCE_REPASSE_CENTS,
            "janela_banco_dias": config.BANK_DATE_WINDOW_DAYS,
            "parametros_modelo_bilhoes": 2,
        },
        "horas": {"premissas": HOURS_PREMISES, "por_semana_nos_dados": per_week, **hours},
    }
    review_csv = config.PROJECT_DOCS_DIR / "revisao_cartas_ia.csv"
    if review_csv.exists():
        import csv
        rows = list(csv.DictReader(review_csv.open(encoding="utf-8")))
        facts["revisao_cartas_ia"] = {"amostra": len(rows),
                                      "corretas": sum(r["avaliacao"] == "correta" for r in rows),
                                      "confusas": sum(r["avaliacao"] == "confusa" for r in rows),
                                      "erradas": sum(r["avaliacao"] == "errada" for r in rows)}
    from .readme_facts import all_strings
    facts["formatado"] = all_strings(facts)
    (out_dir / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "weeks.json").write_text(json.dumps(weeks_index, ensure_ascii=False), encoding="utf-8")
    metrics_payload = {"regras": metrics_rules, "ia": metrics_ai, "ambiguos": ambiguous,
                       "tipos": {k: v for k, v in TIPO_LABELS.items()}}
    (out_dir / "metrics.json").write_text(json.dumps(metrics_payload, ensure_ascii=False, separators=(",", ":")),
                                          encoding="utf-8")
    review = [divergence_payload(d, ctx) for d in divs if d.status == "revisao"]
    (out_dir / "fila_revisao.json").write_text(json.dumps(review, ensure_ascii=False, separators=(",", ":")),
                                               encoding="utf-8")
    (out_dir / "qualidade.json").write_text(json.dumps(result.quality_log.to_records(), ensure_ascii=False),
                                            encoding="utf-8")
    return facts
