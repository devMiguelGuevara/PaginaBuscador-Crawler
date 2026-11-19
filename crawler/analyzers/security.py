"""Análisis de seguridad PASIVO: solo usa las respuestas ya obtenidas durante el rastreo."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from ..models import PageResult

SECURITY_HEADERS: dict[str, tuple[str, str]] = {
    "strict-transport-security": ("alta", "HSTS: obliga al navegador a usar siempre HTTPS"),
    "content-security-policy": ("media", "CSP: limita el origen de scripts y mitiga XSS"),
    "x-frame-options": ("media", "Protege contra clickjacking (o frame-ancestors en CSP)"),
    "x-content-type-options": ("baja", "Evita que el navegador adivine tipos MIME (nosniff)"),
    "referrer-policy": ("baja", "Controla qué información de origen se envía a otros sitios"),
    "permissions-policy": ("baja", "Restringe APIs del navegador (cámara, micrófono, geolocalización)"),
    "cross-origin-opener-policy": ("baja", "Aísla el contexto de navegación frente a otros orígenes"),
}

_PENALTY = {"alta": 15, "media": 8, "baja": 3}
_VERSION_RE = re.compile(r"\d+\.\d+")


def _issue(issues: list, severity: str, message: str, urls: list[str] | None = None) -> None:
    issues.append({"severity": severity, "message": message, "urls": (urls or [])[:50]})


def _https(url: str) -> bool:
    return url.lower().startswith("https://")


def site_security(pages: list[PageResult], target: str) -> dict:
    issues: list[dict] = []
    ok = [p for p in pages if p.status is not None and not p.error]
    main = next((p for p in ok if p.depth == 0), ok[0] if ok else None)
    main_url = (main.final_url or main.url) if main else target
    https = _https(main_url)

    if not https:
        _issue(issues, "alta", "El sitio no usa HTTPS: la información viaja sin cifrar", [main_url])
    redirect_to_https = any(
        (p.redirect_chain and p.redirect_chain[0].lower().startswith("http://") and _https(p.final_url or ""))
        for p in pages
    ) or (target.lower().startswith("http://") and https)
    downgraded = [p.url for p in pages
                  if _https(p.url) and (p.final_url or "").lower().startswith("http://")]
    if downgraded:
        _issue(issues, "alta", f"{len(downgraded)} URL(s) HTTPS redirigen a HTTP "
                               "(rebaja de protocolo: el tráfico viaja sin cifrar)", downgraded)

    # Cabeceras de la página principal (y presencia en el resto)
    main_headers = {k.lower(): v for k, v in (main.headers if main else {}).items()}
    headers: dict[str, str | None] = {}
    missing: list[str] = []
    for name, (sev, desc) in SECURITY_HEADERS.items():
        val = main_headers.get(name)
        if name == "x-frame-options" and not val and "frame-ancestors" in main_headers.get("content-security-policy", ""):
            val = "(vía CSP frame-ancestors)"
        if name == "strict-transport-security" and not https:
            headers[name] = val
            continue
        headers[name] = val
        if not val:
            missing.append(name)
            _issue(issues, sev, f"Falta la cabecera {name} — {desc}", [main_url])

    # Revelación de versiones
    disclosed = set()
    for p in ok:
        h = {k.lower(): v for k, v in p.headers.items()}
        for name in ("server", "x-powered-by", "x-aspnet-version", "x-aspnetmvc-version", "x-generator"):
            val = h.get(name, "")
            if val and (_VERSION_RE.search(val) or name.startswith("x-aspnet")):
                disclosed.add(f"{name}: {val}")
    if disclosed:
        _issue(issues, "baja", "El servidor revela versiones de software: " + "; ".join(sorted(disclosed)[:5]))

    # CORS abierto
    cors = sorted({p.url for p in ok if p.headers and
                   {k.lower(): v for k, v in p.headers.items()}.get("access-control-allow-origin") == "*"})
    if cors:
        _issue(issues, "baja", "CORS abierto (Access-Control-Allow-Origin: *)", cors)

    # Cookies
    cookie_issues: list[str] = []
    seen_cookies: set[str] = set()
    for p in pages:
        for c in p.cookies:
            if c.name in seen_cookies:
                continue
            seen_cookies.add(c.name)
            problems = []
            if https and not c.secure:
                problems.append("sin Secure")
            if not c.http_only and c.auth_hint:
                problems.append("sin HttpOnly")
            if not c.same_site:
                problems.append("sin SameSite")
            if problems:
                label = "de sesión " if c.auth_hint else ""
                cookie_issues.append(f"Cookie {label}'{c.name}': {', '.join(problems)}")
                sev = "alta" if c.auth_hint and ("sin HttpOnly" in problems or "sin Secure" in problems) else "baja"
                _issue(issues, sev, f"Cookie {label}'{c.name}' {', '.join(problems)}", [p.url])

    # Mixed content
    mixed: list[str] = []
    for p in ok:
        if not _https(p.final_url or p.url):
            continue
        for res in list(p.scripts) + list(p.stylesheets) + list(p.iframes):
            if res.lower().startswith("http://") and res not in mixed:
                mixed.append(res)
    if mixed:
        _issue(issues, "media", "Contenido mixto: recursos cargados por HTTP en páginas HTTPS", mixed)

    # Formularios
    insecure_forms: list[str] = []
    login_no_csrf: list[str] = []
    for p in ok:
        for f in p.forms:
            action = f.action or ""
            if action.lower().startswith("http://") or (not https and f.kind in ("login", "register", "payment")):
                insecure_forms.append(p.url)
            if f.kind in ("login", "register", "password_reset") and not f.has_csrf and f.method.upper() == "POST":
                login_no_csrf.append(p.url)
    if insecure_forms:
        _issue(issues, "alta", "Formularios que envían datos sin cifrar (HTTP)", sorted(set(insecure_forms)))
    if login_no_csrf:
        _issue(issues, "media", "Formularios de acceso/registro sin token CSRF visible", sorted(set(login_no_csrf)))

    # Enlaces target=_blank / iframes de terceros no se evalúan (requiere más contexto)

    score = 100
    for iss in issues:
        score -= _PENALTY[iss["severity"]]
    score = max(0, min(100, score))
    order = {"alta": 0, "media": 1, "baja": 2}
    issues.sort(key=lambda i: order[i["severity"]])

    return {
        "score": score,
        "https": https,
        "redirect_to_https": redirect_to_https,
        "headers": headers,
        "missing_headers": missing,
        "version_disclosure": sorted(disclosed),
        "cookie_issues": cookie_issues,
        "mixed_content": mixed[:50],
        "issues": issues,
        "host": urlparse(main_url).hostname or "",
    }
