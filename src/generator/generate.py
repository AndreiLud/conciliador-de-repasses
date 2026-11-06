"""Synthetic data generator for the payout reconciliation project.

It builds a fictitious delivery marketplace ("Talher"), one month of orders,
the weekly payout statements, the bank statement and the contracts. Then it
plants errors (with an answer key) and traps (things that look wrong but are
right). Everything is driven by a seeded ``numpy.random.Generator``.

Usage:  python -m src.generator.generate [--seed N] [--restaurants N]
"""
from __future__ import annotations

import argparse
import json
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from .. import config
from ..money import apply_rate, apply_rate_truncated
from ..payout import PAYMENT_METHODS, PLAN_VERSIONS, PlanVersion, order_payout, plan_version
from . import names as N

DEFAULT_ERRORS = {
    "comissao_taxa_errada": 25,
    "comissao_plano_antigo": 8,
    "taxa_pagamento_errada": 25,
    "cupom_plataforma_cobrado": 20,
    "estorno_nao_descontado": 15,
    "estorno_duplicado": 10,
    "pedido_duplicado": 15,
    "pedido_ausente": 20,
    "transferencia_divergente": 8,
    "repasse_duplicado": 4,
}

DEFAULT_TRAPS = {
    "arredondamento_centavos": 80,
    "ajuste_manual_legitimo": 30,
    "estorno_complementar": 10,
    "pix_devolvido_reenviado": 5,
}


@dataclass
class GeneratorConfig:
    seed: int = 20261005
    n_restaurants: int = 200
    mean_orders_per_day: float = 8.5
    cancel_rate: float = 0.016
    refund_rate: float = 0.013
    refund_restaurant_share: float = 0.70
    refund_hidden_owner_share: float = 0.25
    refund_not_deducted_hidden: int = 8
    coupon_rate: float = 0.18
    coupon_platform_share: float = 0.60
    legacy_layout_share: float = 0.25
    n_plan_changes: int = 20
    n_similar_name_pairs: int = 8
    n_duplicate_export_rows: int = 12
    errors: dict = field(default_factory=lambda: dict(DEFAULT_ERRORS))
    traps: dict = field(default_factory=lambda: dict(DEFAULT_TRAPS))


@dataclass
class World:
    restaurants: pd.DataFrame
    restaurant_plans: pd.DataFrame
    orders: pd.DataFrame
    refunds: pd.DataFrame
    statement: pd.DataFrame
    repasses: pd.DataFrame
    bank: pd.DataFrame
    answer_key: pd.DataFrame
    traps: pd.DataFrame
    plan_versions: list[PlanVersion] = field(default_factory=lambda: list(PLAN_VERSIONS))


# --------------------------------------------------------------------------- helpers

def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def period_end_dt() -> datetime:
    return datetime.combine(config.PERIOD_START + timedelta(days=7 * config.N_WEEKS), datetime.min.time())


def week_of(ts: datetime) -> str:
    return config.week_id(ts.date())


