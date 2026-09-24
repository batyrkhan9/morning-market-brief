## Goal

A personal app that builds a brief every morning, 7 days a week (market briefs on weekdays, week in review and long reads on weekends), publishes it as a web page, and pings each user on Telegram with a message and a link. The purpose is deep understanding of markets, not trading. There are two kinds of user. Me: full mode, English, I read everything, click into sources, and log predictions that get scored automatically. My father: simple mode, Kazakh or Russian, not technical, reads a short message like any other Telegram message and never has to type a command. See the Users section.

## Hard rules

1. Total cost is zero. Only free tiers and free APIs. No credit card anywhere.
2. Every number comes from a data API. An LLM never produces or edits a number.
3. The full mode brief contains no LLM-written explanations. Explanations come from linked human sources and primary filings. LLM use is limited to: the optional Q&A, optional translation, and the optional short AI summary in simple mode. All of it is clearly labeled as AI generated, and none of it ever touches a number.
4. Every item has a clickable source link. Paywalled links (Bloomberg, WSJ, FT) are allowed and marked with a "paywall" tag, and each mover should also have at least one free link when available.
5. Never fail silently. If a section breaks, the brief still ships with a visible note in that section saying what failed.
6. Every external data source sits behind one function in one file, so I can swap the source without touching the rest of the app.
7. No secrets or Telegram chat IDs in the repo. The repo is public (needed for free GitHub Pages).

## Stack

- Python 3.11+
- Scheduling lives in the Cloudflare Worker, because GitHub's cron runs late and skips slots (observed: the first Build fired at 00:44 UTC instead of 22:30, and "hourly" Send ran 4 times in 17 hours). Worker cron at 22:30, 23:30, 00:30, 01:30 and 02:30 UTC dispatches the GitHub Build workflow through the API (GH_DISPATCH_TOKEN, a fine-grained token with Actions write on this repo, stored as a Worker secret; note its expiry date in the README). Each attempt builds only once the official close is available (Yahoo, cross-checked with FRED's SP500 series) and skips if the day is already built; the 02:30 attempt builds unofficially from the last intraday bar, marks every price unofficial and alerts the owner. A GitHub cron at 03:00 UTC is the backup. Editions are keyed by the trading day covered. Worker cron every 15 minutes runs Send: each user gets the latest edition once their local send hour arrives, one message per local day, never an edition built after today's slot or before they registered (state in Workers KV). Public repos get free Actions minutes and the Worker free plan covers the crons.
- Cloudflare Worker (free plan) plus Workers KV as the Telegram webhook, so the bot can react instantly to buttons and messages. See Telegram bot.
- yfinance for prices (unofficial, will break sometimes, see rule 6)
- FRED API for yields, spreads, and macro series (free key)
- SEC EDGAR APIs for filings and financials (free, needs a User-Agent header with a contact email, max 10 requests per second)
- Google News RSS and Yahoo Finance RSS for headlines
- Jinja2 for HTML, plotly for charts (interactive on the page, PNG export via kaleido for Telegram)
- GitHub Pages for hosting (serve from /docs)
- Telegram Bot API for delivery (from Actions) and for incoming messages (through the Worker)
- JSON files committed to the repo for state (no database)

## Repo layout

