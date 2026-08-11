# FICC Morning Call & Trade-Idea Terminal

A qualitative-first Python/Streamlit project built for practising the daily work of a FICC salesperson:

1. Identify the most important verified cross-asset moves.
2. Separate fact, interpretation, opinion, trade and risk.
3. Translate the market into a client-specific conversation.
4. Save the pitch and review honestly whether the thesis worked.

The application is deliberately **official-source first**. It does not pretend that one free API can legally supply every professional market price.

## What the application prioritises

- A maximum of five source-linked overnight events instead of an indiscriminate news feed.
- Events from official or known free-access publishers, with paywalled publishers excluded on a best-effort basis.
- The market or asset classes to inspect, why the event matters and a direct source link.
- One TradingView-hosted advanced chart with a permanent short watchlist for rates, FX, credit proxies, commodities and equities.
- The exact TradingView instrument names and symbols to check in the same order every day.
- Questions and possible FICC pitch angles that change with the selected overnight event.
- Auditable official closing/reference data from Treasury, New York Fed, ECB, EIA and BLS.
- Plain-English rates explanations and a short glossary instead of unexplained market jargon.
- A blank morning-call workspace so the final wording and reasoning remain the user's own.
- Five fictional client personas and six FICC trade/hedging templates.
- Immediate feedback on pitch completeness and interview discipline; real performance is reviewed later.
- A SQLite journal for morning calls, pitches, performance and post-trade reviews.
- Raw-response caching, stale-data flags and an auditable source register.

The navigation is deliberately short:

1. **Overnight brief** — what happened, which market to check and the original source.
2. **Essential charts** — a fixed TradingView routine plus questions tailored to today's event.
3. **Today's trade pitch** — connect one verified event to a client, FICC expression and risk, then receive immediate structural feedback.
4. **Journal** — save calls and review pitches honestly.
5. **Sources** — audit data health, methodology and reuse constraints.

## Why the architecture is hybrid

Official institutions provide reliable curves, reference rates, macroeconomic data, fundamentals and positioning, but generally not a complete set of live executable prices. Index values, CDS indices and many credit spreads are licensed.

The project therefore uses:

- **Python-controlled official data:** Treasury, New York Fed, ECB, Bank of England, EIA, CFTC and BLS.
- **Official announcement feeds:** Federal Reserve, ECB and Bank of England RSS.
- **News discovery:** targeted Google News RSS searches, limited to headlines, named free-access publishers and source links. Discovery is not treated as proof of causality.
- **Provider-hosted widgets:** current/delayed rates, FX, credit proxies, commodities and equity context, with TradingView attribution retained.
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

The tests cover official-response parsing, free-source news filtering, event-tailored questions, plain-English explanations, pitch feedback, market calculations and the SQLite journal.

## Deploy

The simplest public deployment is Streamlit Community Cloud:

1. Create a GitHub repository and push this folder.
2. Connect the repository at <https://share.streamlit.io/>.
3. Set `app.py` as the entry point.
4. Add `EIA_API_KEY` in the deployment's secrets rather than the repository.
5. Keep TradingView attribution visible.

For a public site, recheck each institution's current terms and do not add a data series merely because it is technically downloadable.

## Daily workflow

- **5 minutes:** read the three-to-five ranked events and open the important source links.
- **5 minutes:** check the same exact TradingView symbols and verify the event timing and cross-asset confirmation.
- **5 minutes:** write the blank 60-second call in your own words.
- **10 minutes:** link one verified event to one fictional client and FICC pitch.
- **2 minutes:** use the immediate structure feedback, improve the pitch and save it for later performance review.

The app should reduce searching time, but it must not automate away your judgement. That judgement is what makes the project valuable in interviews.

## Project structure

```text
app.py                              Streamlit interface
ficc_terminal/cache.py              Raw-response cache and fallback logic
ficc_terminal/official_sources.py   Official-source adapters and parsers
ficc_terminal/news.py               Overnight headline discovery, classification and ranking
ficc_terminal/analytics.py          Changes, curves, ranking and themes
ficc_terminal/briefing.py           Client personas and pitch templates
ficc_terminal/daily_focus.py        Event-tailored questions and pitch angles
ficc_terminal/explanations.py       Plain-English rates explanations
ficc_terminal/feedback.py           Immediate pitch-structure feedback
ficc_terminal/storage.py            SQLite morning-call and trade journal
ficc_terminal/source_catalog.py     Source and reuse register
ficc_terminal/widgets.py            Provider-hosted widget configuration
scripts/refresh_data.py             Scheduled/manual refresh command
tests/                              Offline source, news, analytics and journal tests
```

## Suggested CV wording after you have used it consistently

**FICC Morning Call & Trade-Idea Terminal — Independent Python Project**

- Developed a Python/Streamlit cross-asset dashboard using official Treasury, central-bank and government data, with raw-response caching, stale-data controls and transparent source attribution.
- Translated rates, FX, credit, commodities and equity-risk developments into concise morning commentary and client-specific FICC trade and hedging discussions.
- Maintained a SQLite trade journal tracking catalysts, adverse movement, performance and post-trade thesis reviews.

Only add measurable figures—such as the number of daily calls or pitches—after you have actually produced them.

## Disclaimer

This is an educational project. It is not investment advice, does not provide executable prices and does not perform a suitability assessment.
