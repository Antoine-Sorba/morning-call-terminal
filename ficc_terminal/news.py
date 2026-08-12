from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import feedparser
import pandas as pd

from .cache import OfficialHttpClient


OFFICIAL_FEEDS = {
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
    "European Central Bank": "https://www.ecb.europa.eu/rss/press.html",
    "Bank of England": "https://www.bankofengland.co.uk/rss/news",
    "Reserve Bank of Australia": "https://www.rba.gov.au/rss/rss-cb-media-releases.xml",
    "BLS Consumer Price Index": "https://www.bls.gov/feed/cpi.rss",
    "BLS Employment Situation": "https://www.bls.gov/feed/empsit.rss",
    "BLS Producer Price Index": "https://www.bls.gov/feed/ppi.rss",
    "BLS Job Openings": "https://www.bls.gov/feed/jolts.rss",
    "U.S. Bureau of Economic Analysis": "https://apps.bea.gov/rss/rss.xml",
}

NEWS_DISCOVERY_QUERIES = {
    "Central-bank decisions": (
        '(Fed OR FOMC OR ECB OR BoE OR BoJ OR PBOC OR RBA) '
        '(decision OR "rate cut" OR "rate hike" OR intervention OR emergency) when:1d'
    ),
    "Major macro releases": (
        '(CPI OR inflation OR payrolls OR unemployment OR GDP OR PMI OR "retail sales") '
        '(surprise OR unexpectedly OR accelerates OR slows OR rises OR falls) when:1d'
    ),
    "Geopolitical shocks": (
        '(war OR attack OR ceasefire OR sanctions OR election OR coup) '
        '(markets OR oil OR bonds OR currency OR stocks OR shipping) when:1d'
    ),
    "Government and trade policy": (
        '(tariff OR sanctions OR stimulus OR fiscal OR government) '
        '(announces OR imposes OR suspends OR approves OR markets) when:1d'
    ),
    "Energy and supply": (
        '(OPEC OR oil OR gas OR Hormuz OR shipping OR "supply disruption") '
        '(cuts OR halts OR attacks OR sanctions OR surges OR plunges) when:1d'
    ),
    "Credit and financial stability": (
        '(default OR downgrade OR bankruptcy OR "bank stress" OR "credit spreads") '
        '(major OR systemic OR widens OR emergency OR liquidity) when:1d'
    ),
    "Cross-asset reaction": (
        '(Treasury OR dollar OR euro OR yen OR oil OR gold OR "S&P 500") '
        '(surges OR plunges OR jumps OR tumbles OR selloff) when:1d'
    ),
}

ASSET_KEYWORDS = {
    "Rates": (
        "bond", "bonds", "yield", "yields", "treasury", "treasuries", "gilt",
        "bund", "rate", "rates", "fed", "fomc", "ecb", "boe", "boj",
        "rba", "reserve bank of australia", "cash rate", "inflation", "cpi",
        "ppi", "pce", "payroll", "jobs", "employment", "unemployment",
        "wages", "gdp", "pmi", "retail sales", "tariff", "fiscal", "stimulus",
    ),
    "FX": (
        "dollar", "euro", "sterling", "pound", "yen", "yuan", "currency",
        "currencies", "fx", "exchange rate", "intervention", "australian dollar",
        "usd", "eur", "gbp", "jpy", "aud", "cad", "chf",
        "usdjpy", "eurusd", "gbpusd", "audusd", "usdcad", "usdchf", "dxy",
    ),
    "Credit": (
        "credit", "spread", "spreads", "default", "downgrade", "bankruptcy",
        "debt", "corporate bond", "bank stress", "bank run", "liquidity",
    ),
    "Commodities": (
        "oil", "brent", "wti", "opec", "gas", "gold", "copper", "commodity",
        "commodities", "energy", "inventory", "inventories", "supply disruption",
    ),
    "Equities": (
        "stock", "stocks", "equity", "equities", "shares", "s&p", "nasdaq",
        "stoxx", "ftse", "nikkei", "earnings", "futures",
    ),
}

