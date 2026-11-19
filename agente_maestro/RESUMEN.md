# PaginaBuscador Crawler · Agente maestro

> Crawler y analizador de sitios web: le das una URL y genera un reporte HTML/JSON/PDF con páginas, tecnologías, login, formularios, diseño, SEO y seguridad.

## Qué hace

Rastrea un sitio respetando `robots.txt` y produce un reporte con:

- **Mapa y áreas**: páginas, secciones, menú, profundidad, códigos de estado, enlaces rotos.
- **Tecnologías**: CMS, frameworks, servidor, CDN, analítica, pagos, chat… con evidencia (`fingerprints/technologies.json`).
- **Login y usuarios** (pasivo): formularios de acceso/registro, SSO/OAuth, cookies de sesión, captcha, 2FA.
- **Interacción**: formularios, endpoints API/GraphQL/WebSocket, CTAs, widgets y servicios de terceros.
- **Diseño**: capturas desktop y móvil, paleta, tipografías, breakpoints.
- **SEO, seguridad pasiva y rendimiento** con puntuación 0–100 y problemas priorizados.

Modo de render híbrido: HTTP rápido (`httpx` + `selectolax`) y Chromium (`playwright`) solo cuando hace falta (SPAs, logins, capturas).

## Estado

**Activo, el proyecto más completo de la carpeta.** Código de sep-2026; último reporte generado el 5-oct-2026. Tiene 13 archivos de tests. No está en git.

Reportes ya generados en `output/`: app.lab10.ai, books.toscrape.com, cheatsheetseries.owasp.org, mattilda.io.

## Cómo se usa

```powershell
.venv\Scripts\activate
python -m crawler serve                                  # interfaz web en http://127.0.0.1:8000
python -m crawler scan ejemplo.com --max-pages 300 --pdf --open
python -m pytest                                         # tests
```

El `README.md` del proyecto tiene la tabla completa de opciones.

## Archivos clave

| Ruta | Función |
|---|---|
| `crawler/__main__.py` | CLI (Typer): `scan`, `serve` |
| `crawler/engine.py` | `run_crawl()`: orquesta el rastreo asíncrono |
| `crawler/fetcher.py`, `renderer.py` | Descarga HTTP y render con Chromium |
| `crawler/analyzers/` | Un módulo por análisis: page, forms, tech, auth, interactions, design, areas, seo, security |
| `crawler/models.py`, `config.py` | **Contrato compartido** (modelos Pydantic y `CrawlConfig`) |
| `crawler/report/` | Construcción del reporte y exportación (plantillas Jinja2) |
| `crawler/web/` | Interfaz web FastAPI con progreso en vivo (SSE) |
| `docs/CONTRACT.md` | Contrato entre módulos: firmas, claves y eventos de progreso |
| `tests/` | Tests con pytest + fixtures |
| `output/` | Reportes generados |

## Dependencias

`httpx[http2]`, `selectolax`, `playwright` (+ `playwright install chromium`), `pydantic`, `typer`, `rich`, `fastapi`, `uvicorn`, `jinja2`; tests: `pytest`, `pytest-asyncio`. Python ≥ 3.11.

## Observaciones y pendientes

- Ponerlo en git.
- `output/` crece con cada análisis; conviene limpiarlo o excluirlo del control de versiones.

## Reglas para el agente

- Leer `docs/CONTRACT.md` antes de cambiar cualquier analizador. **No editar `models.py` ni `config.py` sin coordinar**: son el contrato entre módulos.
- Todos los textos visibles para el usuario van en español.
- El análisis es **pasivo**: no añadir fuerza bruta, rutas ocultas ni inicio de sesión. Usar solo en sitios propios o con autorización.
- Correr `python -m pytest` después de cada cambio.
