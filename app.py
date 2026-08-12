from __future__ import annotations

import importlib
import hmac
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from ficc_terminal.analytics import build_snapshot
from ficc_terminal.cache import OfficialHttpClient
from ficc_terminal.charts import build_essential_chart
from ficc_terminal.daily_focus import build_daily_focus
from ficc_terminal.journal import (
    CLOSED_PITCH_STATUSES,
    build_closed_performance,
    build_positions_table,
    performance_summary,
)
from ficc_terminal.models import MarketDataset
from ficc_terminal.news import fetch_market_news, rank_important_events, rank_key_events
from ficc_terminal.official_sources import (
    fetch_bls_macro,
    fetch_ecb_fx,
    fetch_ecb_yield_curve,
    fetch_eia_energy,
    fetch_sofr,
    fetch_us_treasury_curve,
)
from ficc_terminal.source_catalog import source_catalog_frame
from ficc_terminal.storage import (
    JournalStore,
    PostgresJournalStore,
    database_url_from_parts,
    is_streamlit_cloud_runtime,
    journal_writes_are_durable,
    normalise_database_url,
    safe_database_error,
)
from ficc_terminal.widgets import (
    ESSENTIAL_MARKETS,
    tradingview_chart_url,
)


load_dotenv()

APP_NAME = "Cross-Asset Morning Call & FICC Trade Journal"
CLIENT_TYPES = (
    "Select a client type",
    "Macro hedge fund",
    "Real-money asset manager",
    "Credit fund",
    "Pension fund / insurance company",
    "Bank treasury / ALM",
    "Corporate treasurer - importer / exporter",
    "Corporate treasurer - commodity producer / consumer",
    "Sovereign wealth fund / reserve manager",
    "Private bank / wealth manager",
    "Other",
)

