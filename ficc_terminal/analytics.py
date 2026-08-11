from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

from .models import MarketDataset


ASSET_CLASS = {
    "ust_curve": "Rates",
    "ecb_curve": "Rates",
    "boe_curve": "Rates",
    "sofr": "Rates",
    "ecb_fx": "FX",
    "eia_energy": "Commodities",
    "cftc_positions": "Positioning",
    "bls_macro": "Macro",
}


def add_changes(frame: pd.DataFrame, change_kind: str) -> pd.DataFrame:
    result = frame.copy().sort_values(["instrument", "date"])
    if change_kind == "bp":
        result["change"] = result.groupby("instrument")["value"].diff() * 100
        result["change_unit"] = "bp"
    elif change_kind == "level":
        result["change"] = result.groupby("instrument")["value"].diff()
        result["change_unit"] = "units"
    else:
        result["change"] = result.groupby("instrument")["value"].pct_change(fill_method=None) * 100
        result["change_unit"] = "%"
    return result


def latest_change(frame: pd.DataFrame, instrument: str, change_kind: str) -> dict | None:
    subset = frame.loc[frame["instrument"] == instrument].copy()
    subset["date"] = pd.to_datetime(subset["date"], errors="coerce")
    subset = subset.dropna(subset=["date", "value"]).sort_values("date")
    if subset.empty:
        return None
    changed = add_changes(subset, change_kind)
    latest = changed.iloc[-1]
    history = changed["change"].dropna()
    z_score = 0.0
    if len(history) >= 10 and history.std(ddof=0) > 0 and pd.notna(latest["change"]):
        z_score = float((latest["change"] - history.mean()) / history.std(ddof=0))
    return {
        "instrument": instrument,
        "date": latest["date"],
        "level": float(latest["value"]),
        "change": float(latest["change"]) if pd.notna(latest["change"]) else np.nan,
        "change_unit": latest["change_unit"],
        "z_score": z_score,
    }


def importance_score(z_score: float, related_confirmation: int = 0, event_near: bool = False) -> float:
    """Simple transparent prioritisation score, capped at 100.

    Absolute historical z-score supplies 80% of the score. Cross-market
    confirmation and proximity to a user-verified event can each add 10 points.
    """

    base = min(abs(float(z_score)), 3.0) / 3.0 * 80.0
    confirmation = min(max(int(related_confirmation), 0), 2) * 5.0
    event = 10.0 if event_near else 0.0
    return round(min(base + confirmation + event, 100.0), 1)


def build_snapshot(datasets: Iterable[MarketDataset]) -> pd.DataFrame:
    rows = []
    for dataset in datasets:
        if not dataset.available or "instrument" not in dataset.frame:
            continue
        change_kind = "bp" if dataset.key in {"ust_curve", "ecb_curve", "boe_curve", "sofr"} else "%"
        if dataset.key in {"cftc_positions", "bls_macro"}:
            change_kind = "level"
        for instrument in dataset.frame["instrument"].dropna().unique():
            result = latest_change(dataset.frame, instrument, change_kind)
            if result is None:
                continue
            result.update(
                {
                    "asset_class": ASSET_CLASS.get(dataset.key, "Other"),
                    "source": dataset.metadata.source_name,
                    "source_url": dataset.metadata.source_url,
                    "frequency": dataset.metadata.frequency,
                    "stale": dataset.stale,
                    "score": importance_score(result["z_score"]),
                }
            )
            rows.append(result)
    if not rows:
        return pd.DataFrame(
            columns=[
                "asset_class",
                "instrument",
                "date",
                "level",
                "change",
                "change_unit",
                "z_score",
                "score",
                "source",
                "source_url",
                "frequency",
                "stale",
            ]
        )
    return pd.DataFrame(rows).sort_values(["score", "asset_class"], ascending=[False, True])


def curve_slope(frame: pd.DataFrame, short: str = "2Y", long: str = "10Y") -> pd.DataFrame:
    pivot = frame.pivot_table(index="date", columns="instrument", values="value", aggfunc="last")
    if short not in pivot or long not in pivot:
        return pd.DataFrame(columns=["date", "instrument", "value"])
    result = ((pivot[long] - pivot[short]) * 100).rename("value").reset_index()
    result["instrument"] = f"{short}{long} slope"
    return result[["date", "instrument", "value"]].dropna()