EVENT_KEYWORDS = {
    "Central banks": (
        "fed", "fomc", "ecb", "boe", "boj", "rba", "reserve bank of australia",
        "central bank", "cash rate", "rate cut", "rate hike", "monetary policy",
    ),
    "Macro data": (
        "inflation", "cpi", "ppi", "pce", "payroll", "jobs", "employment",
        "unemployment", "wages", "gdp", "pmi", "retail sales",
    ),
    "Geopolitics / policy": (
        "war", "attack", "attacks", "ceasefire", "sanction", "sanctions",
        "tariff", "tariffs", "election",
        "government", "intervention", "stimulus",
    ),
    "Energy / supply": ("oil", "opec", "gas", "inventory", "supply", "production", "shipping"),
    "Corporate / credit": ("earnings", "default", "downgrade", "bankruptcy", "debt", "bank", "credit"),
}

HIGH_IMPACT_WORDS = (
    "unexpected", "surprise", "emergency", "shock", "war", "attack", "sanction",
    "tariff", "intervention", "default", "downgrade", "bankruptcy", "record",
    "hike", "cut", "halt", "resign", "disruption",
)

REACTION_PATTERN = re.compile(
    r"\b(jump(?:s|ed)?|surge(?:s|d)?|rall(?:y|ies|ied)|rise(?:s|n)?|"
    r"fall(?:s|en)?|drop(?:s|ped)?|slide(?:s|d)?|sell-?off|plunge(?:s|d)?|"
    r"weaken(?:s|ed)?|strengthen(?:s|ed)?|gain(?:s|ed)?|lose(?:s|t)?)\b",
    flags=re.IGNORECASE,
)

# These publishers are normally readable without a paid subscription. Official
# central-bank feeds are also accepted below. Access can still vary by country,
# so this is a conservative, best-effort allowlist rather than a guarantee.
FREE_ACCESS_PUBLISHERS = (
    "Reuters",
    "Associated Press",
    "AP News",
    "BBC",
    "CNBC",
    "The Guardian",
    "Yahoo Finance",
    "Sky News",
    "Politico",
    "Al Jazeera",
    "NPR",
    "France 24",
    "Deutsche Welle",
    "Investing.com",
    "TradingView",
    "OilPrice.com",
    "XTB",
)

# Top-five events must pass a higher bar than the broader timeline. A major
# release, decision or shock can pass on its own; ordinary market round-ups and
# previews cannot pass merely because they are recent.
KEY_EVENT_SCORE = 11.25
IMPORTANT_EVENT_SCORE = 9.5

PAYWALL_MARKERS = re.compile(
    r"\b(Bloomberg|Financial Times|Wall Street Journal|WSJ|Nikkei Asia|"
    r"MarketWatch|The Times|CNBC Pro|subscription)\b",
    flags=re.IGNORECASE,
)

ADMINISTRATIVE_HEADLINES = re.compile(
    r"\b(?:concert|invite the public|turnover surveys?|annual report|procurement|"
    r"vacancy|museum|archive|conference registration|speech by|opening remarks|"
    r"calendar|minutes from the board meeting)\b",
    flags=re.IGNORECASE,
)

STORY_RULES = (
    ("middle_east_energy", ("oil", "brent", "wti"), ("iran", "hormuz", "oman", "middle east")),
    ("red_sea_energy", ("red sea", "houthi", "saudi"), ("oil", "exports", "shipping", "pipeline", "attack")),
    ("libya_energy_attack", ("libya", "libyan"), ("oil", "energy", "power plant", "drone", "attack")),
    ("opec_supply", ("opec",), ("production", "output", "supply", "quota")),
    (
        "us_inflation",
        ("inflation", "cpi"),
        ("us", "u.s.", "treasury", "fed", "market", "markets", "gold", "stock", "stocks", "nasdaq", "s&p", "rally"),
    ),
    ("us_labour", ("payroll", "jobs", "unemployment", "labour"), ("us", "u.s.", "fed")),
    ("us_growth", ("gdp", "retail sales", "pmi"), ("us", "u.s.", "fed", "dollar", "treasury")),
    ("euro_inflation", ("inflation", "cpi"), ("eurozone", "euro area", "ecb", "euro")),
    ("uk_inflation", ("inflation", "cpi"), ("uk", "britain", "boe", "sterling")),
    ("china_macro", ("china", "chinese", "pboc"), ("gdp", "pmi", "inflation", "stimulus", "yuan")),
    ("india_inflation", ("inflation", "cpi"), ("india", "rbi")),
    ("fed_policy", ("fed", "fomc", "federal reserve"), ("rate", "policy", "powell")),
    ("ecb_policy", ("ecb", "european central bank"), ("rate", "policy", "lagarde")),
    ("boe_policy", ("boe", "bank of england"), ("rate", "policy", "bailey")),
    ("boj_yen", ("boj", "bank of japan", "yen"), ("rate", "policy", "intervention", "yen")),
    ("rba_policy", ("rba", "reserve bank of australia"), ("rate", "policy", "australian dollar")),
    ("trade_tariffs", ("tariff", "trade war"), ("us", "u.s.", "china", "europe")),
    ("credit_stress", ("default", "downgrade", "bankruptcy", "credit"), ("bond", "debt", "bank", "company")),
)

