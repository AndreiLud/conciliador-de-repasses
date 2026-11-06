"""End-to-end reconciliation: ingestion, SQL stages, bank matching, rules,
optional language model for the ambiguous cases, and aggregations."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .. import config
from ..ingestion.load import QualityLog, ingest
from .bank import match_bank
from .classify import TIPO_LABELS, Divergence, aggregate_old_plan, collect_and_classify
from .sql_runner import connect, run_stage, run_stages


@dataclass
class EngineResult:
    con: object
    tables: dict
    quality_log: QualityLog
    divergences: list[Divergence]
    bank_matches: pd.DataFrame
    timings: dict = field(default_factory=dict)
    ai_mode: str = "off"
    before_aggregation: list = field(default_factory=list)


def resolve_with_rules_only(divs: list[Divergence]) -> None:
    """Rules-only baseline for ambiguous cases."""
    for d in divs:
        if not d.ambigua:
            continue
        if d.tipo_regra_base is None:
            d.tipo, d.classificado_por, d.status = None, "revisao", "revisao"
            d.motivo_revisao = "regra sem resposta para este caso"
        elif d.tipo_regra_base == "sem_divergencia":
            d.tipo, d.classificado_por, d.status = "sem_divergencia", "regra_base", "descartada"
        elif d.tipo_regra_base == "outro":
            d.tipo, d.classificado_por, d.status = "outro", "revisao", "revisao"
        else:
            d.tipo, d.classificado_por, d.status = d.tipo_regra_base, "regra_base", "confirmada"
        d.confianca = None


OWNER_TO_TYPE = {"restaurante": "estorno_nao_descontado", "plataforma": "sem_divergencia"}


def _accept(d, tipo, by="ia"):
    d.tipo, d.classificado_por = tipo, by
    d.status = "descartada" if tipo == "sem_divergencia" else "confirmada"


def _review(d, reason, tipo=None):
    d.tipo, d.classificado_por, d.status, d.motivo_revisao = tipo, "revisao", "revisao", reason


def resolve_refund_owner(d, client) -> None:
    """Text-only cases. Policy: the model must quote the note; if the keyword rule
    has an answer and disagrees with the model, a person decides."""
    from ..llm.tasks import classify_refund_owner

    note = next(e["dados"]["nota_do_atendimento"] for e in d.evidencias if e["id"].startswith("estorno:"))
    res = classify_refund_owner(client, note)
    llm_tipo = OWNER_TO_TYPE.get(res.get("responsavel"))
    confident = bool(res.get("ok")) and llm_tipo is not None and res["confianca"] >= config.REVIEW_CONFIDENCE_THRESHOLD
    res["resultado_ia_sozinha"] = llm_tipo if confident else "revisao"
    d.ia = res
    d.confianca = res.get("confianca")
    if res.get("ok") and res.get("trecho"):
        if res["responsavel"] == "indefinido":
            d.explicacao = f'A nota do atendimento diz "{res["trecho"]}", e isso não mostra de quem foi a culpa.'
        else:
            dono = "o restaurante" if res["responsavel"] == "restaurante" else "a plataforma"
            d.explicacao = f'A nota do atendimento diz "{res["trecho"]}", o que aponta para {dono}.'
    if not res.get("ok"):
        _review(d, "a resposta da IA não passou nas checagens do código")
    elif llm_tipo is None:
        _review(d, "a IA não achou na nota de quem foi a culpa")
    elif not confident:
        _review(d, f"confiança da IA abaixo de {config.REVIEW_CONFIDENCE_THRESHOLD:.2f}".replace(".", ","), llm_tipo)
    elif d.tipo_regra_base is not None and d.tipo_regra_base != llm_tipo:
        _review(d, "a regra de palavras-chave e a IA discordam", llm_tipo)
    else:
        _accept(d, llm_tipo)


def resolve_with_llm(divs: list[Divergence], client, progress=None) -> None:
    from ..llm.tasks import classify_case

    pending = [d for d in divs if d.ambigua]
    for i, d in enumerate(pending, 1):
        if d.familia == "estorno_ausente_dono_indefinido":
            resolve_refund_owner(d, client)
        else:
            res = classify_case(client, d)
            ok = bool(res.get("ok"))
            confident = ok and res["confianca"] >= config.REVIEW_CONFIDENCE_THRESHOLD and res["tipo"] != "outro"
            res["resultado_ia_sozinha"] = res["tipo"] if confident else "revisao"
            d.ia = res
            if d.tipo_regra_base and config.env("LINES_AI") != "1":
                # Shadow mode: on legacy lines the hypothesis rule was right in every test case and the model was
                # not, so the rule decides; the model answer is kept only for the evaluation.
                _accept(d, d.tipo_regra_base, by="regra_base")
                d.confianca = None
                continue
            if not ok:
                _review(d, "a resposta da IA não passou nas checagens do código")
            else:
                # The model's free text is never shown: it got facts wrong in the test. The explanation shown
                # is built by the code from the hypothesis the model chose.
                hyp = next((h for h in d.hipoteses if h["tipo"] == res["tipo"]), None)
                d.confianca = res["confianca"]
                d.explicacao = (f"A IA escolheu a hipótese: {hyp['descricao']}." if hyp
                                else f"A IA escolheu: {TIPO_LABELS.get(res['tipo'], res['tipo']).lower()}.")
                if res["tipo"] == "outro":
                    _review(d, "a IA não reconheceu uma causa conhecida")
                elif not confident:
                    _review(d, f"confiança da IA abaixo de {config.REVIEW_CONFIDENCE_THRESHOLD:.2f}".replace(".", ","),
                            res["tipo"])
                elif d.tipo_regra_base and d.tipo_regra_base != res["tipo"]:
                    _review(d, "a regra e a IA apontam causas diferentes", res["tipo"])
                else:
                    _accept(d, res["tipo"])
        if progress:
            progress(i, len(pending), d, d.ia)


def divergences_frame(divs: list[Divergence]) -> pd.DataFrame:
    rows = []
    for d in divs:
        rows.append({"div_id": d.div_id, "familia": d.familia, "chave": d.chave, "restaurante_id": d.restaurante_id,
                     "semana": d.semana, "repasse_id": d.repasse_id, "valor_centavos": d.valor_centavos,
                     "tipo": d.tipo, "classificado_por": d.classificado_por, "confianca": d.confianca,
                     "status": d.status, "qtd_pedidos": max(1, len(d.pedidos)) if d.pedidos else 0})
    cols = ["div_id", "familia", "chave", "restaurante_id", "semana", "repasse_id", "valor_centavos", "tipo",
            "classificado_por", "confianca", "status", "qtd_pedidos"]
    df = pd.DataFrame(rows, columns=cols)
    return df.astype({"valor_centavos": "int64", "confianca": "float64", "qtd_pedidos": "int64",
                      **{c: "string" for c in cols if c not in ("valor_centavos", "confianca", "qtd_pedidos")}})


def run(raw_dir: Path = config.RAW_DIR, files: dict | None = None, ai_mode: str = "off", client=None,
        progress=None, interim_dir: Path = config.INTERIM_DIR) -> EngineResult:
    t = {}
    t0 = time.perf_counter()
    tables, qlog = ingest(raw_dir, interim_dir, files=files)
    t["ingestao_s"] = round(time.perf_counter() - t0, 2)

    t0 = time.perf_counter()
    con = connect(tables)
    run_stages(con, up_to="08_bank_candidates.sql")
    t["sql_s"] = round(time.perf_counter() - t0, 2)

    t0 = time.perf_counter()
    matches, findings = match_bank(con)
    divs = collect_and_classify(con, findings)
    t["regras_s"] = round(time.perf_counter() - t0, 2)

    t0 = time.perf_counter()
    if ai_mode == "on" and client is not None:
        resolve_with_llm(divs, client, progress)
    else:
        resolve_with_rules_only(divs)
    t["ia_classificacao_s"] = round(time.perf_counter() - t0, 2)

    before = list(divs)
    divs = aggregate_old_plan(divs)
    con.register("divergences_df", divergences_frame(divs))
    con.execute("CREATE OR REPLACE TABLE divergences AS SELECT * FROM divergences_df")
    if matches.empty:
        matches = pd.DataFrame(columns=["banco_linha_id", "repasse_id", "status"], dtype="string")
    con.register("bank_matches_df", matches)
    con.execute("CREATE OR REPLACE TABLE bank_matches AS SELECT * FROM bank_matches_df")
    for path in sorted(config.SQL_DIR.glob("09_*.sql")):
        run_stage(con, path)
    return EngineResult(con, tables, qlog, divs, matches, t, ai_mode, before)
