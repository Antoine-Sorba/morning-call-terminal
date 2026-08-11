from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
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
}

NEWS_DISCOVERY_QUERIES = {
    "Cross-asset markets": (
        '(markets OR bonds OR "stock futures" OR dollar OR oil) '
        '(jumps OR falls OR rises OR drops OR rallies OR slides) when:1d'
    ),
    "Credit markets": (
        '("credit spreads" OR "corporate bonds" OR "high yield" OR default OR downgrade) '
        '(widens OR tightens OR rises OR falls OR jumps OR drops) when:1d'
    ),
    "Equity markets": (
        '("S&P 500" OR Nasdaq OR Stoxx OR Nikkei OR "stock futures") '
        '(jumps OR falls OR rises OR drops OR rallies OR slides) when:1d'
    ),
    "Policy and macro": (
        '(Fed OR ECB OR BoE OR BoJ OR inflation OR payrolls OR tariffs OR sanctions) '
        '(markets OR bonds OR dollar OR stocks) when:1d'
    ),
    "World and supply events": (
        '(war OR attack OR election OR OPEC OR "supply disruption") '
        '(markets OR oil OR bonds OR currency OR stocks) when:1d'
    ),
}

ASSET_KEYWORDS = {
    "Rates": (
        "bond", "bonds", "yield", "yields", "treasury", "treasuries", "gilt",
        "bund", "rate", "rates", "fed", "fomc", "ecb", "boe", "boj",
        "rba", "reserve bank of australia", "cash rate", "inflation", "cpi",
        "payroll", "jobs", "unemployment",
    ),
    "FX": (
        "dollar", "euro", "sterling", "pound", "yen", "yuan", "currency",
        "currencies", "fx", "exchange rate", "intervention", "australian dollar",
        "usd", "eur", "gbp", "jpy", "aud", "cad", "chf",
        "usdjpy", "eurusd", "gbpusd", "audusd", "usdcad", "usdchf", "dxy",
    ),
    "Credit": (
        "credit", "spread", "spreads", "default", "downgrade", "bankruptcy",
        "debt", "corporate bond", "bank stress", "liquidity",
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
    "Macro data": ("inflation", "cpi", "payroll", "jobs", "unemployment", "gdp", "pmi", "retail sales"),
    "Geopolitics / policy": ("war", "attack", "sanction", "tariff", "election", "government", "intervention"),
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

PAYWALL_MARKERS = re.compile(
    r"\b(Bloomberg|Financial Times|Wall Street Journal|WSJ|Nikkei Asia|"
    r"MarketWatch|The Times|CNBC Pro|subscription)\b",
    flags=re.IGNORECASE,
)

ADMINISTRATIVE_HEADLINES = re.compile(
    r"\b(?:concert|invite the public|turnover surveys?|annual report|procurement|"
    r"vacancy|museum|archive|conference registration)\b",
    flags=re.IGNORECASE,
)

STORY_RULES = (
    ("middle_east_energy", ("oil", "brent", "wti"), ("iran", "hormuz", "oman", "middle east")),
    ("opec_supply", ("opec",), ("production", "output", "supply", "quota")),
    (
        "us_inflation",
        ("inflation", "cpi"),
        ("us", "u.s.", "treasury", "fed", "market", "markets", "gold", "stock", "stocks", "nasdaq", "s&p", "rally"),
    ),
    ("us_labour", ("payroll", "jobs", "unemployment", "labour"), ("us", "u.s.", "fed")),
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


def _publisher_and_title(entry: object, fallback: str) -> tuple[str, str]:
    title = str(entry.get("title", "Untitled release")).strip()
    source = entry.get("source", {}) or {}
    publisher = str(source.get("title", "")).strip() if hasattr(source, "get") else ""
    if " - " in title:
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
        publisher, title = _publisher_and_title(entry, feed_name)
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
                "summary": re.sub(r"<[^>]+>", " ", str(entry.get("summary", ""))).strip(),
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
    frames = []
    feeds = [
        (name, url, "Official") for name, url in OFFICIAL_FEEDS.items()
    ] + [
        (name, _google_news_url(query), "News discovery")
        for name, query in NEWS_DISCOVERY_QUERIES.items()
    ]
    for name, url, source_type in feeds:
        try:
            cache_key = re.sub(r"\W+", "_", name.lower()).strip("_")
            payload = client.get(f"market_news_{cache_key}", url)
            frame = parse_news_feed(
                payload.content,
                feed_name=name,
                source_type=source_type,
                retrieved_at=payload.retrieved_at,
                stale=payload.stale,
            )
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
    if (
        any(_contains_term(lowered, term) for term in ("iran", "hormuz", "oman-iran"))
        or (_contains_term(lowered, "middle east") and _contains_term(lowered, "oil"))
        or (_contains_term(lowered, "oil") and _contains_term(lowered, "war uncertainty"))
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


def rank_market_events(
    frame: pd.DataFrame,
    *,
    now: datetime | None = None,
    limit: int = 5,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    overnight_start = _london_overnight_start(now_utc)
    result = frame.copy()
    result["published"] = pd.to_datetime(result["published"], utc=True, errors="coerce")
    result = result.dropna(subset=["published", "title", "url"])
    result = result.loc[(result["published"] >= overnight_start) & (result["published"] <= now_utc)]
    if result.empty:
        fallback_start = now_utc - timedelta(hours=36)
        result = frame.copy()
        result["published"] = pd.to_datetime(result["published"], utc=True, errors="coerce")
        result = result.dropna(subset=["published", "title", "url"])
        result = result.loc[(result["published"] >= fallback_start) & (result["published"] <= now_utc)]
    if result.empty:
        return result

    result["classification_text"] = result.apply(
        lambda row: " ".join(
            value
            for value in (
                str(row["title"]),
                str(row.get("publisher", "")),
                str(row.get("summary", "")),
            )
            if value and value != "nan"
        ),
        axis=1,
    )
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

    def score(row: pd.Series) -> float:
        title = row["title"].lower()
        age_hours = max((now_utc - row["published"].to_pydatetime()).total_seconds() / 3600, 0)
        recency = max(0.0, 5.0 - age_hours / 5.0)
        impact = min(sum(_contains_term(title, word) for word in HIGH_IMPACT_WORDS), 3) * 1.4
        breadth = min(len(row["asset_classes"]), 3) * 1.0
        reaction = 3.0 if row["reaction_stated"] else 0.0
        official = 1.5 if row["source_type"] == "Official" else 0.0
        free_source = 2.5 if row["free_access_source"] else -1.0
        source_quality = 0.0
        if row["source_type"] == "Official":
            source_quality = 4.0
        elif any(name in row["publisher"].lower() for name in ("reuters", "associated press", "ap news", "bbc", "cnbc")):
            source_quality = 2.0
        elif any(name in row["publisher"].lower() for name in ("yahoo finance", "oilprice.com")):
            source_quality = 1.0
        promotional_penalty = 4.0 if PROMOTIONAL_HEADLINES.search(row["title"]) else 0.0
        return round(
            recency + impact + breadth + reaction + official + free_source
            + source_quality - promotional_penalty,
            2,
        )

    result["importance"] = result.apply(score, axis=1)
    result["story_key"] = result.apply(
        lambda row: _story_key(row["classification_text"], row["event_type"]),
        axis=1,
    )
    result["primary_asset"] = result.apply(
        lambda row: _primary_asset(row["classification_text"], row["asset_classes"]),
        axis=1,
    )
    result["normalised_title"] = result["title"].str.lower().str.replace(r"\W+", " ", regex=True).str.strip()
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
        .drop(columns=["normalised_title", "classification_text"])
        .reset_index(drop=True)
    )