HEADLINE_REWRITES = (
    (
        re.compile(
            r"^Treasury yields up as oil prices jump and investors await inflation data$",
            flags=re.IGNORECASE,
        ),
        "US Treasury yields rise as oil climbs ahead of inflation data",
    ),
    (
        re.compile(
            r"^Rupee dips as oil rises on Middle East uncertainty; RBI intervention shields$",
            flags=re.IGNORECASE,
        ),
        "Middle East uncertainty lifts oil and pressures the rupee; RBI intervenes",
    ),
    (
        re.compile(
            r"^Chart of the Day: USDJPY Rises Again\. Intervention Is Not Enough — Markets Await BoJ Action$",
            flags=re.IGNORECASE,
        ),
        "USD/JPY rises again as intervention impact fades and markets await BoJ action",
    ),
    (
        re.compile(
            r"^July Inflation Print Puts Rally on Trial as Stocks Eye Record Highs$",
            flags=re.IGNORECASE,
        ),
        "US July inflation data tests record-high stocks and Fed rate expectations",
    ),
)

PROMOTIONAL_HEADLINES = re.compile(
    r"\b(?:stocks? to watch|dividend stocks?|price target|upside|bullish on|"
    r"what it means for|analyst (?:says|sees)|stock (?:jumps|drops|falls|rises|slides|surges))\b",
    flags=re.IGNORECASE,
)

PREVIEW_HEADLINES = re.compile(
    r"\b(?:ahead of|awaits?|what to (?:watch|expect)|preview|eyes? data|"
    r"set to|could|may|forecast|outlook|week ahead|things to know|"
    r"less likely|more likely|odds shift|rate[- ](?:cut|hike) bets?)\b",
    flags=re.IGNORECASE,
)

LOW_SIGNAL_HEADLINES = re.compile(
    r"\b(?:edges?|ticks?|slightly|little changed|mixed|steady|flat|"
    r"pares? gains|modest(?:ly)?|cautious trading)\b",
    flags=re.IGNORECASE,
)

ANALYSIS_HEADLINES = re.compile(
    r"\b(?:how (?:the )?market|why (?:the |a |an )?|explainer|analysis|opinion|"
    r"takeaways?|what .{0,35} means|odds of|case for|strategists? (?:say|see))\b",
    flags=re.IGNORECASE,
)

STRUCTURAL_REPORT_HEADLINES = re.compile(
    r"\b(?:youth unemployment|study finds|survey finds|research finds|"
    r"long-term outlook|report warns|labour agency says)\b",
    flags=re.IGNORECASE,
)

NON_EVENT_CREDIT_HEADLINES = re.compile(
    r"\b(?:avoids? (?:an? )?(?:immediate )?downgrade|not downgraded|"
    r"outlook unchanged|faces? (?:a )?(?:key )?test)\b",
    flags=re.IGNORECASE,
)

MAJOR_MACRO_MARKETS = (
    "us", "u.s.", "united states", "federal reserve", "fed", "treasury",
    "dollar", "china", "chinese", "pboc", "yuan", "eurozone", "euro area",
    "ecb", "euro", "uk", "britain", "boe", "sterling", "japan", "boj", "yen",
    "global",
)

