from ficc_terminal.storage import JournalStore


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
    )
    reviewed = store.list_pitches().iloc[0]
    assert reviewed["status"] == "Closed — thesis wrong"


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
