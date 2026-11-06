"""Generates project_docs/quality_log.md and project_docs/evaluation.md from the
run results, so the numbers in the documentation always match the data."""
from __future__ import annotations

from .. import config
from ..money import format_brl
from ..reconciliation.classify import TIPO_LABELS

TRAP_LABELS = {
    "cancelado_antes_do_preparo": "Cancelado antes do preparo, sem cobrança",
    "pedido_virada_de_semana": "Pedido de domingo à noite concluído depois da meia-noite",
    "estorno_da_plataforma": "Estorno assumido pela plataforma",
    "pedido_fora_do_periodo": "Pedido concluído depois do fechamento do período",
    "arredondamento_centavos": "Diferença de centavos dentro da tolerância",
    "ajuste_manual_legitimo": "Ajuste manual com chamado e justificativa",
    "estorno_complementar": "Segundo estorno legítimo do mesmo pedido",
    "pix_devolvido_reenviado": "Pix devolvido e reenviado",
}
FAMILY_LABELS = {
    "estorno_ausente_dono_indefinido": "Estorno sem responsável (só a nota do atendimento)",
    "linha_pedido": "Linha do extrato legado com mais de uma causa possível",
}


def n_br(x, d=0) -> str:
    s = f"{float(x):,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x) -> str:
    if x is None:
        return "não se aplica"
    return f"{x * 100:.1f}%".replace(".", ",")