SECONDARY_MACRO_MARKETS = (
    "india", "rbi", "canada", "boc", "australia", "rba", "switzerland",
    "snb", "brazil", "korea", "russia",
)

MATERIAL_EVENT_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (
        re.compile(
            r"\b(?:fed|fomc|ecb|boe|boj|pboc|rba|central bank)\b.*"
            r"(?:\b(?:raises?|hikes?|lowers?|holds?|leaves?)\b.{0,20}\b(?:rate|rates)\b|"
            r"\bcuts?\b.{0,20}\b(?:rate|rates|by)\b|\bintervenes?\b|"
            r"\bemergency (?:action|decision)\b|\bpolicy decision\b|"
            r"\bquantitative easing\b|\bquantitative tightening\b)",
            flags=re.IGNORECASE,
        ),
        5.0,
    ),
    (
        re.compile(
            r"\b(?:cpi|ppi|pce|inflation|payrolls?|unemployment|employment|"
            r"wages?|gdp|pmi|retail sales)\b.*"
            r"(?:\b(?:unexpected|surprise|accelerates?|slows?|rises?|falls?|"
            r"increases?|decreases?|contracts?|expands?|record)\b|\d)",
            flags=re.IGNORECASE,
        ),
        4.5,
    ),
    (
        re.compile(
            r"\b(?:war|attack|missile|invasion|ceasefire|sanctions?|tariffs?|"
            r"coup|intervention)\b.*\b(?:announces?|imposes?|strikes?|agrees?|"
            r"ends?|suspends?|escalates?|emergency|unexpected)\b",
            flags=re.IGNORECASE,
        ),
        5.0,
    ),
    (
        re.compile(
            r"\b(?:default|downgrade|bankruptcy|bank run|liquidity crisis|"
            r"capital shortfall|bailout)\b",
            flags=re.IGNORECASE,
        ),
        5.0,
    ),
    (
        re.compile(
            r"\b(?:opec|oil|gas|lng|shipping|hormuz)\b.*\b(?:cuts?|halts?|"
            r"closes?|disrupts?|attacks?|sanctions?|shortage|outage|surges?|plunges?|"
            r"exceeds? quota|misses? quota)\b",
            flags=re.IGNORECASE,
        ),
        4.5,
    ),
)


def _google_news_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        f"{quote_plus(query)}&hl=en-GB&gl=GB&ceid=GB:en"
    )


def _safe_https_url(value: str) -> str:
    return value if value.startswith("https://") else ""


def _contains_term(text: str, term: str) -> bool:
    """Match market terms as words or phrases, avoiding hits such as rate in strategic."""

    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])",
            text.lower(),
        )
    )


def _publisher_and_title(
    entry: object,
    fallback: str,
    *,
    allow_title_publisher: bool = True,
) -> tuple[str, str]:
    title = str(entry.get("title", "Untitled release")).strip()
    source = entry.get("source", {}) or {}
    publisher = str(source.get("title", "")).strip() if hasattr(source, "get") else ""
    if allow_title_publisher and " - " in title:
        candidate_title, candidate_publisher = title.rsplit(" - ", 1)
        publisher_match = (
            publisher
            and (
                candidate_publisher.lower() in publisher.lower()
                or publisher.lower() in candidate_publisher.lower()
            )
        )
        if 1 < len(candidate_publisher) < 80 and (not publisher or publisher_match):
            title, publisher = candidate_title.strip(), candidate_publisher.strip()
    return publisher or fallback, title


