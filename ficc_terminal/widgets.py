from __future__ import annotations

import json


def tradingview_ticker_html() -> str:
    config = {
        "symbols": [
            {"description": "US 10Y future", "proName": "CBOT:ZN1!"},
            {"description": "Bund future", "proName": "EUREX:FGBL1!"},
            {"description": "EUR/USD", "proName": "FX:EURUSD"},
            {"description": "GBP/USD", "proName": "FX:GBPUSD"},
            {"description": "WTI", "proName": "NYMEX:CL1!"},
            {"description": "Gold", "proName": "COMEX:GC1!"},
            {"description": "S&P 500", "proName": "FOREXCOM:SPXUSD"},
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