```
/src
  sources/prices.py        get_prices(tickers, period) -> DataFrame
  sources/fred.py          get_series(series_id, start) -> Series
  sources/edgar.py         get_recent_filings(cik), get_company_facts(cik), get_10k_sections(cik)
  sources/news.py          get_headlines(query, n) -> list of {title, url, publisher, paywall}
  sources/constituents.py  get_sp500() -> DataFrame (ticker, name, sector, cik), cached weekly
  sections/snapshot.py
  sections/sectors.py
  sections/calendar.py
  sections/earnings.py
  sections/movers.py
  sections/slow_movers.py
  sections/deep_dive.py
  sections/monthly_screen.py
  sections/prediction.py
  render.py                builds HTML from the day's JSON
  telegram.py              send message, send photo
  users.py                 load profiles, current languages, who is due for a send
  sections/simple.py       builds the simple mode blocks
  i18n.py                  label lookup by language
  main.py                  runs everything, supports --dry-run and --date
/config
  tickers.yaml             snapshot tickers and sector ETFs
  deep_dive_schedule.yaml  the 11-week plan plus a manual queue
  thresholds.yaml          slow mover rules
  i18n/en.json, ru.json, kk.json
  glossary/kk.json, ru.json   concept of the day entries for simple mode
/data
  daily/YYYY-MM-DD.json    full data for each brief (archive)
  state.json               slow mover alert history, which user got which edition
  predictions.json
/docs                      GitHub Pages output: /en/, /kk/, /ru/, each with index.html and an archive, plus /messages/DATE/ with pre-rendered message texts
/tests                     fixtures of saved API responses, tests run offline
/worker                    Cloudflare Worker (JavaScript), wrangler config, KV binding
/.github/workflows/build.yml, send.yml
```

Pipeline: fetch all sources -> build one JSON for the day -> save to /data/daily -> render HTML per language -> commit and push -> send Telegram messages -> poll Telegram replies and process commands.

Each section runs inside its own try/except and returns either data or an error object that the template shows as a note.

## The brief

### Top part (must be readable in 5 minutes)

**1. Snapshot table.** Columns: last value, 1 day, 1 month, YTD.
- US: S&P 500 (^GSPC), Nasdaq (^IXIC), Dow (^DJI), Russell 2000 (^RUT)
- World via ETFs: Europe (VGK), Japan (EWJ), China (MCHI), Emerging markets (EEM)
- Rates from FRED: 2-year (DGS2), 10-year (DGS10), 10y minus 2y (T10Y2Y), high yield credit spread (BAMLH0A0HYM2). Show changes in basis points, not percent. FRED lags by one business day, so show the date of each value.
- Other: VIX (^VIX), dollar index (DX-Y.NYB), WTI oil (CL=F), gold (GC=F)

**2. Sectors.** All 11 sector ETFs (XLK, XLF, XLV, XLY, XLP, XLE, XLI, XLB, XLU, XLRE, XLC) ranked by 1 day change, with 1 month and YTD columns. Below it, an S&P 500 treemap heatmap: box size by market cap (cache market caps weekly), color by 1 day change, grouped by sector.

**3. Economic calendar.** Use the FRED releases API for what was released yesterday and what is scheduled today. For the big ones show latest value vs prior value: CPI (CPIAUCSL, show year over year), unemployment (UNRATE), payrolls (PAYEMS, monthly change), GDP, PCE, retail sales (RSAFS), jobless claims (ICSA), Fed funds rate (FEDFUNDS). Free sources do not give reliable analyst consensus numbers, so do not fake a "vs expected" column. Link each item to its FRED page.

**4. Earnings.** Detect S&P 500 companies that filed an 8-K with Item 2.02 (results of operations) on the last trading day, using the EDGAR submissions API. For each: company, 1 day stock move, link to the 8-K press release exhibit. This is official and free, and avoids flaky earnings calendar APIs. If a free "reporting today" source turns out to be reliable, add it, otherwise skip that part.

### Deep part (no length limit)

**5. Fast movers.** Top 5 gainers and top 5 losers in the S&P 500 by 1 day change. For each: the move, the sector's move on the same day (so I can see if it was company news or a sector move), 3 headlines with publisher name and paywall tag, and any 8-K filed that day with its item codes translated into plain labels (2.02 results, 5.02 executive change, 1.01 material agreement, and so on).

**6. Slow movers.** The reason this app exists. Flag S&P 500 stocks that crossed one of these on the last trading day:
- 1 year return crosses below -30% or above +50%
- new 52 week, 3 year, or 5 year low or high
- 5 year return crosses below -50%
Do not repeat the same ticker and rule within 30 days (track in state.json). For each flag show a 5 year price chart vs the S&P 500 and 3 headlines. Every flagged ticker gets added to the deep dive queue automatically.

