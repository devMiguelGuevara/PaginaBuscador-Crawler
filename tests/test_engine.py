"""Rastreo de punta a punta contra un sitio local (solo HTTP, sin navegador)."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from crawler.config import CrawlConfig
from crawler.engine import run_crawl

SITE = {
    "/": ("200", "text/html", """<html lang="es"><head><title>Inicio</title>
        <meta name="description" content="Tienda de prueba"></head><body>
        <header><nav><a href="/productos">Productos</a><a href="/login">Iniciar sesión</a>
        <a href="/panel">Mi cuenta</a><a href="/secreto/x">Secreto</a></nav></header>
        <main><h1>Bienvenido</h1><p>Texto de ejemplo con varias palabras para el contenido.</p>
        <a href="/no-existe">Roto</a></main></body></html>"""),
    "/productos": ("200", "text/html", """<html><head><title>Productos</title></head><body>
        <h1>Productos</h1><a href="/">Inicio</a><a href="/productos/1">Uno</a></body></html>"""),
    "/productos/1": ("200", "text/html", "<html><head><title>Producto 1</title></head><body><h1>P1</h1></body></html>"),
    "/login": ("200", "text/html", """<html><head><title>Login</title></head><body>
        <form method="post" action="/login"><input type="hidden" name="csrf_token" value="x">
        <input type="email" name="email"><input type="password" name="password">
        <button type="submit">Entrar</button></form><a href="/recuperar">¿Olvidaste tu contraseña?</a>
        </body></html>"""),
    "/panel": ("302", "/login?next=/panel", ""),
    "/robots.txt": ("200", "text/plain", "User-agent: *\nDisallow: /secreto/\n"),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        entry = SITE.get(self.path.split("?")[0])
        if entry is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><title>404</title></html>")
            return
        code, ctype, body = entry
        self.send_response(int(code))
        if code == "302":
            self.send_header("Location", ctype)
        else:
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Set-Cookie", "sessionid=abc; Path=/")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


async def test_crawl_local_site(site_url, tmp_path):
    cfg = CrawlConfig(start_url=site_url, render="never", screenshots=0, output_dir=str(tmp_path),
                      use_sitemap=False, concurrency=4)
    report = await run_crawl(cfg)
    urls = {p.url for p in report.pages}
    assert site_url in urls
    assert site_url + "productos/1" in urls
    assert not any("/secreto/" in u for u in urls), "robots.txt debe respetarse"
    assert any("robots.txt" in e for e in report.errors)
    assert any(b["url"].endswith("/no-existe") and b["status"] == 404 for b in report.broken_links)

    panel = next(p for p in report.pages if p.url.endswith("/panel"))
    assert panel.redirect_chain and "login" in panel.final_url

    login_forms = [f for f in report.forms if f.kind == "login"]
    assert login_forms and login_forms[0].has_csrf
    assert report.auth_summary.get("has_login")


async def test_max_pages_is_respected(site_url, tmp_path):
    cfg = CrawlConfig(start_url=site_url, render="never", screenshots=0, output_dir=str(tmp_path),
                      use_sitemap=False, max_pages=2, concurrency=8)
    report = await run_crawl(cfg)
    assert len(report.pages) == 2
