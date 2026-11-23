from datetime import UTC, datetime
from typing import Any

from kindle_dash.feed import FeedState, Tweet, parse_timeline, update

NOW = datetime(2026, 11, 23, 21, 0, tzinfo=UTC)


def tweet(id: str, text: str, **extra: Any) -> dict[str, Any]:
    return {
        "__typename": "Tweet",
        "core": {"user_results": {"result": {"core": {"screen_name": f"u{id}", "name": "U"}}}},
        "legacy": {
            "id_str": id,
            "created_at": "Mon Nov 23 20:00:00 +0000 2026",
            "full_text": text,
            "favorite_count": 1,
            "entities": {"urls": [{"url": "https://t.co/a", "display_url": "example.com/a"}]},
            **extra.pop("legacy", {}),
        },
        **extra,
    }


def item(result: dict[str, Any], **content: Any) -> dict[str, Any]:
    return {"tweet_results": {"result": result}, **content}


def timeline(*entries: dict[str, Any]) -> list[Any]:
    body = {"instructions": [{"type": "TimelineAddEntries", "entries": list(entries)}]}
    return [{"data": {"home": {"home_timeline_urt": body}}}]


RETWEET = {"retweeted_status_result": {"result": tweet("5", "Orig")}}
NOTE = {"note_tweet_results": {"result": {"text": "Long"}}}


def test_parse_timeline_reads_threads_retweets_and_long_posts_but_not_ads() -> None:
    raw = timeline(
        {
            "entryId": "tweet-1",
            "content": {"itemContent": item(tweet("1", "Launch https://t.co/a"))},
        },
        {
            "entryId": "promoted-tweet-2",
            "content": {"itemContent": item(tweet("2", "Buy"), promotedMetadata={})},
        },
        {
            "entryId": "home-conversation-3",
            "content": {"items": [{"item": {"itemContent": item(tweet("3", "Thread"))}}]},
        },
        {
            "entryId": "tweet-4",
            "content": {"itemContent": item(tweet("4", "RT", legacy=RETWEET))},
        },
        {
            "entryId": "tweet-6",
            "content": {"itemContent": item(tweet("6", "Short…", note_tweet=NOTE))},
        },
    )

    tweets = {t.id: t.text for t in parse_timeline(raw)}

    assert tweets == {"1": "Launch example.com/a", "3": "Thread", "5": "Orig", "6": "Long"}


def test_update_sends_each_tweet_to_the_model_once_and_keeps_only_important_picks() -> None:
    tweets = [
        Tweet(id=i, author="a", name="A", posted_at=NOW, text=f"t{i}", likes=0) for i in "123"
    ]
    batches: list[list[str]] = []

    def pick(batch: list[Tweet], _recent: list[str]) -> list[Any]:
        batches.append([t.id for t in batch])
        return [
            {"id": "1", "headline": "Big", "summary": "S", "importance": 5},
            {"id": "2", "headline": "Meh", "summary": "S", "importance": 2},
            {"id": "9", "headline": "Made up", "summary": "S", "importance": 5},
        ]

    state = update(FeedState(), tweets, NOW, pick)
    again = update(state, tweets, NOW, pick)

    assert [i.headline for i in state.items] == ["Big"]
    assert batches == [["1", "2", "3"]], "already-seen tweets are not sent again"
    assert again == state
