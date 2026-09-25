from __future__ import annotations

import io
import os
import random
import sys
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings  # noqa: E402
from app.engine import Engine  # noqa: E402
from app.events import EventBus  # noqa: E402
from app.geocoder import GeocodeError, Geocoder  # noqa: E402


def _dms(v: float) -> tuple[Fraction, Fraction, Fraction]:
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = (v - d - m / 60) * 3600
    return Fraction(d), Fraction(m), Fraction(s).limit_denominator(100000)


def natural_image(seed: int = 1) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("RGB", (640, 480), (rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255)))
    d = ImageDraw.Draw(img)
    for _ in range(60):
        x, y = rnd.randint(0, 640), rnd.randint(0, 480)
        r = rnd.randint(10, 120)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(rnd.randint(0, 255), rnd.randint(40, 255), rnd.randint(0, 200)))
    return img


def document_image() -> Image.Image:
    img = Image.new("RGB", (1240, 1754), (246, 245, 240))
    d = ImageDraw.Draw(img)
    y = 120
    rnd = random.Random(7)
    while y < 1650:
        x = 110
        while x < 1100:
            w = rnd.randint(20, 90)
            d.rectangle((x, y, x + w, y + 14), fill=(25, 25, 30))
            for k in range(x, x + w, 7):
                d.line((k, y, k, y + 14), fill=(246, 245, 240), width=2)
            x += w + 14
        y += 34
    return img


def write_photo(path: Path, *, taken: str | None = None, lat: float | None = None, lon: float | None = None,
                image: Image.Image | None = None, seed: int = 1, age_s: float = 60) -> Path:
    img = image or natural_image(seed)
    ex = Image.Exif()
    ex[271] = "TestCam"
    ex[272] = "Model 1"
    if taken:
        ex.get_ifd(0x8769)[36867] = taken.replace("-", ":").replace("T", " ")
    if lat is not None and lon is not None:
        g = ex.get_ifd(0x8825)
        g[1] = "N" if lat >= 0 else "S"
        g[2] = _dms(lat)
        g[3] = "E" if lon >= 0 else "W"
        g[4] = _dms(lon)
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, exif=ex)
    path.write_bytes(buf.getvalue())
    old = time.time() - age_s
    os.utime(path, (old, old))
    return path


class FakeGeocoder(Geocoder):
    """Serves canned OSM answers; counts network calls."""

    def __init__(self, *args: Any, answers: dict[tuple[float, float], dict[str, Any]] | None = None, **kw: Any):
        super().__init__(*args, **kw)
        self.answers = answers or {}
        self.calls = 0
        self.fail = False

    def _fetch(self, lat: float, lon: float) -> dict[str, Any]:
        self.calls += 1
        if self.fail:
            raise GeocodeError("offline")
        best = min(self.answers.items(), key=lambda kv: (kv[0][0] - lat) ** 2 + (kv[0][1] - lon) ** 2)
        return best[1]


CONFIG = """
places:
  - name: Home
    lat: 50.0000
    lon: 19.9000
    radius_m: 50
    folder: "home"
  - name: Village
    lat: 49.7407
    lon: 20.7066
    radius_m: 4000
    folder: "{date} - Znamirowice"
geocoding:
  min_interval_s: 0
"""

PARK = (50.0612, 19.9160)
BULWAR = (50.0480, 19.9330)

ANSWERS = {
    PARK: {
        "nominatim": {
            "category": "leisure", "type": "park", "name": "Park im. dr. Henryka Jordana",
            "address": {"leisure": "Park im. dr. Henryka Jordana", "road": "aleja 3 Maja", "city": "Kraków"},
            "display_name": "Park Jordana, Kraków",
        },
        "pois": [],
    },
    BULWAR: {
        "nominatim": {
            "category": "highway", "type": "footway", "name": "Bulwar Czerwieński",
            "address": {"road": "Bulwar Czerwieński", "city": "Kraków"},
        },
        "pois": [
            {"type": "node", "lat": 50.04802, "lon": 19.93305, "tags": {"name": "Barka Pub", "amenity": "pub"}},
            {"type": "node", "lat": 50.04801, "lon": 19.93301, "tags": {"name": "Parking", "amenity": "parking"}},
        ],
    },
}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    dirs = {k: tmp_path / k for k in ("inbox", "sorted", "data", "logs", "config")}
    for d in dirs.values():
        d.mkdir()
    (dirs["config"] / "config.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("PHOTOSORTER_INBOX", str(dirs["inbox"]))
    monkeypatch.setenv("PHOTOSORTER_SORTED", str(dirs["sorted"]))
    monkeypatch.setenv("PHOTOSORTER_DATA", str(dirs["data"]))
    monkeypatch.setenv("PHOTOSORTER_LOGS", str(dirs["logs"]))
    monkeypatch.setenv("PHOTOSORTER_CONFIG", str(dirs["config"] / "config.yaml"))
    return dirs


def make_engine(answers: dict | None = None) -> Engine:
    settings = load_settings()
    eng = Engine(settings, EventBus())
    eng.geocoder.close()
    eng.geocoder = FakeGeocoder(settings.geocoding, settings.naming["aliases"], eng.db, True, answers=answers or ANSWERS)
    return eng


@pytest.fixture()
def engine(env: dict[str, Path]):
    eng = make_engine()
    yield eng
    eng.close()


def scan(eng: Engine) -> dict[str, Any]:
    eng.start_scan()
    eng.wait_idle()
    return eng.job["result"]


def by_name(eng: Engine) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in eng.cards()}
