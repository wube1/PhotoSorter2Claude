"""Reverse geocoding with OpenStreetMap.

* Nominatim (reverse, zoom 18) gives the city / town / village, the street and the named
  area you are standing in (park, museum grounds, ...).
* Overpass finds named points of interest (restaurant, pub, museum, playground, ...) within
  a small radius, which is more precise than Nominatim's single nearest object.

Results are cached in SQLite by rounded coordinates, so re-scans do not hit the network.
Requests are serialized and rate limited to respect the public services' usage policy.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from . import __version__
from .db import Database
from .geo import haversine_m

log = logging.getLogger(__name__)

CITY_KEYS = ("city", "town", "village", "hamlet", "municipality", "suburb", "county")
STREET_KEYS = ("road", "pedestrian", "footway", "square", "path", "cycleway")
CACHE_VERSION = 1


class GeocodeError(RuntimeError):
    """Temporary failure (network, rate limit). Not cached; retried on the next scan."""


class Geocoder:
    def __init__(self, cfg: dict[str, Any], aliases: dict[str, str], db: Database, street_fallback: bool = True):
        self.cfg = cfg
        self.aliases = {str(k): str(v) for k, v in (aliases or {}).items()}
        self.db = db
        self.street_fallback = street_fallback
        self._lock = threading.Lock()
        self._last_call: dict[str, float] = {}
        ua = str(cfg.get("user_agent") or "PhotoSorter2Claude")
        if "/" not in ua.split(" ")[0]:
            ua = ua.replace("PhotoSorter2Claude", f"PhotoSorter2Claude/{__version__}", 1)
        email = str(cfg.get("contact_email") or "").strip()
        if email:
            ua = f"{ua} contact:{email}"
        self._client = httpx.Client(
            timeout=float(cfg.get("timeout_s", 25)),
            headers={"User-Agent": ua, "Accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    # ---------------------------------------------------------------- public
    def cache_key(self, lat: float, lon: float) -> str:
        prec = int(self.cfg.get("cache_precision", 4))
        return (
            f"v{CACHE_VERSION}:{round(lat, prec):.{prec}f},{round(lon, prec):.{prec}f}:"
            f"{self.cfg.get('language', 'pl')}:{self.cfg.get('poi_radius_m', 45)}"
        )

    def lookup(self, lat: float, lon: float) -> dict[str, Any]:
        """Return {city, place, place_kind, street, display}. Raises GeocodeError on temporary failure."""
        key = self.cache_key(lat, lon)
        raw = self.db.geocache_get(key)
        if raw is None:
            raw = self._fetch(lat, lon)
            self.db.geocache_put(key, raw)
        return self.interpret(raw, lat, lon)

    # ------------------------------------------------------------- internals
    def _throttle(self, service: str) -> None:
        interval = float(self.cfg.get("min_interval_s", 1.1))
        wait = self._last_call.get(service, 0.0) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call[service] = time.monotonic()

    def _get_json(self, service: str, method: str, url: str, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(3):
            self._throttle(service)
            try:
                resp = self._client.request(method, url, **kwargs)
                if resp.status_code in (429, 502, 503, 504):
                    raise GeocodeError(f"{service} HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, ValueError, GeocodeError) as exc:
                last_exc = exc
                time.sleep(2 * (attempt + 1))
        raise GeocodeError(f"{service} failed: {last_exc}")

    def _fetch(self, lat: float, lon: float) -> dict[str, Any]:
        with self._lock:
            nominatim = self._get_json(
                "nominatim",
                "GET",
                f"{str(self.cfg['nominatim_url']).rstrip('/')}/reverse",
                params={
                    "format": "jsonv2",
                    "lat": f"{lat:.6f}",
                    "lon": f"{lon:.6f}",
                    "zoom": 18,
                    "addressdetails": 1,
                    "namedetails": 1,
                    "accept-language": self.cfg.get("language", "pl"),
                },
            )
            pois: list[dict[str, Any]] = []
            overpass_url = str(self.cfg.get("overpass_url") or "").strip()
            if overpass_url:
                keys = "|".join(self.cfg.get("poi_keys") or ["amenity", "tourism", "leisure", "historic"])
                radius = int(self.cfg.get("poi_radius_m", 45))
                query = (
                    f'[out:json][timeout:20];nwr(around:{radius},{lat:.6f},{lon:.6f})[name][~"^({keys})$"~"."];'
                    "out tags center;"
                )
                try:
                    data = self._get_json("overpass", "POST", overpass_url, data={"data": query})
                    pois = list(data.get("elements", []))
                except GeocodeError as exc:
                    # POIs are a refinement; Nominatim alone still gives a usable answer
                    log.warning("Overpass unavailable, using Nominatim only: %s", exc)
                    pois = []
            if isinstance(nominatim, dict) and nominatim.get("error"):
                nominatim = {"address": {}}
            return {"nominatim": nominatim, "pois": pois}

    def _alias(self, name: str | None) -> str | None:
        if not name:
            return None
        return self.aliases.get(name, name)

    def _localized_name(self, tags: dict[str, Any]) -> str | None:
        lang = self.cfg.get("language", "pl")
        return tags.get(f"name:{lang}") or tags.get("name")

    def interpret(self, raw: dict[str, Any], lat: float, lon: float) -> dict[str, Any]:
        nom = raw.get("nominatim") or {}
        address = nom.get("address") or {}
        city = next((address[k] for k in CITY_KEYS if address.get(k)), None)
        street = next((address[k] for k in STREET_KEYS if address.get(k)), None)

        ignore = set(self.cfg.get("ignore_values") or [])
        poi_keys = list(self.cfg.get("poi_keys") or [])
        area_keys = list(self.cfg.get("area_keys") or [])
        radius = float(self.cfg.get("poi_radius_m", 45))

        # 1) nearest named POI (Overpass)
        best: tuple[float, str] | None = None
        for el in raw.get("pois") or []:
            tags = el.get("tags") or {}
            name = self._localized_name(tags)
            if not name:
                continue
            kinds = [k for k in poi_keys if k in tags]
            if not kinds or all(tags.get(k) in ignore for k in kinds):
                continue
            plat = el.get("lat", (el.get("center") or {}).get("lat"))
            plon = el.get("lon", (el.get("center") or {}).get("lon"))
            if plat is None or plon is None:
                continue
            dist = haversine_m(lat, lon, float(plat), float(plon))
            if dist > radius:  # large areas (parks) are handled below via Nominatim
                continue
            if best is None or dist < best[0]:
                best = (dist, name)

        place = best[1] if best else None
        kind = "poi" if place else "none"

        # 2) named object/area Nominatim puts us in (park, museum, restaurant, ...)
        if not place:
            category = nom.get("category") or nom.get("class")
            ntype = nom.get("type")
            nname = (nom.get("namedetails") or {}).get(f"name:{self.cfg.get('language', 'pl')}") or nom.get("name")
            if nname and category in set(poi_keys) | set(area_keys) and ntype not in ignore:
                place, kind = nname, "area"
        if not place:
            for k in area_keys:
                if address.get(k):
                    place, kind = address[k], "area"
                    break

        # 3) street / square / promenade
        if not place and self.street_fallback and street:
            place, kind = street, "street"

        city = self._alias(city)
        place = self._alias(place)
        if place and city and place.strip().lower() == city.strip().lower():
            place, kind = None, "none"
        return {
            "city": city,
            "place": place,
            "place_kind": kind,
            "street": street,
            "display": nom.get("display_name"),
        }
