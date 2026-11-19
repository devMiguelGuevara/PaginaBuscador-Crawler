from crawler.analyzers.security import site_security
from crawler.analyzers.seo import site_seo
from crawler.models import CookieInfo, FormInfo, HeadingInfo, PageResult


def _good(url: str, title: str) -> PageResult:
    return PageResult(
        url=url, final_url=url, status=200, content_type="text/html", title=title,
        meta_description="Descripción única de " + title, canonical=url, lang="es",
        viewport="width=device-width", og={"og:title": title}, json_ld_types=["Organization"],
        headings=[HeadingInfo(level=1, text=title)], word_count=400, elapsed_ms=300,
    )


def test_seo_good_site_scores_high():
    pages = [_good("https://ej.com/", "Inicio de Ejemplo S.A."), _good("https://ej.com/a", "Página A de Ejemplo")]
    r = site_seo(pages)
    assert r["score"] == 100
    assert r["issues"] == []
    assert r["stats"]["paginas_analizadas"] == 2


def test_seo_detects_issues():
    bad = PageResult(url="https://ej.com/x", status=200, content_type="text/html", word_count=10,
                     headings=[HeadingInfo(level=1, text="a"), HeadingInfo(level=1, text="b")],
                     images_total=3, images_no_alt=2, meta_robots="noindex", elapsed_ms=3000)
    dup1 = _good("https://ej.com/d1", "Mismo título repetido aquí")
    dup2 = _good("https://ej.com/d2", "Mismo título repetido aquí")
    broken = PageResult(url="https://ej.com/404", status=404)
    r = site_seo([bad, dup1, dup2, broken])
    msgs = {i["message"]: i for i in r["issues"]}
    assert "https://ej.com/x" in msgs["Páginas sin etiqueta <title>"]["urls"]
    assert set(msgs["Títulos duplicados entre páginas"]["urls"]) == {"https://ej.com/d1", "https://ej.com/d2"}
    assert msgs["Páginas que responden con error (4xx/5xx)"]["urls"] == ["https://ej.com/404"]
    assert "Páginas con varios H1" in msgs and "Páginas marcadas como noindex" in msgs
    assert "Imágenes sin texto alternativo (alt)" in msgs and "Páginas lentas (más de 2 s de respuesta)" in msgs
    assert r["issues"][0]["severity"] == "alta"
    assert r["score"] < 70
    assert site_seo([])["score"] == 100


def test_security_headers_and_cookies():
    p = PageResult(
        url="http://ej.com/", final_url="https://ej.com/", status=200, depth=0,
        redirect_chain=["http://ej.com/"],
        headers={"Strict-Transport-Security": "max-age=31536000", "Server": "nginx/1.18.0",
                 "X-Content-Type-Options": "nosniff"},
        cookies=[CookieInfo(name="sessionid", secure=False, http_only=False, same_site="", auth_hint=True),
                 CookieInfo(name="pref", secure=True, http_only=False, same_site="Lax")],
        scripts=["http://cdn.otro.com/a.js"],
        forms=[FormInfo(page_url="https://ej.com/", kind="login", method="POST", has_csrf=False)],
    )
    r = site_security([p], "http://ej.com/")
    assert r["https"] is True and r["redirect_to_https"] is True
    assert r["headers"]["strict-transport-security"] == "max-age=31536000"
    assert "content-security-policy" in r["missing_headers"]
    assert "strict-transport-security" not in r["missing_headers"]
    assert any("nginx/1.18.0" in v for v in r["version_disclosure"])
    assert any("sessionid" in c for c in r["cookie_issues"])
    assert not any("pref" in c for c in r["cookie_issues"])
    assert r["mixed_content"] == ["http://cdn.otro.com/a.js"]
    assert any("CSRF" in i["message"] for i in r["issues"])
    assert 0 <= r["score"] < 60


def test_security_plain_http():
    p = PageResult(url="http://ej.com/", final_url="http://ej.com/", status=200)
    r = site_security([p], "http://ej.com/")
    assert r["https"] is False
    assert r["issues"][0]["severity"] == "alta"
    assert site_security([], "https://x.com")["score"] <= 100
