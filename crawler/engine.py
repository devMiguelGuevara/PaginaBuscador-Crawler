"""Orquestador del rastreo: siembra, cola BFS asíncrona, render híbrido y análisis por página."""
from __future__ import annotations

import asyncio
import inspect
import re
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import robotparser
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser

from .analyzers import page as page_an
from .config import CrawlConfig
from .fetcher import Fetcher, FetchResult
from .models import CookieInfo, FieldInfo, FormInfo, PageResult, SiteReport
from .renderer import Renderer, RenderResult
from .urls import Scope, normalize

Progress = Callable[[dict[str, Any]], Any]

MAX_SITEMAP_URLS = 2000
AUTO_RENDER_AUTH_PAGES = 5
AUTO_RENDER_JS_PAGES = 15
MAX_LOGIN_PROBES = 3
LOGIN_FORM_KINDS = {"login", "register", "password_reset"}
AUTH_URL_RE = re.compile(r"log-?in|sign-?in|sign-?up|register|registro|/auth(?:$|[/?#_-]|entica|oriz)|account|"
                         r"cuenta|iniciar|acceso|"
                         r"password|contrasena|forgot|reset", re.I)
JS_FRAMEWORKS = {"react", "next.js", "vue.js", "nuxt.js", "angular", "svelte", "sveltekit", "remix", "gatsby",
                 "astro", "ember.js", "preact", "solidjs", "qwik"}
DESIGN_PAGES = 12          # páginas sin render a las que también se les analiza el diseño
STYLESHEETS_PER_PAGE = 3


def _optional(module: str):
    try:
        return __import__(f"crawler.analyzers.{module}", fromlist=[module])
    except Exception:
        return None


forms_an = _optional("forms")
tech_an = _optional("tech")
auth_an = _optional("auth")
inter_an = _optional("interactions")
design_an = _optional("design")
areas_an = _optional("areas")


def normalize_start_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return normalize(url) or url


def _loose_email_inputs(tree: LexborHTMLParser) -> list:
    """Inputs de email fuera de cualquier <form>."""
    out = []
    for node in tree.css('input[type="email"], input[autocomplete="email"]'):
        p = node.parent
        while p is not None and p.tag != "form":
            p = p.parent
        if p is None:
            out.append(node)
    return out


def _fallback_area(url: str) -> str:
    seg = [s for s in urlsplit(url).path.split("/") if s]
    return "/" + seg[0] if seg else "/"


