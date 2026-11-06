"""Open Graph image and README screenshots, taken with Playwright.

Serve the site first (cd docs && python -m http.server 8000), then:
    python scripts/screenshots.py --url http://127.0.0.1:8000
Requires requirements-dev.txt and `python -m playwright install chromium`.
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=str(ROOT / "docs" / "img"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    facts = json.loads((ROOT / "docs" / "data" / "facts.json").read_text(encoding="utf-8"))
    with sync_playwright() as p:
        b = p.chromium.launch()
        og = b.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
        og.goto((ROOT / "scripts" / "og_template.html").as_uri() + "#" + urllib.parse.quote(json.dumps(facts)))
        og.wait_for_timeout(500)
        og.screenshot(path=str(out / "og.png"))
        page = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2, reduced_motion="reduce")
        page.goto(f"{args.url}/index.html", wait_until="networkidle")
        page.wait_for_timeout(500)
        page.screenshot(path=str(out / "hero.png"))
        page.locator("#demo").scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        page.locator("#demo").screenshot(path=str(out / "demo.png"))
        page.locator("#resultados").screenshot(path=str(out / "resultados.png"))
        b.close()


if __name__ == "__main__":
    main()
