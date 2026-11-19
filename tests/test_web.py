import importlib
import json
import sys
import time
import types

import pytest
from fastapi.testclient import TestClient

import crawler
from crawler.models import PageResult, SiteReport
from crawler.web.app import create_app, normalize_target


@pytest.fixture
def fake_engine(monkeypatch, tmp_path):
    async def run_crawl(config, progress=None):
        pages = []
        for i, path in enumerate(["/", "/contacto"]):
            url = config.start_url.rstrip("/") + path
            pages.append(PageResult(url=url, status=200, depth=i, content_type="text/html",
                                    title=f"Página {i}", elapsed_ms=100))
            if progress:
                progress({"type": "page", "url": url, "status": 200, "done": i + 1, "queued": 1 - i,
                          "max_pages": config.max_pages, "rendered": False})
        return SiteReport(target=config.start_url, domain="example.com", started_at="2026-09-10T10:00:00",
                          pages=pages, output_dir=str(tmp_path / "scan"))

    try:
        engine = importlib.import_module("crawler.engine")
        monkeypatch.setattr(engine, "run_crawl", run_crawl)
    except ImportError:
        engine = types.ModuleType("crawler.engine")
        engine.run_crawl = run_crawl
        monkeypatch.setitem(sys.modules, "crawler.engine", engine)
        monkeypatch.setattr(crawler, "engine", engine, raising=False)
    return run_crawl


def test_normalize_target():
    assert normalize_target("example.com") == "https://example.com"
    assert normalize_target(" http://a.b/x ") == "http://a.b/x"
    for bad in ("", "ftp://x.com", "nohost"):
        with pytest.raises(ValueError):
            normalize_target(bad)


def test_index_page():
    with TestClient(create_app()) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "Analizar" in r.text and "robots.txt" in r.text
        assert client.get("/static/app.js").status_code == 200


def test_scan_flow(fake_engine, tmp_path):
    with TestClient(create_app(output_dir=str(tmp_path))) as client:
        r = client.post("/api/scans", json={"start_url": "example.com", "max_pages": 5, "render": "never"})
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["url"] == "https://example.com"
        for _ in range(100):
            state = client.get(f"/api/scans/{job['id']}").json()
            if state["status"] in ("completado", "error"):
                break
            time.sleep(0.05)
        assert state["status"] == "completado", state
        assert state["pages_done"] == 2

        events = []
        with client.stream("GET", f"/api/scans/{job['id']}/events") as resp:
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        types_seen = [e["type"] for e in events]
        assert types_seen[0] == "phase" and types_seen[-1] == "done" and "page" in types_seen

        html = client.get(f"/reports/{job['id']}")
        assert html.status_code == 200 and "Resumen ejecutivo" in html.text
        assert client.get(f"/reports/{job['id']}/json").json()["domain"] == "example.com"
        assert client.get(f"/reports/{job['id']}/pdf").status_code == 404
        assert any(j["id"] == job["id"] for j in client.get("/api/scans").json())


def test_scan_validation():
    with TestClient(create_app()) as client:
        assert client.post("/api/scans", json={"start_url": ""}).status_code == 422
        assert client.post("/api/scans", json={"start_url": "https://x.com", "max_pages": 0}).status_code == 422
        assert client.get("/api/scans/nope").status_code == 404
