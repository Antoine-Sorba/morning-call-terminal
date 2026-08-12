from ficc_terminal.storage import (
    JournalStore,
    create_journal_store,
    is_streamlit_cloud_runtime,
    journal_writes_are_durable,
)


def test_factory_uses_local_sqlite_without_a_cloud_database_url(tmp_path) -> None:
    store = create_journal_store(database_url="", sqlite_path=tmp_path / "journal.db")
    assert isinstance(store, JournalStore)
    assert not store.persistent
    store.close()


def test_morning_call_history_keeps_one_entry_per_date(tmp_path) -> None:
    store = JournalStore(tmp_path / "journal.db")
    first_id = store.save_morning_call(
        "2026-08-10",
        "Initial morning call.",
        "",
        "",
    )
    store.save_morning_call(
        "2026-08-11",
        "The latest morning call.",
        "",
        "",
    )
    updated_id = store.save_morning_call(
        "2026-08-10",
        "Revised morning call.",
        "",
        "",
    )

    calls = store.list_morning_calls()
    assert updated_id == first_id
    assert len(calls) == 2
    assert calls["call_date"].tolist() == ["2026-08-11", "2026-08-10"]
    assert calls.loc[calls["call_date"] == "2026-08-10", "summary"].iloc[0] == (
        "Revised morning call."
    )
    store.close()


def test_morning_calls_and_positions_survive_store_restart(tmp_path) -> None:
    database = tmp_path / "journal.db"
    first = JournalStore(database)
    first.save_morning_call("2026-08-11", "Yesterday's morning call.", "", "")
    first.save_pitch(
        {
            "client": "Macro hedge fund",
            "trade": "Pay US 10Y",
            "market_view": "Yields may rise.",
            "instrument": "Pay fixed in ten-year swaps.",
        },
        "2026-08-11",
    )
    first.close()

    restarted = JournalStore(database)
    assert restarted.list_morning_calls().iloc[0]["summary"] == (
        "Yesterday's morning call."
    )
    assert restarted.list_pitches().iloc[0]["trade"] == "Pay US 10Y"
    restarted.close()


def test_cloud_runtime_rejects_ephemeral_sqlite_writes(tmp_path) -> None:
    store = JournalStore(tmp_path / "journal.db")
    environment = {"STREAMLIT_SHARING_MODE": "true"}

    assert is_streamlit_cloud_runtime(
        environment=environment,
        working_directory="/workspace/project",
    )
    assert not journal_writes_are_durable(
        store,
        environment=environment,
        working_directory="/workspace/project",
    )
    store.close()


def test_local_sqlite_writes_remain_available_for_development(tmp_path) -> None:
    store = JournalStore(tmp_path / "journal.db")

    assert not is_streamlit_cloud_runtime(
        environment={},
        working_directory="/workspace/project",
    )
    assert journal_writes_are_durable(
        store,
        environment={},
        working_directory="/workspace/project",
    )
    store.close()


def test_pitch_journal_round_trip(tmp_path) -> None:
    store = JournalStore(tmp_path / "journal.db")
    pitch = {
        "client": "Macro hedge fund",
        "client_problem": "Duration exposure",
        "trade": "US 2s10s steepener",
        "product": "USD swaps",
        "market_view": "The long end may underperform the front end.",
        "instrument": "Receive 2Y and pay 10Y swaps.",
        "entry_level": "-10 bp",
        "target": "+5 bp",
        "invalidation": "Curve below -20 bp",
        "time_horizon": "Six weeks",
        "catalyst": "US inflation data",
        "main_risk": "Growth shock",
        "client_relevance": "Curve exposure",
        "closing_question": "How is the curve risk currently hedged?",
    }
    pitch_id = store.save_pitch(pitch, "2026-08-11")
    frame = store.list_pitches()
    assert frame.iloc[0]["id"] == pitch_id
    assert frame.iloc[0]["trade"] == "US 2s10s steepener"
    store.review_pitch(
        pitch_id,
        status="Closed — thesis wrong",
        performance="-5 bp",
        maximum_adverse_move="-8 bp",
        catalyst_outcome="The expected catalyst did not occur.",
        thesis_review="I over-weighted supply and under-weighted growth risk.",
        closed_date="2026-08-18",
        realized_return_pct=-1.25,
    )
    reviewed = store.list_pitches().iloc[0]
    assert reviewed["status"] == "Closed — thesis wrong"
    assert reviewed["closed_date"] == "2026-08-18"
    assert reviewed["realized_return_pct"] == -1.25


