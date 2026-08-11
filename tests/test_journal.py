import pandas as pd

from ficc_terminal.journal import (
    build_closed_performance,
    build_positions_table,
    performance_summary,
)


def sample_pitches() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": 1,
                "pitch_date": "2026-08-01",
                "closed_date": "2026-08-05",
                "trade": "Long USD/JPY",
                "product": "FX",
                "instrument": "Buy USD/JPY",
                "entry_level": "145.00",
                "status": "Target reached",
                "realized_return_pct": 2.0,
            },
            {
                "id": 2,
                "pitch_date": "2026-08-02",
                "closed_date": "2026-08-06",
                "trade": "Receive US 2Y",
                "product": "Rates",
                "instrument": "Receive two-year swaps",
                "entry_level": "4.10%",
                "status": "Closed — thesis wrong",
                "realized_return_pct": -1.0,
            },
            {
                "id": 3,
                "pitch_date": "2026-08-03",
                "closed_date": None,
                "trade": "Buy credit protection",
                "product": "Credit",
                "instrument": "Buy five-year index protection",
                "entry_level": "55 bp",
                "status": "Monitoring",
                "realized_return_pct": None,
            },
        ]
    )


def test_positions_table_is_concise_and_uses_the_position_taken() -> None:
    positions = build_positions_table(sample_pitches())
    assert positions.columns.tolist() == [
        "id",
        "Date",
        "Position",
        "Product",
        "Entry",
        "Status",
        "Return (%)",
    ]
    assert positions.iloc[0]["Position"] == "Buy USD/JPY"


def test_closed_pitch_performance_and_summary() -> None:
    closed = build_closed_performance(sample_pitches())
    assert len(closed) == 2
    assert closed["Assessment"].tolist() == ["Needs review", "Good pitch"]

    summary = performance_summary(closed)
    assert summary["closed_count"] == 2
    assert summary["good_pitch_rate"] == 50.0
    assert summary["profitable_rate"] == 50.0
    assert summary["average_return"] == 0.5
