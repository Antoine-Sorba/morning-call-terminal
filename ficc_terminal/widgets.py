from __future__ import annotations

import json


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


def tradingview_ticker_html() -> str:
    config = {
        "symbols": [
            {"description": "US 10Y yield", "proName": "TVC:US10Y"},
            {"description": "Dollar index", "proName": "TVC:DXY"},
            {"description": "EUR/USD", "proName": "FX:EURUSD"},
            {"description": "USD/JPY", "proName": "FX:USDJPY"},
            {"description": "Brent", "proName": "TVC:UKOIL"},
            {"description": "Gold", "proName": "COMEX:GC1!"},
            {"description": "S&P futures", "proName": "CME_MINI:ES1!"},
        ],
        "showSymbolLogo": True,
        "isTransparent": True,
        "displayMode": "adaptive",
        "colorTheme": "light",
        "locale": "en",
    }
    return f"""
    <div class="tradingview-widget-container">
      <div class="tradingview-widget-container__widget"></div>
      <div class="tradingview-widget-copyright">
        <a href="https://www.tradingview.com/" rel="noopener nofollow" target="_blank">Market data by TradingView</a>
      </div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js" async>
      {json.dumps(config)}
      </script>
    </div>
    """


def tradingview_overview_html() -> str:
    config = {
        "colorTheme": "light",
        "dateRange": "1D",
        "showChart": True,
        "locale": "en",
        "largeChartUrl": "",
        "isTransparent": True,
        "showSymbolLogo": True,
        "showFloatingTooltip": True,
        "width": "100%",
        "height": 610,
        "plotLineColorGrowing": "rgba(18, 64, 50, 1)",
        "plotLineColorFalling": "rgba(190, 79, 55, 1)",
        "tabs": [
            {
                "title": "Rates & FX",
                "symbols": [
                    {"s": "CBOT:ZN1!", "d": "US 10Y future"},
                    {"s": "EUREX:FGBL1!", "d": "Bund future"},
                    {"s": "FX:EURUSD", "d": "EUR/USD"},
                    {"s": "FX:GBPUSD", "d": "GBP/USD"},
                    {"s": "FX:USDJPY", "d": "USD/JPY"},
                ],
            },
            {
                "title": "Commodities",
                "symbols": [
                    {"s": "NYMEX:CL1!", "d": "WTI"},
                    {"s": "TVC:UKOIL", "d": "Brent"},
                    {"s": "COMEX:GC1!", "d": "Gold"},
                    {"s": "COMEX:HG1!", "d": "Copper"},
                ],
            },
            {
                "title": "Equity context",
                "symbols": [
                    {"s": "FOREXCOM:SPXUSD", "d": "S&P 500"},
                    {"s": "NASDAQ:NDX", "d": "Nasdaq 100"},
                    {"s": "TVC:UKX", "d": "FTSE 100"},
                    {"s": "TVC:NI225", "d": "Nikkei 225"},
                ],
            },
        ],
    }
    return f"""
    <div class="tradingview-widget-container">
      <div class="tradingview-widget-container__widget"></div>
      <div class="tradingview-widget-copyright">
        <a href="https://www.tradingview.com/" rel="noopener nofollow" target="_blank">Provider-hosted market overview by TradingView</a>
      </div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-market-overview.js" async>
      {json.dumps(config)}
      </script>
    </div>
    """


def tradingview_advanced_chart_html(asset_class: str) -> str:
    market = ESSENTIAL_MARKETS[asset_class]
    config = {
        "autosize": True,
        "symbol": market["default"],
        "interval": "60",
        "timezone": "Europe/London",
        "theme": "light",
        "backgroundColor": "rgba(255, 254, 249, 1)",
        "style": "1",
        "withdateranges": True,
        "hide_side_toolbar": True,
        "allow_symbol_change": True,
        "save_image": False,
        "locale": "en",
        "watchlist": market["watchlist"],
        "support_host": "https://www.tradingview.com",
    }
    return f"""
    <div class="tradingview-widget-container" style="height:100%;width:100%">
      <div class="tradingview-widget-container__widget" style="height:calc(100% - 28px);width:100%"></div>
      <div class="tradingview-widget-copyright">
        <a href="https://www.tradingview.com/" rel="noopener nofollow" target="_blank">Interactive chart by TradingView</a>
      </div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
      {json.dumps(config)}
      </script>
    </div>
    """
