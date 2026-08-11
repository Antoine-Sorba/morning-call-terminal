from datetime import datetime, timezone

import pandas as pd

from ficc_terminal.news import classify_assets, parse_news_feed, rank_market_events


def test_news_feed_parser_keeps_source_link() -> None:
    rss = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Test</title><item>
      <title>Oil jumps after supply disruption - Reuters</title>
      <link>https://example.com/oil</link>
      <pubDate>Tue, 11 Aug 2026 06:30:00 GMT</pubDate>
    </item></channel></rss>"""
    frame = parse_news_feed(
        rss,
        feed_name="Market discovery",
        source_type="News discovery",
        retrieved_at="2026-08-11T07:00:00+00:00",
    )
    assert frame.iloc[0]["publisher"] == "Reuters"
    assert frame.iloc[0]["url"] == "https://example.com/oil"


def test_event_ranking_prioritises_reported_market_reaction() -> None:
    frame = pd.DataFrame(
        [
            {
                "published": "2026-08-11T06:30:00Z",
                "title": "Oil jumps after unexpected supply disruption",
                "url": "https://example.com/one",
                "publisher": "Reuters",
                "feed": "Cross-asset markets",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-11T07:00:00Z",
                "stale": False,
            },
            {
                "published": "2026-08-11T06:45:00Z",
                "title": "Central bank publishes an administrative notice",
                "url": "https://example.com/two",
                "publisher": "Central bank",
                "feed": "Official",
                "source_type": "Official",
                "retrieved_at": "2026-08-11T07:00:00Z",
                "stale": False,
            },
        ]
    )
    ranked = rank_market_events(
        frame,
        now=datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc),
        limit=5,
    )
    assert ranked.iloc[0]["title"].startswith("Oil jumps")
    assert bool(ranked.iloc[0]["reaction_stated"])
    assert "Commodities" in ranked.iloc[0]["asset_classes"]


def test_asset_classification_is_cross_asset() -> None:
    assets = classify_assets("Dollar rises as Treasury yields jump; stocks fall")
    assert {"Rates", "FX", "Equities"}.issubset(set(assets))


def test_event_ranking_excludes_known_paywalled_publishers() -> None:
    frame = pd.DataFrame(
        [
            {
                "published": "2026-08-11T06:30:00Z",
                "title": "Dollar rises as bond yields climb",
                "url": "https://example.com/bloomberg",
                "publisher": "Bloomberg",
                "feed": "Cross-asset markets",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-11T07:00:00Z",
                "stale": False,
            },
            {
                "published": "2026-08-11T06:35:00Z",
                "title": "Oil rises after supply disruption",
                "url": "https://example.com/reuters",
                "publisher": "Reuters",
                "feed": "Cross-asset markets",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-11T07:00:00Z",
                "stale": False,
            },
        ]
    )
    ranked = rank_market_events(
        frame,
        now=datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc),
    )
    assert ranked["publisher"].tolist() == ["Reuters"]
    assert ranked["free_access_source"].all()
