"""Configuration: built-in defaults, deep-merged with an optional read-only config.yaml.

Paths and secrets come from environment variables (see .env.example); everything
about sorting behaviour comes from config.yaml (see config/config.example.yaml).
"""

from __future__ import annotations

import copy
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "naming": {
        # strftime format used for {date}
        "date_format": "%d.%m.%Y",
        # Template for GPS based folders. {place} part is dropped when no place is known.
        "location_template": "{date} - {city} - {place}",
        "city_only_template": "{date} - {city}",
        "documents_template": "{date} - documents",
        # Used when a photo has no GPS and cannot be matched to a nearby session by time.
        "no_location_template": "{date}",
        # Use the street name as {place} when no named point of interest is nearby.
        "street_fallback": True,
        # Rename places / cities coming from OpenStreetMap: "OSM name": "your name"
        "aliases": {
            "Park im. dr. Henryka Jordana": "Park Jordana",
            "Park Jordana im. dr. Henryka Jordana": "Park Jordana",
        },
    },
    # Custom places always win over geocoding. First match (smallest radius first) wins.
    "places": [],
    "grouping": {
        # Photos taken close to each other (distance from the first photo of the session)
        # within this time gap share the first photo's folder.
        "enabled": True,
        "max_gap_minutes": 90,
        "radius_m": 250,
        # Photos without GPS taken within max_gap of a located session inherit its folder
        # (status "review" so you can confirm).
        "attach_no_gps_by_time": True,
    },
    "geocoding": {
        "enabled": True,
        "language": "pl",
        "nominatim_url": "https://nominatim.openstreetmap.org",
        "overpass_url": "https://overpass-api.de/api/interpreter",
        "user_agent": "PhotoSorter2Claude (+https://github.com/wube1/PhotoSorter2Claude)",
        "contact_email": "",
        # Named points of interest within this distance become {place}
        "poi_radius_m": 45,
        # Minimum seconds between requests to the public services (usage policy: 1 req/s)
        "min_interval_s": 1.1,
        "timeout_s": 25,
        # Cache key precision (decimal places). 4 ≈ 11 m.
        "cache_precision": 4,
        "poi_keys": ["amenity", "tourism", "leisure", "historic"],
        "area_keys": ["leisure", "tourism", "amenity", "historic"],
        # Tag values that are never interesting as a folder name
        "ignore_values": [
            "parking", "parking_entrance", "parking_space", "bicycle_parking", "motorcycle_parking",
            "bench", "waste_basket", "waste_disposal", "recycling", "vending_machine", "atm",
            "toilets", "drinking_water", "post_box", "telephone", "charging_station", "fuel",
            "bus_station", "taxi", "shelter", "clock", "fountain", "hunting_stand", "picnic_table",
            "information", "grave_yard", "wayside_cross", "wayside_shrine", "memorial", "yes",
            "dog_park", "pitch", "track", "fitness_station", "outdoor_seating", "bbq",
            "boundary_stone", "street_lamp", "loading_dock", "letter_box", "parcel_locker",
            "compressed_air", "water_point", "smoking_area", "give_box", "ticket_validator",
            "bank", "pharmacy", "dentist", "doctors", "veterinary", "car_wash", "car_rental",
            "bureau_de_change", "money_transfer", "payment_terminal", "post_office", "townhall",
            "social_facility", "courthouse", "police", "fire_station", "public_bookcase",
        ],
    },
    "documents": {
        "enabled": True,
        # Heuristic thresholds (0..1). Higher min_score = fewer false positives.
        "min_score": 0.6,
        # "review" (you confirm) or "ready"
        "status": "review",
    },
    "scan": {
        "workers": 2,
        # Files modified less than this many seconds ago are skipped (still being copied)
        "min_file_age_s": 5,
        "extensions": [".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"],
        "thumbnail_size": 400,
        "preview_size": 1600,
    },
    # "permanent" deletes files; "trash" moves them to <inbox>/.photosorter-trash
    "delete_mode": "permanent",
    # When true a GPS photo is "ready" only if a specific place (not just a city) was found
    "ready_requires_place": False,
    # Shown in the "Apply folder" dropdown. {date} is filled in per photo.
    "predefined_folders": [
        "home",
        "{date} - documents",
        "{date} - Kraków",
        "{date} - screenshots",
    ],
}

TRASH_DIR_NAME = ".photosorter-trash"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float
    radius_m: float
    folder: str


@dataclass
class Settings:
    inbox: Path
    sorted: Path
    data: Path
    logs: Path
    config_file: Path
    auth_user: str
    auth_password: str
    allowed_hosts: list[str]
    log_level: str
    raw: dict[str, Any] = field(default_factory=dict)
    places: list[Place] = field(default_factory=list)
    config_loaded: bool = False
    config_error: str | None = None

    # convenience accessors
    @property
    def naming(self) -> dict[str, Any]:
        return self.raw["naming"]

    @property
    def grouping(self) -> dict[str, Any]:
        return self.raw["grouping"]

    @property
    def geocoding(self) -> dict[str, Any]:
        return self.raw["geocoding"]

    @property
    def documents(self) -> dict[str, Any]:
        return self.raw["documents"]

    @property
    def scan(self) -> dict[str, Any]:
        return self.raw["scan"]

    @property
    def trash_dir(self) -> Path:
        return self.inbox / TRASH_DIR_NAME


def _parse_places(items: Any) -> list[Place]:
    places: list[Place] = []
    for i, item in enumerate(items or []):
        try:
            places.append(
                Place(
                    name=str(item.get("name") or f"place-{i + 1}"),
                    lat=float(item["lat"]),
                    lon=float(item["lon"]),
                    radius_m=float(item.get("radius_m", 100)),
                    folder=str(item["folder"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.error("Ignoring invalid place #%d in config: %s (%s)", i + 1, item, exc)
    # smallest radius first so a precise place wins over a large area around it
    places.sort(key=lambda p: p.radius_m)
    return places


def load_settings() -> Settings:
    env = os.environ
    config_file = Path(env.get("PHOTOSORTER_CONFIG", "/config/config.yaml"))
    raw = copy.deepcopy(DEFAULTS)
    loaded = False
    error = None
    if config_file.is_file():
        try:
            user_cfg = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            if not isinstance(user_cfg, dict):
                raise ValueError("top level of config.yaml must be a mapping")
            raw = _deep_merge(DEFAULTS, user_cfg)
            loaded = True
        except (OSError, ValueError, yaml.YAMLError) as exc:
            error = f"{config_file}: {exc}"
    hosts = [h.strip().lower() for h in env.get("PHOTOSORTER_ALLOWED_HOSTS", "").split(",") if h.strip()]
    settings = Settings(
        inbox=Path(env.get("PHOTOSORTER_INBOX", "/photos/inbox")),
        sorted=Path(env.get("PHOTOSORTER_SORTED", "/photos/sorted")),
        data=Path(env.get("PHOTOSORTER_DATA", "/data")),
        logs=Path(env.get("PHOTOSORTER_LOGS", "/logs")),
        config_file=config_file,
        auth_user=env.get("PHOTOSORTER_AUTH_USER", ""),
        auth_password=env.get("PHOTOSORTER_AUTH_PASSWORD", ""),
        allowed_hosts=hosts,
        log_level=env.get("PHOTOSORTER_LOG_LEVEL", "INFO").upper(),
        raw=raw,
        config_loaded=loaded,
        config_error=error,
    )
    settings.places = _parse_places(raw.get("places"))
    email = env.get("PHOTOSORTER_CONTACT_EMAIL")
    if email:
        settings.geocoding["contact_email"] = email
    return settings
