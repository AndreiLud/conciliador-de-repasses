"""Ingestion: read the raw files, validate, clean and log every decision.

Each loader returns a typed DataFrame (money in integer cents, rates in basis
points, timestamps as naive local datetimes) and appends entries to a
``QualityLog``. Cleaned tables are written to ``data/interim`` as Parquet,
which the SQL stages read.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from .. import config
from ..money import parse_brl, parse_dot_decimal, rate_from_fraction
from .normalize import bank_style

PAYMENT_ALIASES = {
    "pix": "pix", "credito": "credito", "cartao de credito": "credito", "debito": "debito",
    "cartao de debito": "debito", "vale refeicao": "vale_refeicao", "vale-refeicao": "vale_refeicao",
    "vale_refeicao": "vale_refeicao", "vr": "vale_refeicao",
}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return " ".join(t.lower().strip().split())


@dataclass
class QualityEntry:
    arquivo: str
    verificacao: str
    resultado: str  # ok | aviso | corrigido | erro
    quantidade: int
    decisao: str
    justificativa: str = ""


@dataclass
class QualityLog:
    entries: list[QualityEntry] = field(default_factory=list)

    def add(self, arquivo, verificacao, quantidade, decisao="", justificativa="", resultado=None):
        if resultado is None:
            resultado = "ok" if quantidade == 0 else "corrigido"
        self.entries.append(QualityEntry(arquivo, verificacao, resultado, int(quantidade), decisao, justificativa))

    def errors(self) -> list[QualityEntry]:
        return [e for e in self.entries if e.resultado == "erro"]

    def to_records(self) -> list[dict]:
        return [asdict(e) for e in self.entries]


class IngestionError(RuntimeError):
    pass


# --------------------------------------------------------------------------- orders

def load_orders(path: Path, log: QualityLog) -> pd.DataFrame:
    f = path.name
    raw = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    expected = ["pedido_id", "restaurante_id", "criado_em", "concluido_em", "status", "cancelado_em",
                "etapa_cancelamento", "valor_itens", "taxa_entrega", "cupom_codigo", "cupom_valor",
                "cupom_custeio", "forma_pagamento", "valor_total"]
    missing = [c for c in expected if c not in raw.columns]
    if missing:
        raise IngestionError(f"{f}: missing columns {missing}")
    log.add(f, "colunas obrigatórias presentes", 0, "nenhuma", f"{len(expected)} colunas")

    n_before = len(raw)
    dup_mask = raw.duplicated(keep="first")
    raw = raw[~dup_mask].copy()
    log.add(f, "linhas idênticas repetidas", int(dup_mask.sum()), "mantida uma cópia de cada",
            "linhas 100% iguais são falha de exportação, não pedidos distintos")

    conflict = raw["pedido_id"].duplicated(keep=False)
    log.add(f, "pedido_id único", int(conflict.sum()),
            "interromper" if conflict.any() else "nenhuma",
            "mesmo id com conteúdo diferente exige correção na origem",
            resultado="erro" if conflict.any() else "ok")
    if conflict.any():
        raise IngestionError(f"{f}: conflicting duplicated pedido_id")

    rid_fixed = raw["restaurante_id"] != raw["restaurante_id"].str.strip().str.upper()
    raw["restaurante_id"] = raw["restaurante_id"].str.strip().str.upper()
    log.add(f, "restaurante_id fora do padrão (minúsculas ou espaços)", int(rid_fixed.sum()),
            "convertido para maiúsculas sem espaços", "o cadastro usa o padrão R0000")

    norm_methods = raw["forma_pagamento"].map(_norm).map(PAYMENT_ALIASES)
    unknown = norm_methods.isna()
    if unknown.any():
        raise IngestionError(f"{f}: unknown payment methods {raw.loc[unknown, 'forma_pagamento'].unique()[:5]}")
    variants = raw["forma_pagamento"] != norm_methods
    raw["forma_pagamento"] = norm_methods
    log.add(f, "forma de pagamento com grafia variada", int(variants.sum()),
            "normalizada para pix, credito, debito ou vale_refeicao",
            "a mesma forma aparece com acento, maiúsculas ou abreviação")

    out = pd.DataFrame({
        "pedido_id": raw["pedido_id"].str.strip(),
        "restaurante_id": raw["restaurante_id"],
        "criado_em": pd.to_datetime(raw["criado_em"], format="%Y-%m-%d %H:%M:%S"),
        "concluido_em": pd.to_datetime(raw["concluido_em"].replace("", None), format="%Y-%m-%d %H:%M:%S"),
        "status": raw["status"].str.strip().str.lower(),
        "cancelado_em": pd.to_datetime(raw["cancelado_em"].replace("", None), format="%Y-%m-%d %H:%M:%S"),
        "etapa_cancelamento": raw["etapa_cancelamento"].replace("", None),
        "cupom_codigo": raw["cupom_codigo"].replace("", None),
        "cupom_custeio": raw["cupom_custeio"].replace("", None),
        "forma_pagamento": raw["forma_pagamento"],
    })
    for col in ["valor_itens", "taxa_entrega", "cupom_valor", "valor_total"]:
        out[col] = raw[col].map(parse_dot_decimal).fillna(0).astype("int64")

    bad_status = ~out["status"].isin(["entregue", "cancelado"])
    log.add(f, "status fora do domínio", int(bad_status.sum()), "nenhuma", resultado="erro" if bad_status.any() else "ok")
    no_conc = (out["status"] == "entregue") & out["concluido_em"].isna()
    log.add(f, "pedido entregue sem data de conclusão", int(no_conc.sum()), "nenhuma",
            resultado="erro" if no_conc.any() else "ok")
    no_cancel = (out["status"] == "cancelado") & out["cancelado_em"].isna()
    log.add(f, "pedido cancelado sem data de cancelamento", int(no_cancel.sum()), "nenhuma",
            resultado="erro" if no_cancel.any() else "ok")
    neg = (out[["valor_itens", "taxa_entrega", "cupom_valor"]] < 0).any(axis=1)
    log.add(f, "valores negativos", int(neg.sum()), "nenhuma", resultado="erro" if neg.any() else "ok")
    coupon_bad = (out["cupom_valor"] > 0) & ~out["cupom_custeio"].isin(["plataforma", "restaurante"])
    log.add(f, "cupom sem indicação de quem paga", int(coupon_bad.sum()), "nenhuma",
            resultado="erro" if coupon_bad.any() else "ok")
    total_bad = out["valor_total"] != out["valor_itens"] + out["taxa_entrega"] - out["cupom_valor"]
    log.add(f, "valor_total = itens + entrega − cupom", int(total_bad.sum()), "nenhuma",
            "o total pago é a base da taxa de pagamento", resultado="erro" if total_bad.any() else "ok")
    log.add(f, "pedidos válidos após limpeza", 0, f"{len(out)} pedidos de {n_before} linhas lidas",
            resultado="ok")
    return out


# --------------------------------------------------------------------------- refunds

def load_refunds(path: Path, orders: pd.DataFrame, log: QualityLog) -> pd.DataFrame:
    f = path.name
    raw = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    trimmed = raw["motivo"] != raw["motivo"].str.strip()
    log.add(f, "motivo com espaços sobrando", int(trimmed.sum()), "espaços removidos", "não muda o conteúdo")
    out = pd.DataFrame({
        "estorno_id": raw["estorno_id"].str.strip(),
        "pedido_id": raw["pedido_id"].str.strip(),
        "restaurante_id": raw["restaurante_id"].str.strip().str.upper(),
        "processado_em": pd.to_datetime(raw["processado_em"], format="%Y-%m-%d %H:%M:%S"),
        "valor_estornado": raw["valor_estornado"].map(parse_dot_decimal).astype("int64"),
        "responsavel": raw["responsavel"].str.strip().str.lower(),
        "motivo": raw["motivo"].str.strip(),
    })
    dup = out["estorno_id"].duplicated()
    log.add(f, "estorno_id único", int(dup.sum()), "nenhuma", resultado="erro" if dup.any() else "ok")
    orphan = ~out["pedido_id"].isin(orders["pedido_id"])
    log.add(f, "estorno de pedido inexistente", int(orphan.sum()), "nenhuma", resultado="erro" if orphan.any() else "ok")
    items = out["pedido_id"].map(orders.set_index("pedido_id")["valor_itens"])
    total_ref = out.groupby("pedido_id")["valor_estornado"].transform("sum")
    over = total_ref > items + out["pedido_id"].map(orders.set_index("pedido_id")["taxa_entrega"])
    log.add(f, "estornos somados acima do valor do pedido", int(over.sum()), "nenhuma",
            resultado="aviso" if over.any() else "ok")
    blank_owner = out["responsavel"].eq("") | out["responsavel"].isna()
    out.loc[blank_owner, "responsavel"] = None
    odd_owner = out["responsavel"].notna() & ~out["responsavel"].isin(["restaurante", "plataforma"])
    log.add(f, "responsável fora de restaurante ou plataforma", int(odd_owner.sum()),
            "tratado como não preenchido e decidido pela nota", "um rótulo desconhecido não pode virar isenção",
            resultado="aviso" if odd_owner.any() else "ok")
    out.loc[odd_owner, "responsavel"] = None
    blank_owner = out["responsavel"].isna()
    log.add(f, "estorno sem responsável preenchido", int(blank_owner.sum()),
            "mantido; o dono é decidido pela nota do atendimento",
            "palavra-chave quando é claro, modelo de linguagem quando não é, revisão humana se a confiança for baixa",
            resultado="aviso" if blank_owner.any() else "ok")
    multi = out["pedido_id"].duplicated(keep=False)
    log.add(f, "pedidos com mais de um estorno", int(out.loc[multi, "pedido_id"].nunique()),
            "mantidos; cada estorno tem id próprio", "estorno complementar é legítimo", resultado="ok")
    return out


# --------------------------------------------------------------------------- payout statement

def load_statement(path: Path, log: QualityLog) -> pd.DataFrame:
    f = path.name
    raw = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    out = pd.DataFrame({
        "repasse_id": raw["repasse_id"].str.strip(),
        "restaurante_id": raw["restaurante_id"].str.strip().str.upper(),
        "semana": raw["semana"].str.strip(),
        "linha_id": raw["linha_id"].str.strip(),
        "tipo_linha": raw["tipo_linha"].str.strip().str.lower(),
        "pedido_id": raw["pedido_id"].str.strip().replace("", None),
        "referencia": raw["referencia"].str.strip().replace("", None),
        "data_referencia": pd.to_datetime(raw["data_referencia"], format="%d/%m/%Y %H:%M"),
        "descricao": raw["descricao"].str.strip(),
    })
    # Deductions come as negative numbers; store magnitudes.
    for col, sign in [("valor_itens", 1), ("taxa_entrega", 1), ("cupom_restaurante", -1),
                      ("comissao", -1), ("taxa_pagamento", -1), ("valor_liquido", 1)]:
        # Built straight as nullable integers: no float on the way.
        out[col] = pd.array([None if (c := parse_brl(v)) is None else c * sign for v in raw[col]], dtype="Int64")
    comp_cols = ["valor_itens", "taxa_entrega", "cupom_restaurante", "comissao", "taxa_pagamento"]
    is_order = out["tipo_linha"] == "pedido"
    no_comp = out[comp_cols].isna().all(axis=1)
    out["layout"] = "detalhado"
    out.loc[is_order & no_comp, "layout"] = "legado"
    legacy_reps = set(out.loc[out["layout"] == "legado", "repasse_id"])
    out.loc[out["repasse_id"].isin(legacy_reps), "layout"] = "legado"
    log.add(f, "linhas de pedido sem componentes (layout legado)", int((is_order & no_comp).sum()),
            "marcadas como layout legado; só o líquido é comparável",
            "restaurantes do sistema antigo recebem só o valor líquido e uma descrição", resultado="aviso")
    dup = out["linha_id"].duplicated()
    log.add(f, "linha_id único", int(dup.sum()), "nenhuma", resultado="erro" if dup.any() else "ok")
    bad_type = ~out["tipo_linha"].isin(["pedido", "estorno", "ajuste"])
    log.add(f, "tipo_linha fora do domínio", int(bad_type.sum()), "nenhuma", resultado="erro" if bad_type.any() else "ok")
    detailed = is_order & ~no_comp
    calc = (out["valor_itens"] + out["taxa_entrega"] - out["cupom_restaurante"] - out["comissao"]
            - out["taxa_pagamento"])
    incoherent = detailed & (calc != out["valor_liquido"])
    log.add(f, "líquido = soma dos componentes (layout detalhado)", int(incoherent.sum()), "nenhuma",
            resultado="aviso" if incoherent.any() else "ok")
    no_pid = out["tipo_linha"].isin(["pedido", "estorno"]) & out["pedido_id"].isna()
    log.add(f, "linha de pedido ou estorno sem pedido_id", int(no_pid.sum()), "nenhuma",
            resultado="aviso" if no_pid.any() else "ok")
    adj_no_ticket = (out["tipo_linha"] == "ajuste") & (out["referencia"].isna() | (out["descricao"] == ""))
    log.add(f, "ajuste manual sem chamado ou justificativa", int(adj_no_ticket.sum()), "nenhuma",
            resultado="aviso" if adj_no_ticket.any() else "ok")
    return out


def load_repasses(path: Path, statement: pd.DataFrame, log: QualityLog) -> pd.DataFrame:
    f = path.name
    raw = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    out = pd.DataFrame({
        "repasse_id": raw["repasse_id"].str.strip(),
        "restaurante_id": raw["restaurante_id"].str.strip().str.upper(),
        "semana": raw["semana"].str.strip(),
        "periodo_inicio": pd.to_datetime(raw["periodo_inicio"], format="%d/%m/%Y").dt.date,
        "periodo_fim": pd.to_datetime(raw["periodo_fim"], format="%d/%m/%Y").dt.date,
        "data_pagamento_prevista": pd.to_datetime(raw["data_pagamento_prevista"], format="%d/%m/%Y").dt.date,
        "qtd_linhas": raw["qtd_linhas"].astype(int),
        "valor_total": raw["valor_total"].map(parse_brl).astype("int64"),
    })
    dup = out["repasse_id"].duplicated()
    log.add(f, "repasse_id único", int(dup.sum()), "nenhuma", resultado="erro" if dup.any() else "ok")
    sums = statement.groupby("repasse_id")["valor_liquido"].sum()
    counts = statement.groupby("repasse_id")["linha_id"].count()
    mism = out["valor_total"] != out["repasse_id"].map(sums).fillna(0).astype("int64")
    log.add(f, "total do repasse = soma das linhas do extrato", int(mism.sum()), "nenhuma",
            resultado="erro" if mism.any() else "ok")
    cmism = out["qtd_linhas"] != out["repasse_id"].map(counts).fillna(0).astype(int)
    log.add(f, "quantidade de linhas confere com o extrato", int(cmism.sum()), "nenhuma",
            resultado="aviso" if cmism.any() else "ok")
    return out


def set_calendar_from(repasses: pd.DataFrame, log: QualityLog) -> None:
    """The payout weeks come from the payout file itself, so other periods work too."""
    cal = repasses[["semana", "periodo_inicio", "periodo_fim", "data_pagamento_prevista"]].drop_duplicates()
    bad = cal[[(e - s).days != 6 or s.weekday() != 0 for s, e in zip(cal["periodo_inicio"], cal["periodo_fim"])]]
    dup = cal["semana"].duplicated().sum()
    log.add("repasses.csv", "semanas de segunda a domingo, uma linha por semana", int(len(bad) + dup), "nenhuma",
            "o calendário do repasse vem do próprio arquivo", resultado="erro" if len(bad) or dup else "ok")
    config.set_calendar([tuple(r) for r in cal.itertuples(index=False)])


# --------------------------------------------------------------------------- bank statement

_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def load_bank(path: Path, log: QualityLog) -> pd.DataFrame:
    f = path.name
    text = path.read_bytes().decode("latin-1")
    lines = text.splitlines()
    header_idx = next(i for i, ln in enumerate(lines) if ln.lower().startswith("data;lan"))
    log.add(f, "cabeçalho do banco antes da tabela", header_idx, "linhas de identificação ignoradas",
            "o arquivo traz nome do banco, cliente e período antes das colunas", resultado="corrigido")
    rows, skipped, opening = [], 0, None
    for ln in lines[header_idx + 1:]:
        parts = ln.split(";")
        if len(parts) < 5 or not _DATE_RE.match(parts[0].strip()):
            skipped += 1
            continue
        if parts[1].strip().upper() == "SALDO ANTERIOR":
            opening = parse_brl(parts[4])
            continue
        rows.append({"data": pd.to_datetime(parts[0].strip(), format="%d/%m/%Y").date(),
                     "historico": " ".join(parts[1].split()), "documento": parts[2].strip() or None,
                     "valor": parse_brl(parts[3]), "saldo": parse_brl(parts[4])})
    log.add(f, "rodapé e linhas sem data", skipped, "ignoradas", "saldo final e avisos do banco não são lançamentos",
            resultado="corrigido" if skipped else "ok")
    out = pd.DataFrame(rows)
    out.insert(0, "banco_linha_id", [f"B{i + 1:05d}" for i in range(len(out))])
    running = (opening or 0) + out["valor"].cumsum()
    breaks = running != out["saldo"]
    log.add(f, "saldo corrente bate lançamento a lançamento", int(breaks.sum()), "nenhuma",
            "confirma que nenhuma linha se perdeu na leitura", resultado="erro" if breaks.any() else "ok")
    log.add(f, "codificação latin-1 e valores no formato 1.234,56", 0,
            f"{len(out)} lançamentos lidos", resultado="ok")
    return out


# --------------------------------------------------------------------------- contracts

def load_contracts(path: Path, log: QualityLog) -> dict[str, pd.DataFrame]:
    f = path.name
    wb = load_workbook(path, data_only=True, read_only=True)

    def sheet_df(name):
        ws = wb[name]
        it = ws.iter_rows(values_only=True)
        header = [str(h).strip() for h in next(it)]
        return pd.DataFrame([r for r in it if any(v is not None for v in r)], columns=header)

    plans = sheet_df("planos")
    name_spaces = plans["nome"] != plans["nome"].str.strip()
    plans["nome"] = plans["nome"].str.strip()
    log.add(f, "nome de plano com espaços sobrando", int(name_spaces.sum()), "espaços removidos")
    plans["plano_id"] = plans["plano_id"].str.strip().str.upper()
    for col in ["comissao", "taxa_pix", "taxa_debito", "taxa_credito", "taxa_vale_refeicao"]:
        plans[col + "_bps"] = plans[col].map(rate_from_fraction)
    log.add(f, "taxas do Excel convertidas para pontos-base inteiros", 0,
            "arredondamento para o ponto-base mais próximo, recusando sobra maior que 0,0001",
            "células de porcentagem são números binários (0,0319 vira 0,031899...)", resultado="ok")
    plans["vigencia_inicio"] = pd.to_datetime(plans["vigencia_inicio"]).dt.date
    plans["vigencia_fim"] = pd.to_datetime(plans["vigencia_fim"]).dt.date
    plans = plans.drop(columns=["comissao", "taxa_pix", "taxa_debito", "taxa_credito", "taxa_vale_refeicao"])

    overlaps = 0
    for pid, g in plans.sort_values("vigencia_inicio").groupby("plano_id"):
        ends = g["vigencia_fim"].tolist()
        starts = g["vigencia_inicio"].tolist()
        overlaps += sum(1 for a, b in zip(ends[:-1], starts[1:]) if a is None or pd.isna(a) or a >= b)
    log.add(f, "versões de plano sem sobreposição de vigência", overlaps, "nenhuma",
            resultado="erro" if overlaps else "ok")

    rp = sheet_df("restaurante_plano")
    lower = rp["plano_id"] != rp["plano_id"].str.strip().str.upper()
    rp["plano_id"] = rp["plano_id"].str.strip().str.upper()
    log.add(f, "plano_id em minúsculas na aba restaurante_plano", int(lower.sum()), "convertido para maiúsculas")
    rp["restaurante_id"] = rp["restaurante_id"].str.strip().str.upper()
    rp["vigencia_inicio"] = pd.to_datetime(rp["vigencia_inicio"]).dt.date
    rp["vigencia_fim"] = pd.to_datetime(rp["vigencia_fim"]).dt.date
    unknown_plan = ~rp["plano_id"].isin(plans["plano_id"])
    log.add(f, "restaurante com plano inexistente", int(unknown_plan.sum()), "nenhuma",
            resultado="erro" if unknown_plan.any() else "ok")
    bad_periods = 0
    for _, g in rp.sort_values(["restaurante_id", "vigencia_inicio"]).groupby("restaurante_id"):
        rows = g.to_dict("records")
        for a, b in zip(rows[:-1], rows[1:]):
            end = a["vigencia_fim"]
            if end is None or pd.isna(end) or end >= b["vigencia_inicio"] or \
                    (pd.Timestamp(end) + pd.Timedelta(days=1)).date() < b["vigencia_inicio"]:
                bad_periods += 1
    log.add(f, "vigências de plano por restaurante sem sobreposição nem buraco", bad_periods, "nenhuma",
            "cada pedido precisa de exatamente um contrato", resultado="erro" if bad_periods else "ok")
    changes = rp.groupby("restaurante_id").size()
    log.add(f, "restaurantes com troca de plano no período", int((changes > 1).sum()),
            "contrato aplicado pela data de criação do pedido", resultado="ok")

    cad = sheet_df("cadastro")
    cad["restaurante_id"] = cad["restaurante_id"].str.strip().str.upper()
    dup = cad["restaurante_id"].duplicated()
    log.add(f, "restaurante_id único no cadastro", int(dup.sum()), "nenhuma", resultado="erro" if dup.any() else "ok")
    no_plan = ~cad["restaurante_id"].isin(rp["restaurante_id"])
    log.add(f, "restaurante sem contrato", int(no_plan.sum()), "nenhuma", resultado="erro" if no_plan.any() else "ok")
    similar = cad["nome_fantasia"].str.replace(r"\s+(II|Express|Centro|Unidade 2)$", "", regex=True).duplicated(keep=False)
    log.add(f, "nomes fantasia quase iguais (segunda unidade)", int(similar.sum()),
            "mantidos; o casamento bancário compara também CNPJ, agência e conta",
            "segunda unidade com o mesmo nome é comum", resultado="aviso" if similar.any() else "ok")
    cad["nome_banco_fantasia"] = cad["nome_fantasia"].map(bank_style)
    cad["nome_banco_razao"] = cad["razao_social"].map(bank_style)
    cad["cnpj_raiz"] = cad["cnpj"].str.replace(r"\D", "", regex=True).str[:8]
    cad["conta_digitos"] = cad["conta"].astype(str).str.replace(r"\D", "", regex=True)
    cad["agencia"] = cad["agencia"].astype(str).str.zfill(4)
    log.add(f, "nomes do cadastro no padrão do banco", 0,
            "maiúsculas, sem acento e com as abreviações usadas pelo banco",
            "permite comparar o histórico do extrato com o nome fantasia e a razão social", resultado="ok")
    return {"planos": plans, "restaurante_plano": rp, "cadastro": cad}


# --------------------------------------------------------------------------- orchestration

RAW_FILES = {
    "pedidos": "pedidos.csv", "estornos": "estornos.csv", "extrato": "repasse_extrato.csv",
    "repasses": "repasses.csv", "banco": "extrato_bancario.csv", "contratos": "contratos.xlsx",
}


def ingest(raw_dir: Path = config.RAW_DIR, interim_dir: Path = config.INTERIM_DIR,
           files: dict[str, Path] | None = None) -> tuple[dict[str, pd.DataFrame], QualityLog]:
    files = files or {k: raw_dir / v for k, v in RAW_FILES.items()}
    log = QualityLog()
    orders = load_orders(files["pedidos"], log)
    refunds = load_refunds(files["estornos"], orders, log)
    statement = load_statement(files["extrato"], log)
    repasses = load_repasses(files["repasses"], statement, log)
    set_calendar_from(repasses, log)
    bank = load_bank(files["banco"], log)
    contracts = load_contracts(files["contratos"], log)
    unknown_rest = ~orders["restaurante_id"].isin(contracts["cadastro"]["restaurante_id"])
    log.add("pedidos.csv", "pedido de restaurante fora do cadastro", int(unknown_rest.sum()), "nenhuma",
            resultado="erro" if unknown_rest.any() else "ok")
    tables = {"orders": orders, "refunds": refunds, "statement": statement, "repasses": repasses,
              "bank": bank, "plans": contracts["planos"], "restaurant_plans": contracts["restaurante_plano"],
              "restaurants": contracts["cadastro"]}
    if log.errors():
        raise IngestionError("; ".join(f"{e.arquivo}: {e.verificacao}" for e in log.errors()))
    interim_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(interim_dir / f"{name}.parquet", index=False)
    (interim_dir / "quality_log.json").write_text(json.dumps(log.to_records(), ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    return tables, log
