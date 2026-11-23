import httpx
import pytest
import respx

from kindle_dash.homeassistant import HomeAssistant, HomeAssistantError

HA = "http://ha.test"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, html="<html>proxy error</html>"),
        httpx.Response(200, json=[{"unexpected": "shape"}]),
    ],
    ids=["not-json", "wrong-shape"],
)
@respx.mock
async def test_unexpected_states_payload_raises_home_assistant_error(
    response: httpx.Response,
) -> None:
    respx.get(f"{HA}/api/states").mock(return_value=response)
    ha = HomeAssistant(HA, "token")

    with pytest.raises(HomeAssistantError):
        await ha.lights()

    await ha.aclose()


@pytest.mark.parametrize(
    ("entity", "state", "home"),
    [
        ("zone.home", "0", False),
        ("zone.home", "2", True),
        ("person.a", "not_home", False),
        ("person.a", "home", True),
    ],
)
@respx.mock
async def test_anyone_home_reads_zone_counts_and_person_states(
    entity: str, state: str, home: bool
) -> None:
    payload: dict[str, object] = {"entity_id": entity, "state": state, "attributes": {}}
    respx.get(f"{HA}/api/states/{entity}").mock(return_value=httpx.Response(200, json=payload))
    ha = HomeAssistant(HA, "token")

    assert await ha.anyone_home(entity) is home

    await ha.aclose()


@respx.mock
async def test_unavailable_presence_is_an_error_not_away() -> None:
    payload: dict[str, object] = {
        "entity_id": "zone.home",
        "state": "unavailable",
        "attributes": {},
    }
    respx.get(f"{HA}/api/states/zone.home").mock(return_value=httpx.Response(200, json=payload))
    ha = HomeAssistant(HA, "token")

    with pytest.raises(HomeAssistantError):
        await ha.anyone_home("zone.home")

    await ha.aclose()
