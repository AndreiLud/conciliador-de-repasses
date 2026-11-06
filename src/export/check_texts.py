"""Text checks before delivery.

* fills the static numbers of docs/index.html from docs/data/facts.json, so the
  page shows the right values even before JavaScript runs;
* every other number visible in index.html, and every number inside the
  ``<!-- facts -->`` blocks of the READMEs, must exist in facts.json;
* no em dash, en dash or spaced hyphen in prose, no forbidden expressions,
  across the site, READMEs, project docs, letters and summaries.

Usage: python -m src.export.check_texts
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

from .. import config
from ..llm.checks import FORBIDDEN_TERMS, numbers_in, numbers_in_facts
from ..money import format_brl

FACT_SPAN = re.compile(r'(<span data-fact="([^"]+)"(?: data-format="([^"]+)")?>)(.*?)(</span>)')


def _get(obj, path):
    for k in path.split("."):
        obj = obj.get(k) if isinstance(obj, dict) else None
    return obj


def _dec(x, d):
    s = f"{float(x):,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt(value, kind):
    if kind == "pct0":
        return _dec(value * 100, 0) + "%"
    if kind == "pct":
        return _dec(value * 100, 1) + "%"
    if kind == "brl":
        return format_brl(int(value))
    if kind == "dec1":
        return _dec(value, 1)
    if kind == "dec2":
        return _dec(value, 2)
    if kind == "int":
        return _dec(value, 0)
    return str(value)


def render_static_facts(path: Path, facts: dict) -> int:
    text = path.read_text(encoding="utf-8")
    count = 0

    def repl(m):
        nonlocal count
        v = _get(facts, m.group(2))
        if v is None:
            raise KeyError(f"fact not found: {m.group(2)}")
        count += 1
        return f"{m.group(1)}{fmt(v, m.group(3))}{m.group(5)}"

    path.write_text(FACT_SPAN.sub(repl, text), encoding="utf-8")
    return count


def visible_text(page: str) -> str:
    page = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", page, flags=re.S)
    page = re.sub(r'<div class="ledger"[^>]*>.*?</div>\s*</div>\s*</div>', " ", page, flags=re.S)  # illustrative mock
    page = FACT_SPAN.sub(" ", page)
    page = re.sub(r"<[^>]+>", " ", page)
    return html.unescape(page)


def strip_code(md: str) -> str:
    md = re.sub(r"```.*?```", " ", md, flags=re.S)
    return re.sub(r"`[^`]*`", " ", md)


def prose_problems(text: str) -> list[str]:
    out = []
    if "\u2014" in text:
        out.append("travessão (U+2014)")
    if "\u2013" in text:
        out.append("meia-risca (U+2013)")
    for line in text.splitlines():
        if line.strip().startswith("<!--"):
            continue
        if re.search(r"\S - \S", line) or re.match(r"^\s*- ", line):
            out.append(f"hífen como pausa ou marcador: {line.strip()[:80]}")
    low = text.lower()
    for term in FORBIDDEN_TERMS:
        if term in low:
            out.append(f"expressão proibida: {term}")
    return out


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(config.ROOT / ".env")
    facts = json.loads((config.SITE_DATA_DIR / "facts.json").read_text(encoding="utf-8"))
    allowed = numbers_in_facts(facts)
    problems: list[str] = []

    index = config.DOCS_DIR / "index.html"
    n = render_static_facts(index, facts)
    site_url = (config.env("SITE_URL") or config.SITE_URL).rstrip("/")
    page = index.read_text(encoding="utf-8")
    page = re.sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{site_url}/">', page)
    page = re.sub(r'<meta property="og:image" content="[^"]*">',
                  f'<meta property="og:image" content="{site_url}/img/og.png">', page)
    page = re.sub(r'<meta name="twitter:image" content="[^"]*">',
                  f'<meta name="twitter:image" content="{site_url}/img/og.png">', page)
    page = re.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{site_url}/">', page)
    index.write_text(page, encoding="utf-8")
    print(f"Open Graph com URL absoluta: {site_url}")
    page = index.read_text(encoding="utf-8")
    vis = visible_text(page)
    extra = sorted(str(x) for x in numbers_in(vis) - allowed)
    if extra:
        problems.append(f"docs/index.html: números fora do facts.json: {', '.join(extra)}")
    problems += [f"docs/index.html: {p}" for p in prose_problems(vis)]

    for js in sorted((config.DOCS_DIR / "js").glob("*.js")):
        strings = " ".join(re.findall(r"`([^`]*)`|\"([^\"]*)\"", js.read_text(encoding="utf-8")).__str__().split())
        for bad in ("\u2014", "\u2013"):
            if bad in strings:
                problems.append(f"{js.name}: travessão ou meia-risca em texto")

    md_files = [config.ROOT / "README.md", config.ROOT / "README.pt-BR.md",
                *sorted(config.PROJECT_DOCS_DIR.glob("*.md")),
                *sorted((config.PROJECT_DOCS_DIR / "cartas_amostra").glob("*.md")),
                *sorted((config.PROCESSED_DIR / "cartas").rglob("*.md")),
                *sorted((config.PROCESSED_DIR / "resumos").glob("*.md"))]
    for p in md_files:
        if not p.exists():
            continue
        raw = p.read_text(encoding="utf-8")
        body = strip_code(raw)
        for prob in prose_problems(body):
            problems.append(f"{p.relative_to(config.ROOT)}: {prob}")
        for block in re.findall(r"<!-- facts -->(.*?)<!-- /facts -->", raw, flags=re.S):
            extra = sorted(str(x) for x in numbers_in(strip_code(block)) - allowed)
            if extra:
                problems.append(f"{p.relative_to(config.ROOT)}: números fora do facts.json: {', '.join(extra)}")

    # Prompts list the forbidden expressions on purpose; only dashes are checked there.
    for p in sorted(config.PROMPTS_DIR.glob("*.md")):
        for prob in prose_problems(p.read_text(encoding="utf-8")):
            if not prob.startswith("expressão proibida"):
                problems.append(f"{p.relative_to(config.ROOT)}: {prob}")

    for wk in sorted(config.SITE_DATA_DIR.glob("semana_*.json")):
        data = json.loads(wk.read_text(encoding="utf-8"))
        texts = [c["texto"] for c in data["cartas"].values()] + data["resumo"]["paragrafos"] + [data["resumo"]["titulo"]]
        texts += (data["resumo"].get("leitura") or []) + [data["resumo"].get("titulo_leitura") or ""]
        texts += [d["descricao"] for d in data["divergencias"]] + [d["explicacao_ia"] or "" for d in data["divergencias"]]
        for t in texts:
            for prob in prose_problems(t):
                problems.append(f"{wk.name}: {prob}")

    print(f"{n} números do index.html preenchidos a partir do facts.json")
    if problems:
        print(f"{len(problems)} problema(s):")
        for p in problems[:200]:
            print("  " + p)
        return 1
    print("nenhum problema encontrado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
