import argparse
import html
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from kindle_dash.settings import Settings

log = logging.getLogger(__name__)
TIMELINE_JS = Path(__file__).with_name("x_timeline.js")
PICK_MAX_AGE = timedelta(hours=2)
SHOW_MAX_AGE = timedelta(hours=12)
MAX_BATCH = 60
KEEP_ITEMS = 30
KEEP_SEEN = 3000
MIN_IMPORTANCE = 4
X_DATE = "%a %b %d %H:%M:%S %z %Y"


class FeedError(Exception):
    pass


class Tweet(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    author: str
    name: str
    posted_at: datetime
    text: str
    likes: int
    quoted: str | None = None


class Pick(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    headline: Annotated[str, Field(min_length=1, max_length=70)]
    summary: Annotated[str, Field(min_length=1, max_length=200)]
    importance: Annotated[int, Field(ge=1, le=5)]


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    author: str
    name: str
    posted_at: datetime
    likes: int
    headline: str
    summary: str
    text: str


class FeedState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: list[Item] = []
    seen: list[str] = []


def _tweet_results(raw: list[Any]) -> Iterator[Any]:
    for body in raw:
        for instruction in body["data"]["home"]["home_timeline_urt"]["instructions"]:
            for entry in instruction.get("entries", []):
                content = entry["content"]
                contents = [i["item"]["itemContent"] for i in content.get("items", [])]
                if "itemContent" in content:
                    contents.append(content["itemContent"])
                for item in contents:
                    result = item.get("tweet_results", {}).get("result")
                    if result and "promotedMetadata" not in item:
                        yield result


def _text(tweet: Any) -> str:
    note = tweet.get("note_tweet", {}).get("note_tweet_results", {}).get("result")
    legacy = tweet["legacy"]
    text, entities = (
        (note["text"], note.get("entity_set", {}))
        if note
        else (
            legacy["full_text"],
            legacy.get("entities", {}),
        )
    )
    for url in entities.get("urls", []):
        text = text.replace(url["url"], url.get("display_url", ""))
    for media in legacy.get("entities", {}).get("media", []):
        text = text.replace(media["url"], "")
    return html.unescape(text).strip()


def _tweet(result: Any) -> Tweet | None:
    tweet = result.get("tweet", result)
    if "legacy" not in tweet:
        return None
    retweeted = tweet["legacy"].get("retweeted_status_result", {}).get("result")
    if retweeted:
        return _tweet(retweeted)
    user = tweet["core"]["user_results"]["result"]["core"]
    quoted = tweet.get("quoted_status_result", {}).get("result")
    quoted_tweet = _tweet(quoted) if quoted else None
    return Tweet(
        id=tweet["legacy"]["id_str"],
        author=user["screen_name"],
        name=user["name"],
        posted_at=datetime.strptime(tweet["legacy"]["created_at"], X_DATE),
        text=_text(tweet),
        likes=tweet["legacy"]["favorite_count"],
        quoted=f"@{quoted_tweet.author}: {quoted_tweet.text}" if quoted_tweet else None,
    )


def parse_timeline(raw: list[Any]) -> list[Tweet]:
    tweets: dict[str, Tweet] = {}
    for result in _tweet_results(raw):
        tweet = _tweet(result)
        if tweet:
            tweets.setdefault(tweet.id, tweet)
    return list(tweets.values())


def capture_timeline(browser: Path) -> list[Any]:
    try:
        done = subprocess.run(
            [str(browser), "--raw", "run-code", TIMELINE_JS.read_text()],
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
        raw = TypeAdapter(list[Any]).validate_json(json.loads(done.stdout))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValidationError) as e:
        raise FeedError(f"reading the X timeline failed: {e}") from e
    if not raw:
        raise FeedError("the X timeline returned nothing; is the browser logged in to X?")
    return raw


PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "headline": {"type": "string"},
                    "summary": {"type": "string"},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["id", "headline", "summary", "importance"],
            },
        }
    },
    "required": ["picks"],
}


def prompt(tweets: list[Tweet], recent: list[str], interests: str) -> str:
    batch = [
        {"id": t.id, "author": t.author, "likes": t.likes, "text": t.text, "quoting": t.quoted}
        for t in tweets
    ]
    return (
        "You pick tweets for a news feed on a wall display. The reader follows "
        f"{interests}. From the tweets below, pick at most 5 that carry real news or a "
        "substantive insight: launches, releases, results, announcements, notable analysis. "
        "Skip jokes, hype, engagement bait, job ads, giveaways, and replies or images that "
        "make no sense without context. Skip opinions and commentary unless they come with "
        "new facts. Skip any story already in the feed. Most batches have nothing worth "
        "picking; return an empty list then.\n\n"
        "Rate each pick's importance to this reader from 1 to 5: 5 is a major launch or "
        "event they must not miss, 4 is clearly newsworthy, 3 or less is mildly "
        "interesting. Write a neutral headline about the news itself, at most 50 "
        "characters, and a one-sentence summary of at most 140 characters, in plain "
        "British English. Use names exactly as written in the tweet.\n\n"
        f"Already in the feed:\n{json.dumps(recent, ensure_ascii=False)}\n\n"
        f"Tweets:\n{json.dumps(batch, ensure_ascii=False)}"
    )


