// Brazilian formatting helpers and a tiny renderer for the letters.
const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

export const brl = (cents) => BRL.format(Number(cents) / 100);
export const int = (n) => new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 }).format(Number(n));
export const dec = (n, d = 1) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }).format(Number(n));
export const pct = (x, d = 1) => (x == null ? "sem dado" : `${dec(Number(x) * 100, d)}%`);
export const get = (obj, path) => path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

// Paragraphs, bold and pipe tables: all the letters use.
export function mdLite(text) {
  const blocks = text.trim().split(/\n\s*\n/);
  return blocks.map((b) => {
    const lines = b.split("\n");
    if (lines[0].startsWith("|")) {
      const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(lines[0]);
      const body = lines.slice(2).map(cells);
      return `<div class="table-scroll"><table><thead><tr>${head.map((h) => `<th scope="col">${inline(h)}</th>`).join("")}</tr></thead><tbody>${
        body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }
    if (lines[0].startsWith("# ")) return `<h3>${inline(lines[0].slice(2))}</h3>`;
    return `<p>${lines.map(inline).join("<br>")}</p>`;
  }).join("");
}
