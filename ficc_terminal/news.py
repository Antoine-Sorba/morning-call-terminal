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
}

NEWS_DISCOVERY_QUERIES = {
    "Cross-asset markets": (
        '(markets OR bonds OR "stock futures" OR dollar OR oil) '
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
        "inflation", "cpi", "payroll", "jobs", "unemployment",
    ),
    "FX": (
        "dollar", "euro", "sterling", "pound", "yen", "yuan", "currency",
        "currencies", "fx", "exchange rate", "intervention",
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
    "Central banks": ("fed", "fomc", "ecb", "boe", "boj", "central bank", "rate cut", "rate hike"),
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
)

PAYWALL_MARKERS = re.compile(
    r"\b(Bloomberg|Financial Times|Wall Street Journal|WSJ|Nikkei Asia|"
    r"MarketWatch|The Times|CNBC Pro|subscription)\b",
    flags=re.IGNORECASE,
)


def _google_news_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        f"{quote_plus(query)}&hl=en-GB&gl=GB&ceid=GB:en"
    )


def _safe_https_url(value: str) -> str:
    return value if value.startswith("https://") else ""


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
    for index, (name, url, source_type) in enumerate(feeds):
        try:
            payload = client.get(f"market_news_{index}", url)
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
                "published", "title", "url", "publisher", "feed", "source_type",
                "retrieved_at", "stale",
            ]
        )
    return pd.concat(frames, ignore_index=True)


def classify_assets(title: str) -> list[str]:
    lowered = title.lower()
    return [
        asset_class
        for asset_class, keywords in ASSET_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]


def classify_event(title: str) -> str:
    lowered = title.lower()
    for event_type, keywords in EVENT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return event_type
    return "Cross-asset / risk sentiment"


def _market_relevance(asset_classes: list[str]) -> str:
    if not asset_classes:
        return "Check whether the event changed broad risk sentiment before using it in the call."
    joined = ", ".join(asset_classes)
    return f"Check the reaction in {joined}; compare the move with the previous close and related assets."


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

    result["asset_classes"] = result["title"].map(classify_assets)
    result = result.loc[result["asset_classes"].map(bool)]
    if result.empty:
        return result
    result["event_type"] = result["title"].map(classify_event)
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
    if result.empty:
        return result

    def score(row: pd.Series) -> float:
        title = row["title"].lower()
        age_hours = max((now_utc - row["published"].to_pydatetime()).total_seconds() / 3600, 0)
        recency = max(0.0, 5.0 - age_hours / 5.0)
        impact = min(sum(word in title for word in HIGH_IMPACT_WORDS), 3) * 1.4
        breadth = min(len(row["asset_classes"]), 3) * 1.0
        reaction = 3.0 if row["reaction_stated"] else 0.0
        official = 1.5 if row["source_type"] == "Official" else 0.0
        free_source = 2.5 if row["free_access_source"] else -1.0
        return round(recency + impact + breadth + reaction + official + free_source, 2)

    result["importance"] = result.apply(score, axis=1)
    result["market_relevance"] = result["asset_classes"].map(_market_relevance)
    result["normalised_title"] = result["title"].str.lower().str.replace(r"\W+", " ", regex=True).str.strip()
    result = result.sort_values(["importance", "published"], ascending=[False, False])
    result = result.drop_duplicates("normalised_title", keep="first")
    return result.head(limit).drop(columns=["normalised_title"]).reset_index(drop=True)
