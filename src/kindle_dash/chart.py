from dataclasses import dataclass

from kindle_dash.weather import Hour

LABEL_EVERY = 3


@dataclass(frozen=True, slots=True)
class Box:
    width: int
    height: int
    top: int
    bottom: int


def x_at(index: int, count: int, box: Box) -> float:
    return (index + 0.5) * box.width / count


def y_for(temp: float, low: float, high: float, box: Box) -> float:
    span = max(high - low, 1.0)
    return box.top + (high - temp) / span * (box.height - box.top - box.bottom)


def label_hours(hours: list[Hour]) -> list[Hour]:
    return hours[1::LABEL_EVERY]


def temperature_svg(hours: list[Hour], width: int, height: int) -> str:
    box = Box(width, height, top=40, bottom=64)
    count = len(hours)
    if count < 2:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"/>'
    temps = [h.temp for h in hours]
    low, high = min(temps), max(temps)
    band_top = height - box.bottom + 6
    band = box.bottom - 30
    bar = width / count * 0.62
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Helvetica, Arial, sans-serif">'
    ]
    for i, h in enumerate(hours):
        if h.rain_chance:
            bh = band * h.rain_chance / 100
            x = x_at(i, count, box) - bar / 2
            parts.append(
                f'<rect x="{x:.1f}" y="{band_top + band - bh:.1f}" width="{bar:.1f}" '
                f'height="{bh:.1f}" fill="#888"/>'
            )
    parts.append(
        f'<line x1="0" y1="{band_top + band:.1f}" x2="{width}" y2="{band_top + band:.1f}" '
        'stroke="#000" stroke-width="2"/>'
    )
    points = " ".join(
        f"{x_at(i, count, box):.1f},{y_for(t, low, high, box):.1f}" for i, t in enumerate(temps)
    )
    parts.append(
        f'<polyline points="{points}" fill="none" stroke="#000" stroke-width="5" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
    )
    for i in range(1, count, LABEL_EVERY):
        x, y = x_at(i, count, box), y_for(temps[i], low, high, box)
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="#fff" stroke="#000" stroke-width="4"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{y - 16:.1f}" font-size="26" font-weight="bold" '
            f'text-anchor="middle">{round(temps[i])}°</text>'
        )
        if hours[i].rain_chance:
            parts.append(
                f'<text x="{x:.1f}" y="{height - 4}" font-size="20" text-anchor="middle">'
                f"{hours[i].rain_chance}%</text>"
            )
    parts.append("</svg>")
    return "".join(parts)
