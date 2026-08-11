from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ClientPersona:
    name: str
    concern: str
    sales_angle: str


@dataclass(frozen=True)
class TradeTemplate:
    name: str
    product: str
    view: str
    instrument: str
    catalyst: str
    risk: str
    horizon: str


CLIENT_PERSONAS = {
    "UK pension fund": ClientPersona(
        "UK pension fund",
        "Duration exposure, funding-ratio volatility and liability hedging",
        "Gilt, swap or curve hedge framed around liabilities rather than outright return",
    ),
    "European corporate": ClientPersona(
        "European corporate",
        "Future dollar cash flows and budget-rate uncertainty",
        "FX hedge with transparent downside protection and accounting considerations",
    ),
    "Credit fund": ClientPersona(
        "Credit fund",
        "Spread widening, liquidity and relative value",
        "Cash-bond, index or rates-overlay discussion with liquidity explicitly addressed",
    ),
    "Airline": ClientPersona(
        "Airline",
        "Jet-fuel input costs and margin volatility",
        "Layered oil hedge or option structure aligned with operational exposure",
    ),
    "Macro hedge fund": ClientPersona(
        "Macro hedge fund",
        "Central-bank divergence and cross-market convexity",
        "Relative-value rates or FX expression with catalyst and invalidation level",
    ),
}


TRADE_TEMPLATES = {
    "US 2s10s steepener": TradeTemplate(
        "US 2s10s steepener",
        "USD interest-rate swaps",
        "Front-end policy expectations may become better anchored while long-end term premium remains exposed to supply and inflation uncertainty.",
        "Receive fixed in 2-year USD swaps and pay fixed in 10-year USD swaps, DV01-balanced.",
        "US inflation and labour data, Treasury supply, and Federal Reserve communication.",
        "A renewed growth shock or rapid disinflation could rally the long end and flatten the curve.",
        "One to three months",
    ),
    "Receive EUR 5Y": TradeTemplate(
        "Receive EUR 5Y",
        "EUR interest-rate swap",
        "The belly may outperform if activity weakens and the expected ECB path shifts lower.",
        "Receive fixed in a 5-year EUR swap; define the invalidation above the recent rate range.",
        "Euro-area inflation, PMIs and ECB policy communication.",
        "Sticky services inflation or a hawkish ECB repricing could push five-year rates higher.",
        "One to three months",
    ),
    "GBP/USD forward hedge": TradeTemplate(
        "GBP/USD forward hedge",
        "G10 FX forward",
        "A known future dollar cash flow should be protected from adverse GBP/USD moves rather than turned into a directional speculation.",
        "Use a dated FX forward sized to the forecast dollar exposure; consider layered hedges for uncertain timing.",
        "The payment schedule and changes in UK-US rate differentials.",
        "The hedge removes favourable currency participation and forecast cash flows may change.",
        "Match the underlying payment date",
    ),
    "Three-month USD/JPY call spread": TradeTemplate(
        "Three-month USD/JPY call spread",
        "G10 FX options",
        "Rate differentials can support the dollar against the yen, while intervention risk favours defined premium.",
        "Buy a three-month USD/JPY call and sell a higher-strike call with the same expiry.",
        "Fed and Bank of Japan guidance, US yields and official Japanese FX commentary.",
        "A sharp US rates rally, hawkish BoJ shift or intervention could strengthen the yen.",
        "Three months",
    ),
    "WTI call spread hedge": TradeTemplate(
        "WTI call spread hedge",
        "Energy options",
        "An operational fuel buyer may prefer capped protection against a sharp oil rally to an outright directional position.",
        "Buy a WTI call and sell a higher-strike call for the same delivery window; calibrate barrels to exposure.",
        "EIA balances, OPEC+ supply decisions and geopolitical disruption.",
        "Oil may fall or the physical exposure may differ from the WTI basis, leaving premium and basis risk.",
        "Match the procurement window",
    ),
}


def build_pitch(persona_name: str, trade_name: str) -> dict[str, str]:
    persona = CLIENT_PERSONAS[persona_name]
    trade = TRADE_TEMPLATES[trade_name]
    return {
        "client": persona.name,
        "client_problem": persona.concern,
        "sales_angle": persona.sales_angle,
        "trade": trade.name,
        "product": trade.product,
        "market_view": trade.view,
        "instrument": trade.instrument,
        "entry_level": "Complete after checking the latest executable market level",
        "target": "Define using risk/reward and the client's objective",
        "invalidation": trade.risk,
        "time_horizon": trade.horizon,
        "catalyst": trade.catalyst,
        "main_risk": trade.risk,
        "client_relevance": f"This suits a {persona.name} because it addresses {persona.concern.lower()}. {persona.sales_angle}.",
        "closing_question": "How does this exposure sit within your existing hedges, liquidity limits and event risk?",
    }


def personas_as_records() -> list[dict[str, str]]:
    return [asdict(value) for value in CLIENT_PERSONAS.values()]

