from selectolax.lexbor import LexborHTMLParser

from crawler.analyzers import tech
from crawler.models import CookieInfo, PageResult, TechHit

WP = """
<html><head><meta name="generator" content="WordPress 6.5.2">
<link rel="stylesheet" href="/wp-content/themes/x/style.css">
<script src="/wp-includes/js/jquery/jquery.min.js?ver=3.7.1"></script>
<script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"></script>
</head><body></body></html>
"""

NEXT = """
<html><head><script src="/_next/static/chunks/main-abc.js"></script></head>
<body><div id="__next"></div><script id="__NEXT_DATA__" type="application/json">{}</script></body></html>
"""


def _page(html, **kw):
    tree = LexborHTMLParser(html)
    scripts = [s.attributes.get("src") for s in tree.css("script[src]")]
    gen = tree.css_first("meta[name=generator]")
    return PageResult(url="https://ej.com/", html=html, scripts=scripts,
                      generator=gen.attributes.get("content") if gen else "", **kw), tree


def _names(hits):
    return {h.name: h for h in hits}


def test_wordpress_php_nginx():
    p, tree = _page(WP, headers={"server": "nginx/1.25.3", "x-powered-by": "PHP/8.2.1"},
                    cookies=[CookieInfo(name="PHPSESSID")])
    hits = _names(tech.detect(p, tree))
    assert hits["WordPress"].version == "6.5.2"
    assert hits["WordPress"].category == "CMS"
    assert hits["Nginx"].version == "1.25.3"
    assert hits["PHP"].version == "8.2.1"
    assert "jQuery" in hits
    assert "Google Tag Manager" in hits
    assert "MySQL" in hits  # implicado por WordPress


def test_nextjs_vercel_and_js_globals():
    p, tree = _page(NEXT, headers={"x-vercel-id": "iad1::abc", "server": "Vercel"},
                    js_globals=["__NEXT_DATA__", "React.version=18.3.1"])
    hits = _names(tech.detect(p, tree))
    assert {"Next.js", "React", "Vercel", "Node.js"} <= set(hits)
    assert hits["React"].version == "18.3.1"


def test_cloudflare_and_header_pattern():
    p, tree = _page("<html></html>", headers={"cf-ray": "abc", "server": "cloudflare", "x-vtex-cache": "1"})
    hits = _names(tech.detect(p, tree))
    assert "Cloudflare" in hits and "VTEX" in hits


def test_supabase_by_api_calls_and_ecommerce_category():
    from crawler.models import ApiCall
    p, tree = _page("<html></html>", api_calls=[
        ApiCall(url="https://abc.example.com/rest/v1/rpc/get_items", method="POST"),
        ApiCall(url="https://abc.example.com/auth/v1/user", method="GET")])
    hits = _names(tech.detect(p, tree))
    assert "Supabase" in hits and "Supabase Auth" in hits
    p, tree = _page('<script src="https://cdn.shopify.com/s/x.js"></script>')
    assert "Ecommerce" in _names(tech.detect(p, tree))["Shopify"].category


def test_prefilter_literals():
    assert tech.prefilter(r"[\w-]+\.auth0\.com") == (".auth0.com",)
    first, second = tech.prefilter(r"continu\w+ (con|with) google|gsi/client")
    assert first in ("continu", " google") and second == "gsi/client"
    assert tech.prefilter(r"jquery(?:[.-](?P<version>\d+))?\.js") == ("jquery",)
    assert tech.prefilter(r"a|bc") is None
    assert tech.prefilter(r"_nghost-") == ("_nghost-",)
    assert tech.prefilter(r"Mage\.Cookies") == ("mage.cookies",)
    assert tech.prefilter(r"https?://x\.com") == ("://x.com",)


def test_merge_and_probe():
    a = TechHit(name="React", category="Framework JavaScript", confidence=70, evidence=["a"])
    b = TechHit(name="React", category="Framework JavaScript", version="18", confidence=100, evidence=["b"])
    (m,) = tech.merge([a, b])
    assert m.confidence == 100 and m.version == "18" and m.evidence == ["a", "b"]
    probes = tech.js_probe_names()
    assert "__NEXT_DATA__" in probes and "jQuery.fn.jquery" in probes
    assert len(tech._load()) >= 120
