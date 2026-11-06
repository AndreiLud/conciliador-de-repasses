"""Measures the engine against the answer key.

Definitions (also in project_docs/evaluation.md):

* a planted error is *detected* when some divergence (confirmed or in the
  review queue) has the same key;
* it is *caught automatically* when that divergence is confirmed with the
  right type, without human review;
* precision counts confirmed divergences whose key and type match an error;
* a trap is a *false positive* when a confirmed divergence points to it, and
  costs analyst time (but not a wrong letter) when it lands in review.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import pandas as pd

from .. import config
from ..reconciliation.classify import ERROR_TYPES


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def load_answer_key(answer_dir=config.ANSWER_KEY_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    g = pd.read_csv(answer_dir / "gabarito.csv", dtype={"chave": str})
    a = pd.read_csv(answer_dir / "armadilhas.csv", dtype={"chave": str})
    return g, a


def ambiguous_truth(d, gab_by_key: dict) -> str | None:
    if d.familia == "estorno_ausente_dono_indefinido":
        return "estorno_nao_descontado" if d.chave in gab_by_key else "sem_divergencia"
    row = gab_by_key.get(d.chave) or gab_by_key.get(f"{d.restaurante_id}|{d.semana}")
    return row["tipo"] if row else "sem_divergencia"


def outcome(tipo: str | None, status: str) -> str:
    if status == "revisao" or tipo is None:
        return "revisao"
    if status == "descartada":
        return "sem_divergencia"
    return tipo


def evaluate(divs, gab: pd.DataFrame, traps: pd.DataFrame, ambiguous_snapshot: list[dict] | None = None) -> dict:
    gab_by_key = {r["chave"]: r for r in gab.to_dict("records")}
    trap_by_key = {r["chave"]: r for r in traps.to_dict("records")}
    flagged = [d for d in divs if d.status in ("confirmada", "revisao")]
    confirmed = [d for d in divs if d.status == "confirmada"]

    flagged_keys = {d.chave for d in flagged}
    detected = [k for k in gab_by_key if k in flagged_keys]
    conf_by_key = {d.chave: d for d in confirmed}
    auto_ok = [k for k, r in gab_by_key.items() if k in conf_by_key and conf_by_key[k].tipo == r["tipo"]]
    tp_conf = [d for d in confirmed if d.chave in gab_by_key and gab_by_key[d.chave]["tipo"] == d.tipo]

    per_type = {}
    for t in ERROR_TYPES:
        truth = [k for k, r in gab_by_key.items() if r["tipo"] == t]
        pred = [d for d in confirmed if d.tipo == t]
        tp = [d for d in pred if d.chave in gab_by_key and gab_by_key[d.chave]["tipo"] == t]
        det = [k for k in truth if k in flagged_keys]
        per_type[t] = {
            "casos": len(truth),
            "detectados": len(det),
            "confirmados_certos": len(tp),
            "confirmados": len(pred),
            "precisao": _ratio(len(tp), len(pred)),
            "revocacao": _ratio(len(tp), len(truth)),
            "revocacao_deteccao": _ratio(len(det), len(truth)),
            "valor_centavos": int(sum(r["valor_centavos"] for k, r in gab_by_key.items() if r["tipo"] == t)),
            "valor_a_mais_centavos": int(sum(r["valor_centavos"] for r in gab_by_key.values()
                                             if r["tipo"] == t and r["valor_centavos"] > 0)),
            "valor_a_menos_centavos": int(-sum(r["valor_centavos"] for r in gab_by_key.values()
                                               if r["tipo"] == t and r["valor_centavos"] < 0)),
        }

    trap_stats = defaultdict(lambda: {"casos": 0, "falso_positivo": 0, "em_revisao": 0})
    for k, r in trap_by_key.items():
        s = trap_stats[r["tipo"]]
        s["casos"] += 1
        if k in conf_by_key:
            s["falso_positivo"] += 1
        elif k in flagged_keys:
            s["em_revisao"] += 1
    for s in trap_stats.values():
        s["taxa_falso_positivo"] = _ratio(s["falso_positivo"], s["casos"])
    total_traps = sum(s["casos"] for s in trap_stats.values())
    total_fp = sum(s["falso_positivo"] for s in trap_stats.values())
    total_trap_review = sum(s["em_revisao"] for s in trap_stats.values())

    unmatched_conf = [d for d in confirmed if d.chave not in gab_by_key]
    fp_unknown = [d for d in unmatched_conf if d.chave not in trap_by_key]

    true_plus = int(gab.loc[gab["valor_centavos"] > 0, "valor_centavos"].sum())
    true_minus = int(-gab.loc[gab["valor_centavos"] < 0, "valor_centavos"].sum())
    found_plus = int(sum(conf_by_key[k].valor_centavos for k in auto_ok if conf_by_key[k].valor_centavos > 0))
    found_minus = int(-sum(conf_by_key[k].valor_centavos for k in auto_ok if conf_by_key[k].valor_centavos < 0))
    value_exact = sum(1 for k in auto_ok if conf_by_key[k].valor_centavos == gab_by_key[k]["valor_centavos"])

    # Ambiguous cases: rules-only baseline against the final answer.
    amb_rows = []
    for d in (ambiguous_snapshot or []):
        amb_rows.append(d)
    amb = summarize_ambiguous(amb_rows)

    by_who = Counter(d.classificado_por for d in confirmed)
    return {
        "erros_plantados": len(gab_by_key),
        "divergencias_sinalizadas": len(flagged),
        "divergencias_confirmadas": len(confirmed),
        "em_revisao": len(flagged) - len(confirmed),
        "deteccao": {
            "revocacao": _ratio(len(detected), len(gab_by_key)),
            "precisao": _ratio(sum(1 for d in flagged if d.chave in gab_by_key), len(flagged)),
        },
        "automatico": {
            "revocacao": _ratio(len(auto_ok), len(gab_by_key)),
            "precisao": _ratio(len(tp_conf), len(confirmed)),
            "acertos": len(auto_ok),
            "valor_exato": value_exact,
        },
        "confirmadas_por": dict(by_who),
        "por_tipo": per_type,
        "armadilhas": {"casos": total_traps, "falso_positivo": total_fp, "em_revisao": total_trap_review,
                       "taxa_falso_positivo": _ratio(total_fp, total_traps), "por_tipo": dict(trap_stats)},
        "confirmadas_fora_do_gabarito": len(unmatched_conf),
        "confirmadas_sem_explicacao": len(fp_unknown),
        "valor": {"a_mais_restaurante_real": true_plus, "a_menos_restaurante_real": true_minus,
                  "a_mais_restaurante_achado": found_plus, "a_menos_restaurante_achado": found_minus},
        "ambiguos": amb,
    }


def summarize_ambiguous(rows: list[dict]) -> dict:
    """rows: one per ambiguous case with truth, baseline outcome and final outcome."""
    if not rows:
        return {"casos": 0}
    out = {"casos": len(rows)}
    for who in ("regra_base", "ia_sozinha", "ia"):
        decided = [r for r in rows if r[who] != "revisao"]
        right = [r for r in decided if r[who] == r["verdade"]]
        out[who] = {"acertos": len(right), "erros": len(decided) - len(right),
                    "revisao": len(rows) - len(decided),
                    "acuracia_decididos": _ratio(len(right), len(decided)),
                    "acerto_automatico": _ratio(len(right), len(rows))}
    fam = defaultdict(list)
    for r in rows:
        fam[r["familia"]].append(r)
    out["por_familia"] = {}
    for f, rs in fam.items():
        entry = {"casos": len(rs)}
        for who in ("regra_base", "ia_sozinha", "ia"):
            decided = [r for r in rs if r[who] != "revisao"]
            right = [r for r in decided if r[who] == r["verdade"]]
            entry[who] = {"acertos": len(right), "erros": len(decided) - len(right), "revisao": len(rs) - len(decided)}
        out["por_familia"][f] = entry
    return out


def ambiguous_rows(divs_before_aggregation, gab: pd.DataFrame) -> list[dict]:
    gab_by_key = {r["chave"]: r for r in gab.to_dict("records")}
    rows = []
    for d in divs_before_aggregation:
        if not d.opcoes:
            continue
        base = d.tipo_regra_base
        base_outcome = "revisao" if base is None or base == "outro" else base
        rows.append({"div_id": d.div_id, "familia": d.familia, "chave": d.chave,
                     "verdade": ambiguous_truth(d, gab_by_key), "regra_base": base_outcome,
                     "ia_sozinha": (d.ia or {}).get("resultado_ia_sozinha", "revisao"),
                     "ia": outcome(d.tipo, d.status) if d.ia is not None else "revisao",
                     "confianca_ia": d.confianca, "status": d.status})
    return rows