def parse_news_feed(
    content: bytes | str,
    *,
    feed_name: str,
    source_type: str,
    retrieved_at: str,
    stale: bool = False,
) -> pd.DataFrame:
    parsed = feedparser.parse(content)
    records = []
    for entry in parsed.entries:
        publisher, title = _publisher_and_title(
            entry,
            feed_name,
            allow_title_publisher=source_type != "Official",
        )
        raw_date = entry.get("published", entry.get("updated", ""))
        try:
            published = pd.Timestamp(parsedate_to_datetime(raw_date)).tz_convert("UTC")
        except (TypeError, ValueError, OverflowError):
            published = pd.to_datetime(raw_date, utc=True, errors="coerce")
        url = _safe_https_url(str(entry.get("link", "")))
        if not title or not url:
            continue
        records.append(
            {
                "published": published,
                "title": title,
                "summary": " ".join(
                    unescape(
                        re.sub(r"<[^>]+>", " ", str(entry.get("summary", "")))
                    ).split()
                ),
                "url": url,
                "publisher": publisher,
                "feed": feed_name,
                "source_type": source_type,
                "retrieved_at": retrieved_at,
                "stale": stale,
            }
        )
    return pd.DataFrame(records)


def fetch_market_news(client: OfficialHttpClient) -> pd.DataFrame:
    feeds = [
        (name, url, "Official") for name, url in OFFICIAL_FEEDS.items()
    ] + [
        (name, _google_news_url(query), "News discovery")
        for name, query in NEWS_DISCOVERY_QUERIES.items()
    ]

    def fetch_feed(name: str, url: str, source_type: str) -> pd.DataFrame:
        cache_key = re.sub(r"\W+", "_", name.lower()).strip("_")
        payload = client.get(f"market_news_{cache_key}", url)
        return parse_news_feed(
            payload.content,
            feed_name=name,
            source_type=source_type,
            retrieved_at=payload.retrieved_at,
            stale=payload.stale,
        )

    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=min(8, len(feeds))) as executor:
        futures = {
            executor.submit(fetch_feed, name, url, source_type): name
            for name, url, source_type in feeds
        }
        for future in as_completed(futures):
            try:
                frame = future.result()
                if not frame.empty:
                    frames.append(frame)
            except Exception:
                continue
    if not frames:
        return pd.DataFrame(
            columns=[
                "published", "title", "summary", "url", "publisher", "feed", "source_type",
                "retrieved_at", "stale",
            ]
        )
    return pd.concat(frames, ignore_index=True)


def classify_assets(title: str) -> list[str]:
    lowered = title.lower()
    return [
        asset_class
        for asset_class, keywords in ASSET_KEYWORDS.items()
        if any(_contains_term(lowered, keyword) for keyword in keywords)
    ]


def classify_event(title: str) -> str:
    lowered = title.lower()
    for event_type, keywords in EVENT_KEYWORDS.items():
        if any(_contains_term(lowered, keyword) for keyword in keywords):
            return event_type
    return "Cross-asset / risk sentiment"


def precise_headline(title: str, publisher: str = "", summary: str = "") -> str:
    """Apply conservative edits that make a source headline more specific."""

    cleaned = " ".join(title.split()).strip()
    if "reserve bank of australia" in publisher.lower():
        decision = re.search(
            r"decided to (leave|raise|lower) the cash rate target (unchanged )?(?:at|to) ([0-9.]+) per cent",
            summary,
            flags=re.IGNORECASE,
        )
        if decision:
            action, unchanged, level = decision.groups()
            verb = "leaves" if action.lower() == "leave" or unchanged else f"{action.lower()}s"
            return f"RBA {verb} cash rate at {level}%"
    for pattern, replacement in HEADLINE_REWRITES:
        if pattern.match(cleaned):
            return replacement
    cleaned = re.sub(r"^Treasury yields\b", "US Treasury yields", cleaned)
    return cleaned


def _story_key(title: str, event_type: str) -> str:
    """Group different publishers' headlines about the same underlying story."""

    lowered = title.lower()
    if any(_contains_term(lowered, term) for term in ("oil", "brent", "wti", "energy", "shipping")) and (
        any(_contains_term(lowered, term) for term in ("iran", "hormuz", "oman-iran"))
        or _contains_term(lowered, "middle east")
        or _contains_term(lowered, "war uncertainty")
    ):
        return "middle_east_energy"
    for key, subject_terms, context_terms in STORY_RULES:
        if any(_contains_term(lowered, term) for term in subject_terms) and any(
            _contains_term(lowered, term) for term in context_terms
        ):
            return key

    words = re.findall(r"[a-z0-9]+", lowered)
    stop_words = {
        "a", "an", "and", "as", "at", "after", "ahead", "amid", "are",
        "for", "from", "in", "is", "of", "on", "over", "the", "to", "up",
        "with", "while", "market", "markets", "investor", "investors",
        "rise", "rises", "rose", "jump", "jumps", "fall", "falls", "fell",
        "gain", "gains", "drop", "drops", "slip", "slips",
    }
    meaningful = sorted({word for word in words if word not in stop_words and len(word) > 2})
    return f"{event_type.lower()}:{'-'.join(meaningful[:5])}"


