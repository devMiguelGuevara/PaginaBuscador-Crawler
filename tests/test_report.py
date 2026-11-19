import json
from pathlib import Path

from crawler.config import CrawlConfig
from crawler.models import (
    ApiCall, AuthFinding, CookieInfo, DesignInfo, FieldInfo, FormInfo, HeadingInfo, LinkInfo,
    PageResult, SiteReport, TechHit,
)
from crawler.report import exporters
from crawler.report.builder import build_report

# PNG 1x1 transparente
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)

SECTIONS = ["Resumen ejecutivo", "Mapa del sitio y áreas", "Tecnologías", "Login y usuarios",
            "Interacción", "Diseño", "Contenido y SEO", "Seguridad", "Rendimiento", "Inventario", "Apéndice"]


def make_report(out_dir: Path) -> SiteReport:
    base = "https://shop.example.com"
    headers = {"server": "nginx", "content-type": "text/html; charset=utf-8", "content-encoding": "gzip",
               "strict-transport-security": "max-age=63072000"}
    design = DesignInfo(colors={"#3b5bdb": 12, "#ffffff": 40}, fonts=["Inter"], font_sources=["Google Fonts"],
                        css_frameworks=["Bootstrap"], breakpoints=["768px"], viewport="width=device-width",
                        landmarks={"header": True, "nav": True, "main": True, "footer": False}, responsive=True)
    login_form = FormInfo(page_url=f"{base}/login", action="/login", method="POST", kind="login",
                          fields=[FieldInfo(name="email", type="email", label="Correo", required=True),
                                  FieldInfo(name="password", type="password", label="Contraseña", required=True),
                                  FieldInfo(name="csrf_token", type="hidden")],
                          has_csrf=True, csrf_field="csrf_token", submit_text="Entrar")
    home = PageResult(
        url=f"{base}/", final_url=f"{base}/", status=200, depth=0, content_type="text/html", size_bytes=34000,
        elapsed_ms=210, http_version="HTTP/2", rendered=True, title="Tienda <Ejemplo>", lang="es",
        meta_description="La mejor tienda", og={"title": "Tienda"}, json_ld_types=["Organization"],
        headings=[HeadingInfo(level=1, text="Bienvenido"), HeadingInfo(level=2, text="Ofertas")],
        word_count=420, links=[LinkInfo(url=f"{base}/productos", text="Productos", in_nav=True),
                               LinkInfo(url="https://twitter.com/x", text="Twitter", internal=False)],
        images_total=10, images_no_alt=2, scripts=["https://www.googletagmanager.com/gtag/js?id=G-1"],
        headers=headers, cookies=[CookieInfo(name="sessionid", auth_hint=True)],
        api_calls=[ApiCall(url=f"{base}/api/cart?x=1", method="GET", resource_type="fetch", status=200,
                           content_type="application/json", page_url=f"{base}/"),
                   ApiCall(url=f"{base}/graphql", method="POST", graphql=True, status=200)],
        technologies=[TechHit(name="Nginx", category="Servidor web", evidence=["header server: nginx"]),
                      TechHit(name="Google Analytics", category="Analítica", confidence=90)],
        design=design, page_type="home", area="/", screenshot_desktop="screenshots/home_desktop.png",
        console_errors=["TypeError: x is undefined"],
    )
    login = PageResult(
        url=f"{base}/login", status=200, depth=1, parent=f"{base}/", content_type="text/html", size_bytes=9000,
        elapsed_ms=150, title="Iniciar sesión", lang="es", forms=[login_form], headers=headers,
        technologies=[TechHit(name="Nginx", category="Servidor web", version="1.25", evidence=["x"])],
        auth=[AuthFinding(kind="login_page", detail="Formulario de acceso", url=f"{base}/login"),
              AuthFinding(kind="sso_provider", detail="Google", url=f"{base}/login")],
        page_type="auth", area="/login",
    )
    broken = PageResult(url=f"{base}/productos/viejo", status=404, depth=2, parent=f"{base}/",
                        content_type="text/html", elapsed_ms=90, page_type="other", area="/productos")
    shots = out_dir / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    (shots / "home_desktop.png").write_bytes(PNG_1X1)
    return SiteReport(target=f"{base}/", domain="shop.example.com", started_at="2026-09-10T10:00:00",
                      duration_s=3.2, pages=[home, login, broken], robots_txt="User-agent: *\nDisallow: /admin",
                      sitemaps=[f"{base}/sitemap.xml"], sitemap_urls=3, server_info={"server": "nginx"},
                      config={"max_pages": 10}, output_dir=str(out_dir))


