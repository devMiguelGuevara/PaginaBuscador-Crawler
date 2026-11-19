"""Modelos de datos compartidos por el motor, los analizadores y el reporte."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LinkInfo(BaseModel):
    url: str
    text: str = ""
    internal: bool = True
    nofollow: bool = False
    in_nav: bool = False


class HeadingInfo(BaseModel):
    level: int
    text: str


class FieldInfo(BaseModel):
    name: str = ""
    type: str = "text"          # text, email, password, hidden, select, textarea, checkbox...
    label: str = ""
    placeholder: str = ""
    required: bool = False
    autocomplete: str = ""


class FormInfo(BaseModel):
    page_url: str
    action: str = ""
    method: str = "GET"
    form_id: str = ""
    kind: str = "other"         # login, register, password_reset, search, contact, newsletter, payment, comment, other
    fields: list[FieldInfo] = Field(default_factory=list)
    has_csrf: bool = False
    csrf_field: str = ""
    captcha: str | None = None  # recaptcha, hcaptcha, turnstile, ...
    submit_text: str = ""


class TechHit(BaseModel):
    name: str
    category: str
    version: str | None = None
    confidence: int = 100       # 0-100
    evidence: list[str] = Field(default_factory=list)
    website: str = ""


class ApiCall(BaseModel):
    url: str
    method: str = "GET"
    resource_type: str = "fetch"   # xhr, fetch, websocket, eventsource
    status: int | None = None
    content_type: str = ""
    graphql: bool = False
    page_url: str = ""
    third_party: bool = False


class CookieInfo(BaseModel):
    name: str
    domain: str = ""
    path: str = "/"
    secure: bool = False
    http_only: bool = False
    same_site: str = ""
    session: bool = True        # sin expiración
    source: str = "header"      # header | browser
    auth_hint: bool = False     # parece cookie de sesión/autenticación


class AuthFinding(BaseModel):
    kind: str   # login_page, register_page, password_reset, login_form, register_form, sso_provider,
                # session_cookie, jwt_storage, protected_area, captcha, mfa_hint, logout, account_area,
                # admin_area, auth_service, auth_api
    detail: str = ""
    url: str = ""
    evidence: str = ""


class DesignInfo(BaseModel):
    colors: dict[str, int] = Field(default_factory=dict)       # #rrggbb -> apariciones
    computed_colors: dict[str, str] = Field(default_factory=dict)  # rol -> color (body_bg, text, link, button...)
    fonts: list[str] = Field(default_factory=list)
    font_sources: list[str] = Field(default_factory=list)     # Google Fonts, Adobe Fonts, self-hosted...
    css_frameworks: list[str] = Field(default_factory=list)
    icon_libraries: list[str] = Field(default_factory=list)
    breakpoints: list[str] = Field(default_factory=list)
    viewport: str = ""
    theme_color: str = ""
    favicon: str = ""
    landmarks: dict[str, bool] = Field(default_factory=dict)  # header, nav, main, footer, aside
    dark_mode: bool = False
    responsive: bool = False


class PageResult(BaseModel):
    url: str
    final_url: str = ""
    status: int | None = None
    depth: int = 0
    parent: str = ""
    redirect_chain: list[str] = Field(default_factory=list)
    content_type: str = ""
    size_bytes: int = 0
    elapsed_ms: float = 0
    http_version: str = ""
    rendered: bool = False
    spa_suspected: bool = False
    error: str | None = None

    # Contenido
    title: str = ""
    meta_description: str = ""
    lang: str = ""
    canonical: str = ""
    meta_robots: str = ""
    viewport: str = ""
    generator: str = ""
    theme_color: str = ""
    og: dict[str, str] = Field(default_factory=dict)
    twitter: dict[str, str] = Field(default_factory=dict)
    json_ld_types: list[str] = Field(default_factory=list)
    hreflang: list[str] = Field(default_factory=list)
    headings: list[HeadingInfo] = Field(default_factory=list)
    word_count: int = 0
    text_excerpt: str = ""

    # Elementos
    links: list[LinkInfo] = Field(default_factory=list)
    images_total: int = 0
    images_no_alt: int = 0
    scripts: list[str] = Field(default_factory=list)      # src de scripts externos
    inline_scripts: int = 0
    stylesheets: list[str] = Field(default_factory=list)
    iframes: list[str] = Field(default_factory=list)
    buttons: list[str] = Field(default_factory=list)
    forms: list[FormInfo] = Field(default_factory=list)

    # HTTP / navegador
    headers: dict[str, str] = Field(default_factory=dict)
    cookies: list[CookieInfo] = Field(default_factory=list)
    api_calls: list[ApiCall] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    js_globals: list[str] = Field(default_factory=list)
    storage_keys: dict[str, list[str]] = Field(default_factory=dict)  # local/session -> claves
    resource_count: int = 0
    transfer_bytes: int = 0
    load_ms: float = 0

    # Análisis
    technologies: list[TechHit] = Field(default_factory=list)
    auth: list[AuthFinding] = Field(default_factory=list)
    interactions: dict[str, Any] = Field(default_factory=dict)
    design: DesignInfo | None = None
    page_type: str = "other"
    area: str = "/"
    screenshot_desktop: str | None = None
    screenshot_mobile: str | None = None

    # Solo en memoria (no se exporta)
    html: str = Field("", exclude=True)
    css_text: str = Field("", exclude=True)


class AreaInfo(BaseModel):
    name: str
    path_prefix: str
    pages: int = 0
    page_types: dict[str, int] = Field(default_factory=dict)
    sample_urls: list[str] = Field(default_factory=list)
    in_nav: bool = False


class Score(BaseModel):
    name: str
    value: int              # 0-100
    notes: list[str] = Field(default_factory=list)


class SiteReport(BaseModel):
    target: str
    domain: str
    started_at: str
    finished_at: str = ""
    duration_s: float = 0
    config: dict[str, Any] = Field(default_factory=dict)

    robots_txt: str | None = None
    sitemaps: list[str] = Field(default_factory=list)
    sitemap_urls: int = 0
    server_info: dict[str, Any] = Field(default_factory=dict)

    pages: list[PageResult] = Field(default_factory=list)
    technologies: list[TechHit] = Field(default_factory=list)
    auth: list[AuthFinding] = Field(default_factory=list)
    auth_summary: dict[str, Any] = Field(default_factory=dict)
    forms: list[FormInfo] = Field(default_factory=list)
    api_endpoints: list[ApiCall] = Field(default_factory=list)
    areas: list[AreaInfo] = Field(default_factory=list)
    nav_menu: list[LinkInfo] = Field(default_factory=list)
    design: DesignInfo = Field(default_factory=DesignInfo)
    interactions: dict[str, Any] = Field(default_factory=dict)
    seo: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    performance: dict[str, Any] = Field(default_factory=dict)
    broken_links: list[dict[str, Any]] = Field(default_factory=list)
    external_domains: dict[str, int] = Field(default_factory=dict)
    site_type: str = ""
    scores: list[Score] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    output_dir: str = ""
