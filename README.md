# Cross-Asset Morning Call & FICC Trade Journal

A qualitative-first Python/Streamlit project built for practising the daily work of a FICC salesperson:

1. Identify the most important verified cross-asset moves.
2. Separate fact, interpretation, opinion, trade and risk.
3. Translate the market into a client-specific conversation.
4. Save the pitch and review honestly whether the thesis worked.

The application is deliberately **official-source first**. It does not pretend that one free API can legally supply every professional market price.

## What the application prioritises

- Five key market stories plus a rolling 24-hour timeline of other important events, with duplicate coverage of the same underlying story grouped together.
- Events from official or known free-access publishers, with paywalled publishers excluded on a best-effort basis.
- The affected asset classes and a direct source link.
- Native Plotly charts built from official rates, FX and energy history, with recruiter-safe direct TradingView links for live or delayed market charts.
- The exact TradingView instrument names and symbols to check in the same order every day.
- One concise market check and one possible FICC angle for the selected event.
- Auditable official closing/reference data from Treasury, New York Fed, ECB, EIA and BLS.
- A blank morning-call workspace so the final wording and reasoning remain the user's own.
- A visitor-facing latest morning call, with earlier calls available one date at a time in an optional archive and editing kept in a collapsed first-page workspace.
- Fully manual FICC pitch entry with no pre-filled trade or recommendation.
- A concise, row-selectable positions journal with editable transaction detail, dated monitoring updates and structured close-out reviews.
- A closed-trade track record showing pitch hit rate, profitable-position rate, average realised return and every recorded outcome.
- Raw-response caching, stale-data flags and an auditable source register.

The navigation is deliberately short:

1. **Overnight brief** — five key events plus a concise 24-hour timeline so an earlier material story remains visible as new headlines arrive.
2. **Essential charts** — native official-data history, a fixed market routine, direct live-chart links and one key check tailored to today's event.
3. **Today's trade pitch** — write and save an original FICC pitch using blank fields.
4. **Journal** — scan a concise positions table, click a row for the full transaction, edit or monitor it, then record a structured close-out and review the resulting track record.
5. **Sources** — audit data health, methodology and reuse constraints.

## Why the architecture is hybrid

Official institutions provide reliable curves, reference rates, macroeconomic data, fundamentals and positioning, but generally not a complete set of live executable prices. Index values, CDS indices and many credit spreads are licensed.

The project therefore uses:

- **Python-controlled official data:** Treasury, New York Fed, ECB, Bank of England, EIA, CFTC and BLS.
- **Official announcement feeds:** Federal Reserve, ECB, Bank of England and Reserve Bank of Australia RSS.
- **News discovery:** targeted Google News RSS searches, limited to headlines, named free-access publishers and source links. Discovery is not treated as proof of causality.
- **Direct provider links:** exact TradingView symbols open outside the app, avoiding third-party embed failures while retaining a repeatable live-market routine.
- **Human judgement:** the final explanation, opinion and FICC pitch.

It deliberately does **not** redistribute ICE BofA credit series through FRED, scrape news articles or label an ETF price as a credit spread.

## Run locally

Python 3.11 or later is recommended.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

Most sources do not need an API key. To enable EIA energy history, register for a free key at <https://www.eia.gov/opendata/register.php> and place it in `.env`:

```text
EIA_API_KEY=your_key_here
```

Never commit `.env` or an API key to GitHub.

To keep saved morning calls, pitches and performance updates across Streamlit
Cloud restarts and redeployments, add a PostgreSQL connection string to the
deployment secrets:

```toml
DATABASE_URL = "postgresql://user:password@host:5432/database?sslmode=require"
```

Without `DATABASE_URL`, the app uses local SQLite for development. The Journal
page also provides a JSON backup download, but local SQLite alone is not durable
on Streamlit Community Cloud.

## Refresh data without opening the website

```bash
python scripts/refresh_data.py
```

You can schedule that command with cron, Windows Task Scheduler or the scheduler provided by your hosting service. A simple weekday cron entry at 06:15 London time would be:

```text
15 6 * * 1-5 cd /path/to/project && /path/to/.venv/bin/python scripts/refresh_data.py
```

Remember that UK daylight-saving time affects UTC-based schedulers.

## Test the project

```bash
pytest -q
```

The tests cover official-response parsing, native charts, free-source news filtering, event-tailored market checks, market calculations and journal storage.

## Deploy

The simplest public deployment is Streamlit Community Cloud:

1. Create a GitHub repository and push this folder.
2. Connect the repository at <https://share.streamlit.io/>.
3. Set `app.py` as the entry point.
4. Add `EIA_API_KEY` in the deployment's secrets rather than the repository.
5. Add `DATABASE_URL` to Streamlit secrets if the public journal must persist.

For a public site, recheck each institution's current terms and do not add a data series merely because it is technically downloadable.

## Daily workflow

- **5 minutes:** read the five key events, scan the important 24-hour timeline and open the relevant source links.
- **5 minutes:** check the same exact TradingView symbols and verify the event timing and cross-asset confirmation.
- **5 minutes:** write the blank 60-second call in your own words.
- **10 minutes:** write one original FICC pitch with an entry, target, invalidation and time horizon.
- **2 minutes each following day:** record the current level, performance, status and a short market update.
- **At close:** record the outcome, close date, realised return and final review; use consistent hypothetical sizing so returns remain comparable across asset classes.

The app should reduce searching time, but it must not automate away your judgement. That judgement is what makes the project valuable in interviews.

## Project structure

```text
app.py                              Streamlit interface
ficc_terminal/cache.py              Raw-response cache and fallback logic
ficc_terminal/official_sources.py   Official-source adapters and parsers
ficc_terminal/news.py               Overnight headline discovery, classification and ranking
ficc_terminal/analytics.py          Changes, curves, ranking and themes
ficc_terminal/charts.py             Native Plotly charts from official history
ficc_terminal/daily_focus.py        Event-tailored questions and pitch angles
ficc_terminal/storage.py            SQLite and persistent PostgreSQL journal backends
ficc_terminal/source_catalog.py     Source and reuse register
ficc_terminal/widgets.py            Fixed watchlists and direct chart links
scripts/refresh_data.py             Scheduled/manual refresh command
tests/                              Offline source, news, analytics and journal tests
```

## Suggested CV wording after you have used it consistently

**Cross-Asset Morning Call & FICC Trade Journal — Independent Python Project**

- Built and deployed a Python/Streamlit morning-call platform monitoring five asset classes, ranking the five most material overnight events and retaining a source-linked 24-hour market timeline.
- Established a daily routine connecting macroeconomic, monetary-policy and geopolitical catalysts to cross-asset price action, producing a 60-second morning call supported by official data.
- Formulated client-relevant, event-driven FICC trade pitches with defined instruments, catalysts, entries, targets, invalidation points and horizons, tracking daily performance against the original thesis.

Only add measurable figures—such as the number of daily calls or pitches—after you have actually produced them.

## Disclaimer

This is an educational project. It is not investment advice, does not provide executable prices and does not perform a suitability assessment.
