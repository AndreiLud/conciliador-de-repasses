// Conciliador de repasses: static site logic. No framework, no external calls.
import { brl, pct, int, dec, esc, get, mdLite } from "./format.js";
import { setupCalculator } from "./calculator.js";

const state = { facts: null, metrics: null, weeks: [], weekCache: new Map(), week: null, rest: null,
                scope: "restaurante", typeFilter: "todos", tab: "divergencias" };

const ICON = { ok: "i-ok", more: "i-more", less: "i-less", review: "i-review", err: "i-x" };
const EV_LABELS = { pedido_id: "Pedido", criado_em: "Criado em", concluido_em: "Concluído em", forma_pagamento: "Forma de pagamento",
  valor_itens: "Valor dos itens", taxa_entrega: "Taxa de entrega", cupom: "Cupom", total_pago_cliente: "Total pago pelo cliente",
  plano: "Plano", versao: "Versão", comissao: "Comissão", taxa_da_forma_de_pagamento: "Taxa da forma de pagamento",
  entrega: "Entrega", plano_anterior: "Plano anterior", troca_em: "Troca em", comissao_anterior: "Comissão anterior",
  taxa_anterior_da_forma: "Taxa anterior da forma", linha_id: "Linha", repasse_id: "Repasse", layout: "Layout",
  descricao: "Descrição", valor_liquido: "Valor líquido", taxa_pagamento: "Taxa de pagamento",
  cupom_descontado: "Cupom descontado", entrega_repassada: "Entrega repassada", liquido_esperado: "Líquido esperado",
  diferenca: "Diferença", estorno_id: "Estorno", valor: "Valor", processado_em: "Processado em",
  responsavel: "Responsável", nota_do_atendimento: "Nota do atendimento", observacao: "Observação",
  data: "Data", historico: "Histórico", valor_total: "Valor total", data_prevista: "Data prevista" };
const LABEL = { ok: "Certo", more: "Recebeu a mais", less: "Recebeu a menos", review: "Revisão humana" };
const WHO = { regra: "Regra", regra_base: "Regra", ia: "IA local", revisao: "Revisão humana" };

const badge = (kind, text) =>
  `<span class="badge ${kind}"><svg aria-hidden="true"><use href="#${ICON[kind]}"/></svg>${esc(text ?? LABEL[kind])}</span>`;

async function loadJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function fillFacts(facts) {
  document.querySelectorAll("[data-fact]").forEach((el) => {
    const v = get(facts, el.dataset.fact);
    if (v === undefined || v === null) return;
    const f = el.dataset.format;
    el.textContent = f === "pct0" ? pct(v, 0) : f === "pct" ? pct(v, 1) : f === "brl" ? brl(v)
      : f === "dec1" ? dec(v, 1) : f === "dec2" ? dec(v, 2) : f === "int" ? int(v) : String(v);
  });
}

// ------------------------------------------------------------------ demo
function kindOf(d) {
  if (d.status === "revisao") return "review";
  return d.valor_centavos > 0 ? "more" : "less";
}

async function loadWeek(wid) {
  if (!state.weekCache.has(wid)) state.weekCache.set(wid, await loadJSON(`data/semana_${wid}.json`));
  return state.weekCache.get(wid);
}

function fillRestaurants(week) {
  const sel = document.getElementById("sel-rest");
  const flagged = week.repasses.filter((r) => r.divergencias + r.em_revisao > 0);
  const clean = week.repasses.filter((r) => r.divergencias + r.em_revisao === 0)
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  const opt = (r) => `<option value="${esc(r.restaurante_id)}">${esc(r.nome)} (${esc(r.cidade)})${
    r.divergencias ? `, ${r.divergencias} divergência${r.divergencias > 1 ? "s" : ""}` : ""}${
    r.em_revisao ? `, ${r.em_revisao} em revisão` : ""}</option>`;
  sel.innerHTML = `<optgroup label="Com divergência ou em revisão (${flagged.length})">${flagged.map(opt).join("")}</optgroup>`
    + `<optgroup label="Sem divergência (${clean.length})">${clean.map(opt).join("")}</optgroup>`;
  if (!week.repasses.some((r) => r.restaurante_id === state.rest)) state.rest = flagged[0]?.restaurante_id ?? clean[0]?.restaurante_id;
  sel.value = state.rest;
}

