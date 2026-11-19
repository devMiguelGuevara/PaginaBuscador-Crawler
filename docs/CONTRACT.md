# Contrato interno de módulos

Modelos: `crawler/models.py` (PageResult, FormInfo, TechHit, AuthFinding, DesignInfo, ApiCall, CookieInfo,
AreaInfo, Score, SiteReport). Config: `crawler/config.py` (CrawlConfig). **No editar estos dos archivos
sin coordinar** (son el contrato compartido).

Parser HTML: `selectolax.lexbor.LexborHTMLParser` (alias `HTMLParser` en este doc). `tree` puede ser `None`
cuando la respuesta no es HTML. Todos los textos visibles al usuario van **en español**.

## Flujo
1. `engine.run_crawl(config, progress=None) -> SiteReport` (async) rastrea. Por cada página HTML:
   - `analyzers.page.parse_page(page, tree, scope) -> list[str]` rellena contenido/elementos y devuelve URLs internas nuevas.
   - `analyzers.forms.extract_forms(tree, page_url) -> list[FormInfo]` → `page.forms`
   - `analyzers.tech.detect(page, tree) -> list[TechHit]` → `page.technologies`
   - `analyzers.auth.analyze_page(page, tree) -> list[AuthFinding]` → `page.auth`
   - `analyzers.interactions.page_interactions(page, tree) -> dict` → `page.interactions`
   - `analyzers.design.page_design(page, tree, computed) -> DesignInfo` → `page.design` (solo páginas con
     render o las primeras N; `computed` es dict de estilos computados del navegador o `None`;
     `page.css_text` contiene CSS inline + hojas externas descargadas, puede estar vacío)
   - `analyzers.areas.classify_page(page) -> str` → `page.page_type`; `analyzers.areas.area_of(url) -> str` → `page.area`
2. `report.builder.build_report(report) -> SiteReport` recibe el SiteReport con `pages`, `robots_txt`, `sitemaps`,
   `sitemap_urls`, `server_info`, `config`, `errors`, `broken_links` ya rellenos y completa el resto usando
   las funciones de sitio de abajo, más `scores` y `summary` (resumen ejecutivo en español).
3. `report.exporters.export_all(report, config) -> dict[str, str]` escribe `report.json`, `report.html` y
   (si `config.pdf`) `report.pdf` en `report.output_dir`; devuelve {formato: ruta}.

## Valores de `kind`
- `FormInfo.kind`: login, register, password_reset, search, contact, newsletter, payment, comment,
  add_to_cart, other. Los formularios sin atributo `action` tienen `action == ""`.
- `AuthFinding.kind`: además de los del modelo, `login_entry` / `register_entry` (enlace o botón de acceso
  en la navegación; se deduplican a nivel sitio). `login_page` es solo la página que ES de login.
- `auth.summarize()` agrega `entry_points` (list[str]).

## Funciones de sitio
- `tech.merge(hits: list[TechHit]) -> list[TechHit]` — dedup por nombre, máx. confianza, evidencia (máx 5), versión.
- `auth.summarize(pages, findings) -> dict` claves: `has_login, has_register, has_password_reset` (bool),
  `login_urls, register_urls, protected_urls` (list[str]), `sso_providers, auth_services, session_mechanisms,
  captcha, user_features, notes` (list[str]), `mfa` (bool).
- `interactions.site_interactions(pages) -> dict` claves: `ctas, chat_widgets, analytics, social, video,
  third_party_services, downloads` (list[str]), `search` (bool), `cookie_banner` (bool), `modals` (int),
  `event_handlers` (int), `websockets` (list[str]), `graphql` (bool).
- `interactions.collect_api_endpoints(pages) -> list[ApiCall]` — dedup por método + URL sin query.
- `design.merge_designs(designs: list[DesignInfo]) -> DesignInfo`.
- `seo.site_seo(pages) -> dict` claves: `score` (int 0-100), `issues` (list[{severity: alta|media|baja,
  message, urls: list[str]}]), `stats` (dict).
- `security.site_security(pages, target) -> dict` claves: `score`, `https` (bool), `headers` (dict nombre->valor|None),
  `missing_headers` (list), `cookie_issues` (list[str]), `mixed_content` (list[str]), `issues` (como seo).
- `areas.build_areas(pages) -> list[AreaInfo]`, `areas.nav_menu(pages) -> list[LinkInfo]`,
  `areas.detect_site_type(pages, technologies, forms) -> str` (ej. "E-commerce", "Blog", "Aplicación web / SaaS").

## Eventos de progreso (callback `progress(event: dict)`)
- `{"type": "phase", "message": str}`
- `{"type": "page", "url": str, "status": int|None, "done": int, "queued": int, "max_pages": int, "rendered": bool}`
- `{"type": "done", "output_dir": str, "files": dict}` / `{"type": "error", "message": str}`

## Entorno
Python del proyecto: `.venv\Scripts\python.exe`. Tests con `pytest` en `tests/`.
