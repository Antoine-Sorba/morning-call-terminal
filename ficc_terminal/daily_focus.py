from __future__ import annotations


def build_daily_focus(
    *,
    event_title: str,
    event_assets: list[str],
    asset_class: str,
    indicator_names: list[str],
) -> dict[str, str]:
    """Return one concise market check and one possible FICC expression."""

    lowered = event_title.lower()
    first = indicator_names[0]
    related = asset_class in set(event_assets)

    watch_by_asset = {
        "Rates": "US 2Y vs US 10Y: which yield moved more after the event?",
        "FX": "DXY vs the relevant currency pair: is the move broad-dollar or currency-specific?",
        "Credit": "HYG vs LQD, with VIX: is risk aversion reaching credit?",
        "Commodities": "Brent vs WTI: did both markets confirm the move?",
        "Equities": "S&P 500 vs Nasdaq futures: is the move broad or rate-sensitive?",
    }
    pitch_by_asset = {
        "Rates": "Use the 2Y/10Y reaction to test a payer, receiver or curve expression.",
        "FX": "Use DXY confirmation to choose between a broad-dollar trade and a currency-specific option.",
        "Credit": "If HYG weakens as VIX rises, test a credit-index hedge after checking the licensed spread.",
        "Commodities": "If Brent and WTI confirm the shock, test a defined-risk hedge for an energy client.",
        "Equities": "Use equity futures as confirmation, then express the view through rates, FX or credit.",
    }

    watch = watch_by_asset[asset_class]
    pitch_angle = pitch_by_asset[asset_class]

    if any(word in lowered for word in ("oil", "opec", "hormuz", "iran", "supply disruption")):
        event_checks = {
            "Rates": "US 2Y vs US 10Y: is the 10Y leading as oil changes inflation risk?",
            "FX": "DXY and oil-sensitive currencies: is the FX move confirming the oil shock?",
            "Credit": "HYG and energy credit: is the oil move improving or weakening credit risk?",
            "Commodities": "Brent vs WTI: did both move after the oil headline?",
            "Equities": "Energy shares vs the broad index: is the oil shock helping or hurting risk sentiment?",
        }
        event_angles = {
            "Rates": "If the 10Y leads higher, test a curve-steepening or payer idea.",
            "FX": "If oil drives a clear currency divergence, test a defined-risk FX option.",
            "Credit": "If energy risk reaches spreads, test index protection or sector relative value.",
            "Commodities": "Test a defined-risk oil hedge for an energy consumer.",
            "Equities": "Use equities as confirmation and express the view in rates, FX or credit.",
        }
        watch = event_checks[asset_class]
        pitch_angle = event_angles[asset_class]
    elif any(word in lowered for word in ("yen", "boj", "intervention")):
        if asset_class == "FX":
            watch = "USD/JPY vs DXY and US 2Y: is the move specific to the yen?"
            pitch_angle = "If the move is yen-specific, test a defined-risk USD/JPY option."
    elif any(word in lowered for word in ("inflation", "cpi", "payroll", "jobs")):
        if asset_class == "Rates":
            watch = "US 2Y vs US 10Y: did policy expectations or long-term inflation risk move more?"
            pitch_angle = "Use the leading maturity to test a directional or curve trade."

    if not related and event_assets:
        watch = f"{first}: did it react at all? If not, this event may not matter for {asset_class}."

    return {
        "event": event_title.strip() or "Overnight market backdrop",
        "watch": watch,
        "pitch_angle": pitch_angle,
    }