st.set_page_config(
    page_title=APP_NAME,
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
    .chart-fallback { min-height:330px; display:flex; flex-direction:column; justify-content:center; background:#fffef9; border:1px solid #d6dad1; border-radius:.5rem; padding:2.25rem; }
    .chart-fallback-title { font:500 2rem/1.15 Georgia,serif; color:#123f32; margin-bottom:.75rem; }
    .chart-fallback-copy { color:#657169; max-width:620px; }
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


JOURNAL_SCHEMA_VERSION = 8
REQUIRED_JOURNAL_METHODS = (
    "add_pitch_update",
    "list_pitch_updates",
    "list_morning_calls",
    "list_pitches",
    "review_pitch",
    "save_morning_call",
    "save_pitch",
    "update_pitch",
)


@st.cache_resource
def get_journal_store_v8(
    schema_version: int,
    database_url: str,
) -> JournalStore | PostgresJournalStore:
    del schema_version
    storage_module = importlib.import_module("ficc_terminal.storage")
    return storage_module.create_journal_store(
        database_url=database_url,
        sqlite_path="data/ficc_terminal.db",
    )


def configured_database_url() -> str:
    environment_url = os.getenv("DATABASE_URL", "").strip()
    if environment_url:
        return normalise_database_url(environment_url)
    try:
        direct_url = str(st.secrets.get("DATABASE_URL", "")).strip()
        if direct_url:
            return normalise_database_url(direct_url)
        connections = st.secrets.get("connections", {})
        postgresql = connections.get("postgresql", {})
        return database_url_from_parts(postgresql)
    except (FileNotFoundError, KeyError):
        return ""


def configured_editor_password() -> str:
    environment_password = os.getenv("EDITOR_PASSWORD", "").strip()
    if environment_password:
        return environment_password
    try:
        return str(st.secrets.get("EDITOR_PASSWORD", "")).strip()
    except Exception:
        return ""


def load_journal_store() -> JournalStore | PostgresJournalStore:
    """Return a journal object compatible with the current application.

    Streamlit can retain a cached resource while imported class code changes.
    Validate the object so a deployment recovers from an older JournalStore
    instead of repeatedly raising AttributeError errors.
    """

    database_url = ""
    try:
        database_url = configured_database_url()
        journal = get_journal_store_v8(JOURNAL_SCHEMA_VERSION, database_url)
        st.session_state.pop("journal_connection_issue", None)
    except Exception as error:
        st.session_state["journal_connection_issue"] = safe_database_error(error)
        journal = get_journal_store_v8(JOURNAL_SCHEMA_VERSION, "")
        st.warning(
            "Published journal entries are temporarily unavailable while the "
            "database connection is corrected. The rest of the dashboard remains online."
        )
    if all(hasattr(journal, method) for method in REQUIRED_JOURNAL_METHODS):
        return journal
    if hasattr(journal, "close"):
        journal.close()
    get_journal_store_v8.clear()
    importlib.invalidate_caches()
    storage_module = importlib.import_module("ficc_terminal.storage")
    importlib.reload(storage_module)
    journal = get_journal_store_v8(JOURNAL_SCHEMA_VERSION, database_url)
    missing = [method for method in REQUIRED_JOURNAL_METHODS if not hasattr(journal, method)]
    if missing:
        st.warning(
            "The journal is temporarily running in compatibility mode. "
            "Refresh the page once to finish loading the latest controls."
        )
    return journal


def render_editor_access(
    store: JournalStore | PostgresJournalStore,
) -> bool:
    """Keep the hosted journal public to read and private to edit."""

    if not is_streamlit_cloud_runtime():
        return True
    if not journal_writes_are_durable(store):
        connection_issue = st.session_state.get("journal_connection_issue", "")
        st.error(connection_issue or "Persistent journal storage is not connected.")
        st.caption("Journal editing stays locked until permanent storage is connected.")
        return False

    editor_password = configured_editor_password()
    if not editor_password:
        st.error("Owner access is not configured.")
        st.caption("Add EDITOR_PASSWORD in the app secrets to enable journal editing.")
        return False

    if st.session_state.get("editor_authenticated", False):
        st.success("Owner editing enabled")
        if st.button("Lock owner editing", width="stretch"):
            st.session_state["editor_authenticated"] = False
            st.rerun()
        return True

    with st.expander("Owner access"):
        password = st.text_input(
            "Password",
            type="password",
            key="editor_password_input",
        )
        if st.button("Unlock editing", width="stretch"):
            if hmac.compare_digest(password, editor_password):
                st.session_state["editor_authenticated"] = True
                st.session_state.pop("editor_password_error", None)
                st.rerun()
            st.session_state["editor_password_error"] = True
        if st.session_state.get("editor_password_error", False):
            st.error("Incorrect password.")
    return False


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
def load_market_events() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = fetch_market_news(get_client())
    return (
        rank_key_events(raw, limit=5),
        rank_important_events(raw, hours=24, limit=20),
    )


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


def journal_backup_json(
    store: JournalStore | PostgresJournalStore,
) -> str:
    payload = {
        "exported_at": datetime.now(ZoneInfo("Europe/London")).isoformat(timespec="seconds"),
        "morning_calls": store.list_morning_calls().to_dict(orient="records"),
        "pitches": store.list_pitches().to_dict(orient="records"),
        "pitch_updates": store.list_pitch_updates().to_dict(orient="records"),
    }
    return json.dumps(payload, indent=2, default=str)


def delete_pitch_safely(
    store: JournalStore | PostgresJournalStore,
    pitch_id: int,
) -> bool:
    """Delete a pitch even if Streamlit retained a pre-deletion store object."""

    delete_method = getattr(store, "delete_pitch", None)
    if callable(delete_method):
        return bool(delete_method(pitch_id))

    sqlite_connection = getattr(store, "connection", None)
    if sqlite_connection is not None:
        sqlite_connection.execute(
            "DELETE FROM pitch_updates WHERE pitch_id = ?",
            (pitch_id,),
        )
        cursor = sqlite_connection.execute(
            "DELETE FROM pitches WHERE id = ?",
            (pitch_id,),
        )
        sqlite_connection.commit()
        return cursor.rowcount == 1

    postgres_connect = getattr(store, "_connect", None)
    if callable(postgres_connect):
        with postgres_connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM pitch_updates WHERE pitch_id = %s",
                    (pitch_id,),
                )
                cursor.execute(
                    "DELETE FROM pitches WHERE id = %s",
                    (pitch_id,),
                )
                return cursor.rowcount == 1
    return False


def render_event(row: pd.Series, number: int) -> None:
    with st.container(border=True):
        st.markdown(f'<div class="event-number">Event {number} · {row["event_type"]}</div>', unsafe_allow_html=True)
        st.markdown(f"#### {row['display_title']}")
        st.caption(event_label(row))
        tags = " · ".join(row["asset_classes"])
        st.markdown(f"**{tags}**")
        st.link_button("Open source", row["url"], width="stretch")


def morning_call_date_label(value: object) -> str:
    call_date = pd.to_datetime(value, errors="coerce")
    return (
        call_date.strftime("%A, %d %B %Y")
        if pd.notna(call_date)
        else field_text(value)
    )


def render_morning_call(row: pd.Series) -> None:
    with st.container(border=True):
        st.caption(morning_call_date_label(row["call_date"]))
        st.write(field_text(row["summary"]))


def render_public_morning_call_history(calls: pd.DataFrame) -> None:
    st.markdown("## Latest morning call")
    if calls.empty:
        st.info("No morning call has been published yet.")
        return

    render_morning_call(calls.iloc[0])
    earlier_calls = calls.iloc[1:].copy()
    if not earlier_calls.empty:
        earlier_calls["id"] = earlier_calls["id"].astype(int)
        with st.expander(f"Browse past morning calls ({len(earlier_calls)})"):
            call_ids = earlier_calls["id"].tolist()
            selected_id = st.selectbox(
                "Select a date",
                call_ids,
                format_func=lambda call_id: morning_call_date_label(
                    earlier_calls.loc[
                        earlier_calls["id"] == call_id,
                        "call_date",
                    ].iloc[0]
                ),
                key="public_morning_call_archive",
            )
            selected_call = earlier_calls.loc[
                earlier_calls["id"] == selected_id
            ].iloc[0]
            render_morning_call(selected_call)


def render_morning_call_editor(
    calls: pd.DataFrame,
    store: JournalStore | PostgresJournalStore,
    editing_enabled: bool,
) -> None:
    if not editing_enabled:
        return
    st.markdown("## Your 60-second morning call")
    with st.expander("Write or edit a morning call"):
        call_options: list[str | int] = ["new"]
        if not calls.empty:
            call_options.extend(calls["id"].astype(int).tolist())

        def call_option_label(value: str | int) -> str:
            if value == "new":
                return "New morning call"
            selected_date = calls.loc[calls["id"] == value, "call_date"].iloc[0]
            return f"Edit · {morning_call_date_label(selected_date)}"

        selected_option = st.selectbox(
            "Entry",
            call_options,
            format_func=call_option_label,
            key="morning_call_editor_selection",
        )
        is_new = selected_option == "new"
        if is_new:
            selected_date = date.today()
            existing_text = ""
        else:
            selected_row = calls.loc[calls["id"] == selected_option].iloc[0]
            selected_date = pd.to_datetime(selected_row["call_date"]).date()
            existing_text = field_text(selected_row["summary"])

        with st.form(f"morning_call_form_{selected_option}"):
            if is_new:
                call_date = st.date_input("Publication date", value=selected_date)
            else:
                call_date = selected_date
                st.caption(f"Editing {morning_call_date_label(call_date)}")
            call_text = st.text_area(
                "Morning call",
                value=existing_text,
                placeholder="Write today's morning call…",
                height=210,
            )
            submitted = st.form_submit_button(
                "Publish morning call" if is_new else "Save changes"
            )

        if submitted:
            if call_text.strip():
                store.save_morning_call(str(call_date), call_text.strip(), "", "")
                st.session_state["morning_call_saved"] = (
                    "Morning call published."
                    if is_new
                    else "Morning call updated."
                )
                st.rerun()
            else:
                st.warning("Write the morning call before saving it.")


def percentage_label(value: float | int | None, *, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.{decimals}f}%"


def render_pitch_performance(pitches: pd.DataFrame) -> None:
    st.markdown("## Performance")
    closed = build_closed_performance(pitches)
    if closed.empty:
        st.info("Performance figures will appear after the first position is closed.")
        return

    summary = performance_summary(closed)
    metric_columns = st.columns(4)
    metric_columns[0].metric("Closed positions", summary["closed_count"])
    metric_columns[1].metric(
        "Good-pitch rate",
        percentage_label(summary["good_pitch_rate"], decimals=0),
    )
    metric_columns[2].metric(
        "Profitable positions",
        percentage_label(summary["profitable_rate"], decimals=0),
    )
    metric_columns[3].metric(
        "Average return",
        percentage_label(summary["average_return"], decimals=2),
    )
    st.caption(
        "Good-pitch rate counts positions marked Target reached or Thesis right. "
        "Return figures use the realised percentages entered when positions are closed; "
        "use the same hypothetical risk budget across trades for comparability."
    )
    st.dataframe(
        closed.drop(columns="id"),
        width="stretch",
        hide_index=True,
        column_config={
            "Close date": st.column_config.TextColumn("Closed", width="small"),
            "Position": st.column_config.TextColumn("Position", width="medium"),
            "Product": st.column_config.TextColumn("Product", width="small"),
            "Assessment": st.column_config.TextColumn("Pitch assessment", width="small"),
            "Return (%)": st.column_config.NumberColumn(
                "Realised return",
                format="%.2f%%",
            ),
            "Status": st.column_config.TextColumn("Outcome", width="medium"),
        },
    )


def render_position_detail(selected: pd.Series) -> None:
    with st.container(border=True):
        header, status = st.columns([4, 1])
        with header:
            st.markdown(f"### {field_text(selected['trade'])}")
            context = " · ".join(
                value
                for value in [
                    field_text(selected.get("pitch_date")),
                    field_text(selected.get("product")),
                    field_text(selected.get("client")),
                ]
                if value
            )
            if context:
                st.caption(context)
        with status:
            st.markdown(f"**{field_text(selected.get('status')) or 'Open'}**")

        st.markdown("**Position taken**")
        st.write(field_text(selected.get("instrument")) or "—")
        thesis_column, catalyst_column = st.columns(2)
        with thesis_column:
            st.markdown("**Thesis**")
            st.write(field_text(selected.get("market_view")) or "—")
        with catalyst_column:
            st.markdown("**Catalyst**")
            st.write(field_text(selected.get("catalyst")) or "—")

        entry_column, target_column, stop_column, horizon_column = st.columns(4)
        position_terms = (
            (entry_column, "Entry", selected.get("entry_level")),
            (target_column, "Target", selected.get("target")),
            (stop_column, "Invalidation", selected.get("invalidation")),
            (horizon_column, "Horizon", selected.get("time_horizon")),
        )
        for column, label, value in position_terms:
            with column:
                st.caption(label)
                st.markdown(f"**{field_text(value) or '—'}**")

        if field_text(selected.get("main_risk")):
            st.markdown("**Main risk**")
            st.write(field_text(selected.get("main_risk")))


def market_timeline_frame(
    timeline: pd.DataFrame,
    key_events: pd.DataFrame,
) -> pd.DataFrame:
    columns = ["time", "priority", "event", "markets", "source", "link"]
    if timeline.empty:
        return pd.DataFrame(columns=columns)

    key_stories = (
        set(key_events["story_key"].dropna())
        if "story_key" in key_events.columns
        else set()
    )
    rows = []
    for _, row in timeline.iterrows():
        published = pd.to_datetime(row["published"], utc=True).tz_convert("Europe/London")
        rows.append(
            {
                "time": published.strftime("%d %b · %H:%M"),
                "priority": "Key" if row.get("story_key") in key_stories else "Important",
                "event": row["display_title"],
                "markets": " · ".join(row["asset_classes"]),
                "source": row["publisher"],
                "link": row["url"],
            }
        )
    return pd.DataFrame(rows, columns=columns)


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
    st.markdown(f"## {APP_NAME}")
    st.caption("Daily markets and trade-pitch workflow")
    page = st.radio(
        "Navigation",
        ["Overnight brief", "Essential charts", "Today's trade pitch", "Journal", "Sources"],
        label_visibility="collapsed",
    )
    if st.button("Refresh briefing", width="stretch"):
        load_datasets.clear()
        load_market_events.clear()
        st.rerun()
    st.markdown("---")
    st.caption("Independent project · Not investment advice")


with st.spinner("Building the source-linked overnight brief…"):
    datasets = load_datasets()
    events, important_events = load_market_events()
snapshot = build_snapshot(datasets.values())
store = load_journal_store()
with st.sidebar:
    editing_enabled = render_editor_access(store)


if page == "Overnight brief":
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">London morning</div>
          <div class="hero-title">Cross-Asset Morning Call &amp; FICC Trade Journal</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    calls = store.list_morning_calls()
    morning_call_message = st.session_state.pop("morning_call_saved", "")
    if morning_call_message:
        st.success(morning_call_message)
    render_public_morning_call_history(calls)

    st.markdown("## Market events")
    key_tab, timeline_tab = st.tabs(
        ["Top market-moving events · 24h", "Important events · 24h"]
    )
    with key_tab:
        if events.empty:
            st.info("No event currently meets the key-event materiality threshold.")
        else:
            st.caption(
                "Ranked by realised event materiality, source quality, independent "
                "confirmation and cross-asset relevance—not recency alone."
            )
            for number, (_, row) in enumerate(events.iterrows(), start=1):
                render_event(row, number)
    with timeline_tab:
        st.caption("Rolling 24 hours · distinct material stories only · newest first")
        timeline = market_timeline_frame(important_events, events)
        if timeline.empty:
            st.info("No additional important event is currently available.")
        else:
            st.dataframe(
                timeline,
                width="stretch",
                hide_index=True,
                column_config={
                    "time": st.column_config.TextColumn("London time", width="small"),
                    "priority": st.column_config.TextColumn("Priority", width="small"),
                    "event": st.column_config.TextColumn("Event", width="large"),
                    "markets": st.column_config.TextColumn("Markets", width="medium"),
                    "source": st.column_config.TextColumn("Source", width="small"),
                    "link": st.column_config.LinkColumn("Article", display_text="Open source"),
                },
            )

    st.markdown("## Latest official reference moves")
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

    render_morning_call_editor(calls, store, editing_enabled)


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
                '<div class="warning-box"><strong>Credit data boundary</strong><br>Free daily CDS indices and institutional spreads are licensed. Use HYG and LQD only as price proxies, CMDI/CISS for official stress, and a licensed terminal for executable spreads.</div>',
                unsafe_allow_html=True,
            )
    with right:
        official_chart = build_essential_chart(asset_class, datasets)
        if official_chart is not None:
            st.plotly_chart(
                official_chart.figure,
                width="stretch",
                config={"displayModeBar": False, "scrollZoom": False},
            )
            st.caption(f"{official_chart.source_name} · {official_chart.note}")
            st.link_button("Open official chart source", official_chart.source_url)
        else:
            st.markdown(
                """
                <div class="chart-fallback">
                  <div class="chart-fallback-title">Open the live market chart directly</div>
                  <div class="chart-fallback-copy">This public dashboard does not embed third-party pricing scripts. Select an instrument below to open its current or delayed chart in TradingView.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        live_instrument = st.selectbox(
            "Live chart to open",
            guide["indicators"],
            format_func=lambda indicator: f"{indicator['name']} · {indicator['symbol']}",
            key=f"live_chart_{asset_class}",
        )
        st.link_button(
            f"Open {live_instrument['symbol']} in TradingView",
            tradingview_chart_url(live_instrument["symbol"]),
            width="stretch",
        )

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
            client_type = st.selectbox("Client / audience", CLIENT_TYPES)
            custom_client = (
                st.text_input("Custom client / audience")
                if client_type == "Other"
                else ""
            )
            client = custom_client.strip() if client_type == "Other" else client_type
            if client_type == "Select a client type":
                client = ""

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
        submitted = st.form_submit_button(
            "Save pitch to journal",
            disabled=not editing_enabled,
        )

    if not editing_enabled:
        st.info("Owner access is required to save a pitch. Published positions remain visible in the Journal.")

    if submitted:
        if not client or not trade_name.strip() or not market_view.strip() or not instrument.strip():
            st.warning("Select a client and complete the trade name, thesis, and direction/instrument before saving.")
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
    st.download_button(
        "Download journal backup",
        data=journal_backup_json(store),
        file_name=f"ficc-journal-{date.today()}.json",
        mime="application/json",
    )

    pitches = store.list_pitches()
    if st.session_state.pop("pitch_deleted", False):
        st.success("Position and its monitoring history deleted.")
    render_pitch_performance(pitches)
    st.markdown("## Positions")
    if pitches.empty:
        st.info("No positions recorded yet.")
    else:
        positions = build_positions_table(pitches)
        table_selection = st.dataframe(
            positions,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="positions_table",
            column_config={
                "id": None,
                "Date": st.column_config.TextColumn("Date", width="small"),
                "Position": st.column_config.TextColumn("Position taken", width="large"),
                "Product": st.column_config.TextColumn("Product", width="small"),
                "Entry": st.column_config.TextColumn("Entry", width="small"),
                "Status": st.column_config.TextColumn("Status", width="medium"),
                "Return (%)": st.column_config.NumberColumn(
                    "Return",
                    format="%.2f%%",
                    width="small",
                ),
            },
        )
        selected_rows = table_selection.selection.rows
        if not selected_rows:
            st.caption("Click a position in the table to open its full detail and controls.")
        else:
            selected_table_row = positions.iloc[selected_rows[0]]
            pitch_id = int(selected_table_row["id"])
            selected = pitches.loc[pitches["id"] == pitch_id].iloc[0]

            for state_key, message in (
                ("pitch_edit_saved", "Position updated."),
                ("pitch_update_saved", "Market update saved."),
                ("pitch_review_saved", "Position closed and performance recorded."),
            ):
                if st.session_state.pop(state_key, False):
                    st.success(message)

            render_position_detail(selected)

            with st.expander("Edit this position"):
                with st.form(f"edit_pitch_{pitch_id}"):
                    edit_date = st.date_input(
                        "Pitch date",
                        value=pd.to_datetime(selected["pitch_date"]).date(),
                    )
                    edit_left, edit_middle, edit_right = st.columns(3)
                    with edit_left:
                        edit_trade = st.text_input(
                            "Trade name",
                            value=field_text(selected["trade"]),
                        )
                    with edit_middle:
                        edit_product = st.text_input(
                            "Asset class / product",
                            value=field_text(selected["product"]),
                        )
                    with edit_right:
                        edit_client = st.text_input(
                            "Client / audience",
                            value=field_text(selected["client"]),
                        )
                    edit_instrument = st.text_area(
                        "Position taken",
                        value=field_text(selected["instrument"]),
                        height=80,
                    )
                    edit_view = st.text_area(
                        "Thesis",
                        value=field_text(selected["market_view"]),
                        height=100,
                    )
                    edit_catalyst = st.text_area(
                        "Catalyst",
                        value=field_text(selected["catalyst"]),
                        height=80,
                    )
                    edit_level, edit_target_column, edit_stop, edit_horizon = st.columns(4)
                    with edit_level:
                        edit_entry = st.text_input(
                            "Entry level",
                            value=field_text(selected["entry_level"]),
                        )
                    with edit_target_column:
                        edit_target = st.text_input(
                            "Target",
                            value=field_text(selected["target"]),
                        )
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
                    edit_risk = st.text_area(
                        "Main risks",
                        value=field_text(selected["main_risk"]),
                        height=80,
                    )
                    edit_relevance = st.text_area(
                        "Client relevance",
                        value=field_text(selected["client_relevance"]),
                        height=80,
                    )
                    edit_question = st.text_input(
                        "Client question",
                        value=field_text(selected["closing_question"]),
                    )
                    edit_submitted = st.form_submit_button(
                        "Save position changes",
                        disabled=not editing_enabled,
                    )
                if edit_submitted:
                    if not edit_trade.strip() or not edit_view.strip() or not edit_instrument.strip():
                        st.warning(
                            "Complete the trade name, thesis and position before saving."
                        )
                    else:
                        store.update_pitch(
                            pitch_id,
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

            is_closed = field_text(selected.get("status")) in CLOSED_PITCH_STATUSES
            if not is_closed:
                with st.expander("Add a monitoring update"):
                    with st.form(f"performance_update_{pitch_id}", clear_on_submit=True):
                        update_left, update_middle, update_right = st.columns(3)
                        with update_left:
                            update_date = st.date_input("Update date", value=date.today())
                        with update_middle:
                            current_level = st.text_input("Current market level")
                        with update_right:
                            performance = st.text_input("Performance since entry")
                        update_status = st.selectbox("Status", ["Open", "Monitoring"])
                        update_comment = st.text_area("Market update", height=90)
                        update_submitted = st.form_submit_button(
                            "Save market update",
                            disabled=not editing_enabled,
                        )
                    if update_submitted:
                        store.add_pitch_update(
                            pitch_id,
                            update_date=str(update_date),
                            current_level=current_level,
                            performance=performance,
                            status=update_status,
                            comment=update_comment,
                        )
                        st.session_state["pitch_update_saved"] = True
                        st.rerun()

            updates = store.list_pitch_updates(pitch_id)
            if not updates.empty:
                with st.expander(f"View monitoring history ({len(updates)})"):
                    st.dataframe(
                        updates[[
                            "update_date",
                            "current_level",
                            "performance",
                            "status",
                            "comment",
                        ]],
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

            with st.expander("Close position and record outcome"):
                current_status = field_text(selected.get("status"))
                final_status_index = (
                    list(CLOSED_PITCH_STATUSES).index(current_status)
                    if current_status in CLOSED_PITCH_STATUSES
                    else 0
                )
                existing_close_date = pd.to_datetime(
                    selected.get("closed_date"),
                    errors="coerce",
                )
                close_date_value = (
                    existing_close_date.date()
                    if pd.notna(existing_close_date)
                    else date.today()
                )
                existing_return = selected.get("realized_return_pct")
                return_text = (
                    ""
                    if existing_return is None or pd.isna(existing_return)
                    else f"{float(existing_return):g}"
                )
                with st.form(f"review_form_{pitch_id}"):
                    close_left, close_middle, close_right = st.columns(3)
                    with close_left:
                        final_status = st.selectbox(
                            "Outcome",
                            list(CLOSED_PITCH_STATUSES),
                            index=final_status_index,
                        )
                    with close_middle:
                        close_date = st.date_input(
                            "Close date",
                            value=close_date_value,
                        )
                    with close_right:
                        realized_return = st.text_input(
                            "Realised return (%)",
                            value=return_text,
                            placeholder="e.g. +1.50 or -0.75",
                        )
                    maximum_adverse_move = st.text_input(
                        "Maximum adverse movement",
                        value=field_text(selected.get("maximum_adverse_move")),
                    )
                    catalyst_outcome = st.text_area(
                        "What happened to the catalyst?",
                        value=field_text(selected.get("catalyst_outcome")),
                    )
                    thesis_review = st.text_area(
                        "Final review",
                        value=field_text(selected.get("thesis_review")),
                        height=120,
                    )
                    reviewed = st.form_submit_button(
                        "Close position",
                        disabled=not editing_enabled,
                    )
                if reviewed:
                    try:
                        parsed_return = float(
                            realized_return.strip().replace("%", "").replace(",", ".")
                        )
                    except ValueError:
                        st.warning("Enter the realised return as a number, such as 1.50 or -0.75.")
                    else:
                        store.review_pitch(
                            pitch_id,
                            status=final_status,
                            performance=field_text(selected.get("performance")),
                            maximum_adverse_move=maximum_adverse_move,
                            catalyst_outcome=catalyst_outcome,
                            thesis_review=thesis_review,
                            closed_date=str(close_date),
                            realized_return_pct=parsed_return,
                        )
                        st.session_state["pitch_review_saved"] = True
                        st.rerun()

            with st.expander("Delete this position"):
                st.warning(
                    "This permanently removes the position and all of its monitoring "
                    "updates. This action cannot be undone."
                )
                delete_confirmed = st.checkbox(
                    f"I confirm that I want to delete “{field_text(selected['trade'])}”.",
                    key=f"confirm_delete_pitch_{pitch_id}",
                )
                if st.button(
                    "Permanently delete position",
                    disabled=not delete_confirmed or not editing_enabled,
                    key=f"delete_pitch_{pitch_id}",
                ):
                    try:
                        deleted = delete_pitch_safely(store, pitch_id)
                    except Exception:
                        deleted = False
                    if deleted:
                        st.session_state["pitch_deleted"] = True
                        st.rerun()
                    st.error(
                        "The position could not be deleted. Refresh the journal and try again."
                    )


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
        - **Official feeds:** Federal Reserve, ECB, Bank of England, Reserve Bank of Australia, U.S. Bureau of Labor Statistics and U.S. Bureau of Economic Analysis releases are collected directly.
        - **Event discovery:** separate searches monitor central-bank decisions, major macro data, geopolitical shocks, government policy, energy disruptions, credit stress and confirmed cross-asset reactions.
        - **Free-access policy:** paywalled publishers are excluded. Events come from official feeds or a conservative list of publishers normally readable without a subscription; access can still vary by country.
        - **Top-event ranking:** realised event materiality, source quality, independent-publisher confirmation and cross-asset relevance determine up to five events from a rolling 24-hour window. Recency is a minor input; previews, routine market round-ups, low-volatility headlines and single-company earnings receive strong penalties.
        - **Story diversity:** duplicate coverage is grouped into one underlying story, and the selection limits repeated exposure to one asset class. If fewer than five stories clear the threshold, the app shows fewer rather than adding noise.
        - **Important-event timeline:** material stories remain visible for 24 hours even when newer headlines displace them from the five key events; lower-signal coverage is filtered out.
        - **No invented causality:** publication time and market charts must be checked before linking an event to a move.
        - **Copyright discipline:** only the headline, publisher and link are displayed; articles are not reproduced.
        """
    )
    st.markdown("### Data health")
    health = metadata_health(datasets)
    if not health.empty:
        st.dataframe(health, width="stretch", hide_index=True)

    st.markdown("### Journal storage")
    if store.persistent:
        st.success("Saved calls, pitches and performance updates use persistent PostgreSQL storage.")
    else:
        st.warning(
            "This deployment is using local SQLite. Add DATABASE_URL to Streamlit secrets "
            "before relying on the journal across app restarts or redeployments."
        )

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
    f"{APP_NAME} · Refreshed {datetime.now(ZoneInfo('Europe/London')).strftime('%d %b %Y %H:%M London')} · "
    "Facts must be verified before publication · Not investment advice"
)
