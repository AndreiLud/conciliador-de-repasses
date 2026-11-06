"""One command runs everything: generate data, reconcile, evaluate, export.

    python run_all.py                 # full run, language model in cache_first mode
    python run_all.py --offline       # never calls a model server, replays llm_cache/
    python run_all.py --ai off        # rules only (baseline)
    python run_all.py --skip-generate # reuse data/raw

Model settings come from .env (see .env.example).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src import config  # noqa: E402
from src.evaluation.evaluate import ambiguous_rows, evaluate, load_answer_key  # noqa: E402
from src.evaluation.letters_check import check_letters  # noqa: E402
from src.evaluation.reports import write_evaluation_md, write_quality_md  # noqa: E402
from src.export.excel import write_report  # noqa: E402
from src.export.letters import build_letters, build_summaries  # noqa: E402
from src.export import site  # noqa: E402
from src.generator.generate import GeneratorConfig, generate  # noqa: E402
from src.generator.writers import write_world  # noqa: E402
from src.reconciliation import engine  # noqa: E402
from src.reconciliation.explain import Context  # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ai", choices=["on", "off"], default="on")
    ap.add_argument("--offline", action="store_true", help="use only llm_cache/, never call a model server")
    ap.add_argument("--skip-generate", action="store_true")
    ap.add_argument("--prune-cache", action="store_true", help="delete cached model answers not used by this run")
    ap.add_argument("--seed", type=int, default=GeneratorConfig.seed)
    args = ap.parse_args(argv)
    if args.offline:
        os.environ["LLM_MODE"] = "offline"
    t_start = time.perf_counter()

    if not args.skip_generate or not (config.RAW_DIR / "pedidos.csv").exists():
        log("generating synthetic data")
        world = generate(GeneratorConfig(seed=args.seed))
        write_world(world, config.RAW_DIR, config.ANSWER_KEY_DIR)
    gab, traps = load_answer_key()

    log("reconciling with rules only (baseline)")
    t0 = time.perf_counter()
    base = engine.run(ai_mode="off")
    base_seconds = round(time.perf_counter() - t0, 1)
    m_rules = evaluate(base.divergences, gab, traps, ambiguous_rows(base.before_aggregation, gab))
    log(f"rules only: {m_rules['automatico']['acertos']}/{m_rules['erros_plantados']} caught automatically, "
        f"{m_rules['armadilhas']['falso_positivo']} false positives, {m_rules['em_revisao']} in review")

    client, result, m_ai = None, base, None
    if args.ai == "on":
        from src.llm.client import LLMClient

        client = LLMClient()
        live = client.available()
        log(f"language model: provider={client.cfg.provider} model={client.cfg.model} mode={client.cfg.mode} "
            f"server={'up' if live else 'not reachable, cache only'}")

        def progress(i, n, d, res):
            if i % 10 == 0 or i == n:
                log(f"  classified {i}/{n}")

        t0 = time.perf_counter()
        result = engine.run(ai_mode="on", client=client, progress=progress)
        ai_seconds = round(time.perf_counter() - t0, 1)
        m_ai = evaluate(result.divergences, gab, traps, ambiguous_rows(result.before_aggregation, gab))
        log(f"with AI: {m_ai['automatico']['acertos']}/{m_ai['erros_plantados']} caught automatically, "
            f"{m_ai['armadilhas']['falso_positivo']} false positives, {m_ai['em_revisao']} in review")

    log("writing letters and weekly summaries")
    ctx = Context(result.con)
    t0 = time.perf_counter()
    letters = build_letters(result.divergences, ctx, client,
                            progress=(lambda i, n: log(f"  letter {i}/{n}") if i % 10 == 0 or i == n else None)
                            if client else None)
    summaries = build_summaries(result.con, result.divergences, client)
    letters_seconds = round(time.perf_counter() - t0, 1)
    letters_eval = check_letters(letters, summaries)

    out = config.PROCESSED_DIR
    for sub in ("cartas", "resumos"):
        shutil.rmtree(out / sub, ignore_errors=True)
    for l in letters:
        p = out / "cartas" / l["semana"] / f"{l['restaurante_id']}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(l["texto"], encoding="utf-8")
    for s in summaries:
        p = out / "resumos" / f"{s['semana']}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(s["texto"], encoding="utf-8")

    stats = client.stats if client else None
    llm_info = {"ligada": client is not None, "custo_api": 0}
    if client:
        tps = stats.tokens_out / stats.seconds if stats.seconds else None
        llm_info.update({
            "provedor": client.cfg.provider, "modelo": client.cfg.model, "modo": client.cfg.mode,
            "chamadas": stats.calls, "respostas_do_cache": stats.cache_hits, "chamadas_novas": stats.new_calls,
            "faltas_no_cache_offline": stats.cache_misses_offline,
            "tokens_entrada": stats.tokens_in, "tokens_saida": stats.tokens_out,
            "segundos_de_maquina": round(stats.seconds, 1), "segundos_nesta_execucao": round(stats.new_seconds, 1),
            "tokens_saida_por_segundo": round(tps, 2) if tps else None,
            "por_tarefa": {k: {kk: (round(vv, 1) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                           for k, v in stats.by_task.items()},
            "cartas": letters_eval,
        })
    else:
        llm_info["cartas"] = letters_eval

    run_info = {"segundos_total": round(time.perf_counter() - t_start, 1), "segundos_so_regras": base_seconds,
                "etapas": result.timings, "segundos_cartas_e_resumos": letters_seconds}
    log("exporting Excel, site data and documentation tables")
    write_report(out / "relatorio_conciliacao.xlsx", result, m_ai or m_rules,
                 {"Origem": "python run_all.py", "Modo da IA": args.ai if not args.offline else "offline",
                  "Modelo": llm_info.get("modelo", "nenhum")})
    amb = ambiguous_rows(result.before_aggregation, gab)
    notes = {d.div_id: next((e["dados"].get("nota_do_atendimento") for e in d.evidencias
                             if e["id"].startswith("estorno:")), None) for d in result.before_aggregation if d.opcoes}
    for r in amb:
        r["nota"] = notes.get(r["div_id"])
    facts = site.export(result, m_rules, m_ai, letters, summaries, llm_info, run_info, amb)
    (out / "metricas.json").write_text(json.dumps({"regras": m_rules, "ia": m_ai, "ia_uso": llm_info,
                                                   "execucao": run_info}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    from src.export import check_texts, readme_facts
    readme_facts.main()
    check_texts.render_static_facts(config.DOCS_DIR / "index.html", facts)
    write_quality_md(result.quality_log)
    write_evaluation_md(facts, m_rules, m_ai, llm_info, amb)
    sample_dir = config.PROJECT_DOCS_DIR / "cartas_amostra"
    shutil.rmtree(sample_dir, ignore_errors=True)
    sample_dir.mkdir(parents=True, exist_ok=True)
    for l in pick_sample(letters):
        (sample_dir / f"{l['semana']}_{l['restaurante_id']}.md").write_text(l["texto"], encoding="utf-8")
    if args.prune_cache and client is not None and not stats.cache_misses_offline:
        log(f"removed {client.prune_cache()} unused cached answers from llm_cache/")
    log(f"done in {time.perf_counter() - t_start:.1f}s")
    return 0


def pick_sample(letters: list, n: int = 10) -> list:
    """Ten letters covering as many divergence types as possible, fixed order."""
    chosen, seen = [], set()
    for l in sorted(letters, key=lambda x: (x["semana"], x["restaurante_id"])):
        types = {d["tipo"] for d in l["fatos"]["diferencas"]}
        if types - seen:
            chosen.append(l)
            seen |= types
        if len(chosen) >= n:
            break
    for l in letters:
        if len(chosen) >= n:
            break
        if l not in chosen and len(l["fatos"]["diferencas"]) > 1:
            chosen.append(l)
    return chosen[:n]


if __name__ == "__main__":
    raise SystemExit(main())
