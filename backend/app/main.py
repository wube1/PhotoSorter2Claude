"""FastAPI application: JSON API, Server-Sent Events and the built web UI."""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import logging.handlers
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import Settings, load_settings
from .engine import BusyError, Engine
from .events import EventBus
from .media import make_jpeg_preview

log = logging.getLogger("photosorter")

STATIC_DIR = (Path(__file__).resolve().parent / "static").resolve()
CSRF_HEADER = "x-photosorter"
MAX_IDS = 100_000


def setup_logging(settings: Settings) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    for h in list(root.handlers):
        root.removeHandler(h)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    try:
        settings.logs.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            settings.logs / "photosorter.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as exc:
        root.warning("File logging disabled (%s): %s", settings.logs, exc)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# ------------------------------------------------------------------ models
class IdsBody(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=MAX_IDS)


class FolderBody(IdsBody):
    folder: str | None = Field(default=None, max_length=500)


class ApproveBody(IdsBody):
    approved: bool = True


class MoveBody(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=MAX_IDS)


class DeleteBody(IdsBody):
    confirm: str


class ReplacementBody(BaseModel):
    from_folder: str = Field(max_length=500)
    to_folder: str = Field(max_length=500)


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or load_settings()
    bus = engine.bus if engine else EventBus()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal engine
        setup_logging(settings)
        if settings.config_error:
            log.error("Config file could not be loaded, using defaults: %s", settings.config_error)
        elif not settings.config_loaded:
            log.warning("No config file at %s – using built-in defaults", settings.config_file)
        bus.bind_loop(asyncio.get_running_loop())
        if engine is None:
            engine = Engine(settings, bus)
        app.state.engine = engine
        log.info("PhotoSorter2Claude %s started. inbox=%s sorted=%s", __version__, settings.inbox, settings.sorted)
        yield
        engine.close()

    app = FastAPI(title="PhotoSorter2Claude", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)

    def eng() -> Engine:
        return app.state.engine

    # --------------------------------------------------------- security
    auth_enabled = bool(settings.auth_user and settings.auth_password)

    @app.middleware("http")
    async def security(request: Request, call_next: Any) -> Response:
        path = request.url.path
        if settings.allowed_hosts and path != "/healthz":
            host = (request.headers.get("host") or "").split(":")[0].lower()
            if host not in settings.allowed_hosts:
                return JSONResponse({"detail": "Host not allowed"}, status_code=400)
        if auth_enabled and path != "/healthz":
            ok = False
            header = request.headers.get("authorization", "")
            if header.lower().startswith("basic "):
                try:
                    user, _, pwd = base64.b64decode(header[6:]).decode("utf-8").partition(":")
                    ok = secrets.compare_digest(user.encode(), settings.auth_user.encode()) & secrets.compare_digest(
                        pwd.encode(), settings.auth_password.encode()
                    )
                except (binascii.Error, UnicodeDecodeError):
                    ok = False
            if not ok:
                return Response(
                    "Authentication required", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="PhotoSorter2Claude", charset="UTF-8"'},
                )
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != "1":
            # browsers cannot send custom headers cross-site without CORS (which we never allow)
            return JSONResponse({"detail": "Missing X-PhotoSorter header"}, status_code=403)
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        return response

    # -------------------------------------------------------------- api
    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return await run_in_threadpool(eng().state)

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        queue = bus.subscribe()

        async def stream() -> AsyncIterator[str]:
            try:
                yield "retry: 3000\n\n"
                yield f"event: hello\ndata: {{\"version\": \"{__version__}\"}}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=15)
                        yield msg
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                bus.unsubscribe(queue)

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def _busy(exc: BusyError) -> HTTPException:
        return HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/scan", status_code=202)
    async def scan() -> dict[str, Any]:
        try:
            eng().start_scan()
        except BusyError as exc:
            raise _busy(exc) from exc
        return {"started": True}

    @app.post("/api/cards/folder")
    async def set_folder(body: FolderBody) -> dict[str, Any]:
        try:
            cards = await run_in_threadpool(eng().set_manual_folder, body.ids, body.folder)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"cards": cards}

    @app.post("/api/cards/approve")
    async def approve(body: ApproveBody) -> dict[str, Any]:
        return {"cards": await run_in_threadpool(eng().set_approved, body.ids, body.approved)}

    @app.post("/api/cards/reset")
    async def reset(body: IdsBody) -> dict[str, Any]:
        return {"cards": await run_in_threadpool(eng().reset, body.ids)}

    @app.post("/api/replacements")
    async def add_replacement(body: ReplacementBody) -> dict[str, Any]:
        try:
            return await run_in_threadpool(eng().add_replacement, body.from_folder, body.to_folder)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/replacements/{rep_id}")
    async def delete_replacement(rep_id: int) -> dict[str, Any]:
        await run_in_threadpool(eng().delete_replacement, rep_id)
        return {"ok": True}

    @app.post("/api/move", status_code=202)
    async def move(body: MoveBody) -> dict[str, Any]:
        try:
            eng().start_move(body.ids)
        except BusyError as exc:
            raise _busy(exc) from exc
        return {"started": True}

    @app.post("/api/delete", status_code=202)
    async def delete(body: DeleteBody) -> dict[str, Any]:
        if body.confirm != "DELETE":
            raise HTTPException(status_code=422, detail='Type DELETE to confirm')
        if not body.ids:
            raise HTTPException(status_code=422, detail="Nothing selected")
        try:
            eng().start_delete(body.ids)
        except BusyError as exc:
            raise _busy(exc) from exc
        return {"started": True}

    @app.get("/api/thumb/{file_id}")
    async def thumb(file_id: int) -> Response:
        path = await run_in_threadpool(eng().thumb_path, file_id)
        if not path:
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/api/preview/{file_id}")
    async def preview(file_id: int) -> Response:
        e = eng()
        path = await run_in_threadpool(e.source_path, file_id)
        if not path:
            raise HTTPException(status_code=404)
        try:
            data = await run_in_threadpool(make_jpeg_preview, path, int(settings.scan.get("preview_size", 1600)))
        except Exception as exc:
            raise HTTPException(status_code=415, detail=f"Cannot render preview: {exc}") from exc
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})

    # --------------------------------------------------------------- ui
    if (STATIC_DIR / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> Response:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (STATIC_DIR / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(STATIC_DIR):
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def run() -> None:  # pragma: no cover - container entrypoint
    import os

    import uvicorn

    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=os.environ.get("PHOTOSORTER_HOST", "0.0.0.0"),
        port=int(os.environ.get("PHOTOSORTER_LISTEN_PORT", "8080")),
        proxy_headers=False,
        server_header=False,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
