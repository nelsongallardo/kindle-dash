from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from kindle_dash.calendar_feed import CalendarError, CalendarFeed, group_by_day, parse_events

LONDON = ZoneInfo("Europe/London")
SECRET_URL = "https://calendar.example/ical/private-0123456789abcdef0123/basic.ics"

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:gym
SUMMARY:Gym
DTSTART;TZID=Europe/London:20261102T070000
DTEND;TZID=Europe/London:20261102T080000
RRULE:FREQ=WEEKLY;BYDAY=MO
END:VEVENT
BEGIN:VEVENT
UID:holiday
SUMMARY:Holiday
DTSTART;VALUE=DATE:20261124
DTEND;VALUE=DATE:20261126
END:VEVENT
BEGIN:VEVENT
UID:nycall
SUMMARY:NY call
DTSTART;TZID=America/New_York:20261123T200000
DTEND;TZID=America/New_York:20261123T210000
END:VEVENT
END:VCALENDAR
"""


def test_week_view_places_recurring_all_day_and_foreign_tz_events_on_london_days() -> None:
    monday = date(2026, 11, 23)
    start = datetime(2026, 11, 23, tzinfo=LONDON)
    events = parse_events(ICS, start, start + timedelta(days=7), LONDON)

    days = group_by_day(events, monday, 7)
    shown = {
        d.date: [(e.title, e.all_day, e.start.strftime("%H:%M")) for e in d.events] for d in days
    }

    assert shown[date(2026, 11, 23)] == [("Gym", False, "07:00")], "weekly event on its Monday"
    assert shown[date(2026, 11, 24)] == [("Holiday", True, "00:00"), ("NY call", False, "01:00")], (
        "all-day event starts; 20:00 New York is 01:00 next day in London"
    )
    assert shown[date(2026, 11, 25)] == [("Holiday", True, "00:00")], "multi-day event continues"
    assert shown[date(2026, 11, 26)] == [], "all-day DTEND is exclusive"
    assert all(e.title != "Gym" for d in days[1:] for e in d.events), (
        "next Monday's Gym is outside the 7-day window"
    )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, html="<html>Sign in</html>"),
        httpx.Response(500),
    ],
    ids=["not-ical", "server-error"],
)
@respx.mock
async def test_bad_feed_raises_calendar_error_without_leaking_the_secret_url(
    response: httpx.Response,
) -> None:
    respx.get(SECRET_URL).mock(return_value=response)
    feed = CalendarFeed([SECRET_URL], LONDON, days=7)

    with pytest.raises(CalendarError) as excinfo:
        await feed.days()

    assert "private-" not in str(excinfo.value), "error message must not contain the secret URL"
    await feed.aclose()
