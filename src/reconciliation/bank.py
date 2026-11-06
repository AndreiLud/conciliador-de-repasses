"""Assigns bank payments to payouts.

The SQL stage 08 lists candidates; this module walks the payments in date
order and decides, with explicit rules:

1. exact value, restaurant evidence and paid from D+0 to D+2: payout paid;
2. a returned payment (DEVOLUCAO) reopens the payout it refers to, and a new
   payment of the same value within seven days is a resend, not a duplicate;
3. a second payment of the same value for a payout already paid: duplicate;
4. a payment that identifies the restaurant (CNPJ, branch and account, payout
   reference or a clearly best name) but not the value: amount differs;
5. anything else is not identified and goes to the ambiguous queue.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import pandas as pd

from .. import config


@dataclass
class BankFinding:
    familia: str
    chave: str
    restaurante_id: str | None
    semana: str | None
    repasse_id: str | None
    valor_centavos: int
    banco_linhas: list[str]
    detalhe: str
    candidatos: list[dict] = field(default_factory=list)


def _rank(df: pd.DataFrame) -> pd.DataFrame:
    """Strong identifiers first, then name similarity, then the earliest settlement."""
    weak = ~(df["ev_ref"].astype(bool) | df["ev_cnpj"].astype(bool) | df["ev_conta"].astype(bool))
    return (df.assign(_weak=weak, _neg=-df["score"].astype(float))
              .sort_values(["_weak", "_neg", "dias_apos_previsto", "repasse_id"], kind="stable"))


def match_bank(con) -> tuple[pd.DataFrame, list[BankFinding]]:
    lines = con.sql("SELECT * FROM bank_lines WHERE categoria IN ('pagamento', 'devolucao') "
                    "ORDER BY data, banco_linha_id").df()
    cands = con.sql("SELECT * FROM bank_repasse_candidates").df()
    repasses = con.sql("SELECT * FROM stg_repasses").df().set_index("repasse_id")
    by_line = {k: g for k, g in cands.groupby("banco_linha_id")}
    window = config.BANK_DATE_WINDOW_DAYS

    paid: dict[str, str] = {}          # payout -> bank line currently settling it
    returned: dict[str, object] = {}   # payout -> date its payment came back
    status: dict[str, tuple[str, str]] = {}  # bank line -> (payout, status)
    findings: list[BankFinding] = []
    payments = lines[lines["categoria"] == "pagamento"]
    returns = lines[lines["categoria"] == "devolucao"]

    # 1. exact matches
    deferred = []
    for _, p in payments.iterrows():
        c = by_line.get(p["banco_linha_id"])
        if c is None:
            deferred.append(p)
            continue
        exact = c[c["valor_confere"] & c["dias_apos_previsto"].between(0, window)]
        exact = _rank(exact)
        chosen = next((r for _, r in exact.iterrows() if r["repasse_id"] not in paid), None)
        if chosen is None:
            deferred.append(p)
            continue
        paid[chosen["repasse_id"]] = p["banco_linha_id"]
        status[p["banco_linha_id"]] = (chosen["repasse_id"], "pago")

    # 2. returned payments reopen their payout
    for _, d in returns.iterrows():
        c = by_line.get(d["banco_linha_id"])
        if c is None:
            continue
        restaurants = set(c.loc[c["score"] >= config.BANK_NAME_SIMILARITY_MIN, "restaurante_id"])
        for rep, bl in list(paid.items()):
            prow = lines.loc[lines["banco_linha_id"] == bl].iloc[0]
            if (repasses.at[rep, "restaurante_id"] in restaurants and -prow["valor"] == d["valor"]
                    and timedelta(0) <= d["data"] - prow["data"] <= timedelta(days=5)):
                status[bl] = (rep, "devolvido")
                status[d["banco_linha_id"]] = (rep, "devolucao")
                returned[rep] = d["data"]
                del paid[rep]
                break

    # 3 to 5. what is left
    for p in deferred:
        bl = p["banco_linha_id"]
        c = by_line.get(bl)
        amount = int(-p["valor"])
        if c is None:
            findings.append(BankFinding("banco_nao_identificado", bl, None, None, None, amount, [bl],
                                        "pagamento sem restaurante candidato"))
            continue
        exact = c[c["valor_confere"]]
        resend = exact[exact["repasse_id"].isin(returned.keys())]
        resend = resend[[timedelta(0) <= p["data"] - returned[r] <= timedelta(days=7) for r in resend["repasse_id"]]] \
            if len(resend) else resend
        if len(resend) and resend.iloc[0]["repasse_id"] not in paid:
            rep = resend.iloc[0]["repasse_id"]
            paid[rep] = bl
            status[bl] = (rep, "reenvio")
            continue
        already = exact[exact["repasse_id"].isin(paid.keys()) & exact["dias_apos_previsto"].between(0, 10)]
        if len(already):
            row = _rank(already).iloc[0]
            rep = row["repasse_id"]
            findings.append(BankFinding("banco_pagamento_repetido", rep, row["restaurante_id"], row["semana"], rep,
                                        amount, [paid[rep], bl], "segundo pagamento de um repasse já pago"))
            status[bl] = (rep, "repetido")
            continue
        open_c = c[~c["repasse_id"].isin(paid.keys()) & c["dias_apos_previsto"].between(0, window)]
        if len(open_c) == 0:
            findings.append(BankFinding("banco_nao_identificado", bl, None, None, None, amount, [bl],
                                        "nenhum repasse em aberto para os restaurantes candidatos",
                                        _candidate_list(c)))
            continue
        per_rest = (open_c.groupby("restaurante_id")
                    .agg(score=("score", "max"), ev_ref=("ev_ref", "max"), ev_cnpj=("ev_cnpj", "max"),
                         ev_conta=("ev_conta", "max"), n=("repasse_id", "nunique"))
                    .sort_values("score", ascending=False))
        strong = per_rest[per_rest["ev_ref"] | per_rest["ev_cnpj"] | per_rest["ev_conta"]]
        best = None
        if len(strong) == 1:
            best = strong.index[0]
        elif len(strong) == 0 and len(per_rest):
            top = per_rest.iloc[0]
            second = per_rest.iloc[1]["score"] if len(per_rest) > 1 else 0.0
            if top["score"] >= config.BANK_NAME_SIMILARITY_STRONG and top["score"] - second >= 0.05:
                best = per_rest.index[0]
        if best is not None and per_rest.at[best, "n"] == 1:
            row = open_c[open_c["restaurante_id"] == best].iloc[0]
            rep = row["repasse_id"]
            paid[rep] = bl
            status[bl] = (rep, "valor_divergente")
            findings.append(BankFinding("banco_valor_divergente", rep, best, row["semana"], rep,
                                        amount - int(row["valor_total"]), [bl],
                                        "restaurante identificado, valor diferente do extrato"))
            continue
        findings.append(BankFinding("banco_nao_identificado", bl, None, None, None, amount, [bl],
                                    "mais de um repasse possível para este pagamento", _candidate_list(open_c)))

    for _, d in returns.iterrows():
        if d["banco_linha_id"] not in status:
            findings.append(BankFinding("banco_devolucao_sem_par", d["banco_linha_id"], None, None, None,
                                        -int(d["valor"]), [d["banco_linha_id"]],
                                        "devolução no banco sem pagamento correspondente"))

    for rep, row in repasses.iterrows():
        if row["valor_total"] > 0 and rep not in paid:
            findings.append(BankFinding("repasse_sem_pagamento", rep, row["restaurante_id"], row["semana"], rep,
                                        -int(row["valor_total"]), [], "repasse sem pagamento no banco"))

    match_df = pd.DataFrame([{"banco_linha_id": k, "repasse_id": v[0], "status": v[1]} for k, v in status.items()])
    return match_df, findings


def _candidate_list(c: pd.DataFrame, limit: int = 4) -> list[dict]:
    c = _rank(c)
    out = []
    for _, r in c.drop_duplicates("repasse_id").head(limit).iterrows():
        out.append({"repasse_id": r["repasse_id"], "restaurante_id": r["restaurante_id"],
                    "valor_total": int(r["valor_total"]), "data_prevista": str(r["data_pagamento_prevista"]),
                    "similaridade_nome": round(float(r["sim_nome"]), 3), "cnpj_confere": bool(r["ev_cnpj"]),
                    "conta_confere": bool(r["ev_conta"]), "referencia_confere": bool(r["ev_ref"]),
                    "valor_confere": bool(r["valor_confere"])})
    return out
