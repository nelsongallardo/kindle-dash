from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import respx

from kindle_dash.homeassistant import HomeAssistant
from kindle_dash.weather import to_forecast

LONDON = ZoneInfo("Europe/London")


def payload() -> dict[str, object]:
    start = datetime(2026, 11, 23)
    times = [start + timedelta(hours=i) for i in range(48)]
    codes = [0] * 48
    codes[19] = 2
    return {
        "current": {
            "temperature_2m": 6.4,
            "apparent_temperature": 3.1,
            "weather_code": 0,
            "wind_speed_10m": 9.6,
            "is_day": 0,
        },
        "hourly": {
            "time": [t.isoformat(timespec="minutes") for t in times],
            "temperature_2m": [float(t.hour) for t in times],
            "weather_code": codes,
            "precipitation_probability": [None] * 22 + [30, 60] + [None] * 24,
            "is_day": [1 if 8 <= t.hour < 16 else 0 for t in times],
        },
        "daily": {
            "time": ["2026-11-23", "2026-11-24"],
            "weather_code": [0, 61],
            "temperature_2m_max": [8.0, 10.0],
            "temperature_2m_min": [2.0, 5.0],
            "precipitation_probability_max": [0, 80],
            "sunrise": ["2026-11-23T07:31", "2026-11-24T07:33"],
            "sunset": ["2026-11-23T16:01", "2026-11-24T16:00"],
        },
    }


def test_forecast_shows_upcoming_hours_with_night_icons_and_days_after_today() -> None:
    now = datetime(2026, 11, 23, 16, 30, tzinfo=LONDON)

    f = to_forecast(payload(), now, hour_step=2, hour_slots=6)

    assert [h.time.strftime("%H:%M") for h in f.hours] == [
        "17:00",
        "19:00",
        "21:00",
        "23:00",
        "01:00",
        "03:00",
    ], "every second hour after now, crossing midnight"
    assert f.now.condition.icon == "night", "clear after sunset shows the moon"
    assert f.hours[1].condition.icon == "partly-night", "partly cloudy at night"
    assert [d.date for d in f.days] == [date(2026, 11, 24)], "today is not repeated in days"
    assert f.days[0].condition.icon == "rain"
    assert f.next_rain is not None and f.next_rain.time.strftime("%H:%M") == "23:00", (
        "first upcoming hour at or above 50% rain"
    )


@respx.mock
async def test_home_location_is_rounded_before_it_leaves_the_mac() -> None:
    respx.get("http://ha.test/api/config").mock(
        return_value=httpx.Response(200, json={"latitude": 51.501364, "longitude": -0.14189})
    )
    ha = HomeAssistant("http://ha.test", "token")

    assert await ha.approximate_location() == (51.5, -0.14)
    await ha.aclose()
