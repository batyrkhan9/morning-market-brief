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

The project uses [uv](https://docs.astral.sh/uv/) to manage Python. `.python-version` pins 3.12, and the system Python is never touched.

```
brew install uv                                  # once, if uv is missing
uv python install 3.12                           # once
uv venv --python 3.12 .venv                      # create the venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m src.main --dry-run           # build the page locally, send nothing, state untouched
.venv/bin/python -m src.main --date 2026-09-19   # rebuild a past day from saved JSON
.venv/bin/python -m src.main --baseline          # one-time watchlist: every stock beyond a slow mover threshold
.venv/bin/python -m src.main --weekday 2         # build today's edition with Wednesday's deep dive chunk
.venv/bin/python -m src.backtest NKE 2022-01-01  # slow mover crossings and the alerts a live run would have sent
.venv/bin/python -m src.simulate 2               # alert cards per day over the whole S&P 500 for the last 2 years
.venv/bin/python -m src.seed_state 180           # run once before the first scheduled run: pre-load state.json with
                                                 # the last 180 days of alerts so day one shows only new crossings
.venv/bin/python -m pytest                       # offline tests against saved API responses
.venv/bin/python -m tests.make_fixtures          # refresh the saved responses (network)
```

Weekly caches committed to the repo: `data/constituents.json` (Wikipedia S&P 500 table) and `data/market_caps.json`.

Or activate the venv with `source .venv/bin/activate` and use `python` directly.

Required environment variables for a real run are listed in CLAUDE.md under "Telegram bot". A dry run needs `FRED_API_KEY` and `EDGAR_CONTACT_EMAIL` (the SEC requires a contact email in the User-Agent).

## Setup on a new machine

Everything below was done once for this repo. Secrets live in `.env` locally (git-ignored), in GitHub Actions
secrets, and in the Worker's secrets. Nothing secret is in a tracked file.

1. **Keys.** `cp .env.example .env`, then fill in `FRED_API_KEY` (https://fredaccount.stlouisfed.org/apikeys, free)
   and `EDGAR_CONTACT_EMAIL` (any contact email; the SEC requires it in the User-Agent).
2. **Telegram bot.** In Telegram, talk to @BotFather: `/newbot`, pick a name and a username ending in `bot`,
   copy the token into `.env` as `TELEGRAM_TOKEN`. Send the new bot one message so it can learn your chat id.
3. **Cloudflare Worker.** `npm i -g wrangler`, `wrangler login`, then from `worker/`:
   `wrangler kv namespace create KV` and put the printed id into `worker/wrangler.toml`,
   generate a secret with `openssl rand -hex 24` into `.env` as `WORKER_SHARED_SECRET`, and
   `wrangler secret put TELEGRAM_TOKEN`, `wrangler secret put WORKER_SHARED_SECRET`, `wrangler deploy`.
   Put the printed URL into `.env` as `WORKER_URL`. Set the Telegram webhook with the shared secret as the
   secret token: `python -c "from src.telegram import set_webhook; import os; set_webhook(os.environ['WORKER_URL'] + '/webhook', os.environ['WORKER_SHARED_SECRET'])"`
   (run with `.env` loaded). The Worker ignores unknown chats that do not send `/start` and remembers up to 20 of
   them for a week; `GET $WORKER_URL/pull` with `Authorization: Bearer $WORKER_SHARED_SECRET` lists them under `seen`.
   Worker tests: `cd worker && npm install && node --test test/*.test.js`.
4. **Users** register themselves: anyone sends `/start` to the bot and walks through language, mode, send hour
   and timezone (share location, tap a city, or type one). Records live in Workers KV; `/settings`, `/pause`,
   `/resume` and `/stop` manage them. Put your own chat id into `.env` as `OWNER_CHAT_ID` (find it under `seen`
   at `GET $WORKER_URL/pull` after messaging the bot, or from `/users` once registered), then
   `wrangler secret put OWNER_CHAT_ID` from `worker/`. The owner gets crash alerts and can send `/stats`.
5. **GitHub Actions secrets.** `gh secret set NAME` for `FRED_API_KEY`, `EDGAR_CONTACT_EMAIL`,
   `TELEGRAM_TOKEN`, `WORKER_SHARED_SECRET`, `WORKER_URL`, `OWNER_CHAT_ID`.
6. **Seed the alert state** once, so the first scheduled build only reports new crossings:
   `python -m src.seed_state 180`, then commit `data/state.json`.
7. **Scheduling.** The Worker's cron (in `worker/wrangler.toml`) does the timing: every 15 minutes it sends the
   latest edition to users whose local send hour has arrived, and at 22:30, 23:30, 00:30, 01:30 and 02:30 UTC it
   dispatches the GitHub Build workflow. For that, create a fine-grained GitHub token (Settings > Developer settings
   > Fine-grained tokens) limited to this repository with **Actions: read and write**, put it in `.env` as
   `GH_DISPATCH_TOKEN` and `wrangler secret put GH_DISPATCH_TOKEN` from `worker/`. **Token expiry: see the
   "Token expiry" line below; make a new one before that date or builds stop and the owner gets an alert.**
   `gh workflow enable Build` turns on the GitHub-side backup cron at 03:00 UTC.

Manual triggers (bearer secret): `curl -X POST -H "Authorization: Bearer $WORKER_SHARED_SECRET" $WORKER_URL/run-send`
runs one send pass now, and `$WORKER_URL/dispatch-build` (add `?final=1` for the unofficial fallback) dispatches a build.

Useful checks: `python -m src.main --send-now owner` sends the latest edition to one user right away
(the user id is the `id` field from `GET $WORKER_URL/users`);
`curl $WORKER_URL/health` checks the Worker; `python -c "from src.telegram import get_webhook_info; print(get_webhook_info())"`
shows the webhook state and Telegram's last delivery error.

## Status

See the Milestones section of CLAUDE.md.
