# PaginaBuscador Crawler

Crawler y analizador de sitios web en Python. Le das una URL y entrega un reporte detallado con:

- **Mapa del sitio y áreas**: páginas, secciones, menú de navegación, profundidad, códigos de estado.
- **Tecnologías**: CMS, frameworks JS/CSS, servidor, CDN, analítica, pagos, chat, auth… con la evidencia.
- **Login y usuarios** (detección pasiva): páginas y formularios de acceso/registro, SSO/OAuth, cookies y
  tokens de sesión, zonas protegidas, captcha, 2FA.
- **Interacción**: formularios y sus campos, endpoints API/GraphQL/WebSocket llamados por el navegador,
  CTAs, búsqueda, widgets, servicios de terceros.
- **Diseño**: capturas desktop/móvil, paleta de colores, tipografías, framework CSS, breakpoints, estructura.
- **SEO, seguridad pasiva y rendimiento**, con puntuaciones y problemas priorizados.
- **Inventario** filtrable de páginas, enlaces rotos y dominios externos.

## Motor

| Pieza | Librería |
|---|---|
| HTTP | `httpx` async con HTTP/2 |
| Parser HTML | `selectolax` (Lexbor, ~20-30x más rápido que BeautifulSoup) |
| JavaScript / SPAs | `playwright` (Chromium headless) |
| Web | FastAPI + SSE |
| CLI | Typer + Rich |

Modo de render **híbrido** (`--render auto`): descarga rápida por HTTP y usa Chromium solo cuando hace
falta: SPAs detectadas, páginas de login, una muestra en sitios hechos con frameworks JS, capturas, o
cuando el sitio bloquea clientes que no son navegadores.

## Instalación

```powershell
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Uso

### Interfaz web

```powershell
python -m crawler serve            # abre http://127.0.0.1:8000
```

Pega la URL, ajusta opciones, sigue el progreso en vivo y abre el reporte al terminar.

### Terminal

```powershell
python -m crawler scan https://ejemplo.com
python -m crawler scan ejemplo.com --max-pages 300 --depth 6 --render auto --pdf --open
```

| Opción | Por defecto | Descripción |
|---|---|---|
| `-n, --max-pages` | 100 | Máximo de páginas a rastrear |
| `-d, --depth` | 5 | Profundidad máxima de enlaces |
| `-c, --concurrency` | 8 | Peticiones simultáneas |
| `-r, --render` | auto | `auto`, `always` (todo con Chromium) o `never` (solo HTTP) |
| `--screenshots` | 6 | Páginas con captura (inicio + una por área) |
| `--delay` | 0 | Segundos de espera entre peticiones por worker |
| `--pdf` | no | Genera también `report.pdf` |
| `--subdomains` | no | Incluye subdominios del mismo dominio |
| `--no-sitemap` | no | No usar `sitemap.xml` como semilla |
| `--ignore-robots` | no | No respetar robots.txt (**solo en sitios propios**) |
| `-o, --output` | output | Carpeta de salida |
| `--open` | no | Abre el reporte al terminar |

Salida: `output/<dominio>_<fecha>/report.html` (autocontenido, se puede enviar tal cual),
`report.json` (datos completos) y `screenshots/`.

## Uso responsable

- Respeta `robots.txt` y su `Crawl-delay` por defecto.
- El análisis es **pasivo**: solo sigue enlaces que el propio sitio publica. No prueba rutas ocultas,
  no hace fuerza bruta y no inicia sesión.
- Úsalo en sitios propios o con autorización, y ajusta `--delay` y `--concurrency` para no sobrecargar
  servidores ajenos.

## Desarrollo

```powershell
python -m pytest
```

Estructura y contrato entre módulos: [`docs/CONTRACT.md`](docs/CONTRACT.md).