def ask_model(client: httpx.Client, settings: Settings, text: str) -> list[Any]:
    try:
        response = client.post(
            f"{str(settings.lmstudio_url).rstrip('/')}/chat/completions",
            json={
                "model": settings.feed_model,
                "messages": [{"role": "user", "content": text}],
                "temperature": 0.2,
                "ttl": 300,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "picks", "strict": True, "schema": PICK_SCHEMA},
                },
            },
            timeout=600,
        )
        response.raise_for_status()
        return json.loads(response.json()["choices"][0]["message"]["content"])["picks"]
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
        raise FeedError(f"the local model failed: {e}") from e


def update(
    state: FeedState,
    tweets: list[Tweet],
    now: datetime,
    pick: Callable[[list[Tweet], list[str]], list[Any]],
) -> FeedState:
    seen = set(state.seen)
    fresh = [t for t in tweets if t.id not in seen and now - t.posted_at <= PICK_MAX_AGE]
    fresh = sorted(fresh, key=lambda t: t.posted_at, reverse=True)[:MAX_BATCH]
    if not fresh:
        return state
    by_id = {t.id: t for t in fresh}
    added: list[Item] = []
    for raw in pick(fresh, [i.headline for i in state.items[:15]]):
        try:
            p = Pick.model_validate(raw)
        except ValidationError as e:
            log.warning("dropped a pick: %s", e.errors()[0]["msg"])
            continue
        t = by_id.get(p.id)
        if t is None or any(i.id == t.id for i in added):
            log.warning("dropped a pick for unknown tweet %s", p.id)
            continue
        if p.importance < MIN_IMPORTANCE:
            log.info("skipped (importance %d): %s", p.importance, p.headline)
            continue
        added.append(
            Item(
                id=t.id,
                author=t.author,
                name=t.name,
                posted_at=t.posted_at,
                likes=t.likes,
                headline=p.headline,
                summary=p.summary,
                text=f"{t.text}\n\nQuoting {t.quoted}" if t.quoted else t.text,
            )
        )
    added.sort(key=lambda i: i.posted_at, reverse=True)
    return FeedState(
        items=(added + list(state.items))[:KEEP_ITEMS],
        seen=([t.id for t in fresh] + list(state.seen))[:KEEP_SEEN],
    )


def latest(state: FeedState, now: datetime, count: int) -> list[tuple[Item, str]]:
    shown: list[tuple[Item, str]] = []
    for item in state.items:
        age = now - item.posted_at
        if age > SHOW_MAX_AGE or len(shown) == count:
            continue
        minutes = max(int(age.total_seconds() // 60), 0)
        shown.append((item, f"{minutes} min ago" if minutes < 60 else f"{minutes // 60} h ago"))
    return shown


def feed_path(feed_dir: Path) -> Path:
    return feed_dir / "feed.json"


def load_feed(feed_dir: Path) -> FeedState:
    path = feed_path(feed_dir)
    if not path.exists():
        return FeedState()
    try:
        return FeedState.model_validate_json(path.read_text())
    except ValidationError as e:
        log.warning("ignoring invalid feed %s: %s", path, e)
        return FeedState()


def save_feed(feed_dir: Path, state: FeedState) -> None:
    feed_dir.mkdir(parents=True, exist_ok=True)
    path = feed_path(feed_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=1))
    os.replace(tmp, path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="kindle-dash-feed")
    parser.add_argument("--dry-run", action="store_true", help="print picks, save nothing")
    args = parser.parse_args()
    settings = Settings()
    now = datetime.now(settings.tz)
    if not args.dry_run and not settings.feed_start_hour <= now.hour < settings.feed_end_hour:
        log.info("outside feed hours, skipping")
        return
    try:
        tweets = parse_timeline(capture_timeline(settings.hermes_browser))
        state = load_feed(settings.feed_dir)
        with httpx.Client() as client:
            new = update(
                state,
                tweets,
                now,
                lambda batch, recent: ask_model(
                    client, settings, prompt(batch, recent, settings.feed_interests)
                ),
            )
    except FeedError as e:
        log.error("%s", e)
        sys.exit(1)
    known = {i.id for i in state.items}
    added = [i for i in new.items if i.id not in known]
    fresh = len(set(new.seen) - set(state.seen))
    log.info("%d tweets, %d new, %d picked", len(tweets), fresh, len(added))
    for item in added:
        log.info("picked @%s: %s", item.author, item.headline)
    if not args.dry_run:
        save_feed(settings.feed_dir, new)
