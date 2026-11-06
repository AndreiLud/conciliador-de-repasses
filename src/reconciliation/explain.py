"""Deterministic, plain Portuguese description of each divergence.

These sentences feed three places: the evidence panel of the demo, the
fallback letter (when the model is off or its text fails the checks) and the
facts handed to the model. Every number comes from the data.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .. import config
from ..money import format_brl, format_pct
from .classify import METHOD_LABEL, TIPO_LABELS

MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
          "outubro", "novembro", "dezembro"]


def br_date(d) -> str:
    d = pd.Timestamp(d)
    return d.strftime("%d/%m/%Y")


def week_label(wid: str) -> str:
    start, end = config.week_bounds(wid)
    if start.month == end.month:
        return f"de {start.day} a {end.day} de {MONTHS[end.month - 1]} de {end.year}"
    return f"de {start.day} de {MONTHS[start.month - 1]} a {end.day} de {MONTHS[end.month - 1]} de {end.year}"


class Context:
    """Lookups the descriptions need, loaded once from the DuckDB connection."""

    def __init__(self, con):
        self.orders = con.sql("SELECT * FROM stg_orders").df().set_index("pedido_id")
        self.comp = con.sql("SELECT * FROM order_line_comparison").df().set_index("pedido_id")
        self.refunds = con.sql("SELECT * FROM stg_refunds").df().set_index("estorno_id")
        self.restaurants = con.sql("SELECT * FROM stg_restaurants").df().set_index("restaurante_id")
        self.repasses = con.sql("SELECT * FROM stg_repasses").df().set_index("repasse_id")
        self.bank = con.sql("SELECT * FROM stg_bank").df().set_index("banco_linha_id")
        self.plans = con.sql("SELECT * FROM stg_restaurant_plans").df()

    def name(self, rid: str) -> str:
        return str(self.restaurants.at[rid, "nome_fantasia"]) if rid in self.restaurants.index else rid


def plan_change(d, ctx: Context):
    """(old plan name, new plan name, change date) taken from the contract the detection used."""
    for pid in d.pedidos:
        if pid in ctx.comp.index:
            c = ctx.comp.loc[pid]
            if isinstance(c.get("plano_anterior_nome"), str):
                return c["plano_anterior_nome"], c["plano_nome"], br_date(c["data_troca"])
    return None


def describe(d, ctx: Context) -> str:
    t = d.tipo
    pid = d.pedidos[0] if d.pedidos else None
    v = format_brl(abs(d.valor_centavos))
    if d.familia == "linha_pedido" and d.status == "revisao":
        fits = [h["descricao"] for h in d.hipoteses if h.get("confere")]
        base = (f"No pedido {pid}, o valor pago difere do recalculado em {v}.")
        if fits:
            return base + " O valor do extrato confere com: " + "; ".join(fits) + "."
        return base + " Nenhuma hipótese calculada reproduz o valor do extrato."
    if d.familia == "estorno_ausente_dono_indefinido" and d.status != "confirmada" and d.chave in ctx.refunds.index:
        e = ctx.refunds.loc[d.chave]
        return (f"O estorno de {v} do pedido {e['pedido_id']} não tem responsável preenchido e não foi descontado. "
                f"A nota do atendimento diz: \u201c{e['motivo']}\u201d. Se a culpa foi do restaurante, ele recebeu {v} "
                f"a mais; se foi da plataforma, está tudo certo.")
    if t in ("comissao_taxa_errada", "taxa_pagamento_errada", "cupom_plataforma_cobrado") and pid in ctx.comp.index:
        c = ctx.comp.loc[pid]
        detailed = c["layout"] == "detalhado"
        if t == "comissao_taxa_errada":
            if detailed and not pd.isna(c["s_comissao"]):
                return (f"No pedido {pid}, a comissão cobrada foi {format_brl(int(c['s_comissao']))}. Pelo contrato "
                        f"({format_pct(int(c['comissao_bps']))} sobre {format_brl(int(c['e_itens']))} em itens), "
                        f"seriam {format_brl(int(c['e_comissao']))}.")
            hyp = next((h for h in d.hipoteses if h["tipo"] == t), None)
            extra = f" O valor pago bate com {hyp['descricao']}." if hyp and hyp.get("confere") else ""
            return (f"No pedido {pid}, o líquido pago foi {format_brl(int(c['s_liquido']))} e o contrato leva a "
                    f"{format_brl(int(c['e_liquido']))}, uma diferença de {v} na comissão.{extra}")
        if t == "taxa_pagamento_errada":
            method = METHOD_LABEL.get(c["forma_pagamento"], c["forma_pagamento"])
            if detailed and not pd.isna(c["s_taxa"]):
                return (f"No pedido {pid}, pago com {method}, a taxa de pagamento cobrada foi "
                        f"{format_brl(int(c['s_taxa']))}. A taxa do contrato para {method} é "
                        f"{format_pct(int(c['taxa_bps']))}, o que dá {format_brl(int(c['e_taxa']))}.")
            return (f"No pedido {pid}, pago com {method}, o líquido pago foi {format_brl(int(c['s_liquido']))} e "
                    f"o correto seria {format_brl(int(c['e_liquido']))}. A diferença de {v} corresponde à taxa de "
                    f"outra forma de pagamento.")
        o = ctx.orders.loc[pid]
        return (f"No pedido {pid}, o cupom {o['cupom_codigo']} de {format_brl(int(o['cupom_valor']))} é pago pela "
                f"plataforma, mas foi descontado do restaurante.")
    if t == "comissao_plano_antigo":
        ch = plan_change(d, ctx)
        if ch:
            old, new, when = ch
            n = len(d.pedidos)
            orders = "1 pedido feito depois da troca foi calculado" if n == 1 else \
                f"{n} pedidos feitos depois da troca foram calculados"
            return (f"O restaurante passou do plano {old} para o plano {new} em {when}. Mesmo assim, {orders} com "
                    f"as regras do plano {old}, uma diferença de {v} no repasse.")
        return "Pedidos foram calculados com um plano que não estava mais em vigor."
    if t == "pedido_ausente" and pid in ctx.orders.index:
        o = ctx.orders.loc[pid]
        return (f"O pedido {pid}, entregue em {br_date(o['concluido_em'])}, não entrou no repasse. "
                f"O valor líquido dele é {v}.")
    if t == "pedido_duplicado":
        return f"O pedido {pid} aparece duas vezes no extrato de repasse e foi pago em dobro ({v} a mais)."
    if t in ("estorno_nao_descontado", "estorno_duplicado"):
        eid = d.chave
        if eid in ctx.refunds.index:
            e = ctx.refunds.loc[eid]
            if t == "estorno_nao_descontado":
                return (f"O estorno de {format_brl(int(e['valor_estornado']))} feito ao cliente do pedido "
                        f"{e['pedido_id']} em {br_date(e['processado_em'])}, por um problema no pedido, não foi "
                        f"descontado do repasse.")
            return (f"O estorno de {format_brl(int(e['valor_estornado']))} do pedido {e['pedido_id']} foi descontado "
                    f"duas vezes.")
    if t == "transferencia_divergente" and d.repasse_id in ctx.repasses.index:
        total = int(ctx.repasses.at[d.repasse_id, "valor_total"])
        paid = total + d.valor_centavos
        return (f"O extrato do repasse soma {format_brl(total)}, mas a transferência no banco foi de "
                f"{format_brl(paid)}.")
    if t == "repasse_duplicado":
        return f"O repasse {d.repasse_id} foi pago duas vezes no banco, {v} a mais."
    if d.motivo_revisao:
        return d.motivo_revisao[0].upper() + d.motivo_revisao[1:] + "."
    return TIPO_LABELS.get(t or "", "Diferença encontrada") + "."


def describe_plain(d, ctx: Context) -> str:
    """Same cause as ``describe`` in plain words and without amounts (the letter table has them)."""
    t = d.tipo
    pid = d.pedidos[0] if d.pedidos else None
    more = d.valor_centavos > 0
    if t == "comissao_taxa_errada":
        return (f"No pedido {pid}, a comissão foi calculada com uma taxa {'menor' if more else 'maior'} do que a "
                f"prevista no contrato.")
    if t == "taxa_pagamento_errada":
        return (f"No pedido {pid}, a taxa de pagamento usada foi a de outra forma de pagamento, "
                f"{'mais barata' if more else 'mais cara'} do que a correta.")
    if t == "cupom_plataforma_cobrado" and pid in ctx.orders.index:
        return (f"No pedido {pid}, o cupom {ctx.orders.at[pid, 'cupom_codigo']} é pago pela plataforma, mas foi "
                f"descontado do restaurante.")
    if t == "comissao_plano_antigo":
        ch = plan_change(d, ctx)
        if ch:
            old, new, when = ch
            return (f"Vocês trocaram do plano {old} para o plano {new} em {when}, mas pedidos feitos depois da "
                    f"troca ainda foram calculados com as regras do plano {old}.")
        return "Pedidos foram calculados com um plano que não estava mais em vigor."
    if t == "pedido_ausente":
        return f"O pedido {pid} foi entregue, mas não entrou no repasse."
    if t == "pedido_duplicado":
        return f"O pedido {pid} entrou duas vezes no repasse."
    if t == "estorno_nao_descontado" and d.chave in ctx.refunds.index:
        e = ctx.refunds.loc[d.chave]
        return (f"O cliente do pedido {e['pedido_id']} recebeu um estorno por um problema do restaurante "
                f"({e['motivo']}), e esse estorno não foi descontado do repasse.")
    if t == "estorno_duplicado":
        return f"O estorno do pedido {pid} foi descontado duas vezes."
    if t == "transferencia_divergente":
        return "O valor transferido no banco ficou diferente do valor do extrato de repasse."
    if t == "repasse_duplicado":
        return "O repasse desta semana foi pago duas vezes no banco."
    return TIPO_LABELS.get(t or "", "Diferença encontrada") + "."
