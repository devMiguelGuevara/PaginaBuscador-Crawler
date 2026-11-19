"""Gestor en memoria de escaneos lanzados desde la web."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..config import CrawlConfig


@dataclass
class Job:
    id: str
    config: CrawlConfig
    status: str = "pendiente"          # pendiente, ejecutando, completado, error, cancelado
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    finished_at: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    output_dir: str = ""
    error: str = ""
    pages_done: int = 0
    summary: list[str] = field(default_factory=list)
    task: asyncio.Task | None = None
    _cond: asyncio.Condition = field(default_factory=asyncio.Condition)

    def public(self) -> dict[str, Any]:
        last_page = next((e for e in reversed(self.events) if e.get("type") == "page"), None)
        return {
            "id": self.id,
            "url": self.config.start_url,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "pages_done": self.pages_done,
            "queued": (last_page or {}).get("queued", 0),
            "max_pages": self.config.max_pages,
            "files": {k: f"/reports/{self.id}" + ("" if k == "html" else f"/{k}") for k in self.files},
            "error": self.error,
            "summary": self.summary,
            "config": self.config.model_dump(),
        }

    async def emit(self, event: dict[str, Any]) -> None:
        if event.get("type") == "page":
            self.pages_done = max(self.pages_done, int(event.get("done", self.pages_done) or 0))
        async with self._cond:
            self.events.append({**event, "seq": len(self.events)})
            self._cond.notify_all()

    async def wait_events(self, after: int, timeout: float) -> list[dict[str, Any]]:
        """Devuelve eventos con seq >= after, esperando hasta `timeout` si no hay nuevos."""
        async with self._cond:
            if len(self.events) <= after and not self.finished:
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout)
                except asyncio.TimeoutError:
                    pass
            return self.events[after:]

    @property
    def finished(self) -> bool:
        return self.status in ("completado", "error", "cancelado")


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def create(self, config: CrawlConfig) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], config=config)
        self.jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    def start(self, job: Job) -> None:
        job.task = asyncio.create_task(self._run(job))

    async def _run(self, job: Job) -> None:
        from .. import engine
        from ..report import exporters

        loop = asyncio.get_running_loop()
        job.status = "ejecutando"
        await job.emit({"type": "phase", "message": f"Iniciando escaneo de {job.config.start_url}"})

        def progress(event: dict[str, Any]) -> None:
            # El motor puede llamar desde el propio loop (lo normal) o desde otro hilo.
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                loop.create_task(job.emit(event))
            else:
                asyncio.run_coroutine_threadsafe(job.emit(event), loop)

        try:
            report = await engine.run_crawl(job.config, progress=progress)
            await asyncio.sleep(0)  # deja salir los eventos pendientes
            if not report.summary and not report.scores:
                from ..report.builder import build_report
                report = build_report(report)
            await job.emit({"type": "phase", "message": "Generando reporte…"})
            files = await exporters.export_all_async(report, job.config)
            job.files = files
            job.output_dir = report.output_dir
            job.summary = list(report.summary)
            job.status = "completado"
            job.finished_at = datetime.now().isoformat(timespec="seconds")
            await job.emit({"type": "done", "output_dir": report.output_dir,
                            "files": job.public()["files"], "summary": job.summary})
        except asyncio.CancelledError:
            job.status = "cancelado"
            job.finished_at = datetime.now().isoformat(timespec="seconds")
            await job.emit({"type": "error", "message": "Escaneo cancelado por el usuario"})
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.now().isoformat(timespec="seconds")
            await job.emit({"type": "error", "message": job.error})

    def cancel(self, job: Job) -> bool:
        if job.task and not job.task.done():
            job.task.cancel()
            return True
        return False
