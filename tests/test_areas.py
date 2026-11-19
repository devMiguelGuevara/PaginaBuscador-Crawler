from crawler.analyzers.areas import area_of, build_areas, classify_page, detect_site_type, nav_menu
from crawler.models import FormInfo, HeadingInfo, LinkInfo, PageResult, TechHit


def test_area_of():
    assert area_of("https://ej.com/") == "/"
    assert area_of("https://ej.com") == "/"
    assert area_of("https://ej.com/blog/post-1") == "/blog"
    assert area_of("https://ej.com/es/productos/x") == "/productos"
    assert area_of("https://ej.com/es-mx/") == "/"
    assert area_of("https://ej.com/en-US/Docs/intro") == "/docs"
    assert area_of("https://app.ej.com/#/dashboard/stats") == "#/dashboard"
    assert area_of("https://ej.com/index.html") == "/"
    assert area_of("https://ej.com/about.html") == "/about"


def _p(url: str, **kw) -> PageResult:
    kw.setdefault("status", 200)
    return PageResult(url=url, final_url=url, **kw)


def test_classify_page():
    assert classify_page(_p("https://ej.com/")) == "home"
    assert classify_page(_p("https://ej.com/login")) == "auth"
    assert classify_page(_p("https://ej.com/x", forms=[FormInfo(page_url="", kind="login")])) == "auth"
    assert classify_page(_p("https://ej.com/cart")) == "carrito/checkout"
    assert classify_page(_p("https://ej.com/mi-cuenta/pedidos")) == "cuenta"
    assert classify_page(_p("https://ej.com/item-9", json_ld_types=["Product"])) == "producto"
    assert classify_page(_p("https://ej.com/2024/05/algo", og={"og:type": "article"})) == "blog/articulo"
    assert classify_page(_p("https://ej.com/blog/hola")) == "blog/articulo"
    assert classify_page(_p("https://ej.com/catalogue/category/books_1/index.html")) == "categoria/listado"
    assert classify_page(_p("https://ej.com/contacto")) == "contacto"
    assert classify_page(_p("https://ej.com/privacy-policy")) == "legal"
    assert classify_page(_p("https://ej.com/docs/start")) == "documentacion"
    assert classify_page(_p("https://ej.com/pricing")) == "precios"
    assert classify_page(_p("https://ej.com/faq")) == "soporte/faq"
    assert classify_page(_p("https://ej.com/search?q=x")) == "busqueda"
    assert classify_page(_p("https://ej.com/gone", status=404)) == "error"
    assert classify_page(_p("https://ej.com/zz", title="Contáctanos hoy")) == "contacto"
    assert classify_page(_p("https://ej.com/zz", headings=[HeadingInfo(level=1, text="Quiénes somos")])) == "acerca"
    assert classify_page(_p("https://ej.com/random-thing")) == "other"


def test_build_areas_and_nav():
    nav = [LinkInfo(url="https://ej.com/blog", text="Blog", in_nav=True),
           LinkInfo(url="https://ej.com/contacto", text="Contacto", in_nav=True),
           LinkInfo(url="https://ej.com/blog/", text="", in_nav=True)]
    pages = [
        _p("https://ej.com/", links=nav, page_type="home", area="/"),
        _p("https://ej.com/blog/a", links=nav, page_type="blog/articulo", area="/blog"),
        _p("https://ej.com/blog/b", links=nav[:2], page_type="blog/articulo", area="/blog"),
        _p("https://ej.com/legal/terms", page_type="legal", area="/legal"),
    ]
    areas = build_areas(pages)
    assert [a.path_prefix for a in areas] == ["/", "/blog", "/legal"]
    blog = areas[1]
    assert blog.name == "Blog" and blog.pages == 2 and blog.in_nav
    assert blog.page_types == {"blog/articulo": 2}
    assert areas[0].name == "Inicio"
    assert areas[2].in_nav is False
    menu = nav_menu(pages)
    assert [m.text for m in menu] == ["Blog", "Contacto"]


def test_detect_site_type():
    shop = [_p("https://s.com/", page_type="home")]
    assert detect_site_type(shop, [TechHit(name="Shopify", category="Ecommerce")], []).startswith("E-commerce")
    blog = [_p(f"https://b.com/blog/{i}", page_type="blog/articulo") for i in range(5)] + [_p("https://b.com/")]
    assert detect_site_type(blog, [], []).startswith("Blog")
    app = [_p("https://app.x.com/", page_type="home", spa_suspected=True),
           _p("https://app.x.com/login", page_type="auth")]
    forms = [FormInfo(page_url="https://app.x.com/login", kind="login")]
    assert detect_site_type(app, [], forms) == "Aplicación web / SaaS"
    assert detect_site_type([_p("https://l.com/")], [], []).startswith("Landing")
    corp = [_p(f"https://c.com/p{i}", page_type="other") for i in range(6)]
    assert detect_site_type(corp, [], []).startswith("Sitio corporativo")
    assert detect_site_type([], [], [])
