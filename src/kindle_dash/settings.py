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
    presence_entity: str = "zone.home"
    kindle_ssh_host: str = "kindle"
    paper_dir: Path = Path(__file__).resolve().parents[2] / "data" / "paper"
    paper_until_hour: int = 10
    paper_seconds: int = 120
    feed_dir: Path = Path(__file__).resolve().parents[2] / "data" / "feed"
    feed_start_hour: int = 7
    feed_end_hour: int = 24
    feed_model: str = "qwen3.6-35b-a3b-dwq"
    feed_interests: str = "AI, developer tools, technology companies and markets"
    lmstudio_url: HttpUrl = HttpUrl("http://127.0.0.1:1234/v1")
    hermes_browser: Path = Path.home() / ".hermes" / "browser" / "hermes-browser"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
