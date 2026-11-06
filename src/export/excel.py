"""Excel report for the finance team."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..reconciliation.classify import TIPO_LABELS
from ..reconciliation.explain import Context, describe, week_label

BRL = '"R$" #,##0.00;[Red]-"R$" #,##0.00'
HEAD = PatternFill("solid", fgColor="0E1116")
HEAD_FONT = Font(bold=True, color="FFFFFF")


def reais(cents) -> Decimal | None:
    if cents is None:
        return None
    return Decimal(int(cents)) / Decimal(100)


def _sheet(wb, title, header, rows, money_cols=(), widths=None, first=False):
    ws = wb.active if first else wb.create_sheet(title)
    ws.title = title
    ws.append(header)
    for c in ws[1]:
        c.fill, c.font = HEAD, HEAD_FONT
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for r in rows:
        ws.append(r)
    for i, name in enumerate(header, start=1):
        letter = get_column_letter(i)
        ws.column_dimensions[letter].width = (widths or {}).get(name, max(12, min(45, len(name) + 6)))
        if name in money_cols:
            for cell in ws[letter][1:]:
                cell.number_format = BRL
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def write_report(path: Path, result, metrics: dict | None, run_info: dict) -> Path:
    con, divs = result.con, result.divergences
    ctx = Context(con)
    wb = Workbook()

    weeks = con.sql("SELECT * FROM summary_by_week").df()
    rows = [[week_label(r["semana"]), int(r["repasses"]), reais(r["total_repassado"]), int(r["divergencias"]),
             int(r["restaurantes_afetados"]), reais(r["a_mais_restaurante"]), reais(r["a_menos_restaurante"]),
             int(r["em_revisao"])] for r in weeks.to_dict("records")]
    ws = _sheet(wb, "Resumo", ["Semana", "Repasses", "Total repassado", "Divergências confirmadas",
                               "Restaurantes afetados", "Restaurantes receberam a mais",
                               "Restaurantes receberam a menos", "Casos em revisão"], rows,
                money_cols={"Total repassado", "Restaurantes receberam a mais", "Restaurantes receberam a menos"},
                widths={"Semana": 34}, first=True)
    ws.append([])
    for k, v in run_info.items():
        ws.append([k, v])

    conf = [d for d in divs if d.status == "confirmada"]
    rows = []
    for d in sorted(conf, key=lambda x: (x.semana or "", x.restaurante_id or "")):
        rows.append([d.div_id, d.semana, d.restaurante_id, ctx.name(d.restaurante_id), d.repasse_id,
                     TIPO_LABELS.get(d.tipo, d.tipo), reais(d.valor_centavos),
                     "Restaurante recebeu a mais" if d.valor_centavos > 0 else "Restaurante recebeu a menos",
                     {"regra": "Regra", "ia": "IA", "regra_base": "Regra"}.get(d.classificado_por, d.classificado_por),
                     float(d.confianca) if d.confianca is not None else None,
                     ", ".join(d.pedidos[:10]) + (" ..." if len(d.pedidos) > 10 else ""),
                     d.explicacao or describe(d, ctx)])
    _sheet(wb, "Divergências", ["ID", "Semana", "Restaurante", "Nome", "Repasse", "Tipo", "Valor", "Direção",
                                "Classificado por", "Confiança", "Pedidos", "Explicação"], rows,
           money_cols={"Valor"}, widths={"Nome": 30, "Tipo": 38, "Explicação": 90, "Direção": 28, "Repasse": 24})

    by_type = con.sql("SELECT * FROM summary_by_type").df()
    rows = [[TIPO_LABELS.get(r["tipo"], r["tipo"]), int(r["casos"]), reais(r["a_mais_restaurante"] or 0),
             reais(r["a_menos_restaurante"] or 0), int(r["por_regra"]), int(r["por_ia"])]
            for r in by_type.fillna(0).to_dict("records")]
    _sheet(wb, "Por tipo", ["Tipo", "Casos", "Restaurante recebeu a mais", "Restaurante recebeu a menos",
                            "Classificados por regra", "Classificados pela IA"], rows,
           money_cols={"Restaurante recebeu a mais", "Restaurante recebeu a menos"}, widths={"Tipo": 40})

    by_rest = con.sql("SELECT * FROM summary_by_restaurant").df()
    rows = [[r["restaurante_id"], r["nome_fantasia"], r["cidade"], r["categoria"], int(r["divergencias"]),
             reais(r["saldo_centavos"]), reais(r["a_mais_restaurante"]), reais(r["a_menos_restaurante"]), r["semanas"]]
            for r in by_rest.to_dict("records")]
    _sheet(wb, "Por restaurante", ["Restaurante", "Nome", "Cidade", "Categoria", "Divergências", "Saldo",
                                   "Recebeu a mais", "Recebeu a menos", "Semanas"], rows,
           money_cols={"Saldo", "Recebeu a mais", "Recebeu a menos"}, widths={"Nome": 32, "Semanas": 40})

    review = [d for d in divs if d.status == "revisao"]
    rows = [[d.div_id, d.semana, d.restaurante_id, ctx.name(d.restaurante_id) if d.restaurante_id else "",
             d.repasse_id, TIPO_LABELS.get(d.tipo, d.tipo) if d.tipo else "Sem sugestão", reais(d.valor_centavos),
             float(d.confianca) if d.confianca is not None else None, d.motivo_revisao,
             d.explicacao or describe(d, ctx)] for d in review]
    _sheet(wb, "Fila de revisão", ["ID", "Semana", "Restaurante", "Nome", "Repasse", "Sugestão", "Valor",
                                   "Confiança da IA", "Por que está aqui", "Contexto"], rows,
           money_cols={"Valor"}, widths={"Nome": 30, "Sugestão": 36, "Por que está aqui": 50, "Contexto": 90})

    rows = [[e.arquivo, e.verificacao, e.resultado, e.quantidade, e.decisao, e.justificativa]
            for e in result.quality_log.entries]
    _sheet(wb, "Qualidade dos dados", ["Arquivo", "Verificação", "Resultado", "Quantidade", "Decisão",
                                       "Justificativa"], rows,
           widths={"Verificação": 55, "Decisão": 60, "Justificativa": 70})

    if metrics:
        rows = [[TIPO_LABELS.get(t, t), v["casos"], v["confirmados_certos"], v["precisao"], v["revocacao"]]
                for t, v in metrics["por_tipo"].items()]
        _sheet(wb, "Avaliação", ["Tipo de erro plantado", "Casos", "Achados com o tipo certo", "Precisão",
                                 "Revocação"], rows, widths={"Tipo de erro plantado": 42})
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
