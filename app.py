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

from ficc_terminal.analytics import build_snapshot
from ficc_terminal.cache import OfficialHttpClient
from ficc_terminal.daily_focus import build_daily_focus
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
    page_title="Global Markets Morning Brief",
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
    .event-number { color:#123f32; font-size:.7rem; font-weight:800; letter-spacing:.1em; text-transform:uppercase; }
    .warning-box { background:#fff4df; border:1px solid #dfc38a; padding:1rem; border-radius:.35rem; }
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
def get_journal_store_v2(schema_version: int) -> JournalStore:
    del schema_version
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


def field_text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value)


def render_event(row: pd.Series, number: int) -> None:
    with st.container(border=True):
        st.markdown(f'<div class="event-number">Event {number} · {row["event_type"]}</div>', unsafe_allow_html=True)
        st.markdown(f"#### {row['display_title']}")
        st.caption(event_label(row))
        tags = " · ".join(row["asset_classes"])
        st.markdown(f"**{tags}**")
        st.link_button("Open source", row["url"], width="stretch")


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
    st.markdown("## Global Markets Morning Brief")
    st.caption("Cross-asset market journal")
    page = st.radio(
        "Navigation",
        ["Overnight brief", "Essential charts", "Today's trade pitch", "Journal", "Sources"],
        label_visibility="collapsed",
    )
    if st.button("Refresh briefing", width="stretch"):
        load_datasets.clear()
        load_overnight_events.clear()
        st.rerun()
    st.markdown("---")
    st.caption("Independent project · Not investment advice")


with st.spinner("Building the source-linked overnight brief…"):
    datasets = load_datasets()
    events = load_overnight_events()
snapshot = build_snapshot(datasets.values())
store = get_journal_store_v2(2)


if page == "Overnight brief":
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">London morning</div>
          <div class="hero-title">Global Markets Morning Brief</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("## Key overnight events")
    if events.empty:
        st.info("No qualifying overnight event is currently available.")
    else:
        for number, (_, row) in enumerate(events.iterrows(), start=1):
            render_event(row, number)

    st.markdown("## The market reaction check")
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

    st.markdown("## Your 60-second morning call")
    call = st.text_area(
        "Morning call",
        value="",
        placeholder="Write today's morning call…",
        height=210,
    )
    if st.button("Save morning call"):
        if call.strip():
            store.save_morning_call(str(date.today()), call, "", "")
            st.success("Morning call saved.")
        else:
            st.warning("Write the morning call before saving it.")


elif page == "Essential charts":
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">One chart at a time</div>
          <div class="hero-title">The essential cross-asset screen</div>
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
    left, right = st.columns([0.34, 0.66])
    with left:
        st.markdown("### Your fixed daily watchlist")
        st.caption("These stay the same every day. Search the exact code in TradingView and check them in this order.")
        for number, indicator in enumerate(guide["indicators"], start=1):
            st.markdown(f"**{number}. {indicator['name']}**")
            st.code(indicator["symbol"], language=None)
            st.caption(indicator["why"])
        if asset_class == "Credit":
            st.markdown(
                '<div class="warning-box"><strong>Credit limitation</strong><br>Free daily CDS indices and institutional spreads are licensed. The chart shows transparent proxies and VIX context; use CMDI/CISS for official stress and a licensed terminal for executable spreads.</div>',
                unsafe_allow_html=True,
            )
    with right:
        components.html(tradingview_advanced_chart_html(asset_class), height=660, scrolling=False)
        st.caption("TradingView hosts this chart directly. Use the watchlist inside it to switch instruments; delay depends on the exchange and symbol.")

    st.markdown("### Today's event and questions")
    if events.empty:
        focus_title = "The overnight market backdrop"
        focus_assets: list[str] = []
        st.info("No qualifying free-access event was found. Use the fixed routine without assigning a cause.")
    else:
        focus_title = st.selectbox("Event to investigate", events["display_title"].tolist())
        focus_event = events.loc[events["display_title"] == focus_title].iloc[0]
        focus_assets = list(focus_event["asset_classes"])
        st.caption(f"{focus_event['publisher']} · {', '.join(focus_assets)}")
        st.link_button("Open today's free source", focus_event["url"])
    focus = build_daily_focus(
        event_title=focus_title,
        event_assets=focus_assets,
        asset_class=asset_class,
        indicator_names=[indicator["name"] for indicator in guide["indicators"]],
    )
    question_column, angle_column = st.columns(2)
    with question_column:
        st.markdown("#### Main market check")
        st.write(focus["watch"])
    with angle_column:
        st.markdown("#### FICC angle")
        st.write(focus["pitch_angle"])

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


elif page == "Today's trade pitch":
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">Trade entry</div>
          <div class="hero-title">Record today's FICC pitch</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    event_options = ["No linked event"] + events["display_title"].tolist() if not events.empty else ["No linked event"]
    linked_event = st.selectbox("Related overnight event", event_options)
    if linked_event != "No linked event":
        event_row = events.loc[events["display_title"] == linked_event].iloc[0]
        st.caption(f"{event_row['publisher']} · {', '.join(event_row['asset_classes'])}")
        st.link_button("Open source", event_row["url"])

    with st.form("manual_pitch_form", clear_on_submit=True):
        pitch_date = st.date_input("Pitch date", value=date.today())
        top_left, top_middle, top_right = st.columns(3)
        with top_left:
            trade_name = st.text_input("Trade name")
        with top_middle:
            product = st.text_input("Asset class / product")
        with top_right:
            client = st.text_input("Client / audience")

        market_view = st.text_area("Thesis", height=100)
        instrument = st.text_area("Direction and instrument", height=85)
        catalyst = st.text_area("Catalyst", height=80)

        level_left, level_middle, level_right, level_end = st.columns(4)
        with level_left:
            entry_level = st.text_input("Entry level")
        with level_middle:
            target = st.text_input("Target")
        with level_right:
            invalidation = st.text_input("Stop / invalidation")
        with level_end:
            time_horizon = st.text_input("Time horizon")

        main_risk = st.text_area("Main risks", height=80)
        client_relevance = st.text_area("Client relevance", height=80)
        closing_question = st.text_input("Client question")
        submitted = st.form_submit_button("Save pitch to journal")

    if submitted:
        if not trade_name.strip() or not market_view.strip() or not instrument.strip():
            st.warning("Complete the trade name, thesis, and direction/instrument before saving.")
        else:
            completed = {
                "client": client,
                "client_problem": "",
                "trade": trade_name,
                "product": product,
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
            store.save_pitch(completed, str(pitch_date))
            st.success("Pitch saved to the journal.")
    st.caption("Illustrative discussion only · Not investment advice · No suitability assessment")


elif page == "Journal":
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">Track record</div>
          <div class="hero-title">Market journal</div>
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
            calls[["call_date", "summary"]],
            width="stretch",
            hide_index=True,
            column_config={"call_date": "Date", "summary": "Morning call"},
        )

    pitches = store.list_pitches()
    st.markdown("### Saved pitches")
    if pitches.empty:
        st.info("No pitches saved yet.")
    else:
        st.dataframe(
            pitches[[
                "id", "pitch_date", "trade", "product", "instrument",
                "entry_level", "target", "status", "performance",
            ]],
            width="stretch",
            hide_index=True,
            column_config={
                "id": "ID",
                "pitch_date": "Pitch date",
                "trade": "Trade",
                "product": "Product",
                "instrument": "Direction / instrument",
                "entry_level": "Entry",
                "target": "Target",
                "status": "Status",
                "performance": "Latest performance",
            },
        )
        pitch_id = st.selectbox(
            "Selected pitch",
            pitches["id"].tolist(),
            format_func=lambda value: f"#{value} · {pitches.loc[pitches['id'] == value, 'trade'].iloc[0]}",
        )
        selected = pitches.loc[pitches["id"] == pitch_id].iloc[0]

        if st.session_state.pop("pitch_edit_saved", False):
            st.success("Pitch updated.")

        with st.expander("Edit pitch"):
            with st.form(f"edit_pitch_{pitch_id}"):
                edit_date = st.date_input(
                    "Pitch date",
                    value=pd.to_datetime(selected["pitch_date"]).date(),
                )
                edit_left, edit_middle, edit_right = st.columns(3)
                with edit_left:
                    edit_trade = st.text_input("Trade name", value=field_text(selected["trade"]))
                with edit_middle:
                    edit_product = st.text_input("Asset class / product", value=field_text(selected["product"]))
                with edit_right:
                    edit_client = st.text_input("Client / audience", value=field_text(selected["client"]))
                edit_view = st.text_area("Thesis", value=field_text(selected["market_view"]), height=100)
                edit_instrument = st.text_area(
                    "Direction and instrument",
                    value=field_text(selected["instrument"]),
                    height=85,
                )
                edit_catalyst = st.text_area("Catalyst", value=field_text(selected["catalyst"]), height=80)
                edit_level, edit_target_column, edit_stop, edit_horizon = st.columns(4)
                with edit_level:
                    edit_entry = st.text_input("Entry level", value=field_text(selected["entry_level"]))
                with edit_target_column:
                    edit_target = st.text_input("Target", value=field_text(selected["target"]))
                with edit_stop:
                    edit_invalidation = st.text_input(
                        "Stop / invalidation",
                        value=field_text(selected["invalidation"]),
                    )
                with edit_horizon:
                    edit_time_horizon = st.text_input(
                        "Time horizon",
                        value=field_text(selected["time_horizon"]),
                    )
                edit_risk = st.text_area("Main risks", value=field_text(selected["main_risk"]), height=80)
                edit_relevance = st.text_area(
                    "Client relevance",
                    value=field_text(selected["client_relevance"]),
                    height=80,
                )
                edit_question = st.text_input(
                    "Client question",
                    value=field_text(selected["closing_question"]),
                )
                edit_submitted = st.form_submit_button("Save changes")
            if edit_submitted:
                if not edit_trade.strip() or not edit_view.strip() or not edit_instrument.strip():
                    st.warning("Complete the trade name, thesis, and direction/instrument before saving.")
                else:
                    store.update_pitch(
                        int(pitch_id),
                        {
                            "client": edit_client,
                            "client_problem": "",
                            "trade": edit_trade,
                            "product": edit_product,
                            "market_view": edit_view,
                            "instrument": edit_instrument,
                            "entry_level": edit_entry,
                            "target": edit_target,
                            "invalidation": edit_invalidation,
                            "time_horizon": edit_time_horizon,
                            "catalyst": edit_catalyst,
                            "main_risk": edit_risk,
                            "client_relevance": edit_relevance,
                            "closing_question": edit_question,
                        },
                        str(edit_date),
                    )
                    st.session_state["pitch_edit_saved"] = True
                    st.rerun()

        with st.expander("Original pitch", expanded=True):
            detail_rows = [
                ("Date", selected["pitch_date"]),
                ("Trade", selected["trade"]),
                ("Product", field_text(selected.get("product")) or "—"),
                ("Client", field_text(selected.get("client")) or "—"),
                ("Thesis", field_text(selected.get("market_view")) or "—"),
                ("Direction / instrument", field_text(selected.get("instrument")) or "—"),
                ("Catalyst", field_text(selected.get("catalyst")) or "—"),
                ("Entry", field_text(selected.get("entry_level")) or "—"),
                ("Target", field_text(selected.get("target")) or "—"),
                ("Stop / invalidation", field_text(selected.get("invalidation")) or "—"),
                ("Horizon", field_text(selected.get("time_horizon")) or "—"),
                ("Main risk", field_text(selected.get("main_risk")) or "—"),
            ]
            st.dataframe(
                pd.DataFrame(detail_rows, columns=["Field", "Value"]),
                width="stretch",
                hide_index=True,
            )

        if st.session_state.pop("pitch_update_saved", False):
            st.success("Performance update saved.")

        st.markdown("### Add a performance update")
        with st.form(f"performance_update_{pitch_id}", clear_on_submit=True):
            update_left, update_middle, update_right = st.columns(3)
            with update_left:
                update_date = st.date_input("Update date", value=date.today())
            with update_middle:
                current_level = st.text_input("Current market level")
            with update_right:
                performance = st.text_input("Performance since entry")
            status_options = [
                "Open",
                "Monitoring",
                "Target reached",
                "Stop / invalidation reached",
                "Closed — thesis right",
                "Closed — thesis wrong",
                "Closed — risk limit",
                "Expired",
            ]
            current_status = selected.get("status") or "Open"
            status_index = status_options.index(current_status) if current_status in status_options else 0
            update_status = st.selectbox("Status", status_options, index=status_index)
            update_comment = st.text_area("Market update", height=90)
            update_submitted = st.form_submit_button("Save performance update")
        if update_submitted:
            store.add_pitch_update(
                int(pitch_id),
                update_date=str(update_date),
                current_level=current_level,
                performance=performance,
                status=update_status,
                comment=update_comment,
            )
            st.session_state["pitch_update_saved"] = True
            st.rerun()

        updates = store.list_pitch_updates(int(pitch_id))
        st.markdown("### Performance history")
        if updates.empty:
            st.info("No performance updates recorded for this pitch.")
        else:
            st.dataframe(
                updates[["update_date", "current_level", "performance", "status", "comment"]],
                width="stretch",
                hide_index=True,
                column_config={
                    "update_date": "Date",
                    "current_level": "Market level",
                    "performance": "Performance",
                    "status": "Status",
                    "comment": "Market update",
                },
            )

        with st.expander("Final review"):
            with st.form(f"review_form_{pitch_id}"):
                final_status = st.selectbox(
                    "Final status",
                    status_options,
                    index=status_index,
                    key=f"final_status_{pitch_id}",
                )
                maximum_adverse_move = st.text_input(
                    "Maximum adverse movement",
                    value=selected.get("maximum_adverse_move") or "",
                )
                catalyst_outcome = st.text_area(
                    "Catalyst outcome",
                    value=selected.get("catalyst_outcome") or "",
                )
                thesis_review = st.text_area(
                    "Review",
                    value=selected.get("thesis_review") or "",
                    height=120,
                )
                reviewed = st.form_submit_button("Save final review")
            if reviewed:
                store.review_pitch(
                    int(pitch_id),
                    status=final_status,
                    performance=selected.get("performance") or "",
                    maximum_adverse_move=maximum_adverse_move,
                    catalyst_outcome=catalyst_outcome,
                    thesis_review=thesis_review,
                )
                st.success("Final review saved.")


else:
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">Auditability before automation</div>
          <div class="hero-title">Sources and methodology</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("### How the overnight events are selected")
    st.markdown(
        """
        - **Official feeds:** Federal Reserve, ECB, Bank of England and Reserve Bank of Australia releases are collected directly.
        - **News discovery:** targeted Google News RSS searches identify potentially market-moving world events and display the named publisher and source link.
        - **Free-access policy:** paywalled publishers are excluded. Events come from official feeds or a conservative list of publishers normally readable without a subscription; access can still vary by country.
        - **Ranking:** recency, market impact and cross-asset relevance determine priority; similar headlines about one underlying story are grouped together.
        - **No invented causality:** publication time and market charts must be checked before linking an event to a move.
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
    f"Global Markets Morning Brief · Refreshed {datetime.now(ZoneInfo('Europe/London')).strftime('%d %b %Y %H:%M London')} · "
    "Facts must be verified before publication · Not investment advice"
)
