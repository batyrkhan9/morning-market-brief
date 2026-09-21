# morning-market-brief

A personal app that builds a market brief every morning, publishes it as a web page on GitHub Pages, and pings each user on Telegram with a message and a link. Weekday editions cover the last US trading day; Saturday is the week in review, Sunday is the long read and thesis.

Two user modes:

- **Full mode** (English): snapshot, sectors, calendar, earnings, fast and slow movers, a weekly deep dive, and scored predictions.
- **Simple mode** (Kazakh or Russian): one short plain-language Telegram message a day, no commands, language switch with one tap.

The full specification, hard rules, and milestones are in [CLAUDE.md](CLAUDE.md).

## Principles

- Total cost is zero: free tiers and free APIs only.
- Every number comes from a data API. An LLM never produces or edits a number.
- Every item links to a human-written source or a primary filing.
- Never fail silently: a broken section ships with a visible note.
- No secrets or chat IDs in the repo. The repo is public.

## Stack

Python 3.11+, GitHub Actions (build and send workflows), GitHub Pages (served from `/docs`), Cloudflare Worker + KV (Telegram webhook), yfinance, FRED, SEC EDGAR, Google News and Yahoo Finance RSS, Jinja2, plotly.

## Local run

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.main --dry-run            # build the page locally, send nothing
python -m src.main --date 2026-09-19    # rebuild a past day from saved JSON
```

Required environment variables for a real run are listed in CLAUDE.md under "Telegram bot". A dry run needs only `FRED_API_KEY` and `EDGAR_CONTACT_EMAIL`.

## Status

See the Milestones section of CLAUDE.md.
