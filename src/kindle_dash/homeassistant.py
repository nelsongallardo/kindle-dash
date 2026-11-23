import asyncio
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError


class HomeAssistantError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Light:
    entity_id: str
    name: str
    on: bool
    available: bool


class _Attributes(BaseModel):
    model_config = ConfigDict(extra="ignore")
    friendly_name: str | None = None


class _State(BaseModel):
    model_config = ConfigDict(extra="ignore")
    entity_id: str
    state: str
    attributes: _Attributes


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: float
    longitude: float


_STATES = TypeAdapter(list[_State])


def _to_light(s: _State) -> Light:
    fallback = s.entity_id.split(".", 1)[1].replace("_", " ").capitalize()
    return Light(
        entity_id=s.entity_id,
        name=s.attributes.friendly_name or fallback,
        on=s.state == "on",
        available=s.state not in ("unavailable", "unknown"),
    )


class HomeAssistant:
    def __init__(self, base_url: str, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(8.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str) -> object:
        try:
            r = await self._client.get(path)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise HomeAssistantError(f"GET {path} failed: {e}") from e

    async def lights(self) -> list[Light]:
        try:
            states = _STATES.validate_python(await self._get("/api/states"))
        except ValidationError as e:
            raise HomeAssistantError(f"unexpected /api/states payload: {e}") from e
        lights = [_to_light(s) for s in states if s.entity_id.startswith("light.")]
        return sorted(lights, key=lambda light: light.name.lower())

    async def anyone_home(self, entity_id: str) -> bool:
        try:
            state = _State.model_validate(await self._get(f"/api/states/{entity_id}")).state
        except ValidationError as e:
            raise HomeAssistantError(f"unexpected {entity_id} payload: {e}") from e
        if state.isdigit():
            return int(state) > 0
        if state in ("unavailable", "unknown"):
            raise HomeAssistantError(f"{entity_id} is {state}")
        return state == "home"

    async def approximate_location(self) -> tuple[float, float]:
        try:
            config = _Config.model_validate(await self._get("/api/config"))
        except ValidationError as e:
            raise HomeAssistantError(f"unexpected /api/config payload: {e}") from e
        return round(config.latitude, 2), round(config.longitude, 2)

    async def _light(self, entity_id: str) -> Light:
        try:
            return _to_light(_State.model_validate(await self._get(f"/api/states/{entity_id}")))
        except ValidationError as e:
            raise HomeAssistantError(f"unexpected state payload for {entity_id}: {e}") from e

    async def set_all_and_wait(self, on: bool) -> None:
        targets = [light.entity_id for light in await self.lights() if light.available]
        if not targets:
            return
        service = "turn_on" if on else "turn_off"
        try:
            r = await self._client.post(
                f"/api/services/light/{service}", json={"entity_id": targets}
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise HomeAssistantError(f"light.{service} failed: {e}") from e
        for _ in range(10):
            lights = {light.entity_id: light for light in await self.lights()}
            if all(lights[t].on == on for t in targets if t in lights):
                return
            await asyncio.sleep(0.2)

    async def toggle_and_wait(self, entity_id: str) -> None:
        if not entity_id.startswith("light."):
            raise HomeAssistantError(f"not a light: {entity_id}")
        before = (await self._light(entity_id)).on
        try:
            r = await self._client.post("/api/services/light/toggle", json={"entity_id": entity_id})
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise HomeAssistantError(f"toggle {entity_id} failed: {e}") from e
        for _ in range(10):
            if (await self._light(entity_id)).on != before:
                return
            await asyncio.sleep(0.2)
