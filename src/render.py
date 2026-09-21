"""Build HTML pages per language from the day's JSON."""
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src import i18n
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


def render_html(day, lang="en"):
    return env().get_template("brief.html.j2").render(day=day, t=i18n.load(lang), lang=lang)


def write_pages(day, docs_dir=DOCS, langs=("en",)):
    """Write docs/<lang>/index.html for each language and the root redirect. Returns written paths."""
    written = []
    for lang in langs:
        out = docs_dir / lang / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html(day, lang), encoding="utf-8")
        written.append(out)
    root = docs_dir / "index.html"
    root.write_text(REDIRECT, encoding="utf-8")
    written.append(root)
    return written
