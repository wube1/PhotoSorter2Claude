import os
from pathlib import Path

from tests.conftest import BULWAR, PARK, by_name, document_image, make_engine, scan, write_photo

from app.proposals import STATUS_DUPLICATE, STATUS_READY, STATUS_REVIEW


def test_full_flow(env, engine):
    inbox, out = env["inbox"], env["sorted"]
    write_photo(inbox / "park1.jpg", taken="2025-06-23T12:00:00", lat=PARK[0], lon=PARK[1], seed=1)
    write_photo(inbox / "sub" / "park2.jpg", taken="2025-06-23T12:40:00", lat=PARK[0] + 0.0004, lon=PARK[1], seed=2)
    write_photo(inbox / "bulwar.jpg", taken="2025-06-23T18:00:00", lat=BULWAR[0], lon=BULWAR[1], seed=3)
    write_photo(inbox / "home.jpg", taken="2025-06-24T09:00:00", lat=50.0002, lon=19.9002, seed=4)
    write_photo(inbox / "village.jpg", taken="2025-07-01T10:00:00", lat=49.75, lon=20.72, seed=5)
    write_photo(inbox / "nogps_near.jpg", taken="2025-06-23T12:20:00", seed=6)
    write_photo(inbox / "nogps_alone.jpg", taken="2025-05-01T10:00:00", seed=7)
    write_photo(inbox / "doc.jpg", taken="2025-06-25T10:00:00", lat=PARK[0], lon=PARK[1], image=document_image())
    (inbox / "dup.jpg").write_bytes((inbox / "park1.jpg").read_bytes())
    os.utime(inbox / "dup.jpg", (1, 1))
    (inbox / "notes.txt").write_text("ignored")

    result = scan(engine)
    assert "error" not in result, result
    cards = by_name(engine)
    assert set(cards) == {"park1.jpg", "park2.jpg", "bulwar.jpg", "home.jpg", "village.jpg", "nogps_near.jpg",
                          "nogps_alone.jpg", "doc.jpg", "dup.jpg"}

    assert cards["park1.jpg"]["folder"] == "23.06.2025 - Kraków - Park Jordana"
    assert cards["park1.jpg"]["status"] == STATUS_READY
    assert cards["park2.jpg"]["folder"] == "23.06.2025 - Kraków - Park Jordana"  # same session
    assert "same session" in cards["park2.jpg"]["reason"]
    assert cards["bulwar.jpg"]["folder"] == "23.06.2025 - Kraków - Barka Pub"
    assert cards["home.jpg"]["folder"] == "home"
    assert cards["village.jpg"]["folder"] == "01.07.2025 - Znamirowice"
    assert cards["nogps_near.jpg"]["folder"] == "23.06.2025 - Kraków - Park Jordana"
    assert cards["nogps_near.jpg"]["status"] == STATUS_REVIEW
    assert cards["nogps_alone.jpg"]["folder"] == "01.05.2025"
    assert cards["nogps_alone.jpg"]["status"] == STATUS_REVIEW
    assert cards["doc.jpg"]["folder"] == "25.06.2025 - documents", cards["doc.jpg"]
    assert cards["dup.jpg"]["status"] == STATUS_DUPLICATE
    assert engine.thumb_path(cards["park1.jpg"]["id"]) is not None

    # the geocoder is called once per session (park, bulwar), results cached
    calls = engine.geocoder.calls
    assert calls == 2
    scan(engine)
    assert engine.geocoder.calls == calls

    # manual override survives rescans and restarts
    engine.set_manual_folder([cards["nogps_alone.jpg"]["id"]], "{date} - Wawel")
    rep = engine.add_replacement("23.06.2025 - Kraków - Barka Pub", "{date} - Kraków - Bulwar Czerwieński")
    assert rep["id"]
    engine.close()
    engine2 = make_engine()
    scan(engine2)
    cards = by_name(engine2)
    assert cards["nogps_alone.jpg"]["folder"] == "01.05.2025 - Wawel"
    assert cards["nogps_alone.jpg"]["status"] == STATUS_READY
    assert cards["bulwar.jpg"]["folder"] == "23.06.2025 - Kraków - Bulwar Czerwieński"
    assert len(engine2.replacements()) == 1

    # move every ready card
    ready = {n for n, c in cards.items() if c["status"] == STATUS_READY}
    engine2.start_move(None)
    engine2.wait_idle()
    res = engine2.job["result"]
    assert res["moved"] == len(ready), res
    assert (out / "23.06.2025 - Kraków - Park Jordana" / "park2.jpg").is_file()
    assert (out / "home" / "home.jpg").is_file()
    assert (out / "01.05.2025 - Wawel" / "nogps_alone.jpg").is_file()
    assert not (inbox / "sub").exists()  # emptied subfolder cleaned up
    left = by_name(engine2)
    assert set(left) == {"nogps_near.jpg", "doc.jpg", "dup.jpg"}
    # replacement rule gone once its files moved
    assert engine2.replacements() == []

    # approving the duplicate: identical file already in destination -> stays as duplicate
    dup_id = left["dup.jpg"]["id"]
    engine2.set_approved([dup_id], True)
    engine2.start_move([dup_id])
    engine2.wait_idle()
    assert engine2.job["result"]["duplicates"] == 1
    assert by_name(engine2)["dup.jpg"]["status"] == STATUS_DUPLICATE

    # delete
    engine2.start_delete([dup_id])
    engine2.wait_idle()
    assert not (inbox / "dup.jpg").exists()
    assert "dup.jpg" not in by_name(engine2)
    engine2.close()


