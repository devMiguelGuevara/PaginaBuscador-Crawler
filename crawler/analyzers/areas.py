"""Áreas/secciones del sitio, tipo de página, menú de navegación y tipo de sitio."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from urllib.parse import parse_qs, urlparse

from ..models import AreaInfo, FormInfo, LinkInfo, PageResult, TechHit

_LANGS = {
    "es", "en", "pt", "fr", "de", "it", "nl", "ca", "eu", "gl", "ja", "zh", "ko", "ru", "ar", "pl", "sv",
    "no", "da", "fi", "tr", "he", "hi", "cs", "el", "hu", "ro", "uk", "id", "vi", "th",
}
_LANG_RE = re.compile(r"^([a-z]{2})(?:[-_][a-z]{2,4})?$", re.I)

_AREA_NAMES = {
    "/": "Inicio", "blog": "Blog", "news": "Noticias", "noticias": "Noticias", "shop": "Tienda",
    "tienda": "Tienda", "store": "Tienda", "products": "Productos", "product": "Productos",
    "productos": "Productos", "producto": "Productos", "catalogue": "Catálogo", "catalog": "Catálogo",
    "catalogo": "Catálogo", "category": "Categorías", "categoria": "Categorías", "categories": "Categorías",
    "collections": "Colecciones", "about": "Acerca de", "about-us": "Acerca de", "nosotros": "Nosotros",
    "contact": "Contacto", "contacto": "Contacto", "contact-us": "Contacto", "login": "Inicio de sesión",
    "signin": "Inicio de sesión", "sign-in": "Inicio de sesión", "register": "Registro", "signup": "Registro",
    "sign-up": "Registro", "account": "Cuenta de usuario", "my-account": "Cuenta de usuario",
    "cuenta": "Cuenta de usuario", "profile": "Perfil", "perfil": "Perfil", "cart": "Carrito",
    "carrito": "Carrito", "checkout": "Pago", "docs": "Documentación", "documentation": "Documentación",
    "help": "Ayuda", "ayuda": "Ayuda", "support": "Soporte", "soporte": "Soporte", "faq": "Preguntas frecuentes",
    "pricing": "Precios", "precios": "Precios", "plans": "Planes", "planes": "Planes", "legal": "Legal",
    "privacy": "Privacidad", "privacidad": "Privacidad", "terms": "Términos", "terminos": "Términos",
    "dashboard": "Panel", "admin": "Administración", "app": "Aplicación", "search": "Búsqueda",
    "buscar": "Búsqueda", "tag": "Etiquetas", "tags": "Etiquetas", "author": "Autores", "careers": "Empleo",
    "jobs": "Empleo", "empleo": "Empleo", "servicios": "Servicios", "services": "Servicios",
    "features": "Funcionalidades", "api": "API", "static": "Recursos estáticos", "media": "Multimedia",
}

# (tipo, palabras clave en la ruta, palabras clave en el título)
_RULES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("auth", ("login", "signin", "sign-in", "logon", "register", "signup", "sign-up", "registro", "registrarse",
              "auth", "authenticate", "password", "forgot", "reset-password", "recuperar", "iniciar-sesion",
              "ingresar", "acceso", "sso", "oauth"),
     ("iniciar sesión", "inicia sesión", "log in", "login", "sign in", "registr", "sign up", "contraseña",
      "password")),
    ("carrito/checkout", ("cart", "carrito", "checkout", "basket", "bag", "pago", "payment", "cesta"),
     ("carrito", "checkout", "shopping cart", "finalizar compra")),
    ("cuenta", ("account", "my-account", "cuenta", "mi-cuenta", "profile", "perfil", "settings", "ajustes",
                "preferences", "user", "usuario", "me"),
     ("mi cuenta", "my account", "perfil", "profile")),
    ("dashboard", ("dashboard", "admin", "panel", "console", "backoffice", "wp-admin", "administrator"),
     ("dashboard", "panel de control", "administración")),
    ("busqueda", ("search", "buscar", "busqueda", "búsqueda", "results", "resultados"),
     ("resultados de búsqueda", "search results")),
    ("producto", ("product", "products", "producto", "productos", "item", "p", "dp", "sku"), ()),
    ("blog/articulo", ("blog", "news", "noticias", "post", "posts", "articulo", "articulos", "article",
                       "articles", "novedades", "prensa", "press"), ()),
    ("categoria/listado", ("category", "categoria", "categorias", "categories", "catalogue", "catalog",
                           "catalogo", "collections", "collection", "shop", "tienda", "tag", "tags", "archive",
                           "page"), ()),
    ("contacto", ("contact", "contacto", "contact-us", "contactanos", "contáctanos"),
     ("contacto", "contact us", "contáctanos")),
    ("acerca", ("about", "about-us", "nosotros", "acerca", "quienes-somos", "empresa", "company", "team",
                "equipo", "historia"),
     ("acerca de", "about us", "quiénes somos", "nosotros")),
    ("legal", ("privacy", "privacidad", "terms", "terminos", "términos", "legal", "cookies", "aviso-legal",
               "aviso-de-privacidad", "tos", "gdpr", "condiciones"),
     ("privacidad", "privacy", "términos", "terms", "aviso legal", "política de cookies")),
    ("documentacion", ("docs", "doc", "documentation", "documentacion", "guide", "guides", "guia", "reference",
                       "api-reference", "manual", "tutorial", "tutorials"),
     ("documentación", "documentation", "api reference")),
    ("precios", ("pricing", "precios", "plans", "planes", "tarifas", "prices"), ("precios", "pricing", "planes")),
    ("soporte/faq", ("faq", "faqs", "support", "soporte", "help", "ayuda", "preguntas-frecuentes", "centro-de-ayuda"),
     ("preguntas frecuentes", "faq", "soporte", "centro de ayuda", "help center")),
]

_ARTICLE_LD = {"article", "blogposting", "newsarticle", "techarticle", "report"}
_PRODUCT_LD = {"product", "offer", "aggregateoffer", "productgroup"}


def _segments(url: str) -> tuple[list[str], list[str]]:
    """Devuelve (segmentos de ruta sin prefijo de idioma, segmentos de hash-route)."""
    try:
        p = urlparse(url)
    except ValueError:
        return [], []
    segs = [s for s in p.path.split("/") if s]
    if segs and _LANG_RE.match(segs[0]) and _LANG_RE.match(segs[0]).group(1).lower() in _LANGS:
        segs = segs[1:]
    if segs and re.fullmatch(r"index\.(html?|php|aspx?|jsp)", segs[-1], re.I):
        segs = segs[:-1]
    frag = p.fragment or ""
    hash_segs: list[str] = []
    if frag.startswith("/") or frag.startswith("!/"):
        hash_segs = [s for s in frag.lstrip("!").split("?")[0].split("/") if s]
    return segs, hash_segs


def area_of(url: str) -> str:
    segs, hash_segs = _segments(url)
    if hash_segs and not segs:
        return "#/" + hash_segs[0].lower()
    if not segs:
        return "/"
    first = segs[0].lower()
    if "." in first and len(segs) == 1:  # archivo en la raíz (p.ej. /about.html)
        first = first.rsplit(".", 1)[0]
    return "/" + first


def _area_name(prefix: str) -> str:
    key = prefix.lstrip("#").strip("/").lower()
    if not key:
        return _AREA_NAMES["/"]
    if key in _AREA_NAMES:
        return _AREA_NAMES[key]
    name = re.sub(r"[-_]+", " ", key).strip()
    return (name[:1].upper() + name[1:]) if name else prefix


def _tokens(url: str) -> set[str]:
    segs, hash_segs = _segments(url)
    toks: set[str] = set()
    for s in segs + hash_segs:
        s = s.lower()
        toks.add(s)
        toks.update(t for t in re.split(r"[-_.]", s) if t)
        if "." in s:
            toks.add(s.rsplit(".", 1)[0])
    return toks


def classify_page(page: PageResult) -> str:
    if page.error or (page.status is not None and page.status >= 400):
        return "error"
    url = page.final_url or page.url
    segs, hash_segs = _segments(url)
    toks = _tokens(url)
    title = (page.title or "").lower()
    h1 = " ".join(h.text.lower() for h in page.headings if h.level == 1)
    text_title = f"{title} {h1}"
    ld = {t.lower() for t in page.json_ld_types}
    og_type = (page.og.get("og:type") or page.og.get("type") or "").lower()
    kinds = {f.kind for f in page.forms}

    try:
        query = parse_qs(urlparse(url).query)
    except ValueError:
        query = {}

    # Página protegida: redirigió a un login (ej. /panel → /?login=1&next=/panel)
    if page.redirect_chain and page.final_url and page.final_url != page.url \
            and _LOGIN_REDIRECT.search(page.final_url):
        return "auth"
    if not segs and not hash_segs and not query.get("q") and not query.get("s"):
        return "home"
    if kinds & {"login", "register", "password_reset"} and len(page.forms) <= 3:
        return "auth"
    if query.get("q") or query.get("s") or query.get("search"):
        if "search" in kinds or not toks - {"search", "buscar"}:
            return "busqueda"
    if ld & _PRODUCT_LD or og_type.startswith("product"):
        return "producto"
    if ld & _ARTICLE_LD or og_type == "article":
        return "blog/articulo"
    for ptype, url_kw, title_kw in _RULES:
        if ptype == "producto" and "p" in url_kw:
            # 'p' y 'dp' solo cuentan como primer segmento
            if segs and segs[0].lower() in ("p", "dp") and len(segs) > 1:
                return ptype
            if toks & (set(url_kw) - {"p", "dp"}):
                return ptype
            continue
        if ptype == "categoria/listado" and "page" in toks and not (toks & (set(url_kw) - {"page"})):
            continue
        if toks & set(url_kw):
            return ptype
    for ptype, _, title_kw in _RULES:
        if title_kw and any(k in text_title for k in title_kw):
            return ptype
    if "contact" in kinds:
        return "contacto"
    if "search" in kinds and len(page.forms) == 1 and page.word_count < 100:
        return "busqueda"
    return "other"


def build_areas(pages: list[PageResult]) -> list[AreaInfo]:
    groups: dict[str, list[PageResult]] = defaultdict(list)
    for p in pages:
        groups[p.area if p.area and p.area != "/" or not p.url else area_of(p.final_url or p.url)].append(p)

    nav_areas: set[str] = set()
    for p in pages:
        for link in p.links:
            if link.in_nav and link.internal:
                nav_areas.add(area_of(link.url))

    areas: list[AreaInfo] = []
    for prefix, items in groups.items():
        types = Counter(p.page_type for p in items)
        samples = []
        for p in sorted(items, key=lambda x: (x.depth, len(x.url))):
            if p.url not in samples:
                samples.append(p.url)
            if len(samples) >= 5:
                break
        areas.append(AreaInfo(
            name=_area_name(prefix),
            path_prefix=prefix,
            pages=len(items),
            page_types=dict(types.most_common()),
            sample_urls=samples,
            in_nav=prefix in nav_areas,
        ))
    areas.sort(key=lambda a: (a.path_prefix != "/", -a.pages, a.path_prefix))
    return areas


def _norm_link(url: str) -> str:
    return url.split("#")[0].rstrip("/") if not re.search(r"#!?/", url) else url.rstrip("/")


def nav_menu(pages: list[PageResult]) -> list[LinkInfo]:
    counts: Counter[str] = Counter()
    first: dict[str, LinkInfo] = {}
    order: dict[str, int] = {}
    for p in pages:
        seen_here: set[str] = set()
        for link in p.links:
            if not link.in_nav or not link.url:
                continue
            key = _norm_link(link.url)
            if key in seen_here:
                continue
            seen_here.add(key)
            counts[key] += 1
            if key not in first or (not first[key].text and link.text):
                first[key] = link
            order.setdefault(key, len(order))
    ranked = sorted(counts, key=lambda k: (-counts[k], order[k]))[:30]
    ranked.sort(key=lambda k: order[k])
    return [first[k] for k in ranked]


_ECOMMERCE_TECH = ("shopify", "woocommerce", "magento", "prestashop", "bigcommerce", "vtex", "opencart",
                   "salesforce commerce", "wix stores", "ecwid", "tiendanube", "nuvemshop", "jumpseller",
                   "shopware", "squarespace commerce")
_DOCS_TECH = ("docusaurus", "gitbook", "mkdocs", "read the docs", "sphinx", "vitepress", "mintlify",
              "readme.io", "nextra", "starlight")
_FORUM_TECH = ("discourse", "phpbb", "vbulletin", "xenforo", "flarum", "nodebb")
_LMS_TECH = ("moodle", "canvas lms", "teachable", "thinkific", "kajabi", "learndash")
_LMS_WORDS = re.compile(
    r"\b(learning platform|online learning|e-?learning|lms|cursos?|courses?|aprende|aprender|learn|"
    r"programas?|clases|lessons?|lecciones|bootcamps?|cohortes?|diplomados?|capacitaci[oó]n|"
    r"academ(?:y|ia)|estudiantes|students|retos|workshops?|talleres)\b", re.I)
_LOGIN_REDIRECT = re.compile(r"log-?in|sign-?in|/auth(?:$|[/?#_-]|entica|oriz)|iniciar|acceso", re.I)


def _lms_signals(pages: list[PageResult]) -> int:
    """Palabras de formación en títulos, descripciones, encabezados y rutas de las primeras páginas."""
    found: set[str] = set()
    for p in pages[:40]:
        text = " ".join([p.title, p.meta_description, p.url] + [h.text for h in p.headings if h.level <= 2])
        found.update(m.lower() for m in _LMS_WORDS.findall(text))
    return len(found)


def detect_site_type(pages: list[PageResult], technologies: list[TechHit], forms: list[FormInfo]) -> str:
    ok = [p for p in pages if not p.error and (p.status is None or p.status < 400)]
    n = max(1, len(ok))
    types = Counter(p.page_type for p in ok)
    tech_names = " | ".join(f"{t.name} {t.category}".lower() for t in technologies)
    kinds = Counter(f.kind for f in forms)

    def share(*names: str) -> float:
        return sum(types[t] for t in names) / n

    ecommerce_tech = any(k in tech_names for k in _ECOMMERCE_TECH) or "ecommerce" in tech_names \
        or "e-commerce" in tech_names
    if ecommerce_tech or kinds["add_to_cart"] or kinds["payment"] \
            or (share("producto", "carrito/checkout") >= 0.2 and types["producto"] >= 2) \
            or types["carrito/checkout"] and types["producto"]:
        return "E-commerce / Tienda en línea"
    if any(k in tech_names for k in _FORUM_TECH):
        return "Foro / Comunidad"
    if any(k in tech_names for k in _LMS_TECH) or _lms_signals(ok) >= 4:
        return "Plataforma educativa (LMS)"
    if any(k in tech_names for k in _DOCS_TECH) or share("documentacion") >= 0.3:
        return "Sitio de documentación"

    has_auth = bool(kinds["login"] or kinds["register"] or types["auth"])
    spa = any(p.spa_suspected for p in ok)  # renderizar con Chromium no convierte un sitio en SPA
    api_heavy = sum(len(p.api_calls) for p in ok) >= 5
    if (has_auth and (spa or api_heavy or types["dashboard"] or types["precios"])) \
            or (spa and len(ok) <= 5 and has_auth):
        return "Aplicación web / SaaS"
    if share("blog/articulo") >= 0.3 or "wordpress" in tech_names and types["blog/articulo"] >= 3:
        return "Blog / Medio de noticias"
    if len(ok) <= 3:
        if has_auth:
            return "Aplicación web / SaaS"
        return "Landing page / Sitio de una página"
    if types["precios"] and (has_auth or spa):
        return "Aplicación web / SaaS"
    if types["documentacion"] >= 3:
        return "Sitio de documentación"
    return "Sitio corporativo / Institucional"
