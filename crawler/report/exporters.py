"""Exporta el SiteReport a JSON, HTML autocontenido y PDF."""
from __future__ import annotations

import base64
import json
import mimetypes
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import CrawlConfig
from ..labels import form_kind
from ..models import SiteReport

TEMPLATES = Path(__file__).parent / "templates"
MAX_IMAGE_BYTES = 2_500_000      # por captura
MAX_IMAGES_TOTAL = 30_000_000    # suma embebida en el HTML

CATEGORY_ORDER = [
    "CMS", "E-commerce", "Framework web", "Framework JavaScript", "Librería JavaScript", "Framework CSS",
    "Servidor web", "Lenguaje", "Hosting", "CDN", "PaaS", "Autenticación", "Pagos", "Analítica",
    "Marketing", "Chat", "Tag manager", "Seguridad", "Fuentes", "Mapas", "Video",
]


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "j2", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["bytes"] = _fmt_bytes
    env.filters["ms"] = lambda v: f"{float(v or 0):,.0f} ms"
    env.filters["short_url"] = _short_url
    env.filters["score_class"] = lambda v: "good" if (v or 0) >= 80 else ("mid" if (v or 0) >= 50 else "bad")
    env.filters["status_class"] = _status_class
    env.filters["tojson_safe"] = lambda v: json.dumps(v, ensure_ascii=False).replace("</", "<\\/")
    env.filters["form_kind"] = form_kind
    return env


def _fmt_bytes(n: Any) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _short_url(url: str, limit: int = 70) -> str:
    p = urlparse(url or "")
    s = (p.path or "/") + (f"?{p.query}" if p.query else "")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _status_class(status: Any) -> str:
    if not status:
        return "st-err"
    s = int(status)
    return "st-ok" if s < 300 else ("st-redir" if s < 400 else "st-err")


def _data_uri(base: Path, rel: str | None, budget: list[int]) -> str | None:
    if not rel:
        return None
    path = (base / rel) if not Path(rel).is_absolute() else Path(rel)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > MAX_IMAGE_BYTES or budget[0] + len(data) > MAX_IMAGES_TOTAL:
        return None
    budget[0] += len(data)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _url_tree(report: SiteReport) -> dict[str, Any]:
    """Árbol anidado {segmento: {"_page": {...}, "_children": {...}}} a partir de las rutas."""
    root: dict[str, Any] = {"_page": None, "_children": OrderedDict()}
    for p in sorted(report.pages, key=lambda x: urlparse(x.url).path):
        u = urlparse(p.url)
        segs = [s for s in u.path.split("/") if s]
        if u.query:
            segs = segs + [f"?{u.query}"]
        node = root
        for seg in segs:
            node = node["_children"].setdefault(seg, {"_page": None, "_children": OrderedDict()})
        node["_page"] = {"url": p.url, "status": p.status, "title": p.title, "type": p.page_type}
    return root


def _screens(report: SiteReport) -> list[dict[str, Any]]:
    base = Path(report.output_dir or ".")
    budget = [0]
    out = []
    for p in report.pages:
        if not (p.screenshot_desktop or p.screenshot_mobile):
            continue
        out.append({
            "url": p.url, "title": p.title, "area": p.area,
            "desktop": _data_uri(base, p.screenshot_desktop, budget),
            "mobile": _data_uri(base, p.screenshot_mobile, budget),
        })
    return out


def _tech_groups(report: SiteReport) -> list[tuple[str, list]]:
    groups: dict[str, list] = {}
    for t in report.technologies:
        groups.setdefault(t.category or "Otros", []).append(t)
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(groups.items(), key=lambda kv: (order.get(kv[0], 99), kv[0]))


def _context(report: SiteReport) -> dict[str, Any]:
    pages = report.pages
    status_counts: dict[str, int] = {}
    for p in pages:
        key = str(p.status) if p.status else "error"
        status_counts[key] = status_counts.get(key, 0) + 1
    security_headers = (report.security or {}).get("headers") or {}
    inventory = [
        {
            "url": p.url, "path": _short_url(p.url, 90), "status": p.status or 0, "type": p.page_type,
            "area": p.area, "title": p.title, "ms": round(p.elapsed_ms or 0), "bytes": p.size_bytes or 0,
            "rendered": p.rendered, "depth": p.depth, "forms": len(p.forms), "words": p.word_count,
            "error": p.error or "",
        }
        for p in pages
    ]
    return {
        "r": report,
        "home": next((p for p in pages if p.depth == 0), pages[0] if pages else None),
        "tree": _url_tree(report),
        "screens": _screens(report),
        "tech_groups": _tech_groups(report),
        "status_counts": dict(sorted(status_counts.items())),
        "security_headers": security_headers,
        "inventory": inventory,
        "auth_by_kind": _group_auth(report),
        "console_errors": [(p.url, e) for p in pages for e in p.console_errors][:80],
        "rendered_count": sum(1 for p in pages if p.rendered),
        "total_forms": sum(len(p.forms) for p in pages),
    }


def _group_auth(report: SiteReport) -> dict[str, list]:
    out: dict[str, list] = {}
    for f in report.auth:
        out.setdefault(f.kind, []).append(f)
    return out


def render_html(report: SiteReport) -> str:
    return _env().get_template("report.html.j2").render(**_context(report))


def export_json(report: SiteReport, path: Path) -> Path:
    path.write_text(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def export_html(report: SiteReport, path: Path) -> Path:
    path.write_text(render_html(report), encoding="utf-8")
    return path


def export_all(report: SiteReport, config: CrawlConfig | None = None) -> dict[str, str]:
    """Escribe report.json y report.html en report.output_dir (síncrono)."""
    out = Path(report.output_dir or (config.output_dir if config else "output"))
    out.mkdir(parents=True, exist_ok=True)
    report.output_dir = str(out)
    files: dict[str, str] = {}
    files["json"] = str(export_json(report, out / "report.json"))
    files["html"] = str(export_html(report, out / "report.html"))
    return files


async def export_pdf(html_path: str | Path, pdf_path: str | Path) -> Path:
    """Genera un PDF desde el HTML con Chromium headless (Playwright)."""
    from playwright.async_api import async_playwright

    html_path, pdf_path = Path(html_path).resolve(), Path(pdf_path)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.goto(html_path.as_uri(), wait_until="load")
            # Las capturas usan loading=lazy: fuerza su carga antes de imprimir y abre los <details>
            await page.evaluate("""async () => {
                document.querySelectorAll('img[loading=lazy]').forEach(i => { i.loading = 'eager'; });
                document.querySelectorAll('details').forEach(d => { d.open = true; });
                await Promise.all([...document.images].filter(i => !i.complete)
                    .map(i => new Promise(r => { i.onload = i.onerror = r; })));
            }""")
            await page.emulate_media(media="print")
            await page.pdf(path=str(pdf_path), format="A4", print_background=True,
                           margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
        finally:
            await browser.close()
    return pdf_path


async def export_all_async(report: SiteReport, config: CrawlConfig | None = None) -> dict[str, str]:
    """JSON + HTML y, si `config.pdf`, también PDF. Nunca lanza por el PDF."""
    files = export_all(report, config)
    if config is not None and config.pdf:
        try:
            files["pdf"] = str(await export_pdf(files["html"], Path(report.output_dir) / "report.pdf"))
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"No se pudo generar el PDF: {exc!r}")
            export_json(report, Path(files["json"]))
    return files
