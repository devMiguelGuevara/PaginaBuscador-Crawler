"""Normalización y alcance de URLs."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|_ga|_gl|ref_src|igshid)$", re.I)

NON_HTML_EXT = re.compile(
    r"\.(png|jpe?g|gif|webp|avif|svg|ico|bmp|tiff?|pdf|docx?|xlsx?|pptx?|odt|csv|zip|rar|7z|gz|tar|"
    r"mp3|mp4|m4a|wav|ogg|webm|mov|avi|mkv|css|js|mjs|map|json|xml|txt|woff2?|ttf|otf|eot|exe|dmg|apk|msi)$",
    re.I,
)

# Sufijos de segundo nivel comunes (para obtener el dominio registrable sin dependencias)
_SECOND_LEVEL = {
    "com", "net", "org", "gob", "gov", "edu", "co", "ac", "mil", "nom", "info", "biz",
}


def normalize(url: str, base: str | None = None) -> str | None:
    """Devuelve la URL absoluta normalizada o None si no es http(s)."""
    if not url:
        return None
    url = url.strip()
    if url.startswith(("javascript:", "mailto:", "tel:", "data:", "sms:", "whatsapp:", "blob:")):
        return None
    if base:
        url = urljoin(base, url)
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower().rstrip(".")
    port = parts.port
    netloc = host
    if port and not ((parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not TRACKING_PARAMS.match(k)))
    # Conserva rutas hash de SPAs (#/ruta o #!/ruta); descarta anclas normales
    frag = parts.fragment if parts.fragment.startswith(("/", "!/")) else ""
    return urlunsplit((parts.scheme.lower(), netloc, path, query, frag))


def registrable_domain(host: str) -> str:
    host = (host or "").lower().split(":")[0]
    labels = host.split(".")
    if len(labels) <= 2 or re.fullmatch(r"[\d.]+", host):
        return host
    if labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


class Scope:
    """Decide qué URLs pertenecen al sitio rastreado."""

    def __init__(self, start_url: str, include_subdomains: bool = False):
        self.start_url = start_url
        self.host = host_of(start_url)
        self.base_host = self.host[4:] if self.host.startswith("www.") else self.host
        self.root = registrable_domain(self.host)
        self.include_subdomains = include_subdomains

    def is_internal(self, url: str) -> bool:
        h = host_of(url)
        if not h:
            return False
        bare = h[4:] if h.startswith("www.") else h
        if bare == self.base_host:
            return True
        if self.include_subdomains:
            return h == self.root or h.endswith("." + self.root)
        return False

    def is_same_site(self, url: str) -> bool:
        """Mismo dominio registrable (útil para clasificar recursos de terceros)."""
        h = host_of(url)
        return bool(h) and (h == self.root or h.endswith("." + self.root))

    def should_crawl(self, url: str) -> bool:
        if not self.is_internal(url):
            return False
        path = urlsplit(url).path
        return not NON_HTML_EXT.search(path)