def _primary_asset(title: str, asset_classes: list[str]) -> str:
    lowered = title.lower()
    counts = {
        asset: sum(_contains_term(lowered, keyword) for keyword in ASSET_KEYWORDS[asset])
        for asset in asset_classes
    }
    return max(asset_classes, key=lambda asset: counts[asset])


def _london_overnight_start(now_utc: datetime) -> datetime:
    london = ZoneInfo("Europe/London")
    local_now = now_utc.astimezone(london)
    start_day = local_now.date() if local_now.hour >= 21 else local_now.date() - timedelta(days=1)
    local_start = datetime.combine(start_day, datetime.min.time(), london).replace(hour=21)
    return local_start.astimezone(timezone.utc)


def _source_quality(row: pd.Series) -> float:
    publisher = str(row.get("publisher", "")).lower()
    if row.get("source_type") == "Official":
        return 4.0
    if any(name in publisher for name in ("reuters", "associated press", "ap news", "bbc")):
        return 3.0
    if any(name in publisher for name in ("cnbc", "the guardian", "politico", "al jazeera")):
        return 2.2
    if any(name in publisher for name in ("yahoo finance", "investing.com", "tradingview")):
        return 1.2
    return 0.5


def _materiality_score(text: str, event_type: str) -> float:
    """Score an event that actually happened, rather than a preview or opinion."""

    matched = max(
        (weight for pattern, weight in MATERIAL_EVENT_PATTERNS if pattern.search(text)),
        default=0.0,
    )
    lowered = text.lower()
    action_terms = (
        "announces", "announced", "imposes", "imposed", "approves", "approved",
        "suspends", "suspended", "halts", "halted", "launches", "launched",
        "raises", "raised", "cuts", "cut", "holds", "held", "intervenes",
        "intervened", "unexpected", "surprise", "emergency",
    )
    if event_type in {"Central banks", "Geopolitics / policy", "Energy / supply"} and any(
        _contains_term(lowered, term) for term in action_terms
    ):
        matched = max(matched, 4.0)
    if event_type == "Macro data" and re.search(r"\d", lowered) and not PREVIEW_HEADLINES.search(text):
        matched = max(matched, 4.0)
    return matched


def _event_text(row: pd.Series) -> str:
    """Combine a headline and useful synopsis without counting RSS duplicates twice."""

    title = " ".join(str(row.get("title", "")).split()).strip()
    summary = " ".join(str(row.get("summary", "")).split()).strip()
    if not summary or summary == "nan" or summary.lower().startswith(title.lower()):
        return title
    return f"{title} {summary}"


