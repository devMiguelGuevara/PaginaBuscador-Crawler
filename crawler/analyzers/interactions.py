"""Cómo interactúa el sitio: CTAs, búsqueda, modales, widgets, analítica, APIs y terceros."""
from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse, urlunparse

from ..models import ApiCall, PageResult

_CTA_WORDS = re.compile(
    r"\b(comprar|compra|agregar|añadir|reservar|registr|suscr|empez|comenz|prueba|probar|solicit|"
    r"contact|descarg|cotiz|agenda|pedir|ordenar|únete|unete|ingresa|inicia|crear cuenta|ver más|"
    r"saber más|más información|demo|free trial|sign ?up|get started|start|try|buy|shop|add to cart|"
    r"subscribe|download|book|request|contact us|learn more|join|order|checkout|pagar|donar|donate)",
    re.I,
)
_CTA_CLASS = re.compile(r"(?:^|[\s_-])(btn|button|cta|call-to-action)(?:$|[\s_-])", re.I)

CHAT_WIDGETS: dict[str, tuple[str, ...]] = {
    "Intercom": ("widget.intercom.io", "js.intercomcdn.com", "intercomsettings"),
    "Crisp": ("client.crisp.chat", "$crisp"),
    "Drift": ("js.driftt.com", "drift.com/"),
    "Tawk.to": ("embed.tawk.to",),
    "Zendesk Chat": ("static.zdassets.com", "zopim", "zendesk.com/embeddable"),
    "HubSpot Chat": ("js.usemessages.com", "hs-scripts.com", "hubspot-messages"),
    "WhatsApp": ("wa.me/", "api.whatsapp.com", "web.whatsapp.com/send"),
    "Tidio": ("code.tidio.co",),
    "LiveChat": ("cdn.livechatinc.com",),
    "Facebook Messenger": ("connect.facebook.net/es_la/sdk/xfbml.customerchat", "fb-customerchat", "m.me/"),
    "Freshchat": ("wchat.freshchat.com", "freshworks"),
    "Olark": ("static.olark.com",),
    "JivoChat": ("code.jivosite.com", "jivo"),
    "Chatwoot": ("chatwoot",),
}

ANALYTICS: dict[str, tuple[str, ...]] = {
    "Google Analytics": ("google-analytics.com", "gtag(", "googletagmanager.com/gtag/js", "ga('create'"),
    "Google Tag Manager": ("googletagmanager.com/gtm.js", "gtm-"),
    "Meta Pixel": ("connect.facebook.net/en_us/fbevents.js", "fbevents.js", "fbq("),
    "Hotjar": ("static.hotjar.com", "hotjar"),
    "Microsoft Clarity": ("clarity.ms",),
    "Segment": ("cdn.segment.com", "analytics.load("),
    "Mixpanel": ("cdn.mxpnl.com", "mixpanel"),
    "PostHog": ("posthog",),
    "Amplitude": ("cdn.amplitude.com", "amplitude.getinstance", "api2.amplitude.com"),
    "LinkedIn Insight": ("snap.licdn.com", "_linkedin_partner_id"),
    "TikTok Pixel": ("analytics.tiktok.com", "ttq.load"),
    "Heap": ("cdn.heapanalytics.com", "heap.load"),
    "Matomo": ("matomo.js", "piwik.js", "_paq.push"),
    "Plausible": ("plausible.io/js",),
    "Yandex Metrica": ("mc.yandex.ru",),
    "Twitter/X Pixel": ("static.ads-twitter.com",),
    "Sentry": ("browser.sentry-cdn.com", "sentry.io", "sentry"),
    "Datadog RUM": ("datadoghq", "dd_rum"),
    "FullStory": ("fullstory.com",),
    "Vercel Analytics": ("/_vercel/insights", "va.vercel-scripts.com"),
    "Cloudflare Web Analytics": ("static.cloudflareinsights.com",),
}

SOCIAL: dict[str, tuple[str, ...]] = {
    "Facebook": ("facebook.com/",), "Instagram": ("instagram.com/",), "X / Twitter": ("twitter.com/", "x.com/"),
    "LinkedIn": ("linkedin.com/company", "linkedin.com/in/", "linkedin.com/school"),
    "YouTube": ("youtube.com/@", "youtube.com/c/", "youtube.com/channel", "youtube.com/user"),
    "TikTok": ("tiktok.com/@",), "Pinterest": ("pinterest.com/", "pinterest.com.mx/"),
    "GitHub": ("github.com/",), "Discord": ("discord.gg/", "discord.com/invite"),
    "Telegram": ("t.me/",), "Threads": ("threads.net/",),
}

