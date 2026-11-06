"""Write a generated World in the formats a finance team actually receives."""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from .. import config
from ..money import format_number_br


def _dot(cents) -> str:
    if cents is None or (isinstance(cents, float) and np.isnan(cents)):
        return ""
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"


def _br(cents) -> str:
    if cents is None or (isinstance(cents, float) and np.isnan(cents)):
        return ""
    return format_number_br(int(cents))


def _ts(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)) or value is pd.NaT:
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _br_dt(value) -> str:
    return pd.Timestamp(value).strftime("%d/%m/%Y %H:%M")


def _br_d(value) -> str:
    return pd.Timestamp(value).strftime("%d/%m/%Y")


def write_orders(world, path: Path, rng: np.random.Generator) -> None:
    o = world.orders
    method_variants = {"credito": ["Crédito", "CREDITO", "credito "], "pix": ["PIX", "Pix"],
                       "debito": ["Débito", "DEBITO"], "vale_refeicao": ["Vale Refeição", "VR", "vale-refeicao"]}
    rows = []
    for rec in o.to_dict("records"):
        # Formatting noise depends only on the order id, so duplicated export rows stay identical.
        h = (int(rec["pedido_id"]) * 2654435761) % 100_000
        method = rec["forma_pagamento"]
        if h < 3_000:
            opts = method_variants[method]
            method = opts[h % len(opts)]
        rid = rec["restaurante_id"].lower() if 50_000 <= h < 50_200 else rec["restaurante_id"]
        rows.append({
            "pedido_id": rec["pedido_id"], "restaurante_id": rid,
            "criado_em": _ts(rec["criado_em"]), "concluido_em": _ts(rec["concluido_em"]),
            "status": rec["status"], "cancelado_em": _ts(rec["cancelado_em"]),
            "etapa_cancelamento": rec["etapa_cancelamento"] or "",
            "valor_itens": _dot(rec["valor_itens"]), "taxa_entrega": _dot(rec["taxa_entrega"]),
            "cupom_codigo": rec["cupom_codigo"] or "", "cupom_valor": _dot(rec["cupom_valor"]),
            "cupom_custeio": rec["cupom_custeio"] or "", "forma_pagamento": method,
            "valor_total": _dot(rec["valor_total"]),
        })
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")


def write_refunds(world, path: Path) -> None:
    r = world.refunds.copy()
    out = pd.DataFrame({
        "estorno_id": r["estorno_id"], "pedido_id": r["pedido_id"], "restaurante_id": r["restaurante_id"],
        "processado_em": r["processado_em"].map(_ts), "valor_estornado": r["valor_estornado"].map(_dot),
        "responsavel": r["responsavel"].where(~r["_responsavel_oculto"], ""),
        "motivo": r["motivo"].map(lambda s: f" {s}  " if len(s) % 7 == 0 else s),
    })
    out.to_csv(path, index=False, encoding="utf-8")


def write_statement(world, path: Path) -> None:
    st = world.statement
    neg = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else -int(v)
    rows = []
    for rec in st.to_dict("records"):
        rows.append({
            "repasse_id": rec["repasse_id"], "restaurante_id": rec["restaurante_id"], "semana": rec["semana"],
            "linha_id": rec["linha_id"], "tipo_linha": rec["tipo_linha"],
            "pedido_id": rec["pedido_id"] or "", "referencia": rec["referencia"] or "",
            "data_referencia": _br_dt(rec["data_referencia"]),
            "valor_itens": _br(rec["valor_itens"]), "taxa_entrega": _br(rec["taxa_entrega"]),
            "cupom_restaurante": _br(neg(rec["cupom_restaurante"])), "comissao": _br(neg(rec["comissao"])),
            "taxa_pagamento": _br(neg(rec["taxa_pagamento"])), "valor_liquido": _br(rec["valor_liquido"]),
            "descricao": rec["descricao"],
        })
    pd.DataFrame(rows).to_csv(path, index=False, sep=";", encoding="utf-8", quoting=csv.QUOTE_MINIMAL)


def write_repasses(world, path: Path) -> None:
    rows = []
    for rec in world.repasses.to_dict("records"):
        start, end = config.week_bounds(rec["semana"])
        rows.append({
            "repasse_id": rec["repasse_id"], "restaurante_id": rec["restaurante_id"], "semana": rec["semana"],
            "periodo_inicio": _br_d(start), "periodo_fim": _br_d(end),
            "data_pagamento_prevista": _br_d(config.payment_date(rec["semana"])),
            "qtd_linhas": rec["qtd_linhas"], "valor_total": _br(rec["valor_total"]),
        })
    pd.DataFrame(rows).to_csv(path, index=False, sep=";", encoding="utf-8")


