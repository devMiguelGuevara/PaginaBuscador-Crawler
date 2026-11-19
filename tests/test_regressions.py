"""Regresiones encontradas en rastreos reales (app.lab10.ai, quotes/books.toscrape.com)."""
from selectolax.lexbor import LexborHTMLParser

from crawler.analyzers import areas, interactions
from crawler.analyzers.page import parse_page
from crawler.engine import AUTH_URL_RE
from crawler.models import ApiCall, FormInfo, PageResult
from crawler.urls import Scope


def test_author_is_not_auth():
    assert not AUTH_URL_RE.search("https://quotes.toscrape.com/author/Jane-Austen")
    assert AUTH_URL_RE.search("https://ej.com/auth/login")
    assert AUTH_URL_RE.search("https://app.lab10.ai/?login=1&next=%2Fdirectory")
    p = PageResult(url="https://q.com/author/Jane-Austen", final_url="https://q.com/author/Jane-Austen/",
                   status=200, redirect_chain=["301 https://q.com/author/Jane-Austen"])
    assert areas.classify_page(p) != "auth"


def test_protected_redirect_is_auth():
    p = PageResult(url="https://app.lab10.ai/directory", final_url="https://app.lab10.ai/?login=1&next=%2Fdirectory",
                   status=200, redirect_chain=["307 https://app.lab10.ai/directory"])
    assert areas.classify_page(p) == "auth"


def test_add_to_cart_means_ecommerce():
    pages = [PageResult(url=f"https://b.com/c/{i}", status=200, page_type="categoria/listado") for i in range(5)]
    forms = [FormInfo(page_url="https://b.com/", kind="add_to_cart", submit_text="Add to basket")]
    assert areas.detect_site_type(pages, [], forms).startswith("E-commerce")


def test_rendered_pages_are_not_spa():
    pages = [PageResult(url=f"https://q.com/t/{i}", status=200, rendered=True) for i in range(6)]
    forms = [FormInfo(page_url="https://q.com/login", kind="login")]
    assert areas.detect_site_type(pages, [], forms) != "Aplicación web / SaaS"


def test_api_endpoints_group_ids():
    calls = [ApiCall(url=f"https://cdn.x.com/{'a1b2c3d4e5f6a7b8c9d0' + str(i)}/seg", page_url="https://x.com/")
             for i in range(10)]
    calls.append(ApiCall(url="https://db.x.com/rest/v1/rpc/get_programs?select=*", method="POST"))
    page = PageResult(url="https://x.com/", api_calls=calls)
    eps = interactions.collect_api_endpoints([page])
    assert len(eps) == 2
    assert any(e.url == "https://cdn.x.com/{id}/seg" for e in eps)


def test_empty_form_container_is_skipped():
    from crawler.analyzers.forms import extract_forms
    html = """<form method="get" class="form-horizontal"><div style="display:none"></div><strong>1000</strong></form>
              <form><button type="submit">Add to basket</button></form>"""
    forms = extract_forms(LexborHTMLParser(html), "https://b.com/")
    assert [f.kind for f in forms] == ["add_to_cart"]


def test_links_upgraded_after_https_to_http_downgrade():
    # quotes.toscrape.com: https://…/author/X → 301 → http://…/author/X/ con enlaces http://
    html = '<html><body><a href="http://q.com/login">Login</a></body></html>'
    page = PageResult(url="https://q.com/author/X", final_url="http://q.com/author/X/", html=html)
    found = parse_page(page, LexborHTMLParser(html), Scope("https://q.com/"))
    assert found == ["https://q.com/login"]


def test_https_to_http_downgrade_is_security_issue():
    from crawler.analyzers.security import site_security
    pages = [
        PageResult(url="https://q.com/", final_url="https://q.com/", status=200, depth=0),
        PageResult(url="https://q.com/author/X", final_url="http://q.com/author/X/", status=200, depth=1,
                   redirect_chain=["301 https://q.com/author/X"]),
    ]
    res = site_security(pages, "https://q.com/")
    assert any("HTTPS redirigen a HTTP" in i["message"] and i["severity"] == "alta" for i in res["issues"])


def test_internal_http_links_upgraded_on_https():
    html = '<html><body><a href="http://q.com/login">Login</a><a href="https://q.com/login">Login</a></body></html>'
    page = PageResult(url="https://q.com/", final_url="https://q.com/", html=html)
    found = parse_page(page, LexborHTMLParser(html), Scope("https://q.com/"))
    assert found == ["https://q.com/login"]
    assert [l.url for l in page.links] == ["https://q.com/login"]
