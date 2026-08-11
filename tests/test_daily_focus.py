from ficc_terminal.daily_focus import build_daily_focus


def test_oil_event_creates_event_specific_questions_and_pitch_angle() -> None:
    focus = build_daily_focus(
        event_title="Oil rises after an unexpected supply disruption",
        event_assets=["Commodities", "Rates"],
        asset_class="Commodities",
        indicator_names=["Brent Crude Oil", "Light Crude Oil Futures"],
    )
    assert "what time" in focus["questions"][0].lower()
    assert any("call-spread" in angle for angle in focus["pitch_angles"])


def test_yen_event_creates_fx_specific_pitch_angle() -> None:
    focus = build_daily_focus(
        event_title="Yen strengthens after Bank of Japan intervention warning",
        event_assets=["FX", "Rates"],
        asset_class="FX",
        indicator_names=["U.S. Dollar Currency Index", "U.S. Dollar / Japanese Yen"],
    )
    assert any("USD/JPY" in angle for angle in focus["pitch_angles"])
    assert any("DXY" in angle for angle in focus["pitch_angles"])
