"""Detección pasiva de login, registro, sesiones y áreas de usuario."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..models import AuthFinding, LinkInfo, PageResult
from .tech import could_match, prefilter

PATH_RULES: list[tuple[str, re.Pattern, str]] = [
    ("password_reset", re.compile(r"/(forgot|reset|recover|olvid|recuperar|restablecer)[\w\-]*", re.I),
     "Página de recuperación de contraseña"),
    ("register_page", re.compile(r"/(register|registro|registrarse|signup|sign-up|sign_up|join|crear-cuenta|"
                                 r"create-account)(/|$|\?|\.)|[?&](register|registro|signup|sign_up)=", re.I),
     "Página de registro"),
    ("login_page", re.compile(r"/(login|log-in|signin|sign-in|sign_in|iniciar-sesion|ingresar|acceder|"
                              r"entrar|auth|authenticate|session/new|users/sign_in|wp-login\.php)(/|$|\?|\.)|"
                              r"[?&](login|signin|sign_in|auth)=", re.I), "Página de inicio de sesión"),
    ("logout", re.compile(r"/(logout|log-out|signout|sign-out|cerrar-sesion|salir)(/|$|\?|\.)", re.I),
     "Enlace de cierre de sesión"),
    ("admin_area", re.compile(r"/(admin|administrator|wp-admin|backoffice|panel|cpanel|manage|staff)(/|$|\?|\.)",
                              re.I), "Área de administración"),
    ("account_area", re.compile(r"/(account|accounts|cuenta|mi-cuenta|my-account|perfil|profile|dashboard|"
                                r"settings|configuracion|me|user|users|usuario|orders|pedidos)(/|$|\?|\.)", re.I),
     "Área de cuenta de usuario"),
]
LOGIN_URL_RE = re.compile(r"(^|[/?&=_.\-])(login|log-in|signin|sign-in|sign_in|iniciar-sesion|ingresar|acceder|"
                          r"auth|authenticate|session|sessions)([/?&=_.\-#]|$)", re.I)
REGISTER_URL_RE = re.compile(r"(^|[/?&=_.\-])(register|registro|registrarse|signup|sign-up|sign_up|join|"
                             r"crear-cuenta|create-account)([/?&=_.\-#]|$)", re.I)

# Enlaces/botones que llevan al login o registro (no convierten la página actual en página de login)
ENTRY_LABELS = {"login_entry": "Acceso a login desde la navegación",
                "register_entry": "Acceso a registro desde la navegación"}
BUTTON_LABELS = {"login_entry": "Botón de inicio de sesión", "register_entry": "Botón de registro"}
SITE_WIDE_KINDS = {"session_cookie", "jwt_storage", "sso_provider", "auth_service", "captcha", "mfa_hint"}

TEXT_RULES: list[tuple[str, re.Pattern, str]] = [
    ("login_entry", re.compile(r"^(iniciar sesi[oó]n|inicia sesi[oó]n|log ?in|sign ?in|ingresar|acceder|entrar|"
                               r"mi cuenta|my account|login)$", re.I), ENTRY_LABELS["login_entry"]),
    ("register_entry", re.compile(r"^(reg[ií]strate|registrarse|registro|sign ?up|crear cuenta|create account|"
                                  r"join( now)?|[uú]nete|get started|empieza gratis|start free( trial)?)$", re.I),
     ENTRY_LABELS["register_entry"]),
    ("password_reset", re.compile(r"(olvid[ée] (mi|la|tu) contrase[nñ]a|forgot( your)? password|"
                                  r"recuperar contrase[nñ]a|reset password)", re.I),
     "Enlace de recuperación de contraseña"),
    ("logout", re.compile(r"^(cerrar sesi[oó]n|log ?out|sign ?out|salir)$", re.I), "Cierre de sesión"),
]

SSO_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Google", re.compile(r"accounts\.google\.com|apis\.google\.com/js/platform|gsi/client|"
                          r"continu\w+ (con|with) google|sign in with google|iniciar sesi[oó]n con google", re.I)),
    ("Microsoft", re.compile(r"login\.microsoftonline\.com|login\.live\.com|msal|"
                             r"(con|with) microsoft", re.I)),
    ("Facebook", re.compile(r"facebook\.com/[\w./]*dialog/oauth|connect\.facebook\.net/[\w_]+/sdk\.js|"
                            r"(con|with) facebook", re.I)),
    ("Apple", re.compile(r"appleid\.apple\.com|appleid\.cdn-apple\.com|(con|with) apple", re.I)),
    ("GitHub", re.compile(r"github\.com/login/oauth|(con|with) github", re.I)),
    ("LinkedIn", re.compile(r"linkedin\.com/oauth|(con|with) linkedin", re.I)),
    ("X / Twitter", re.compile(r"api\.twitter\.com/oauth|twitter\.com/i/oauth2", re.I)),
]
AUTH_SERVICES: list[tuple[str, re.Pattern]] = [
    ("Auth0", re.compile(r"[\w\-]+\.auth0\.com|cdn\.auth0\.com|auth0-spa-js|@auth0", re.I)),
    ("Okta", re.compile(r"[\w\-]+\.okta(preview)?\.com|okta-signin-widget|okta-auth-js", re.I)),
    ("Amazon Cognito", re.compile(r"cognito-idp\.[\w\-]+\.amazonaws\.com|amazoncognito\.com|"
                                  r"CognitoIdentityServiceProvider", re.I)),
    ("Firebase Auth", re.compile(r"identitytoolkit\.googleapis\.com|securetoken\.googleapis\.com|"
                                 r"firebaseauth|firebase-auth|__/auth/handler|firebase:authUser", re.I)),
    ("Keycloak", re.compile(r"/realms/[\w\-]+/protocol/openid-connect|keycloak(\.min)?\.js", re.I)),
    ("Clerk", re.compile(r"clerk\.[\w\-.]+|@clerk/|clerk\.accounts\.dev|__clerk", re.I)),
    ("Supabase Auth", re.compile(r"[\w\-]+\.supabase\.co/auth/v1|sb-[\w\-]+-auth-token|supabase\.auth", re.I)),
    ("Magic", re.compile(r"auth\.magic\.link|magic-sdk", re.I)),
    ("NextAuth / Auth.js", re.compile(r"/api/auth/(session|csrf|providers|signin)|next-auth\.", re.I)),
    ("Passport.js", re.compile(r"passport-(local|google|facebook)", re.I)),
    ("WorkOS", re.compile(r"api\.workos\.com|authkit", re.I)),
    ("Stytch", re.compile(r"stytch\.com", re.I)),
    ("OneLogin", re.compile(r"onelogin\.com", re.I)),
    ("Azure AD B2C", re.compile(r"b2clogin\.com", re.I)),
]
SESSION_COOKIE_RE = re.compile(
    r"^(phpsessid|jsessionid|asp\.net_sessionid|\.aspnetcore\.(session|cookies|identity\.application)|"
    r"connect\.sid|laravel_session|sessionid|session|_session|[\w\-]*_session|sess|sid|"
    r"next-auth\.session-token|__secure-next-auth\.session-token|next-auth\.csrf-token|"
    r"__session|sb-[\w\-]+-auth-token|wordpress_logged_in_\w*|wordpress_sec_\w*|_shopify_s|"
    r"ci_session|rack\.session|express\.sid|auth_token|access_token|refresh_token|token|jwt|"
    r"remember_[\w\-]+|__host-[\w\-]+)$", re.I)
STORAGE_TOKEN_RE = re.compile(
    r"token|jwt|access[_\-]?token|refresh[_\-]?token|id[_\-]?token|auth|session|supabase|firebase:authuser|"
    r"@@auth0spajs@@|okta-token-storage|msal\.|cognito|clerk|user", re.I)
MFA_RE = re.compile(r"\b(2fa|mfa|otp|totp|two[\- ]factor|authenticator|verificaci[oó]n en dos pasos|"
                    r"doble factor|c[oó]digo de verificaci[oó]n|verification code|one[\- ]time (password|code))\b",
                    re.I)
AUTH_API_RE = re.compile(r"/(auth|login|logout|signin|signup|register|token|oauth2?|session|sessions|me|"
                         r"user|users|account|refresh|verify|otp|mfa)(/|$|\?)", re.I)

FEATURE_RULES: list[tuple[str, re.Pattern]] = [
    ("Perfil de usuario", re.compile(r"perfil|profile|mi cuenta|my account|/account|/cuenta", re.I)),
    ("Carrito de compras", re.compile(r"carrito|cart|basket|cesta|bolsa de compra", re.I)),
    ("Lista de deseos / favoritos", re.compile(r"favoritos|wishlist|wish list|favorites|guardados", re.I)),
    ("Historial de pedidos", re.compile(r"mis pedidos|my orders|order history|/orders|/pedidos|mis compras", re.I)),
    ("Notificaciones", re.compile(r"notificaciones|notifications", re.I)),
    ("Configuración de cuenta", re.compile(r"configuraci[oó]n|settings|preferencias|preferences", re.I)),
    ("Panel / dashboard", re.compile(r"dashboard|panel de control|/panel|/app/", re.I)),
    ("Mensajería", re.compile(r"mensajes|messages|inbox|bandeja", re.I)),
    ("Suscripción / planes", re.compile(r"suscripci[oó]n|subscription|billing|facturaci[oó]n|planes|pricing|precios",
                                        re.I)),
    ("Direcciones guardadas", re.compile(r"direcciones|addresses|address book", re.I)),
    ("Equipos / organizaciones", re.compile(r"workspace|organizaci[oó]n|organization|equipo|team", re.I)),
]


_SSO = [(name, rx, prefilter(rx.pattern)) for name, rx in SSO_PATTERNS]
_SERVICES = [(name, rx, prefilter(rx.pattern)) for name, rx in AUTH_SERVICES]


def _add(out: list[AuthFinding], seen: set, kind: str, detail: str, url: str, evidence: str = "") -> None:
    key = (kind, detail, url)
    if key in seen:
        return
    seen.add(key)
    out.append(AuthFinding(kind=kind, detail=detail, url=url, evidence=evidence[:200]))


def _path(url: str) -> str:
    p = urlparse(url)
    return (p.path or "/") + (("?" + p.query) if p.query else "")


def analyze_page(page: PageResult, tree) -> list[AuthFinding]:
    out: list[AuthFinding] = []
    seen: set = set()
    url = page.final_url or page.url

    # 1. La propia URL
    for kind, rx, label in PATH_RULES:
        if rx.search(_path(url)):
            _add(out, seen, kind, label, url, f"ruta {_path(url)}")
            break

    # 2. Zonas protegidas
    if page.status in (401, 403):
        _add(out, seen, "protected_area", f"Responde HTTP {page.status}", page.url, f"status {page.status}")
    if page.redirect_chain and page.final_url and page.final_url != page.url:
        if LOGIN_URL_RE.search(_path(page.final_url)) and not LOGIN_URL_RE.search(_path(page.url)):
            _add(out, seen, "protected_area", "Redirige al login", page.url, f"→ {page.final_url}")
    www_auth = page.headers.get("www-authenticate", "")
    if www_auth:
        _add(out, seen, "protected_area", f"Autenticación HTTP ({www_auth.split()[0]})", page.url, www_auth)

    # 3. Enlaces y botones (si page.links aún no está relleno, se leen del árbol)
    links = page.links
    if not links and tree is not None:
        host = urlparse(url).netloc
        links = []
        for a in tree.css("a[href]"):
            href = urljoin(url, a.attributes.get("href") or "")
            # Enlace http:// interno en página https: es la misma URL (evita duplicar el login)
            if url.startswith("https://") and href.startswith("http://") \
                    and urlparse(href).netloc == urlparse(url).netloc:
                href = "https://" + href[7:]
            if href.startswith(("http://", "https://")):
                links.append(LinkInfo(url=href, text=(a.text(strip=True) or "")[:100],
                                      internal=urlparse(href).netloc == host))
    unique_links: dict[tuple[str, str], LinkInfo] = {}
    for link in links:
        unique_links.setdefault((link.url, (link.text or "").strip()), link)
    links = list(unique_links.values())
    for link in links:
        text = (link.text or "").strip()
        matched = False
        for kind, rx, label in TEXT_RULES:
            if text and rx.search(text):
                _add(out, seen, kind, label, link.url, f"enlace «{text[:60]}»")
                matched = True
                break
        if not matched and link.internal:
            for kind, rx, label in PATH_RULES:
                if kind == "admin_area":
                    continue
                if rx.search(_path(link.url)):
                    if kind in ("login_page", "register_page"):
                        kind = kind.replace("_page", "_entry")
                        label = ENTRY_LABELS[kind]
                    _add(out, seen, kind, label, link.url, f"enlace {_path(link.url)}")
                    break
    for btn in page.buttons:
        for kind, rx, label in TEXT_RULES:
            if rx.search(btn.strip()):
                _add(out, seen, kind, BUTTON_LABELS.get(kind, label), url, f"botón «{btn[:60]}»")
                break

    # 4. Formularios
    for f in page.forms:
        if f.kind == "login":
            names = ", ".join(x.name or x.type for x in f.fields if x.type != "hidden")[:120]
            _add(out, seen, "login_form", "Formulario de inicio de sesión", url,
                 f"campos: {names}; CSRF: {'sí' if f.has_csrf else 'no'}")
        elif f.kind == "register":
            _add(out, seen, "register_form", "Formulario de registro", url,
                 f"{len([x for x in f.fields if x.type != 'hidden'])} campos")
        elif f.kind == "password_reset":
            _add(out, seen, "password_reset", "Formulario de recuperación de contraseña", url)
        if f.captcha:
            _add(out, seen, "captcha", f.captcha, url, f"formulario {f.kind}")

    # 5. SSO y servicios de autenticación
    haystacks: list[str] = []
    haystacks.extend(page.scripts)
    haystacks.extend(l.url for l in links)
    haystacks.extend(c.url for c in page.api_calls)
    haystacks.extend(page.buttons)
    haystacks.extend(l.text for l in links if l.text)
    for k, v in page.storage_keys.items():
        haystacks.extend(v)
    blob = "\n".join(haystacks)
    html = page.html[:400_000] if page.html else ""
    texts = [(blob, blob.lower()), (html, html.lower())]
    for kind, patterns in (("sso_provider", _SSO), ("auth_service", _SERVICES)):
        for name, rx, lits in patterns:
            for text, low in texts:
                if not text or not could_match(lits, low):
                    continue
                m = rx.search(text)
                if m:
                    _add(out, seen, kind, name, url, m.group(0))
                    break

    # 6. Cookies de sesión
    for c in page.cookies:
        if c.auth_hint or SESSION_COOKIE_RE.match(c.name):
            flags = []
            if c.http_only:
                flags.append("HttpOnly")
            if c.secure:
                flags.append("Secure")
            if c.same_site:
                flags.append(f"SameSite={c.same_site}")
            _add(out, seen, "session_cookie", c.name, url, " ".join(flags) or "sin flags")

    # 7. Tokens en storage (JWT)
    for store, keys in page.storage_keys.items():
        for k in keys:
            if STORAGE_TOKEN_RE.search(k):
                _add(out, seen, "jwt_storage", f"{k} ({store}Storage)", url, "token/sesión en almacenamiento web")

    # 8. APIs de autenticación
    for call in page.api_calls:
        if AUTH_API_RE.search(urlparse(call.url).path or ""):
            _add(out, seen, "auth_api", f"{call.method} {urlparse(call.url).path}", url,
                 f"status {call.status}" if call.status else "")

    # 9. MFA
    text_blob = " ".join([page.title, page.text_excerpt, " ".join(page.buttons),
                          " ".join(h.text for h in page.headings)])
    fields_blob = " ".join(f"{x.name} {x.label} {x.autocomplete}" for f in page.forms for x in f.fields)
    m = MFA_RE.search(text_blob) or MFA_RE.search(fields_blob) or \
        (re.search(r'autocomplete=["\']one-time-code', html, re.I) if html else None)
    if m:
        _add(out, seen, "mfa_hint", "Indicios de autenticación en dos pasos", url, m.group(0))
    return out


def dedupe_findings(findings: list[AuthFinding]) -> list[AuthFinding]:
    """Deduplica hallazgos a nivel sitio (un botón de login en la cabecera cuenta una sola vez)."""
    out: list[AuthFinding] = []
    seen: set = set()
    for f in findings:
        if f.kind in SITE_WIDE_KINDS:
            key = (f.kind, f.detail)
        elif f.kind in ENTRY_LABELS and f.evidence.startswith("botón"):
            key = (f.kind, f.evidence.lower())
        elif f.kind in ENTRY_LABELS:
            key = (f.kind, f.url)
        else:
            key = (f.kind, f.detail, f.url)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def looks_login(url: str) -> bool:
    return bool(LOGIN_URL_RE.search(_path(url)))


def looks_register(url: str) -> bool:
    return bool(REGISTER_URL_RE.search(_path(url)))


def summarize(pages: list[PageResult], findings: list[AuthFinding]) -> dict:
    def uniq(seq):
        seen, res = set(), []
        for x in seq:
            if x and x not in seen:
                seen.add(x)
                res.append(x)
        return res

    findings = dedupe_findings(findings)
    by_kind: dict[str, list[AuthFinding]] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)
    notes: list[str] = []
    n_pages = max(len(pages), 1)

    def form_pages(kind: str, label: str) -> list[str]:
        urls = uniq([f.url for f in by_kind.get(kind, [])])
        if len(urls) > 3 and len(urls) >= 0.5 * n_pages:
            # formulario global (modal o cabecera): no convierte cada página en página de login
            notes.append(f"El formulario de {label} aparece en {len(urls)} páginas (modal o cabecera global).")
            return [min(urls, key=len)]
        return urls

    login_urls = uniq([f.url for f in by_kind.get("login_page", [])] + form_pages("login_form", "login") +
                      [f.url for f in by_kind.get("login_entry", []) if looks_login(f.url)])
    register_urls = uniq([f.url for f in by_kind.get("register_page", [])] + form_pages("register_form", "registro") +
                         [f.url for f in by_kind.get("register_entry", []) if looks_register(f.url)])
    entry_points = uniq([
        f"{f.detail}: {f.evidence}" + ("" if f.evidence.startswith("botón") else f" → {f.url}")
        for f in by_kind.get("login_entry", []) + by_kind.get("register_entry", [])
    ])
    protected = uniq([f.url for f in by_kind.get("protected_area", [])])
    sso = uniq([f.detail for f in by_kind.get("sso_provider", [])])
    services = uniq([f.detail for f in by_kind.get("auth_service", [])])
    captcha = uniq([f.detail for f in by_kind.get("captcha", [])])

    mechanisms: list[str] = []
    if by_kind.get("session_cookie"):
        names = uniq([f.detail for f in by_kind["session_cookie"]])[:4]
        mechanisms.append("Cookie de sesión (" + ", ".join(names) + ")")
    if by_kind.get("jwt_storage"):
        mechanisms.append("Token (JWT/API) en almacenamiento del navegador")
    if sso:
        mechanisms.append("OAuth / SSO (" + ", ".join(sso) + ")")
    if any("Autenticación HTTP" in f.detail for f in by_kind.get("protected_area", [])):
        mechanisms.append("Autenticación HTTP (Basic/Digest/Bearer)")
    if by_kind.get("auth_api"):
        mechanisms.append("API de autenticación")

    # Funcionalidades de usuario
    blob_parts: list[str] = []
    for p in pages:
        blob_parts.append(p.final_url or p.url)
        blob_parts.extend(l.text for l in p.links if l.text)
        blob_parts.extend(l.url for l in p.links if l.internal)
        blob_parts.extend(p.buttons)
    blob = "\n".join(blob_parts)
    features = [name for name, rx in FEATURE_RULES if rx.search(blob)]

    has_login = bool(login_urls or by_kind.get("login_entry") or sso or services or by_kind.get("auth_api"))
    if has_login:
        forms = [f for p in pages for f in p.forms if f.kind == "login"]
        if forms and not any(f.has_csrf for f in forms):
            notes.append("Los formularios de login no muestran token CSRF visible.")
        if forms and not any(f.captcha for f in forms):
            notes.append("El login no muestra captcha visible (posible riesgo de fuerza bruta si no hay rate limiting).")
        if any(f.captcha for f in forms):
            notes.append("El login está protegido con captcha.")
        if any(urlparse(p.final_url or p.url).scheme == "http" for p in pages
               if (p.final_url or p.url) in login_urls):
            notes.append("Hay páginas de login servidas sin HTTPS.")
    if protected:
        notes.append(f"{len(protected)} URL(s) requieren autenticación o redirigen al login.")
    if by_kind.get("jwt_storage"):
        notes.append("Se guardan tokens en localStorage/sessionStorage (accesibles desde JavaScript).")
    if by_kind.get("admin_area"):
        notes.append("Se detectaron rutas de administración: " +
                     ", ".join(uniq([f.url for f in by_kind["admin_area"]])[:3]))
    if not has_login and not register_urls:
        notes.append("No se detectó sistema de login en las páginas públicas analizadas.")

    return {
        "has_login": has_login,
        "has_register": bool(register_urls or by_kind.get("register_entry")),
        "has_password_reset": bool(by_kind.get("password_reset")),
        "login_urls": login_urls,
        "register_urls": register_urls,
        "protected_urls": protected,
        "sso_providers": sso,
        "auth_services": services,
        "session_mechanisms": mechanisms,
        "captcha": captcha,
        "user_features": features,
        "notes": notes,
        "mfa": bool(by_kind.get("mfa_hint")),
        "entry_points": entry_points,
    }
