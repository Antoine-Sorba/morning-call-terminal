import pandas as pd

from ficc_terminal.analytics import curve_slope, importance_score, latest_change


def test_basis_point_change() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-07", "2026-08-10"]),
            "instrument": ["10Y", "10Y"],
            "value": [4.65, 4.72],
        }
    )
    result = latest_change(frame, "10Y", "bp")
    assert result is not None
    assert round(result["change"]) == 7


def test_curve_slope() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-10", "2026-08-10"]),
            "instrument": ["2Y", "10Y"],
            "value": [4.25, 4.72],
        }
    )
    result = curve_slope(frame)
    assert round(result.iloc[0]["value"]) == 47


def test_importance_score_is_bounded() -> None:
    assert importance_score(0) == 0
    assert importance_score(99, related_confirmation=5, event_near=True) == 100

