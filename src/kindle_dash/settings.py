from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KINDLE_DASH_", env_file=".env", extra="forbid")

    ha_url: HttpUrl = HttpUrl("http://127.0.0.1:8123")
    ha_token: SecretStr | None = None
    # JSON list in the env file, e.g. KINDLE_DASH_CALENDAR_ICS_URLS='["https://..."]'
    calendar_ics_urls: list[SecretStr] = []
    calendar_days: int = 7
    timezone: str = "Europe/London"
    weather_place: str | None = None
    rotate_seconds: int = 60
    home_idle_seconds: int = 120
    paper_dir: Path = Path(__file__).resolve().parents[2] / "data" / "paper"
    paper_until_hour: int = 10
    paper_seconds: int = 120

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
