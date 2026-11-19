"""CLI: `python -m crawler scan <url>` y `python -m crawler serve`."""
from __future__ import annotations

import asyncio
import sys
import webbrowser
from typing import Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from .config import CrawlConfig

app = typer.Typer(add_completion=False, help="Crawler y analizador de sitios web.")
console = Console()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


@app.command()
def scan(
    url: str = typer.Argument(..., help="URL del sitio a analizar"),
    max_pages: int = typer.Option(100, "--max-pages", "-n", help="Máximo de páginas"),
    depth: int = typer.Option(5, "--depth", "-d", help="Profundidad máxima"),
    concurrency: int = typer.Option(8, "--concurrency", "-c", help="Peticiones simultáneas"),
    render: str = typer.Option("auto", "--render", "-r", help="auto | always | never"),
    delay: float = typer.Option(0.0, "--delay", help="Segundos entre peticiones por worker"),
    screenshots: int = typer.Option(6, "--screenshots", help="Nº de páginas con captura"),
    pdf: bool = typer.Option(False, "--pdf", help="Generar también PDF"),
    ignore_robots: bool = typer.Option(False, "--ignore-robots", help="No respetar robots.txt (solo sitios propios)"),
    subdomains: bool = typer.Option(False, "--subdomains", help="Incluir subdominios"),
    no_sitemap: bool = typer.Option(False, "--no-sitemap", help="No usar sitemap.xml"),
    output: str = typer.Option("output", "--output", "-o", help="Carpeta de salida"),
    open_report: bool = typer.Option(False, "--open", help="Abrir el reporte HTML al terminar"),
) -> None:
    """Rastrea un sitio y genera el reporte."""
    from .engine import scan as run_scan

    if render not in ("auto", "always", "never"):
        raise typer.BadParameter("--render debe ser auto, always o never")
    config = CrawlConfig(
        start_url=url, max_pages=max_pages, max_depth=depth, concurrency=concurrency, render=render,
        delay=delay, screenshots=screenshots, pdf=pdf, respect_robots=not ignore_robots,
        include_subdomains=subdomains, use_sitemap=not no_sitemap, output_dir=output)

    with Progress(TextColumn("[bold cyan]{task.description}"), BarColumn(), MofNCompleteColumn(),
                  TimeElapsedColumn(), TextColumn("{task.fields[url]}", style="dim"),
                  console=console, transient=False) as prog:
        task = prog.add_task("Rastreando", total=max_pages, url="")

        def on_event(ev: dict) -> None:
            t = ev.get("type")
            if t == "phase":
                prog.console.print(f"[yellow]•[/] {ev['message']}")
            elif t == "page":
                status = ev.get("status")
                color = "green" if status and status < 400 else "red"
                mark = " [magenta]JS[/]" if ev.get("rendered") else ""
                prog.update(task, completed=ev["done"], url=ev["url"][-70:])
                prog.console.print(f"  [{color}]{status or 'ERR'}[/]{mark} {ev['url']}", highlight=False)

        report, files = asyncio.run(run_scan(config, on_event))
        prog.update(task, completed=len(report.pages), total=max(len(report.pages), 1))

    _print_summary(report, files)
    if open_report and files.get("html"):
        webbrowser.open(files["html"])


def _print_summary(report, files: dict[str, str]) -> None:
    console.rule(f"[bold]Resultado: {report.domain}")
    t = Table(show_header=False, box=None)
    t.add_row("Páginas", str(len(report.pages)))
    t.add_row("Duración", f"{report.duration_s} s")
    t.add_row("Tipo de sitio", report.site_type or "-")
    t.add_row("Tecnologías", ", ".join(x.name for x in report.technologies[:12]) or "-")
    t.add_row("Login", "Sí" if report.auth_summary.get("has_login") else "No detectado")
    t.add_row("Formularios", str(len(report.forms)))
    t.add_row("Endpoints API", str(len(report.api_endpoints)))
    for s in report.scores:
        t.add_row(f"Puntuación {s.name}", f"{s.value}/100")
    console.print(t)
    for line in report.summary:
        console.print(f"  • {line}")
    if report.errors:
        console.print(f"[yellow]{len(report.errors)} aviso(s) durante el rastreo (ver reporte).[/]")
    for fmt, path in files.items():
        console.print(f"[green]{fmt.upper()}[/]: {path}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host"),
    port: int = typer.Option(8000, help="Puerto"),
    no_open: bool = typer.Option(False, "--no-open", help="No abrir el navegador"),
) -> None:
    """Inicia la interfaz web local."""
    import uvicorn

    if not no_open:
        webbrowser.open(f"http://{host}:{port}")
    uvicorn.run("crawler.web.app:app", host=host, port=port, log_level="info")


def main(argv: Optional[list[str]] = None) -> None:
    app()


if __name__ == "__main__":
    main()
