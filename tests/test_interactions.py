from selectolax.lexbor import LexborHTMLParser

from crawler.analyzers.interactions import collect_api_endpoints, page_interactions, site_interactions
from crawler.models import ApiCall, FormInfo, LinkInfo, PageResult

HTML = """<html><body>
<a class="btn btn-primary" href="/signup">Crear cuenta gratis</a>
<button type="button">Solicitar demo</button>
<button>x</button>
<a href="/about">Nosotros</a>
<form role="search"><input type="search" name="q"></form>
<div class="modal" id="m1"></div><dialog></dialog>
<div onclick="go()">clic</div>
<iframe src="https://www.youtube.com/embed/abc"></iframe>
<script src="https://widget.intercom.io/widget/xyz"></script>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-1"></script>
<div id="cookie-banner">Usamos cookies para mejorar tu experiencia</div>
</body></html>"""


def _page() -> PageResult:
    return PageResult(
        url="https://ej.com/", final_url="https://ej.com/", html=HTML,
        scripts=["https://widget.intercom.io/widget/xyz", "https://www.googletagmanager.com/gtag/js?id=G-1",
                 "https://ej.com/app.js"],
        iframes=["https://www.youtube.com/embed/abc"],
        links=[LinkInfo(url="https://facebook.com/ejemplo", internal=False),
               LinkInfo(url="https://ej.com/docs/manual.pdf"),
               LinkInfo(url="https://ej.com/about")],
        api_calls=[ApiCall(url="wss://rt.ej.com/socket", resource_type="websocket"),
                   ApiCall(url="https://api.ej.com/graphql?op=Q", method="POST", graphql=True),
                   ApiCall(url="https://api.ej.com/graphql?op=R", method="POST", graphql=True),
                   ApiCall(url="https://api.ej.com/users", method="GET")],
        forms=[FormInfo(page_url="https://ej.com/", kind="search")],
    )


def test_page_interactions():
    p = _page()
    inter = page_interactions(p, LexborHTMLParser(HTML))
    assert "Crear cuenta gratis" in inter["ctas"]
    assert "Solicitar demo" in inter["ctas"]
    assert "Nosotros" not in inter["ctas"]
    assert inter["search"] is True
    assert inter["modals"] == 2
    assert inter["event_handlers"] == 1
    assert inter["chat_widgets"] == ["Intercom"]
    assert "Google Analytics" in inter["analytics"]
    assert inter["social"] == ["Facebook"]
    assert inter["video"] == ["YouTube"]
    assert inter["cookie_banner"] is True
    assert inter["downloads"] == ["https://ej.com/docs/manual.pdf"]
    assert inter["websockets"] == ["wss://rt.ej.com/socket"]
    assert inter["graphql"] is True


def test_page_interactions_no_tree():
    inter = page_interactions(PageResult(url="https://x.com/"), None)
    assert inter["ctas"] == [] and inter["search"] is False and inter["modals"] == 0


def test_site_interactions_and_endpoints():
    p = _page()
    p.interactions = page_interactions(p, LexborHTMLParser(HTML))
    site = site_interactions([p])
    assert site["search"] and site["graphql"] and site["cookie_banner"]
    assert "widget.intercom.io" in site["third_party_services"]
    assert "api.ej.com" not in site["third_party_services"]  # mismo dominio base
    assert site["websockets"] == ["wss://rt.ej.com/socket"]
    eps = collect_api_endpoints([p])
    urls = [(e.method, e.url) for e in eps]
    assert ("POST", "https://api.ej.com/graphql") in urls
    assert len([u for u in urls if u[1] == "https://api.ej.com/graphql"]) == 1
    assert len(eps) == 3
    assert site_interactions([])["ctas"] == []
