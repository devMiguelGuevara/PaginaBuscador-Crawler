from selectolax.lexbor import LexborHTMLParser

from crawler.analyzers import auth
from crawler.analyzers.forms import extract_forms
from crawler.models import ApiCall, CookieInfo, LinkInfo, PageResult

HOME_HTML = """
<html><head><script src="https://accounts.google.com/gsi/client"></script></head><body>
<nav><a href="/login">Iniciar sesión</a><a href="/registro">Regístrate</a><a href="/carrito">Carrito</a></nav>
</body></html>
"""

LOGIN_HTML = """
<form method="post" action="/login"><input type="hidden" name="_token" value="x">
<input type="email" name="email"><input type="password" name="password">
<a href="/password/reset">¿Olvidé mi contraseña?</a><button>Entrar</button></form>
"""


def _page(url, html, **kw):
    tree = LexborHTMLParser(html)
    p = PageResult(url=url, final_url=kw.pop("final_url", url), html=html, **kw)
    p.forms = extract_forms(tree, p.final_url)
    return p, tree


def test_home_links_and_sso():
    p, tree = _page("https://ej.com/", HOME_HTML,
                    scripts=["https://accounts.google.com/gsi/client"],
                    links=[LinkInfo(url="https://ej.com/login", text="Iniciar sesión"),
                           LinkInfo(url="https://ej.com/registro", text="Regístrate"),
                           LinkInfo(url="https://ej.com/carrito", text="Carrito")])
    findings = auth.analyze_page(p, tree)
    kinds = {(f.kind, f.url) for f in findings}
    assert ("login_entry", "https://ej.com/login") in kinds
    assert ("register_entry", "https://ej.com/registro") in kinds
    assert not any(f.kind in ("login_page", "register_page") for f in findings)
    assert any(f.kind == "sso_provider" and f.detail == "Google" for f in findings)


def test_login_page_form_cookie_and_storage():
    p, tree = _page("https://ej.com/login", LOGIN_HTML,
                    cookies=[CookieInfo(name="laravel_session", http_only=True, secure=True)],
                    storage_keys={"local": ["access_token", "theme"]},
                    api_calls=[ApiCall(url="https://api.ej.com/auth/me", method="GET", status=401)])
    findings = auth.analyze_page(p, tree)
    kinds = {f.kind for f in findings}
    assert {"login_page", "login_form", "session_cookie", "jwt_storage", "auth_api"} <= kinds
    assert not any(f.kind == "jwt_storage" and "theme" in f.detail for f in findings)


def test_protected_redirect():
    p, tree = _page("https://ej.com/dashboard", "<html></html>", status=200,
                    final_url="https://ej.com/login?next=/dashboard",
                    redirect_chain=["https://ej.com/dashboard"])
    findings = auth.analyze_page(p, tree)
    assert any(f.kind == "protected_area" and f.url == "https://ej.com/dashboard" for f in findings)


def test_summarize():
    p1, t1 = _page("https://ej.com/", HOME_HTML, scripts=["https://accounts.google.com/gsi/client"],
                   links=[LinkInfo(url="https://ej.com/login", text="Iniciar sesión"),
                          LinkInfo(url="https://ej.com/registro", text="Regístrate"),
                          LinkInfo(url="https://ej.com/carrito", text="Carrito")])
    p2, t2 = _page("https://ej.com/login", LOGIN_HTML,
                   cookies=[CookieInfo(name="PHPSESSID")])
    p3, t3 = _page("https://ej.com/admin", "", status=403)
    findings = []
    for p, t in ((p1, t1), (p2, t2), (p3, t3)):
        p.auth = auth.analyze_page(p, t)
        findings += p.auth
    s = auth.summarize([p1, p2, p3], findings)
    assert s["has_login"] and s["has_register"] and s["has_password_reset"]
    assert "Google" in s["sso_providers"]
    assert "https://ej.com/admin" in s["protected_urls"]
    assert any("PHPSESSID" in m for m in s["session_mechanisms"])
    assert "Carrito de compras" in s["user_features"]
    assert s["mfa"] is False
    assert isinstance(s["notes"], list)


def test_header_button_is_entry_not_login_page():
    pages, findings = [], []
    for path in ("/", "/productos", "/blog", "/contacto"):
        p, t = _page("https://ej.com" + path, "<html><body><button>Iniciar sesión</button></body></html>",
                     buttons=["Iniciar sesión"], cookies=[CookieInfo(name="sessionid")])
        p.auth = auth.analyze_page(p, t)
        assert not any(f.kind == "login_page" for f in p.auth)
        assert any(f.kind == "login_entry" and f.detail == "Botón de inicio de sesión" for f in p.auth)
        pages.append(p)
        findings += p.auth
    deduped = auth.dedupe_findings(findings)
    assert sum(f.kind == "login_entry" for f in deduped) == 1
    assert sum(f.kind == "session_cookie" for f in deduped) == 1
    s = auth.summarize(pages, findings)
    assert s["has_login"] is True
    assert s["login_urls"] == []
    assert len(s["entry_points"]) == 1


def test_login_modal_by_query_redirect():
    p, t = _page("https://app.ej.ai/directory", "<html></html>", status=200,
                 final_url="https://app.ej.ai/?login=1&next=%2Fdirectory",
                 redirect_chain=["https://app.ej.ai/directory"])
    p.auth = auth.analyze_page(p, t)
    assert any(f.kind == "protected_area" and f.url == "https://app.ej.ai/directory" for f in p.auth)
    assert any(f.kind == "login_page" and f.url == p.final_url for f in p.auth)
    s = auth.summarize([p], p.auth)
    assert s["login_urls"] == ["https://app.ej.ai/?login=1&next=%2Fdirectory"]
    assert s["protected_urls"] == ["https://app.ej.ai/directory"]


def test_global_login_form_collapsed():
    pages, findings = [], []
    for path in ("/", "/a", "/b", "/c", "/d"):
        p, t = _page("https://ej.com" + path, LOGIN_HTML.replace('action="/login"', ""))
        p.auth = auth.analyze_page(p, t)
        pages.append(p)
        findings += p.auth
    s = auth.summarize(pages, findings)
    assert s["login_urls"] == ["https://ej.com/"]
    assert any("modal o cabecera" in n for n in s["notes"])


def test_author_path_is_not_login():
    assert not auth.looks_login("https://ej.com/author/juan")
    assert auth.looks_login("https://ej.com/users/sign_in")
    assert auth.looks_register("https://ej.com/?signup=1")


def test_summarize_empty():
    s = auth.summarize([], [])
    assert s["has_login"] is False
    assert s["notes"]
