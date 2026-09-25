# PhotoSorter2Claude – notes for Claude sessions

Owner: wube (GitHub `wube1`). Repo is **public** → never commit personal coordinates (home etc.);
the owner's real `config.yaml` lives only on the NAS.

## What it is
Semi-automatic photo sorter web app, deployed via Portainer on TrueNAS from a Gitea mirror
(`http://192.168.50.2:3006/wube/PhotoSorter2Claude`) of this GitHub repo. Local LAN only, HTTP.
Runs as `1000:1000`, read-only root FS, 1 GB mem cap, network `CommonContainerNetwork` (external).
Volumes: inbox `/mnt/Data/pictures/!sort` → `/photos/inbox`, output `/mnt/Data/pictures/!sorted`
→ `/photos/sorted`, appdata `/mnt/Legend/containers/persistent_storage/photosorter2claude/{config(ro),data,logs}`.

## Owner's requirements (keep honouring)
- Folder naming: `DD.MM.YYYY - City/Village - Specific place` (e.g. `23.06.2025 - Kraków - Park Jordana`),
  as precise as possible (POI > area > street). Custom places with radius (home → `home`, etc.).
- Photos in the same place within a short time → same folder as the first photo.
- Paper documents → `date - documents`.
- UI: live scan progress, tiles pop up, tick boxes, click-and-drag selection, clear selection,
  predefined folder dropdown + manual folder input for ticked cards, approve, "replace folder
  everywhere" rule, "move ready" (no rescan), red delete with double confirmation, "i" icons on
  every button. Manual choices/rules persist across rescans and restarts until files moved/deleted.
- Proper semver releases, PDF documentation kept up to date with every change (docs/DOCUMENTATION.md
  → `python scripts/build_docs.py`), CHANGELOG entry per release.

## Layout
- `backend/app`: `main.py` (API/SSE/security), `engine.py` (jobs), `media.py` (EXIF, thumbs, doc
  detection), `geocoder.py` (Nominatim + Overpass, cached), `proposals.py` (naming/sessions/effective status),
  `config.py` (defaults + config.yaml + env), `db.py` (SQLite).
- `frontend/src`: React 19 + TS + Vite; `help.ts` holds all "i" texts.
- Tests: `cd backend && python -m pytest -q` (fake geocoder in `tests/conftest.py`).
- Sandbox has no Docker daemon and no access to OSM servers: test with the fake geocoder / a local mock.

## Release process
Bump `VERSION` + `frontend/package.json` version, CHANGELOG, rebuild PDF, commit, push to `main`
(the session git proxy refuses tag pushes; the workflow creates tag `vX.Y.Z` itself when it is missing)
→ `.github/workflows/release.yml` publishes `ghcr.io/wube1/photosorter2claude` and a GitHub Release.

## Status / ideas for later
- v1.0.0: initial release (see CHANGELOG).
- Possible next steps: RAW (CR2/NEF/ARW/DNG) + video support, moving sidecar files (.xmp/.aae),
  self-hosted Nominatim option, map view, undo last move, per-folder year subfolders.
