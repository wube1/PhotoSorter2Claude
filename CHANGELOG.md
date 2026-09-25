# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-09-25

### Added
- Web app (FastAPI + React) packaged as one Docker image running as `1000:1000` with a read-only
  root filesystem; ready-to-deploy `docker-compose.yaml` for Portainer (external
  `CommonContainerNetwork`, `restart: unless-stopped`, 1 GB memory cap).
- Live inbox scan with progress bar; tiles appear and update in real time (Server-Sent Events).
- Folder proposals `date - city - place` from EXIF date + GPS using OpenStreetMap
  (Nominatim for town/street/area, Overpass for nearby restaurants, pubs, museums, playgrounds …),
  Polish names, aliases, cached lookups and polite rate limiting.
- Custom places with radius (e.g. `home`, `date - Znamirowice`) that always win.
- Sessions: photos taken close together in time and space share the first photo's folder.
- Photos without GPS matched by time to a located session (needs review).
- Paper-document detection → `date - documents`.
- Duplicate detection inside the inbox and against the destination folder; never overwrites files.
- Card selection by click, click-and-drag over tiles, shift-click range, Ctrl+A; per-group select.
- Bulk actions: predefined folder dropdown, custom folder (with `{date}`), approve, reset,
  delete with double confirmation (permanent or trash mode).
- "Replace folder" rules and manual folders that survive rescans and restarts until the photos
  are moved or deleted.
- "Move ready" creates folders and moves all Ready cards without rescanning.
- "i" help icons on every button, Help dialog, preview with details and map link,
  light/dark theme, responsive layout, keyboard shortcuts.
- Optional basic-auth login and host allow-list; CSRF protection; strict security headers.
- CI (tests, UI build, container smoke test), release workflow publishing multi-arch images to
  GHCR and GitHub Releases with the PDF documentation.
