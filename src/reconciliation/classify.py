"""Turns detection findings into classified divergences.

Rules classify every case where the evidence points to a single cause. The
remaining cases are *ambiguous* and carry:

* the evidence (order, statement line, contract, refund, bank) with ids;
* the hypotheses computed by code, each with the net amount it would
  produce and whether it reproduces the statement;
* the allowed answers;
* a rules-only fallback answer (``tipo_regra_base``) used as the baseline
  when we measure what the language model adds.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

import pandas as pd

from .. import config
from ..money import apply_rate, format_brl, format_pct
from .bank import BankFinding

TIPO_LABELS = {
    "comissao_taxa_errada": "Comissão com taxa errada",
    "comissao_plano_antigo": "Plano antigo aplicado depois da troca",
    "taxa_pagamento_errada": "Taxa de pagamento errada",
    "cupom_plataforma_cobrado": "Cupom da plataforma cobrado do restaurante",
    "estorno_nao_descontado": "Estorno não descontado",
    "estorno_duplicado": "Estorno descontado duas vezes",
    "pedido_duplicado": "Pedido pago em duplicidade",
    "pedido_ausente": "Pedido entregue fora do repasse",
    "transferencia_divergente": "Valor transferido diferente do extrato",
    "repasse_duplicado": "Repasse pago em duplicidade",
    "pedido_nao_esperado": "Pedido pago sem estar previsto",
    "estorno_nao_esperado": "Estorno sem correspondência",
    "repasse_sem_pagamento": "Repasse sem pagamento no banco",
    "diferenca_sem_explicacao": "Diferença sem explicação",
    "outro": "Outra causa",
    "sem_divergencia": "Sem divergência",
}
ERROR_TYPES = [
    "comissao_taxa_errada", "comissao_plano_antigo", "taxa_pagamento_errada", "cupom_plataforma_cobrado",
    "estorno_nao_descontado", "estorno_duplicado", "pedido_duplicado", "pedido_ausente",
    "transferencia_divergente", "repasse_duplicado",
]
LINE_OPTIONS = ["comissao_taxa_errada", "comissao_plano_antigo", "taxa_pagamento_errada",
                "cupom_plataforma_cobrado", "outro"]
REFUND_OPTIONS = ["estorno_nao_descontado", "sem_divergencia"]
METHOD_LABEL = {"pix": "Pix", "credito": "crédito", "debito": "débito", "vale_refeicao": "vale-refeição"}


@dataclass
class Divergence:
    div_id: str
    familia: str
    chave: str
    restaurante_id: str | None
    semana: str | None
    repasse_id: str | None
    valor_centavos: int
    evidencias: list[dict] = field(default_factory=list)
    hipoteses: list[dict] = field(default_factory=list)
    opcoes: list[str] = field(default_factory=list)
    tipo: str | None = None
    tipo_regra_base: str | None = None
    classificado_por: str = ""
    confianca: float | None = None
    explicacao: str = ""
    status: str = ""
    motivo_revisao: str = ""
    linhas: list[str] = field(default_factory=list)
    pedidos: list[str] = field(default_factory=list)
    ia: dict | None = None

    @property
    def ambigua(self) -> bool:
        return bool(self.opcoes) and self.classificado_por in ("", "pendente")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tipo_label"] = TIPO_LABELS.get(self.tipo or "", self.tipo)
        d["direcao"] = "restaurante_recebeu_a_mais" if self.valor_centavos > 0 else "restaurante_recebeu_a_menos"
        return d


def _i(v):
    if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)):
        return None
    return int(v)


def _s(v):
    if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)):
        return None
    return str(v)


# --------------------------------------------------------------------------- evidence builders

PAYER = {"plataforma": "pago pela plataforma", "restaurante": "pago pelo restaurante"}


def br_ts(v) -> str:
    """Timestamp as dd/mm/aaaa hh:mm (dates as dd/mm/aaaa when there is no time of day)."""
    if v is None or v is pd.NaT or (isinstance(v, float) and pd.isna(v)):
        return ""
    ts = pd.Timestamp(v)
    return ts.strftime("%d/%m/%Y") if ts.hour == 0 and ts.minute == 0 and ts.second == 0 else ts.strftime("%d/%m/%Y %H:%M")


def order_evidence(o: dict) -> dict:
    code = _s(o.get("cupom_codigo"))
    return {"id": f"pedido:{o['pedido_id']}", "fonte": "base de pedidos", "dados": {
        "pedido_id": o["pedido_id"], "criado_em": br_ts(o["criado_em"]), "concluido_em": br_ts(o["concluido_em"]),
        "forma_pagamento": METHOD_LABEL.get(o["forma_pagamento"], o["forma_pagamento"]),
        "valor_itens": format_brl(int(o["valor_itens"])), "taxa_entrega": format_brl(int(o["taxa_entrega"])),
        "cupom": (f"{code} de {format_brl(int(o['cupom_valor']))}, {PAYER.get(_s(o.get('cupom_custeio')), '')}"
                  if code else "sem cupom"),
        "total_pago_cliente": format_brl(int(o["valor_total"])),
    }}


def contract_evidence(o: dict) -> list[dict]:
    ev = [{"id": f"contrato:{o['plano_id']}-v{o['versao']}", "fonte": "contratos.xlsx", "dados": {
        "plano": o["plano_nome"], "versao": o["versao"], "comissao": format_pct(o["comissao_bps"]),
        "taxa_da_forma_de_pagamento": format_pct(o["taxa_bps"]),
        "entrega": "própria (taxa fica com o restaurante)" if o["entrega"] == "propria"
                   else "da plataforma (taxa fica com a plataforma)",
    }}]
    if o.get("plano_anterior"):
        ev.append({"id": f"contrato_anterior:{o['plano_anterior']}", "fonte": "contratos.xlsx", "dados": {
            "plano_anterior": o["plano_anterior_nome"], "troca_em": br_ts(o["data_troca"]),
            "comissao_anterior": format_pct(o["ant_comissao_bps"]),
            "taxa_anterior_da_forma": format_pct(o["ant_taxa_bps"]),
        }})
    return ev


def statement_evidence(o: dict) -> dict:
    d = {"linha_id": o["linha_id"], "repasse_id": o["repasse_id"], "layout": o["layout"],
         "descricao": o["descricao"], "valor_liquido": format_brl(o["s_liquido"], signed=True)}
    if o["layout"] == "detalhado":
        d.update({"comissao": format_brl(o["s_comissao"]), "taxa_pagamento": format_brl(o["s_taxa"]),
                  "cupom_descontado": format_brl(o["s_cupom"]), "entrega_repassada": format_brl(o["s_entrega"])})
    return {"id": f"linha:{o['linha_id']}", "fonte": "extrato de repasse", "dados": d}


def expected_evidence(o: dict) -> dict:
    return {"id": f"calculo:{o['pedido_id']}", "fonte": "recálculo do motor", "dados": {
        "comissao": format_brl(o["e_comissao"]), "taxa_pagamento": format_brl(o["e_taxa"]),
        "cupom_descontado": format_brl(o["e_cupom"]), "entrega_repassada": format_brl(o["e_entrega"]),
        "liquido_esperado": format_brl(o["e_liquido"], signed=True),
        "diferenca": format_brl(o["s_liquido"] - o["e_liquido"], signed=True),
    }}


# --------------------------------------------------------------------------- hypotheses for order lines

def line_hypotheses(o: dict, plans: pd.DataFrame) -> list[dict]:
    tol = config.TOLERANCE_LINE_CENTS
    s = o["s_liquido"]
    hyps = []

    def add(tipo, desc, net, extra=None):
        hyps.append({"tipo": tipo, "descricao": desc, "liquido_hipotese": int(net),
                     "liquido_hipotese_brl": format_brl(int(net), signed=True),
                     "confere": abs(s - int(net)) <= tol, **(extra or {})})

    if o.get("ant_liquido") is not None:
        add("comissao_plano_antigo", f"plano anterior ({o['plano_anterior_nome']}) aplicado depois da troca",
            o["ant_liquido"])
    if o.get("cupom_custeio") == "plataforma" and o.get("cupom_valor", 0) > 0:
        add("cupom_plataforma_cobrado", f"cupom {o['cupom_codigo']} da plataforma descontado do restaurante",
            o["e_liquido"] - o["cupom_valor"])
    pv = plans[(plans["plano_id"] == o["plano_id"])]
    best_fee = None
    for _, p in pv.iterrows():
        for m in ["pix", "debito", "credito", "vale_refeicao"]:
            bps = int(p[f"taxa_{m}_bps"])
            if bps == o["taxa_bps"]:
                continue
            net = o["e_liquido"] + o["e_taxa"] - apply_rate(o["valor_total"], bps)
            cand = (abs(s - net), m, int(p["versao"]), bps, net)
            if best_fee is None or cand < best_fee:
                best_fee = cand
    if best_fee:
        _, m, ver, bps, net = best_fee
        add("taxa_pagamento_errada", f"taxa de {METHOD_LABEL[m]} ({format_pct(bps)}, versão {ver}) no lugar da correta",
            net)
    implied = o["e_itens"] + o["e_entrega"] - o["e_cupom"] - o["e_taxa"] - s
    best_c = None
    for r in range(0, 4001, 50):
        if r == o["comissao_bps"]:
            continue
        gap = abs(apply_rate(o["e_itens"], r) - implied)
        if best_c is None or gap < best_c[0]:
            best_c = (gap, r)
    if best_c:
        r = best_c[1]
        net = o["e_itens"] + o["e_entrega"] - o["e_cupom"] - o["e_taxa"] - apply_rate(o["e_itens"], r)
        add("comissao_taxa_errada", f"comissão de {format_pct(r)} no lugar de {format_pct(o['comissao_bps'])}", net)
    return hyps


def baseline_line_type(hyps: list[dict]) -> str | None:
    """Rules-only answer for an ambiguous line: first hypothesis that fits, by fixed priority."""
    fits = {h["tipo"] for h in hyps if h["confere"]}
    for t in ["comissao_plano_antigo", "cupom_plataforma_cobrado", "taxa_pagamento_errada", "comissao_taxa_errada"]:
        if t in fits:
            return t
    return None


def classify_detailed_line(o: dict) -> str | None:
    tol = config.TOLERANCE_LINE_CENTS
    if o.get("ant_liquido") is not None and abs(o["s_liquido"] - o["ant_liquido"]) <= tol:
        return "comissao_plano_antigo"
    diffs = {k: abs(o[f"s_{k}"] - o[f"e_{k}"]) > tol for k in ["itens", "entrega", "cupom", "comissao", "taxa"]}
    changed = {k for k, v in diffs.items() if v}
    if changed == {"comissao"}:
        return "comissao_taxa_errada"
    if changed == {"taxa"}:
        return "taxa_pagamento_errada"
    if changed == {"cupom"} and o["e_cupom"] == 0 and o.get("cupom_custeio") == "plataforma" \
            and o["s_cupom"] == o["cupom_valor"]:
        return "cupom_plataforma_cobrado"
    return None


# --------------------------------------------------------------------------- refund owner (text only)

PLATFORM_WORDS = ["entregador", "motoboy", "parceiro", "app ", "aplicativo", "cobrou", "rota", "atraso",
                  "nao recebeu", "entrega cancelada"]
RESTAURANT_WORDS = ["faltou", "faltando", "errado", "sabor", "cru", "embalagem", "cabelo", "porcao", "loja",
                    "sobremesa", "item", "tampa", "molho", "restaurante"]


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c)) + " "


def baseline_refund_owner(note: str) -> str | None:
    t = _plain(note)
    p = sum(w in t for w in PLATFORM_WORDS)
    r = sum(w in t for w in RESTAURANT_WORDS)
    if r > p:
        return "estorno_nao_descontado"
    if p > r:
        return "sem_divergencia"
    return None


# --------------------------------------------------------------------------- main entry

def collect_and_classify(con, bank_findings: list[BankFinding]) -> list[Divergence]:
    plans = con.sql("SELECT * FROM stg_plans").df()
    comp = con.sql("""
        SELECT c.*, o.cupom_codigo AS o_cupom_codigo
        FROM order_line_comparison c JOIN stg_orders o USING (pedido_id)
    """).df()
    comp = {r["pedido_id"]: r for r in comp.to_dict("records")}
    found = con.sql("SELECT * FROM line_divergences ORDER BY familia, chave, linha_id NULLS FIRST").df()
    refunds = {r["estorno_id"]: r for r in con.sql("SELECT * FROM expected_refund_lines").df().to_dict("records")}
    orders = {r["pedido_id"]: r for r in con.sql(
        "SELECT pedido_id, criado_em, concluido_em, forma_pagamento, valor_itens, taxa_entrega, cupom_codigo, "
        "cupom_valor, cupom_custeio, valor_total, status FROM stg_orders").df().to_dict("records")}

    divs: list[Divergence] = []

    def new(familia, chave, rid, semana, rep, valor) -> Divergence:
        d = Divergence(div_id=f"D{len(divs) + 1:05d}", familia=familia, chave=str(chave), restaurante_id=rid,
                       semana=semana, repasse_id=rep, valor_centavos=int(valor))
        divs.append(d)
        return d

    for f in found.to_dict("records"):
        fam = f["familia"]
        if fam == "linha_pedido":
            o = {k: (_i(v) if isinstance(v, (int, float)) or v is pd.NA else v) for k, v in comp[f["pedido_id"]].items()}
            for k in ["plano_id", "plano_nome", "entrega", "layout", "descricao", "linha_id", "repasse_id",
                      "cupom_custeio", "cupom_codigo", "forma_pagamento", "plano_anterior", "plano_anterior_nome",
                      "pedido_id", "semana"]:
                o[k] = _s(comp[f["pedido_id"]][k])
            o["data_troca"] = comp[f["pedido_id"]]["data_troca"]
            o["criado_em"], o["concluido_em"] = comp[f["pedido_id"]]["criado_em"], comp[f["pedido_id"]]["concluido_em"]
            d = new(fam, f["chave"], f["restaurante_id"], f["semana"], f["repasse_id"], f["valor_centavos"])
            d.linhas, d.pedidos = [o["linha_id"]], [o["pedido_id"]]
            d.evidencias = [order_evidence(orders[o["pedido_id"]]), *contract_evidence(o),
                            statement_evidence(o), expected_evidence(o)]
            d.hipoteses = line_hypotheses(o, plans)
            tipo = classify_detailed_line(o) if o["layout"] == "detalhado" else None
            fits = sorted({h["tipo"] for h in d.hipoteses if h["confere"]})
            if tipo is None and o["layout"] == "legado" and len(fits) == 1:
                tipo = fits[0]
            if tipo:
                d.tipo, d.classificado_por, d.confianca, d.status = tipo, "regra", 1.0, "confirmada"
            else:
                d.opcoes, d.classificado_por = list(LINE_OPTIONS), "pendente"
                d.tipo_regra_base = baseline_line_type(d.hipoteses)
        elif fam == "pedido_repetido":
            d = new(fam, f["chave"], f["restaurante_id"], f["semana"], f["repasse_id"], f["valor_centavos"])
            d.linhas, d.pedidos = [f["linha_id"]], [f["pedido_id"]]
            d.evidencias = [order_evidence(orders[f["pedido_id"]]),
                            {"id": f"linha:{f['linha_id']}", "fonte": "extrato de repasse",
                             "dados": {"repasse_id": f["repasse_id"], "valor_liquido": format_brl(f["valor_centavos"])}}]
            d.tipo, d.classificado_por, d.confianca, d.status = "pedido_duplicado", "regra", 1.0, "confirmada"
        elif fam == "pedido_ausente":
            d = new(fam, f["chave"], f["restaurante_id"], f["semana"], f["repasse_id"], f["valor_centavos"])
            d.pedidos = [f["pedido_id"]]
            d.evidencias = [order_evidence(orders[f["pedido_id"]])]
            d.tipo, d.classificado_por, d.confianca, d.status = "pedido_ausente", "regra", 1.0, "confirmada"
        elif fam == "pedido_nao_esperado":
            d = new(fam, f["chave"], f["restaurante_id"], f["semana"], f["repasse_id"], f["valor_centavos"])
            d.linhas = [f["linha_id"]]
            d.tipo, d.classificado_por, d.status = "pedido_nao_esperado", "revisao", "revisao"
            d.motivo_revisao = "pedido pago sem constar como entregue no período"
        elif fam in ("estorno_ausente", "estorno_ausente_dono_indefinido"):
            e = refunds[f["estorno_id"]]
            d = new(fam, f["chave"], f["restaurante_id"], f["semana"], f["repasse_id"], f["valor_centavos"])
            d.pedidos = [e["pedido_id"]]
            d.evidencias = [{"id": f"estorno:{e['estorno_id']}", "fonte": "base de estornos", "dados": {
                "estorno_id": e["estorno_id"], "pedido_id": e["pedido_id"], "valor": format_brl(int(e["e_valor"])),
                "processado_em": br_ts(e["processado_em"]),
                "responsavel": e["responsavel"] if e["responsavel"] != "indefinido" else "não preenchido",
                "nota_do_atendimento": e["motivo"]}},
                {"id": f"repasse:{f['repasse_id']}", "fonte": "extrato de repasse",
                 "dados": {"repasse_id": f["repasse_id"], "observacao": "nenhuma linha de estorno para este pedido"}}]
            if fam == "estorno_ausente":
                d.tipo, d.classificado_por, d.confianca, d.status = "estorno_nao_descontado", "regra", 1.0, "confirmada"
            else:
                d.opcoes, d.classificado_por = list(REFUND_OPTIONS), "pendente"
                d.tipo_regra_base = baseline_refund_owner(e["motivo"])
        elif fam == "estorno_repetido":
            d = new(fam, f["chave"], f["restaurante_id"], f["semana"], f["repasse_id"], f["valor_centavos"])
            d.linhas, d.pedidos = [f["linha_id"]], [f["pedido_id"]]
            d.evidencias = [{"id": f"linha:{f['linha_id']}", "fonte": "extrato de repasse",
                             "dados": {"repasse_id": f["repasse_id"], "valor": format_brl(f["valor_centavos"], signed=True)}}]
            d.tipo, d.classificado_por, d.confianca, d.status = "estorno_duplicado", "regra", 1.0, "confirmada"
        elif fam == "estorno_nao_esperado":
            d = new(fam, f["chave"], f["restaurante_id"], f["semana"], f["repasse_id"], f["valor_centavos"])
            d.linhas = [f["linha_id"]]
            d.tipo, d.classificado_por, d.status = "estorno_nao_esperado", "revisao", "revisao"
            d.motivo_revisao = "estorno descontado sem estorno correspondente do restaurante"

    for b in bank_findings:
        d = new(b.familia, b.chave, b.restaurante_id, b.semana, b.repasse_id, b.valor_centavos)
        d.evidencias = [{"id": f"banco:{x}", "fonte": "extrato bancário", "dados": {}} for x in b.banco_linhas]
        if b.repasse_id:
            d.evidencias.append({"id": f"repasse:{b.repasse_id}", "fonte": "repasses.csv", "dados": {}})
        if b.familia == "banco_valor_divergente":
            d.tipo, d.classificado_por, d.confianca, d.status = "transferencia_divergente", "regra", 1.0, "confirmada"
        elif b.familia == "banco_pagamento_repetido":
            d.tipo, d.classificado_por, d.confianca, d.status = "repasse_duplicado", "regra", 1.0, "confirmada"
        elif b.familia == "repasse_sem_pagamento":
            d.tipo, d.classificado_por, d.status = "repasse_sem_pagamento", "revisao", "revisao"
            d.motivo_revisao = b.detalhe
        else:
            d.tipo, d.classificado_por, d.status = "outro", "revisao", "revisao"
            d.motivo_revisao = b.detalhe
            d.hipoteses = b.candidatos

    residuals = con.sql(f"SELECT * FROM repasse_residuals WHERE abs(residuo) > {config.TOLERANCE_REPASSE_CENTS}").df()
    for r in residuals.to_dict("records"):
        d = new("residuo_repasse", r["repasse_id"], r["restaurante_id"], r["semana"], r["repasse_id"], r["residuo"])
        d.tipo, d.classificado_por, d.status = "diferenca_sem_explicacao", "revisao", "revisao"
        d.motivo_revisao = "diferença no total do repasse que as linhas não explicam"

    promote_old_plan_pattern(divs)
    return divs


def promote_old_plan_pattern(divs: list[Divergence]) -> None:
    """In legacy statements, if three or more lines of the same payout fit the
    old plan hypothesis, an ambiguous line that also fits it follows the pattern."""
    counts: dict[tuple, int] = {}
    for d in divs:
        if d.familia == "linha_pedido" and any(h["tipo"] == "comissao_plano_antigo" and h["confere"] for h in d.hipoteses):
            counts[(d.restaurante_id, d.semana)] = counts.get((d.restaurante_id, d.semana), 0) + 1
    for d in divs:
        if d.ambigua and d.familia == "linha_pedido" and counts.get((d.restaurante_id, d.semana), 0) >= 3 and \
                any(h["tipo"] == "comissao_plano_antigo" and h["confere"] for h in d.hipoteses):
            d.tipo, d.classificado_por, d.confianca, d.status = "comissao_plano_antigo", "regra", 1.0, "confirmada"
            d.opcoes = []


def aggregate_old_plan(divs: list[Divergence]) -> list[Divergence]:
    """One divergence per payout for the old plan: the cause is the contract, not each order."""
    out, groups = [], {}
    for d in divs:
        if d.tipo == "comissao_plano_antigo" and d.familia == "linha_pedido" and d.status == "confirmada":
            groups.setdefault((d.restaurante_id, d.semana), []).append(d)
        else:
            out.append(d)
    for (rid, wk), items in groups.items():
        first = items[0]
        agg = Divergence(div_id=first.div_id, familia="plano_antigo_semana", chave=f"{rid}|{wk}", restaurante_id=rid,
                         semana=wk, repasse_id=first.repasse_id, valor_centavos=sum(x.valor_centavos for x in items))
        agg.tipo, agg.status = "comissao_plano_antigo", "confirmada"
        by_ai = [x for x in items if x.classificado_por == "ia"]
        agg.classificado_por = "ia" if by_ai and len(by_ai) == len(items) else "regra"
        agg.confianca = min((x.confianca or 1.0) for x in items)
        agg.linhas = [l for x in items for l in x.linhas]
        agg.pedidos = [p for x in items for p in x.pedidos]
        contract = [e for e in first.evidencias if e["id"].startswith("contrato")]
        agg.evidencias = contract + [e for x in items[:5] for e in x.evidencias if e["id"].startswith("linha:")]
        agg.hipoteses = [{"tipo": "comissao_plano_antigo", "pedidos_afetados": len(items),
                          "descricao": "plano anterior aplicado depois da troca"}]
        out.append(agg)
    return sorted(out, key=lambda d: d.div_id)


NUMBER_RE = re.compile(r"\d")
