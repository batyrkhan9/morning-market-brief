"""Telegram message text for each user mode and language, built from the day's JSON.

Rendered at build time to docs/messages/<trading day>/ and docs/messages/latest/ so the Worker can
re-send today's message in another language without running Python.
"""
from src import i18n
from src.render import fmt_chg, fmt_num

PAGES_URL = "https://batyrkhan9.github.io/morning-market-brief"
MAX = 4000  # leave headroom under Telegram's 4096


def _row(r, width=16):
    if "error" in r:
        return f"{r['label'][:width]:<{width}} {'n/a':>9}"
    last = fmt_num(r["last"], r.get("decimals", 2))
    chg = "stale" if r.get("stale") else fmt_chg(r["chg_1d"], r["unit"])
    return f"{r['label'][:width]:<{width}} {last:>9} {chg:>8}"


def full_message(day, lang="en"):
    t = i18n.load(lang)
    s = day["sections"]
    lines = [f"<b>{t['site_title']}</b> · {t['edition']} {day['date']}"]
    if day.get("unofficial"):
        lines.append(f"⚠️ {t['unofficial_tag']}: {t['unofficial_banner'].split('.')[0]}.")
    snap = s.get("snapshot", {})
    if "error" in snap:
        lines.append(f"{t['snapshot']}: {t['section_failed']}")
    else:
        rows = []
        for g in snap.get("groups", []):
            rows.extend(g["rows"])
        lines.append("<pre>" + "\n".join(_row(r) for r in rows) + "</pre>")
    br = s.get("breadth", {})
    if "error" not in br:
        lines.append(f"{t['breadth']}: {len(br.get('lows', []))} {t['at_lows']}, {len(br.get('highs', []))} {t['at_highs']}")
    fm, sm, er = s.get("movers", {}), s.get("slow_movers", {}), s.get("earnings", {})
    counts = []
    if "error" not in fm:
        top = fm["gainers"][:1] + fm["losers"][:1]
        counts.append(f"{len(fm['gainers']) + len(fm['losers'])} {t['msg_fast_movers']} ("
                      + ", ".join(f"{m['ticker']} {fmt_chg(m['chg_1d'])}" for m in top) + ")")
    if "error" not in sm:
        n = len(sm.get("alerts", []))
        counts.append(f"{n} {t['msg_slow_movers']}" + (f" ({', '.join(sm['top'])})" if sm.get("top") else ""))
    if "error" not in er:
        counts.append(f"{len(er.get('rows', []))} {t['msg_earnings']}, {er.get('scanned', 0)} {t['msg_eightk']}")
    if counts:
        lines.append(f"<b>{t['msg_counts']}</b>: " + " · ".join(counts))
    dd = s.get("deep_dive", {})
    if "error" not in dd and dd.get("name"):
        lines.append(f"<b>{t['msg_deep_dive']}</b>: {dd['name']} — {t['chunk_' + dd['chunk']]}")
    pr = s.get("prediction", {})
    if "error" not in pr and pr.get("total"):
        lines.append(f"<b>{t['msg_predictions']}</b>: {len(pr.get('open', []))} {t['msg_open']}, "
                     f"{len(pr.get('scored_today', []))} {t['msg_scored']}, {t['msg_hit_rate']} {pr['hit_rate']}")
    for e in [x for name in ("snapshot", "movers", "slow_movers", "earnings", "deep_dive") for x in [s.get(name, {})] if "error" in x]:
        pass
    failed = [name for name in ("snapshot", "sectors", "heatmap", "movers", "slow_movers", "earnings", "deep_dive") if "error" in s.get(name, {})]
    if failed:
        lines.append(f"⚠️ {t['section_failed']}: {', '.join(failed)}")
    lines.append(f'<a href="{PAGES_URL}/{lang}/">{t["msg_open_page"]}</a>')
    text = "\n".join(lines)
    if len(text) > MAX:
        text = text[: MAX - 20] + "…\n" + lines[-1]
    return text


def all_messages(day):
    """{filename: text} for every user mode and language that exists today."""
    return {"full_en.txt": full_message(day, "en")}
