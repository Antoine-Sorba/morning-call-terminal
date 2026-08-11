from __future__ import annotations


def explain_us_rate_moves(
    *,
    two_year_level: float,
    two_year_change_bp: float,
    ten_year_level: float,
    ten_year_change_bp: float,
) -> dict[str, str]:
    """Explain two US government-bond yield moves without unexplained jargon."""

    def direction(change: float) -> str:
        return "rose" if change > 0 else "fell" if change < 0 else "was unchanged"

    previous_two = two_year_level - two_year_change_bp / 100
    previous_ten = ten_year_level - ten_year_change_bp / 100
    what_happened = (
        f"The US 2-year government-bond yield {direction(two_year_change_bp)} "
        f"by {abs(two_year_change_bp):.0f} basis points to {two_year_level:.2f}%. "
        f"The US 10-year yield {direction(ten_year_change_bp)} by "
        f"{abs(ten_year_change_bp):.0f} basis points to {ten_year_level:.2f}%."
    )
    number_meaning = (
        "One basis point is 0.01 percentage point. In this observation, the "
        f"2-year moved from about {previous_two:.2f}% to {two_year_level:.2f}%, "
        f"and the 10-year moved from about {previous_ten:.2f}% to {ten_year_level:.2f}%. "
        "When a bond's yield rises, its price normally falls, and vice versa."
    )

    difference = abs(two_year_change_bp - ten_year_change_bp)
    if two_year_change_bp > 0 and ten_year_change_bp > 0:
        if difference <= 2:
            interpretation = (
                "Both yields rose by a similar amount. This is a broad fall in US "
                "government-bond prices; the numbers alone do not prove why it happened."
            )
        elif two_year_change_bp > ten_year_change_bp:
            interpretation = (
                "The 2-year rose more. That can mean investors expect the Federal Reserve "
                "to keep its policy rate higher, but you must check the event timing before saying so."
            )
        else:
            interpretation = (
                "The 10-year rose more. That can point to greater concern about long-term "
                "inflation, economic growth or government-bond supply, but it is not proof of one cause."
            )
    elif two_year_change_bp < 0 and ten_year_change_bp < 0:
        if difference <= 2:
            interpretation = (
                "Both yields fell by a similar amount. This is a broad rise in US "
                "government-bond prices; weaker growth, lower inflation expectations or "
                "safe-haven buying are possibilities to verify."
            )
        elif two_year_change_bp < ten_year_change_bp:
            interpretation = (
                "The 2-year fell more. Investors may be expecting lower Federal Reserve "
                "policy rates, but confirm this against the event and its publication time."
            )
        else:
            interpretation = (
                "The 10-year fell more. This can occur when investors seek safer assets or "
                "expect weaker long-term growth and inflation, but the move alone does not identify the cause."
            )
    else:
        interpretation = (
            "The 2-year and 10-year moved in different directions. This changed the shape "
            "of the yield curve, so compare the exact timing with today's event before forming a view."
        )

    return {
        "what_happened": what_happened,
        "number_meaning": number_meaning,
        "possible_interpretation": interpretation,
        "how_to_verify": (
            "Open TVC:US02Y and TVC:US10Y in TradingView. Compare the event's publication "
            "time with the first clear chart move, then check whether the dollar, equities "
            "or oil support the same explanation."
        ),
    }
