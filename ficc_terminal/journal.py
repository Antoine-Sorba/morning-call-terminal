from __future__ import annotations

import pandas as pd


CLOSED_PITCH_STATUSES = (
    "Target reached",
    "Stop / invalidation reached",
    "Closed — thesis right",
    "Closed — thesis wrong",
    "Closed — risk limit",
    "Expired",
)

GOOD_PITCH_STATUSES = {
    "Target reached",
    "Closed — thesis right",
}

WEAK_PITCH_STATUSES = {
    "Stop / invalidation reached",
    "Closed — thesis wrong",
}


def build_positions_table(pitches: pd.DataFrame) -> pd.DataFrame:
    columns = ["id", "Date", "Position", "Product", "Entry", "Status", "Return (%)"]
    if pitches.empty:
        return pd.DataFrame(columns=columns)

    frame = pitches.copy().reset_index(drop=True)
    recorded_returns = (
        frame["realized_return_pct"]
        if "realized_return_pct" in frame
        else pd.Series(index=frame.index, dtype=float)
    )
    frame["Return (%)"] = pd.to_numeric(recorded_returns, errors="coerce")
    frame = frame.rename(
        columns={
            "pitch_date": "Date",
            "instrument": "Position",
            "product": "Product",
            "entry_level": "Entry",
            "status": "Status",
        }
    )
    return frame[columns]


def build_closed_performance(pitches: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "id",
        "Close date",
        "Position",
        "Product",
        "Assessment",
        "Return (%)",
        "Status",
    ]
    if pitches.empty:
        return pd.DataFrame(columns=columns)

    closed = pitches.loc[pitches["status"].isin(CLOSED_PITCH_STATUSES)].copy()
    if closed.empty:
        return pd.DataFrame(columns=columns)

    closed["Assessment"] = "Unclassified"
    closed.loc[closed["status"].isin(GOOD_PITCH_STATUSES), "Assessment"] = "Good pitch"
    closed.loc[closed["status"].isin(WEAK_PITCH_STATUSES), "Assessment"] = "Needs review"
    recorded_returns = (
        closed["realized_return_pct"]
        if "realized_return_pct" in closed
        else pd.Series(index=closed.index, dtype=float)
    )
    closed["Return (%)"] = pd.to_numeric(recorded_returns, errors="coerce")
    closed = closed.rename(
        columns={
            "closed_date": "Close date",
            "trade": "Position",
            "product": "Product",
            "status": "Status",
        }
    )
    return closed[columns].sort_values(
        ["Close date", "id"],
        ascending=[False, False],
        na_position="last",
    )


def performance_summary(closed: pd.DataFrame) -> dict[str, float | int | None]:
    if closed.empty:
        return {
            "closed_count": 0,
            "good_pitch_rate": None,
            "profitable_rate": None,
            "average_return": None,
        }

    assessed = closed.loc[closed["Assessment"].isin(["Good pitch", "Needs review"])]
    recorded_returns = pd.to_numeric(closed["Return (%)"], errors="coerce").dropna()
    return {
        "closed_count": int(len(closed)),
        "good_pitch_rate": (
            float((assessed["Assessment"] == "Good pitch").mean() * 100)
            if not assessed.empty
            else None
        ),
        "profitable_rate": (
            float((recorded_returns > 0).mean() * 100)
            if not recorded_returns.empty
            else None
        ),
        "average_return": (
            float(recorded_returns.mean())
            if not recorded_returns.empty
            else None
        ),
    }
