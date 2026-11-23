import time
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

STATUS_URL = "https://api.tfl.gov.uk/Line/Mode/tube,elizabeth-line/Status"
GOOD_SERVICE = 10


class TflError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Disruption:
    line: str
    status: str
    severity: int


class _Status(BaseModel):
    model_config = ConfigDict(extra="ignore")
    statusSeverity: int
    statusSeverityDescription: str


class _Line(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    lineStatuses: list[_Status]


_LINES = TypeAdapter(list[_Line])


def disruptions(raw: object) -> list[Disruption]:
    try:
        lines = _LINES.validate_python(raw)
    except ValidationError as e:
        raise TflError(f"unexpected status payload: {e}") from e
    out: list[Disruption] = []
    for line in lines:
        bad = sorted(
            (s for s in line.lineStatuses if s.statusSeverity != GOOD_SERVICE),
            key=lambda s: s.statusSeverity,
        )
        if bad:
            labels = list(dict.fromkeys(s.statusSeverityDescription for s in bad))
            out.append(Disruption(line.name, ", ".join(labels), bad[0].statusSeverity))
    return sorted(out, key=lambda d: (d.severity, d.line))


class TubeStatus:
    def __init__(self, ttl_seconds: int = 120) -> None:
        self._ttl = ttl_seconds
        self._cache: tuple[float, list[Disruption]] | None = None
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def disruptions(self) -> list[Disruption]:
        if self._cache and time.monotonic() - self._cache[0] < self._ttl:
            return self._cache[1]
        try:
            r = await self._client.get(STATUS_URL)
            r.raise_for_status()
            raw = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise TflError(f"status fetch failed: {e}") from e
        result = disruptions(raw)
        self._cache = (time.monotonic(), result)
        return result
