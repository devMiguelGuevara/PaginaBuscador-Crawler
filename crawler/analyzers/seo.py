"""Análisis SEO a nivel de sitio."""
from __future__ import annotations

from collections import defaultdict

from ..models import PageResult

_PENALTY = {"alta": 12, "media": 6, "baja": 2}


def _is_html_ok(p: PageResult) -> bool:
    if p.error or p.status is None or p.status >= 400:
        return False
    ct = (p.content_type or "").lower()
    return not ct or "html" in ct


def _issue(issues: list, severity: str, message: str, urls: list[str]) -> None:
    if urls:
        issues.append({"severity": severity, "message": message, "urls": urls[:50]})


def site_seo(pages: list[PageResult]) -> dict:
    ok = [p for p in pages if _is_html_ok(p)]
    issues: list[dict] = []
    n = len(ok)

    no_title = [p.url for p in ok if not p.title.strip()]
    long_title = [p.url for p in ok if len(p.title.strip()) > 60]
    short_title = [p.url for p in ok if 0 < len(p.title.strip()) < 15]
    titles: dict[str, list[str]] = defaultdict(list)
    descs: dict[str, list[str]] = defaultdict(list)
    for p in ok:
        if p.title.strip():
            titles[p.title.strip().lower()].append(p.url)
        if p.meta_description.strip():
            descs[p.meta_description.strip().lower()].append(p.url)
    dup_titles = [u for urls in titles.values() if len(urls) > 1 for u in urls]
    dup_descs = [u for urls in descs.values() if len(urls) > 1 for u in urls]
    no_desc = [p.url for p in ok if not p.meta_description.strip()]
    long_desc = [p.url for p in ok if len(p.meta_description.strip()) > 160]

    no_h1 = [p.url for p in ok if not any(h.level == 1 for h in p.headings)]
    multi_h1 = [p.url for p in ok if sum(1 for h in p.headings if h.level == 1) > 1]
    no_canonical = [p.url for p in ok if not p.canonical]
    no_lang = [p.url for p in ok if not p.lang]
    noindex = [p.url for p in ok if "noindex" in (p.meta_robots or "").lower()
               or "noindex" in (p.headers.get("x-robots-tag", "") or "").lower()]
    img_alt = [p.url for p in ok if p.images_no_alt > 0]
    no_og = [p.url for p in ok if not p.og.get("og:title") and not p.og.get("title") and not p.og]
    no_ld = [p.url for p in ok if not p.json_ld_types]
    thin = [p.url for p in ok if p.word_count < 150]
    no_viewport = [p.url for p in ok if not p.viewport]
    broken = [p.url for p in pages if p.status is not None and p.status >= 400]
    errored = [p.url for p in pages if p.error]
    slow = [p.url for p in ok if p.elapsed_ms > 2000]

    _issue(issues, "alta", "Páginas sin etiqueta <title>", no_title)
    _issue(issues, "alta", "Páginas que responden con error (4xx/5xx)", broken)
    _issue(issues, "alta", "Páginas sin encabezado H1", no_h1)
    _issue(issues, "media", "Títulos duplicados entre páginas", dup_titles)
    _issue(issues, "media", "Páginas sin meta description", no_desc)
    _issue(issues, "media", "Meta descriptions duplicadas", dup_descs)
    _issue(issues, "media", "Páginas con varios H1", multi_h1)
    _issue(issues, "media", "Páginas marcadas como noindex", noindex)
    _issue(issues, "media", "Imágenes sin texto alternativo (alt)", img_alt)
    _issue(issues, "media", "Páginas lentas (más de 2 s de respuesta)", slow)
    _issue(issues, "media", "Páginas sin meta viewport (no optimizadas para móvil)", no_viewport)
    _issue(issues, "media", "Páginas con error de red o timeout", errored)
    _issue(issues, "baja", "Títulos demasiado largos (>60 caracteres)", long_title)
    _issue(issues, "baja", "Títulos demasiado cortos (<15 caracteres)", short_title)
    _issue(issues, "baja", "Meta descriptions demasiado largas (>160 caracteres)", long_desc)
    _issue(issues, "baja", "Páginas sin URL canónica", no_canonical)
    _issue(issues, "baja", "Páginas sin atributo lang en <html>", no_lang)
    _issue(issues, "baja", "Páginas sin etiquetas OpenGraph (vista previa en redes)", no_og)
    _issue(issues, "baja", "Páginas sin datos estructurados (JSON-LD)", no_ld)
    _issue(issues, "baja", "Páginas con poco contenido (<150 palabras)", thin)

    # Score: penalización ponderada por la proporción de páginas afectadas
    score = 100.0
    if n == 0:
        score = 0.0 if pages else 100.0
    else:
        for iss in issues:
            ratio = min(1.0, len(iss["urls"]) / n)
            score -= _PENALTY[iss["severity"]] * (0.4 + 0.6 * ratio)
    score = max(0, min(100, round(score)))

    total_words = sum(p.word_count for p in ok)
    stats = {
        "paginas_analizadas": n,
        "paginas_con_error": len(broken) + len(errored),
        "promedio_palabras": round(total_words / n) if n else 0,
        "con_meta_description": n - len(no_desc),
        "con_h1": n - len(no_h1),
        "con_canonical": n - len(no_canonical),
        "con_opengraph": n - len(no_og),
        "con_datos_estructurados": n - len(no_ld),
        "imagenes_total": sum(p.images_total for p in ok),
        "imagenes_sin_alt": sum(p.images_no_alt for p in ok),
        "tipos_json_ld": sorted({t for p in ok for t in p.json_ld_types}),
        "idiomas": sorted({p.lang for p in ok if p.lang}),
        "hreflang": sorted({h for p in ok for h in p.hreflang}),
    }
    order = {"alta": 0, "media": 1, "baja": 2}
    issues.sort(key=lambda i: (order[i["severity"]], -len(i["urls"])))
    return {"score": score, "issues": issues, "stats": stats}
