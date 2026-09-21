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
