"""Plotly figures: S&P 500 treemap and 5 year comparison lines. Interactive HTML plus PNG export."""
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs_version

# Diverging: red (down) <-> neutral gray <-> blue (up); categorical slots: blue, orange.
DOWN, MID, UP = "#e34948", "#f0efec", "#2a78d6"
SERIES = ["#2a78d6", "#eb6834"]
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def plotly_cdn():
    return f"https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js"


def treemap_figure(rows, limit=3.0):
    """rows: {ticker, name, sector, cap, chg_1d}. Box size = market cap, color = 1 day change."""
    ids, labels, parents, values, colors, text, hover = [], [], [], [], [], [], []
    sectors = sorted({r["sector"] for r in rows})
    for s in sectors:
        ids.append(s); labels.append(s); parents.append(""); values.append(0); colors.append(0)
        text.append(""); hover.append(s)
    for r in rows:
        ids.append(r["ticker"]); labels.append(r["ticker"]); parents.append(r["sector"])
        values.append(r["cap"]); colors.append(r["chg_1d"])
        text.append(f"{r['chg_1d']:+.1f}%")
        hover.append(f"{r['name']} ({r['ticker']})<br>{r['chg_1d']:+.2f}%<br>${r['cap'] / 1e9:,.0f}B")
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values, branchvalues="remainder",
        text=text, textinfo="label+text", hovertext=hover, hoverinfo="text",
        marker=dict(colors=colors, colorscale=[[0, DOWN], [0.5, MID], [1, UP]], cmid=0,
                    cmin=-limit, cmax=limit, line=dict(width=2, color="#fcfcfb"),
                    colorbar=dict(title="1 day %", ticksuffix="%", thickness=12, len=0.6)),
        pathbar=dict(visible=False), tiling=dict(pad=2), root=dict(color="#fcfcfb"),
    ))
    fig.update_layout(margin=dict(t=8, l=0, r=0, b=0), height=560, font=dict(family=FONT, color=INK),
                      paper_bgcolor="#fcfcfb")
    return fig


def comparison_figure(dates, a, b, label_a, label_b):
    """Two lines indexed to 100 at the first date. One axis, legend, 2px lines, unified hover."""
    fig = go.Figure()
    for series, label, color in ((a, label_a, SERIES[0]), (b, label_b, SERIES[1])):
        fig.add_trace(go.Scatter(x=dates, y=series, mode="lines", name=label,
                                 line=dict(width=2, color=color), hovertemplate="%{y:.0f}"))
    fig.update_layout(
        margin=dict(t=8, l=0, r=0, b=0), height=260, hovermode="x unified", showlegend=True,
        legend=dict(orientation="h", y=1.08, x=0, font=dict(size=12)),
        font=dict(family=FONT, color=INK, size=12), paper_bgcolor="#fcfcfb", plot_bgcolor="#fcfcfb",
        xaxis=dict(showgrid=False, linecolor=GRID, tickfont=dict(color=MUTED)),
        yaxis=dict(gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED), title="indexed to 100"),
    )
    return fig


def to_html(fig, div_id=None):
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id=div_id,
                       config={"displayModeBar": False, "responsive": True})