**7. Deep dive of the week.** One company per week, one chunk per day. Weekdays are lighter, the long filing text goes on the weekend:
- Monday: macro day plus the week ahead. FRED charts, 5 year view: 2y and 10y yields, the 10y minus 2y curve, CPI year over year, unemployment, high yield spread, dollar. Mark what changed over the last week. Then the economic releases scheduled for this week (FRED releases API) and weekend headlines. Monday has no fast movers section, because Friday's moves are covered in the Saturday edition.
- Tuesday: how the company makes money. Full text of Item 1 (Business) from the latest 10-K, plus segment revenue if available.
- Wednesday: the numbers. 10 year charts from the EDGAR company facts API: revenue, gross margin, operating margin, net income, long term debt, shares outstanding, all next to the stock price. XBRL tag names differ by company (for revenue try Revenues, RevenueFromContractWithCustomerExcludingAssessedTax, SalesRevenueNet), so use a list of candidates per metric.
- Thursday: competitors. 5 year price charts of the company vs 3 to 4 competitors (listed in the schedule file), plus revenue growth and operating margin side by side from company facts where the competitor files with the SEC.
- Friday: latest earnings press release (from the most recent Item 2.02 8-K).
- Saturday and Sunday: see Weekend editions below.

Use a library such as edgartools or sec-parser to pull 10-K sections. Parsing will fail on some filings. When it does, show a direct link to the filing instead and note the failure.

Default schedule (editable in deep_dive_schedule.yaml):
1. Consumer Discretionary: Nike (vs Adidas ADR, On, Deckers, Lululemon)
2. Technology: Nvidia (vs AMD, Broadcom, Intel, TSMC ADR)
3. Financials: JPMorgan (vs Bank of America, Goldman Sachs, Wells Fargo)
4. Health Care: Eli Lilly (vs Novo Nordisk ADR, Pfizer, Merck)
5. Energy: ExxonMobil (vs Chevron, ConocoPhillips, Shell ADR)
6. Communication Services: Alphabet (vs Meta, Netflix, Disney)
7. Industrials: Caterpillar (vs Deere, Honeywell, GE Aerospace)
8. Consumer Staples: Costco (vs Walmart, Target, Procter and Gamble)
9. Utilities: NextEra Energy (vs Duke, Southern, Constellation)
10. Real Estate: Prologis (vs American Tower, Equinix, Simon Property)
11. Materials: Linde (vs Sherwin-Williams, Freeport-McMoRan, Nucor)

After week 11, take companies from the queue (slow mover flags plus anything I add with /queue).

**8. Monthly screen.** On the first trading day of each month: S&P 500 top 20 and bottom 20 by 1 year and by 5 year return.

**9. Prediction.** Ends every brief. Shows my open predictions, any that got scored today, and my running hit rate.

## Weekend editions

Markets are closed, so there is no new daily data. Weekends are for the week in review and the long reading.

**Saturday: week in review plus long read part 1.**
- Snapshot and sector tables on a 1 week basis (plus 1 month and YTD).
- Friday's fast movers, then the top 10 gainers and losers for the whole week.
- Every slow mover flag from the week in one list.
- Earnings recap: all Item 2.02 filers this week with their stock reaction.
- Economic data recap: everything released this week, latest vs prior.
- Predictions scored this week and the running hit rate.
- Long read: full text of Item 1A (Risk Factors) for the week's company.

**Sunday: long read part 2 plus thesis.**
- Full text of Item 7 (MD&A) for the week's company.
- One page that gathers the whole week's deep dive in one place (links to Tuesday through Saturday chunks).
- Thesis prompt. I reply with `/thesis TICKER text`, five sentences: what happened, why, bull case, bear case, what would change the story. Saved to /data/theses/TICKER.md and shown on a "My theses" archive page. Then the week's prediction with `/predict`.
- Note: the repo is public, so theses are public too. Add a config flag to keep theses out of /docs if I want them less visible.

