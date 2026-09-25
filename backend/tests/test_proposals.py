from datetime import datetime

from app.proposals import GeoPoint, build_sessions, render, sanitize_folder

FMT = "%d.%m.%Y"


def test_sanitize_blocks_traversal_and_bad_chars():
    assert sanitize_folder("../../etc") == "..-..-etc".lstrip(".").lstrip("-") or "/" not in sanitize_folder("../../etc")
    assert sanitize_folder("a/b\\c:d*e?x") == "a-b-c-d-e-x"
    assert sanitize_folder("..") == ""
    assert sanitize_folder("   ") == ""
    assert "/" not in sanitize_folder("x/../../y")


def test_render_template_and_empty_parts():
    t = "2025-06-23T14:05:00"
    assert render("{date} - {city} - {place}", t, FMT, city="Kraków", place="Park Jordana") == "23.06.2025 - Kraków - Park Jordana"
    assert render("{date} - {city} - {place}", t, FMT, city="Kraków", place="") == "23.06.2025 - Kraków"
    assert render("{date} - {city} - {place}", t, FMT, city="", place="X") == "23.06.2025 - X"
    assert render("home", t, FMT) == "home"
    assert render("{year}/{month}", t, FMT) == "2025-06"
    # malicious format specs are used literally, never evaluated
    assert render("{date.__class__}", t, FMT) == "{date.__class__}"


def test_sessions_split_by_time_and_distance():
    base = datetime(2025, 6, 23, 12, 0)
    pts = [
        GeoPoint(1, base, 50.0612, 19.9160),
        GeoPoint(2, base.replace(minute=30), 50.0615, 19.9165),  # 45 m away, 30 min later
        GeoPoint(3, base.replace(hour=13, minute=10), 50.0613, 19.9161),
        GeoPoint(4, base.replace(hour=16), 50.0613, 19.9161),  # time gap > 90 min
        GeoPoint(5, base.replace(hour=16, minute=10), 50.0480, 19.9330),  # far away
    ]
    sessions = build_sessions(pts, 90, 250)
    assert [[p.id for p in s] for s in sessions] == [[1, 2, 3], [4], [5]]
