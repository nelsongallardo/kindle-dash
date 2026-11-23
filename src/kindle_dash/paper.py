import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from kindle_dash.settings import Settings

log = logging.getLogger(__name__)
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
STABLECOINS = {"USDT", "USDC", "DAI"}


class PaperError(Exception):
    pass


class Move(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    symbol: str
    name: str
    kind: Literal["stock", "etf", "crypto"]
    change_percent: float | None


class Prepared(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    date: date
    moves: list[Move]


class Story(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: Annotated[str, Field(min_length=1, max_length=80)]
    summary: Annotated[str, Field(min_length=1, max_length=260)]
    source: Annotated[str, Field(min_length=1, max_length=30)]


class LeadStory(Story):
    summary: Annotated[str, Field(min_length=1, max_length=300)]


class HoldingNote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    symbol: str
    note: Annotated[str, Field(min_length=1, max_length=65)]


class XTopic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: Annotated[str, Field(min_length=1, max_length=50)]
    summary: Annotated[str, Field(min_length=1, max_length=220)]


class Upcoming(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    date: date
    event: Annotated[str, Field(min_length=1, max_length=60)]


class Stories(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    lead: LeadStory
    tech: Annotated[list[Story], Field(min_length=2, max_length=4)]
    holdings: Annotated[list[HoldingNote], Field(max_length=6)]
    x_topics: Annotated[list[XTopic], Field(min_length=2, max_length=5)]
    week_ahead: Annotated[list[Upcoming], Field(max_length=5)]


class Paper(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    date: date
    published_at: datetime
    moves: list[Move]
    stories: Stories

    def note_for(self, symbol: str) -> str | None:
        return next((n.note for n in self.stories.holdings if n.symbol == symbol), None)


class _Holding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    symbol: str
    name: str
    type: str
    currency: str


class _Holdings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    holdings: list[_Holding]


class _Quote(BaseModel):
    model_config = ConfigDict(extra="ignore")
    close: list[float | None]


class _Indicators(BaseModel):
    model_config = ConfigDict(extra="ignore")
    quote: list[_Quote]


class _ChartResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    indicators: _Indicators


class _Chart(BaseModel):
    model_config = ConfigDict(extra="ignore")
    result: list[_ChartResult]


class _ChartResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chart: _Chart


def yahoo_symbol(h: _Holding) -> tuple[str, Literal["stock", "etf", "crypto"]] | None:
    if h.type == "crypto":
        return None if h.symbol in STABLECOINS else (f"{h.symbol}-USD", "crypto")
    if h.type == "etf":
        return (f"{h.symbol}.L" if h.currency == "GBP" else h.symbol), "etf"
    if h.type == "stock":
        return h.symbol, "stock"
    return None


def daily_change(raw: object) -> float | None:
    try:
        closes = _ChartResponse.model_validate(raw).chart.result[0].indicators.quote[0].close
    except (ValidationError, IndexError) as e:
        raise PaperError(f"unexpected chart payload: {e}") from e
    known = [c for c in closes if c is not None]
    if len(known) < 2:
        return None
    return round((known[-1] - known[-2]) / known[-2] * 100, 2)


def ledgi_holdings() -> list[_Holding]:
    try:
        out = subprocess.run(
            ["ledgi", "holdings", "list", "--output", "json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        return _Holdings.model_validate_json(out).holdings
    except (subprocess.SubprocessError, OSError, ValidationError) as e:
        raise PaperError(f"ledgi holdings failed: {e}") from e


def fetch_moves(holdings: list[_Holding], client: httpx.Client) -> list[Move]:
    moves: list[Move] = []
    for h in holdings:
        found = yahoo_symbol(h)
        if found is None:
            continue
        symbol, kind = found
        try:
            r = client.get(
                YAHOO_CHART.format(symbol=symbol), params={"range": "5d", "interval": "1d"}
            )
            r.raise_for_status()
            change = daily_change(r.json())
        except (httpx.HTTPError, ValueError, PaperError):
            change = None
        moves.append(Move(symbol=h.symbol, name=h.name, kind=kind, change_percent=change))
    return sorted(moves, key=lambda m: (m.kind != "stock", m.symbol))


def publish(prepared: Prepared, stories_json: str, now: datetime) -> Paper:
    try:
        stories = Stories.model_validate_json(stories_json)
    except ValidationError as e:
        raise PaperError(f"stories JSON is invalid:\n{e}") from e
    known = {m.symbol for m in prepared.moves}
    unknown = [n.symbol for n in stories.holdings if n.symbol not in known]
    if unknown:
        raise PaperError(f"holdings notes name symbols not in the portfolio: {unknown}")
    return Paper(date=prepared.date, published_at=now, moves=prepared.moves, stories=stories)


def paper_path(directory: Path, day: date) -> Path:
    return directory / f"{day.isoformat()}.json"


def prepared_path(directory: Path, day: date) -> Path:
    return directory / f"{day.isoformat()}.prepared.json"


def load_paper(directory: Path, day: date) -> Paper | None:
    path = paper_path(directory, day)
    try:
        return Paper.model_validate_json(path.read_text())
    except FileNotFoundError:
        return None
    except ValidationError as e:
        log.warning("paper %s is unreadable: %s", path.name, e)
        return None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(prog="kindle-dash-paper")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="write the day's holdings and price moves; print them")
    prep.add_argument("--date", type=date.fromisoformat)
    sub.add_parser("schema", help="print the JSON schema the agent's stories must match")
    pub = sub.add_parser("publish", help="validate the agent's stories JSON and publish")
    pub.add_argument("stories", type=Path)
    pub.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args(argv)
    now = datetime.now(settings.tz)
    day: date = getattr(args, "date", None) or now.date()
    directory = settings.paper_dir
    try:
        if args.command == "schema":
            print(json.dumps(TypeAdapter(Stories).json_schema(), indent=2))
        elif args.command == "prepare":
            with httpx.Client(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
                prepared = Prepared(date=day, moves=fetch_moves(ledgi_holdings(), client))
            text = prepared.model_dump_json(indent=2)
            _write(prepared_path(directory, day), text)
            print(text)
        else:
            prepared = Prepared.model_validate_json(prepared_path(directory, day).read_text())
            paper = publish(prepared, args.stories.read_text(), now)
            _write(paper_path(directory, day), paper.model_dump_json(indent=2))
            print(f"published {paper_path(directory, day)}")
    except (PaperError, FileNotFoundError, ValidationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
