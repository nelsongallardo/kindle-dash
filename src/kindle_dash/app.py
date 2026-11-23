import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from kindle_dash.calendar_feed import CalendarError, CalendarFeed
from kindle_dash.homeassistant import HomeAssistant, HomeAssistantError
from kindle_dash.settings import Settings

log = logging.getLogger("kindle_dash")
Screen = Literal["home", "calendar"]
SCREENS: list[tuple[Screen, str]] = [("home", "Home"), ("calendar", "Calendar")]

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


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    yield
    if ha:
        await ha.aclose()
    await calendar.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def render(request: Request, screen: Screen, **context: object) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        f"{screen}.html",
        {
            "screens": SCREENS,
            "active": screen,
            "now": datetime.now(settings.tz),
            "refresh_seconds": settings.refresh_seconds,
            **context,
        },
    )


@app.get("/")
async def index() -> RedirectResponse:
    return RedirectResponse("/home", status_code=303)


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


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # httpx logs full request URLs at INFO, and the calendar URL is a secret.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    uvicorn.run(app, host="0.0.0.0", port=8090)
