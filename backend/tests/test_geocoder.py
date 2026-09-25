from tests.conftest import ANSWERS, BULWAR, PARK, FakeGeocoder

from app.config import DEFAULTS


def make():
    return FakeGeocoder(DEFAULTS["geocoding"], DEFAULTS["naming"]["aliases"], None, True)


def test_park_uses_alias():
    g = make()
    r = g.interpret(ANSWERS[PARK], *PARK)
    assert r["city"] == "Kraków"
    assert r["place"] == "Park Jordana"
    assert r["place_kind"] == "area"


def test_nearby_poi_wins_and_ignored_values_skipped():
    g = make()
    r = g.interpret(ANSWERS[BULWAR], *BULWAR)
    assert r["place"] == "Barka Pub"
    assert r["place_kind"] == "poi"


def test_street_fallback():
    g = make()
    raw = {"nominatim": {"category": "highway", "type": "footway", "address": {"road": "Bulwar Czerwieński", "city": "Kraków"}}, "pois": []}
    r = g.interpret(raw, *BULWAR)
    assert r["place"] == "Bulwar Czerwieński"
    assert r["place_kind"] == "street"


def test_village_and_far_poi_ignored():
    g = make()
    raw = {
        "nominatim": {"category": "place", "type": "house", "address": {"village": "Znamirowice", "county": "powiat"}},
        "pois": [{"type": "way", "center": {"lat": 49.75, "lon": 20.72}, "tags": {"name": "Big Lake Park", "leisure": "park"}}],
    }
    r = g.interpret(raw, 49.7407, 20.7066)
    assert r["city"] == "Znamirowice"
    assert r["place"] is None
