from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from ficc_terminal.analytics import (
    build_snapshot,
    curve_slope,
    generated_morning_call,
    potential_themes,
)
from ficc_terminal.briefing import CLIENT_PERSONAS, TRADE_TEMPLATES, build_pitch
from ficc_terminal.cache import OfficialHttpClient
from ficc_terminal.models import MarketDataset
from ficc_terminal.official_sources import (
    fetch_bls_macro,
    fetch_boe_nominal_curve,
    fetch_cftc_positioning,
    fetch_ecb_fx,
    fetch_ecb_yield_curve,
    fetch_eia_energy,
    fetch_official_headlines,
    fetch_sofr,
    fetch_us_treasury_curve,
)
from ficc_terminal.source_catalog import source_catalog_frame
from ficc_terminal.storage import JournalStore
from ficc_terminal.widgets import tradingview_overview_html, tradingview_ticker_html


load_dotenv()

st.set_page_config(
    page_title="FICC Morning Call & Trade-Idea Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --ink:#17231d; --green:#153f32; --lime:#c9f36a; --paper:#f5f3eb; --muted:#647168; }
    .stApp { background: var(--paper); color: var(--ink); }
    [data-testid="stSidebar"] { background: #102f25; }
    [data-testid="stSidebar"] * { color: #ecf2ed !important; }
    [data-testid="stSidebar"] .stButton button { background:#c9f36a; color:#153f32 !important; border:0; }
    h1, h2, h3 { letter-spacing:-0.025em; }
    h1 { font-family: Georgia, serif; font-weight:500; }
    .hero { padding:1.1rem 0 1.4rem; border-bottom:1px solid #d4d8ce; margin-bottom:1.2rem; }
    .hero-kicker { color:#153f32; font-size:.72rem; font-weight:800; letter-spacing:.13em; text-transform:uppercase; }
    .hero-title { max-width:950px; font:500 clamp(2.5rem,5vw,5rem)/.98 Georgia,serif; letter-spacing:-.055em; margin:.55rem 0 1rem; }
    .hero-copy { max-width:850px; color:#566259; font-size:1.03rem; line-height:1.65; }
    .source-caption { margin-top:-.6rem; color:#748077; font-size:.72rem; }
    .status-row { display:flex; flex-wrap:wrap; gap:.5rem; margin:.5rem 0 1rem; }
    .status-pill { padding:.35rem .62rem; border:1px solid #cfd4ca; border-radius:99px; background:#fffef9; font-size:.68rem; font-weight:700; }
    .status-ok { border-color:#75ad91; }
    .status-warn { border-color:#d0a85b; }
    .separation-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:.55rem; margin:1rem 0; }
    .separation-card { min-height:145px; padding:1rem; border:1px solid #d4d8ce; background:#fffef9; }
    .separation-card b { display:block; color:#153f32; font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; }
    .separation-card p { color:#5f6b63; font-size:.82rem; line-height:1.5; }
    .theme-card { padding:1rem 1.1rem; margin:.55rem 0; background:#fffef9; border-left:4px solid #c9f36a; }
    .theme-card strong { color:#153f32; }
    .theme-card small { color:#6d796f; }
    .official-limit { padding:1rem; background:#fff4df; border:1px solid #e1c48b; border-radius:.35rem; }
    .pitch-preview { padding:1.25rem; background:#153f32; color:#f6f7f1; border-radius:.35rem; }
    .pitch-preview h3 { color:#c9f36a; }
    .pitch-preview strong { color:#c9f36a; }
    div[data-testid="stMetric"] { background:#fffef9; border:1px solid #d5d9d0; padding:1rem; }
    div[data-testid="stMetric"] label { color:#637067; }
    .stTabs [data-baseweb="tab-list"] { gap:.2rem; flex-wrap:wrap; }
    .stTabs [data-baseweb="tab"] { background:#ecebe3; border-radius:3px; padding:.45rem .8rem; }
    .stTabs [aria-selected="true"] { background:#153f32 !important; color:white !important; }
    @media(max-width:900px){ .separation-grid{grid-template-columns:1fr 1fr;} }
    @media(max-width:600px){ .separation-grid{grid-template-columns:1fr;} .hero-title{font-size:2.7rem;} }
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
    client = get_client()
    loaders = {
        "ust_curve": lambda: fetch_us_treasury_curve(client),
        "sofr": lambda: fetch_sofr(client),
        "ecb_fx": lambda: fetch_ecb_fx(client),
        "ecb_curve": lambda: fetch_ecb_yield_curve(client),
        "boe_curve": lambda: fetch_boe_nominal_curve(client),
        "eia_energy": lambda: fetch_eia_energy(client, os.getenv("EIA_API_KEY")),
        "cftc_positions": lambda: fetch_cftc_positioning(client),
        "bls_macro": lambda: fetch_bls_macro(client),
    }
    datasets: dict[str, MarketDataset] = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(loader): key for key, loader in loaders.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                datasets[key] = future.result()
            except Exception as error:
                st.session_state.setdefault("load_errors", {})[key] = str(error)
    return datasets


@st.cache_data(ttl=900, show_spinner=False)
def load_headlines() -> pd.DataFrame:
    try:
        return fetch_official_headlines()
    except Exception:
        return pd.DataFrame(columns=["institution", "published", "title", "url"])


def dataset_status_html(datasets: dict[str, MarketDataset]) -> str:
    pills = []
    for dataset in datasets.values():
        good = dataset.available and not dataset.stale
        label = f"{dataset.metadata.source_name}: {dataset.status_label()}"
        css = "status-ok" if good else "status-warn"
        pills.append(f'<span class="status-pill {css}">{label}</span>')
    return '<div class="status-row">' + "".join(pills) + "</div>"


def metadata_block(dataset: MarketDataset) -> None:
    with st.expander(f"Source and methodology · {dataset.metadata.source_name}"):
        st.markdown(
            f"""
            **Series:** {dataset.metadata.series_name}  
            **Observation frequency:** {dataset.metadata.frequency}  
            **Delay:** {dataset.metadata.delay}  
            **Units:** {dataset.metadata.unit}  
            **Transformation:** {dataset.metadata.transformation}  
            **Retrieved:** {dataset.metadata.retrieved_at}  
            **Status:** {dataset.status_label()}  
            **Reuse note:** {dataset.metadata.licence_note}  
            **Official page:** [{dataset.metadata.source_name}]({dataset.metadata.source_url})
            """
        )
        if dataset.error:
            st.warning(f"Feed message: {dataset.error}")


def snapshot_row(snapshot: pd.DataFrame, instrument: str, source_contains: str | None = None):
    rows = snapshot.loc[snapshot["instrument"] == instrument]
    if source_contains:
        rows = rows.loc[rows["source"].str.contains(source_contains, case=False, na=False)]
    return None if rows.empty else rows.iloc[0]


def show_metric(label: str, row, source_label: str) -> None:
    if row is None:
        st.metric(label, "—", "Official feed unavailable")
        st.caption(source_label)
        return
    level = row["level"]
    if row["asset_class"] == "Rates":
        value = f"{level:.2f}%"
    elif label == "USD/JPY":
        value = f"{level:.2f}"
    else:
        value = f"{level:.4g}"
    change = row["change"]
    delta = None if pd.isna(change) else f"{change:+.2f}{row['change_unit']}"
    st.metric(label, value, delta, delta_color="off")
    date_text = pd.to_datetime(row["date"]).strftime("%d %b %Y")
    stale = " · cached/stale" if row["stale"] else ""
    st.caption(f"{source_label} · {date_text}{stale}")


MATURITY_ORDER = ["1M", "2M", "3M", "4M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]


def curve_chart(dataset: MarketDataset, title: str) -> go.Figure | None:
    if not dataset.available:
        return None
    frame = dataset.frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    dates = sorted(frame["date"].dropna().unique())
    if not dates:
        return None
    selected_dates = dates[-2:]
    latest = frame.loc[frame["date"].isin(selected_dates)].copy()
    order_lookup = {maturity: index for index, maturity in enumerate(MATURITY_ORDER)}
    latest["order"] = latest["instrument"].map(order_lookup)
    latest = latest.dropna(subset=["order"]).sort_values(["date", "order"])
    fig = px.line(latest, x="instrument", y="value", color=latest["date"].dt.strftime("%d %b"), markers=True, title=title)
    fig.update_layout(
        xaxis_title="Maturity",
        yaxis_title="Yield (%)",
        legend_title="Observation",
        template="plotly_white",
        margin=dict(l=15, r=15, t=55, b=20),
    )
    return fig


def line_chart(dataset: MarketDataset, instruments: list[str], title: str, y_title: str) -> go.Figure | None:
    if not dataset.available:
        return None
    frame = dataset.frame.loc[dataset.frame["instrument"].isin(instruments)].copy()
    if frame.empty:
        return None
    fig = px.line(frame, x="date", y="value", color="instrument", title=title)
    fig.update_layout(template="plotly_white", yaxis_title=y_title, xaxis_title="", margin=dict(l=15, r=15, t=55, b=20))
    return fig


with st.sidebar:
    st.markdown("## FICC Terminal")
    st.caption("Official-source market learning system")
    if st.button("Refresh official data", width="stretch"):
        load_datasets.clear()
        load_headlines.clear()
        st.rerun()
    show_live_widgets = st.toggle(
        "Show provider-hosted live screen",
        value=True,
        help="TradingView serves these prices directly and retains its attribution. Python does not extract or store them.",
    )
    st.markdown("---")
    st.markdown("**Daily routine**")
    st.markdown("1. Check verified moves\n2. Read official releases\n3. Confirm the driver\n4. Tailor one FICC pitch\n5. Save and review")
    st.markdown("---")
    st.caption("Educational project · Not investment advice")


with st.spinner("Checking official market sources…"):
    datasets = load_datasets()
snapshot = build_snapshot(datasets.values())
themes = potential_themes(snapshot)
store = get_store()

st.markdown(
    """
    <div class="hero">
      <div class="hero-kicker">London morning workflow · official-source first</div>
      <div class="hero-title">FICC Morning Call & Trade-Idea Terminal</div>
      <div class="hero-copy">Python collects and checks the facts. You decide what matters, verify the driver and turn it into a client-relevant FICC conversation.</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown(dataset_status_html(datasets), unsafe_allow_html=True)

if show_live_widgets:
    components.html(tradingview_ticker_html(), height=90, scrolling=False)
    st.caption("Provider-hosted live/delayed market screen. Prices are served by TradingView and are not stored by this application.")

tabs = st.tabs(
    [
        "Morning call",
        "Rates",
        "FX",
        "Credit & risk",
        "Commodities",
        "Equities & live screen",
        "Macro & official news",
        "FICC pitch",
        "Journal",
        "Sources",
    ]
)


with tabs[0]:
    st.subheader("Morning snapshot")
    metric_columns = st.columns(5)
    metrics = [
        ("US 2Y", snapshot_row(snapshot, "2Y", "Treasury"), "US Treasury"),
        ("US 10Y", snapshot_row(snapshot, "10Y", "Treasury"), "US Treasury"),
        ("SOFR", snapshot_row(snapshot, "SOFR"), "New York Fed"),
        ("EUR/USD", snapshot_row(snapshot, "EUR/USD"), "ECB reference rate"),
        ("WTI", snapshot_row(snapshot, "WTI"), "EIA spot series"),
    ]
    for column, (label, row, source_label) in zip(metric_columns, metrics):
        with column:
            show_metric(label, row, source_label)

    st.markdown("### What moved most?")
    if snapshot.empty:
        st.warning("No official observations are currently available. Use the Sources tab to open the institutions directly.")
    else:
        display = snapshot.head(12).copy()
        display["date"] = pd.to_datetime(display["date"]).dt.strftime("%d %b %Y")
        display["stale"] = display["stale"].map({True: "Yes", False: "No"})
        st.dataframe(
            display[["asset_class", "instrument", "date", "level", "change", "change_unit", "score", "source", "stale"]],
            width="stretch",
            hide_index=True,
            column_config={
                "score": st.column_config.ProgressColumn("Importance", min_value=0, max_value=100),
                "source": st.column_config.TextColumn("Official source"),
            },
        )
        st.caption("Importance = move versus its own history, with room for verified cross-market confirmation and event proximity. It is a prioritisation aid, not a trading signal.")

    st.markdown("### Potential cross-asset themes")
    for theme in themes:
        st.markdown(
            f'<div class="theme-card"><strong>{theme["theme"]}</strong><br>{theme["evidence"]}<br><small>{theme["verification"]}</small></div>',
            unsafe_allow_html=True,
        )

    st.markdown("### Draft the 100–150 word call")
    generated = generated_morning_call(snapshot, themes)
    morning_summary = st.text_area(
        "Automated draft — verify and rewrite it in your own words",
        value=generated,
        height=190,
        help="The application never claims an unverified causal driver. Your edited version is the real project output.",
    )
    interpretation = st.text_area(
        "Your interpretation — what matters and why?",
        placeholder="Example: The common feature is a repricing of the expected policy path. I confirmed this against…",
        height=100,
    )
    sources_checked = st.text_input(
        "Sources you personally checked",
        placeholder="Example: US Treasury close, Fed release, BLS CPI release, ECB statement",
    )
    if st.button("Save today's morning call"):
        store.save_morning_call(str(date.today()), morning_summary, interpretation, sources_checked)
        st.success("Morning call saved to the local journal.")

    st.markdown("### Keep the reasoning disciplined")
    st.markdown(
        """
        <div class="separation-grid">
          <div class="separation-card"><b>Fact</b><p>A source-linked observation: “US 10Y increased 7 bp.”</p></div>
          <div class="separation-card"><b>Interpretation</b><p>A verified explanation: “The move followed the official CPI release.”</p></div>
          <div class="separation-card"><b>Opinion</b><p>Your conditional view: “I expect front-end pressure to persist.”</p></div>
          <div class="separation-card"><b>Trade</b><p>The cleanest client-relevant expression and implementation.</p></div>
          <div class="separation-card"><b>Risk</b><p>The event or level that would make the thesis wrong.</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


with tabs[1]:
    st.subheader("Rates — the deepest section")
    rate_tabs = st.tabs(["United States", "Euro area", "United Kingdom", "Funding & curves"])
    with rate_tabs[0]:
        treasury = datasets.get("ust_curve")
        if treasury and treasury.available:
            fig = curve_chart(treasury, "Latest U.S. Treasury curves")
            if fig:
                st.plotly_chart(fig, width="stretch")
            selected = st.multiselect("Treasury maturities", MATURITY_ORDER, default=["2Y", "5Y", "10Y", "30Y"])
            history = line_chart(treasury, selected, "U.S. par yields", "Yield (%)")
            if history:
                st.plotly_chart(history, width="stretch")
            slope = curve_slope(treasury.frame)
            if not slope.empty:
                slope_fig = px.line(slope, x="date", y="value", title="U.S. 2s10s curve slope", labels={"value": "Basis points"})
                slope_fig.add_hline(y=0, line_dash="dot", line_color="#6d786f")
                slope_fig.update_layout(template="plotly_white")
                st.plotly_chart(slope_fig, width="stretch")
        else:
            st.warning(treasury.error if treasury else "Treasury adapter did not return a dataset")
        if treasury:
            metadata_block(treasury)
    with rate_tabs[1]:
        ecb_curve = datasets.get("ecb_curve")
        if ecb_curve and ecb_curve.available:
            fig = curve_chart(ecb_curve, "Euro-area AAA nominal spot curve")
            if fig:
                st.plotly_chart(fig, width="stretch")
            history = line_chart(ecb_curve, ["2Y", "5Y", "10Y", "30Y"], "ECB official curve history", "Yield (%)")
            if history:
                st.plotly_chart(history, width="stretch")
        else:
            st.warning(ecb_curve.error if ecb_curve else "ECB curve adapter unavailable")
        if ecb_curve:
            metadata_block(ecb_curve)
    with rate_tabs[2]:
        boe_curve = datasets.get("boe_curve")
        if boe_curve and boe_curve.available:
            available_maturities = list(boe_curve.frame["instrument"].dropna().unique())
            selected = st.multiselect("BoE curve points", available_maturities, default=available_maturities[:4])
            history = line_chart(boe_curve, selected, "Bank of England official nominal curve", "Yield (%)")
            if history:
                st.plotly_chart(history, width="stretch")
        else:
            st.warning(boe_curve.error if boe_curve else "Bank of England curve adapter unavailable")
        if boe_curve:
            metadata_block(boe_curve)
    with rate_tabs[3]:
        sofr = datasets.get("sofr")
        if sofr and sofr.available:
            chart = line_chart(sofr, ["SOFR"], "Secured Overnight Financing Rate", "Percent")
            if chart:
                st.plotly_chart(chart, width="stretch")
        else:
            st.warning(sofr.error if sofr else "SOFR adapter unavailable")
        if sofr:
            metadata_block(sofr)


with tabs[2]:
    st.subheader("FX — official daily reference rates")
    fx = datasets.get("ecb_fx")
    if fx and fx.available:
        instruments = list(fx.frame["instrument"].dropna().unique())
        selected = st.multiselect("Currency pairs", instruments, default=[item for item in ["EUR/USD", "GBP/USD", "USD/JPY"] if item in instruments])
        chart = line_chart(fx, selected, "ECB reference-rate crosses", "Exchange rate")
        if chart:
            st.plotly_chart(chart, width="stretch")
        returns = fx.frame.pivot_table(index="date", columns="instrument", values="value", aggfunc="last").pct_change(fill_method=None) * 100
        if not returns.empty:
            st.markdown("#### Latest daily percentage changes")
            latest_returns = returns.iloc[-1].dropna().sort_values().to_frame("Daily change (%)")
            st.dataframe(latest_returns, width="stretch")
    else:
        st.warning(fx.error if fx else "ECB FX adapter unavailable")
    if fx:
        metadata_block(fx)
    st.info("ECB rates are daily reference rates, not overnight London-open executable prices. The provider-hosted ticker above fills that timing gap without Python redistributing licensed quotes.")


with tabs[3]:
    st.subheader("Credit and market functioning")
    st.markdown(
        """
        <div class="official-limit"><strong>Important limitation</strong><br>
        Free daily institutional credit spreads, cash-bond prices and CDS indices are generally proprietary. This project does not silently pull ICE BofA series through FRED or label ETF prices as credit spreads. It uses open official stress indicators and clearly labelled provider-hosted proxies.</div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("#### Official indicators to check")
    credit_sources = [
        ("New York Fed CMDI", "Overall, investment-grade and high-yield corporate-bond market distress; monthly.", "https://www.newyorkfed.org/research/policy/cmdi"),
        ("ECB CISS", "Daily composite indicator of systemic stress; useful risk context, not a pure spread.", "https://data.ecb.europa.eu/data/datasets/CISS"),
        ("FINRA TRACE", "Authoritative U.S. corporate-bond transactions and delayed aggregates; agreement governs reuse.", "https://www.finra.org/finra-data/fixed-income"),
    ]
    columns = st.columns(3)
    for column, (title, description, url) in zip(columns, credit_sources):
        with column:
            st.markdown(f"**{title}**")
            st.write(description)
            st.link_button("Open official source", url, width="stretch")
    st.markdown("#### Daily credit workflow")
    st.markdown("1. Check CMDI/CISS for the official stress backdrop.  \n2. Use a licensed terminal or provider-hosted ETF widget for current direction.  \n3. Read primary issuance and issuer releases.  \n4. State clearly whether a number is a spread, yield, price or ETF proxy.")


with tabs[4]:
    st.subheader("Commodities — price history, fundamentals and positioning")
    energy = datasets.get("eia_energy")
    if energy and energy.available:
        chart = line_chart(energy, ["WTI", "Brent"], "Official EIA spot-price history", "USD per barrel")
        if chart:
            st.plotly_chart(chart, width="stretch")
    else:
        st.warning(energy.error if energy else "EIA adapter unavailable")
        st.caption("Register for a free EIA key, copy .env.example to .env, and add EIA_API_KEY. No paid market-data key is required.")
    if energy:
        metadata_block(energy)

    positions = datasets.get("cftc_positions")
    if positions and positions.available:
        markets = list(positions.frame["instrument"].dropna().unique())
        defaults = [market for market in markets if any(term in market.upper() for term in ["CRUDE OIL", "GOLD", "NATURAL GAS", "COPPER"])]
        selected_market = st.selectbox("CFTC managed-money market", defaults or markets)
        subset = positions.frame.loc[positions.frame["instrument"] == selected_market]
        fig = px.line(subset, x="date", y="value", title=f"Managed-money net position · {selected_market}")
        fig.add_hline(y=0, line_dash="dot", line_color="#6d786f")
        fig.update_layout(template="plotly_white", yaxis_title="Net contracts")
        st.plotly_chart(fig, width="stretch")
    else:
        st.warning(positions.error if positions else "CFTC adapter unavailable")
    if positions:
        metadata_block(positions)


with tabs[5]:
    st.subheader("Equity and live-market context")
    st.markdown("Equities matter because they reveal risk appetite and sector reactions, but they remain context for this FICC project. Raw S&P, FTSE, STOXX and other index series are licensed; the application therefore does not copy them into Python.")
    if show_live_widgets:
        components.html(tradingview_overview_html(), height=660, scrolling=False)
    else:
        st.info("Enable the provider-hosted live screen in the sidebar. Attribution and delay labels remain with the provider.")
    st.markdown("**Interpretation questions:** Did higher yields pressure duration-sensitive equities? Are banks confirming the rates move? Is the energy sector confirming the commodity move? Did credit proxies confirm or diverge from equities?")


with tabs[6]:
    st.subheader("Macro releases and official news")
    macro = datasets.get("bls_macro")
    if macro and macro.available:
        macro_instruments = list(macro.frame["instrument"].dropna().unique())
        selected = st.selectbox("BLS series", macro_instruments)
        chart = line_chart(macro, [selected], selected, "Official published value")
        if chart:
            st.plotly_chart(chart, width="stretch")
    else:
        st.warning(macro.error if macro else "BLS adapter unavailable")
    if macro:
        metadata_block(macro)

    st.markdown("#### Official calendars")
    calendar_columns = st.columns(5)
    calendars = [
        ("Fed", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
        ("ECB", "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"),
        ("BLS", "https://www.bls.gov/schedule/"),
        ("ONS", "https://www.ons.gov.uk/releasecalendar"),
        ("Eurostat", "https://ec.europa.eu/eurostat/news/release-calendar"),
    ]
    for column, (label, url) in zip(calendar_columns, calendars):
        with column:
            st.link_button(label, url, width="stretch")

    st.markdown("#### Latest central-bank releases")
    headlines = load_headlines()
    if headlines.empty:
        st.info("Official RSS feeds are currently unavailable. Use the calendar links above.")
    else:
        for row in headlines.head(15).itertuples():
            st.markdown(f"**{row.institution}** · [{row.title}]({row.url})  ")
            if row.published:
                st.caption(row.published)
    st.caption("RSS headlines are discovery links. The application does not republish articles or claim that a headline proves the cause of a market move.")


with tabs[7]:
    st.subheader("Client-specific FICC pitch")
    left, right = st.columns([0.38, 0.62])
    with left:
        persona_name = st.selectbox("Fictional client", list(CLIENT_PERSONAS))
        trade_name = st.selectbox("Illustrative trade or hedge", list(TRADE_TEMPLATES))
        pitch = build_pitch(persona_name, trade_name)
        st.markdown(f"**Client problem:** {pitch['client_problem']}")
        st.markdown(f"**Sales angle:** {pitch['sales_angle']}")
        st.caption("The templates provide structure. You must update the market view, executable level, target and risk after checking the market.")
    with right:
        st.markdown(f'<div class="pitch-preview"><h3>{pitch["trade"]}</h3><p><strong>Why this client:</strong> {pitch["client_relevance"]}</p><p><strong>Instrument:</strong> {pitch["instrument"]}</p><p><strong>Catalyst:</strong> {pitch["catalyst"]}</p><p><strong>Risk:</strong> {pitch["main_risk"]}</p></div>', unsafe_allow_html=True)

    st.markdown("#### Complete and save the pitch")
    with st.form("pitch_form"):
        market_view = st.text_area("Market view", value=pitch["market_view"], height=100)
        instrument = st.text_area("Instrument and structure", value=pitch["instrument"], height=90)
        column_a, column_b = st.columns(2)
        with column_a:
            entry_level = st.text_input("Entry level", value=pitch["entry_level"])
            target = st.text_input("Target or hedge objective", value=pitch["target"])
            time_horizon = st.text_input("Time horizon", value=pitch["time_horizon"])
        with column_b:
            catalyst = st.text_area("Expected catalyst", value=pitch["catalyst"], height=80)
            invalidation = st.text_area("Invalidation condition", value=pitch["invalidation"], height=80)
        main_risk = st.text_area("Main risks", value=pitch["main_risk"], height=90)
        client_relevance = st.text_area("Why it suits this client", value=pitch["client_relevance"], height=90)
        closing_question = st.text_input("Question to finish the sales conversation", value=pitch["closing_question"])
        submitted = st.form_submit_button("Save pitch to journal")
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
        st.success("Pitch saved. Review the outcome honestly in the Journal tab.")
    st.caption("Illustrative discussion only · Not investment advice · No suitability assessment has been performed")


with tabs[8]:
    st.subheader("Trade journal and intellectual-honesty review")
    pitches = store.list_pitches()
    if pitches.empty:
        st.info("No pitches saved yet. Complete one in the FICC Pitch tab.")
    else:
        st.dataframe(
            pitches[["id", "pitch_date", "client", "trade", "entry_level", "target", "status", "performance"]],
            width="stretch",
            hide_index=True,
        )
        pitch_id = st.selectbox("Pitch to review", pitches["id"].tolist(), format_func=lambda value: f"#{value} · {pitches.loc[pitches['id'] == value, 'trade'].iloc[0]}")
        selected = pitches.loc[pitches["id"] == pitch_id].iloc[0]
        with st.form("review_form"):
            status = st.selectbox("Status", ["Open", "Closed — thesis right", "Closed — thesis wrong", "Closed — risk limit", "Expired"])
            performance = st.text_input("Performance", value=selected.get("performance") or "", placeholder="Use the correct market convention and state assumptions")
            maximum_adverse_move = st.text_input("Maximum adverse movement", value=selected.get("maximum_adverse_move") or "")
            catalyst_outcome = st.text_area("Did the catalyst occur?", value=selected.get("catalyst_outcome") or "")
            thesis_review = st.text_area("What was right, wrong, or incomplete? What would you change?", value=selected.get("thesis_review") or "", height=130)
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

    st.markdown("#### Saved morning calls")
    calls = store.list_morning_calls()
    if calls.empty:
        st.caption("No morning calls saved yet.")
    else:
        st.dataframe(calls[["call_date", "summary", "interpretation", "sources_checked"]], width="stretch", hide_index=True)


with tabs[9]:
    st.subheader("Source register and data governance")
    catalog = source_catalog_frame()
    st.dataframe(
        catalog,
        width="stretch",
        hide_index=True,
        column_config={"url": st.column_config.LinkColumn("Official page", display_text="Open source")},
    )
    st.markdown("#### Data-health detail")
    health_rows = []
    for dataset in datasets.values():
        health_rows.append(
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
    st.dataframe(pd.DataFrame(health_rows), width="stretch", hide_index=True)
    st.markdown(
        """
        **Rules enforced by the project**

        - Keep the raw last successful official response.
        - Separate observation date from retrieval time.
        - Mark cached data as stale rather than silently treating it as current.
        - Show the institution, frequency, units and transformation.
        - Do not mix a cash yield, futures price, spread and ETF proxy.
        - Do not publish ICE BofA credit series through FRED without permission.
        - Do not scrape or reproduce Reuters, FT or other copyrighted articles.
        - Treat algorithmic themes as hypotheses until a source-linked driver is verified.
        """
    )

st.markdown("---")
st.caption("FICC Morning Call & Trade-Idea Terminal · Official-source educational project · Facts must be verified before publication · Not investment advice")

