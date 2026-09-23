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


def fmt_money(v, unit="USD"):
    if v is None:
        return "—"
    if unit == "USD":
        return f"{v / 1e9:,.2f} bn"
    if unit == "shares":
        return f"{v / 1e6:,.0f} m"
    return f"{v:.1f}%"


def paragraphs(text):
    from markupsafe import escape
    parts = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    return "".join(f"<p>{escape(p)}</p>" for p in parts)


def sign_class(v):
    if v is None or v == 0:
        return ""
    return "pos" if v > 0 else "neg"


def env():
    e = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))
    e.filters["num"] = fmt_num
    e.filters["chg"] = fmt_chg
    e.filters["sign"] = sign_class
    e.filters["money"] = fmt_money
    e.filters["paragraphs"] = paragraphs
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
    top = set(sm.get("top", []))
    for f in sm.get("alerts", []):
        if f["ticker"] not in top:
            continue
        try:
            c = f["chart"]
            fig = charts.comparison_figure(c["dates"], c["stock"], c["benchmark"], f["ticker"], "S&P 500")
            out["slow"][f["ticker"]] = charts.to_html(fig, div_id="slow-chart-" + f["ticker"])
        except Exception as e:  # noqa: BLE001
            out["slow"][f["ticker"]] = f'<div class="note">chart: {type(e).__name__}: {e}</div>'
    return out


SECTIONS = ["snapshot", "sectors", "breadth", "earnings", "heatmap", "movers", "slow_movers", "ongoing", "deep_dive"]


def with_defaults(day):
    """A section that was never built renders as a visible note, never as a template crash."""
    day = dict(day, sections=dict(day.get("sections", {})))
    for name in SECTIONS:
        day["sections"].setdefault(name, {"error": "not built"})
    return day


def render_html(day, lang="en", docs_dir=None):
    day = with_defaults(day)
    return env().get_template("brief.html.j2").render(
        day=day, t=i18n.load(lang), lang=lang, charts=build_charts(day, docs_dir, lang))


def render_slow_movers(day, lang="en"):
    """Full list of today's slow mover alerts with static SVG charts (no plotly.js)."""
    sm = day["sections"].get("slow_movers", {})
    svgs = {}
    for f in sm.get("alerts", []):
        try:
            c = f["chart"]
            svgs[f["ticker"]] = charts.static_line_svg(c["dates"], c["stock"], c["benchmark"], f["ticker"], "S&P 500")
        except Exception as e:  # noqa: BLE001
            svgs[f["ticker"]] = f'<div class="note">chart: {type(e).__name__}: {e}</div>'
    return env().get_template("slow_movers.html.j2").render(day=day, t=i18n.load(lang), lang=lang, svgs=svgs)


def build_chunk_figs(dd):
    figs = {"cdn": charts.plotly_cdn(), "macro": {}, "metrics": {}, "price": "", "competitors": ""}
    d = dd.get("data") or {}
    try:
        if dd["chunk"] == "macro":
            for c in d.get("charts", []):
                figs["macro"][c["id"]] = charts.to_html(charts.line_figure(c["dates"], c["values"], c["label"], c["unit"]))
        elif dd["chunk"] == "numbers":
            for m, mm in (d.get("metrics") or {}).items():
                if mm:
                    figs["metrics"][m] = charts.to_html(charts.bars_figure(mm["periods"], mm["values"], mm["unit"]))
            if d.get("price"):
                figs["price"] = charts.to_html(charts.line_figure(d["price"]["dates"], d["price"]["values"], dd["ticker"]))
        elif dd["chunk"] == "competitors" and d.get("chart"):
            figs["competitors"] = charts.to_html(charts.multi_line_figure(d["chart"]))
    except Exception as e:  # noqa: BLE001
        figs["error"] = f"{type(e).__name__}: {e}"
    return figs


def render_chunk(day, lang="en"):
    dd = day["sections"]["deep_dive"]
    return env().get_template("chunk.html.j2").render(day=day, dd=dd, t=i18n.load(lang), lang=lang, figs=build_chunk_figs(dd))


def render_ongoing(day, lang="en"):
    og = day["sections"].get("ongoing", {})
    svgs = {}
    for r in og.get("rows", []):
        if r.get("chart"):
            try:
                c = r["chart"]
                svgs[r["ticker"]] = charts.static_line_svg(c["dates"], c["stock"], c["benchmark"], r["ticker"], "S&P 500")
            except Exception as e:  # noqa: BLE001
                svgs[r["ticker"]] = f'<div class="note">chart: {type(e).__name__}: {e}</div>'
    return env().get_template("ongoing.html.j2").render(day=day, og=og, t=i18n.load(lang), lang=lang, svgs=svgs)


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
        full = docs_dir / lang / "slow-movers.html"
        full.write_text(render_slow_movers(day, lang), encoding="utf-8")
        written.append(full)
        og = docs_dir / lang / "ongoing.html"
        og.write_text(render_ongoing(day, lang), encoding="utf-8")
        written.append(og)
        dd = day["sections"].get("deep_dive", {})
        if "error" not in dd and dd.get("page"):
            chunk = docs_dir / lang / dd["page"]
            chunk.parent.mkdir(parents=True, exist_ok=True)
            chunk.write_text(render_chunk(day, lang), encoding="utf-8")
            written.append(chunk)
    root = docs_dir / "index.html"
    root.write_text(REDIRECT, encoding="utf-8")
    written.append(root)
    return written
