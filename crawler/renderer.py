"""Renderizado con Playwright (Chromium headless): DOM final, red, cookies, storage, capturas y estilos."""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .fetcher import AUTH_COOKIE_RE
from .models import ApiCall, CookieInfo

API_TYPES = {"xhr", "fetch", "eventsource", "websocket"}
MEDIA_CT = re.compile(r"^(video|audio|image|font)/|mpegurl|mp2t|dash\+xml|octet-stream")
NAV_CT = re.compile(r"text/html|text/x-component")
LOGIN_TRIGGER = re.compile(
    r"^\s*(iniciar sesi[oó]n|inicia sesi[oó]n|log ?in|sign ?in|acceder|ingresar|entrar|acceso|mi cuenta)\s*$", re.I)

JS_PROBE = """(paths) => {
  const found = [];
  for (const p of paths) {
    try {
      let o = window;
      for (const k of p.split('.')) { if (o == null) { o = undefined; break; } o = o[k]; }
      if (o === undefined || o === null) continue;
      if (typeof o === 'string' || typeof o === 'number') { found.push(p + '=' + String(o).slice(0, 40)); continue; }
      found.push(p);
      try { if (typeof o.version === 'string') found.push(p + '.version=' + o.version.slice(0, 40)); } catch (e) {}
    } catch (e) {}
  }
  return found;
}"""

JS_PAGE_INFO = """() => {
  const cs = (el) => el ? getComputedStyle(el) : null;
  const q = (s) => document.querySelector(s);
  const body = document.body, h = q('h1') || q('h2'), a = q('main a, a[href]');
  const btn = q('button:not([disabled]), .btn, [class*="button"], input[type=submit]');
  const header = q('header, [role=banner], nav'), footer = q('footer, [role=contentinfo]');
  const g = (el, prop) => { const s = cs(el); return s ? s.getPropertyValue(prop) : ''; };
  const computed = {
    body_bg: g(body, 'background-color'), text: g(body, 'color'),
    link: g(a, 'color'), heading: g(h, 'color'),
    button_bg: g(btn, 'background-color'), button_text: g(btn, 'color'),
    header_bg: g(header, 'background-color'), footer_bg: g(footer, 'background-color'),
    nav_bg: g(q('nav'), 'background-color'),
    font_body: g(body, 'font-family'), font_heading: g(h, 'font-family'),
  };
  let css = '';
  for (const sheet of Array.from(document.styleSheets)) {
    try { for (const r of Array.from(sheet.cssRules)) { css += r.cssText + '\\n'; if (css.length > 400000) break; } }
    catch (e) {}
    if (css.length > 400000) break;
  }
  const res = performance.getEntriesByType('resource');
  const nav = performance.getEntriesByType('navigation')[0];
  let transfer = nav ? (nav.transferSize || 0) : 0;
  for (const r of res) transfer += r.transferSize || 0;
  const sk = (s) => { try { return Object.keys(s).slice(0, 50); } catch (e) { return []; } };
  return {
    computed, css,
    resource_count: res.length, transfer_bytes: transfer,
    load_ms: nav ? Math.round(nav.loadEventEnd || nav.domContentLoadedEventEnd || 0) : 0,
    storage: { local: sk(window.localStorage), session: sk(window.sessionStorage) },
    height: Math.max(document.body ? document.body.scrollHeight : 0, document.documentElement.scrollHeight),
  };
}"""


@dataclass
class RenderResult:
    url: str
    final_url: str = ""
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    html: str = ""
    api_calls: list[ApiCall] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    cookies: list[CookieInfo] = field(default_factory=list)
    storage_keys: dict[str, list[str]] = field(default_factory=dict)
    js_globals: list[str] = field(default_factory=list)
    computed: dict = field(default_factory=dict)
    css_text: str = ""
    resource_count: int = 0
    transfer_bytes: int = 0
    load_ms: float = 0
    elapsed_ms: float = 0
    screenshot_desktop: str | None = None
    screenshot_mobile: str | None = None
    login_probe_html: str = ""      # DOM tras pulsar el botón de login (modal/página de acceso)
    login_probe_url: str = ""
    login_probe_trigger: str = ""
    error: str | None = None


