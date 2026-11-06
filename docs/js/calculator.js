// Hours saved calculator. Same formula as src/export/site.py::hours_estimate.
// It is an estimate: the premises are assumptions and can be edited.
import { dec, esc } from "./format.js";

export function estimate(p, perWeek) {
  const scale = p.restaurantes_por_semana / perWeek.restaurantes;
  const d = perWeek.divergencias * scale, q = perWeek.revisao * scale, c = perWeek.cartas * scale;
  const manual = (p.restaurantes_por_semana * p.min_conferir_repasse + (d + q) * p.min_investigar_divergencia
    + c * p.min_escrever_carta) / 60;
  const tool = (d * p.min_revisar_divergencia + q * p.min_revisar_fila + c * p.min_revisar_carta) / 60;
  const r1 = (x) => Math.round(x * 10) / 10;
  return { manual: r1(manual), tool: r1(tool), saved: r1(r1(manual) - r1(tool)), d, q, c };
}

export function setupCalculator(facts) {
  const premises = facts.horas.premissas, perWeek = facts.horas.por_semana_nos_dados;
  const box = document.getElementById("calc-fields");
  box.innerHTML = Object.entries(premises).map(([k, v]) =>
    `<div class="field"><label for="p-${k}">${esc(v.rotulo)}</label><input type="number" inputmode="decimal" min="0" step="1" id="p-${k}" data-k="${k}" value="${v.valor}"></div>`).join("");
  const update = () => {
    const p = {};
    box.querySelectorAll("input").forEach((i) => { p[i.dataset.k] = Math.max(0, Number(i.value) || 0); });
    if (!p.restaurantes_por_semana) p.restaurantes_por_semana = 1;
    const r = estimate(p, perWeek);
    document.getElementById("calc-saved").textContent = `${dec(Math.max(0, r.saved), 1)} h`;
    document.getElementById("calc-manual").textContent = `${dec(r.manual, 1)} h`;
    document.getElementById("calc-tool").textContent = `${dec(r.tool, 1)} h`;
    document.getElementById("calc-formula").textContent =
      `Por semana, nessa escala: ${dec(r.d, 0)} divergências confirmadas, ${dec(r.q, 0)} casos na fila e ${dec(r.c, 0)} cartas, na proporção observada nos dados.`;
  };
  box.addEventListener("input", update);
  update();
}