class Crawler:
    def __init__(self, config: CrawlConfig, progress: Progress | None = None):
        self.config = config.model_copy(update={"start_url": normalize_start_url(config.start_url)})
        self.progress = progress
        self.scope = Scope(self.config.start_url, self.config.include_subdomains)
        self.upgrade_https = self.config.start_url.startswith("https://")
        self.queue: asyncio.Queue[tuple[str, int, str]] = asyncio.Queue()
        self.seen: set[str] = set()
        self.pages: list[PageResult] = []
        self.processed = 0
        self.reserved = 0          # páginas asignadas a un worker (evita pasarse de max_pages)
        self.errors: list[str] = []
        self.robots: robotparser.RobotFileParser | None = None
        self.robots_blocked: list[str] = []
        self.delay = self.config.delay
        self.site_is_spa = False
        self.js_heavy = False
        self.auth_renders = 0
        self.js_renders = 0
        self.login_probe_attempts = 0
        self.login_probe_done = False
        self.screenshot_areas: set[str] = set()
        self.screenshots_taken = 0
        self.design_count = 0
        self.css_cache: dict[str, str] = {}
        self.started = time.perf_counter()
        domain = self.scope.host or "sitio"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = Path(self.config.output_dir) / f"{re.sub(r'[^a-zA-Z0-9.-]', '_', domain)}_{stamp}"
        self.report = SiteReport(
            target=self.config.start_url, domain=domain, started_at=datetime.now().isoformat(timespec="seconds"),
            config=self.config.model_dump(), output_dir=str(self.output_dir))
        self.fetcher: Fetcher | None = None
        self.renderer: Renderer | None = None
        self.js_probes: list[str] = []
        if tech_an is not None and hasattr(tech_an, "js_probe_names"):
            try:
                self.js_probes = list(tech_an.js_probe_names())
            except Exception:
                self.js_probes = []

    # ---------------------------------------------------------------- utilidades
    async def emit(self, event: dict[str, Any]) -> None:
        if self.progress is None:
            return
        try:
            r = self.progress(event)
            if inspect.isawaitable(r):
                await r
        except Exception:
            pass

    def _err(self, msg: str) -> None:
        if len(self.errors) < 200:
            self.errors.append(msg)

    def enqueue(self, url: str, depth: int, parent: str) -> None:
        # Enlaces http:// internos en un sitio https: misma página, se rastrea una sola vez
        if self.upgrade_https and url.startswith("http://") and self.scope.is_internal(url):
            url = "https://" + url[7:]
        if url in self.seen or depth > self.config.max_depth:
            return
        if len(self.seen) >= self.config.max_pages * 3:
            return
        self.seen.add(url)
        self.queue.put_nowait((url, depth, parent))

    # ---------------------------------------------------------------- siembra
    async def load_robots_and_sitemaps(self) -> list[str]:
        p = urlsplit(self.config.start_url)
        origin = f"{p.scheme}://{p.netloc}"
        status, text = await self.fetcher.fetch_text(f"{origin}/robots.txt")
        sitemaps: list[str] = []
        if status == 200 and text and "<html" not in text[:500].lower():
            self.report.robots_txt = text[:20000]
            rp = robotparser.RobotFileParser()
            rp.parse(text.splitlines())
            self.robots = rp
            cd = rp.crawl_delay("*")
            if cd:
                self.delay = max(self.delay, min(float(cd), 5.0))
            sitemaps = list(rp.site_maps() or [])
        if not self.config.use_sitemap:
            self.report.sitemaps = sitemaps
            return []
        if not sitemaps:
            sitemaps = [f"{origin}/sitemap.xml"]
        urls: list[str] = []
        pending, visited = list(sitemaps), set()
        while pending and len(visited) < 8 and len(urls) < MAX_SITEMAP_URLS:
            sm = pending.pop(0)
            if sm in visited:
                continue
            visited.add(sm)
            st, xml = await self.fetcher.fetch_text(sm)
            if st != 200 or not xml or "<html" in xml[:300].lower():
                continue
            self.report.sitemaps.append(sm)
            locs = re.findall(r"<loc>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</loc>", xml, re.I | re.S)
            if "<sitemapindex" in xml[:1000].lower():
                pending.extend(locs[:20])
            else:
                urls.extend(locs[: MAX_SITEMAP_URLS - len(urls)])
        self.report.sitemap_urls = len(urls)
        return urls

    def allowed(self, url: str) -> bool:
        if not self.config.respect_robots or self.robots is None:
            return True
        try:
            return self.robots.can_fetch(self.config.user_agent, url)
        except Exception:
            return True

    # ---------------------------------------------------------------- render
    def _want_screenshot(self, url: str) -> bool:
        if self.config.render == "never" or self.screenshots_taken >= self.config.screenshots:
            return False
        area = areas_an.area_of(url) if areas_an is not None else _fallback_area(url)
        if area in self.screenshot_areas:
            return False
        self.screenshot_areas.add(area)
        self.screenshots_taken += 1
        return True

    def _want_render(self, page: PageResult, fetch_failed: bool) -> bool:
        mode = self.config.render
        if mode == "never":
            return False
        if mode == "always" or fetch_failed or page.spa_suspected or self.site_is_spa:
            return True
        # Páginas de acceso: el formulario/modal de login suele montarse con JavaScript
        if AUTH_URL_RE.search(page.final_url or page.url) and self.auth_renders < AUTO_RENDER_AUTH_PAGES:
            self.auth_renders += 1
            return True
        # Sitios hechos con frameworks JS: renderiza una muestra para capturar APIs, cookies y storage
        if self.js_heavy and self.js_renders < AUTO_RENDER_JS_PAGES:
            self.js_renders += 1
            return True
        return False

    async def _render(self, url: str, screenshot: bool, probe_login: bool = False) -> RenderResult | None:
        if self.renderer is None:
            self.renderer = Renderer(self.config.user_agent, self.config.render_concurrency,
                                     timeout=max(self.config.timeout, 30.0), site_host=self.scope.root)
        rr = await self.renderer.render(url, self.js_probes,
                                        self.output_dir / "screenshots" if screenshot else None,
                                        probe_login=probe_login)
        if rr.error and not rr.html:
            self._err(f"{url}: {rr.error}")
            if not self.renderer.available:
                return None
        return rr

    # ---------------------------------------------------------------- página
    def _page_from_fetch(self, url: str, depth: int, parent: str, fr: FetchResult) -> PageResult:
        return PageResult(
            url=url, final_url=fr.final_url or url, status=fr.status, depth=depth, parent=parent,
            redirect_chain=fr.redirect_chain, content_type=fr.content_type, size_bytes=len(fr.body),
            elapsed_ms=fr.elapsed_ms, http_version=fr.http_version, error=fr.error,
            headers=fr.headers, cookies=list(fr.cookies), html=fr.text if fr.is_html else "")

    async def _collect_css(self, page: PageResult, tree: LexborHTMLParser) -> str:
        parts = [s.text() or "" for s in tree.css("style")]
        for href in page.stylesheets[:STYLESHEETS_PER_PAGE]:
            if href not in self.css_cache:
                try:
                    r = await self.fetcher.fetch(href)
                    self.css_cache[href] = r.text[:300_000] if r.status == 200 else ""
                except Exception:
                    self.css_cache[href] = ""
            parts.append(self.css_cache[href])
        return "\n".join(parts)[:600_000]

    async def process(self, url: str, depth: int, parent: str) -> None:
        if not self.allowed(url):
            self.robots_blocked.append(url)
            return
        fr = await self.fetcher.fetch(url)
        page = self._page_from_fetch(url, depth, parent, fr)
        final = normalize(page.final_url) or page.final_url
        if final != url and self.scope.is_internal(final):
            self.seen.add(final)

        tree = LexborHTMLParser(page.html) if page.html else None
        links: list[str] = []
        if tree is not None:
            try:
                links = page_an.parse_page(page, tree, self.scope)
            except Exception as e:
                self._err(f"{url}: error al analizar HTML: {e}")

        fetch_failed = fr.error is not None or (fr.status in (401, 403, 429, 503) and not page.html)
        blocked_bot = fr.status in (403, 429, 503) and bool(re.search(
            r"cloudflare|captcha|challenge|access denied|just a moment", page.html[:5000], re.I))
        screenshot = self._want_screenshot(url) if (tree is not None or fetch_failed) else False
        rr: RenderResult | None = None
        if screenshot or self._want_render(page, fetch_failed or blocked_bot):
            probe = not self.login_probe_done and self.login_probe_attempts < MAX_LOGIN_PROBES
            if probe:
                self.login_probe_attempts += 1
            rr = await self._render(url, screenshot, probe)

        if rr is not None and rr.html:
            spa = page.spa_suspected
            if self.processed == 0 and spa:
                self.site_is_spa = True
            page = self._merge_render(page, rr)
            tree = LexborHTMLParser(page.html)
            try:
                links = page_an.parse_page(page, tree, self.scope)
            except Exception as e:
                self._err(f"{url}: error al analizar DOM renderizado: {e}")
            page.spa_suspected = spa or page.spa_suspected
        elif self.processed == 0 and page.spa_suspected:
            self.site_is_spa = True

        await self.analyze(page, tree, rr)
        if rr is not None and rr.login_probe_html:
            self._apply_login_probe(page, rr)
        if not self.js_heavy and any(t.name.lower() in JS_FRAMEWORKS for t in page.technologies):
            self.js_heavy = True
        self.pages.append(page)
        self.processed += 1
        for link in links:
            self.enqueue(link, depth + 1, url)
        await self.emit({"type": "page", "url": url, "status": page.status, "done": self.processed,
                         "queued": self.queue.qsize(), "max_pages": self.config.max_pages,
                         "rendered": page.rendered, "title": page.title[:120]})

    def _apply_login_probe(self, page: PageResult, rr: RenderResult) -> None:
        """Añade a la página los formularios/hallazgos de acceso que aparecen tras pulsar «Iniciar sesión»."""
        self.login_probe_done = True
        if forms_an is None:
            return
        purl = rr.login_probe_url or page.final_url or page.url
        ptree = LexborHTMLParser(rr.login_probe_html)
        probe = PageResult(url=purl, final_url=purl, status=200, rendered=True,
                           html=rr.login_probe_html, api_calls=rr.api_calls)
        try:
            page_an.parse_page(probe, ptree, self.scope)
            forms = forms_an.extract_forms(ptree, purl)
        except Exception as e:
            self._err(f"{page.url}: sonda de login: {type(e).__name__}: {e}")
            return

        def key(f):
            return f.kind, tuple((x.name, x.type) for x in f.fields)

        known = {key(f) for f in page.forms}
        new_forms = []
        for f in forms:
            if key(f) in known:
                continue
            if f.kind in LOGIN_FORM_KINDS or any(x.type in ("password", "email") for x in f.fields):
                f.form_id = (f.form_id + " " if f.form_id else "") + f"(aparece al pulsar {rr.login_probe_trigger})"
                new_forms.append(f)
        if not any(f.kind in LOGIN_FORM_KINDS for f in new_forms):
            # Modales sin <form>: un campo de email que aparece tras el clic = acceso por email
            # (enlace mágico / código de un solo uso)
            before = len(_loose_email_inputs(LexborHTMLParser(page.html))) if page.html else 0
            after = _loose_email_inputs(ptree)
            if len(after) > before:
                inp = after[-1]
                new_forms.append(FormInfo(
                    page_url=purl, kind="login", method="",
                    form_id=f"(sin <form>; aparece al pulsar {rr.login_probe_trigger})",
                    fields=[FieldInfo(name=inp.attributes.get("name") or "", type="email",
                                      placeholder=inp.attributes.get("placeholder") or "",
                                      autocomplete=inp.attributes.get("autocomplete") or "")],
                    submit_text="Acceso con email (enlace mágico o código)"))
        page.forms.extend(new_forms)
        probe.forms = new_forms
        if auth_an is None:
            return
        try:
            found = auth_an.analyze_page(probe, ptree)
        except Exception:
            found = []
        have = {(a.kind, a.detail) for a in page.auth}
        for a in found:
            if (a.kind, a.detail) in have or a.kind in ("login_entry", "register_entry"):
                continue
            a.evidence = (a.evidence + " · " if a.evidence else "") + f"tras pulsar {rr.login_probe_trigger}"
            page.auth.append(a)

    def _merge_render(self, page: PageResult, rr: RenderResult) -> PageResult:
        headers = {**rr.headers, **page.headers} if page.headers else rr.headers
        cookies: dict[str, CookieInfo] = {c.name: c for c in rr.cookies}
        cookies.update({c.name: c for c in page.cookies})  # los de cabecera tienen flags más fiables
        # Si el servidor redirigió, su destino es la señal fiable (el JS puede reescribir la URL después).
        # Si no, un cambio de URL en el navegador es una redirección del lado del cliente (típico de SPAs).
        chain = list(page.redirect_chain)
        final = page.final_url or rr.final_url
        browser_final = normalize(rr.final_url) if rr.final_url else None
        before = (normalize(page.final_url or page.url) or "").rstrip("/")
        if not chain and browser_final and browser_final.rstrip("/") != before:
            chain.append(f"JS {page.final_url or page.url}")
            final = rr.final_url
        return PageResult(
            url=page.url, final_url=final, status=page.status or rr.status,
            depth=page.depth, parent=page.parent, redirect_chain=chain,
            content_type=page.content_type or "text/html", size_bytes=page.size_bytes or len(rr.html.encode()),
            elapsed_ms=page.elapsed_ms or rr.elapsed_ms, http_version=page.http_version, rendered=True,
            error=page.error if page.status is None and not rr.html else None,
            headers=headers, cookies=list(cookies.values()), api_calls=rr.api_calls,
            console_errors=rr.console_errors, js_globals=rr.js_globals, storage_keys=rr.storage_keys,
            resource_count=rr.resource_count, transfer_bytes=rr.transfer_bytes, load_ms=rr.load_ms,
            screenshot_desktop=rr.screenshot_desktop, screenshot_mobile=rr.screenshot_mobile,
            html=rr.html, css_text=rr.css_text)

    async def analyze(self, page: PageResult, tree: LexborHTMLParser | None, rr: RenderResult | None) -> None:
        def run(name: str, fn):
            try:
                return fn()
            except Exception as e:
                self._err(f"{page.url}: analizador {name}: {type(e).__name__}: {e}")
                return None

        if tree is not None and forms_an is not None:
            page.forms = run("forms", lambda: forms_an.extract_forms(tree, page.final_url or page.url)) or []
        if tech_an is not None:
            page.technologies = run("tech", lambda: tech_an.detect(page, tree)) or []
        if auth_an is not None:
            page.auth = run("auth", lambda: auth_an.analyze_page(page, tree)) or []
        if inter_an is not None:
            page.interactions = run("interactions", lambda: inter_an.page_interactions(page, tree)) or {}
        if design_an is not None and tree is not None and (page.rendered or self.design_count < DESIGN_PAGES):
            if not page.css_text:
                page.css_text = await self._collect_css(page, tree)
            self.design_count += 1
            computed = rr.computed if rr is not None else None
            page.design = run("design", lambda: design_an.page_design(page, tree, computed))
        if areas_an is not None:
            page.page_type = run("areas", lambda: areas_an.classify_page(page)) or "other"
            page.area = run("areas", lambda: areas_an.area_of(page.url)) or "/"
        else:
            page.area = _fallback_area(page.url)
        page.css_text = ""  # libera memoria; el HTML se conserva para el builder

    # ---------------------------------------------------------------- bucle
    async def worker(self) -> None:
        while True:
            url, depth, parent = await self.queue.get()
            try:
                if self.reserved < self.config.max_pages:
                    self.reserved += 1
                    await self.process(url, depth, parent)
                    if self.delay:
                        await asyncio.sleep(self.delay)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._err(f"{url}: {type(e).__name__}: {e}")
            finally:
                self.queue.task_done()

    async def server_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {}
        home = next((p for p in self.pages if p.status), None)
        if home:
            h = home.headers
            info.update({k: h[k] for k in ("server", "x-powered-by", "via", "x-generator", "x-cache", "cf-ray")
                         if k in h})
            info["http_version"] = home.http_version
            info["final_url"] = home.final_url
            info["https"] = home.final_url.startswith("https://")
        try:
            loop = asyncio.get_running_loop()
            addrs = await asyncio.wait_for(loop.getaddrinfo(self.scope.host, 443, type=socket.SOCK_STREAM), 5)
            info["ips"] = sorted({a[4][0] for a in addrs})
        except Exception:
            pass
        return info

    async def run(self) -> SiteReport:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.fetcher = Fetcher(self.config.user_agent, self.config.timeout, self.config.max_body_bytes,
                               max_connections=self.config.concurrency * 2)
        workers: list[asyncio.Task] = []
        try:
            await self.emit({"type": "phase", "message": f"Iniciando rastreo de {self.config.start_url}"})
            # Página inicial primero (resuelve redirecciones y detecta SPA antes de paralelizar)
            self.seen.add(self.config.start_url)
            self.reserved += 1
            await self.process(self.config.start_url, 0, "")
            if self.pages and self.pages[0].final_url:
                final = self.pages[0].final_url
                if final.startswith("https://"):
                    self.upgrade_https = True
                if not self.scope.is_internal(final) and self.scope.is_same_site(final):
                    self.scope = Scope(final, self.config.include_subdomains)
            await self.emit({"type": "phase", "message": "Leyendo robots.txt y sitemaps"})
            for u in await self.load_robots_and_sitemaps():
                nu = normalize(u)
                if nu and self.scope.should_crawl(nu):
                    self.enqueue(nu, 1, "sitemap")
            if self.site_is_spa:
                await self.emit({"type": "phase", "message": "Sitio SPA detectado: se renderizará con Chromium"})
            await self.emit({"type": "phase", "message": "Rastreando páginas"})
            workers = [asyncio.create_task(self.worker()) for _ in range(self.config.concurrency)]
            await self.queue.join()
        finally:
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await self.fetcher.close()

        await self.emit({"type": "phase", "message": "Analizando resultados"})
        self.report.pages = self.pages
        self.report.server_info = await self.server_info()
        self.report.broken_links = [
            {"url": p.url, "status": p.status, "from": p.parent} for p in self.pages
            if p.status is not None and p.status >= 400 and p.parent]
        if self.robots_blocked:
            self._err(f"{len(self.robots_blocked)} URL(s) omitidas por robots.txt "
                      f"(ej. {', '.join(self.robots_blocked[:3])})")
        if self.renderer is not None and not self.renderer.available:
            self._err(self.renderer.start_error or "Playwright no disponible")
        self.report.errors = self.errors
        self.report.finished_at = datetime.now().isoformat(timespec="seconds")
        self.report.duration_s = round(time.perf_counter() - self.started, 1)
        try:
            from .report.builder import build_report
            self.report = build_report(self.report)
        except Exception as e:
            self.report.errors.append(f"Error construyendo el reporte: {type(e).__name__}: {e}")
        return self.report

    async def close(self) -> None:
        if self.renderer is not None:
            await self.renderer.close()


async def run_crawl(config: CrawlConfig, progress: Progress | None = None) -> SiteReport:
    crawler = Crawler(config, progress)
    try:
        return await crawler.run()
    finally:
        await crawler.close()


async def scan(config: CrawlConfig, progress: Progress | None = None) -> tuple[SiteReport, dict[str, str]]:
    """Rastrea y exporta (JSON/HTML/PDF). Emite el evento `done`."""
    report = await run_crawl(config, progress)
    files: dict[str, str] = {}
    try:
        from .report.exporters import export_all_async
        files = await export_all_async(report, config)
    except Exception as e:
        report.errors.append(f"Error exportando: {type(e).__name__}: {e}")
    if progress is not None:
        r = progress({"type": "done", "output_dir": report.output_dir, "files": files})
        if inspect.isawaitable(r):
            await r
    return report, files
