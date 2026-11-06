"""Conciliador de repasses: local app.

Run:  streamlit run app/streamlit_app.py
Upload the six files (or use the sample data), reconcile, review and download
the Excel report and the letters. The language model runs locally (Ollama or
a llama.cpp server); nothing is sent outside the machine.
"""
from __future__ import annotations

import io
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src import config  # noqa: E402
from src.export.excel import write_report  # noqa: E402
from src.export.letters import build_letters, build_summaries  # noqa: E402
from src.ingestion.load import RAW_FILES, IngestionError  # noqa: E402
from src.llm.client import LLMClient, LLMConfig  # noqa: E402
from src.money import format_brl  # noqa: E402
from src.reconciliation import engine  # noqa: E402
from src.reconciliation.classify import TIPO_LABELS  # noqa: E402
from src.reconciliation.explain import Context, describe, week_label  # noqa: E402

COLS = {"div_id": "ID", "semana": "Semana", "restaurante_id": "Restaurante", "nome": "Nome", "tipo_label": "Tipo",
        "valor": "Valor", "classificado_por": "Classificado por", "confianca": "Confiança da IA",
        "descricao": "Descrição", "motivo_revisao": "Por que está na fila", "explicacao": "Explicação da IA"}

st.set_page_config(page_title="Conciliador de repasses", layout="wide")

FILE_HELP = {
    "pedidos": "Base de pedidos (CSV, ponto decimal)",
    "estornos": "Estornos (CSV)",
    "extrato": "Extrato de repasse linha a linha (CSV com ponto e vírgula)",
    "repasses": "Total de cada repasse (CSV com ponto e vírgula)",
    "banco": "Extrato bancário (CSV do banco, latin-1)",
    "contratos": "Contratos (Excel com abas planos, restaurante_plano e cadastro)",
}

st.title("Conciliador de repasses")
st.caption("Recalcula o repasse de cada restaurante, cruza com o extrato e o banco, explica cada divergência e "
           "escreve a carta. Todo cálculo de dinheiro é feito pelo código. A IA roda na sua máquina.")

with st.sidebar:
    st.header("IA local")
    defaults = LLMConfig.from_env()
    ai_mode = st.radio("Modo", ["Desligada (só regras)", "Cache e servidor local", "Só cache (offline)"], index=1)
    provider = st.selectbox("Provedor", ["llamacpp", "ollama"], index=0 if defaults.provider == "llamacpp" else 1)
    model = st.text_input("Modelo", defaults.model)
    base_url = st.text_input("Endereço do servidor", defaults.base_url if defaults.provider == provider
                             else ("http://127.0.0.1:11434" if provider == "ollama" else "http://127.0.0.1:8080"))
    if st.button("Testar conexão"):
        ok = LLMClient(LLMConfig(provider=provider, model=model, base_url=base_url)).available()
        st.success("Servidor respondeu.") if ok else st.warning("Servidor não respondeu. O cache ainda funciona.")
    st.caption("IA desligada: a regra de palavras-chave decide os estornos sem responsável e, quando não tem "
               "resposta, o caso vai para revisão. Sem servidor no modo com IA: o que não está no cache vai para "
               "revisão e as cartas usam o texto fixo.")

st.subheader("1. Arquivos")
use_sample = st.toggle("Usar os dados sintéticos de exemplo", value=True)
uploads = {}
if not use_sample:
    cols = st.columns(2)
    for i, (key, label) in enumerate(FILE_HELP.items()):
        uploads[key] = cols[i % 2].file_uploader(label, type=["csv", "xlsx"], key=key)


def materialize(tmp: Path) -> dict[str, Path] | None:
    if use_sample:
        if not (config.RAW_DIR / "pedidos.csv").exists():
            from src.generator.generate import generate
            from src.generator.writers import write_world
            write_world(generate(), config.RAW_DIR, config.ANSWER_KEY_DIR)
        return {k: config.RAW_DIR / v for k, v in RAW_FILES.items()}
    if any(f is None for f in uploads.values()):
        return None
    out = {}
    for key, f in uploads.items():
        p = tmp / RAW_FILES[key]
        p.write_bytes(f.getvalue())
        out[key] = p
    return out


