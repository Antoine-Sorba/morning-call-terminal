from __future__ import annotations

import json


ESSENTIAL_MARKETS = {
    "Rates": {
        "default": "TVC:US10Y",
        "watchlist": ["TVC:US02Y", "TVC:US10Y", "TVC:DE10Y", "TVC:GB10Y"],
        "indicators": ["US 2Y", "US 10Y", "US 2s10s", "German 10Y", "UK 10Y"],
        "look_for": [
            "Did the front end or long end move more? That identifies policy versus term-premium pressure.",
            "Higher yield means lower bond price. Compare US, Germany and the UK for policy divergence.",
            "Confirm the driver against an official data release or central-bank communication.",
        ],
    },
    "FX": {
        "default": "TVC:DXY",
        "watchlist": ["TVC:DXY", "FX:EURUSD", "FX:GBPUSD", "FX:USDJPY"],
        "indicators": ["Dollar index", "EUR/USD", "GBP/USD", "USD/JPY"],
        "look_for": [
            "Start with the dollar: is the move broad or isolated to one currency?",
            "Check whether relative two-year yields confirm the FX move.",
            "For USD/JPY, always consider US yields, BoJ policy and intervention risk.",
        ],
    },
    "Credit": {
        "default": "AMEX:HYG",
        "watchlist": ["AMEX:HYG", "AMEX:LQD", "CBOE:VIX"],
        "indicators": ["High-yield ETF proxy", "Investment-grade ETF proxy", "VIX", "CMDI / CISS"],
        "look_for": [
            "HYG and LQD are liquid price proxies—not credit spreads and not executable CDS levels.",
            "A fall in HYG with a rise in VIX can confirm broader risk aversion.",
            "Use NY Fed CMDI and ECB CISS for the official stress backdrop; use a licensed terminal for spreads.",
        ],
    },
    "Commodities": {
        "default": "TVC:UKOIL",
        "watchlist": ["TVC:UKOIL", "NYMEX:CL1!", "COMEX:GC1!", "COMEX:HG1!"],
        "indicators": ["Brent", "WTI", "Gold", "Copper"],
        "look_for": [
            "Separate supply shocks from demand or growth concerns.",
            "Brent matters for global inflation; copper is often read as growth-sensitive.",
            "Check EIA data and official producer announcements before assigning a cause.",
        ],
    },
    "Equities": {
        "default": "CME_MINI:ES1!",
        "watchlist": ["CME_MINI:ES1!", "CME_MINI:NQ1!", "EUREX:FESX1!", "TVC:NI225"],
        "indicators": ["S&P futures", "Nasdaq futures", "Euro Stoxx futures", "Nikkei 225"],
        "look_for": [
            "Futures are the clearest overnight risk-sentiment check before cash markets open.",
            "Compare Nasdaq with rates: long-duration equities are particularly yield-sensitive.",
            "Use equities as confirmation for a FICC view, not as the trade pitch itself.",
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