def fake_cnpj(rng: np.random.Generator) -> str:
    """CNPJ-shaped string whose check digits are deliberately invalid."""
    base = [int(d) for d in rng.integers(0, 10, size=8)]
    digits = base + [0, 0, 0, 1]

    def dv(nums, weights):
        s = sum(n * w for n, w in zip(nums, weights))
        r = s % 11
        return 0 if r < 2 else 11 - r

    d1 = dv(digits, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(digits + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    bad1 = (d1 + 1 + int(rng.integers(0, 8))) % 10  # never equal to the valid digit
    b = "".join(map(str, digits))
    return f"{b[0:2]}.{b[2:5]}.{b[5:8]}/{b[8:12]}-{bad1}{d2}"


def unique_ids(rng: np.random.Generator, n: int, low: int, high: int) -> list[int]:
    out: set[int] = set()
    while len(out) < n:
        out.update(int(x) for x in rng.integers(low, high, size=(n - len(out)) * 2))
    return list(out)[:n] if len(out) == n else sorted(out)[:n]


# --------------------------------------------------------------------------- restaurants

def build_restaurants(rng: np.random.Generator, cfg: GeneratorConfig) -> pd.DataFrame:
    cats = list(N.CATEGORIES)
    cat_w = np.array([N.CATEGORIES[c][0] for c in cats])
    cat_w = cat_w / cat_w.sum()
    city_w = np.array([c[2] for c in N.CITIES])
    city_w = city_w / city_w.sum()

    n_base = cfg.n_restaurants - cfg.n_similar_name_pairs
    rows, used = [], set()
    while len(rows) < n_base:
        cat = cats[rng.choice(len(cats), p=cat_w)]
        _, _, _, patterns, pool = N.CATEGORIES[cat]
        name = patterns[rng.integers(len(patterns))].format(x=pool[rng.integers(len(pool))])
        if name in used:
            continue
        used.add(name)
        city, uf, _ = N.CITIES[rng.choice(len(N.CITIES), p=city_w)]
        rows.append({"nome_fantasia": name, "categoria": cat, "cidade": city, "uf": uf})

    # Second units with almost the same name, same city: a classic matching headache.
    pair_src = rng.choice(len(rows), size=cfg.n_similar_name_pairs, replace=False)
    for i, src in enumerate(pair_src):
        base = rows[src]
        suffix = N.NAME_VARIANT_SUFFIXES[i % len(N.NAME_VARIANT_SUFFIXES)]
        rows.append({**base, "nome_fantasia": base["nome_fantasia"] + suffix})

    order = rng.permutation(len(rows))
    rows = [rows[i] for i in order]
    plan_ids = ["ESS", "COM", "PLUS"]
    for i, r in enumerate(rows):
        r["restaurante_id"] = f"R{i + 1:04d}"
        r["cnpj"] = fake_cnpj(rng)
        if rng.random() < 0.6:
            core = r["nome_fantasia"]
            r["razao_social"] = f"{core} {N.COMPANY_SUFFIXES[rng.integers(len(N.COMPANY_SUFFIXES))]}"
        else:
            initials = " ".join(f"{chr(65 + int(rng.integers(0, 26)))}." for _ in range(int(rng.integers(1, 3))))
            surname = N.OWNER_SURNAMES[rng.integers(len(N.OWNER_SURNAMES))]
            word = N.COMPANY_WORDS[rng.integers(len(N.COMPANY_WORDS))]
            r["razao_social"] = f"{initials} {surname} {word} {N.COMPANY_SUFFIXES[rng.integers(len(N.COMPANY_SUFFIXES))]}"
        r["agencia"] = f"{int(rng.integers(1, 9999)):04d}"
        r["conta"] = f"{int(rng.integers(10000, 999999))}-{int(rng.integers(0, 10))}"
        r["plano_inicial"] = plan_ids[rng.choice(3, p=[0.35, 0.45, 0.20])]
        r["layout_extrato"] = "legado" if rng.random() < cfg.legacy_layout_share else "detalhado"
        lam = float(np.exp(rng.normal(np.log(cfg.mean_orders_per_day * 0.85), 0.6)))
        r["pedidos_dia"] = round(min(max(lam, 1.5), 45.0), 2)
        r["cliente_desde"] = (date(2023, 1, 1) + timedelta(days=int(rng.integers(0, 900)))).isoformat()
    return pd.DataFrame(rows)


def build_restaurant_plans(rng: np.random.Generator, cfg: GeneratorConfig, rest: pd.DataFrame) -> pd.DataFrame:
    rows = []
    eligible = rest.index[rest["pedidos_dia"] >= 5].to_numpy()
    changers = set(rng.choice(eligible, size=min(cfg.n_plan_changes, len(eligible)), replace=False).tolist())
    next_plan = {"ESS": ["COM", "PLUS"], "COM": ["PLUS", "ESS"], "PLUS": ["COM"]}
    for idx, r in rest.iterrows():
        start = date.fromisoformat(r["cliente_desde"])
        if idx in changers:
            change = config.PERIOD_START + timedelta(days=int(rng.integers(8, 30)))
            new = next_plan[r["plano_inicial"]][int(rng.integers(len(next_plan[r["plano_inicial"]])))]
            rows.append({"restaurante_id": r["restaurante_id"], "plano_id": r["plano_inicial"],
                         "vigencia_inicio": start, "vigencia_fim": change - timedelta(days=1)})
            rows.append({"restaurante_id": r["restaurante_id"], "plano_id": new,
                         "vigencia_inicio": change, "vigencia_fim": None})
        else:
            rows.append({"restaurante_id": r["restaurante_id"], "plano_id": r["plano_inicial"],
                         "vigencia_inicio": start, "vigencia_fim": None})
    return pd.DataFrame(rows)


def plan_of(rplans: dict, rid: str, day: date) -> str:
    for p in rplans[rid]:
        if p["vigencia_inicio"] <= day and (p["vigencia_fim"] is None or day <= p["vigencia_fim"]):
            return p["plano_id"]
    raise LookupError((rid, day))


# --------------------------------------------------------------------------- orders and refunds

DOW_FACTOR = [0.85, 0.85, 0.9, 0.95, 1.2, 1.3, 1.25]


def _order_hour(rng, late_share: float, sunday: bool) -> float:
    late = late_share * (2.2 if sunday else 1.0)
    u = rng.random()
    if u < late:
        return float(rng.uniform(22.3, 23.999))
    if u < late + 0.06:
        return float(rng.uniform(14.5, 18.0))
    if rng.random() < 0.5:
        return float(np.clip(rng.normal(12.4, 0.9), 10.0, 15.0))
    return float(np.clip(rng.normal(20.0, 1.2), 17.5, 22.9))


def _price(rng, mean_cents: int) -> int:
    v = rng.lognormal(np.log(mean_cents), 0.42)
    v = max(v, 1290)
    cents = int(round(v / 100.0)) * 100
    return cents - int(rng.choice([0, 10, 10, 50]))


def build_orders(rng: np.random.Generator, cfg: GeneratorConfig, rest: pd.DataFrame, rplans: dict) -> pd.DataFrame:
    rows = []
    n_days = 7 * config.N_WEEKS
    for _, r in rest.iterrows():
        _, mean_ticket, late_share, _, _ = N.CATEGORIES[r["categoria"]]
        for d in range(n_days):
            day = config.PERIOD_START + timedelta(days=d)
            n = rng.poisson(r["pedidos_dia"] * DOW_FACTOR[day.weekday()])
            for _ in range(n):
                hour = _order_hour(rng, late_share, day.weekday() == 6)
                created = datetime.combine(day, datetime.min.time()) + timedelta(seconds=int(hour * 3600))
                plan_id = plan_of(rplans, r["restaurante_id"], created.date())
                pv = plan_version(plan_id, created.date())
                items = _price(rng, mean_ticket)
                if pv.delivery == "propria":
                    delivery = 0 if rng.random() < 0.25 else int(rng.choice([399, 499, 599, 699, 799, 899, 999]))
                else:
                    delivery = 0 if rng.random() < 0.20 else int(rng.choice([499, 599, 699, 799, 899, 999, 1099, 1299]))
                code, coupon, funder = None, 0, None
                if rng.random() < cfg.coupon_rate:
                    platform = rng.random() < cfg.coupon_platform_share
                    pool = N.COUPONS_PLATFORM if platform else N.COUPONS_RESTAURANT
                    code, kind, val = pool[rng.integers(len(pool))]
                    coupon = val if kind == "fixed" else min(apply_rate(items, val), 2000 if platform else 1500)
                    coupon = min(coupon, items // 2)
                    funder = "plataforma" if platform else "restaurante"
                lunch = 11 <= hour < 15
                p = [0.30, 0.35, 0.10, 0.25] if lunch else [0.36, 0.45, 0.14, 0.05]
                method = ["pix", "credito", "debito", "vale_refeicao"][rng.choice(4, p=p)]
                cancelled = rng.random() < cfg.cancel_rate
                duration = timedelta(minutes=float(18 + rng.gamma(4.0, 7.0)))
                rows.append({
                    "restaurante_id": r["restaurante_id"], "criado_em": created,
                    "status": "cancelado" if cancelled else "entregue",
                    "concluido_em": None if cancelled else created + duration,
                    "cancelado_em": created + timedelta(minutes=float(rng.uniform(1, 8))) if cancelled else None,
                    "etapa_cancelamento": "antes_do_preparo" if cancelled else None,
                    "valor_itens": items, "taxa_entrega": delivery,
                    "cupom_codigo": code, "cupom_valor": coupon, "cupom_custeio": funder,
                    "forma_pagamento": method,
                })
    orders = pd.DataFrame(rows).sort_values("criado_em").reset_index(drop=True)
    ids = unique_ids(rng, len(orders), 300_000_000, 999_999_999)
    orders.insert(0, "pedido_id", [str(i) for i in ids])
    orders["valor_total"] = orders["valor_itens"] + orders["taxa_entrega"] - orders["cupom_valor"]
    return orders


def build_refunds(rng: np.random.Generator, cfg: GeneratorConfig, orders: pd.DataFrame) -> pd.DataFrame:
    delivered = orders[orders["status"] == "entregue"]
    pick = delivered.sample(frac=cfg.refund_rate, random_state=int(rng.integers(1 << 31)))
    rows = []
    for _, o in pick.iterrows():
        restaurant = rng.random() < cfg.refund_restaurant_share
        full = rng.random() < 0.4
        value = o["valor_itens"] if full else max(500, int(round(o["valor_itens"] * rng.uniform(0.2, 0.55) / 10)) * 10)
        if rng.random() < 0.08:
            note = N.REFUND_NOTES_AMBIGUOUS[rng.integers(len(N.REFUND_NOTES_AMBIGUOUS))]
            restaurant = rng.random() < 0.5
        else:
            pool = N.REFUND_NOTES_RESTAURANT if restaurant else N.REFUND_NOTES_PLATFORM
            note = pool[rng.integers(len(pool))]
        rows.append({
            "pedido_id": o["pedido_id"], "restaurante_id": o["restaurante_id"],
            "processado_em": o["concluido_em"] + timedelta(hours=float(rng.uniform(10, 120))),
            "valor_estornado": int(value),
            "responsavel": "restaurante" if restaurant else "plataforma",
            "motivo": note,
            # The support team leaves the responsibility field blank in some tickets.
            "_responsavel_oculto": bool(rng.random() < cfg.refund_hidden_owner_share),
        })
    refunds = pd.DataFrame(rows).sort_values("processado_em").reset_index(drop=True)
    ids = unique_ids(rng, len(refunds), 100_000, 999_999)
    refunds.insert(0, "estorno_id", [f"EST-{i}" for i in ids])
    return refunds


# --------------------------------------------------------------------------- statement

def legacy_order_description(rng, line: dict) -> str:
    pid, plan, method = line["pedido_id"], line["_plan_name"], line["_method"]
    m_abbr = {"pix": "PIX", "credito": "CRED", "debito": "DEB", "vale_refeicao": "VR"}[method]
    m_text = {"pix": "Pix", "credito": "cartão de crédito", "debito": "cartão de débito",
              "vale_refeicao": "vale-refeição"}[method]
    coupon = ""
    if line["_coupon_charged"] > 0:
        coupon = f" | CUPOM LOJA {line['_coupon_charged'] / 100:.2f}".replace(".", ",")
    pct = f"{line['_commission_bps'] / 100:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    tpl = int(rng.integers(0, 5))
    if tpl == 0:
        return f"PED {pid} | {strip_accents(plan).upper()[:6]} | {m_abbr}{coupon}"
    if tpl == 1:
        return f"Pedido nº {pid} (plano {plan}, pgto {m_text})"
    if tpl == 2:
        return f"Venda {pid} {m_abbr} com {pct}%"
    if tpl == 3:
        return f"{pid} {strip_accents(plan).lower()} {m_abbr.lower()}{coupon.lower()}"
    return f"Repasse pedido {pid}"


def statement_line_from_order(o: pd.Series, pv: PlanVersion, **overrides) -> dict:
    method_for_fee = overrides.pop("fee_method", o["forma_pagamento"])
    fee_bps = overrides.pop("fee_bps", pv.fee_bps[method_for_fee])
    pay = order_payout(o["valor_itens"], o["taxa_entrega"], o["cupom_valor"], o["cupom_custeio"],
                       o["forma_pagamento"], pv, fee_bps=fee_bps, **overrides)
    return {
        "tipo_linha": "pedido", "pedido_id": o["pedido_id"], "referencia": o["pedido_id"],
        "data_referencia": o["concluido_em"],
        "valor_itens": pay.items, "taxa_entrega": pay.delivery_to_restaurant,
        "cupom_restaurante": pay.coupon_restaurant, "comissao": pay.commission,
        "taxa_pagamento": pay.payment_fee, "valor_liquido": pay.net,
        "_plan_name": pv.name, "_method": method_for_fee,
        "_commission_bps": overrides.get("commission_bps", pv.commission_bps),
        "_coupon_charged": pay.coupon_restaurant,
    }


def build_statement(orders: pd.DataFrame, refunds: pd.DataFrame, rest: pd.DataFrame,
                    rplans: dict) -> pd.DataFrame:
    """Correct statement lines (before any planted error)."""
    end = period_end_dt()
    lines = []
    for _, o in orders[(orders["status"] == "entregue") & (orders["concluido_em"] < end)].iterrows():
        pv = plan_version(plan_of(rplans, o["restaurante_id"], o["criado_em"].date()), o["criado_em"].date())
        line = statement_line_from_order(o, pv)
        line.update({"restaurante_id": o["restaurante_id"], "semana": week_of(o["concluido_em"])})
        lines.append(line)
    for _, e in refunds[(refunds["responsavel"] == "restaurante") & (refunds["processado_em"] < end)].iterrows():
        lines.append({
            "restaurante_id": e["restaurante_id"], "semana": week_of(e["processado_em"]),
            "tipo_linha": "estorno", "pedido_id": e["pedido_id"], "referencia": e["estorno_id"],
            "data_referencia": e["processado_em"], "valor_itens": None, "taxa_entrega": None,
            "cupom_restaurante": None, "comissao": None, "taxa_pagamento": None,
            "valor_liquido": -int(e["valor_estornado"]),
            "_motivo": e["motivo"],
        })
    st = pd.DataFrame(lines)
    st["repasse_id"] = "REP-" + st["semana"].str.replace("-", "") + "-" + st["restaurante_id"]
    layout = rest.set_index("restaurante_id")["layout_extrato"]
    st["_layout"] = st["restaurante_id"].map(layout)
    return st


# --------------------------------------------------------------------------- planted errors

class Planter:
    def __init__(self, rng, world_parts: dict, rplans: dict):
        self.rng = rng
        self.orders = world_parts["orders"].set_index("pedido_id", drop=False)
        self.refunds = world_parts["refunds"]
        self.rest = world_parts["rest"]
        self.rplans = rplans
        self.st = world_parts["statement"]
        self.keys_used: set[str] = set()
        self.answer: list[dict] = []
        self.traps: list[dict] = []

    # -- utilities
    def _add_answer(self, tipo, unidade, chave, rid, semana, valor, detalhe):
        self.answer.append({"classe": "erro", "tipo": tipo, "unidade": unidade, "chave": chave,
                            "restaurante_id": rid, "semana": semana, "valor_centavos": int(valor),
                            "detalhe": detalhe})
        self.keys_used.add(chave)

    def _add_trap(self, tipo, unidade, chave, rid, semana, detalhe):
        self.traps.append({"classe": "armadilha", "tipo": tipo, "unidade": unidade, "chave": chave,
                           "restaurante_id": rid, "semana": semana, "valor_centavos": 0, "detalhe": detalhe})
        self.keys_used.add(chave)

    def _candidate_order_lines(self, extra_mask=None):
        st = self.st
        mask = (st["tipo_linha"] == "pedido") & ~st["pedido_id"].isin(self.keys_used) & ~st["_trap"]
        if extra_mask is not None:
            mask &= extra_mask
        return np.array(st.index[mask].to_numpy())

    def _pv_for(self, pid):
        o = self.orders.loc[pid]
        return plan_version(plan_of(self.rplans, o["restaurante_id"], o["criado_em"].date()), o["criado_em"].date()), o

    def _rewrite(self, idx, new_line: dict):
        for k, v in new_line.items():
            self.st.at[idx, k] = v

    # -- order line errors
    def commission_wrong_rate(self, n):
        cands = self.rng.permutation(self._candidate_order_lines())
        done = 0
        for idx in cands:
            if done >= n:
                break
            line = self.st.loc[idx]
            pv, o = self._pv_for(line["pedido_id"])
            right = pv.commission_bps
            options = {1200: [2100, 1500, 1700, 1250, 1800], 2300: [3200, 2800, 2500, 2650, 2000],
                       2000: [2300, 2500, 2200, 2450, 1200]}[right]
            wrong = int(options[self.rng.integers(len(options))])
            new = statement_line_from_order(o, pv, commission_bps=wrong)
            diff = new["valor_liquido"] - line["valor_liquido"]
            if abs(diff) < 10:
                continue
            self._rewrite(idx, new)
            self._add_answer("comissao_taxa_errada", "pedido", line["pedido_id"], line["restaurante_id"],
                             line["semana"], diff, f"comissão aplicada {wrong} bps, contrato {right} bps")
            done += 1

    def payment_fee_wrong(self, n):
        cands = self.rng.permutation(self._candidate_order_lines())
        done = 0
        for idx in cands:
            if done >= n:
                break
            line = self.st.loc[idx]
            pv, o = self._pv_for(line["pedido_id"])
            right_m = o["forma_pagamento"]
            others = [m for m in PAYMENT_METHODS if m != right_m and pv.fee_bps[m] != pv.fee_bps[right_m]]
            wrong_m = others[self.rng.integers(len(others))]
            new = statement_line_from_order(o, pv, fee_method=wrong_m)
            diff = new["valor_liquido"] - line["valor_liquido"]
            if abs(diff) < 5:
                continue
            self._rewrite(idx, new)
            self._add_answer("taxa_pagamento_errada", "pedido", line["pedido_id"], line["restaurante_id"],
                             line["semana"], diff, f"taxa de {wrong_m} aplicada em pedido pago com {right_m}")
            done += 1

    def platform_coupon_charged(self, n):
        mask = self.st["pedido_id"].map(self.orders["cupom_custeio"]).eq("plataforma")
        cands = self.rng.permutation(self._candidate_order_lines(mask))[:n]
        for idx in cands:
            line = self.st.loc[idx]
            pv, o = self._pv_for(line["pedido_id"])
            o2 = o.copy()
            o2["cupom_custeio"] = "restaurante"
            new = statement_line_from_order(o2, pv)
            diff = new["valor_liquido"] - line["valor_liquido"]
            self._rewrite(idx, new)
            self._add_answer("cupom_plataforma_cobrado", "pedido", line["pedido_id"], line["restaurante_id"],
                             line["semana"], diff, f"cupom {o['cupom_codigo']} da plataforma descontado do restaurante")

    def old_plan_after_change(self, n):
        changers = [rid for rid, ps in self.rplans.items() if len(ps) > 1]
        self.rng.shuffle(changers)
        done = 0
        for rid in changers:
            if done >= n:
                break
            old, new = self.rplans[rid][0], self.rplans[rid][1]
            change = new["vigencia_inicio"]
            st = self.st
            for wid in [config.week_id(change), config.week_id(change + timedelta(days=7))]:
                mask = ((st["restaurante_id"] == rid) & (st["semana"] == wid) & (st["tipo_linha"] == "pedido")
                        & ~st["pedido_id"].isin(self.keys_used) & ~st["_trap"])
                idxs = [i for i in st.index[mask]
                        if self.orders.loc[st.at[i, "pedido_id"], "criado_em"].date() >= change]
                if len(idxs) < 3:
                    continue
                total = 0
                for idx in idxs:
                    line = st.loc[idx]
                    o = self.orders.loc[line["pedido_id"]]
                    pv_old = plan_version(old["plano_id"], o["criado_em"].date())
                    new_line = statement_line_from_order(o, pv_old)
                    total += new_line["valor_liquido"] - line["valor_liquido"]
                    self._rewrite(idx, new_line)
                    self.keys_used.add(line["pedido_id"])
                chave = f"{rid}|{wid}"
                self._add_answer("comissao_plano_antigo", "restaurante_semana", chave, rid, wid, total,
                                 f"plano {old['plano_id']} aplicado em {len(idxs)} pedidos após a troca para "
                                 f"{new['plano_id']} em {change.isoformat()}")
                done += 1
                break

    def duplicated_order(self, n):
        cands = self.rng.permutation(self._candidate_order_lines())
        done, extra = 0, []
        weeks = config.week_ids()
        for idx in cands:
            if done >= n:
                break
            line = self.st.loc[idx].to_dict()
            target_week = line["semana"]
            if done % 3 == 2:  # one in three shows up again in the following payout
                pos = weeks.index(line["semana"])
                if pos + 1 >= len(weeks):
                    continue
                target_week = weeks[pos + 1]
            dup = dict(line)
            dup["semana"] = target_week
            dup["repasse_id"] = "REP-" + target_week.replace("-", "") + "-" + line["restaurante_id"]
            extra.append(dup)
            self._add_answer("pedido_duplicado", "pedido", line["pedido_id"], line["restaurante_id"], target_week,
                             line["valor_liquido"],
                             "pedido repetido no mesmo repasse" if target_week == line["semana"]
                             else f"pedido já pago na {line['semana']} e repetido na {target_week}")
            done += 1
        self.st = pd.concat([self.st, pd.DataFrame(extra)], ignore_index=True)

    def missing_order(self, n):
        cands = self.rng.permutation(self._candidate_order_lines())[:n]
        for idx in cands:
            line = self.st.loc[idx]
            self._add_answer("pedido_ausente", "pedido", line["pedido_id"], line["restaurante_id"], line["semana"],
                             -line["valor_liquido"], "pedido entregue fora do repasse")
        self.st = self.st.drop(index=cands).reset_index(drop=True)

    def refund_not_deducted(self, n, n_hidden=0):
        st = self.st
        hidden = set(self.refunds.loc[self.refunds["_responsavel_oculto"], "estorno_id"])
        mask = (st["tipo_linha"] == "estorno") & ~st["referencia"].isin(self.keys_used) & ~st["_trap"]
        is_hidden = st["referencia"].isin(hidden)
        c_hidden = self.rng.permutation(np.array(st.index[mask & is_hidden].to_numpy()))[:n_hidden]
        c_other = self.rng.permutation(np.array(st.index[mask & ~is_hidden].to_numpy()))[:n - len(c_hidden)]
        cands = list(c_hidden) + list(c_other)
        for idx in cands:
            line = st.loc[idx]
            self._add_answer("estorno_nao_descontado", "estorno", line["referencia"], line["restaurante_id"],
                             line["semana"], -line["valor_liquido"], "estorno do restaurante sem desconto")
        self.st = st.drop(index=cands).reset_index(drop=True)

    def refund_duplicated(self, n):
        st = self.st
        mask = (st["tipo_linha"] == "estorno") & ~st["referencia"].isin(self.keys_used) & ~st["_trap"]
        cands = self.rng.permutation(np.array(st.index[mask].to_numpy()))[:n]
        extra = []
        for idx in cands:
            line = st.loc[idx].to_dict()
            extra.append(dict(line))
            self._add_answer("estorno_duplicado", "estorno", line["referencia"], line["restaurante_id"],
                             line["semana"], line["valor_liquido"], "estorno descontado duas vezes")
        self.st = pd.concat([st, pd.DataFrame(extra)], ignore_index=True)

    # -- traps on the statement
    def rounding_traps(self, n):
        st = self.st
        per_repasse: dict[str, int] = {}
        done = 0
        for idx in self.rng.permutation(self._candidate_order_lines()):
            if done >= n:
                break
            line = st.loc[idx]
            if per_repasse.get(line["repasse_id"], 0) >= 2:
                continue
            pv, o = self._pv_for(line["pedido_id"])
            new = statement_line_from_order(o, pv, rate_fn=apply_rate_truncated)
            diff = new["valor_liquido"] - line["valor_liquido"]
            if diff == 0 or abs(diff) > config.TOLERANCE_LINE_CENTS:
                continue
            self._rewrite(idx, new)
            st.at[idx, "_trap"] = True
            per_repasse[line["repasse_id"]] = per_repasse.get(line["repasse_id"], 0) + 1
            self._add_trap("arredondamento_centavos", "pedido", line["pedido_id"], line["restaurante_id"],
                           line["semana"], f"diferença de {diff} centavo(s) por truncamento")
            done += 1

    def manual_adjustments(self, n):
        reps = self.st.drop_duplicates("repasse_id")[["repasse_id", "restaurante_id", "semana"]]
        pick = reps.sample(n=n, random_state=int(self.rng.integers(1 << 31)))
        extra = []
        ticket_ids = unique_ids(self.rng, n, 40_000, 99_999)
        for (_, r), t in zip(pick.iterrows(), ticket_ids):
            text, sign = N.ADJUSTMENT_REASONS[self.rng.integers(len(N.ADJUSTMENT_REASONS))]
            value = sign * int(self.rng.integers(5, 160)) * 100 + sign * int(self.rng.choice([0, 50, 90]))
            start, _ = config.week_bounds(r["semana"])
            ticket = f"CHM-{t}"
            extra.append({"restaurante_id": r["restaurante_id"], "semana": r["semana"],
                          "repasse_id": r["repasse_id"], "tipo_linha": "ajuste", "pedido_id": None,
                          "referencia": ticket,
                          "data_referencia": datetime.combine(start + timedelta(days=int(self.rng.integers(0, 7))),
                                                              datetime.min.time()) + timedelta(hours=10),
                          "valor_itens": None, "taxa_entrega": None, "cupom_restaurante": None,
                          "comissao": None, "taxa_pagamento": None, "valor_liquido": value,
                          "_motivo": text, "_trap": True,
                          "_layout": self.st.loc[self.st["repasse_id"] == r["repasse_id"], "_layout"].iloc[0]})
            self._add_trap("ajuste_manual_legitimo", "ajuste", ticket, r["restaurante_id"], r["semana"],
                           f"{text} ({ticket})")
        self.st = pd.concat([self.st, pd.DataFrame(extra)], ignore_index=True)


# --------------------------------------------------------------------------- bank

def bank_name(text: str) -> str:
    t = " " + strip_accents(text).upper().replace(".", "").replace(",", "") + " "
    for long, short in N.BANK_ABBREVIATIONS.items():
        t = t.replace(long, short)
    for suffix in [" LTDA EPP", " LTDA ME", " LTDA", " EIRELI", " SLU", " ME "]:
        t = t.replace(suffix, " ")
    return " ".join(t.split())


def bank_description(rng, r: pd.Series, repasse_id: str) -> str:
    use_legal = rng.random() < 0.45
    name = bank_name(r["razao_social"] if use_legal else r["nome_fantasia"])
    cnpj_digits = "".join(c for c in r["cnpj"] if c.isdigit())
    ref = repasse_id.replace("REP-", "").replace("-", "")
    tpl = int(rng.integers(0, 6))
    if tpl == 0:
        return f"PIX ENVIADO {name[:22]}"
    if tpl == 1:
        return f"PIX ENV {cnpj_digits[:8]} {name[:18]}"
    if tpl == 2:
        return f"TED ENVIADA {name[:20]} AG{r['agencia']} CC{r['conta'].replace('-', '')}"
    if tpl == 3:
        return f"PAGTO FORNEC REPASSE {ref[:10 + int(rng.integers(0, 3))]} {name[:14]}"
    if tpl == 4:
        return f"TRANSF PIX LOTE {int(rng.integers(100, 999))} {name[:16]}"
    return f"PIX {name[:24]}"


def build_bank(rng, repasses: pd.DataFrame, rest: pd.DataFrame, planter: Planter, cfg: GeneratorConfig) -> pd.DataFrame:
    rinfo = rest.set_index("restaurante_id")
    payments = []
    for _, rp in repasses.iterrows():
        if rp["valor_total"] <= 0:
            continue
        due = config.payment_date(rp["semana"])
        offset = int(rng.choice([0, 1, 2], p=[0.88, 0.09, 0.03]))
        payments.append({"data": due + timedelta(days=offset), "valor": -int(rp["valor_total"]),
                         "historico": bank_description(rng, rinfo.loc[rp["restaurante_id"]], rp["repasse_id"]),
                         "_repasse_id": rp["repasse_id"], "_rid": rp["restaurante_id"], "_semana": rp["semana"]})
    pay = pd.DataFrame(payments)

    # Bank side errors.
    used = set()
    n_div = cfg.errors.get("transferencia_divergente", 0)
    for i in rng.permutation(len(pay)):
        if n_div == 0:
            break
        row = pay.loc[i]
        amount = -row["valor"]
        kind = int(rng.integers(0, 4))
        if kind == 0:  # two adjacent digits swapped
            s = str(amount)
            if len(s) < 4:
                continue
            j = int(rng.integers(0, len(s) - 1))
            if s[j] == s[j + 1]:
                continue
            new_amount = int(s[:j] + s[j + 1] + s[j] + s[j + 2:])
            if new_amount < 100:
                continue
            why = "dígitos trocados na digitação"
        elif kind == 1:
            new_amount, why = amount - 1000, "tarifa de R$ 10,00 descontada indevidamente"
        elif kind == 2:
            new_amount, why = amount // 2, "pagamento parcial"
        else:
            new_amount, why = amount + 10000, "R$ 100,00 a mais"
        pay.at[i, "valor"] = -new_amount
        used.add(row["_repasse_id"])
        planter._add_answer("transferencia_divergente", "repasse", row["_repasse_id"], row["_rid"], row["_semana"],
                            new_amount - amount, why)
        n_div -= 1

    extra = []
    n_dup = cfg.errors.get("repasse_duplicado", 0)
    for i in rng.permutation(len(pay)):
        if n_dup == 0:
            break
        row = pay.loc[i]
        if row["_repasse_id"] in used:
            continue
        used.add(row["_repasse_id"])
        extra.append({**row.to_dict(), "data": row["data"] + timedelta(days=int(rng.integers(1, 3))),
                      "historico": bank_description(rng, rinfo.loc[row["_rid"]], row["_repasse_id"])})
        planter._add_answer("repasse_duplicado", "repasse", row["_repasse_id"], row["_rid"], row["_semana"],
                            -row["valor"], "mesmo repasse pago duas vezes")
        n_dup -= 1

    n_ret = cfg.traps.get("pix_devolvido_reenviado", 0)
    for i in rng.permutation(len(pay)):
        if n_ret == 0:
            break
        row = pay.loc[i]
        if row["_repasse_id"] in used:
            continue
        used.add(row["_repasse_id"])
        r = rinfo.loc[row["_rid"]]
        name = bank_name(r["nome_fantasia"])[:20]
        extra.append({"data": row["data"] + timedelta(days=1), "valor": -row["valor"],
                      "historico": f"DEVOLUCAO PIX {name} CHAVE INEXISTENTE",
                      "_repasse_id": row["_repasse_id"], "_rid": row["_rid"], "_semana": row["_semana"]})
        extra.append({"data": row["data"] + timedelta(days=int(rng.integers(3, 6))), "valor": row["valor"],
                      "historico": f"TED ENVIADA {bank_name(r['razao_social'])[:20]} AG{r['agencia']} "
                                   f"CC{r['conta'].replace('-', '')}",
                      "_repasse_id": row["_repasse_id"], "_rid": row["_rid"], "_semana": row["_semana"]})
        planter._add_trap("pix_devolvido_reenviado", "repasse", row["_repasse_id"], row["_rid"], row["_semana"],
                          "Pix devolvido por chave inexistente e reenviado por TED")
        n_ret -= 1
    pay = pd.concat([pay, pd.DataFrame(extra)], ignore_index=True)

    # Other movements of the account, unrelated to payouts.
    noise = []
    first = config.PERIOD_START
    last = config.payment_date(config.week_ids()[-1]) + timedelta(days=2)
    day = first
    weekly_total = int(repasses["valor_total"].clip(lower=0).sum() / config.N_WEEKS)
    while day <= last:
        if day.weekday() < 5:
            noise.append({"data": day, "valor": int(weekly_total / 5 * rng.uniform(0.95, 1.25)),
                          "historico": f"RECEB ADQUIRENCIA LIQ CARTOES {(day - timedelta(days=1)).strftime('%d/%m')}"})
            noise.append({"data": day, "valor": int(weekly_total / 25 * rng.uniform(0.8, 1.2)),
                          "historico": "RECEB PIX COBRANCA CLIENTES"})
            if rng.random() < 0.4:
                noise.append({"data": day, "valor": -int(rng.integers(150_000, 2_500_000)),
                              "historico": f"PAGTO BOLETO {['LOGISTICA PARCEIRA', 'SERVICOS DE NUVEM', 'MARKETING DIGITAL', 'ALUGUEL ESCRITORIO'][int(rng.integers(0, 4))]}"})
        noise.append({"data": day, "valor": -int(rng.integers(5, 40)) * 50, "historico": "TARIFA PIX LOTE"})
        day += timedelta(days=1)
    for wid in config.week_ids():
        noise.append({"data": config.payment_date(wid), "valor": -int(rng.integers(800, 4000)),
                      "historico": "TARIFA TED"})
        noise.append({"data": config.payment_date(wid) - timedelta(days=1), "valor": -int(weekly_total * 0.15),
                      "historico": "APLICACAO AUTOMATICA"})
        noise.append({"data": config.payment_date(wid), "valor": int(weekly_total * 0.15) + int(rng.integers(1000, 50000)),
                      "historico": "RESGATE AUTOMATICO"})
    bank = pd.concat([pay, pd.DataFrame(noise)], ignore_index=True)
    bank["_ord"] = rng.random(len(bank))
    bank = bank.sort_values(["data", "_ord"]).drop(columns="_ord").reset_index(drop=True)
    docs = unique_ids(rng, len(bank), 100_000, 999_999)
    bank["documento"] = [str(d) if rng.random() < 0.8 else "" for d in docs]
    bank["saldo"] = 180_000_000 + bank["valor"].cumsum()
    return bank


# --------------------------------------------------------------------------- orchestration

def generate(cfg: GeneratorConfig | None = None) -> World:
    cfg = cfg or GeneratorConfig()
    rng = np.random.default_rng(cfg.seed)
    rest = build_restaurants(rng, cfg)
    rplans_df = build_restaurant_plans(rng, cfg, rest)
    rplans: dict = {}
    for row in rplans_df.to_dict("records"):
        rplans.setdefault(row["restaurante_id"], []).append(row)
    orders = build_orders(rng, cfg, rest, rplans)
    refunds = build_refunds(rng, cfg, orders)

    # Complementary refunds: a second, legitimate refund with the same value.
    comp = refunds[(refunds["responsavel"] == "restaurante")]
    comp = comp[comp["valor_estornado"] * 2 <= comp["pedido_id"].map(orders.set_index("pedido_id")["valor_itens"])]
    comp = comp[comp["processado_em"] < period_end_dt() - timedelta(days=3)]
    comp = comp.sample(n=cfg.traps.get("estorno_complementar", 0), random_state=int(rng.integers(1 << 31)))
    comp_rows = []
    new_ids = unique_ids(rng, len(comp) + 50, 100_000, 999_999)
    existing = set(refunds["estorno_id"])
    new_ids = [i for i in new_ids if f"EST-{i}" not in existing][:len(comp)]
    for (_, e), nid in zip(comp.iterrows(), new_ids):
        comp_rows.append({**e.to_dict(), "estorno_id": f"EST-{nid}", "_responsavel_oculto": False,
                          "processado_em": e["processado_em"] + timedelta(hours=float(rng.uniform(2, 40))),
                          "motivo": "segundo item faltando no mesmo pedido (estorno complementar)"})
    refunds = pd.concat([refunds, pd.DataFrame(comp_rows)], ignore_index=True)
    refunds = refunds.sort_values("processado_em").reset_index(drop=True)

    statement = build_statement(orders, refunds, rest, rplans)
    statement["_trap"] = False
    comp_ids = {r["estorno_id"] for r in comp_rows}
    statement.loc[statement["referencia"].isin(comp_ids), "_trap"] = True

    planter = Planter(rng, {"orders": orders, "refunds": refunds, "rest": rest, "statement": statement}, rplans)
    for e in comp_rows:
        planter._add_trap("estorno_complementar", "estorno", e["estorno_id"], e["restaurante_id"],
                          week_of(e["processado_em"]), "segundo estorno legítimo, mesmo valor do primeiro")
    # Natural traps are excluded from error targets so each case has one label.
    end = period_end_dt()
    delivered = orders[orders["status"] == "entregue"]
    crossing = delivered[(delivered["criado_em"].dt.day_of_week == 6)
                         & (delivered["concluido_em"].dt.date > delivered["criado_em"].dt.date)]
    planter.st.loc[planter.st["pedido_id"].isin(set(crossing["pedido_id"])) & (planter.st["tipo_linha"] == "pedido"),
                   "_trap"] = True

    e = cfg.errors
    planter.old_plan_after_change(e.get("comissao_plano_antigo", 0))
    planter.commission_wrong_rate(e.get("comissao_taxa_errada", 0))
    planter.payment_fee_wrong(e.get("taxa_pagamento_errada", 0))
    planter.platform_coupon_charged(e.get("cupom_plataforma_cobrado", 0))
    planter.rounding_traps(cfg.traps.get("arredondamento_centavos", 0))
    planter.refund_not_deducted(e.get("estorno_nao_descontado", 0), cfg.refund_not_deducted_hidden)
    planter.refund_duplicated(e.get("estorno_duplicado", 0))
    planter.missing_order(e.get("pedido_ausente", 0))
    planter.duplicated_order(e.get("pedido_duplicado", 0))
    planter.manual_adjustments(cfg.traps.get("ajuste_manual_legitimo", 0))

    st = planter.st
    # Natural traps: week crossing, cancelled before preparation, platform refunds, out of period.
    for _, o in crossing.iterrows():
        if o["concluido_em"] < end:
            planter._add_trap("pedido_virada_de_semana", "pedido", o["pedido_id"], o["restaurante_id"],
                              week_of(o["concluido_em"]), "criado no domingo, concluído depois da meia-noite")
        else:
            planter._add_trap("pedido_fora_do_periodo", "pedido", o["pedido_id"], o["restaurante_id"],
                              week_of(o["concluido_em"]), "concluído depois do fechamento do período")
    for _, o in orders[orders["status"] == "cancelado"].iterrows():
        planter._add_trap("cancelado_antes_do_preparo", "pedido", o["pedido_id"], o["restaurante_id"],
                          week_of(o["criado_em"]), "cancelado antes do preparo, sem cobrança")
    for _, r in refunds[refunds["responsavel"] == "plataforma"].iterrows():
        planter._add_trap("estorno_da_plataforma", "estorno", r["estorno_id"], r["restaurante_id"],
                          week_of(r["processado_em"]), "estorno assumido pela plataforma")

    # Statement line ids and descriptions.
    st = st.sort_values(["repasse_id", "tipo_linha", "data_referencia"], kind="stable").reset_index(drop=True)
    st["linha_id"] = [f"L{i + 1:06d}" for i in range(len(st))]
    desc = []
    for _, line in st.iterrows():
        if line["tipo_linha"] == "pedido":
            if line["_layout"] == "legado":
                desc.append(legacy_order_description(rng, line))
            else:
                desc.append(f"Pedido {line['pedido_id']}")
        elif line["tipo_linha"] == "estorno":
            if line["_layout"] == "legado":
                desc.append(f"Estorno ref. pedido {line['pedido_id']} ({line['_motivo']})")
            else:
                desc.append(f"Estorno {line['referencia']} do pedido {line['pedido_id']}")
        else:
            desc.append(line["_motivo"])
    st["descricao"] = desc
    # Legacy layout exports only the net value of each line.
    legacy = st["_layout"] == "legado"
    for col in ["valor_itens", "taxa_entrega", "cupom_restaurante", "comissao", "taxa_pagamento"]:
        st.loc[legacy, col] = None
    st.loc[legacy & (st["tipo_linha"] == "estorno"), "referencia"] = None

    repasses = (st.groupby(["repasse_id", "restaurante_id", "semana"], as_index=False)
                .agg(qtd_linhas=("linha_id", "count"), valor_total=("valor_liquido", "sum")))
    bank = build_bank(rng, repasses, rest, planter, cfg)

    answer = pd.DataFrame(planter.answer)
    answer.insert(0, "caso_id", [f"E{i + 1:04d}" for i in range(len(answer))])
    traps = pd.DataFrame(planter.traps)
    traps.insert(0, "caso_id", [f"A{i + 1:05d}" for i in range(len(traps))])

    # The orders export comes with a few exact duplicate rows (a known export glitch).
    dup_rows = orders.sample(n=cfg.n_duplicate_export_rows, random_state=int(rng.integers(1 << 31)))
    orders_export = pd.concat([orders, dup_rows]).sort_values("criado_em", kind="stable").reset_index(drop=True)

    return World(restaurants=rest, restaurant_plans=rplans_df, orders=orders_export, refunds=refunds,
                 statement=st, repasses=repasses, bank=bank, answer_key=answer, traps=traps)


def main(argv=None):
    from .writers import write_world

    parser = argparse.ArgumentParser(description="Generate synthetic marketplace payout data.")
    parser.add_argument("--seed", type=int, default=GeneratorConfig.seed)
    parser.add_argument("--restaurants", type=int, default=GeneratorConfig.n_restaurants)
    args = parser.parse_args(argv)
    cfg = GeneratorConfig(seed=args.seed, n_restaurants=args.restaurants)
    world = generate(cfg)
    paths = write_world(world, config.RAW_DIR, config.ANSWER_KEY_DIR)
    (config.ANSWER_KEY_DIR / "generator_config.json").write_text(
        json.dumps(asdict(cfg), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    for p in paths:
        print(p.relative_to(config.ROOT))


if __name__ == "__main__":
    main()
