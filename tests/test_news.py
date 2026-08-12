from datetime import datetime, timezone

import pandas as pd

from ficc_terminal.news import (
    classify_assets,
    parse_news_feed,
    precise_headline,
    rank_important_events,
    rank_key_events,
    rank_market_events,
)


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


def test_asset_classification_does_not_find_rate_inside_strategic() -> None:
    assets = classify_assets("US Strategic Petroleum Reserve falls as oil jumps")
    assert "Rates" not in assets
    assert "Commodities" in assets


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


def test_similar_oil_headlines_count_as_one_market_story() -> None:
    titles = [
        "Oil pares gains as traders weigh Oman-Iran talks",
        "Oil rises above $89 as Strait of Hormuz deal hopes fade",
        "Oil Jumps Over 2% as U.S.-Iran Peace Prospects Fade and Hormuz Risks Persist",
        "Treasury yields up as oil prices jump and investors await inflation data",
        "Yen strengthens after Bank of Japan intervention warning",
        "Credit spreads widen after major company default",
        "Nasdaq futures fall after technology earnings disappoint",
    ]
    publishers = ["Reuters", "Yahoo Finance", "Yahoo Finance", "CNBC", "Reuters", "Reuters", "CNBC"]
    frame = pd.DataFrame(
        [
            {
                "published": f"2026-08-11T{6 + index // 2:02d}:{index % 2 * 20:02d}:00Z",
                "title": title,
                "url": f"https://example.com/{index}",
                "publisher": publishers[index],
                "feed": "Cross-asset markets",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-11T08:00:00Z",
                "stale": False,
            }
            for index, title in enumerate(titles)
        ]
    )
    ranked = rank_market_events(
        frame,
        now=datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc),
        limit=5,
    )
    assert len(ranked) == 5
    assert (ranked["story_key"] == "middle_east_energy").sum() == 1
    assert ranked["story_key"].nunique() == 5


def test_treasury_headline_is_made_more_precise() -> None:
    assert precise_headline(
        "Treasury yields up as oil prices jump and investors await inflation data"
    ) == "US Treasury yields rise as oil climbs ahead of inflation data"


def test_rba_official_summary_becomes_a_precise_headline() -> None:
    assert precise_headline(
        "Statement by the Monetary Policy Board: Monetary Policy Decision",
        "Reserve Bank of Australia",
        "At its meeting today, the Board decided to leave the cash rate target unchanged at 4.35 per cent.",
    ) == "RBA leaves cash rate at 4.35%"


def test_cross_asset_oil_war_headline_is_grouped_with_hormuz_story() -> None:
    titles = [
        "IXIC: Nasdaq slips as oil jumps 5% amid war uncertainty",
        "Oil rises above $89 as Strait of Hormuz deal hopes fade",
        "RBA leaves the cash rate unchanged",
    ]
    frame = pd.DataFrame(
        [
            {
                "published": f"2026-08-11T0{6 + index}:00:00Z",
                "title": title,
                "url": f"https://example.com/{index}",
                "publisher": "Reuters",
                "feed": "Cross-asset markets",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-11T09:00:00Z",
                "stale": False,
            }
            for index, title in enumerate(titles)
        ]
    )
    ranked = rank_market_events(
        frame,
        now=datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc),
        limit=5,
    )
    assert (ranked["story_key"] == "middle_east_energy").sum() == 1


def test_important_timeline_keeps_an_earlier_material_story_without_noise() -> None:
    stories = [
        ("2026-08-11T10:00:00Z", "OPEC oil output exceeds quota targets", "Reuters"),
        ("2026-08-11T12:00:00Z", "Dollar falls after surprise central bank intervention", "Reuters"),
        ("2026-08-11T13:00:00Z", "Credit spreads widen after major company default", "Reuters"),
        ("2026-08-11T14:00:00Z", "Nasdaq futures plunge after earnings shock", "CNBC"),
        ("2026-08-11T15:00:00Z", "US Treasury yields surge after inflation surprise", "Reuters"),
        ("2026-08-11T16:00:00Z", "Gold rallies after emergency sanctions announcement", "BBC"),
        ("2026-08-11T17:00:00Z", "New Zealand stocks end slightly lower", "TradingView"),
    ]
    frame = pd.DataFrame(
        [
            {
                "published": published,
                "title": title,
                "url": f"https://example.com/{index}",
                "publisher": publisher,
                "feed": "Cross-asset markets",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-11T18:00:00Z",
                "stale": False,
            }
            for index, (published, title, publisher) in enumerate(stories)
        ]
    )
    now = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)

    key_events = rank_key_events(frame, now=now, limit=5)
    timeline = rank_important_events(frame, now=now, limit=20)

    earlier_story = stories[0][1]
    noise = stories[-1][1]
    assert all("earnings" not in title.lower() for title in key_events["title"])
    assert earlier_story in timeline["title"].tolist()
    assert noise not in timeline["title"].tolist()
    assert timeline["story_key"].nunique() == len(timeline)