def to_png(fig, path, width=1000, height=600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_image(str(path), width=width, height=height, scale=2)
    return path


def static_line_svg(dates, a, b, label_a, label_b, width=640, height=200):
    """A dependency-free SVG line chart: two series indexed to 100, hairline grid, year ticks, legend."""
    pad_l, pad_r, pad_t, pad_b = 40, 8, 30, 20
    w, h = width - pad_l - pad_r, height - pad_t - pad_b
    vals = [v for v in a + b if v is not None]
    lo, hi = min(vals), max(vals)
    lo, hi = (lo - (hi - lo) * 0.05, hi + (hi - lo) * 0.05) if hi > lo else (lo - 1, hi + 1)
    n = max(len(dates) - 1, 1)

    def pt(i, v):
        return f"{pad_l + i / n * w:.1f},{pad_t + (hi - v) / (hi - lo) * h:.1f}"

    def path(series, color):
        pts = " ".join(pt(i, v) for i, v in enumerate(series) if v is not None)
        return f'<polyline fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" points="{pts}"/>'

    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{label_a} vs {label_b}, 5 years indexed to 100" '
           f'style="max-width:{width}px;font-family:{FONT};font-size:11px">']
    step = 50 if hi - lo > 150 else 25 if hi - lo > 60 else 10
    g = int(lo // step + 1) * step
    while g < hi:
        y = pad_t + (hi - g) / (hi - lo) * h
        out.append(f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{pad_l - 4}" y="{y + 4:.1f}" text-anchor="end" fill="{MUTED}">{g}</text>')
        g += step
    seen = set()
    for i, d in enumerate(dates):
        yr = d[:4]
        if yr not in seen and i > 0.06 * n:
            seen.add(yr)
            x = pad_l + i / n * w
            out.append(f'<text x="{x:.1f}" y="{height - 6}" text-anchor="middle" fill="{MUTED}">{yr}</text>')
    out.append(path(b, SERIES[1]))
    out.append(path(a, SERIES[0]))
    out.append(f'<rect x="{pad_l}" y="10" width="14" height="3" fill="{SERIES[0]}"/><text x="{pad_l + 18}" y="15" fill="{INK}">{label_a}</text>')
    out.append(f'<rect x="{pad_l + 90}" y="10" width="14" height="3" fill="{SERIES[1]}"/><text x="{pad_l + 108}" y="15" fill="{INK}">{label_b}</text>')
    out.append("</svg>")
    return "".join(out)


SERIES5 = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]


def _layout(fig, height, ytitle=None):
    fig.update_layout(
        margin=dict(t=8, l=0, r=0, b=0), height=height, font=dict(family=FONT, color=INK, size=12),
        paper_bgcolor="#fcfcfb", plot_bgcolor="#fcfcfb", hovermode="x unified",
        xaxis=dict(showgrid=False, linecolor=GRID, tickfont=dict(color=MUTED)),
        yaxis=dict(gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED), title=ytitle),
    )
    return fig


def bars_figure(periods, values, unit):
    """One metric over fiscal years. Thin bars, tabular hover, unit-aware axis."""
    labels = [p[:4] if p else "" for p in periods]
    if unit == "USD":
        y = [None if v is None else v / 1e9 for v in values]
        ytitle, fmt = "USD bn", "%{y:,.1f} bn"
    elif unit == "shares":
        y = [None if v is None else v / 1e6 for v in values]
        ytitle, fmt = "million shares", "%{y:,.0f} m"
    else:
        y = values
        ytitle, fmt = "%", "%{y:.1f}%"
    fig = go.Figure(go.Bar(x=labels, y=y, marker=dict(color=SERIES[0], line=dict(width=0)),
                           hovertemplate=fmt, customdata=periods, width=0.6))
    _layout(fig, 220, ytitle)
    fig.update_layout(hovermode="x", showlegend=False)
    fig.update_xaxes(type="category")
    return fig


def line_figure(dates, values, label, unit=""):
    fig = go.Figure(go.Scatter(x=dates, y=values, mode="lines", name=label,
                               line=dict(width=2, color=SERIES[0]), hovertemplate="%{y:.2f}" + (unit if unit == "%" else "")))
    _layout(fig, 220, unit if unit != "index" else None)
    fig.update_layout(showlegend=False)
    return fig


def multi_line_figure(series, height=320):
    """series: {label: {dates, values}} indexed to 100, at most 5 lines in fixed color order."""
    fig = go.Figure()
    for (label, s), color in zip(series.items(), SERIES5):
        fig.add_trace(go.Scatter(x=s["dates"], y=s["values"], mode="lines", name=label,
                                 line=dict(width=2, color=color), hovertemplate="%{y:.0f}"))
    _layout(fig, height, "indexed to 100")
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.08, x=0, font=dict(size=12)))
    return fig
