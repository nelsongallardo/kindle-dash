import pytest

from kindle_dash.tfl import TflError, disruptions


def line(name: str, *statuses: tuple[int, str]) -> dict[str, object]:
    return {
        "name": name,
        "lineStatuses": [
            {"statusSeverity": sev, "statusSeverityDescription": desc} for sev, desc in statuses
        ],
    }


def test_only_disrupted_lines_are_listed_worst_first() -> None:
    raw = [
        line("Bakerloo", (9, "Minor Delays")),
        line("Central", (9, "Minor Delays"), (3, "Part Suspended")),
        line("Victoria", (10, "Good Service")),
        line("District", (9, "Minor Delays"), (9, "Minor Delays")),
    ]

    shown = [(d.line, d.status) for d in disruptions(raw)]

    assert shown == [
        ("Central", "Part Suspended, Minor Delays"),
        ("Bakerloo", "Minor Delays"),
        ("District", "Minor Delays"),
    ], "good service hidden; worst line first; repeated statuses merged"


def test_unexpected_payload_raises_tfl_error() -> None:
    with pytest.raises(TflError):
        disruptions({"message": "rate limited"})
