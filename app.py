from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from ficc_terminal.analytics import build_snapshot, potential_themes
from ficc_terminal.briefing import CLIENT_PERSONAS, TRADE_TEMPLATES, build_pitch
from ficc_terminal.cache import OfficialHttpClient
from ficc_terminal.models import MarketDataset
from ficc_terminal.news import fetch_market_news, rank_market_events
from ficc_terminal.official_sources import (
    fetch_bls_macro,
    fetch_ecb_fx,
    fetch_ecb_yield_curve,
    fetch_eia_energy,
    fetch_sofr,
    fetch_us_treasury_curve,
)
from ficc_terminal.source_catalog import source_catalog_frame
from ficc_terminal.storage import JournalStore
from ficc_terminal.widgets import (
    ESSENTIAL_MARKETS,
    tradingview_advanced_chart_html,
    tradingview_ticker_html,
)


load_dotenv()

st.set_page_config(
    page_title="FICC Overnight Brief",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --ink:#18221d; --green:#123f32; --lime:#c9f36a; --paper:#f6f4ed; --muted:#657169; }
    .stApp { background:var(--paper); color:var(--ink); }
    [data-testid="stSidebar"] { background:#102f25; }
    [data-testid="stSidebar"] * { color:#eef3ef !important; }
    [data-testid="stSidebar"] .stButton button { background:#c9f36a; color:#123f32 !important; border:0; }
    h1, h2, h3 { letter-spacing:-.025em; }
    h1 { font-family:Georgia,serif; font-weight:500; }
    .hero { padding:1rem 0 1.25rem; border-bottom:1px solid #d5d9d0; margin-bottom:1.25rem; }
    .hero-kicker { color:#123f32; font-size:.72rem; font-weight:800; letter-spacing:.13em; text-transform:uppercase; }
    .hero-title { max-width:980px; font:500 clamp(2.5rem,5vw,4.8rem)/1 Georgia,serif; letter-spacing:-.05em; margin:.5rem 0 .8rem; }
    .hero-copy { max-width:870px; color:#566259; font-size:1.02rem; line-height:1.6; }
    .event-card { background:#fffef9; border:1px solid #d6dad1; border-left:5px solid #c9f36a; padding:1.05rem 1.15rem; margin:.75rem 0; border-radius:.25rem; }
    .event-number { color:#123f32; font-size:.7rem; font-weight:800; letter-spacing:.1em; text-transform:uppercase; }
    .discipline { background:#edf4ef; border:1px solid #b8cec0; padding:1rem; border-radius:.35rem; }
    .warning-box { background:#fff4df; border:1px solid #dfc38a; padding:1rem; border-radius:.35rem; }
    .pitch-box { background:#123f32; color:#f5f7f1; padding:1.25rem; border-radius:.4rem; }
    .pitch-box strong { color:#c9f36a; }
    .small-label { color:#66736a; font-size:.72rem; font-weight:750; letter-spacing:.07em; text-transform:uppercase; }
    div[data-testid="stMetric"] { background:#fffef9; border:1px solid #d6dad1; padding:.85rem; }
    div[data-testid="stMetric"] label { color:#617067; }
    [data-testid="stLinkButton"] a { border-color:#123f32; }
    @media(max-width:700px){ .hero-title{font-size:2.6rem;} }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_client() -> OfficialHttpClient:
    return OfficialHttpClient(cache_dir=Path("data/raw"), timeout=15)


@st.cache_resource
def get_store() -> JournalStore:
    return JournalStore("data/ficc_terminal.db")


@st.cache_data(ttl=900, show_spinner=False)
def load_datasets() -> dict[str, MarketDataset]:
    """Load only information that helps a daily morning call.

    Large weekly positioning files and the full BoE archive remain in the source
    register instead of slowing down every visit.
    """

    client = get_client()
    loaders = {
        "ust_curve": lambda: fetch_us_treasury_curve(client),
        "sofr": lambda: fetch_sofr(client),
        "ecb_fx": lambda: fetch_ecb_fx(client),
        "ecb_curve": lambda: fetch_ecb_yield_curve(client),
        "eia_energy": lambda: fetch_eia_energy(client, os.getenv("EIA_API_KEY")),
        "bls_macro": lambda: fetch_bls_macro(client),
    }
    datasets: dict[str, MarketDataset] = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(loader): key for key, loader in loaders.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                datasets[key] = future.result()
            except Exception:
                continue
    return datasets


@st.cache_data(ttl=600, show_spinner=False)
def load_overnight_events() -> pd.DataFrame:
    raw = fetch_market_news(get_client())
    return rank_market_events(raw, limit=5)


def snapshot_row(
    snapshot: pd.DataFrame,
    instrument: str,
    source_contains: str | None = None,
) -> pd.Series | None:
    rows = snapshot.loc[snapshot["instrument"] == instrument]
    if source_contains:
        rows = rows.loc[rows["source"].str.contains(source_contains, case=False, na=False)]
    return None if rows.empty else rows.iloc[0]


def show_move(label: str, row: pd.Series | None, context: str) -> None:
    if row is None:
        st.metric(label, "—", "Not available")
        st.caption(context)
        return
    level = float(row["level"])
    value = f"{level:.2f}%" if row["asset_class"] == "Rates" else f"{level:.4g}"
    change = row.get("change")
    delta = None if pd.isna(change) else f"{float(change):+.2f}{row['change_unit']}"
    st.metric(label, value, delta, delta_color="off")
    observed = pd.to_datetime(row["date"]).strftime("%d %b")
    st.caption(f"{context} · {observed}{' · stale' if row['stale'] else ''}")


def event_label(row: pd.Series) -> str:
    published = pd.to_datetime(row["published"], utc=True).tz_convert("Europe/London")
    return (
        f"{published.strftime('%H:%M London')} · {row['publisher']} · "
        f"{row['source_type']}"
    )


def render_event(row: pd.Series, number: int) -> None:
    with st.container(border=True):
        st.markdown(f'<div class="event-number">Event {number} · {row["event_type"]}</div>', unsafe_allow_html=True)
        st.markdown(f"#### {row['title']}")
        st.caption(event_label(row))
        tags = " · ".join(row["asset_classes"])
        st.markdown(f"**Markets to check:** {tags}")
        st.write(row["market_relevance"])
        left, right = st.columns([0.7, 0.3])
        with left:
            if row["reaction_stated"]:
                st.success(row["evidence_label"], icon="✅")
            else:
                st.warning(row["evidence_label"], icon="⚠️")
        with right:
            st.link_button("Read the source", row["url"], width="stretch")


def morning_call_draft(events: pd.DataFrame, snapshot: pd.DataFrame) -> str:
    if events.empty:
        event_text = "No sufficiently relevant overnight event was identified automatically."
    else:
        lines = []
        for row in events.head(3).itertuples():
            markets = ", ".join(row.asset_classes)
            qualifier = "with a market reaction stated in the headline" if row.reaction_stated else "with the reaction still to verify"
            lines.append(f"{row.title} ({markets}; {qualifier}).")
        event_text = " The main source-linked events were: " + " ".join(lines)

    facts = []
    for row in snapshot.dropna(subset=["change"]).head(4).itertuples():
        facts.append(f"{row.instrument} {row.change:+.1f}{row.change_unit}")
    move_text = "; ".join(facts) if facts else "official closing moves are not yet available"
    return (
        "Good morning."
        + event_text
        + f" The latest official cross-asset check shows: {move_text}. "
        "My next step is to verify the timing in the TradingView charts and open the original sources before assigning causality. "
        "For the client conversation, I would focus on the exposure most directly affected, the cleanest FICC expression or hedge, and the event that would invalidate the view."
    )


def suggested_trade_for_event(event: pd.Series | None) -> str:
    if event is None:
        return "US 2s10s steepener"
    assets = set(event.get("asset_classes", []))
    if "Commodities" in assets:
        return "WTI call spread hedge"
    if "FX" in assets:
        return "Three-month USD/JPY call spread"
    if "Rates" in assets and "FX" not in assets:
        return "US 2s10s steepener"
    if "Credit" in assets:
        return "Receive EUR 5Y"
    return "US 2s10s steepener"


def metadata_health(datasets: dict[str, MarketDataset]) -> pd.DataFrame:
    rows = []
    for dataset in datasets.values():
        rows.append(
            {
                "dataset": dataset.metadata.series_name,
                "institution": dataset.metadata.source_name,
                "status": dataset.status_label(),
                "latest observation": dataset.latest_date,
                "retrieved": dataset.metadata.retrieved_at,
                "frequency": dataset.metadata.frequency,
                "transformation": dataset.metadata.transformation,
                "message": dataset.error or "",
            }
        )
    return pd.DataFrame(rows)


with st.sidebar:
    st.markdown("## FICC Overnight Brief")
    st.caption("Understand the story before pitching the trade")
    page = st.radio(
        "Navigation",
        ["Overnight brief", "Essential charts", "Build a pitch", "Journal", "Sources"],
        label_visibility="collapsed",
    )
    if st.button("Refresh briefing", width="stretch"):
        load_datasets.clear()
        load_overnight_events.clear()
        st.rerun()
    st.markdown("---")
    st.markdown("**The interview habit**")
    st.caption("Fact → reaction → interpretation → client relevance → trade → risk")
    st.markdown("---")
    st.caption("Educational project · Not investment advice")


with st.spinner("Building the source-linked overnight brief…"):
    datasets = load_datasets()
    events = load_overnight_events()
snapshot = build_snapshot(datasets.values())
store = get_store()


if page == "Overnight brief":
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">London morning · qualitative first</div>
          <div class="hero-title">What actually mattered overnight?</div>
          <div class="hero-copy">A short list of source-linked events, the markets to inspect, and the questions that turn news into a defensible FICC conversation.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="discipline"><strong>How to read this page:</strong> “Market reaction stated” means the linked headline explicitly describes a move. “Verify the price reaction” means the event is important but causality has not been established. Open the source and check the chart before using it in an interview.</div>',
        unsafe_allow_html=True,
    )

    st.markdown("## The overnight events")
    st.caption("Ranked for recency, market breadth, event significance and whether a price reaction is explicitly reported. Maximum five.")
    if events.empty:
        st.warning("No sufficiently relevant source-linked event was found in the overnight window. Do not manufacture a story: check the official calendars and live charts below.")
    else:
        for number, (_, row) in enumerate(events.iterrows(), start=1):
            render_event(row, number)

    st.markdown("## The market reaction check")
    st.caption("TradingView serves the live/delayed prices directly. The application does not extract or relabel them.")
    components.html(tradingview_ticker_html(), height=92, scrolling=False)

    metric_columns = st.columns(5)
    essential_rows = [
        ("US 2Y", snapshot_row(snapshot, "2Y", "Treasury"), "US Treasury close"),
        ("US 10Y", snapshot_row(snapshot, "10Y", "Treasury"), "US Treasury close"),
        ("SOFR", snapshot_row(snapshot, "SOFR"), "New York Fed"),
        ("EUR/USD", snapshot_row(snapshot, "EUR/USD"), "ECB reference rate"),
        ("USD/JPY", snapshot_row(snapshot, "USD/JPY"), "ECB-derived cross"),
    ]
    for column, (label, row, context) in zip(metric_columns, essential_rows):
        with column:
            show_move(label, row, context)
    st.caption("These are auditable official reference or closing observations—not a substitute for the overnight TradingView chart.")

    st.markdown("## What may connect the moves?")
    themes = potential_themes(snapshot)[:2]
    if not themes:
        st.info("No strong cross-asset hypothesis is supported by the available official moves.")
    for theme in themes:
        with st.container(border=True):
            st.markdown(f"**Hypothesis: {theme['theme']}**")
            st.write(theme["evidence"])
            st.caption(theme["verification"])

    st.markdown("## Your 60-second morning call")
    call = st.text_area(
        "Edit this draft in your own words",
        value=morning_call_draft(events, snapshot),
        height=210,
        help="The draft deliberately avoids claiming an unverified cause.",
    )
    interpretation = st.text_area(
        "Your interpretation",
        placeholder="What is the common theme? Which market confirms or contradicts it?",
        height=90,
    )
    sources_checked = st.text_input(
        "Sources you personally opened",
        placeholder="Example: Reuters article, Fed release, US Treasury close, TradingView US 10Y chart",
    )
    if st.button("Save morning call"):
        store.save_morning_call(str(date.today()), call, interpretation, sources_checked)
        st.success("Morning call saved to your journal.")


elif page == "Essential charts":
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">One chart at a time</div>
          <div class="hero-title">The essential cross-asset screen</div>
          <div class="hero-copy">Choose an asset class, inspect only its core indicators, and answer the three interpretation questions before moving on.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    asset_class = st.radio(
        "Asset class",
        list(ESSENTIAL_MARKETS),
        horizontal=True,
    )
    guide = ESSENTIAL_MARKETS[asset_class]
    left, right = st.columns([0.28, 0.72])
    with left:
        st.markdown("### Only watch")
        for indicator in guide["indicators"]:
            st.markdown(f"- {indicator}")
        st.markdown("### Ask yourself")
        for question in guide["look_for"]:
            st.markdown(f"- {question}")
        if asset_class == "Credit":
            st.markdown(
                '<div class="warning-box"><strong>Credit limitation</strong><br>Free daily CDS indices and institutional spreads are licensed. The chart shows transparent proxies and VIX context; use CMDI/CISS for official stress and a licensed terminal for executable spreads.</div>',
                unsafe_allow_html=True,
            )
    with right:
        components.html(tradingview_advanced_chart_html(asset_class), height=660, scrolling=False)
        st.caption("Official TradingView hosted widget. Use the watchlist inside the chart to switch instruments; delay depends on the exchange and symbol.")

    st.markdown("### Primary sources to confirm the story")
    source_links = {
        "Rates": [
            ("US Treasury", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates"),
            ("ECB yield curves", "https://data.ecb.europa.eu/data/datasets/YC"),
            ("Bank of England", "https://www.bankofengland.co.uk/statistics/yield-curves"),
        ],
        "FX": [
            ("ECB reference rates", "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"),
            ("Japan MOF FX", "https://www.mof.go.jp/english/policy/international_policy/reference/feio/index.htm"),
        ],
        "Credit": [
            ("New York Fed CMDI", "https://www.newyorkfed.org/research/policy/cmdi"),
            ("ECB CISS", "https://data.ecb.europa.eu/data/datasets/CISS"),
            ("FINRA fixed income", "https://www.finra.org/finra-data/fixed-income"),
        ],
        "Commodities": [
            ("EIA", "https://www.eia.gov/"),
            ("CFTC positioning", "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"),
        ],
        "Equities": [
            ("TradingView market data", "https://www.tradingview.com/markets/"),
        ],
    }
    source_columns = st.columns(len(source_links[asset_class]))
    for column, (label, url) in zip(source_columns, source_links[asset_class]):
        with column:
            st.link_button(label, url, width="stretch")


elif page == "Build a pitch":
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">News to client conversation</div>
          <div class="hero-title">Turn one event into one FICC pitch</div>
          <div class="hero-copy">A sales pitch is not “I think the market goes up.” It connects a verified catalyst to a specific client exposure, instrument, objective and risk.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    event_options = ["No event selected"] + events["title"].tolist() if not events.empty else ["No event selected"]
    selected_title = st.selectbox("Event or catalyst", event_options)
    selected_event = None
    if selected_title != "No event selected":
        selected_event = events.loc[events["title"] == selected_title].iloc[0]
        st.caption(f"Source: {selected_event['publisher']} · Markets: {', '.join(selected_event['asset_classes'])}")

    suggested_trade = suggested_trade_for_event(selected_event)
    persona_name = st.selectbox("Fictional client", list(CLIENT_PERSONAS))
    trade_names = list(TRADE_TEMPLATES)
    trade_name = st.selectbox(
        "FICC expression or hedge",
        trade_names,
        index=trade_names.index(suggested_trade),
    )
    pitch = build_pitch(persona_name, trade_name)
    event_context = selected_title if selected_event is not None else "Complete after choosing and verifying a catalyst"

    st.markdown(
        f"""
        <div class="pitch-box">
          <p><strong>1 · Client problem</strong><br>{pitch['client_problem']}</p>
          <p><strong>2 · View</strong><br>{pitch['market_view']}</p>
          <p><strong>3 · Expression</strong><br>{pitch['instrument']}</p>
          <p><strong>4 · Catalyst</strong><br>{event_context}</p>
          <p><strong>5 · Main risk</strong><br>{pitch['main_risk']}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### Complete the details")
    with st.form("pitch_form"):
        market_view = st.text_area("Market view", value=pitch["market_view"], height=90)
        instrument = st.text_area("Instrument and structure", value=pitch["instrument"], height=85)
        catalyst = st.text_area("Verified catalyst", value=event_context, height=80)
        column_a, column_b = st.columns(2)
        with column_a:
            entry_level = st.text_input("Entry level", value=pitch["entry_level"])
            target = st.text_input("Target or hedge objective", value=pitch["target"])
            time_horizon = st.text_input("Time horizon", value=pitch["time_horizon"])
        with column_b:
            invalidation = st.text_area("What invalidates the view?", value=pitch["invalidation"], height=85)
            main_risk = st.text_area("Main risks", value=pitch["main_risk"], height=85)
        client_relevance = st.text_area("Why it is relevant to this client", value=pitch["client_relevance"], height=90)
        closing_question = st.text_input("Question to ask the client", value=pitch["closing_question"])
        submitted = st.form_submit_button("Save pitch")
    if submitted:
        completed = pitch | {
            "market_view": market_view,
            "instrument": instrument,
            "entry_level": entry_level,
            "target": target,
            "invalidation": invalidation,
            "time_horizon": time_horizon,
            "catalyst": catalyst,
            "main_risk": main_risk,
            "client_relevance": client_relevance,
            "closing_question": closing_question,
        }
        store.save_pitch(completed, str(date.today()))
        st.success("Pitch saved. Review the result later in the Journal.")
    st.caption("Illustrative discussion only · Not investment advice · No suitability assessment")


elif page == "Journal":
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">Build evidence of genuine interest</div>
          <div class="hero-title">Your morning-call and pitch journal</div>
          <div class="hero-copy">The project becomes valuable when you use it consistently and review where your interpretation was right or wrong.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    calls = store.list_morning_calls()
    st.markdown("### Saved morning calls")
    if calls.empty:
        st.info("No morning calls saved yet.")
    else:
        st.dataframe(
            calls[["call_date", "summary", "interpretation", "sources_checked"]],
            width="stretch",
            hide_index=True,
        )

    pitches = store.list_pitches()
    st.markdown("### Saved pitches")
    if pitches.empty:
        st.info("No pitches saved yet.")
    else:
        st.dataframe(
            pitches[["id", "pitch_date", "client", "trade", "entry_level", "target", "status", "performance"]],
            width="stretch",
            hide_index=True,
        )
        pitch_id = st.selectbox(
            "Pitch to review",
            pitches["id"].tolist(),
            format_func=lambda value: f"#{value} · {pitches.loc[pitches['id'] == value, 'trade'].iloc[0]}",
        )
        selected = pitches.loc[pitches["id"] == pitch_id].iloc[0]
        with st.form("review_form"):
            status = st.selectbox("Status", ["Open", "Closed — thesis right", "Closed — thesis wrong", "Closed — risk limit", "Expired"])
            performance = st.text_input("Performance", value=selected.get("performance") or "")
            maximum_adverse_move = st.text_input("Maximum adverse movement", value=selected.get("maximum_adverse_move") or "")
            catalyst_outcome = st.text_area("Did the catalyst occur?", value=selected.get("catalyst_outcome") or "")
            thesis_review = st.text_area("What was right, wrong or incomplete?", value=selected.get("thesis_review") or "", height=120)
            reviewed = st.form_submit_button("Save review")
        if reviewed:
            store.review_pitch(
                int(pitch_id),
                status=status,
                performance=performance,
                maximum_adverse_move=maximum_adverse_move,
                catalyst_outcome=catalyst_outcome,
                thesis_review=thesis_review,
            )
            st.success("Review saved.")


else:
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">Auditability before automation</div>
          <div class="hero-title">Sources and methodology</div>
          <div class="hero-copy">Every number or event must remain traceable, correctly labelled and easy to challenge.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("### How the overnight events are selected")
    st.markdown(
        """
        - **Official feeds:** Federal Reserve, ECB and Bank of England releases are collected directly.
        - **News discovery:** targeted Google News RSS searches identify potentially market-moving world events and display the named publisher and source link.
        - **Ranking:** recency, affected asset classes, high-impact language and an explicitly reported market reaction determine priority.
        - **No invented causality:** an event without an explicit market reaction is labelled for verification.
        - **Copyright discipline:** only the headline, publisher and link are displayed; articles are not reproduced.
        """
    )
    st.markdown("### Data health")
    health = metadata_health(datasets)
    if not health.empty:
        st.dataframe(health, width="stretch", hide_index=True)

    st.markdown("### Source register")
    catalog = source_catalog_frame()
    st.dataframe(
        catalog,
        width="stretch",
        hide_index=True,
        column_config={"url": st.column_config.LinkColumn("Official page", display_text="Open source")},
    )
    st.markdown("### Official calendars")
    calendars = [
        ("Federal Reserve", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
        ("ECB", "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"),
        ("BLS", "https://www.bls.gov/schedule/"),
        ("ONS", "https://www.ons.gov.uk/releasecalendar"),
        ("Eurostat", "https://ec.europa.eu/eurostat/news/release-calendar"),
    ]
    columns = st.columns(len(calendars))
    for column, (label, url) in zip(columns, calendars):
        with column:
            st.link_button(label, url, width="stretch")


st.markdown("---")
st.caption(
    f"FICC Overnight Brief · Refreshed {datetime.now(ZoneInfo('Europe/London')).strftime('%d %b %Y %H:%M London')} · "
    "Facts must be verified before publication · Not investment advice"
)