Telegram weekend messages are short: a few lines of the week's numbers on Saturday, the thesis prompt on Sunday, plus the link.

## Users

Static user profiles live in the USERS secret (JSON, never in the repo). Example:

```
[
  {"id": "owner",  "chat_id": 111, "mode": "full",   "languages": ["en"],       "default_language": "en",
   "timezone": "America/Los_Angeles", "send_hour": 6, "blocks": [], "ai_summary": false, "is_owner": true},
  {"id": "father", "chat_id": 222, "mode": "simple", "languages": ["kk", "ru"], "default_language": "kk",
   "timezone": "Asia/Almaty", "send_hour": 8, "blocks": ["kazakhstan"], "ai_summary": false, "mirror_to_owner": true}
]
```

The current language of each user lives in Workers KV, because it changes when they tap a button. Everything else changes only when I edit the secret. Adding a third person later means adding one entry.

**Full mode (me).** Everything in "The brief" and "Weekend editions", all commands, English.

**Simple mode (my father).** Built for someone who does not read English, has no finance background, and is not technical.
- One message a day, written so that every number comes with context. No tables, no finance terms without an explanation. Blocks in order: greeting and date, one line day summary, US indexes (S&P 500, Nasdaq), oil, gold and tenge, the Kazakhstan block, the 3 biggest movers among large well-known companies (filter movers to the top 100 by market cap so the names mean something to him) each with its reason, concept of the day, link to his page.
- Context is built by code from templates, not by an LLM, so it is always correct and works the same in kk and ru:
  - Day summary: compare today's S&P 500 move with the last 5 years of daily moves. Bottom 70% by size: "normal day, nothing unusual". 70 to 95%: "noticeable move". Top 5%: "rare, big day", and the message opens with that line.
  - Under each number, one short sentence picked by rules: streaks ("third day down in a row"), change over 1 month and since the start of the year, distance from the all time high, "biggest move since DATE" when true. At most one or two facts per number, the most unusual ones win.
  - For tenge, say it in words: "tenge weakened 1,8% over the month", not just the rate.
  - Under each mover, a "Why" line with the best headline found in his languages, so the number and the reason sit together. If the whole sector moved with it, say that instead ("the whole technology sector rose 2,1%"). If no reason is found, say "no clear news" rather than leaving it empty.
- Concept of the day: one short plain explanation (2 to 3 sentences) from /config/glossary/kk.json and ru.json. About 60 entries written once, reviewed by a native speaker, then rotated: what the S&P 500 is, why oil matters for the tenge, what an index is, why interest rates move stocks, what a dividend is, and so on. If something big happens to one item (tenge, oil, gold), show that item's entry that day instead of the next one in the rotation. This is how his understanding grows over time without any AI text.
- Kazakhstan block: USD/KZT (KZT=X), plus Kaspi (KSPI) and Kazatomprom (KAP.IL or current working ticker, verify). Put any new block behind the "blocks" list so it is per user.
- News in his languages, written by real journalists, no LLM needed. Use Google News RSS with language and country parameters (hl=kk&gl=KZ and hl=ru&gl=KZ). Search by company name plus the word for "shares" in that language. Order of preference follows his current language: if it is Kazakh, take Kazakh headlines first and fill the remaining slots with Russian ones, since Kazakh coverage of US stocks is thin. If it is Russian, Russian only. Show the publisher name next to each headline. If nothing is found, show fewer headlines, never English ones.
- Optional AI summary (ai_summary flag, off by default): 3 to 4 sentences in his current language explaining the day, written by a free LLM tier from that day's headlines only. Code inserts every number. Labeled as AI written. When mirror_to_owner is true, I get a copy of his message so I can check quality. Kazakh output from free models is weaker than Russian, so test before turning it on.
- No commands, ever. Nothing in his chat starts with a slash.
- Language switch: a persistent Telegram reply keyboard with two big buttons, "Қазақша" and "Русский". Tapping one sends that word as a normal message. The Worker saves the choice to KV, confirms in the new language, and instantly re-sends today's message in that language (pre-rendered by the build job, see below). All later messages come in that language until he taps the other button.
- His page: phone first, large text, same blocks as the message with 1 month and 1 year charts for each number, a language toggle at the top (both versions are pre-built, so switching is instant), and no English text anywhere. No filings, no deep dive.
- Saturday: the same message on a weekly basis. Sunday: nothing.
- Onboarding: I send him the bot link, he presses Start once. The Worker sees a known chat_id, sets his keyboard, and greets him in Kazakh. Unknown chat IDs get no response.