def find_row(
    snapshot: pd.DataFrame,
    instrument: str,
    source_contains: str | None = None,
) -> pd.Series | None:
    matches = snapshot.loc[snapshot["instrument"] == instrument]
    if source_contains:
        matches = matches.loc[
            matches["source"].str.contains(source_contains, case=False, na=False)
        ]
    return None if matches.empty else matches.iloc[0]


def potential_themes(snapshot: pd.DataFrame) -> list[dict[str, str]]:
    """Return rule-based hypotheses, never asserted causal explanations."""

    themes: list[dict[str, str]] = []
    us2 = find_row(snapshot, "2Y", "Treasury")
    us10 = find_row(snapshot, "10Y", "Treasury")
    eurusd = find_row(snapshot, "EUR/USD")
    wti = find_row(snapshot, "WTI")

    if us2 is not None and us10 is not None:
        two_move, ten_move = us2.get("change"), us10.get("change")
        if pd.notna(two_move) and pd.notna(ten_move):
            if two_move > 5 and ten_move > 5:
                evidence = f"US 2Y {two_move:+.0f} bp and US 10Y {ten_move:+.0f} bp."
                if eurusd is not None and pd.notna(eurusd.get("change")) and eurusd["change"] < 0:
                    evidence += f" EUR/USD {eurusd['change']:+.2f}%."
                themes.append(
                    {
                        "theme": "Potential hawkish US rates repricing",
                        "evidence": evidence,
                        "verification": "Check the latest Fed communication and official US data release before attributing cause.",
                    }
                )
            slope_move = ten_move - two_move
            if abs(slope_move) >= 3:
                shape = "steepening" if slope_move > 0 else "flattening"
                themes.append(
                    {
                        "theme": f"Potential US curve {shape}",
                        "evidence": f"The 10Y move exceeded the 2Y move by {slope_move:+.0f} bp.",
                        "verification": "Confirm the curve move against supply, inflation and growth headlines.",
                    }
                )

    if wti is not None and pd.notna(wti.get("change")) and abs(wti["change"]) >= 2:
        direction = "upside" if wti["change"] > 0 else "downside"
        themes.append(
            {
                "theme": f"Potential energy-driven inflation {direction}",
                "evidence": f"Official EIA WTI spot series changed {wti['change']:+.2f}%.",
                "verification": "Check EIA balances and official supply developments; the spot series is not a live futures quote.",
            }
        )

    if not themes and not snapshot.empty:
        top = snapshot.dropna(subset=["change"]).head(3)
        if not top.empty:
            evidence = "; ".join(
                f"{row.instrument} {row.change:+.2f}{row.change_unit}" for row in top.itertuples()
            )
            themes.append(
                {
                    "theme": "No single cross-asset theme is confirmed",
                    "evidence": f"Largest standardised official moves: {evidence}.",
                    "verification": "Review official releases and reputable market reporting before assigning a common driver.",
                }
            )
    return themes[:4]


def format_market_fact(row: pd.Series) -> str:
    change = row.get("change")
    change_text = "change unavailable"
    if pd.notna(change):
        change_text = f"{change:+.1f} {row.get('change_unit', '')}"
    level = row.get("level")
    level_text = "level unavailable" if not math.isfinite(float(level)) else f"{float(level):,.4g}"
    date_text = pd.to_datetime(row.get("date")).strftime("%d %b %Y")
    stale_text = " (cached/stale)" if row.get("stale") else ""
    return f"{row['instrument']} was {level_text}, {change_text}, on {date_text}{stale_text}."


def generated_morning_call(snapshot: pd.DataFrame, themes: list[dict[str, str]]) -> str:
    if snapshot.empty:
        return (
            "Official feeds are currently unavailable. No market facts have been generated. "
            "Check the source panel and do not publish a morning call until the data are verified."
        )
    facts = [format_market_fact(row) for _, row in snapshot.dropna(subset=["change"]).head(5).iterrows()]
    theme_text = themes[0]["theme"] if themes else "No common cross-asset theme is confirmed"
    return (
        "Good morning. The largest verified moves in the latest official data were: "
        + " ".join(facts)
        + f" The dashboard flags '{theme_text}' as a hypothesis, not a proven cause. "
        "Before the call, verify the driver using the linked central-bank, statistical-agency or government release. "
        "For the client conversation, focus on the relevant exposure, the cleanest FICC hedge or expression, and the condition that would invalidate the idea."
    )
