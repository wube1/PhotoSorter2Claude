"""The sorting engine: scanning, proposals, manual overrides, moving and deleting.

All long operations run as a single background "job" (scan, move or delete) so the web
server stays responsive and progress is streamed live to every open browser.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .config import TRASH_DIR_NAME, Settings
from .db import Database
from .events import EventBus
from .geo import haversine_m, match_place
from .geocoder import GeocodeError, Geocoder
from .media import analyze, sha256_file
from .proposals import (
    DUP_IN_DESTINATION,
    STATUS_READY,
    STATUS_REVIEW,
    GeoPoint,
    build_sessions,
    effective,
    location_folder,
    parse_dt,
    render,
    sanitize_folder,
)

log = logging.getLogger(__name__)


class BusyError(RuntimeError):
    pass


def _n(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


class Engine:
    def __init__(self, settings: Settings, bus: EventBus, geocoder: Geocoder | None = None):
        self.settings = settings
        self.bus = bus
        self.db = Database(settings.data / "photosorter.db")
        self.thumbs = settings.data / "thumbs"
        self.thumbs.mkdir(parents=True, exist_ok=True)
        self.geocoder = geocoder or Geocoder(
            settings.geocoding, settings.naming.get("aliases") or {}, self.db, settings.naming.get("street_fallback", True)
        )
        self._job_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self.job: dict[str, Any] = {
            "running": False,
            "kind": None,
            "phase": "idle",
            "done": 0,
            "total": 0,
            "message": "Ready",
            "started_at": None,
            "finished_at": None,
            "result": None,
        }
        self._last_progress_emit = 0.0

    def close(self) -> None:
        self.geocoder.close()
        self.db.close()

    # ================================================================ state
    @property
    def date_format(self) -> str:
        return str(self.settings.naming["date_format"])

    def card(self, row: Any, reps: list[Any]) -> dict[str, Any]:
        eff = effective(row, reps, self.date_format)
        loc = json.loads(row["location"]) if row["location"] else None
        return {
            "id": row["id"],
            "name": Path(row["rel_path"]).name,
            "path": row["rel_path"],
            "size": row["size"],
            "taken_at": row["taken_at"],
            "taken_source": row["taken_source"],
            "lat": row["lat"],
            "lon": row["lon"],
            "width": row["width"],
            "height": row["height"],
            "camera": row["camera"],
            "doc_score": row["doc_score"],
            "location": loc,
            "auto_folder": row["auto_folder"],
            "manual_folder": row["manual_folder"],
            "approved": bool(row["approved"]),
            "dup_of": row["dup_of"],
            "folder": eff["folder"],
            "status": eff["status"],
            "reason": eff["reason"],
            "manual": eff["manual"],
            "thumb": f"/api/thumb/{row['id']}?v={(row['sha256'] or '')[:10]}" if row["sha256"] else None,
        }

    def cards(self, ids: Iterable[int] | None = None) -> list[dict[str, Any]]:
        reps = self.db.replacements()
        rows = self.db.all_files() if ids is None else self.db.files_by_ids(ids)
        return [self.card(r, reps) for r in rows]

    def replacements(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.replacements()]

    def predefined_folders(self) -> list[str]:
        return [str(f) for f in self.settings.raw.get("predefined_folders") or []]

    def state(self) -> dict[str, Any]:
        s = self.settings
        return {
            "version": __version__,
            "cards": self.cards(),
            "replacements": self.replacements(),
            "predefined_folders": self.predefined_folders(),
            "job": dict(self.job),
            "config": {
                "loaded": s.config_loaded,
                "error": s.config_error,
                "file": str(s.config_file),
                "places": [p.name for p in s.places],
                "geocoding": bool(s.geocoding.get("enabled", True)),
                "delete_mode": s.raw.get("delete_mode", "permanent"),
                "date_format": self.date_format,
                "inbox": str(s.inbox),
                "sorted": str(s.sorted),
            },
        }

    # ============================================================== events
    def _emit_cards(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        for start in range(0, len(ids), 200):
            self.bus.publish("cards", {"cards": self.cards(ids[start : start + 200])})

    def _emit_removed(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if ids:
            self.bus.publish("removed", {"ids": ids})

    def _progress(self, force: bool = False, **fields: Any) -> None:
        with self._state_lock:
            self.job.update(fields)
            snapshot = dict(self.job)
        now = time.monotonic()
        if force or now - self._last_progress_emit > 0.2:
            self._last_progress_emit = now
            self.bus.publish("job", snapshot)

    # ================================================================ jobs
    def _start_job(self, kind: str, target: Any, *args: Any) -> None:
        if not self._job_lock.acquire(blocking=False):
            raise BusyError(f"Another operation is running: {self.job.get('kind')}")
        self._progress(
            force=True, running=True, kind=kind, phase="starting", done=0, total=0, message=f"Starting {kind}…",
            started_at=time.time(), finished_at=None, result=None,
        )

        def runner() -> None:
            result: dict[str, Any] | None = None
            try:
                result = target(*args)
                message = (result or {}).get("message", "Done")
            except Exception as exc:  # keep the app alive, report the error
                log.exception("%s failed", kind)
                message = f"{kind.capitalize()} failed: {exc}"
                result = {"error": str(exc), "message": message}
            finally:
                self._progress(
                    force=True, running=False, phase="idle", message=message, finished_at=time.time(), result=result,
                )
                self._job_lock.release()

        threading.Thread(target=runner, name=f"job-{kind}", daemon=True).start()

    def wait_idle(self, timeout: float = 60) -> None:
        """Test helper: block until no job is running."""
        end = time.time() + timeout
        while self.job["running"] and time.time() < end:
            time.sleep(0.02)

    def start_scan(self) -> None:
        self._start_job("scan", self._scan)

    def start_move(self, ids: list[int] | None) -> None:
        self._start_job("move", self._move, ids)

    def start_delete(self, ids: list[int]) -> None:
        self._start_job("delete", self._delete, ids)

    # ================================================================ scan
    def _discover(self) -> dict[str, tuple[int, float]]:
        exts = {e.lower() for e in self.settings.scan["extensions"]}
        min_age = float(self.settings.scan.get("min_file_age_s", 5))
        now = time.time()
        found: dict[str, tuple[int, float]] = {}
        root = self.settings.inbox
        for dirpath, dirnames, filenames in os.walk(root):
            # skip hidden folders (incl. our trash) and Synology/QNAP/macOS junk
            dirnames[:] = [
                d for d in dirnames if not d.startswith(".") and not d.startswith("@") and d != TRASH_DIR_NAME
            ]
            for name in filenames:
                if name.startswith("."):
                    continue
                if os.path.splitext(name)[1].lower() not in exts:
                    continue
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                if now - st.st_mtime < min_age:
                    continue  # still being copied, pick it up next time
                rel = os.path.relpath(full, root)
                found[rel] = (st.st_size, st.st_mtime)
                if len(found) % 200 == 0:
                    self._progress(phase="discovering", message=f"Found {len(found)} photos…", done=len(found))
        return found

    def _scan(self) -> dict[str, Any]:
        if not self.settings.inbox.is_dir():
            raise RuntimeError(f"Inbox folder {self.settings.inbox} does not exist or is not mounted")
        self._progress(force=True, phase="discovering", message="Looking for photos…")
        found = self._discover()
        index = self.db.file_index()

        gone = [row["id"] for rel, row in index.items() if rel not in found]
        if gone:
            self._remove_rows(gone)

        todo: list[tuple[int, str]] = []
        for rel, (size, mtime) in found.items():
            row = index.get(rel)
            if row and row["size"] == size and abs(row["mtime"] - mtime) < 1e-3 and row["analyzed"]:
                continue
            fid = self.db.insert_or_reset_file(rel, size, mtime)
            todo.append((fid, rel))
        if todo:
            self._emit_cards([fid for fid, _ in todo])

        total = len(todo)
        self._progress(force=True, phase="analyzing", done=0, total=total, message=f"Analyzing {total} new photos…")
        thumb_size = int(self.settings.scan.get("thumbnail_size", 400))
        detect_docs = bool(self.settings.documents.get("enabled", True))
        workers = max(1, int(self.settings.scan.get("workers", 2)))
        done = 0
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="analyze") as pool:
            futures = {
                pool.submit(analyze, self.settings.inbox / rel, thumb_size, detect_docs): (fid, rel) for fid, rel in todo
            }
            for fut in as_completed(futures):
                fid, rel = futures[fut]
                info = fut.result()
                if info.thumb and info.sha256:
                    self._store_thumb(info.sha256, info.thumb)
                self.db.update_file(
                    fid,
                    sha256=info.sha256 or None,
                    taken_at=info.taken_at,
                    taken_source=info.taken_source,
                    lat=info.lat,
                    lon=info.lon,
                    width=info.width,
                    height=info.height,
                    camera=info.camera,
                    doc_score=info.doc_score,
                    error=info.error,
                    analyzed=1,
                    auto_status="pending",
                )
                done += 1
                self._emit_cards([fid])
                self._progress(phase="analyzing", done=done, total=total, message=f"Analyzed {done}/{total}: {Path(rel).name}")

        self._mark_duplicates()
        located = self._propose()
        pruned = self.prune_replacements()
        cards = self.cards()
        ready = sum(1 for c in cards if c["status"] == STATUS_READY)
        msg = f"Scan finished: {_n(len(cards), 'photo')} in inbox, {total} new, {ready} ready to move"
        if located.get("failed"):
            msg += f", {_n(located['failed'], 'location lookup')} failed (will retry next scan)"
        self.bus.publish("reload", {})
        return {"message": msg, "total": len(cards), "new": total, "removed": len(gone), "ready": ready,
                "pruned_replacements": pruned, **located}

    def _store_thumb(self, sha: str, data: bytes) -> None:
        path = self.thumbs / sha[:2] / f"{sha}.webp"
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def thumb_path(self, file_id: int) -> Path | None:
        row = self.db.file(file_id)
        if not row or not row["sha256"]:
            return None
        path = self.thumbs / row["sha256"][:2] / f"{row['sha256']}.webp"
        return path if path.is_file() else None

    def source_path(self, file_id: int) -> Path | None:
        row = self.db.file(file_id)
        if not row:
            return None
        path = self._safe_inbox_path(row["rel_path"])
        return path if path and path.is_file() else None

    def _safe_inbox_path(self, rel: str) -> Path | None:
        root = self.settings.inbox.resolve()
        path = (root / rel).resolve()
        return path if path.is_relative_to(root) else None

    def _mark_duplicates(self) -> None:
        rows = self.db.query("SELECT id, sha256, dup_of FROM files WHERE sha256 IS NOT NULL ORDER BY id")
        first: dict[str, int] = {}
        changes: list[tuple[int, int | None]] = []
        for r in rows:
            original = first.setdefault(r["sha256"], r["id"])
            want = None if original == r["id"] else original
            if r["dup_of"] == DUP_IN_DESTINATION and want is None:
                continue  # keep "already in destination" flag
            if r["dup_of"] != want:
                changes.append((r["id"], want))
        for fid, want in changes:
            self.db.update_file(fid, dup_of=want)
        if changes:
            self._emit_cards([fid for fid, _ in changes])

    # =========================================================== proposals
    def _propose(self) -> dict[str, int]:
        s = self.settings
        naming = s.naming
        fmt = self.date_format
        rows = [r for r in self.db.all_files() if r["analyzed"]]
        updates: dict[int, dict[str, Any]] = {}
        doc_min = float(s.documents.get("min_score", 0.6))
        doc_status = STATUS_READY if s.documents.get("status") == "ready" else STATUS_REVIEW
        geo_points: list[GeoPoint] = []
        no_gps: list[Any] = []

        for r in rows:
            if r["error"]:
                updates[r["id"]] = dict(
                    auto_folder=render(naming["no_location_template"], r["taken_at"], fmt),
                    auto_status=STATUS_REVIEW, auto_reason=r["error"], location=None,
                )
                continue
            if s.documents.get("enabled", True) and r["doc_score"] is not None and r["doc_score"] >= doc_min:
                updates[r["id"]] = dict(
                    auto_folder=render(naming["documents_template"], r["taken_at"], fmt),
                    auto_status=doc_status,
                    auto_reason=f"Looks like a paper document ({round(r['doc_score'] * 100)}% match)",
                    location=None,
                )
                continue
            if r["lat"] is not None and r["lon"] is not None:
                place = match_place(r["lat"], r["lon"], s.places)
                if place:
                    dist = haversine_m(r["lat"], r["lon"], place.lat, place.lon)
                    updates[r["id"]] = dict(
                        auto_folder=render(place.folder, r["taken_at"], fmt),
                        auto_status=STATUS_READY,
                        auto_reason=f"Custom place “{place.name}” ({dist:.0f} m from its centre)",
                        location=json.dumps({"place": place.name, "source": "custom"}, ensure_ascii=False),
                    )
                    continue
                geo_points.append(GeoPoint(r["id"], parse_dt(r["taken_at"]), r["lat"], r["lon"]))
            else:
                no_gps.append(r)

        # write the cheap decisions immediately so tiles update fast
        self._apply_updates(updates)
        updates = {}

        g = s.grouping
        if g.get("enabled", True):
            sessions = build_sessions(geo_points, float(g.get("max_gap_minutes", 90)), float(g.get("radius_m", 250)))
        else:
            sessions = [[p] for p in geo_points]

        by_id = {r["id"]: r for r in rows}
        stats = {"located": 0, "failed": 0, "sessions": len(sessions)}
        total = len(sessions)
        self._progress(force=True, phase="locating", done=0, total=total,
                       message=f"Looking up {total} locations…" if total else "No GPS photos to locate")
        session_info: list[tuple[list[GeoPoint], str, str]] = []
        for i, session in enumerate(sessions, start=1):
            anchor = session[0]
            anchor_row = by_id[anchor.id]
            loc: dict[str, Any] | None = None
            if s.geocoding.get("enabled", True):
                try:
                    loc = self.geocoder.lookup(anchor.lat, anchor.lon)
                    stats["located"] += 1
                except GeocodeError as exc:
                    log.warning("Geocoding failed for %s: %s", anchor_row["rel_path"], exc)
                    stats["failed"] += 1
                    status, reason = STATUS_REVIEW, "Location lookup failed (offline?) – will retry on next scan"
                    folder = render(naming["no_location_template"], anchor_row["taken_at"], fmt)
            else:
                status, reason = STATUS_REVIEW, "Geocoding is disabled in config.yaml"
                folder = render(naming["no_location_template"], anchor_row["taken_at"], fmt)
            if loc is not None:
                folder = location_folder(naming, anchor_row["taken_at"], loc.get("city"), loc.get("place"))
                if not loc.get("city") and not loc.get("place"):
                    status, reason = STATUS_REVIEW, "No town or place found at these coordinates"
                elif s.raw.get("ready_requires_place") and not loc.get("place"):
                    status, reason = STATUS_REVIEW, "Only the town is known (no specific place nearby)"
                else:
                    status = STATUS_READY
                    kind = {"poi": "nearby place", "area": "area", "street": "street", "none": "town"}.get(
                        loc.get("place_kind", "none"), "place")
                    reason = f"GPS location ({kind})"
            loc_json = json.dumps({**(loc or {}), "source": "osm"}, ensure_ascii=False) if loc else None
            for p in session:
                member_reason = reason
                if p.id != anchor.id:
                    member_reason = f"{reason}; same session as {Path(anchor_row['rel_path']).name}"
                updates[p.id] = dict(auto_folder=folder, auto_status=status, auto_reason=member_reason, location=loc_json)
            session_info.append((session, folder, status))
            self._apply_updates(updates)
            updates = {}
            self._progress(phase="locating", done=i, total=total, message=f"Located {i}/{total} sessions")

        # photos without GPS: attach to a located session close in time, else date only
        attach = g.get("attach_no_gps_by_time", True)
        max_gap = float(g.get("max_gap_minutes", 90)) * 60
        timeline: list[tuple[datetime, str, str]] = []
        for session, folder, status in session_info:
            for p in session:
                if p.taken:
                    timeline.append((p.taken, folder, Path(by_id[p.id]["rel_path"]).name))
        for r in no_gps:
            taken = parse_dt(r["taken_at"])
            best = None
            if attach and taken and r["taken_source"] == "exif":
                for t, folder, name in timeline:
                    gap = abs((t - taken).total_seconds())
                    if gap <= max_gap and (best is None or gap < best[0]):
                        best = (gap, folder, name)
            if best:
                updates[r["id"]] = dict(
                    auto_folder=best[1], auto_status=STATUS_REVIEW,
                    auto_reason=f"No GPS – taken {best[0] / 60:.0f} min from {best[2]}", location=None,
                )
            else:
                reason = "No GPS data" if r["taken_source"] == "exif" else "No GPS and no EXIF date (file date used)"
                updates[r["id"]] = dict(
                    auto_folder=render(naming["no_location_template"], r["taken_at"], fmt),
                    auto_status=STATUS_REVIEW, auto_reason=reason, location=None,
                )
        self._apply_updates(updates)
        return stats

    def _apply_updates(self, updates: dict[int, dict[str, Any]]) -> None:
        if not updates:
            return
        now = time.time()
        self.db.executemany(
            "UPDATE files SET auto_folder=?, auto_status=?, auto_reason=?, location=?, updated_at=? WHERE id=?",
            [[u["auto_folder"], u["auto_status"], u["auto_reason"], u["location"], now, fid] for fid, u in updates.items()],
        )
        self._emit_cards(updates.keys())

    # ======================================================= user overrides
    def set_manual_folder(self, ids: list[int], folder: str | None) -> list[dict[str, Any]]:
        value = folder.strip() if folder else None
        if value is not None and not render(value, "2000-01-01T00:00:00", self.date_format):
            raise ValueError("Folder name is empty after removing characters that are not allowed")
        self.db.update_files(ids, manual_folder=value)
        self._emit_cards(ids)
        return self.cards(ids)

    def set_approved(self, ids: list[int], approved: bool) -> list[dict[str, Any]]:
        self.db.update_files(ids, approved=1 if approved else 0)
        self._emit_cards(ids)
        return self.cards(ids)

    def reset(self, ids: list[int]) -> list[dict[str, Any]]:
        self.db.update_files(ids, manual_folder=None, approved=0)
        self._emit_cards(ids)
        return self.cards(ids)

    def add_replacement(self, from_folder: str, to_folder: str) -> dict[str, Any]:
        src = from_folder.strip()
        dst = to_folder.strip()
        if not src or not dst:
            raise ValueError("Both folder names are required")
        if not render(dst, "2000-01-01T00:00:00", self.date_format):
            raise ValueError("New folder name is empty after removing characters that are not allowed")
        rep_id = self.db.add_replacement(src, dst)
        self.bus.publish("replacements", {"replacements": self.replacements()})
        self._emit_all()
        return {"id": rep_id}

    def delete_replacement(self, rep_id: int) -> None:
        self.db.delete_replacement(rep_id)
        self.bus.publish("replacements", {"replacements": self.replacements()})
        self._emit_all()

    def _emit_all(self) -> None:
        self.bus.publish("reload", {})

    def prune_replacements(self) -> int:
        """Drop replacement rules that no longer match any card in the inbox."""
        reps = self.db.replacements()
        if not reps:
            return 0
        rows = self.db.all_files()
        folders = []
        for r in rows:
            f = render(r["manual_folder"], r["taken_at"], self.date_format) if r["manual_folder"] else (r["auto_folder"] or "")
            folders.append((f, r["taken_at"]))
        pruned = 0
        for rep in reps:
            hits = 0
            new_folders = []
            for f, taken in folders:
                if f == rep["from_folder"]:
                    hits += 1
                    f = render(rep["to_folder"], taken, self.date_format) or f
                new_folders.append((f, taken))
            folders = new_folders
            if hits == 0:
                self.db.delete_replacement(rep["id"])
                pruned += 1
        if pruned:
            self.bus.publish("replacements", {"replacements": self.replacements()})
        return pruned

    # ================================================================ move
    def _unique_dest(self, dest_dir: Path, name: str, src: Path, sha: str | None) -> tuple[Path | None, bool]:
        """Return (destination path, is_duplicate). Never overwrites an existing file.

        A file with identical content already in the destination folder (under any name)
        means this photo is a duplicate and is not moved."""
        try:
            size = src.stat().st_size
            if sha:
                with os.scandir(dest_dir) as it:
                    for entry in it:
                        if entry.is_file() and entry.stat().st_size == size and sha256_file(Path(entry.path)) == sha:
                            return None, True
        except OSError:
            pass
        dest = dest_dir / name
        if not dest.exists():
            return dest, False
        stem, ext = os.path.splitext(name)
        for n in range(1, 10_000):
            candidate = dest_dir / f"{stem} ({n}){ext}"
            if not candidate.exists():
                return candidate, False
        raise RuntimeError(f"Too many files named {name} in {dest_dir}")

    @staticmethod
    def _move_file(src: Path, dest: Path) -> None:
        try:
            os.rename(src, dest)  # instant when on the same mount
            return
        except OSError:
            pass
        tmp = dest.with_name(f".{dest.name}.partial")
        try:
            shutil.copy2(src, tmp)
            with open(tmp, "rb") as fh:
                os.fsync(fh.fileno())
            if tmp.stat().st_size != src.stat().st_size:
                raise OSError("size mismatch after copy")
            os.replace(tmp, dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        src.unlink()

    def _move(self, ids: list[int] | None) -> dict[str, Any]:
        cards = self.cards(ids) if ids else self.cards()
        ready = [c for c in cards if c["status"] == STATUS_READY]
        total = len(ready)
        self._progress(force=True, phase="moving", done=0, total=total, message=f"Moving {total} photos…")
        sorted_root = self.settings.sorted
        if not sorted_root.is_dir():
            raise RuntimeError(f"Output folder {sorted_root} does not exist or is not mounted")
        root_resolved = sorted_root.resolve()
        moved: list[int] = []
        duplicates: list[int] = []
        failed: list[dict[str, Any]] = []
        folders: set[str] = set()
        source_dirs: set[Path] = set()
        for i, c in enumerate(ready, start=1):
            try:
                folder = sanitize_folder(c["folder"])
                if not folder:
                    raise ValueError("empty folder name")
                src = self._safe_inbox_path(c["path"])
                if not src or not src.is_file():
                    raise FileNotFoundError("file no longer in inbox")
                dest_dir = (sorted_root / folder).resolve()
                if not dest_dir.is_relative_to(root_resolved) or dest_dir == root_resolved:
                    raise ValueError("unsafe destination")
                dest_dir.mkdir(parents=True, exist_ok=True)
                row = self.db.file(c["id"])
                dest, is_dup = self._unique_dest(dest_dir, src.name, src, row["sha256"] if row else None)
                if is_dup or dest is None:
                    self.db.update_file(c["id"], dup_of=DUP_IN_DESTINATION, approved=0)
                    duplicates.append(c["id"])
                    continue
                self._move_file(src, dest)
                source_dirs.add(src.parent)
                moved.append(c["id"])
                folders.add(folder)
                log.info("Moved %s -> %s", c["path"], dest)
            except Exception as exc:
                log.error("Could not move %s: %s", c["path"], exc)
                failed.append({"id": c["id"], "name": c["name"], "error": str(exc)})
            self._progress(phase="moving", done=i, total=total, message=f"Moved {i}/{total}")
        self._remove_rows(moved)
        if duplicates:
            self._emit_cards(duplicates)
        self._cleanup_empty_dirs(source_dirs)
        self.prune_replacements()
        msg = f"Moved {_n(len(moved), 'photo')} into {_n(len(folders), 'folder')}"
        if duplicates:
            msg += f", {len(duplicates)} already existed (marked duplicate)"
        if failed:
            msg += f", {len(failed)} failed"
        return {"message": msg, "moved": len(moved), "folders": sorted(folders), "duplicates": len(duplicates),
                "failed": failed}

    def _cleanup_empty_dirs(self, dirs: set[Path]) -> None:
        root = self.settings.inbox.resolve()
        for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
            cur = d.resolve()
            while cur != root and cur.is_relative_to(root):
                try:
                    cur.rmdir()  # only succeeds when empty
                except OSError:
                    break
                cur = cur.parent

    # ============================================================== delete
    def _delete(self, ids: list[int]) -> dict[str, Any]:
        rows = self.db.files_by_ids(ids)
        mode = self.settings.raw.get("delete_mode", "permanent")
        total = len(rows)
        self._progress(force=True, phase="deleting", done=0, total=total, message=f"Deleting {total} photos…")
        deleted: list[int] = []
        failed: list[dict[str, Any]] = []
        dirs: set[Path] = set()
        for i, r in enumerate(rows, start=1):
            try:
                src = self._safe_inbox_path(r["rel_path"])
                if src is None:
                    raise ValueError("unsafe path")
                if src.exists():
                    if mode == "trash":
                        dest = self.settings.trash_dir / r["rel_path"]
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        if dest.exists():
                            dest = dest.with_name(f"{dest.stem}.{int(time.time())}{dest.suffix}")
                        self._move_file(src, dest)
                    else:
                        src.unlink()
                dirs.add(src.parent)
                deleted.append(r["id"])
                log.info("Deleted (%s) %s", mode, r["rel_path"])
            except Exception as exc:
                log.error("Could not delete %s: %s", r["rel_path"], exc)
                failed.append({"id": r["id"], "name": Path(r["rel_path"]).name, "error": str(exc)})
            self._progress(phase="deleting", done=i, total=total, message=f"Deleted {i}/{total}")
        self._remove_rows(deleted)
        self._cleanup_empty_dirs(dirs)
        self._mark_duplicates()
        self.prune_replacements()
        verb = "Moved to trash" if mode == "trash" else "Deleted"
        msg = f"{verb} {_n(len(deleted), 'photo')}" + (f", {len(failed)} failed" if failed else "")
        return {"message": msg, "deleted": len(deleted), "failed": failed}

    def _remove_rows(self, ids: list[int]) -> None:
        if not ids:
            return
        rows = self.db.files_by_ids(ids)
        shas = {r["sha256"] for r in rows if r["sha256"]}
        self.db.delete_files(ids)
        for sha in shas:
            if not self.db.query("SELECT 1 FROM files WHERE sha256=? LIMIT 1", (sha,)):
                (self.thumbs / sha[:2] / f"{sha}.webp").unlink(missing_ok=True)
        self._emit_removed(ids)
