import asyncio
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import recurring_ical_events  # pyright: ignore[reportMissingTypeStubs]
from icalendar import Calendar


class CalendarError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Event:
    title: str
    start: datetime
    end: datetime
    all_day: bool


@dataclass(frozen=True, slots=True)
class Day:
    date: date
    events: list[Event]


def _as_datetime(value: date | datetime, tz: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(tz) if value.tzinfo else value.replace(tzinfo=tz)
    return datetime(value.year, value.month, value.day, tzinfo=tz)


def parse_events(ics: bytes, start: datetime, end: datetime, tz: ZoneInfo) -> list[Event]:
    try:
        cal = Calendar.from_ical(ics)
    except ValueError as e:
        raise CalendarError("calendar feed is not valid iCal") from e
    events: list[Event] = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        dtstart = ev.get("DTSTART").dt
        dtend_prop = ev.get("DTEND")
        dtend = dtend_prop.dt if dtend_prop else dtstart
        events.append(
            Event(
                title=str(ev.get("SUMMARY", "(no title)")),
                start=_as_datetime(dtstart, tz),
                end=_as_datetime(dtend, tz),
                all_day=not isinstance(dtstart, datetime),
            )
        )
    return events


def group_by_day(events: list[Event], first: date, days: int) -> list[Day]:
    out: list[Day] = []
    for i in range(days):
        d = first + timedelta(days=i)
        todays = [
            e for e in events if e.start.date() <= d and (e.end.date() > d or e.start.date() == d)
        ]
        todays.sort(key=lambda e: (not e.all_day, e.start, e.title))
        out.append(Day(date=d, events=todays))
    return out


class CalendarFeed:
    def __init__(self, urls: list[str], tz: ZoneInfo, days: int, ttl_seconds: int = 300) -> None:
        self._urls = urls
        self._tz = tz
        self._days = days
        self._ttl = ttl_seconds
        self._cache: tuple[float, date, list[Day]] | None = None
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=True)

    @property
    def configured(self) -> bool:
        return bool(self._urls)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _fetch(self, url: str) -> bytes:
        try:
            r = await self._client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise CalendarError(f"calendar fetch failed ({type(e).__name__})") from e
        return r.content

    async def days(self) -> list[Day]:
        today = datetime.now(self._tz).date()
        if (
            self._cache
            and self._cache[1] == today
            and time.monotonic() - self._cache[0] < self._ttl
        ):
            return self._cache[2]
        start = datetime(today.year, today.month, today.day, tzinfo=self._tz)
        end = start + timedelta(days=self._days)
        bodies = await asyncio.gather(*(self._fetch(u) for u in self._urls))
        events = [e for body in bodies for e in parse_events(body, start, end, self._tz)]
        result = group_by_day(events, today, self._days)
        self._cache = (time.monotonic(), today, result)
        return result
