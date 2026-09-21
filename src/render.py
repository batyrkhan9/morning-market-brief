"""Build HTML pages per language from the day's JSON."""
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src import charts, i18n
from src.paths import DOCS, TEMPLATES

REDIRECT = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=en/">
<link rel="canonical" href="en/"><title>Morning Market Brief</title></head>
<body><a href="en/">Morning Market Brief</a></body></html>
"""


def fmt_num(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:,.{decimals}f}"


def fmt_chg(v, unit="pct"):
    if v is None:
        return "—"
    if unit == "bp":
        return f"{v:+.0f} bp"
    return f"{v:+.2f}%"


def sign_class(v):
    if v is None or v == 0:
        return ""
    return "pos" if v > 0 else "neg"


def env():
    e = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))
    e.filters["num"] = fmt_num
    e.filters["chg"] = fmt_chg
    e.filters["sign"] = sign_class
    return e


def build_charts(day, docs_dir=None, lang="en"):
    """Chart HTML fragments for the template. A failing chart becomes an inline note, never a crash."""
    out = {"cdn": charts.plotly_cdn(), "heatmap": "", "slow": {}, "errors": []}
    hm = day["sections"].get("heatmap", {})
    if hm.get("rows"):
        try:
            fig = charts.treemap_figure(hm["rows"])
            out["heatmap"] = charts.to_html(fig, div_id="heatmap")
            if docs_dir is not None:
                try:
                    charts.to_png(fig, docs_dir / lang / "heatmap.png")
                except Exception as e:  # noqa: BLE001 - PNG is for Telegram, page does not need it
                    out["errors"].append(f"heatmap png: {type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            out["heatmap"] = f'<div class="note">heatmap: {type(e).__name__}: {e}</div>'
    sm = day["sections"].get("slow_movers", {})
    for f in sm.get("flagged", []):
        try:
            c = f["chart"]
            fig = charts.comparison_figure(c["dates"], c["stock"], c["benchmark"], f["ticker"], "S&P 500")
            out["slow"][f["ticker"]] = charts.to_html(fig, div_id="slow-chart-" + f["ticker"])
        except Exception as e:  # noqa: BLE001
            out["slow"][f["ticker"]] = f'<div class="note">chart: {type(e).__name__}: {e}</div>'
    return out


def render_html(day, lang="en", docs_dir=None):
    return env().get_template("brief.html.j2").render(
        day=day, t=i18n.load(lang), lang=lang, charts=build_charts(day, docs_dir, lang))


def render_baseline(base, lang="en"):
    return env().get_template("baseline.html.j2").render(base=base, t=i18n.load(lang), lang=lang)


def write_baseline(base, docs_dir=DOCS, lang="en"):
    out = docs_dir / lang / "baseline.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_baseline(base, lang), encoding="utf-8")
    return out


def write_pages(day, docs_dir=DOCS, langs=("en",)):
    """Write docs/<lang>/index.html for each language and the root redirect. Returns written paths."""
    written = []
    for lang in langs:
        out = docs_dir / lang / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html(day, lang, docs_dir), encoding="utf-8")
        written.append(out)
    root = docs_dir / "index.html"
    root.write_text(REDIRECT, encoding="utf-8")
    written.append(root)
    return written
