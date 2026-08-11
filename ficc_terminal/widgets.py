from __future__ import annotations

from urllib.parse import quote


ESSENTIAL_MARKETS = {
    "Rates": {
        "default": "TVC:US10Y",
        "watchlist": ["TVC:US02Y", "TVC:US10Y", "TVC:DE10Y", "TVC:GB10Y"],
        "indicators": [
            {"name": "United States 2-Year Government Bond Yield", "symbol": "TVC:US02Y", "why": "Most sensitive to expected Federal Reserve policy."},
            {"name": "United States 10-Year Government Bond Yield", "symbol": "TVC:US10Y", "why": "Reflects policy, growth, inflation, supply and term premium."},
            {"name": "Germany 10-Year Government Bond Yield", "symbol": "TVC:DE10Y", "why": "Core euro-area rates benchmark."},
            {"name": "United Kingdom 10-Year Government Bond Yield", "symbol": "TVC:GB10Y", "why": "Core UK gilt-market benchmark."},
        ],
    },
    "FX": {
        "default": "TVC:DXY",
        "watchlist": ["TVC:DXY", "FX:EURUSD", "FX:GBPUSD", "FX:USDJPY"],
        "indicators": [
            {"name": "U.S. Dollar Currency Index", "symbol": "TVC:DXY", "why": "Shows whether a dollar move is broad across major currencies."},
            {"name": "Euro / U.S. Dollar", "symbol": "FX:EURUSD", "why": "Main expression of US–euro-area policy divergence."},
            {"name": "British Pound / U.S. Dollar", "symbol": "FX:GBPUSD", "why": "Links UK data and BoE expectations to the dollar."},
            {"name": "U.S. Dollar / Japanese Yen", "symbol": "FX:USDJPY", "why": "Highly sensitive to yield differentials and intervention risk."},
        ],
    },
    "Credit": {
        "default": "AMEX:HYG",
        "watchlist": ["AMEX:HYG", "AMEX:LQD", "CBOE:VIX"],
        "indicators": [
            {"name": "iShares iBoxx $ High Yield Corporate Bond ETF", "symbol": "AMEX:HYG", "why": "Liquid high-yield price proxy; not a spread."},
            {"name": "iShares iBoxx $ Investment Grade Corporate Bond ETF", "symbol": "AMEX:LQD", "why": "Liquid investment-grade price proxy; not a spread."},
            {"name": "CBOE Volatility Index", "symbol": "CBOE:VIX", "why": "Equity-volatility context for broad risk appetite."},
        ],
    },
    "Commodities": {
        "default": "TVC:UKOIL",
        "watchlist": ["TVC:UKOIL", "NYMEX:CL1!", "COMEX:GC1!", "COMEX:HG1!"],
        "indicators": [
            {"name": "Brent Crude Oil", "symbol": "TVC:UKOIL", "why": "Global oil and inflation benchmark."},
            {"name": "Light Crude Oil Futures", "symbol": "NYMEX:CL1!", "why": "Front WTI continuous futures contract."},
            {"name": "Gold Futures", "symbol": "COMEX:GC1!", "why": "Safe-haven, real-yield and dollar-sensitive asset."},
            {"name": "Copper Futures", "symbol": "COMEX:HG1!", "why": "Growth- and China-sensitive industrial commodity."},
        ],
    },
    "Equities": {
        "default": "CME_MINI:ES1!",
        "watchlist": ["CME_MINI:ES1!", "CME_MINI:NQ1!", "EUREX:FESX1!", "TVC:NI225"],
        "indicators": [
            {"name": "S&P 500 E-mini Futures", "symbol": "CME_MINI:ES1!", "why": "Primary overnight US risk-sentiment benchmark."},
            {"name": "Nasdaq 100 E-mini Futures", "symbol": "CME_MINI:NQ1!", "why": "More sensitive to technology and long-term yields."},
            {"name": "EURO STOXX 50 Index Futures", "symbol": "EUREX:FESX1!", "why": "European equity-risk benchmark."},
            {"name": "Nikkei 225", "symbol": "TVC:NI225", "why": "Key Asian equity and yen-sensitive benchmark."},
        ],
    },
}


def tradingview_chart_url(symbol: str) -> str:
    """Return a direct TradingView chart link without embedding third-party code."""

    return f"https://www.tradingview.com/chart/?symbol={quote(symbol, safe='')}"
