"""Interfaz web local: pegas una URL, ves el progreso en vivo y abres el reporte."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from ..config import CrawlConfig
from .jobs import JobManager

HERE = Path(__file__).parent
KEEPALIVE_S = 15


def normalize_target(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("Debes indicar una URL")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname and parsed.hostname != "localhost":
        raise ValueError(f"URL no válida: {url}")
    return url


def create_app(output_dir: str = "output") -> FastAPI:
    manager = JobManager()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        for job in manager.list():  # cancela escaneos en curso al cerrar
            manager.cancel(job)
        await asyncio.sleep(0)

    app = FastAPI(title="PaginaBuscador Crawler", version="0.1.0", lifespan=lifespan)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.state.jobs = manager
    app.state.output_dir = output_dir

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {"defaults": CrawlConfig(start_url="https://example.com")})

    @app.post("/api/scans")
    async def create_scan(payload: dict[str, Any]):
        data = dict(payload or {})
        try:
            data["start_url"] = normalize_target(data.get("start_url") or data.get("url") or "")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        data.pop("url", None)
        data.setdefault("output_dir", app.state.output_dir)
        try:
            config = CrawlConfig(**{k: v for k, v in data.items() if k in CrawlConfig.model_fields})
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc
        job = manager.create(config)
        manager.start(job)
        return job.public()

    @app.get("/api/scans")
    async def list_scans():
        return [j.public() for j in manager.list()]

    def _job(job_id: str):
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Escaneo no encontrado")
        return job

    @app.get("/api/scans/{job_id}")
    async def get_scan(job_id: str):
        return _job(job_id).public()

    @app.post("/api/scans/{job_id}/cancel")
    async def cancel_scan(job_id: str):
        job = _job(job_id)
        return {"cancelled": manager.cancel(job), "status": job.status}

    @app.get("/api/scans/{job_id}/events")
    async def scan_events(job_id: str, request: Request):
        job = _job(job_id)
        last = request.headers.get("last-event-id")
        start = int(last) + 1 if last and last.isdigit() else 0

        async def stream():
            cursor = start
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                events = await job.wait_events(cursor, KEEPALIVE_S)
                if events:
                    for ev in events:
                        yield f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    cursor = events[-1]["seq"] + 1
                elif job.finished:
                    break
                else:
                    yield ": keepalive\n\n"
                if job.finished and cursor >= len(job.events):
                    break

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def _file(job_id: str, kind: str) -> Path:
        job = _job(job_id)
        path = job.files.get(kind)
        if not path or not Path(path).exists():
            raise HTTPException(status_code=404, detail=f"El archivo {kind.upper()} no está disponible")
        return Path(path)

    @app.get("/reports/{job_id}")
    async def report_html(job_id: str):
        return FileResponse(_file(job_id, "html"), media_type="text/html")

    @app.get("/reports/{job_id}/json")
    async def report_json(job_id: str):
        return FileResponse(_file(job_id, "json"), media_type="application/json",
                            filename=f"reporte_{job_id}.json")

    @app.get("/reports/{job_id}/pdf")
    async def report_pdf(job_id: str):
        return FileResponse(_file(job_id, "pdf"), media_type="application/pdf",
                            filename=f"reporte_{job_id}.pdf")

    return app


app = create_app()