function divCard(d, showRest) {
  const k = kindOf(d);
  const amount = `${d.valor_centavos > 0 ? "+" : "-"}${brl(Math.abs(d.valor_centavos))}`;
  const who = d.classificado_por === "ia"
    ? `<span class="who ai">IA local${d.confianca != null ? ` · confiança ${dec(d.confianca, 2)}` : ""}</span>`
    : `<span class="who">${esc(WHO[d.classificado_por] ?? d.classificado_por)}</span>`;
  const reason = d.status === "revisao" && d.motivo_revisao ? `<p><strong>Por que está na fila:</strong> ${esc(d.motivo_revisao)}.${
    d.sugestao ? ` Sugestão da IA: ${esc(d.sugestao.toLowerCase())}.` : ""}</p>` : "";
  const quote = d.explicacao_ia ? `<p><strong>IA local:</strong> ${esc(d.explicacao_ia)}</p>` : "";  // built by code
  return `<article class="dcard ${k}">
    <div class="dcard-top"><span class="dcard-title">${esc(d.tipo_label)}</span><span class="dcard-amount num">${amount}</span></div>
    <div>${badge(k)} ${showRest ? `<span class="meta" style="margin-left:6px;color:var(--muted);font-size:.86rem">${esc(d.nome)}</span>` : ""}</div>
    <p>${esc(d.descricao)}</p>${quote}${reason}
    <div class="dcard-foot"><span>Classificado por ${who}</span>
      <button class="link-btn" type="button" data-ev="${esc(d.id)}">Ver evidências</button></div>
  </article>`;
}