def test_daily_pitch_updates_are_kept_as_history(tmp_path) -> None:
    store = JournalStore(tmp_path / "journal.db")
    pitch_id = store.save_pitch(
        {
            "client": "Credit fund",
            "trade": "Buy iTraxx Main protection",
            "product": "Credit index CDS",
            "market_view": "Credit spreads may widen.",
            "instrument": "Buy five-year protection.",
            "entry_level": "55 bp",
            "target": "65 bp",
            "invalidation": "Below 50 bp",
            "time_horizon": "One month",
            "catalyst": "Risk event",
            "main_risk": "De-escalation",
            "client_relevance": "Portfolio hedge",
        },
        "2026-08-11",
    )
    update_id = store.add_pitch_update(
        pitch_id,
        update_date="2026-08-12",
        current_level="58 bp",
        performance="+3 bp",
        status="Monitoring",
        comment="Spreads widened after the event.",
    )
    updates = store.list_pitch_updates(pitch_id)
    assert updates.iloc[0]["id"] == update_id
    assert updates.iloc[0]["current_level"] == "58 bp"
    pitch = store.list_pitches().iloc[0]
    assert pitch["status"] == "Monitoring"
    assert pitch["performance"] == "+3 bp"


def test_saved_pitch_can_be_edited_without_losing_updates(tmp_path) -> None:
    store = JournalStore(tmp_path / "journal.db")
    original = {
        "client": "Macro fund",
        "trade": "Pay US 10Y",
        "product": "USD swaps",
        "market_view": "Yields may rise.",
        "instrument": "Pay fixed in ten-year swaps.",
        "entry_level": "4.20%",
        "target": "4.40%",
        "invalidation": "4.10%",
        "time_horizon": "Two weeks",
        "catalyst": "Inflation data",
        "main_risk": "Growth shock",
    }
    pitch_id = store.save_pitch(original, "2026-08-11")
    store.add_pitch_update(
        pitch_id,
        update_date="2026-08-12",
        current_level="4.25%",
        performance="+5 bp",
        status="Monitoring",
        comment="Yield moved higher.",
    )
    edited = original | {"trade": "Pay US 10Y swap", "target": "4.45%"}
    assert store.update_pitch(pitch_id, edited, "2026-08-11")
    saved = store.list_pitches().iloc[0]
    assert saved["trade"] == "Pay US 10Y swap"
    assert saved["target"] == "4.45%"
    assert len(store.list_pitch_updates(pitch_id)) == 1


def test_pitch_can_be_deleted_with_its_monitoring_history(tmp_path) -> None:
    store = JournalStore(tmp_path / "journal.db")
    pitch_id = store.save_pitch(
        {
            "client": "Macro hedge fund",
            "trade": "US 2s10s steepener",
            "market_view": "The curve may steepen.",
            "instrument": "Receive two-year and pay ten-year swaps.",
        },
        "2026-08-11",
    )
    store.add_pitch_update(
        pitch_id,
        update_date="2026-08-12",
        current_level="-5 bp",
        performance="+2 bp",
        status="Monitoring",
        comment="The curve steepened.",
    )

    assert store.delete_pitch(pitch_id)
    assert store.list_pitches().empty
    assert store.list_pitch_updates(pitch_id).empty
    assert not store.delete_pitch(pitch_id)
    store.close()


def test_two_store_instances_can_write_without_locking(tmp_path) -> None:
    database = tmp_path / "journal.db"
    first = JournalStore(database)
    second = JournalStore(database)
    pitch_id = first.save_pitch(
        {
            "client": "Asset manager",
            "trade": "Receive front-end rates",
            "market_view": "Policy expectations are too restrictive.",
            "instrument": "Receive two-year swaps.",
        },
        "2026-08-11",
    )
    second.add_pitch_update(
        pitch_id,
        update_date="2026-08-12",
        current_level="3.90%",
        performance="+2 bp",
        status="Monitoring",
        comment="The position remains open.",
    )
    assert len(first.list_pitch_updates(pitch_id)) == 1
    first.close()
    second.close()