def rank_market_events(
    frame: pd.DataFrame,
    *,
    now: datetime | None = None,
    limit: int = 5,
    window_hours: int | None = None,
    min_importance: float | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    period_start = (
        now_utc - timedelta(hours=window_hours)
        if window_hours is not None
        else _london_overnight_start(now_utc)
    )
    result = frame.copy()
    result["published"] = pd.to_datetime(result["published"], utc=True, errors="coerce")
    result = result.dropna(subset=["published", "title", "url"])
    result = result.loc[(result["published"] >= period_start) & (result["published"] <= now_utc)]
    if result.empty and window_hours is None:
        fallback_start = now_utc - timedelta(hours=36)
        result = frame.copy()
        result["published"] = pd.to_datetime(result["published"], utc=True, errors="coerce")
        result = result.dropna(subset=["published", "title", "url"])
        result = result.loc[(result["published"] >= fallback_start) & (result["published"] <= now_utc)]
    if result.empty:
        return result

    result["classification_text"] = result.apply(_event_text, axis=1)
    result["asset_classes"] = result["classification_text"].map(classify_assets)
    result = result.loc[result["asset_classes"].map(bool)]
    if result.empty:
        return result
    result["event_type"] = result["classification_text"].map(classify_event)
    result["display_title"] = result.apply(
        lambda row: precise_headline(
            str(row["title"]),
            str(row.get("publisher", "")),
            str(row.get("summary", "")),
        ),
        axis=1,
    )
    result["reaction_stated"] = result["title"].map(lambda value: bool(REACTION_PATTERN.search(value)))
    result["free_access_source"] = result.apply(
        lambda row: row["source_type"] == "Official"
        or any(
            name.lower() in row["publisher"].lower()
            for name in FREE_ACCESS_PUBLISHERS
        ),
        axis=1,
    )
    result = result.loc[result["free_access_source"]]
    result = result.loc[
        ~result.apply(
            lambda row: bool(
                PAYWALL_MARKERS.search(f"{row['publisher']} {row['title']}")
            ),
            axis=1,
        )
    ]
    result = result.loc[
        ~(
            (result["source_type"] == "Official")
            & result["title"].str.contains(ADMINISTRATIVE_HEADLINES, na=False)
        )
    ]
    if result.empty:
        return result

    result["story_key"] = result.apply(
        lambda row: _story_key(
            (
                f"{row['classification_text']} U.S."
                if str(row.get("publisher", "")).startswith(("BLS ", "U.S. Bureau of Economic Analysis"))
                else row["classification_text"]
            ),
            row["event_type"],
        ),
        axis=1,
    )
    result["primary_asset"] = result.apply(
        lambda row: _primary_asset(row["classification_text"], row["asset_classes"]),
        axis=1,
    )
    result["normalised_title"] = (
        result["title"].str.lower().str.replace(r"\W+", " ", regex=True).str.strip()
    )
    publisher_count = result.groupby("story_key")["publisher"].transform("nunique")
    headline_variant_count = result.groupby("story_key")["normalised_title"].transform("nunique")
    result["source_count"] = publisher_count.combine(headline_variant_count, min)
    story_assets = result.groupby("story_key")["asset_classes"].transform(
        lambda values: len({asset for assets in values for asset in assets})
    )

    def score(row: pd.Series) -> float:
        title = str(row["title"])
        full_text = str(row["classification_text"])
        age_hours = max((now_utc - row["published"].to_pydatetime()).total_seconds() / 3600, 0)
        recency = max(0.0, 2.0 - age_hours / 12.0)
        impact = min(
            sum(_contains_term(title.lower(), word) for word in HIGH_IMPACT_WORDS),
            3,
        ) * 0.75
        event_base = {
            "Central banks": 3.5,
            "Macro data": 3.5,
            "Geopolitics / policy": 3.5,
            "Energy / supply": 3.0,
            "Corporate / credit": 3.0,
            "Cross-asset / risk sentiment": 0.5,
        }.get(row["event_type"], 0.5)
        materiality = _materiality_score(full_text, row["event_type"])
        breadth = min(len(row["asset_classes"]), 3) * 0.75
        reaction = 1.5 if row["reaction_stated"] else 0.0
        confirmation = min(max(int(row["source_count"]) - 1, 0) * 1.25, 2.5)
        cross_asset_confirmation = min(max(int(story_assets.loc[row.name]) - 1, 0) * 0.5, 1.0)
        preview_penalty = 5.0 if PREVIEW_HEADLINES.search(title) else 0.0
        low_signal_penalty = 3.0 if LOW_SIGNAL_HEADLINES.search(title) else 0.0
        analysis_penalty = 7.5 if ANALYSIS_HEADLINES.search(title) else 0.0
        structural_report_penalty = (
            5.0 if STRUCTURAL_REPORT_HEADLINES.search(title) else 0.0
        )
        non_event_credit_penalty = (
            5.0 if NON_EVENT_CREDIT_HEADLINES.search(title) else 0.0
        )
        promotional_penalty = 6.0 if PROMOTIONAL_HEADLINES.search(title) else 0.0
        earnings_penalty = (
            3.5
            if _contains_term(title.lower(), "earnings")
            and not any(
                _contains_term(title.lower(), term)
                for term in ("default", "downgrade", "bankruptcy", "bank stress")
            )
            else 0.0
        )
        macro_terms = (
            "inflation", "cpi", "ppi", "pce", "payroll", "jobs", "employment",
            "unemployment", "wages", "gdp", "pmi", "retail sales",
        )
        is_macro_release = any(_contains_term(title.lower(), term) for term in macro_terms)
        has_major_market = any(_contains_term(full_text.lower(), term) for term in MAJOR_MACRO_MARKETS)
        has_secondary_market = any(
            _contains_term(full_text.lower(), term) for term in SECONDARY_MACRO_MARKETS
        )
        local_macro_penalty = 0.0
        if is_macro_release and not has_major_market:
            local_macro_penalty = 1.5 if has_secondary_market else 4.0
        return round(
            event_base + materiality + recency + impact + breadth + reaction
            + _source_quality(row) + 0.5 + confirmation + cross_asset_confirmation
            - preview_penalty - low_signal_penalty - analysis_penalty
            - structural_report_penalty - promotional_penalty - earnings_penalty
            - non_event_credit_penalty - local_macro_penalty,
            2,
        )

    result["importance"] = result.apply(score, axis=1)
    if min_importance is not None:
        result = result.loc[result["importance"] >= min_importance]
        if result.empty:
            return result.drop(columns=["classification_text"], errors="ignore").reset_index(drop=True)
    result["story_importance"] = result.groupby("story_key")["importance"].transform("max")
    result["representative_quality"] = result.apply(
        lambda row: (
            (10.0 if row["source_type"] == "Official" else 0.0)
            + _source_quality(row)
            + _materiality_score(row["classification_text"], row["event_type"])
            - (3.0 if ANALYSIS_HEADLINES.search(str(row["title"])) else 0.0)
            - (2.0 if PREVIEW_HEADLINES.search(str(row["title"])) else 0.0)
        ),
        axis=1,
    )
    result = result.sort_values(
        ["story_key", "representative_quality", "importance", "published"],
        ascending=[True, False, False, False],
    )
    result = result.drop_duplicates("story_key", keep="first")
    result["importance"] = result["story_importance"]
    result = result.sort_values(["importance", "published"], ascending=[False, False])
    result = result.drop_duplicates("normalised_title", keep="first")

    selected_indices: list[int] = []
    selected_stories: set[str] = set()
    asset_counts: dict[str, int] = {}
    for index, row in result.iterrows():
        story = row["story_key"]
        asset = row["primary_asset"]
        if story in selected_stories or asset_counts.get(asset, 0) >= 2:
            continue
        selected_indices.append(index)
        selected_stories.add(story)
        asset_counts[asset] = asset_counts.get(asset, 0) + 1
        if len(selected_indices) == limit:
            break

    if len(selected_indices) < limit:
        for index, row in result.iterrows():
            if index in selected_indices or row["story_key"] in selected_stories:
                continue
            selected_indices.append(index)
            selected_stories.add(row["story_key"])
            if len(selected_indices) == limit:
                break

    return (
        result.loc[selected_indices]
        .drop(
            columns=[
                "normalised_title", "classification_text", "story_importance",
                "representative_quality",
            ]
        )
        .reset_index(drop=True)
    )


def rank_key_events(
    frame: pd.DataFrame,
    *,
    now: datetime | None = None,
    limit: int = 5,
) -> pd.DataFrame:
    """Return the highest-conviction distinct stories from the rolling 24 hours."""

    return rank_market_events(
        frame,
        now=now,
        limit=limit,
        window_hours=24,
        min_importance=KEY_EVENT_SCORE,
    )


def rank_important_events(
    frame: pd.DataFrame,
    *,
    now: datetime | None = None,
    hours: int = 24,
    limit: int = 20,
) -> pd.DataFrame:
    """Return a concise rolling timeline of distinct, material market stories."""

    ranked = rank_market_events(
        frame,
        now=now,
        limit=limit,
        window_hours=hours,
        min_importance=IMPORTANT_EVENT_SCORE,
    )
    if ranked.empty:
        return ranked
    return ranked.sort_values("published", ascending=False).reset_index(drop=True)