def write_quality_md(qlog) -> None:
    lines = ["# Log de qualidade dos dados", "",
             "Saída de `python run_all.py`. Cada linha é uma verificação feita na ingestão, com a decisão "
             "tomada e o motivo.", "",
             "| Arquivo | Verificação | Resultado | Quantidade | Decisão | Justificativa |",
             "|---|---|---|---|---|---|"]
    for e in qlog.entries:
        lines.append(f"| {e.arquivo} | {e.verificacao} | {e.resultado} | {e.quantidade} | {e.decisao} | "
                     f"{e.justificativa} |")
    (config.PROJECT_DOCS_DIR / "quality_log.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _who(m: dict, who: str) -> dict:
    return m["ambiguos"].get(who, {}) if m and m.get("ambiguos") else {}


def write_evaluation_md(facts: dict, m_rules: dict, m_ai: dict | None, llm: dict, amb: list) -> None:
    final = m_ai or m_rules
    L = ["# Avaliação", "",
         "Saída de `python run_all.py`, medida contra o gabarito em `data/answer_key/`. Os números do site e dos "
         "READMEs saem do mesmo cálculo (`docs/data/facts.json`).", "",
         "## Definições", "",
         "* **Detectado:** existe uma divergência sinalizada (confirmada ou na fila de revisão) com a mesma chave "
         "do erro plantado (pedido, estorno, repasse ou restaurante e semana).",
         "* **Achado automático:** a divergência foi confirmada sem revisão humana e com o tipo certo.",
         "* **Precisão automática:** entre as divergências confirmadas, quantas correspondem a um erro plantado "
         "do mesmo tipo.",
         "* **Falso positivo:** uma armadilha (algo que parece erro, mas está certo) que virou divergência "
         "confirmada. Armadilhas que caem na fila de revisão custam tempo de analista, mas não geram carta errada.",
         "", "## Resultado geral", "",
         "| Métrica | Só regras | Regras e IA |", "|---|---|---|"]

    def row(label, a, b):
        L.append(f"| {label} | {a} | {b} |")

    ai = m_ai or {}
    row("Erros plantados", m_rules["erros_plantados"], final["erros_plantados"])
    row("Detectados (revocação da detecção)", pct(m_rules["deteccao"]["revocacao"]),
        pct(ai.get("deteccao", {}).get("revocacao")) if m_ai else "não rodou")
    row("Achados automáticos com o tipo certo", f"{m_rules['automatico']['acertos']} "
        f"({pct(m_rules['automatico']['revocacao'])})",
        f"{ai['automatico']['acertos']} ({pct(ai['automatico']['revocacao'])})" if m_ai else "não rodou")
    row("Precisão automática", pct(m_rules["automatico"]["precisao"]),
        pct(ai["automatico"]["precisao"]) if m_ai else "não rodou")
    row("Falsos positivos nas armadilhas", f"{m_rules['armadilhas']['falso_positivo']} de "
        f"{n_br(m_rules['armadilhas']['casos'])}",
        f"{ai['armadilhas']['falso_positivo']} de {n_br(ai['armadilhas']['casos'])}" if m_ai else "não rodou")
    row("Casos na fila de revisão", m_rules["em_revisao"], ai["em_revisao"] if m_ai else "não rodou")
    L += ["", "## Por tipo de erro", "",
          "| Tipo | Casos | Achados com o tipo certo | Precisão | Revocação | Plantado: restaurante recebeu a mais | Plantado: restaurante recebeu a menos |",
          "|---|---|---|---|---|---|---|"]
    for t, v in final["por_tipo"].items():
        L.append(f"| {TIPO_LABELS[t]} | {v['casos']} | {v['confirmados_certos']} | {pct(v['precisao'])} | "
                 f"{pct(v['revocacao'])} | {format_brl(v.get('valor_a_mais_centavos', 0))} | "
                 f"{format_brl(v.get('valor_a_menos_centavos', 0))} |")
    L += ["", "## Armadilhas", "", "| Armadilha | Casos | Falso positivo | Na fila de revisão |", "|---|---|---|---|"]
    for t, v in sorted(final["armadilhas"]["por_tipo"].items(), key=lambda kv: -kv[1]["casos"]):
        L.append(f"| {TRAP_LABELS.get(t, t)} | {n_br(v['casos'])} | {v['falso_positivo']} | {v['em_revisao']} |")

    L += ["", "## Casos ambíguos: o que a IA acrescenta", "",
          "Casos ambíguos são os que a regra não fecha sozinha. Três políticas, medidas nos mesmos casos:", "",
          "* **Regra:** palavras-chave na nota do atendimento (estornos) ou a primeira hipótese que confere, por "
          "prioridade fixa (linhas do extrato legado).",
          "* **IA sozinha:** o modelo local decide; confiança abaixo do limite vai para revisão. Já inclui as "
          "guardas do código (tipo dentro das opções, hipótese que confere, trecho que existe na nota) e uma nova "
          "tentativa quando a resposta é reprovada.",
          "* **Juntas (política final):** a IA decide e precisa citar o trecho que decide; se a regra tem resposta e "
          "discorda, o caso vai para revisão.", "",
          "Cada célula mostra certos, errados e enviados para revisão.", "",
          "| Grupo | Casos | Regra | IA sozinha | Juntas |", "|---|---|---|---|---|"]
    src = m_ai or m_rules
    fmt3 = lambda x: f"{x['acertos']}, {x['erros']}, {x['revisao']}" if x else "não rodou"
    for fam, v in (src["ambiguos"].get("por_familia") or {}).items():
        L.append(f"| {FAMILY_LABELS.get(fam, fam)} | {v['casos']} | {fmt3(v['regra_base'])} | "
                 f"{fmt3(v['ia_sozinha']) if m_ai else 'não rodou'} | {fmt3(v['ia']) if m_ai else 'não rodou'} |")
    rb, ias, ia = _who(src, "regra_base"), _who(src, "ia_sozinha"), _who(src, "ia")
    if rb:
        L.append(f"| **Total** | {src['ambiguos']['casos']} | {fmt3(rb)} | {fmt3(ias) if m_ai else 'não rodou'} | "
                 f"{fmt3(ia) if m_ai else 'não rodou'} |")
    L += ["", "Leitura honesta: nas linhas do extrato legado a regra acertou todos os casos e a IA errou a maioria, "
          "então ali a regra decide e a IA roda só em modo sombra, para esta medição (`LINES_AI=1` devolve a decisão "
          "a ela). O ganho está nos estornos sem responsável, em que a única evidência é texto livre.", ""]

    c = llm.get("cartas", {})
    rv = facts.get("revisao_cartas_ia")
    if rv:
        L += ["## Revisão humana das cartas escritas pela IA", "",
              f"Lemos uma amostra fixa de {rv['amostra']} cartas escritas pelo modelo local, cada uma contra os fatos "
              f"que ele recebeu. Resultado: {rv['corretas']} corretas, {rv['confusas']} confusas e {rv['erradas']} com "
              "fato errado ou inventado (por exemplo, prometer que o valor já foi ajustado, inverter quem recebeu a "
              "mais ou contar pedidos a mais). As checagens automáticas de número e de estilo aprovavam essas cartas, "
              "porque o erro é de sentido e não de número.", "",
              "Decisão: as cartas publicadas usam o texto montado pelo código, que é exato. A escrita pela IA continua "
              "no código e pode ser ligada com `LETTERS_AI=1` para testar um modelo maior. Cada carta avaliada está em "
              "`project_docs/revisao_cartas_ia.csv`.", ""]
    L += ["## Cartas e resumos", "",
          f"* Cartas geradas: {c.get('total', 0)}, com texto do código. Cartas com texto da IA nesta execução: "
          f"{c.get('texto_da_ia', 0)}.",
          f"* Cartas finais com problema de estilo: {c.get('cartas_finais_com_problema_de_estilo', 0)}. Com número "
          f"fora dos dados: {c.get('cartas_finais_com_numero_fora_dos_dados', 0)}.",
          f"* Resumos semanais: {c.get('resumos', 0)}, com texto do código. A leitura da semana pela IA também foi "
          "testada e desligada: mesmo sem números, o modelo apontava como maior valor um tipo que não era.",
          "* A amostra de cartas finais para revisão humana está em `project_docs/cartas_amostra/`.", ""]
    if llm.get("ligada"):
        L += ["## Uso do modelo local", "",
              f"* Provedor: {llm.get('provedor')}. Modelo: {llm.get('modelo')}. Custo de API: zero.",
              f"* Chamadas: {llm.get('chamadas')} ({llm.get('respostas_do_cache')} respondidas pelo cache nesta "
              f"execução).",
              f"* Tokens de entrada: {n_br(llm.get('tokens_entrada', 0))}. Tokens de saída: "
              f"{n_br(llm.get('tokens_saida', 0))}.",
              f"* Tempo de máquina gasto quando as respostas foram geradas: {n_br(llm.get('segundos_de_maquina', 0), 1)} "
              f"segundos, em CPU sem placa de vídeo. Repetir pelo cache leva segundos.", ""]
    v = final["valor"]
    L += ["## Valor das divergências", "",
          f"* Restaurantes receberam a mais: {format_brl(v['a_mais_restaurante_real'])} plantados, "
          f"{format_brl(v['a_mais_restaurante_achado'])} achados automaticamente.",
          f"* Restaurantes receberam a menos: {format_brl(v['a_menos_restaurante_real'])} plantados, "
          f"{format_brl(v['a_menos_restaurante_achado'])} achados automaticamente.", "",
          "## Horas economizadas (estimativa)", "",
          "Estimativa, não medição. As premissas estão abaixo e podem ser editadas na calculadora do site.", "",
          "| Premissa | Valor |", "|---|---|"]
    for k, p in facts["horas"]["premissas"].items():
        L.append(f"| {p['rotulo']} | {p['valor']} |")
    h = facts["horas"]
    L += ["", f"Com essas premissas: {str(h['horas_manual']).replace('.', ',')} horas por semana na planilha contra "
          f"{str(h['horas_ferramenta']).replace('.', ',')} horas com a ferramenta.", ""]
    (config.PROJECT_DOCS_DIR / "evaluation.md").write_text("\n".join(L), encoding="utf-8")