def test_build_report_fills_sections(tmp_path):
    report = build_report(make_report(tmp_path))
    names = {t.name for t in report.technologies}
    assert "Nginx" in names and len([t for t in report.technologies if t.name == "Nginx"]) == 1
    assert len(report.forms) == 1 and report.forms[0].kind == "login"
    assert report.api_endpoints and any(c.graphql for c in report.api_endpoints)
    assert report.performance["pages_measured"] == 3
    assert report.performance["compressed_pct"] > 0
    assert any(b["url"].endswith("/viejo") for b in report.broken_links)
    assert "twitter.com" in report.external_domains
    assert {s.name for s in report.scores} >= {"Accesibilidad", "Rendimiento"}
    assert 3 <= len(report.summary) <= 12
    assert all(0 <= s.value <= 100 for s in report.scores)


def test_export_html_and_json(tmp_path):
    report = build_report(make_report(tmp_path))
    files = exporters.export_all(report, CrawlConfig(start_url=report.target, output_dir=str(tmp_path)))
    html = Path(files["html"]).read_text(encoding="utf-8")
    for section in SECTIONS:
        assert section in html, section
    assert "data:image/png;base64," in html          # captura embebida
    assert "Tienda &lt;Ejemplo&gt;" in html          # autoescape
    data = json.loads(Path(files["json"]).read_text(encoding="utf-8"))
    assert data["domain"] == "shop.example.com"
    assert "html" not in data["pages"][0]            # campo excluido


def test_repeated_forms_are_deduplicated(tmp_path):
    report = make_report(tmp_path)
    base = "https://shop.example.com"
    for i in range(4):
        url = f"{base}/libro-{i}?ref=x"
        basket = [FormInfo(page_url=url, action="", method="POST", kind="other", submit_text="Add to basket",
                           fields=[FieldInfo(name="qty", type="number")]) for _ in range(20)]
        # misma acción apuntando a la propia página también cuenta como idéntico
        basket.append(FormInfo(page_url=url, action=url, method="POST", kind="other", submit_text="Add to basket",
                               fields=[FieldInfo(name="qty", type="number")]))
        report.pages.append(PageResult(url=url, status=200, depth=2, content_type="text/html", forms=basket))
    report = build_report(report)
    baskets = [f for f in report.forms if f.submit_text == "Add to basket"]
    assert len(baskets) == 1
    idx = report.forms.index(baskets[0])
    assert report.interactions["form_pages"][idx] == 4
    assert any("presente en 4 páginas" in s for s in report.summary)
    html = exporters.render_html(report)
    assert "presente en 4 páginas" in html


def test_builder_survives_broken_analyzer(tmp_path, monkeypatch):
    import crawler.report.builder as b

    real = b._analyzer

    def boom(name):
        if name == "seo":
            raise RuntimeError("fallo simulado")
        return real(name)

    monkeypatch.setattr(b, "_analyzer", boom)
    report = b.build_report(make_report(tmp_path))
    assert any("seo" in e for e in report.errors)
    assert report.summary
    exporters.export_all(report)


def test_empty_report_renders(tmp_path):
    report = SiteReport(target="https://vacio.example", domain="vacio.example", started_at="x",
                        output_dir=str(tmp_path))
    report = build_report(report)
    html = exporters.render_html(report)
    assert "No detectado" in html or "Ninguno" in html