def test_important_timeline_uses_a_strict_rolling_24_hour_window() -> None:
    frame = pd.DataFrame(
        [
            {
                "published": published,
                "title": title,
                "url": f"https://example.com/{index}",
                "publisher": "Reuters",
                "feed": "Cross-asset markets",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-11T18:00:00Z",
                "stale": False,
            }
            for index, (published, title) in enumerate(
                [
                    ("2026-08-10T19:00:00Z", "Oil jumps after unexpected supply disruption"),
                    ("2026-08-10T17:00:00Z", "Dollar plunges after surprise central bank intervention"),
                ]
            )
        ]
    )

    timeline = rank_important_events(
        frame,
        now=datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc),
    )

    assert timeline["title"].tolist() == ["Oil jumps after unexpected supply disruption"]


def test_key_events_favour_major_older_release_over_recent_market_noise() -> None:
    frame = pd.DataFrame(
        [
            {
                "published": "2026-08-11T22:00:00Z",
                "title": "US CPI rises 0.4%, above forecasts as core inflation accelerates",
                "url": "https://example.com/cpi",
                "publisher": "Reuters",
                "feed": "Major macro releases",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-12T18:00:00Z",
                "stale": False,
            },
            {
                "published": "2026-08-12T17:50:00Z",
                "title": "New Zealand stocks edge slightly higher in cautious trading",
                "url": "https://example.com/minor",
                "publisher": "TradingView",
                "feed": "Cross-asset reaction",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-12T18:00:00Z",
                "stale": False,
            },
            {
                "published": "2026-08-12T17:45:00Z",
                "title": "US Treasury yields rise ahead of inflation data",
                "url": "https://example.com/preview",
                "publisher": "Reuters",
                "feed": "Cross-asset reaction",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-12T18:00:00Z",
                "stale": False,
            },
        ]
    )

    ranked = rank_key_events(
        frame,
        now=datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc),
    )

    assert ranked["title"].tolist() == [
        "US CPI rises 0.4%, above forecasts as core inflation accelerates"
    ]


def test_key_events_group_duplicate_coverage_and_reward_confirmation() -> None:
    frame = pd.DataFrame(
        [
            {
                "published": published,
                "title": title,
                "url": f"https://example.com/{index}",
                "publisher": publisher,
                "feed": "Energy and supply",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-12T08:00:00Z",
                "stale": False,
            }
            for index, (published, title, publisher) in enumerate(
                [
                    (
                        "2026-08-12T06:30:00Z",
                        "Oil jumps after attack disrupts shipping through Hormuz",
                        "Reuters",
                    ),
                    (
                        "2026-08-12T06:35:00Z",
                        "Hormuz shipping disrupted after attack sends oil surging",
                        "BBC",
                    ),
                ]
            )
        ]
    )

    ranked = rank_key_events(
        frame,
        now=datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc),
    )

    assert len(ranked) == 1
    assert ranked.iloc[0]["story_key"] == "middle_east_energy"
    assert ranked.iloc[0]["source_count"] == 2


def test_official_release_is_displayed_for_a_confirmed_macro_story() -> None:
    frame = pd.DataFrame(
        [
            {
                "published": "2026-08-12T12:30:00Z",
                "title": "CPI for all items increases 0.4% in July; shelter rises",
                "summary": "",
                "url": "https://www.bls.gov/news.release/cpi.nr0.htm",
                "publisher": "BLS Consumer Price Index",
                "feed": "BLS Consumer Price Index",
                "source_type": "Official",
                "retrieved_at": "2026-08-12T13:00:00Z",
                "stale": False,
            },
            {
                "published": "2026-08-12T12:35:00Z",
                "title": "Gold jumps after US inflation surprises markets",
                "summary": "",
                "url": "https://example.com/reaction",
                "publisher": "Reuters",
                "feed": "Cross-asset reaction",
                "source_type": "News discovery",
                "retrieved_at": "2026-08-12T13:00:00Z",
                "stale": False,
            },
        ]
    )

    ranked = rank_key_events(
        frame,
        now=datetime(2026, 8, 12, 13, 0, tzinfo=timezone.utc),
    )

    assert len(ranked) == 1
    assert ranked.iloc[0]["source_type"] == "Official"
    assert ranked.iloc[0]["publisher"] == "BLS Consumer Price Index"