def write_bank(world, path: Path) -> None:
    b = world.bank
    first, last = b["data"].min(), b["data"].max()
    lines = [
        "Banco Ficticio de Pagamentos S.A.;;;;",
        "Extrato de conta corrente;;;;",
        "Cliente: TALHER INTERMEDIACAO DE PEDIDOS LTDA;;;;",
        "Agência: 0001   Conta: 778812-4;;;;",
        f"Período: {_br_d(first)} a {_br_d(last)};;;;",
        ";;;;",
        "Data;Lançamento;Documento;Valor (R$);Saldo (R$)",
        f"{_br_d(first)};SALDO ANTERIOR;;;{_br(int(b['saldo'].iloc[0] - b['valor'].iloc[0]))}",
    ]
    for rec in b.to_dict("records"):
        lines.append(f"{_br_d(rec['data'])};{rec['historico']};{rec['documento']};{_br(rec['valor'])};{_br(rec['saldo'])}")
    lines += [";;;;", f"Saldo final em {_br_d(last)};;;;{_br(int(b['saldo'].iloc[-1]))}",
              "Os lançamentos acima estão sujeitos a confirmação.;;;;"]
    path.write_text("\r\n".join(lines) + "\r\n", encoding="latin-1")


def write_contracts(world, path: Path) -> None:
    wb = Workbook()
    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F2937")

    def sheet(ws, header, rows, pct_cols=(), date_cols=()):
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
        for r in rows:
            ws.append(r)
        for col_idx, name in enumerate(header, start=1):
            letter = ws.cell(row=1, column=col_idx).column_letter
            ws.column_dimensions[letter].width = max(12, len(name) + 4)
            for cell in ws[letter][1:]:
                if name in pct_cols:
                    cell.number_format = "0.00%"
                if name in date_cols:
                    cell.number_format = "DD/MM/YYYY"

    ws = wb.active
    ws.title = "planos"
    rows = []
    for pv in world.plan_versions:
        rows.append([pv.plan_id, pv.name + ("  " if pv.plan_id == "PLUS" else ""), pv.version, pv.valid_from,
                     pv.valid_to, pv.commission_bps / 10000, pv.delivery,
                     pv.fee_bps["pix"] / 10000, pv.fee_bps["debito"] / 10000,
                     pv.fee_bps["credito"] / 10000, pv.fee_bps["vale_refeicao"] / 10000])
    sheet(ws, ["plano_id", "nome", "versao", "vigencia_inicio", "vigencia_fim", "comissao", "entrega",
               "taxa_pix", "taxa_debito", "taxa_credito", "taxa_vale_refeicao"], rows,
          pct_cols={"comissao", "taxa_pix", "taxa_debito", "taxa_credito", "taxa_vale_refeicao"},
          date_cols={"vigencia_inicio", "vigencia_fim"})

    ws = wb.create_sheet("restaurante_plano")
    rows = []
    for i, r in enumerate(world.restaurant_plans.to_dict("records")):
        pid = r["plano_id"].lower() if i % 37 == 5 else r["plano_id"]
        rows.append([r["restaurante_id"], pid, r["vigencia_inicio"], r["vigencia_fim"]])
    sheet(ws, ["restaurante_id", "plano_id", "vigencia_inicio", "vigencia_fim"], rows,
          date_cols={"vigencia_inicio", "vigencia_fim"})

    ws = wb.create_sheet("cadastro")
    rows = [[r["restaurante_id"], r["nome_fantasia"], r["razao_social"], r["cnpj"], r["cidade"], r["uf"],
             r["categoria"], r["agencia"], r["conta"], date.fromisoformat(r["cliente_desde"])]
            for r in world.restaurants.to_dict("records")]
    sheet(ws, ["restaurante_id", "nome_fantasia", "razao_social", "cnpj", "cidade", "uf", "categoria",
               "agencia", "conta", "cliente_desde"], rows, date_cols={"cliente_desde"})
    wb.save(path)


def write_answer_key(world, answer_dir: Path) -> list[Path]:
    answer_dir.mkdir(parents=True, exist_ok=True)
    p1, p2 = answer_dir / "gabarito.csv", answer_dir / "armadilhas.csv"
    world.answer_key.to_csv(p1, index=False, encoding="utf-8")
    world.traps.to_csv(p2, index=False, encoding="utf-8")
    return [p1, p2]


def write_world(world, raw_dir: Path, answer_dir: Path, seed: int = 7) -> list[Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    paths = {
        "pedidos.csv": lambda p: write_orders(world, p, rng),
        "estornos.csv": lambda p: write_refunds(world, p),
        "repasse_extrato.csv": lambda p: write_statement(world, p),
        "repasses.csv": lambda p: write_repasses(world, p),
        "extrato_bancario.csv": lambda p: write_bank(world, p),
        "contratos.xlsx": lambda p: write_contracts(world, p),
    }
    out = []
    for name, fn in paths.items():
        fn(raw_dir / name)
        out.append(raw_dir / name)
    return out + write_answer_key(world, answer_dir)
