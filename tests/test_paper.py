import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from kindle_dash.app import rotation
from kindle_dash.paper import Move, PaperError, Prepared, daily_change, publish

LONDON = ZoneInfo("Europe/London")
PREPARED = Prepared(
    date=date(2026, 11, 24),
    moves=[Move(symbol="NVDA", name="NVIDIA Corp", kind="stock", change_percent=3.0)],
)


def stories(**overrides: object) -> str:
    story = {"title": "Headline", "summary": "Summary.", "source": "Reuters"}
    base: dict[str, object] = {
        "lead": story,
        "tech": [story, story],
        "holdings": [{"symbol": "NVDA", "note": "Earnings beat"}],
        "x_topics": [{"title": "Topic", "summary": "Talk."}] * 2,
        "week_ahead": [],
    }
    return json.dumps(base | overrides)


def test_publish_keeps_prepared_prices_and_agent_notes() -> None:
    paper = publish(PREPARED, stories(), datetime(2026, 11, 24, 6, 50, tzinfo=LONDON))

    assert paper.moves == PREPARED.moves, "prices come from prepare, not the agent"
    assert paper.note_for("NVDA") == "Earnings beat"


@pytest.mark.parametrize(
    "bad",
    [
        {"holdings": [{"symbol": "TSLA", "note": "Not owned"}]},
        {"lead": {"title": "x" * 81, "summary": "s", "source": "s"}},
        {"tech": []},
        {"extra": "field"},
    ],
    ids=["unowned symbol", "headline too long", "no tech stories", "unknown field"],
)
def test_publish_rejects_stories_the_page_cannot_show(bad: dict[str, object]) -> None:
    with pytest.raises(PaperError):
        publish(PREPARED, stories(**bad), datetime(2026, 11, 24, 6, 50, tzinfo=LONDON))


def test_daily_change_uses_last_two_known_closes() -> None:
    raw = {
        "chart": {"result": [{"indicators": {"quote": [{"close": [90.0, 100.0, 110.0, None]}]}}]}
    }

    assert daily_change(raw) == 10.0


def test_paper_leads_the_rotation_only_in_the_morning() -> None:
    morning = datetime(2026, 11, 24, 7, 0, tzinfo=LONDON)
    afternoon = datetime(2026, 11, 24, 14, 0, tzinfo=LONDON)

    assert rotation(morning, paper_ready=True, until_hour=10)[:3] == ["paper", "inside", "talk"]
    assert "paper" not in rotation(morning, paper_ready=False, until_hour=10)
    assert "paper" not in rotation(afternoon, paper_ready=True, until_hour=10)