st.subheader("2. Conciliar")
if st.button("Rodar a conciliação", type="primary"):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        files = materialize(tmp)
        if files is None:
            st.error("Envie os seis arquivos ou use os dados de exemplo.")
            st.stop()
        client = None
        if not ai_mode.startswith("Desligada"):
            mode = "offline" if ai_mode.startswith("Só cache") else "cache_first"
            client = LLMClient(LLMConfig(provider=provider, model=model, base_url=base_url, mode=mode))
        progress = st.progress(0.0, text="Lendo e validando os arquivos")

        def on_progress(i, n, d, res):
            progress.progress(min(0.9, 0.3 + 0.6 * i / max(n, 1)), text=f"IA local: caso ambíguo {i} de {n}")

        try:
            result = engine.run(files=files, ai_mode="on" if client else "off", client=client,
                                progress=on_progress, interim_dir=tmp / "interim")
        except IngestionError as exc:
            st.error(f"Os arquivos não passaram na validação: {exc}")
            st.stop()
        progress.progress(0.92, text="Escrevendo cartas e resumos")
        ctx = Context(result.con)
        letters = build_letters(result.divergences, ctx, client)
        summaries = build_summaries(result.con, result.divergences, client)
        xlsx = tmp / "relatorio_conciliacao.xlsx"
        write_report(xlsx, result, None, {"Origem": "app Streamlit", "IA": ai_mode, "Modelo": model if client else "nenhum"})
        progress.progress(1.0, text="Pronto")
        st.session_state["out"] = {
            "divs": [d.to_dict() | {"descricao": describe(d, ctx), "nome": ctx.name(d.restaurante_id)
                                    if d.restaurante_id else ""} for d in result.divergences],
            "quality": result.quality_log.to_records(), "letters": letters, "summaries": summaries,
            "xlsx": xlsx.read_bytes(), "timings": result.timings,
            "llm": client.stats.__dict__ if client else None,
            "repasses": int(result.tables["repasses"].shape[0]),
        }

out = st.session_state.get("out")
if out:
    divs = pd.DataFrame(out["divs"])
    conf = divs[divs["status"] == "confirmada"] if len(divs) else divs
    rev = divs[divs["status"] == "revisao"] if len(divs) else divs
    st.subheader("3. Resultado")
    c = st.columns(5)
    c[0].metric("Repasses conferidos", out["repasses"])
    c[1].metric("Divergências confirmadas", len(conf))
    c[2].metric("Na fila de revisão", len(rev))
    c[3].metric("Restaurante recebeu a mais", format_brl(int(conf.loc[conf.valor_centavos > 0, "valor_centavos"].sum()) if len(conf) else 0))
    c[4].metric("Restaurante recebeu a menos", format_brl(int(-conf.loc[conf.valor_centavos < 0, "valor_centavos"].sum()) if len(conf) else 0))
    if out["llm"]:
        s = out["llm"]
        st.caption(f"IA local: {s['calls']} chamadas, {s['cache_hits']} respondidas pelo cache, "
                   f"{s['tokens_in']} tokens de entrada e {s['tokens_out']} de saída. Custo de API: zero.")

    tab1, tab2, tab3, tab4 = st.tabs(["Divergências", "Fila de revisão", "Cartas", "Qualidade dos dados"])
    with tab1:
        if len(conf):
            types = sorted(conf["tipo_label"].dropna().unique())
            pick = st.multiselect("Filtrar por tipo", types, default=types)
            view = conf[conf["tipo_label"].isin(pick)].copy()
            view["valor"] = view["valor_centavos"].map(lambda v: format_brl(v, signed=True))
            view["semana"] = view["semana"].map(week_label)
            st.dataframe(view[["div_id", "semana", "restaurante_id", "nome", "tipo_label", "valor", "classificado_por",
                               "confianca", "descricao"]].rename(columns=COLS), hide_index=True, width="stretch")
        else:
            st.info("Nenhuma divergência confirmada.")
    with tab2:
        if len(rev):
            view = rev.copy()
            view["valor"] = view["valor_centavos"].map(lambda v: format_brl(v, signed=True))
            view["semana"] = view["semana"].map(lambda w: week_label(w) if isinstance(w, str) else "")
            st.dataframe(view[["div_id", "semana", "restaurante_id", "nome", "tipo_label", "valor", "motivo_revisao",
                               "explicacao", "descricao"]].rename(columns=COLS), hide_index=True, width="stretch")
        else:
            st.info("Fila vazia.")
    with tab3:
        if out["letters"]:
            labels = [f"{week_label(l['semana'])} · {l['restaurante']}" for l in out["letters"]]
            i = st.selectbox("Carta", range(len(labels)), format_func=lambda k: labels[k])
            l = out["letters"][i]
            st.caption("Texto da IA local, aprovado nas checagens." if l["fonte_texto"] == "ia" else "Texto fixo montado pelo código.")
            st.markdown(l["texto"])
        for s in out["summaries"]:
            with st.expander(f"Resumo da semana {week_label(s['semana'])}"):
                st.markdown(s["texto"])
    with tab4:
        st.dataframe(pd.DataFrame(out["quality"]).rename(columns={
            "arquivo": "Arquivo", "verificacao": "Verificação", "resultado": "Resultado", "quantidade": "Quantidade",
            "decisao": "Decisão", "justificativa": "Justificativa"}), hide_index=True, width="stretch")

    st.subheader("4. Baixar")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for l in out["letters"]:
            z.writestr(f"cartas/{l['semana']}/{l['restaurante_id']}.md", l["texto"])
        for s in out["summaries"]:
            z.writestr(f"resumos/{s['semana']}.md", s["texto"])
    d1, d2 = st.columns(2)
    d1.download_button("Relatório em Excel", out["xlsx"], "relatorio_conciliacao.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    d2.download_button("Cartas e resumos (zip)", buf.getvalue(), "cartas_e_resumos.zip", "application/zip")
