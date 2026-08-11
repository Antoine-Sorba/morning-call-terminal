from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go

from .models import MarketDataset


INK = "#18221d"
GREEN = "#123f32"
COLORS = (GREEN, "#5f8f75", "#c28b2c", "#a34f3f", "#5c6f91")


@dataclass(frozen=True)
class EssentialChart:
    figure: go.Figure
    source_name: str
    source_url: str
    note: str


def _available_dataset(
    datasets: dict[str, MarketDataset],
    key: str,
) -> MarketDataset | None:
    dataset = datasets.get(key)
    if dataset is None or not dataset.available:
        return None
    required = {"date", "instrument", "value"}
    return dataset if required.issubset(dataset.frame.columns) else None


def _clean_history(
    dataset: MarketDataset,
    instruments: tuple[str, ...],
    observations: int,
) -> pd.DataFrame:
    frame = dataset.frame.loc[
        dataset.frame["instrument"].isin(instruments),
        ["date", "instrument", "value"],
    ].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna().drop_duplicates(["date", "instrument"], keep="last")
    if frame.empty:
        return frame
    dates = frame["date"].drop_duplicates().sort_values().tail(observations)
    return frame.loc[frame["date"].isin(dates)].sort_values(["date", "instrument"])


def _line_figure(
    frame: pd.DataFrame,
    *,
    title: str,
    subtitle: str,
    yaxis_title: str,
) -> go.Figure:
    figure = go.Figure()
    for index, instrument in enumerate(frame.columns):
        values = frame[instrument].dropna()
        if values.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=values.index,
                y=values,
                name=str(instrument),
                mode="lines",
                line={"color": COLORS[index % len(COLORS)], "width": 2.4},
                hovertemplate=f"{instrument}<br>%{{x|%d %b %Y}}<br>%{{y:.2f}}<extra></extra>",
            )
        )
        figure.add_trace(
            go.Scatter(
                x=[values.index[-1]],
                y=[values.iloc[-1]],
                mode="markers",
                marker={"color": COLORS[index % len(COLORS)], "size": 8},
                showlegend=False,
                hoverinfo="skip",
            )
        )

    figure.update_layout(
        title={
            "text": f"<b>{title}</b><br><sup>{subtitle}</sup>",
            "x": 0.02,
            "xanchor": "left",
            "font": {"color": INK, "size": 20},
        },
        height=520,
        margin={"l": 30, "r": 20, "t": 90, "b": 35},
        paper_bgcolor="#fffef9",
        plot_bgcolor="#fffef9",
        font={"color": INK, "family": "Arial, sans-serif"},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.02, "x": 0.01, "title": None},
        xaxis={
            "showgrid": False,
            "showline": True,
            "linecolor": "#d6dad1",
            "fixedrange": True,
        },
        yaxis={
            "title": yaxis_title,
            "gridcolor": "#e8e9e3",
            "zeroline": False,
            "fixedrange": True,
        },
    )
    return figure


def build_essential_chart(
    asset_class: str,
    datasets: dict[str, MarketDataset],
) -> EssentialChart | None:
    """Build recruiter-safe native charts from official historical datasets."""

    if asset_class == "Rates":
        dataset = _available_dataset(datasets, "ust_curve")
        if dataset is None:
            return None
        history = _clean_history(dataset, ("2Y", "5Y", "10Y", "30Y"), 120)
        pivot = history.pivot(index="date", columns="instrument", values="value")
        if pivot.empty:
            return None
        return EssentialChart(
            figure=_line_figure(
                pivot,
                title="U.S. Treasury yield curve history",
                subtitle="Official daily closing yields · latest 120 observations",
                yaxis_title="Yield (%)",
            ),
            source_name=dataset.metadata.source_name,
            source_url=dataset.metadata.source_url,
            note=dataset.metadata.delay,
        )

    if asset_class == "FX":
        dataset = _available_dataset(datasets, "ecb_fx")
        if dataset is None:
            return None
        history = _clean_history(dataset, ("EUR/USD", "GBP/USD", "USD/JPY"), 90)
        pivot = history.pivot(index="date", columns="instrument", values="value").sort_index()
        if pivot.empty:
            return None
        pivot = pivot.ffill().dropna(how="all")
        starting_values = pivot.bfill().iloc[0].replace(0, pd.NA)
        rebased = pivot.divide(starting_values).multiply(100).dropna(how="all", axis=1)
        if rebased.empty:
            return None
        return EssentialChart(
            figure=_line_figure(
                rebased,
                title="G10 FX reference-rate performance",
                subtitle="Official ECB reference rates · rebased to 100",
                yaxis_title="Index (start = 100)",
            ),
            source_name=dataset.metadata.source_name,
            source_url=dataset.metadata.source_url,
            note=dataset.metadata.delay,
        )

    if asset_class == "Commodities":
        dataset = _available_dataset(datasets, "eia_energy")
        if dataset is None:
            return None
        history = _clean_history(dataset, ("WTI", "Brent"), 120)
        pivot = history.pivot(index="date", columns="instrument", values="value")
        if pivot.empty:
            return None
        return EssentialChart(
            figure=_line_figure(
                pivot,
                title="Crude-oil spot-price history",
                subtitle="Official EIA observations · latest 120 observations",
                yaxis_title="U.S. dollars per barrel",
            ),
            source_name=dataset.metadata.source_name,
            source_url=dataset.metadata.source_url,
            note=dataset.metadata.delay,
        )

    return None
