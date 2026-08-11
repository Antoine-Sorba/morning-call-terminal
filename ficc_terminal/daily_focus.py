from __future__ import annotations


def build_daily_focus(
    *,
    event_title: str,
    event_assets: list[str],
    asset_class: str,
    indicator_names: list[str],
) -> dict[str, list[str] | str]:
    """Create plain-English questions and pitch angles for one event.

    The function supplies a repeatable reasoning routine. It does not decide
    that an event caused a move and it does not recommend a trade.
    """

    title = event_title.strip() or "the overnight market backdrop"
    lowered = title.lower()
    first = indicator_names[0]
    second = indicator_names[1] if len(indicator_names) > 1 else indicator_names[0]
    related = asset_class in set(event_assets)

    questions = [
        f"At what time did this happen, and did {first} move immediately afterwards? If the move started earlier, do not claim the event caused it.",
    ]

    asset_questions = {
        "Rates": [
            "Did the US 2-year yield or US 10-year yield move more? The 2-year is more sensitive to expected central-bank policy; the 10-year also reflects long-term inflation, growth and bond supply.",
            "Did German and UK 10-year yields move in the same direction? If not, the story may be country-specific rather than global.",
        ],
        "FX": [
            "Did the U.S. Dollar Index move in the same direction as the currency pair? If yes, the move may be broad dollar strength or weakness; if no, it may be currency-specific.",
            "Do relative government-bond yields support the FX move, or is safe-haven demand a better explanation?",
        ],
        "Credit": [
            "Did HYG fall more than LQD while VIX rose? That combination would be consistent with broader risk aversion, but HYG and LQD remain ETF price proxies—not credit spreads.",
            "Is the move large enough to justify checking NY Fed CMDI, ECB CISS or a licensed credit-spread screen?",
        ],
        "Commodities": [
            "Did Brent and WTI move together? A larger Brent move can point to a more global supply concern; a broad fall in oil and copper can point to weaker demand expectations.",
            "Did gold rise at the same time? That can indicate safe-haven demand, but confirm it against the dollar and real yields.",
        ],
        "Equities": [
            "Did S&P 500 and Nasdaq futures move together? A larger Nasdaq move may indicate that interest rates are an important part of the story.",
            "Did European and Japanese markets confirm the direction, or is the event concentrated in one region?",
        ],
    }
    questions.extend(asset_questions[asset_class])

    if not related and event_assets:
        questions.append(
            f"This event is primarily tagged to {', '.join(event_assets)}, not {asset_class}. Use {first} and {second} as confirmation rather than as the main evidence."
        )
    elif related:
        questions.append(
            f"What would you have expected {first} and {second} to do after this event, and did the actual charts confirm that expectation?"
        )

    pitch_angles = {
        "Rates": [
            "Policy-path angle: use the US 2-year yield to decide whether the event changes expected central-bank policy.",
            "Curve angle: compare the US 2-year and 10-year yields before discussing a steepener, flattener, payer or receiver trade.",
        ],
        "FX": [
            "Broad-dollar angle: only use a dollar expression if DXY confirms the move across several currencies.",
            "Currency-specific angle: if DXY is stable, consider whether the catalyst is specific to the euro, sterling or yen and use defined-risk options where event risk is high.",
        ],
        "Credit": [
            "Hedging angle: if HYG weakens and VIX rises, discuss credit-index protection with a credit fund, then verify the licensed spread and carry.",
            "Relative-value angle: compare investment-grade and high-yield sensitivity rather than treating every risk-off event identically.",
        ],
        "Commodities": [
            "Corporate-hedging angle: an airline or energy consumer may prefer a layered call spread if the event creates upside oil-price risk.",
            "Macro angle: check whether higher energy prices are also pushing inflation expectations and government-bond yields higher.",
        ],
        "Equities": [
            "Confirmation angle: use equity futures to validate risk sentiment, then express the client conversation through rates, FX or credit.",
            "Rates-sensitivity angle: if Nasdaq underperforms as yields rise, the cleaner FICC discussion may be the rates move rather than equities themselves.",
        ],
    }[asset_class]

    if any(word in lowered for word in ("oil", "opec", "hormuz", "supply disruption")):
        pitch_angles.insert(0, "Event-specific angle: compare an oil call-spread hedge for a consumer with the inflation impact on rates.")
    elif any(word in lowered for word in ("yen", "boj", "intervention")):
        pitch_angles.insert(0, "Event-specific angle: compare USD/JPY with DXY and US yields before discussing a defined-risk FX option.")
    elif any(word in lowered for word in ("inflation", "cpi", "payroll", "jobs")):
        pitch_angles.insert(0, "Event-specific angle: identify whether the front end, long end or dollar reacted most before selecting the FICC expression.")
    elif any(word in lowered for word in ("war", "attack", "sanction", "tariff")):
        pitch_angles.insert(0, "Event-specific angle: test safe-haven demand in the dollar, gold and government bonds before discussing protection trades.")

    return {
        "event": title,
        "questions": questions[:4],
        "pitch_angles": pitch_angles[:3],
    }