Example simple mode message in Kazakh (numbers are made up, wording to be reviewed by a native speaker before launch):

```
Қайырлы таң! Дүйсенбі, 21 қыркүйек

Бүгін қысқаша
АҚШ нарығы сәл төмендеді. Бұл қалыпты тербеліс, ерекше ештеңе болған жоқ.

АҚШ акциялары
S&P 500: 6 480 (-0,8%)
Қатарынан үшінші күн төмендеп келеді. Жыл басынан бері: +12%.
Nasdaq: 21 150 (-1,2%)
Бір айда: -3,5%.

Мұнай, алтын, теңге
Brent мұнайы: $71,40 (+1,5%)
Бір айда 6%-ға қымбаттады.
Алтын: $3 310 (+0,3%)
Доллар: 541,2 теңге (+0,4%)
Теңге бір айда 1,8%-ға әлсіреді.

Қазақстан компаниялары
Kaspi: $92,10 (+0,6%)

Ең көп өзгерген ірі компаниялар
Nike: -4,1%. Жыл басынан бері: -39%.
Неге: [тақырып] · Курсив
Nvidia: +3,2%
Неге: технология секторы түгел өсті (+2,1%).

Бүгінгі ұғым: S&P 500 деген не?
Бұл АҚШ-тағы ең ірі 500 компанияның акцияларын біріктіретін көрсеткіш. Ол өссе, америкалық ірі компаниялардың құны өсіп жатыр деген сөз. Әлемдегі көп нарық соған қарап қозғалады.

Толығырақ: [сілтеме]
```

Number format for kk and ru: space as thousands separator, comma as decimal separator.

## Telegram bot

- Create with BotFather. Secrets in GitHub Actions and in the Worker: TELEGRAM_TOKEN, USERS, WORKER_SHARED_SECRET. Actions only: FRED_API_KEY, EDGAR_CONTACT_EMAIL.
- Outgoing: the hourly Send workflow sends each user their message (rendered per user mode and current language) and marks it as sent. Full mode message: snapshot as a compact text table, the heatmap PNG, count of fast movers, slow movers, and earnings, and the link to the full page. Stay under the 4,096 character limit.
- The Build job pre-renders every message variant to /docs/messages/DATE/ (full_en, simple_kk, simple_ru), so the Worker can re-send today's message in another language without running Python.
- Incoming: the Cloudflare Worker is the Telegram webhook (so do not use getUpdates anywhere). It ignores unknown chat IDs. It handles:
  - Language buttons ("Қазақша", "Русский", and "English" for me): save to KV, confirm, re-send today's message.
  - Full mode commands, confirmed instantly and saved to a KV queue:
    - `/predict NKE above 40 by 2026-12-31 because ...` (also `below`). Strict format so it can be scored with no LLM. The Worker checks the format and replies right away if something is wrong. Works for tickers and for the snapshot items (SPX, US10Y, OIL, and so on).
    - `/thesis TICKER text` saves my weekly thesis for that company.
    - `/queue TICKER` adds a company to the deep dive queue.
  - Any other text from a simple mode user: for now reply in their language that questions are coming soon, and forward the text to me. Later this becomes the Q&A (Phase 2).
