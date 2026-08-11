import pandas as pd

from ficc_terminal.charts import build_essential_chart
from ficc_terminal.models import MarketDataset, SourceMetadata
from ficc_terminal.widgets import tradingview_chart_url


def market_dataset(key: str, rows: list[dict[str, object]]) -> MarketDataset:
    return MarketDataset(
        key=key,
        frame=pd.DataFrame(rows),
        metadata=SourceMetadata(
            source_name="Official test source",
            series_name="Test series",
            source_url="https://example.com/official",
            frequency="Daily",
            unit="Test units",
            delay="Official close",
        ),
    )


def test_rates_chart_uses_official_history() -> None:
    rows = [
        {"date": date, "instrument": instrument, "value": value}
        for date, values in (
            ("2026-08-10", {"2Y": 4.1, "5Y": 4.2, "10Y": 4.3, "30Y": 4.5}),
            ("2026-08-11", {"2Y": 4.2, "5Y": 4.3, "10Y": 4.4, "30Y": 4.6}),
        )
        for instrument, value in values.items()
    ]
    chart = build_essential_chart("Rates", {"ust_curve": market_dataset("ust_curve", rows)})
    assert chart is not None
    assert chart.source_name == "Official test source"
    assert "Treasury" in chart.figure.layout.title.text
    assert {trace.name for trace in chart.figure.data if trace.showlegend is not False} == {
        "2Y",
        "5Y",
        "10Y",
        "30Y",
    }


def test_fx_chart_rebases_different_currency_scales() -> None:
    rows = [
        {"date": "2026-08-10", "instrument": "EUR/USD", "value": 1.10},
        {"date": "2026-08-11", "instrument": "EUR/USD", "value": 1.11},
        {"date": "2026-08-10", "instrument": "USD/JPY", "value": 150.0},
        {"date": "2026-08-11", "instrument": "USD/JPY", "value": 151.0},
    ]
    chart = build_essential_chart("FX", {"ecb_fx": market_dataset("ecb_fx", rows)})
    assert chart is not None
    line_traces = [trace for trace in chart.figure.data if trace.showlegend is not False]
    assert all(round(float(trace.y[0]), 6) == 100 for trace in line_traces)


def test_chart_falls_back_cleanly_when_no_redistributable_history_exists() -> None:
    assert build_essential_chart("Credit", {}) is None
    assert build_essential_chart("Equities", {}) is None


def test_tradingview_link_encodes_the_exact_symbol() -> None:
    assert tradingview_chart_url("NYMEX:CL1!").endswith("NYMEX%3ACL1%21")
