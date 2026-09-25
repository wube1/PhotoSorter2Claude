"""Geometry helpers: distances and custom place matching."""

from __future__ import annotations

import math
from typing import Iterable

from .config import Place

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def match_place(lat: float, lon: float, places: Iterable[Place]) -> Place | None:
    """Return the matching custom place. Places are pre-sorted by radius (smallest first)."""
    for place in places:
        if haversine_m(lat, lon, place.lat, place.lon) <= place.radius_m:
            return place
    return None