def test_name_collision_gets_suffix(env, engine):
    inbox, out = env["inbox"], env["sorted"]
    write_photo(inbox / "a.jpg", taken="2025-06-24T09:00:00", lat=50.0002, lon=19.9002, seed=10)
    (out / "home").mkdir()
    (out / "home" / "a.jpg").write_bytes(b"different")
    scan(engine)
    engine.start_move(None)
    engine.wait_idle()
    assert (out / "home" / "a (1).jpg").is_file()
    assert (out / "home" / "a.jpg").read_bytes() == b"different"


def test_geocoder_failure_is_review_and_not_cached(env, engine):
    write_photo(env["inbox"] / "p.jpg", taken="2025-06-23T12:00:00", lat=PARK[0], lon=PARK[1])
    engine.geocoder.fail = True
    res = scan(engine)
    assert res["failed"] == 1
    c = by_name(engine)["p.jpg"]
    assert c["status"] == STATUS_REVIEW and c["folder"] == "23.06.2025"
    engine.geocoder.fail = False
    scan(engine)
    assert by_name(engine)["p.jpg"]["status"] == STATUS_READY


def test_trash_mode(env, monkeypatch):
    cfg = env["config"] / "config.yaml"
    cfg.write_text(cfg.read_text() + "\ndelete_mode: trash\n")
    eng = make_engine()
    write_photo(env["inbox"] / "x.jpg", taken="2025-06-23T12:00:00")
    scan(eng)
    eng.start_delete([by_name(eng)["x.jpg"]["id"]])
    eng.wait_idle()
    assert (env["inbox"] / ".photosorter-trash" / "x.jpg").is_file()
    scan(eng)
    assert by_name(eng) == {}
    eng.close()


def test_fresh_files_are_skipped(env, engine):
    write_photo(env["inbox"] / "copying.jpg", taken="2025-06-23T12:00:00", age_s=0)
    scan(engine)
    assert by_name(engine) == {}


def test_natural_photos_are_not_documents(env, engine):
    for i in range(6):
        write_photo(env["inbox"] / f"n{i}.jpg", taken="2025-06-23T12:00:00", seed=100 + i)
    scan(engine)
    for c in engine.cards():
        assert "document" not in c["folder"], (c["name"], c["doc_score"])