function renderDivergences(week, rep) {
  const all = week.divergencias;
  const pool = state.scope === "restaurante" ? all.filter((d) => d.restaurante_id === rep.restaurante_id) : all;
  const types = [...new Set(pool.map((d) => d.tipo_label))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  if (state.typeFilter !== "todos" && !types.includes(state.typeFilter)) state.typeFilter = "todos";
  const shown = state.typeFilter === "todos" ? pool : pool.filter((d) => d.tipo_label === state.typeFilter);
  const scope = `<div class="chips" role="group" aria-label="Escopo">
      <button class="chip" type="button" data-scope="restaurante" aria-pressed="${state.scope === "restaurante"}">Este restaurante</button>
      <button class="chip" type="button" data-scope="semana" aria-pressed="${state.scope === "semana"}">Toda a semana (${all.length})</button></div>`;
  const chips = types.length > 1 ? `<div class="chips" role="group" aria-label="Filtrar por tipo">
      <button class="chip" type="button" data-type="todos" aria-pressed="${state.typeFilter === "todos"}">Todos os tipos</button>
      ${types.map((t) => `<button class="chip" type="button" data-type="${esc(t)}" aria-pressed="${state.typeFilter === t}">${esc(t)}</button>`).join("")}</div>` : "";
  const list = shown.length
    ? `<div class="cards">${shown.map((d) => divCard(d, state.scope === "semana")).join("")}</div>`
    : `<div class="empty">${badge("ok")}<p style="margin:0">Nenhuma divergência neste repasse. O valor pago bate com o recalculado, linha a linha, e com o banco.</p></div>`;
  return scope + chips + list;
}

function renderLetter(week, rep) {
  const letter = week.cartas[rep.restaurante_id];
  if (!letter) return `<div class="empty">${badge("ok")}<p style="margin:0">Sem carta: não há diferença confirmada para explicar a este restaurante nesta semana.</p></div>`;
  const src = letter.fonte_texto === "ia"
    ? `<span class="who ai">Texto da IA local</span> aprovado nas checagens de números e estilo. Tabela e valores vêm do código.`
    : `<span class="who">Texto fixo</span> montado pelo código, sem IA.`;
  return `<p class="letter-source">${src}</p><div class="letter">${mdLite(letter.texto)}</div>`;
}

function renderReview(week) {
  const items = week.divergencias.filter((d) => d.status === "revisao");
  if (!items.length) return `<div class="empty">Nenhum caso esperando revisão nesta semana.</div>`;
  return `<p class="chart-note" style="margin-top:0">Casos que nem a regra nem a IA fecharam com segurança. Ninguém recebe carta sobre eles antes de uma pessoa decidir.</p>
    <div class="cards">${items.map((d) => divCard(d, true)).join("")}</div>`;
}

function renderSummary(week) {
  const s = week.resumo, f = s.fatos;
  const rows = f.tipos_que_mais_pesaram.map((t) => `<tr><td>${esc(t.tipo)}</td><td class="n">${int(t.casos)}</td><td class="n">${esc(t.valor)}</td></tr>`).join("");
  const reading = s.leitura ? `<div class="ai-box" style="margin:14px 0"><h4>Leitura da semana: ${esc(s.titulo_leitura)}</h4>${
    s.leitura.map((p) => `<p style="margin:0 0 6px">${esc(p)}</p>`).join("")}<p class="chart-note" style="margin:0">Texto da IA local, sem números, aprovado nas checagens.</p></div>` : "";
  return `<p class="letter-source"><span class="who">Texto fixo</span> texto e tabelas montados pelo código, sem IA.</p>
    <div class="letter"><h3 style="margin-bottom:12px">${esc(s.titulo)}</h3>${s.paragrafos.map((p) => `<p>${esc(p)}</p>`).join("")}${reading}
    <table><thead><tr><th>Tipo que mais pesou</th><th>Casos</th><th>Valor</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function statusOf(rep) {
  // What the restaurant actually got (bank, when there is a payment) against what it was owed.
  const got = rep.total_banco > 0 ? rep.total_banco : rep.total_extrato;
  const net = got - rep.total_devido;
  if (rep.em_revisao && !rep.divergencias) return badge("review", "Em revisão");
  if (net > 0) return badge("more", "A favor do restaurante");
  if (net < 0) return badge("less", "A favor da plataforma");
  return rep.divergencias ? badge("ok", "Diferenças se compensam") : badge("ok");
}

async function renderBoard() {
  const board = document.getElementById("board");
  const week = await loadWeek(state.week);
  const rep = week.repasses.find((r) => r.restaurante_id === state.rest) ?? week.repasses[0];
  const mine = week.divergencias.filter((d) => d.restaurante_id === rep.restaurante_id);
  const reviewN = week.divergencias.filter((d) => d.status === "revisao").length;
  const tabs = [["divergencias", "Divergências", mine.length], ["carta", "Carta ao restaurante", week.cartas[rep.restaurante_id] ? 1 : 0],
    ["revisao", "Fila de revisão da semana", reviewN], ["resumo", "Resumo da semana", null]];
  const panel = state.tab === "divergencias" ? renderDivergences(week, rep) : state.tab === "carta" ? renderLetter(week, rep)
    : state.tab === "revisao" ? renderReview(week) : renderSummary(week);
  board.innerHTML = `
    <div class="status-line"><div><h3>${esc(rep.nome)}</h3><div class="meta">${esc(rep.categoria)} em ${esc(rep.cidade)} · ${esc(rep.repasse_id)} · ${int(rep.pedidos)} pedidos · pago em ${esc(week.data_pagamento)}</div></div>${statusOf(rep)}</div>
    <div class="totals">
      <div class="total"><div class="t-label">Devido pelo contrato</div><div class="t-value num">${brl(rep.total_devido)}</div><div class="t-note">recalculado pedido a pedido</div></div>
      <div class="total"><div class="t-label">No extrato de repasse</div><div class="t-value num">${brl(rep.total_extrato)}</div><div class="t-note">${rep.total_extrato === rep.total_devido ? "igual ao devido" : `diferença de ${brl(Math.abs(rep.total_extrato - rep.total_devido))}`}</div></div>
      <div class="total"><div class="t-label">Pago no banco</div><div class="t-value num">${brl(rep.total_banco)}</div><div class="t-note">${rep.total_banco === rep.total_extrato ? "igual ao extrato" : `diferença de ${brl(Math.abs(rep.total_banco - rep.total_extrato))}`}</div></div>
    </div>
    <div class="tabs" role="tablist" aria-label="Detalhes do repasse">${tabs.map(([id, label, n]) =>
      `<button class="tab" role="tab" id="tab-${id}" aria-controls="tabpanel" aria-selected="${state.tab === id}" tabindex="${state.tab === id ? 0 : -1}" data-tab="${id}">${label}${n != null ? `<span class="count">${n}</span>` : ""}</button>`).join("")}</div>
    <div class="tabpanel" id="tabpanel" role="tabpanel" aria-labelledby="tab-${state.tab}">${panel}</div>`;
  const n = mine.length;
  document.getElementById("board-status").textContent =
    `${rep.nome}, semana ${week.rotulo}: ${n} divergência${n === 1 ? "" : "s"}${reviewN ? `, ${reviewN} na fila de revisão da semana` : ""}.`;
}

function evidenceHTML(d) {
  const blocks = (d.evidencias || []).map((e) => {
    const rows = Object.entries(e.dados || {}).map(([k, v]) => `<dt>${esc(EV_LABELS[k] ?? k.replaceAll("_", " "))}</dt><dd>${esc(String(v))}</dd>`).join("");
    return `<div class="ev"><div class="ev-head"><span class="mono">${esc(e.id)}</span><span>${esc(e.fonte)}</span></div>${rows ? `<dl>${rows}</dl>` : ""}</div>`;
  }).join("");
  const hyps = (d.hipoteses || []).filter((h) => h.descricao && h.liquido_hipotese_brl);
  const hypTable = hyps.length ? `<div><h4>Hipóteses calculadas pelo código</h4><div class="table-scroll"><table class="hyp"><thead><tr><th>Causa testada</th><th>Líquido se fosse isso</th><th>Confere com o extrato</th></tr></thead><tbody>${
    hyps.map((h) => `<tr><td>${esc(h.descricao)}</td><td class="num">${esc(h.liquido_hipotese_brl)}</td><td>${h.confere ? badge("ok", "Confere") : badge("err", "Não confere")}</td></tr>`).join("")}</tbody></table></div></div>` : "";
  const ai = d.explicacao_ia ? `<div class="ai-box"><h4>O que a IA local decidiu</h4><p style="margin:0 0 6px">${esc(d.explicacao_ia)}</p>
      <p class="chart-note" style="margin:0">Tipo: ${esc(d.tipo_label)}. Confiança: ${d.confianca != null ? dec(d.confianca, 2) : "não informada"}. ${d.familia === "linha_pedido" ? "A regra de prioridade" : "A regra de palavras-chave"} teria dito: ${esc(d.regra_base ? (state.metrics?.tipos?.[d.regra_base] ?? d.regra_base) : "sem resposta, revisão humana")}.</p></div>` : "";
  return `<p style="margin:0">${badge(kindOf(d))} <strong>${esc(d.tipo_label)}</strong>, ${brl(Math.abs(d.valor_centavos))}. ${esc(d.descricao)}</p>${ai}${hypTable}<div><h4>Evidências</h4><div style="display:grid;gap:10px">${blocks || "<p>Sem evidências adicionais.</p>"}</div></div>`;
}

function setupDemo() {
  const selWeek = document.getElementById("sel-week");
  selWeek.innerHTML = state.weeks.map((w) => `<option value="${w.semana}">${esc(w.rotulo)}</option>`).join("");
  state.week = state.weeks[1]?.semana ?? state.weeks[0].semana;
  selWeek.value = state.week;
  const refresh = async () => {
    const wanted = state.week;
    try {
      const week = await loadWeek(wanted);
      if (wanted !== state.week) return;
      fillRestaurants(week);
      await renderBoard();
    } catch (err) {
      document.getElementById("board").innerHTML = `<div class="empty">Não foi possível carregar a semana (${esc(err.message)}).</div>`;
    }
  };
  selWeek.addEventListener("change", async () => { state.week = selWeek.value; await refresh(); });
  document.getElementById("sel-rest").addEventListener("change", async (e) => {
    state.rest = e.target.value;
    try { await renderBoard(); } catch (err) { document.getElementById("board").innerHTML = `<div class="empty">Erro ao mostrar o restaurante (${esc(err.message)}).</div>`; }
  });
  const board = document.getElementById("board");
  board.addEventListener("click", async (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    if (t.dataset.tab) { state.tab = t.dataset.tab; await renderBoard(); const tb = document.getElementById(`tab-${state.tab}`); tb?.focus(); tb?.scrollIntoView({ block: "nearest", inline: "nearest" }); }
    else if (t.dataset.scope) { state.scope = t.dataset.scope; state.typeFilter = "todos"; await renderBoard();
      board.querySelector(`[data-scope="${state.scope}"]`)?.focus(); }
    else if (t.dataset.type) { state.typeFilter = t.dataset.type; await renderBoard();
      [...board.querySelectorAll("[data-type]")].find((b) => b.dataset.type === state.typeFilter)?.focus(); }
    else if (t.dataset.ev) {
      const week = await loadWeek(state.week);
      const d = week.divergencias.find((x) => x.id === t.dataset.ev);
      openEvidence(d, t);
    }
  });
  board.addEventListener("keydown", async (e) => {
    const t = e.target.closest('[role="tab"]');
    if (!t || !["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
    const tabs = [...board.querySelectorAll('[role="tab"]')];
    let i = tabs.indexOf(t);
    i = e.key === "ArrowRight" ? (i + 1) % tabs.length : e.key === "ArrowLeft" ? (i - 1 + tabs.length) % tabs.length : e.key === "Home" ? 0 : tabs.length - 1;
    e.preventDefault();
    state.tab = tabs[i].dataset.tab;
    await renderBoard();
    document.getElementById(`tab-${state.tab}`)?.focus();
  });
  refresh();
}

function openEvidence(d, opener) {
  const dlg = document.getElementById("ev-dialog");
  document.getElementById("ev-title").textContent = `Evidências do caso ${d.id}`;
  document.getElementById("ev-body").innerHTML = evidenceHTML(d);
  dlg.showModal();
  dlg.addEventListener("close", () => opener?.focus(), { once: true });
}

function setupDialog() {
  const dlg = document.getElementById("ev-dialog");
  dlg.querySelector("[data-close]").addEventListener("click", () => dlg.close());
  // Light dismiss for browsers without the closedby attribute.
  if (!("closedBy" in HTMLDialogElement.prototype)) {
    dlg.addEventListener("click", (event) => {
      if (event.target !== dlg) return;
      const r = dlg.getBoundingClientRect();
      const inside = r.top <= event.clientY && event.clientY <= r.top + r.height && r.left <= event.clientX && event.clientX <= r.left + r.width;
      if (!inside) dlg.close();
    });
  }
}

// ------------------------------------------------------------------ results
function renderResults() {
  const m = state.metrics, final = m.ia ?? m.regras, labels = m.tipos;
  const types = Object.entries(final.por_tipo).sort((a, b) => b[1].casos - a[1].casos);
  const bar = (v, cls) => v == null ? "" : `<div class="bar ${cls}" aria-hidden="true"><span style="width:${v * 100}%"></span></div>`;
  document.getElementById("tbl-types").insertAdjacentHTML("beforeend", `<thead><tr><th scope="col">Tipo</th><th scope="col">Casos</th><th scope="col">Revocação</th><th scope="col"><span class="visually-hidden">Barra de revocação</span></th><th scope="col">Precisão</th><th scope="col"><span class="visually-hidden">Barra de precisão</span></th></tr></thead><tbody>${
    types.map(([t, v]) => `<tr><th scope="row" style="font-weight:500;color:var(--text)">${esc(labels[t])}</th><td class="n">${int(v.casos)}</td><td class="n">${pct(v.revocacao, 0)}</td><td>${bar(v.revocacao, "recall")}</td><td class="n">${v.precisao == null ? "sem casos" : pct(v.precisao, 0)}</td><td>${bar(v.precisao, "")}</td></tr>`).join("")}</tbody>`);
  const trapLabels = { cancelado_antes_do_preparo: "Cancelado antes do preparo", pedido_virada_de_semana: "Pedido na virada da semana",
    estorno_da_plataforma: "Estorno assumido pela plataforma", pedido_fora_do_periodo: "Pedido concluído depois do fechamento",
    arredondamento_centavos: "Diferença de centavos", ajuste_manual_legitimo: "Ajuste manual com chamado",
    estorno_complementar: "Segundo estorno legítimo", pix_devolvido_reenviado: "Pix devolvido e reenviado" };
  const traps = Object.entries(final.armadilhas.por_tipo).sort((a, b) => b[1].casos - a[1].casos);
  document.getElementById("tbl-traps").insertAdjacentHTML("beforeend", `<thead><tr><th scope="col">Armadilha</th><th scope="col">Casos</th><th scope="col">Falso positivo</th><th scope="col">Em revisão</th></tr></thead><tbody>${
    traps.map(([t, v]) => `<tr><th scope="row" style="font-weight:500;color:var(--text)">${esc(trapLabels[t] ?? t)}</th><td class="n">${int(v.casos)}</td><td class="n">${v.falso_positivo ? badge("err", int(v.falso_positivo)) : badge("ok", "0")}</td><td class="n">${int(v.em_revisao)}</td></tr>`).join("")}</tbody>`);

  const amb = final.ambiguos;
  const base = amb.regra_base, iaAlone = m.ia ? amb.ia_sozinha : null, ia = m.ia ? amb.ia : null;
  const row = (label, x) => {
    const n = amb.casos, w = (k) => `${(x[k] / n) * 100}%`;
    return `<div class="stack-row"><div class="stack-label"><span>${label}</span><span class="num">${int(x.acertos)} certos, ${int(x.erros)} errados, ${int(x.revisao)} na revisão</span></div>
      <div class="stack-bar" role="img" aria-label="${label}: ${x.acertos} certos, ${x.erros} errados e ${x.revisao} na revisão, de ${n} casos">
      <span class="s-ok" style="width:${w("acertos")}">${x.acertos || ""}</span><span class="s-err" style="width:${w("erros")}">${x.erros || ""}</span><span class="s-rev" style="width:${w("revisao")}">${x.revisao || ""}</span></div></div>`;
  };
  document.getElementById("stack").innerHTML = row("Só regras", base)
    + (iaAlone ? row("Só a IA local", iaAlone) : "") + (ia ? row("Regra e IA juntas (política final)", ia) : "");
  document.getElementById("ai-compare-note").textContent = `${int(amb.casos)} casos em que a regra não fecha sozinha. A maioria são estornos sem responsável preenchido, em que a única pista é a nota escrita pelo atendimento. Nas linhas do extrato legado a regra foi melhor, então a política final usa a regra ali.`;
  if (m.ia) {
    const fam = m.ia.ambiguos.por_familia, names = { estorno_ausente_dono_indefinido: "Estornos sem responsável", linha_pedido: "Linhas do extrato legado" };
    const cell = (x) => `<td class="n">${x.acertos}, ${x.erros}, ${x.revisao}</td>`;
    document.getElementById("ai-families").innerHTML = `<p class="chart-note">Na política final, a IA precisa citar o trecho da nota que decide. Se a regra de palavras-chave tem resposta e discorda da IA, uma pessoa decide. Nas linhas do legado, quem decide é a regra.</p><details class="data"><summary>Ver por grupo de caso (certos, errados, revisão)</summary><div class="table-scroll"><table class="metric-table"><thead><tr><th>Grupo</th><th>Casos</th><th>Regra</th><th>IA</th><th>Juntas</th></tr></thead><tbody>${
      Object.entries(fam).map(([k, v]) => `<tr><td>${esc(names[k] ?? k)}</td><td class="n">${v.casos}</td>${cell(v.regra_base)}${cell(v.ia_sozinha)}${cell(v.ia)}</tr>`).join("")}</tbody></table></div></details>`;
  }

  const f = state.facts, ai = f.ia;
  const k = (v, l) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`;
  document.getElementById("kpis").innerHTML = [
    k("R$ 0", "de API: o modelo roda na máquina, sem chave e sem internet"),
    ai.ligada ? k(int(ai.chamadas), `chamadas ao modelo local (${esc(ai.modelo)})`) : "",
    ai.ligada ? k(`${int(ai.tokens_entrada)} / ${int(ai.tokens_saida)}`, "tokens de entrada e de saída") : "",
    ai.ligada ? k(`${dec(ai.segundos_de_maquina / 60, 0)} min`, "de processador gastos pela IA quando as respostas foram geradas; repetir pelo cache leva segundos") : "",
    k(`${dec(f.execucao.segundos_so_regras, 0)} s`, "para conciliar o mês inteiro só com regras"),
    k(brl(f.resultado.valor_a_menos_centavos), "achados que os restaurantes receberam a menos"),
    k(brl(f.resultado.valor_a_mais_centavos), "achados que os restaurantes receberam a mais"),
    k(int(f.resultado.cartas), `cartas para ${int(f.resultado.restaurantes_com_carta)} restaurantes`),
  ].join("");
}

function setupReveal() {
  const els = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window)) { els.forEach((e) => e.classList.add("in")); return; }
  const io = new IntersectionObserver((entries) => entries.forEach((en) => {
    if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
  }), { rootMargin: "0px 0px -8% 0px" });
  els.forEach((e) => io.observe(e));
}

async function main() {
  setupReveal();
  setupDialog();
  try {
    const [facts, weeks, metrics] = await Promise.all([loadJSON("data/facts.json"), loadJSON("data/weeks.json"), loadJSON("data/metrics.json")]);
    Object.assign(state, { facts, weeks, metrics });
    fillFacts(facts);
    setupDemo();
    renderResults();
    setupCalculator(facts);
  } catch (err) {
    document.getElementById("board").innerHTML = `<div class="empty">Não foi possível carregar os dados (${esc(err.message)}). Abra o site por um servidor local: python -m http.server dentro de docs/.</div>`;
  }
}
main();