def _slug(url: str) -> str:
    p = urlsplit(url)
    s = (p.path.strip("/") + ("_" + p.fragment if p.fragment else "")) or "home"
    return re.sub(r"[^a-zA-Z0-9]+", "_", s)[:60].strip("_") or "home"


class Renderer:
    def __init__(self, user_agent: str, concurrency: int = 3, timeout: float = 30.0, site_host: str = ""):
        self.user_agent = user_agent
        self.timeout_ms = int(timeout * 1000)
        self.sem = asyncio.Semaphore(concurrency)
        self.site_host = site_host
        self._pw = None
        self._browser = None
        self._ctx = None
        self._mobile_ctx = None
        self._lock = asyncio.Lock()
        self.available = True
        self.start_error: str | None = None

    async def start(self) -> bool:
        async with self._lock:
            if self._browser or not self.available:
                return self.available
            try:
                from playwright.async_api import async_playwright
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(headless=True)
                self._ctx = await self._browser.new_context(
                    user_agent=self.user_agent, viewport={"width": 1366, "height": 900},
                    locale="es-ES", java_script_enabled=True)
            except Exception as e:  # Chromium no instalado, etc.
                self.available = False
                self.start_error = f"No se pudo iniciar Playwright: {e}"
                await self.close()
            return self.available

    async def close(self) -> None:
        for obj in (self._mobile_ctx, self._ctx, self._browser):
            if obj is not None:
                try:
                    await obj.close()
                except Exception:
                    pass
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._pw = self._browser = self._ctx = self._mobile_ctx = None

    async def render(self, url: str, js_probes: list[str] | None = None,
                     screenshot_dir: Path | None = None, probe_login: bool = False) -> RenderResult:
        res = RenderResult(url=url)
        if not await self.start():
            res.error = self.start_error
            return res
        async with self.sem:
            page = await self._ctx.new_page()
            calls: dict[str, ApiCall] = {}

            def on_request(req):
                if req.resource_type in API_TYPES and len(calls) < 300:
                    try:
                        h = req.headers
                    except Exception:
                        h = {}
                    # Navegación/prefetch interno de Next.js (React Server Components): no es una API
                    if h.get("rsc") or h.get("next-router-prefetch") or "_rsc=" in req.url:
                        return
                    body = ""
                    try:
                        body = req.post_data or ""
                    except Exception:
                        pass
                    gql = "graphql" in req.url.lower() or bool(re.search(r'"(query|operationName)"\s*:', body[:2000]))
                    host = (urlsplit(req.url).hostname or "").lower()
                    calls[f"{req.method} {req.url}"] = ApiCall(
                        url=req.url[:500], method=req.method, resource_type=req.resource_type,
                        graphql=gql, page_url=url,
                        third_party=bool(self.site_host) and not host.endswith(self.site_host))

            def on_response(resp):
                key = f"{resp.request.method} {resp.url}"
                if key in calls:
                    ct = (resp.headers.get("content-type") or "").lower()
                    # Medios (segmentos de video/HLS, imágenes, fuentes) y HTML/RSC de navegación no son APIs
                    if MEDIA_CT.search(ct) or (NAV_CT.search(ct) and not calls[key].third_party):
                        calls.pop(key, None)
                        return
                    calls[key].status = resp.status
                    calls[key].content_type = ct[:80]

            def on_ws(ws):
                host = (urlsplit(ws.url).hostname or "").lower()
                calls[f"WS {ws.url}"] = ApiCall(url=ws.url[:500], method="WS", resource_type="websocket",
                                                page_url=url,
                                                third_party=bool(self.site_host) and not host.endswith(self.site_host))

            page.on("request", on_request)
            page.on("response", on_response)
            page.on("websocket", on_ws)
            page.on("console", lambda m: m.type == "error" and len(res.console_errors) < 30
                    and res.console_errors.append(m.text[:300]))
            page.on("pageerror", lambda e: len(res.console_errors) < 30 and res.console_errors.append(str(e)[:300]))

            started = time.perf_counter()
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                try:
                    await page.wait_for_load_state("networkidle", timeout=min(10000, self.timeout_ms))
                except Exception:
                    pass
                await page.wait_for_timeout(600)
                if resp is not None:
                    res.status = resp.status
                    try:
                        res.headers = {k.lower(): v for k, v in (await resp.all_headers()).items()}
                    except Exception:
                        res.headers = {k.lower(): v for k, v in resp.headers.items()}
                res.final_url = page.url
                res.html = await page.content()
                info = await page.evaluate(JS_PAGE_INFO)
                res.computed = info.get("computed") or {}
                res.css_text = info.get("css") or ""
                res.resource_count = info.get("resource_count") or 0
                res.transfer_bytes = info.get("transfer_bytes") or 0
                res.load_ms = info.get("load_ms") or 0
                res.storage_keys = info.get("storage") or {}
                if js_probes:
                    res.js_globals = await page.evaluate(JS_PROBE, js_probes)
                for c in await self._ctx.cookies():
                    res.cookies.append(CookieInfo(
                        name=c["name"], domain=c.get("domain", ""), path=c.get("path", "/"),
                        secure=bool(c.get("secure")), http_only=bool(c.get("httpOnly")),
                        same_site=c.get("sameSite", "") or "", session=c.get("expires", -1) in (-1, None),
                        source="browser", auth_hint=bool(AUTH_COOKIE_RE.search(c["name"]))))
                if screenshot_dir is not None:
                    await self._screenshots(page, res, screenshot_dir, info.get("height") or 900)
                if probe_login:
                    await self._probe_login(page, res)
            except Exception as e:
                res.error = f"Render: {type(e).__name__}: {str(e).splitlines()[0][:200]}"
            finally:
                res.elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
                res.api_calls = list(calls.values())
                await page.close()
        return res

    async def _probe_login(self, page, res: RenderResult) -> None:
        """Pulsa el botón/enlace de acceso (sin enviar nada) y guarda el DOM resultante.

        Muchos sitios montan el formulario de login en un modal que solo existe tras el clic.
        """
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=LOGIN_TRIGGER)
            try:
                if await loc.count() == 0 or not await loc.first.is_visible():
                    continue
                label = re.sub(r"\s+", " ", await loc.first.inner_text()).strip()[:60]
                await loc.first.click(timeout=4000)
            except Exception:
                continue
            try:
                await page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                pass
            await page.wait_for_timeout(1200)
            res.login_probe_html = await page.content()
            res.login_probe_url = page.url
            res.login_probe_trigger = f"{'botón' if role == 'button' else 'enlace'} «{label}»"
            return

    async def _screenshots(self, page, res: RenderResult, out: Path, height: int) -> None:
        out.mkdir(parents=True, exist_ok=True)
        slug = _slug(res.final_url or res.url)
        desk = out / f"{slug}_desktop.jpg"
        h = min(max(int(height), 900), 4500)
        await page.screenshot(path=str(desk), type="jpeg", quality=60, full_page=True,
                              clip={"x": 0, "y": 0, "width": 1366, "height": h})
        res.screenshot_desktop = f"{out.name}/{desk.name}"
        try:
            if self._mobile_ctx is None:
                self._mobile_ctx = await self._browser.new_context(
                    user_agent=self.user_agent.replace("Windows NT 10.0; Win64; x64", "iPhone; CPU iPhone OS 17_0 like Mac OS X")
                    + " Mobile",
                    viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                    device_scale_factor=2, locale="es-ES")
            mp = await self._mobile_ctx.new_page()
            try:
                await mp.goto(res.final_url or res.url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                try:
                    await mp.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
                mob = out / f"{slug}_mobile.jpg"
                await mp.screenshot(path=str(mob), type="jpeg", quality=55)
                res.screenshot_mobile = f"{out.name}/{mob.name}"
            finally:
                await mp.close()
        except Exception:
            pass

    async def pdf(self, html_path: Path, pdf_path: Path) -> None:
        if not await self.start():
            raise RuntimeError(self.start_error or "Playwright no disponible")
        page = await self._browser.new_page()
        try:
            await page.goto(html_path.resolve().as_uri(), wait_until="load")
            await page.emulate_media(media="print")
            await page.pdf(path=str(pdf_path), format="A4", print_background=True,
                           margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
        finally:
            await page.close()
