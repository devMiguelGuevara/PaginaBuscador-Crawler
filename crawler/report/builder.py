"""Agrega los resultados por página en un SiteReport completo."""
from __future__ import annotations

import importlib
import statistics
import traceback
from collections import Counter
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from ..labels import form_kind
from ..models import (
    ApiCall,
    AuthFinding,
    DesignInfo,
    FormInfo,
    PageResult,
    Score,
    SiteReport,
    TechHit,
)


def _analyzer(name: str):
    return importlib.import_module(f"crawler.analyzers.{name}")


def _step(report: SiteReport, label: str, fn: Callable[[], Any], default: Any = None) -> Any:
    """Ejecuta un paso del análisis sin permitir que rompa el reporte."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc(limit=2).strip().splitlines()[-1]
        report.errors.append(f"Análisis '{label}' falló: {exc!r} ({tb})")
        return default


def _html_pages(pages: list[PageResult]) -> list[PageResult]:
    return [p for p in pages if "html" in (p.content_type or "").lower() or p.title or p.links]


# ----------------------------------------------------------------- deduplicación

def _dedup_auth(pages: list[PageResult], existing: list[AuthFinding]) -> list[AuthFinding]:
    all_findings = [*existing, *(f for p in pages for f in p.auth)]
    try:
        # Deduplicación a nivel sitio del analizador (botón de login de la cabecera = 1 hallazgo)
        return _analyzer("auth").dedupe_findings(all_findings)
    except Exception:  # noqa: BLE001
        pass
    seen: set[tuple[str, str, str]] = set()
    out: list[AuthFinding] = []
    for f in all_findings:
        key = (f.kind, f.detail, f.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _strip_url(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/")


def _form_key(f: FormInfo, page_url: str) -> tuple:
    action = _strip_url(urljoin(page_url, f.action)) if f.action.strip() else ""
    if action == _strip_url(page_url):
        action = ""
    fields = tuple(sorted((fl.name, fl.type) for fl in f.fields))
    return (f.kind, f.method.upper(), action, fields, f.submit_text.strip().lower())


def _dedup_forms(pages: list[PageResult]) -> tuple[list[FormInfo], list[int]]:
    """Formularios únicos y, alineado por índice, en cuántas páginas aparece cada uno."""
    index: dict[tuple, int] = {}
    out: list[FormInfo] = []
    page_sets: list[set[str]] = []
    for p in pages:
        for f in p.forms:
            key = _form_key(f, f.page_url or p.url)
            i = index.get(key)
            if i is None:
                i = index[key] = len(out)
                out.append(f)
                page_sets.append(set())
            page_sets[i].add(p.url)
    return out, [len(s) for s in page_sets]


def _fallback_merge_tech(hits: list[TechHit]) -> list[TechHit]:
    by_name: dict[str, TechHit] = {}
    for h in hits:
        cur = by_name.get(h.name)
        if cur is None:
            by_name[h.name] = h.model_copy(deep=True)
            continue
        cur.confidence = max(cur.confidence, h.confidence)
        cur.version = cur.version or h.version
        for ev in h.evidence:
            if ev not in cur.evidence and len(cur.evidence) < 5:
                cur.evidence.append(ev)
    return sorted(by_name.values(), key=lambda t: (t.category, t.name))


def _fallback_api(pages: list[PageResult]) -> list[ApiCall]:
    seen: set[tuple[str, str]] = set()
    out: list[ApiCall] = []
    for p in pages:
        for c in p.api_calls:
            key = (c.method.upper(), c.url.split("?")[0])
            if key not in seen:
                seen.add(key)
                out.append(c)
    return out


# ----------------------------------------------------------------- métricas

def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    k = (len(vals) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def _performance(pages: list[PageResult]) -> dict[str, Any]:
    ok = [p for p in pages if p.status and p.error is None]
    times = [p.elapsed_ms for p in ok if p.elapsed_ms]
    sizes = [p.size_bytes for p in ok if p.size_bytes]
    compressed = [p for p in ok if (p.headers.get("content-encoding") or "").strip()]
    http_versions = Counter(p.http_version or "desconocido" for p in ok)
    loads = [p.load_ms for p in ok if p.load_ms]
    return {
        "pages_measured": len(ok),
        "avg_ms": round(statistics.fmean(times), 1) if times else 0,
        "median_ms": round(statistics.median(times), 1) if times else 0,
        "p95_ms": round(_percentile(times, 0.95), 1),
        "max_ms": round(max(times), 1) if times else 0,
        "avg_bytes": int(statistics.fmean(sizes)) if sizes else 0,
        "total_bytes": int(sum(sizes)),
        "avg_load_ms": round(statistics.fmean(loads), 1) if loads else 0,
        "avg_resources": round(statistics.fmean([p.resource_count for p in ok if p.resource_count]), 1)
        if any(p.resource_count for p in ok) else 0,
        "transfer_bytes": int(sum(p.transfer_bytes for p in ok)),
        "compressed_pct": round(100 * len(compressed) / len(ok), 1) if ok else 0,
        "compression": dict(Counter((p.headers.get("content-encoding") or "ninguna") for p in ok)),
        "http_versions": dict(http_versions),
        "rendered_pages": sum(1 for p in pages if p.rendered),
        "http_pages": sum(1 for p in pages if not p.rendered),
        "slowest": [{"url": p.url, "ms": round(p.elapsed_ms, 1)}
                    for p in sorted(ok, key=lambda p: p.elapsed_ms, reverse=True)[:5]],
        "heaviest": [{"url": p.url, "bytes": p.size_bytes}
                     for p in sorted(ok, key=lambda p: p.size_bytes, reverse=True)[:5]],
    }


def _external_domains(pages: list[PageResult], domain: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    base = domain.lower().removeprefix("www.")

    def add(url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if host and not host.removeprefix("www.").endswith(base):
            counts[host] += 1

    for p in pages:
        for link in p.links:
            if not link.internal:
                add(link.url)
        for src in [*p.scripts, *p.stylesheets, *p.iframes]:
            add(src)
    return dict(counts.most_common(60))


def _broken_links(pages: list[PageResult]) -> list[dict[str, Any]]:
    out = []
    for p in pages:
        if (p.status and p.status >= 400) or (p.error and p.status is None):
            out.append({"url": p.url, "status": p.status, "from": p.parent, "error": p.error or ""})
    return out


def _accessibility(pages: list[PageResult], forms: list[FormInfo]) -> Score:
    notes: list[str] = []
    html = _html_pages(pages) or pages
    value = 100
    imgs = sum(p.images_total for p in html)
    no_alt = sum(p.images_no_alt for p in html)
    if imgs:
        ratio = no_alt / imgs
        value -= int(35 * ratio)
        if no_alt:
            notes.append(f"{no_alt} de {imgs} imágenes sin texto alternativo (alt).")
    no_lang = [p for p in html if not p.lang]
    if no_lang:
        value -= int(15 * len(no_lang) / max(len(html), 1))
        notes.append(f"{len(no_lang)} página(s) sin atributo lang.")
    designs = [p.design for p in html if p.design]
    if designs:
        for lm in ("header", "nav", "main", "footer"):
            missing = sum(1 for d in designs if not d.landmarks.get(lm))
            if missing:
                value -= int(5 * missing / len(designs))
                notes.append(f"Landmark <{lm}> ausente en {missing} de {len(designs)} página(s) analizadas.")
    fields = [fl for f in forms for fl in f.fields if fl.type not in ("hidden", "submit", "button")]
    unlabeled = [fl for fl in fields if not fl.label and not fl.placeholder]
    if fields and unlabeled:
        value -= int(20 * len(unlabeled) / len(fields))
        notes.append(f"{len(unlabeled)} de {len(fields)} campos de formulario sin etiqueta visible.")
    no_h1 = [p for p in html if not any(h.level == 1 for h in p.headings)]
    if no_h1 and html:
        value -= int(10 * len(no_h1) / len(html))
        notes.append(f"{len(no_h1)} página(s) sin encabezado H1.")
    if not notes:
        notes.append("Sin problemas básicos de accesibilidad detectados.")
    return Score(name="Accesibilidad", value=max(0, min(100, value)), notes=notes)


def _performance_score(perf: dict[str, Any]) -> Score:
    notes: list[str] = []
    value = 100
    avg = perf.get("avg_ms", 0) or 0
    if avg > 3000:
        value -= 45
    elif avg > 1500:
        value -= 30
    elif avg > 800:
        value -= 15
    elif avg > 400:
        value -= 5
    notes.append(f"Tiempo medio de respuesta: {avg} ms (p95 {perf.get('p95_ms', 0)} ms).")
    avg_b = perf.get("avg_bytes", 0) or 0
    if avg_b > 1_500_000:
        value -= 20
    elif avg_b > 500_000:
        value -= 10
    notes.append(f"Peso medio del HTML: {round(avg_b / 1024, 1)} KB.")
    comp = perf.get("compressed_pct", 0) or 0
    if perf.get("pages_measured") and comp < 50:
        value -= 15
        notes.append(f"Solo {comp}% de las respuestas usan compresión (gzip/br).")
    if perf.get("http_versions") and not any(v.upper().startswith("HTTP/2") or v.upper().startswith("HTTP/3")
                                              for v in perf["http_versions"]):
        value -= 5
        notes.append("El servidor no negoció HTTP/2 ni HTTP/3.")
    return Score(name="Rendimiento", value=max(0, min(100, value)), notes=notes)


def _issues_notes(data: dict[str, Any], limit: int = 4) -> list[str]:
    order = {"alta": 0, "media": 1, "baja": 2}
    issues = sorted(data.get("issues", []) or [], key=lambda i: order.get(i.get("severity", "baja"), 3))
    return [f"[{i.get('severity', '')}] {i.get('message', '')}" for i in issues[:limit]]


# ----------------------------------------------------------------- resumen

def _summary(report: SiteReport) -> list[str]:
    s: list[str] = []
    pages = report.pages
    ok = [p for p in pages if p.status and p.status < 400]
    home = next((p for p in pages if p.depth == 0), pages[0] if pages else None)
    title = (home.title if home else "") or report.domain
    kind = report.site_type or "Sitio web"
    s.append(f"«{title}» ({report.domain}) es un sitio de tipo {kind}; se analizaron {len(pages)} URL "
             f"({len(ok)} respondieron correctamente) en {report.duration_s:.1f} s.")
    if home and home.meta_description:
        s.append(f"Descripción declarada: {home.meta_description[:220]}")

    if report.technologies:
        cats: dict[str, list[str]] = {}
        for t in report.technologies:
            cats.setdefault(t.category, []).append(t.name + (f" {t.version}" if t.version else ""))
        top = "; ".join(f"{c}: {', '.join(n[:4])}" for c, n in list(cats.items())[:6])
        s.append(f"Tecnologías detectadas ({len(report.technologies)}): {top}.")
    else:
        s.append("No se identificaron tecnologías con certeza (posible sitio estático u ofuscado).")

    if report.areas:
        names = ", ".join(f"{a.name} ({a.pages})" for a in sorted(report.areas, key=lambda a: -a.pages)[:8])
        s.append(f"Áreas principales del sitio: {names}.")

    a = report.auth_summary or {}
    if a.get("has_login") or a.get("sso_providers") or a.get("auth_services"):
        parts = []
        login_urls = list(a.get("login_urls") or [])
        if login_urls:
            extra = f" (+{len(login_urls) - 5} más)" if len(login_urls) > 5 else ""
            parts.append("login en " + ", ".join(login_urls[:5]) + extra)
        if a.get("has_register"):
            parts.append("registro de usuarios")
        if a.get("has_password_reset"):
            parts.append("recuperación de contraseña")
        if a.get("sso_providers"):
            parts.append("SSO con " + ", ".join(a["sso_providers"][:5]))
        if a.get("auth_services"):
            parts.append("servicio de identidad " + ", ".join(a["auth_services"][:3]))
        if a.get("session_mechanisms"):
            parts.append("sesión vía " + ", ".join(a["session_mechanisms"][:3]))
        if a.get("mfa"):
            parts.append("indicios de 2FA/MFA")
        s.append("Usuarios y acceso: " + "; ".join(parts or ["se detectó un sistema de autenticación"]) + ".")
        if a.get("protected_urls"):
            s.append(f"Zonas protegidas detectadas: {len(a['protected_urls'])} URL requieren sesión "
                     f"(ej. {a['protected_urls'][0]}).")
    else:
        s.append("No se detectó login ni gestión de usuarios en las páginas públicas analizadas.")

    forms_kinds = Counter(f.kind for f in report.forms)
    inter = report.interactions or {}
    bits = []
    if report.forms:
        bits.append(f"{len(report.forms)} formularios únicos ("
                    + ", ".join(f"{form_kind(k).lower()}: {v}" for k, v in forms_kinds.items()) + ")")
        form_pages = inter.get("form_pages") or []
        repeated = sorted(((n, f) for n, f in zip(form_pages, report.forms) if n > 1), key=lambda x: -x[0])[:2]
        for n, f in repeated:
            bits.append(f"formulario «{f.submit_text or form_kind(f.kind)}» presente en {n} páginas")
    if report.api_endpoints:
        bits.append(f"{len(report.api_endpoints)} endpoints de API invocados desde el navegador")
    if inter.get("graphql"):
        bits.append("GraphQL")
    if inter.get("websockets"):
        bits.append("WebSockets")
    if inter.get("search"):
        bits.append("buscador interno")
    if inter.get("chat_widgets"):
        bits.append("chat: " + ", ".join(inter["chat_widgets"][:3]))
    if bits:
        s.append("Interacción: " + "; ".join(bits) + ".")
    if inter.get("analytics"):
        s.append("Analítica/seguimiento: " + ", ".join(inter["analytics"][:6]) + ".")

    d = report.design
    dbits = []
    if d.css_frameworks:
        dbits.append("framework CSS " + ", ".join(d.css_frameworks[:3]))
    if d.fonts:
        dbits.append("tipografías " + ", ".join(d.fonts[:4]))
    if d.colors:
        dbits.append("paleta principal " + ", ".join(list(d.colors)[:5]))
    dbits.append("diseño responsive" if d.responsive or d.viewport else "sin meta viewport (no responsive)")
    s.append("Diseño: " + "; ".join(dbits) + ".")

    probs = []
    for sc in report.scores:
        if sc.value < 60:
            probs.append(f"{sc.name} bajo ({sc.value}/100)")
    if report.broken_links:
        probs.append(f"{len(report.broken_links)} enlaces rotos o con error")
    sec = report.security or {}
    if sec.get("missing_headers"):
        probs.append("faltan cabeceras de seguridad: " + ", ".join(sec["missing_headers"][:4]))
    if probs:
        s.append("Principales problemas: " + "; ".join(probs) + ".")
    return s[:12]


# ----------------------------------------------------------------- principal

def build_report(report: SiteReport) -> SiteReport:
    pages = report.pages
    html_pages = _html_pages(pages)

    def technologies() -> list[TechHit]:
        hits = [h for p in pages for h in p.technologies]
        try:
            return _analyzer("tech").merge(hits)
        except ImportError:
            return _fallback_merge_tech(hits)

    report.technologies = _step(report, "tecnologías", technologies, []) or []

    report.auth = _step(report, "auth-dedup", lambda: _dedup_auth(pages, report.auth), report.auth) or []
    report.auth_summary = _step(report, "auth", lambda: _analyzer("auth").summarize(pages, report.auth), {}) or {}

    forms_res = _step(report, "formularios", lambda: _dedup_forms(pages), None)
    report.forms, form_pages = forms_res if forms_res else ([], [])

    def api() -> list[ApiCall]:
        try:
            return _analyzer("interactions").collect_api_endpoints(pages)
        except ImportError:
            return _fallback_api(pages)

    report.api_endpoints = _step(report, "api", api, []) or []
    report.interactions = _step(report, "interacción",
                                lambda: _analyzer("interactions").site_interactions(pages), {}) or {}
    report.interactions["form_pages"] = form_pages  # alineado con report.forms

    report.areas = _step(report, "áreas", lambda: _analyzer("areas").build_areas(pages), []) or []
    report.nav_menu = _step(report, "menú", lambda: _analyzer("areas").nav_menu(pages), []) or []
    report.site_type = _step(report, "tipo de sitio",
                             lambda: _analyzer("areas").detect_site_type(pages, report.technologies, report.forms),
                             "") or ""

    designs = [p.design for p in pages if p.design]
    if designs:
        report.design = _step(report, "diseño", lambda: _analyzer("design").merge_designs(designs),
                              designs[0]) or DesignInfo()

    report.seo = _step(report, "seo", lambda: _analyzer("seo").site_seo(html_pages or pages), {}) or {}
    report.security = _step(report, "seguridad",
                            lambda: _analyzer("security").site_security(pages, report.target), {}) or {}
    report.performance = _step(report, "rendimiento", lambda: _performance(pages), {}) or {}
    report.external_domains = _step(report, "dominios externos",
                                    lambda: _external_domains(pages, report.domain), {}) or {}
    if not report.broken_links:
        report.broken_links = _step(report, "enlaces rotos", lambda: _broken_links(pages), []) or []

    def scores() -> list[Score]:
        out = []
        if report.seo:
            out.append(Score(name="SEO", value=int(report.seo.get("score", 0) or 0),
                             notes=_issues_notes(report.seo) or ["Sin problemas SEO relevantes."]))
        if report.security:
            out.append(Score(name="Seguridad", value=int(report.security.get("score", 0) or 0),
                             notes=_issues_notes(report.security) or ["Sin problemas de seguridad pasiva."]))
        out.append(_accessibility(pages, report.forms))
        out.append(_performance_score(report.performance))
        return out

    report.scores = _step(report, "puntuaciones", scores, []) or []
    report.summary = _step(report, "resumen", lambda: _summary(report), []) or []
    return report