COOKIE_BANNERS: dict[str, tuple[str, ...]] = {
    "Cookiebot": ("consent.cookiebot.com", "cookiebot"),
    "OneTrust": ("cdn.cookielaw.org", "onetrust", "optanon"),
    "CookieYes": ("cookieyes", "cdn-cookieyes.com"),
    "Osano": ("osano.com", "osano"),
    "Complianz": ("complianz",),
    "Iubenda": ("iubenda.com",),
    "Usercentrics": ("usercentrics",),
    "TrustArc": ("trustarc", "truste.com"),
    "Termly": ("termly.io",),
    "Didomi": ("didomi",),
    "Quantcast Choice": ("quantcast.mgr.consensu.org", "quantcast"),
}

_DOWNLOAD_EXT = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|zip|rar|7z|csv|apk|dmg|exe|msi|epub)(?:$|\?)", re.I)
_EVENT_ATTRS = ("onclick", "onsubmit", "onchange", "oninput", "onmouseover", "onkeyup", "onkeydown",
                "onload", "onfocus", "onblur")


def _clean(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _base_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("com", "co", "org", "net", "gob", "gov", "edu", "ac"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _match_any(haystack: str, table: dict[str, tuple[str, ...]]) -> list[str]:
    return [name for name, needles in table.items() if any(n in haystack for n in needles)]


def _haystack(page: PageResult) -> str:
    parts = [page.html or "", " ".join(page.scripts), " ".join(page.iframes), " ".join(page.stylesheets),
             " ".join(a.url for a in page.api_calls), " ".join(page.js_globals)]
    return "\n".join(parts).lower()


# --------------------------------------------------------------------------- por página

def page_interactions(page: PageResult, tree) -> dict:
    hay = _haystack(page)
    links_blob = " ".join(link.url.lower() for link in page.links)

    ctas: list[str] = []
    modals = 0
    event_handlers = 0
    search = any(f.kind == "search" for f in page.forms)
    video: list[str] = []
    maps = False

    if tree is not None:
        try:
            for node in tree.css("button, a, input[type=submit], input[type=button], [role=button]"):
                attrs = node.attributes
                text = _clean(node.text(deep=True, separator=" ") if node.tag != "input" else (attrs.get("value") or ""))
                if not text or len(text) < 2:
                    text = _clean(attrs.get("aria-label") or "")
                if not text:
                    continue
                cls = attrs.get("class") or ""
                is_cta = bool(_CTA_CLASS.search(cls)) or (node.tag != "a" and bool(_CTA_WORDS.search(text))) \
                    or (node.tag == "a" and bool(_CTA_WORDS.search(text)) and len(text) <= 40)
                if is_cta and text not in ctas:
                    ctas.append(text)
                if len(ctas) >= 15:
                    break
            modals = len(tree.css("dialog, [role=dialog], [role=alertdialog], .modal, [data-bs-toggle=modal], "
                                  "[data-toggle=modal], [aria-modal=true]"))
            for attr in _EVENT_ATTRS:
                event_handlers += len(tree.css(f"[{attr}]"))
            if tree.css_first("input[type=search], [role=search], input[name=q], input[name=s], "
                              "input[name=search], input[name=query]"):
                search = True
            if tree.css_first("video"):
                video.append("Video HTML5")
            if tree.css_first("audio"):
                video.append("Audio HTML5")
        except Exception:
            pass

    if "youtube.com/embed" in hay or "youtube-nocookie.com" in hay or "youtu.be/" in hay:
        video.append("YouTube")
    if "player.vimeo.com" in hay:
        video.append("Vimeo")
    if "fast.wistia" in hay:
        video.append("Wistia")
    if "maps.googleapis.com" in hay or "google.com/maps" in hay or "maps.google." in hay:
        maps = True
    if "api.mapbox.com" in hay or "leaflet" in hay or "openstreetmap" in hay:
        maps = True

    chat = _match_any(hay + " " + links_blob, CHAT_WIDGETS)
    analytics = _match_any(hay, ANALYTICS)
    social = _match_any(links_blob, SOCIAL)
    cookie_tools = _match_any(hay, COOKIE_BANNERS)
    cookie_banner = bool(cookie_tools) or bool(
        re.search(r"(usamos|utilizamos|we use)\s+cookies|aceptar (todas las )?cookies|accept (all )?cookies|"
                  r"cookie-banner|cookie-consent|cookie_notice|cookie-notice", hay)
    )
    downloads = []
    for link in page.links:
        if _DOWNLOAD_EXT.search(link.url) and link.url not in downloads:
            downloads.append(link.url)

    websockets = [a.url for a in page.api_calls if a.resource_type == "websocket"]
    graphql = any(a.graphql for a in page.api_calls)

    return {
        "ctas": ctas,
        "search": search,
        "modals": modals,
        "event_handlers": event_handlers,
        "chat_widgets": chat,
        "analytics": analytics,
        "social": social,
        "video": _dedup(video),
        "maps": maps,
        "cookie_banner": cookie_banner,
        "cookie_tools": cookie_tools,
        "downloads": downloads[:20],
        "websockets": websockets,
        "graphql": graphql,
    }


# --------------------------------------------------------------------------- sitio

def site_interactions(pages: list[PageResult]) -> dict:
    ctas: Counter[str] = Counter()
    lists: dict[str, list[str]] = {k: [] for k in ("chat_widgets", "analytics", "social", "video", "downloads",
                                                    "websockets", "cookie_tools")}
    search = cookie_banner = graphql = maps = False
    modals = event_handlers = 0
    third: Counter[str] = Counter()
    forms_by_kind: Counter[str] = Counter()

    site_hosts = {_base_domain(_host(p.final_url or p.url)) for p in pages[:1]}
    for p in pages:
        inter = p.interactions or {}
        ctas.update(inter.get("ctas", []))
        for key in lists:
            for item in inter.get(key, []) or []:
                if item not in lists[key]:
                    lists[key].append(item)
        search = search or bool(inter.get("search"))
        cookie_banner = cookie_banner or bool(inter.get("cookie_banner"))
        graphql = graphql or bool(inter.get("graphql")) or any(a.graphql for a in p.api_calls)
        maps = maps or bool(inter.get("maps"))
        modals += int(inter.get("modals", 0) or 0)
        event_handlers += int(inter.get("event_handlers", 0) or 0)
        for a in p.api_calls:
            if a.resource_type == "websocket" and a.url not in lists["websockets"]:
                lists["websockets"].append(a.url)
        for f in p.forms:
            forms_by_kind[f.kind] += 1
        for url in list(p.scripts) + list(p.iframes) + list(p.stylesheets) + [a.url for a in p.api_calls]:
            h = _host(url)
            if h and _base_domain(h) not in site_hosts:
                third[h] += 1

    return {
        "ctas": [c for c, _ in ctas.most_common(25)],
        "search": search,
        "cookie_banner": cookie_banner,
        "modals": modals,
        "event_handlers": event_handlers,
        "graphql": graphql,
        "maps": maps,
        "third_party_services": [h for h, _ in third.most_common(40)],
        "third_party_counts": dict(third.most_common(40)),
        "forms_by_kind": dict(forms_by_kind),
        **lists,
    }


def _strip_query(url: str) -> str:
    try:
        p = urlparse(url)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except ValueError:
        return url


_ID_SEGMENT = re.compile(
    r"^(\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{12,}|eyJ[\w-]+|[\w-]{24,})$",
    re.I)
MAX_ENDPOINTS_PER_HOST = 25


def _endpoint_pattern(url: str) -> str:
    """URL sin query y con segmentos-ID sustituidos por {id} (agrupa /users/123 y /users/456)."""
    base = _strip_query(url)
    m = re.match(r"^(\w+://[^/]+)(/.*)?$", base)
    if not m:
        return base
    path = "/".join("{id}" if _ID_SEGMENT.match(s) else s for s in (m.group(2) or "/").split("/"))
    return m.group(1) + path


def collect_api_endpoints(pages: list[PageResult]) -> list[ApiCall]:
    seen: dict[tuple[str, str], ApiCall] = {}
    per_host: Counter[str] = Counter()
    for p in pages:
        for a in p.api_calls:
            pattern = a.url if a.resource_type == "websocket" else _endpoint_pattern(a.url)
            key = (a.method.upper(), pattern)
            if key in seen:
                continue
            host = re.sub(r"^\w+://([^/]+).*$", r"\1", pattern)
            if per_host[host] >= MAX_ENDPOINTS_PER_HOST:
                continue
            per_host[host] += 1
            seen[key] = a.model_copy(update={"url": pattern, "page_url": a.page_url or p.url})
    return sorted(seen.values(), key=lambda a: (a.third_party, a.url, a.method))


def _dedup(items) -> list[str]:
    out: list[str] = []
    for i in items:
        if i and i not in out:
            out.append(i)
    return out