- The Build job pulls the KV queue and current languages through a Worker endpoint protected by WORKER_SHARED_SECRET, then writes predictions, theses, and queue items into the repo files.
- Scoring: each build checks predictions whose date has passed, marks them right or wrong using the closing price, and reports results in the next message. predictions.json stores the user "id" field, never the chat ID.

## Languages (English, Kazakh, Russian)

- All labels, section titles, button texts, and bot replies come from /config/i18n/en.json, kk.json, ru.json. No hardcoded strings in templates or in the Worker.
- Kazakh is a first class language, in Cyrillic script. Draft kk.json and ru.json carefully, then I review every label with my father before launch. Keep finance labels in simple mode to plain everyday words.
- Numbers, tickers, and charts are the same in every language, so simple mode needs no translation engine at all: labels are static, and headlines come from Kazakh and Russian language media.
- Pages are built to /docs/en/ (full mode) and /docs/kk/ and /docs/ru/ (simple mode).
- Later option: a full mode page in kk or ru with machine translated headlines and filing text, in chunks, cached, marked "machine translated", English original one click away, with a fixed glossary for finance terms. Not needed for launch, since the only full mode reader uses English.

## Phase 2: asking questions

Step A (build with v1, costs nothing): every mover, slow mover, and deep dive chunk on the page gets an "Ask about this" button. It copies a ready prompt to the clipboard with that item's data, links, and relevant filing text, ending with "Explain why this happened. Separate what the sources confirm from what is a guess." I paste it into whatever chat model I already use.

Step B (later): real time Q&A inside Telegram. The Worker already receives every message, so this only adds one branch to it. For simple mode users any normal sentence counts as a question, no command needed. The Worker loads the current day's JSON from the repo, sends my question plus that JSON to a free LLM API tier (check current options and limits first, they change often), and replies in the user's language. Rules for the model: answer only from the provided data and linked sources, cite the link for every claim, and say "this is not in today's data" instead of guessing. Every answer ends with a line saying it is AI generated.

## Reliability

- `python -m src.main --dry-run` builds the page locally and sends nothing.
- `--date YYYY-MM-DD` rebuilds a past day from saved JSON.
- On US market holidays that fall on a weekday, send a short edition with only the deep dive chunk and a note that markets were closed (use the pandas market calendar or a small holiday list).
- Retry each network call 3 times with backoff. Cache constituents and market caps weekly.
- Tests use saved fixture responses so they run offline.
- The workflow commits /data and /docs every run. This also keeps the scheduled workflow from being auto-disabled for inactivity.
- If the whole run crashes, a final step sends me a Telegram message with the error.

## Milestones

1. Skeleton: repo layout, prices.py, fred.py, snapshot and sectors sections, HTML page, dry run works.
2. Constituents, heatmap, fast movers with news links, slow movers with state tracking.
3. EDGAR: 8-K detection for earnings and movers, company facts charts, 10-K section pull, deep dive weekly rotation.
4. Telegram and Worker: per user profiles, Build and Send workflows with per user send hours, Cloudflare Worker webhook with KV, /predict, /thesis, /queue with instant confirmation, scoring.
5. Simple mode: message template with rule based context sentences, concept of the day glossary, Kazakhstan block, Kazakh and Russian news search with fallback, pre-rendered message variants, language buttons with instant re-send, simple mode page with language toggle, onboarding flow.
6. Pages publishing, archive page, error alerts, i18n files for en, kk, ru.
7. "Ask about this" buttons. Economic calendar. Monthly screen. Saturday and Sunday editions.
8. Phase 2: optional AI summary for simple mode, then the Worker Q&A.

Done means: seven days in a row (including one weekend) every user gets their brief within an hour of their send hour with no manual fix, my father can switch between Kazakh and Russian with one tap and gets today's message back in the new language within seconds, and one broken source does not stop the rest from shipping.