import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from kindle_dash.calendar_feed import CalendarError, CalendarFeed, Day
from kindle_dash.chart import label_hours, temperature_svg
from kindle_dash.feed import latest, load_feed
from kindle_dash.homeassistant import HomeAssistant, HomeAssistantError, Light
from kindle_dash.paper import Paper, load_paper
from kindle_dash.settings import Settings
from kindle_dash.tfl import Disruption, TflError, TubeStatus
from kindle_dash.weather import Forecast, WeatherError, WeatherFeed

log = logging.getLogger("kindle_dash")
Screen = Literal["home", "paper", "inside", "talk", "today", "feed", "calendar", "weather"]
SCREENS: list[tuple[Screen, str]] = [
    ("home", "Home"),
    ("paper", "Paper"),
    ("today", "Today"),
    ("feed", "Feed"),
    ("calendar", "Calendar"),
    ("weather", "Weather"),
]
DAY_ROTATION: list[Screen] = ["today", "feed", "calendar", "weather"]
FEED_ITEMS = 3
PAPER_SCREENS: list[Screen] = ["paper", "inside", "talk"]
CHART_WIDTH, CHART_HEIGHT = 870, 140

settings = Settings()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
ha = (
    HomeAssistant(str(settings.ha_url), settings.ha_token.get_secret_value())
    if settings.ha_token
    else None
)
calendar = CalendarFeed(
    [u.get_secret_value() for u in settings.calendar_ics_urls],
    settings.tz,
    settings.calendar_days,
)
weather = WeatherFeed(ha.approximate_location, settings.tz) if ha else None
tube = TubeStatus()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    yield
    if ha:
        await ha.aclose()
    if weather:
        await weather.aclose()
    await calendar.aclose()
    await tube.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def rotation(now: datetime, paper_ready: bool, until_hour: int) -> list[Screen]:
    if paper_ready and now.hour < until_hour:
        return PAPER_SCREENS + DAY_ROTATION
    return DAY_ROTATION


def next_screen(screen: Screen, screens: list[Screen]) -> tuple[int, Screen]:
    if screen not in screens:
        return settings.home_idle_seconds, screens[0]
    dwell = settings.paper_seconds if screen in PAPER_SCREENS else settings.rotate_seconds
    return dwell, screens[(screens.index(screen) + 1) % len(screens)]


def swipe_order(paper_ready: bool) -> list[Screen]:
    order: list[Screen] = []
    for key, _ in SCREENS:
        if key == "paper" and paper_ready:
            order += PAPER_SCREENS
        else:
            order.append(key)
    return order


def swipe_targets(screen: Screen, paper_ready: bool) -> tuple[Screen, Screen]:
    order = swipe_order(paper_ready)
    here = order.index(screen) if screen in order else order.index("paper")
    return order[here - 1], order[(here + 1) % len(order)]


def todays_paper(now: datetime) -> Paper | None:
    return load_paper(settings.paper_dir, now.date())


def render(request: Request, screen: Screen, **context: object) -> HTMLResponse:
    now = datetime.now(settings.tz)
    paper_ready = todays_paper(now) is not None
    seconds, then = next_screen(screen, rotation(now, paper_ready, settings.paper_until_hour))
    swipe_prev, swipe_next = swipe_targets(screen, paper_ready)
    return templates.TemplateResponse(
        request,
        f"{screen}.html",
        {
            "screens": SCREENS,
            "active": screen,
            "now": now,
            "refresh_seconds": seconds,
            "refresh_url": f"/{then}",
            "swipe_prev": f"/{swipe_prev}",
            "swipe_next": f"/{swipe_next}",
            **context,
        },
    )


@app.get("/")
async def index() -> RedirectResponse:
    now = datetime.now(settings.tz)
    return RedirectResponse(
        f"/{rotation(now, todays_paper(now) is not None, settings.paper_until_hour)[0]}",
        status_code=303,
    )


