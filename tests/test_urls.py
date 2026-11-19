from crawler.urls import Scope, normalize, registrable_domain


def test_normalize_basic():
    assert normalize("HTTPS://Example.COM:443/a//b?b=2&a=1#frag") == "https://example.com/a/b?a=1&b=2"
    assert normalize("/x", "https://ex.com/a/b") == "https://ex.com/x"
    assert normalize("https://ex.com") == "https://ex.com/"


def test_normalize_drops_tracking_and_non_http():
    assert normalize("https://ex.com/?utm_source=x&id=3") == "https://ex.com/?id=3"
    for bad in ("mailto:a@b.com", "javascript:void(0)", "tel:123", "ftp://ex.com/f", ""):
        assert normalize(bad) is None


def test_normalize_keeps_spa_hash_routes():
    assert normalize("https://ex.com/#/login") == "https://ex.com/#/login"
    assert normalize("https://ex.com/#!/app") == "https://ex.com/#!/app"
    assert normalize("https://ex.com/page#section") == "https://ex.com/page"


def test_registrable_domain():
    assert registrable_domain("app.lab10.ai") == "lab10.ai"
    assert registrable_domain("www.tienda.com.mx") == "tienda.com.mx"
    assert registrable_domain("localhost") == "localhost"


def test_scope():
    s = Scope("https://www.ex.com/")
    assert s.is_internal("https://ex.com/a")
    assert s.is_internal("https://www.ex.com/a")
    assert not s.is_internal("https://blog.ex.com/a")
    assert not s.should_crawl("https://ex.com/logo.png")
    assert s.should_crawl("https://ex.com/productos")
    assert Scope("https://ex.com/", include_subdomains=True).is_internal("https://blog.ex.com/")
    assert s.is_same_site("https://cdn.ex.com/x.js")
