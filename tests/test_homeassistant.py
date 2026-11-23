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
