"""Folder naming, sessions (time/location grouping) and the effective folder/status of a card."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from .geo import haversine_m

FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
MAX_FOLDER_BYTES = 200

STATUS_READY = "ready"
STATUS_REVIEW = "review"
STATUS_DUPLICATE = "duplicate"
STATUS_PENDING = "pending"

DUP_IN_DESTINATION = 0  # dup_of value: identical file already exists in the destination folder


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def sanitize_folder(name: str | None) -> str:
    """Make a user/OSM supplied string a safe single folder name (no path traversal)."""
    if not name:
        return ""
    text = FORBIDDEN.sub("-", str(name))
    text = re.sub(r"\s+", " ", text).strip().strip(".").strip()
    # collapse separators left over from empty template parts: "a - - b" / trailing " -"
    while re.search(r"\s-\s+-(\s|$)", text):
        text = re.sub(r"\s-\s+-(\s|$)", r" -\1", text)
    text = re.sub(r"^(-\s*)+|(\s*-)+$", "", text).strip()
    if text in {"", ".", ".."}:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_FOLDER_BYTES:
        text = encoded[:MAX_FOLDER_BYTES].decode("utf-8", "ignore").rstrip(" .-")
    return text


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def render(template: str | None, taken_at: str | None, date_format: str, **values: Any) -> str:
    """Fill {date} {year} {month} {day} {city} {place} and sanitize. Invalid templates are used literally."""
    if not template:
        return ""
    dt = parse_dt(taken_at)
    fields = _SafeDict(
        date=dt.strftime(date_format) if dt else "unknown date",
        year=dt.strftime("%Y") if dt else "",
        month=dt.strftime("%m") if dt else "",
        day=dt.strftime("%d") if dt else "",
    )
    fields.update({k: ("" if v is None else str(v)) for k, v in values.items()})
    try:
        # only allow simple {name} fields, no attribute/index access
        for _, field_name, _, _ in string.Formatter().parse(template):
            if field_name and not field_name.isidentifier():
                raise ValueError(field_name)
        text = template.format_map(fields)
    except (ValueError, IndexError, KeyError):
        text = template
    return sanitize_folder(text)


def location_folder(naming: Mapping[str, Any], taken_at: str | None, city: str | None, place: str | None) -> str:
    fmt = naming["date_format"]
    if city and place:
        return render(naming["location_template"], taken_at, fmt, city=city, place=place)
    if city:
        return render(naming["city_only_template"], taken_at, fmt, city=city)
    if place:
        return render(naming["city_only_template"], taken_at, fmt, city=place)
    return render(naming["no_location_template"], taken_at, fmt)


@dataclass
class GeoPoint:
    id: int
    taken: datetime | None
    lat: float
    lon: float


def build_sessions(points: Sequence[GeoPoint], max_gap_minutes: float, radius_m: float) -> list[list[GeoPoint]]:
    """Group photos into sessions. A new session starts when the time gap to the previous
    photo exceeds max_gap_minutes or the photo is further than radius_m from the session's
    first photo (the anchor, whose location names the folder)."""
    ordered = sorted(points, key=lambda p: (p.taken is None, p.taken or datetime.min, p.id))
    sessions: list[list[GeoPoint]] = []
    for p in ordered:
        if sessions:
            current = sessions[-1]
            anchor, prev = current[0], current[-1]
            same_time = (
                p.taken is not None
                and prev.taken is not None
                and (p.taken - prev.taken).total_seconds() <= max_gap_minutes * 60
            )
            if same_time and haversine_m(anchor.lat, anchor.lon, p.lat, p.lon) <= radius_m:
                current.append(p)
                continue
        sessions.append([p])
    return sessions


def apply_replacements(folder: str, replacements: Iterable[Mapping[str, Any]], taken_at: str | None, date_format: str) -> str:
    for rep in replacements:
        if folder and folder == rep["from_folder"]:
            folder = render(rep["to_folder"], taken_at, date_format) or folder
    return folder


def effective(row: Mapping[str, Any], replacements: Sequence[Mapping[str, Any]], date_format: str) -> dict[str, Any]:
    """Compute what the UI shows and what "move" uses for a file row."""
    manual = row["manual_folder"]
    if manual:
        folder = render(manual, row["taken_at"], date_format)
    else:
        folder = row["auto_folder"] or ""
    folder = apply_replacements(folder, replacements, row["taken_at"], date_format)

    reason = row["auto_reason"] or ""
    if not row["analyzed"]:
        status = STATUS_PENDING
    elif row["dup_of"] is not None and not row["approved"]:
        status = STATUS_DUPLICATE
        if row["dup_of"] == DUP_IN_DESTINATION:
            reason = "An identical file already exists in the destination folder"
        else:
            reason = "Same content as another photo in the inbox"
    elif (manual or row["approved"]) and folder:
        status = STATUS_READY
        if manual:
            reason = "Folder set manually"
    elif row["error"]:
        status = STATUS_REVIEW
        reason = row["error"]
    else:
        status = row["auto_status"] or STATUS_PENDING
    if status == STATUS_READY and not folder:
        status = STATUS_REVIEW
    return {"folder": folder, "status": status, "reason": reason, "manual": bool(manual)}
