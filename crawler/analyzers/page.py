"""Extracción base de contenido y elementos de una página HTML."""
from __future__ import annotations

import json
import re

from selectolax.lexbor import LexborHTMLParser

from ..models import HeadingInfo, LinkInfo, PageResult
from ..urls import Scope, normalize

MAX_LINKS = 400
SPA_ROOTS = ("#root", "#app", "#__next", "#__nuxt", "#___gatsby", "#svelte", "app-root", "[ng-version]",
             "[data-reactroot]", "#q-app", "#main-app")


def _attr(node, name: str) -> str:
    return (node.attributes.get(name) or "").strip() if node is not None else ""


def _clean(text: str | None, limit: int = 200) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _in_nav(node) -> bool:
    p = node.parent
    depth = 0
    while p is not None and depth < 12:
        if p.tag in ("nav", "header") or _attr(p, "role") in ("navigation", "menubar", "menu"):
            return True
        p = p.parent
        depth += 1
    return False


def visible_text(html: str) -> str:
    t = LexborHTMLParser(html)
    t.strip_tags(["script", "style", "noscript", "template", "svg"])
    body = t.body or t.root
    return _clean(body.text(separator=" ") if body else "", 10_000_000)


def parse_page(page: PageResult, tree: LexborHTMLParser, scope: Scope) -> list[str]:
    """Rellena campos de contenido/elementos en `page` y devuelve URLs internas rastreables."""
    base = page.final_url or page.url
    base_node = tree.css_first("base[href]")
    if base_node is not None:
        base = normalize(_attr(base_node, "href"), base) or base

    page.title = _clean(tree.css_first("title").text() if tree.css_first("title") else "", 300)
    html_node = tree.css_first("html")
    page.lang = _attr(html_node, "lang")

    for m in tree.css("meta"):
        name = (_attr(m, "name") or _attr(m, "property") or _attr(m, "http-equiv")).lower()
        content = _attr(m, "content")
        if not name:
            continue
        if name == "description":
            page.meta_description = _clean(content, 500)
        elif name == "robots":
            page.meta_robots = content
        elif name == "viewport":
            page.viewport = content
        elif name == "generator":
            page.generator = content
        elif name == "theme-color":
            page.theme_color = content
        elif name.startswith("og:") and len(page.og) < 20:
            page.og[name[3:]] = _clean(content, 300)
        elif name.startswith("twitter:") and len(page.twitter) < 20:
            page.twitter[name[8:]] = _clean(content, 300)

    for link in tree.css("link[rel]"):
        rel = _attr(link, "rel").lower()
        href = _attr(link, "href")
        if "canonical" in rel:
            page.canonical = normalize(href, base) or href
        elif "alternate" in rel and _attr(link, "hreflang"):
            page.hreflang.append(_attr(link, "hreflang"))
        elif "stylesheet" in rel:
            u = normalize(href, base)
            if u and u not in page.stylesheets:
                page.stylesheets.append(u)

    types: list[str] = []
    for s in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(s.text() or "")
        except (ValueError, TypeError):
            continue
        stack = [data]
        while stack and len(types) < 30:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                t = item.get("@type")
                for v in (t if isinstance(t, list) else [t]):
                    if isinstance(v, str) and v not in types:
                        types.append(v)
                if "@graph" in item:
                    stack.append(item["@graph"])
    page.json_ld_types = types

    page.headings = [
        HeadingInfo(level=int(h.tag[1]), text=_clean(h.text(separator=" "), 200))
        for h in tree.css("h1, h2, h3, h4")[:80]
        if _clean(h.text())
    ]

    # Scripts, iframes, imágenes, botones
    for s in tree.css("script"):
        src = _attr(s, "src")
        if src:
            u = normalize(src, base)
            if u and u not in page.scripts:
                page.scripts.append(u)
        elif _attr(s, "type") != "application/ld+json":
            page.inline_scripts += 1
    page.iframes = [u for u in (normalize(_attr(f, "src"), base) for f in tree.css("iframe[src]")) if u][:30]
    imgs = tree.css("img")
    page.images_total = len(imgs)
    page.images_no_alt = sum(1 for i in imgs if "alt" not in i.attributes)
    buttons = []
    for b in tree.css('button, input[type="submit"], input[type="button"], [role="button"]'):
        label = _clean(b.text(separator=" ") or _attr(b, "value") or _attr(b, "aria-label") or _attr(b, "title"), 80)
        if label and label not in buttons and not re.fullmatch(r"[\d\W_]{1,4}", label):
            buttons.append(label)
        if len(buttons) >= 50:
            break
    page.buttons = buttons

    # Enlaces
    found: list[str] = []
    seen: set[str] = set()
    for a in tree.css("a[href], [routerlink], [data-href]"):
        href = _attr(a, "href") or _attr(a, "routerlink") or _attr(a, "data-href")
        u = normalize(href, base)
        if not u or u in seen:
            continue
        internal = scope.is_internal(u)
        # En un sitio https, un enlace http:// interno apunta a la misma página (aunque esta página
        # haya llegado por http tras una redirección que rebaja el protocolo)
        if internal and u.startswith("http://") and (base.startswith("https://")
                                                     or scope.start_url.startswith("https://")):
            u = "https://" + u[7:]
            if u in seen:
                continue
        seen.add(u)
        if len(page.links) < MAX_LINKS:
            page.links.append(LinkInfo(
                url=u,
                text=_clean(a.text(separator=" ") or _attr(a, "aria-label") or _attr(a, "title"), 120),
                internal=internal,
                nofollow="nofollow" in _attr(a, "rel").lower(),
                in_nav=_in_nav(a),
            ))
        if internal and scope.should_crawl(u):
            found.append(u)

    # Texto visible
    text = visible_text(page.html) if page.html else ""
    page.word_count = len(text.split())
    page.text_excerpt = text[:400]
    page.spa_suspected = detect_spa(page, tree)
    return found


def detect_spa(page: PageResult, tree: LexborHTMLParser) -> bool:
    """Heurística: HTML casi vacío con contenedor raíz de framework JS y bundles."""
    has_root = any(tree.css_first(sel) is not None for sel in SPA_ROOTS)
    module_scripts = len(tree.css('script[type="module"]')) + len(page.scripts)
    if page.word_count < 60 and (has_root or module_scripts >= 1):
        return True
    noscript = tree.css_first("noscript")
    if noscript is not None and re.search(r"enable javascript|habilita javascript|activa javascript|need to enable",
                                          noscript.text() or "", re.I):
        return page.word_count < 200
    return False
