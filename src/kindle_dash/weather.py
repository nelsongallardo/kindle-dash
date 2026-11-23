import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

Icon = Literal[
    "clear", "night", "partly", "partly-night", "cloudy", "fog", "rain", "snow", "thunder"
]

# WMO weather interpretation codes, as documented by Open-Meteo.
CONDITIONS: dict[int, tuple[str, Icon]] = {
    0: ("Clear", "clear"),
    1: ("Mostly clear", "partly"),
    2: ("Partly cloudy", "partly"),
    3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"),
    48: ("Freezing fog", "fog"),
    51: ("Light drizzle", "rain"),
    53: ("Drizzle", "rain"),
    55: ("Heavy drizzle", "rain"),
    56: ("Freezing drizzle", "rain"),
    57: ("Freezing drizzle", "rain"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"),
    67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Light showers", "rain"),
    81: ("Showers", "rain"),
    82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"),
    86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "thunder"),
    96: ("Thunderstorm, hail", "thunder"),
    99: ("Thunderstorm, hail", "thunder"),
}


NIGHT_ICONS: dict[Icon, Icon] = {"clear": "night", "partly": "partly-night"}


@dataclass(frozen=True, slots=True)
class Condition:
    label: str
    icon: Icon


def condition(code: int, is_day: bool = True) -> Condition:
    label, icon = CONDITIONS.get(code, ("Unknown", "cloudy"))
    if not is_day:
        icon = NIGHT_ICONS.get(icon, icon)
    return Condition(label, icon)


class WeatherError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Now:
    temp: float
    feels_like: float
    condition: Condition
    wind_mph: float


@dataclass(frozen=True, slots=True)
class Hour:
    time: datetime
    temp: float
    condition: Condition
    rain_chance: int


@dataclass(frozen=True, slots=True)
class DayForecast:
    date: date
    condition: Condition
    high: float
    low: float
    rain_chance: int
    sunrise: datetime
    sunset: datetime


@dataclass(frozen=True, slots=True)
class Forecast:
    now: Now
    today: DayForecast
    hours: list[Hour]
    days: list[DayForecast]


class _Current(BaseModel):
    model_config = ConfigDict(extra="ignore")
    temperature_2m: float
    apparent_temperature: float
    weather_code: int
    wind_speed_10m: float
    is_day: int


class _Hourly(BaseModel):
    model_config = ConfigDict(extra="ignore")
    time: list[datetime]
    temperature_2m: list[float]
    weather_code: list[int]
    precipitation_probability: list[int | None]
    is_day: list[int]


class _Daily(BaseModel):
    model_config = ConfigDict(extra="ignore")
    time: list[date]
    weather_code: list[int]
    temperature_2m_max: list[float]
    temperature_2m_min: list[float]
    precipitation_probability_max: list[int | None]
    sunrise: list[datetime]
    sunset: list[datetime]


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")
    current: _Current
    hourly: _Hourly
    daily: _Daily


def to_forecast(raw: object, now: datetime, hour_step: int, hour_slots: int) -> Forecast:
    try:
        r = _Response.model_validate(raw)
    except ValidationError as e:
        raise WeatherError(f"unexpected forecast payload: {e}") from e
    tz = now.tzinfo
    h = r.hourly
    hours = [
        Hour(
            time=t.replace(tzinfo=tz),
            temp=h.temperature_2m[i],
            condition=condition(h.weather_code[i], bool(h.is_day[i])),
            rain_chance=h.precipitation_probability[i] or 0,
        )
        for i, t in enumerate(h.time)
        if t.replace(tzinfo=tz) > now
    ][::hour_step][:hour_slots]
    d = r.daily
    days = [
        DayForecast(
            date=day,
            condition=condition(d.weather_code[i]),
            high=d.temperature_2m_max[i],
            low=d.temperature_2m_min[i],
            rain_chance=d.precipitation_probability_max[i] or 0,
            sunrise=d.sunrise[i].replace(tzinfo=tz),
            sunset=d.sunset[i].replace(tzinfo=tz),
        )
        for i, day in enumerate(d.time)
    ]
    if not days or days[0].date != now.date():
        raise WeatherError("forecast does not start today")
    c = r.current
    return Forecast(
        now=Now(
            temp=c.temperature_2m,
            feels_like=c.apparent_temperature,
            condition=condition(c.weather_code, bool(c.is_day)),
            wind_mph=c.wind_speed_10m,
        ),
        today=days[0],
        hours=hours,
        days=days[1:],
    )


class WeatherFeed:
    def __init__(
        self,
        location: Callable[[], Awaitable[tuple[float, float]]],
        tz: ZoneInfo,
        ttl_seconds: int = 600,
    ) -> None:
        self._location = location
        self._where: tuple[float, float] | None = None
        self._tz = tz
        self._ttl = ttl_seconds
        self._cache: tuple[float, Forecast] | None = None
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def forecast(self) -> Forecast:
        now = datetime.now(self._tz)
        if (
            self._cache
            and time.monotonic() - self._cache[0] < self._ttl
            and self._cache[1].today.date == now.date()
        ):
            return self._cache[1]
        if self._where is None:
            self._where = await self._location()
        lat, lon = self._where
        params: dict[str, str | float] = {
            "latitude": lat,
            "longitude": lon,
            "timezone": str(self._tz),
            "forecast_days": 6,
            "wind_speed_unit": "mph",
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,is_day",
            "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,sunrise,sunset",
        }
        try:
            r = await self._client.get(OPEN_METEO, params=params)
            r.raise_for_status()
            raw = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise WeatherError(f"forecast fetch failed: {e}") from e
        result = to_forecast(raw, now, hour_step=2, hour_slots=6)
        self._cache = (time.monotonic(), result)
        return result