@app.get("/home", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    if ha is None:
        return render(request, "home", lights=[], error="Home Assistant token not set.")
    try:
        return render(request, "home", lights=await ha.lights(), error=None)
    except HomeAssistantError as e:
        log.warning("home: %s", e)
        return render(request, "home", lights=[], error="Can't reach Home Assistant.")


@app.post("/lights/toggle")
async def toggle(entity_id: str = Form()) -> RedirectResponse:
    if ha is not None:
        try:
            await ha.toggle_and_wait(entity_id)
        except HomeAssistantError as e:
            log.warning("toggle: %s", e)
    return RedirectResponse("/home", status_code=303)


@app.post("/lights/all")
async def all_lights(state: Literal["on", "off"] = Form()) -> RedirectResponse:
    if ha is not None:
        try:
            await ha.set_all_and_wait(state == "on")
        except HomeAssistantError as e:
            log.warning("all lights: %s", e)
    return RedirectResponse("/home", status_code=303)


@app.get("/calendar", response_class=HTMLResponse)
async def calendar_screen(request: Request) -> HTMLResponse:
    if not calendar.configured:
        return render(request, "calendar", days=[], error="No calendar link set.")
    try:
        return render(request, "calendar", days=await calendar.days(), error=None)
    except CalendarError as e:
        log.warning("calendar: %s", e)
        return render(request, "calendar", days=[], error="Can't load the calendar.")


@app.get("/weather", response_class=HTMLResponse)
async def weather_screen(request: Request) -> HTMLResponse:
    if weather is None:
        return render(request, "weather", forecast=None, error="Home Assistant token not set.")
    try:
        return render(
            request,
            "weather",
            forecast=await weather.forecast(),
            place=settings.weather_place,
            error=None,
        )
    except (WeatherError, HomeAssistantError) as e:
        log.warning("weather: %s", e)
        return render(request, "weather", forecast=None, error="Can't load the weather.")


async def _forecast_or_none() -> Forecast | None:
    if weather is None:
        return None
    try:
        return await weather.forecast()
    except (WeatherError, HomeAssistantError) as e:
        log.warning("today/weather: %s", e)
        return None


async def _days_or_none() -> list[Day] | None:
    if not calendar.configured:
        return None
    try:
        return await calendar.days()
    except CalendarError as e:
        log.warning("today/calendar: %s", e)
        return None


async def _lights_or_none() -> list[Light] | None:
    if ha is None:
        return None
    try:
        return await ha.lights()
    except HomeAssistantError as e:
        log.warning("today/lights: %s", e)
        return None


async def _tube_or_none() -> list[Disruption] | None:
    try:
        return await tube.disruptions()
    except TflError as e:
        log.warning("today/tube: %s", e)
        return None


@app.get("/today", response_class=HTMLResponse)
async def today_screen(request: Request) -> HTMLResponse:
    forecast, days, lights, disruptions = await asyncio.gather(
        _forecast_or_none(), _days_or_none(), _lights_or_none(), _tube_or_none()
    )
    now = datetime.now(settings.tz)
    later_today = [e for e in days[0].events if e.all_day or e.end > now] if days else None
    tomorrow = days[1].events if days and len(days) > 1 else None
    return render(
        request,
        "today",
        forecast=forecast,
        place=settings.weather_place,
        later_today=later_today,
        tomorrow=tomorrow,
        lights=lights,
        disruptions=disruptions,
        error=None,
    )


@app.get("/feed", response_class=HTMLResponse)
async def feed_screen(request: Request) -> HTMLResponse:
    now = datetime.now(settings.tz)
    items = latest(load_feed(settings.feed_dir), now, FEED_ITEMS)
    return render(request, "feed", items=items, error=None)


@app.get("/paper", response_class=HTMLResponse)
async def paper_screen(request: Request) -> HTMLResponse:
    forecast, disruptions = await asyncio.gather(_forecast_or_none(), _tube_or_none())
    return render(
        request,
        "paper",
        paper=todays_paper(datetime.now(settings.tz)),
        forecast=forecast,
        chart_hours=label_hours(forecast.timeline) if forecast else [],
        disruptions=disruptions,
        place=settings.weather_place,
        error=None,
    )


@app.get("/inside", response_class=HTMLResponse)
async def inside_screen(request: Request) -> HTMLResponse:
    return render(request, "inside", paper=todays_paper(datetime.now(settings.tz)), error=None)


@app.get("/talk", response_class=HTMLResponse)
async def talk_screen(request: Request) -> HTMLResponse:
    days, disruptions = await asyncio.gather(_days_or_none(), _tube_or_none())
    now = datetime.now(settings.tz)
    return render(
        request,
        "talk",
        paper=todays_paper(now),
        disruptions=disruptions,
        events=[e for e in days[0].events if e.all_day or e.end > now] if days else None,
        error=None,
    )


@app.get("/paper/weather.svg")
async def weather_chart() -> Response:
    forecast = await _forecast_or_none()
    hours = forecast.timeline if forecast else []
    return Response(temperature_svg(hours, CHART_WIDTH, CHART_HEIGHT), media_type="image/svg+xml")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # httpx logs full request URLs at INFO, and the calendar URL is a secret.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    uvicorn.run(app, host="0.0.0.0", port=8090)
