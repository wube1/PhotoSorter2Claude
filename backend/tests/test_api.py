import base64

from fastapi.testclient import TestClient

from tests.conftest import PARK, make_engine, write_photo

from app.config import load_settings
from app.main import create_app

H = {"X-PhotoSorter": "1"}


def client(eng):
    return TestClient(create_app(load_settings(), eng))


def test_api_flow_and_csrf(env):
    write_photo(env["inbox"] / "p.jpg", taken="2025-06-23T12:00:00", lat=PARK[0], lon=PARK[1])
    eng = make_engine()
    with client(eng) as c:
        assert c.get("/healthz").json()["status"] == "ok"
        assert c.post("/api/scan").status_code == 403  # missing CSRF header
        assert c.post("/api/scan", headers=H).status_code == 202
        eng.wait_idle()
        state = c.get("/api/state").json()
        card = state["cards"][0]
        assert card["folder"] == "23.06.2025 - Kraków - Park Jordana"
        assert c.get(card["thumb"]).headers["content-type"] == "image/webp"
        assert c.get(f"/api/preview/{card['id']}").headers["content-type"] == "image/jpeg"
        r = c.post("/api/cards/folder", json={"ids": [card["id"]], "folder": "../../x"}, headers=H)
        assert r.json()["cards"][0]["folder"] == "..-..-x" or "/" not in r.json()["cards"][0]["folder"]
        assert c.post("/api/cards/folder", json={"ids": [card["id"]], "folder": "///"}, headers=H).status_code == 422
        assert c.post("/api/delete", json={"ids": [card["id"]], "confirm": "yes"}, headers=H).status_code == 422
        assert c.post("/api/delete", json={"ids": [card["id"]], "confirm": "DELETE"}, headers=H).status_code == 202
        eng.wait_idle()
        assert c.get("/api/state").json()["cards"] == []
        assert "Content-Security-Policy" in c.get("/healthz").headers


def test_basic_auth(env, monkeypatch):
    monkeypatch.setenv("PHOTOSORTER_AUTH_USER", "me")
    monkeypatch.setenv("PHOTOSORTER_AUTH_PASSWORD", "secret")
    eng = make_engine()
    with client(eng) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/api/state").status_code == 401
        tok = base64.b64encode(b"me:secret").decode()
        assert c.get("/api/state", headers={"Authorization": f"Basic {tok}"}).status_code == 200
        bad = base64.b64encode(b"me:nope").decode()
        assert c.get("/api/state", headers={"Authorization": f"Basic {bad}"}).status_code == 401


def test_allowed_hosts(env, monkeypatch):
    monkeypatch.setenv("PHOTOSORTER_ALLOWED_HOSTS", "photos.lan")
    eng = make_engine()
    with client(eng) as c:
        assert c.get("/api/state").status_code == 400
        assert c.get("/api/state", headers={"Host": "photos.lan:8080"}).status_code == 200


def test_healthz_bypasses_host_and_auth(env, monkeypatch):
    monkeypatch.setenv("PHOTOSORTER_ALLOWED_HOSTS", "photos.lan")
    monkeypatch.setenv("PHOTOSORTER_AUTH_USER", "me")
    monkeypatch.setenv("PHOTOSORTER_AUTH_PASSWORD", "secret")
    eng = make_engine()
    with client(eng) as c:
        assert c.get("/healthz", headers={"Host": "127.0.0.1:8080"}).status_code == 200
