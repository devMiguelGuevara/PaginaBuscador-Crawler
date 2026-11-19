"""Análisis de diseño: colores, tipografías, frameworks CSS, iconos, responsive y estructura."""
from __future__ import annotations

import colorsys
import re
from collections import Counter
from urllib.parse import parse_qs, urlparse

from ..models import DesignInfo, PageResult

# --------------------------------------------------------------------------- colores

_HEX_RE = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
_RGB_RE = re.compile(r"rgba?\(\s*([^)]+)\)", re.I)
_HSL_RE = re.compile(r"hsla?\(\s*([^)]+)\)", re.I)
_URL_RE = re.compile(r"url\([^)]*\)", re.I)


def _clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _split_args(args: str) -> list[str]:
    args = args.replace("/", " ").replace(",", " ")
    return [a for a in args.split() if a]


def _alpha(val: str | None) -> float:
    if val is None:
        return 1.0
    try:
        return float(val[:-1]) / 100 if val.endswith("%") else float(val)
    except ValueError:
        return 1.0


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(_clamp(r), _clamp(g), _clamp(b))


def normalize_color(value: str) -> str | None:
    """Convierte un color CSS (hex, rgb[a], hsl[a]) a #rrggbb. None si es transparente o inválido."""
    if not value:
        return None
    v = value.strip().lower()
    if v in ("transparent", "none", "inherit", "initial", "currentcolor", "unset"):
        return None
    m = _HEX_RE.fullmatch(v) or _HEX_RE.match(v)
    if m and v.startswith("#"):
        h = m.group(1)
        if len(h) in (3, 4):
            if len(h) == 4 and h[3] == "0":
                return None
            h = "".join(c * 2 for c in h[:3])
        elif len(h) == 8:
            if h[6:8] == "00":
                return None
            h = h[:6]
        return "#" + h
    m = _RGB_RE.match(v)
    if m:
        parts = _split_args(m.group(1))
        if len(parts) < 3:
            return None
        try:
            chans = [float(p[:-1]) * 2.55 if p.endswith("%") else float(p) for p in parts[:3]]
        except ValueError:
            return None
        if _alpha(parts[3] if len(parts) > 3 else None) == 0:
            return None
        return _rgb_to_hex(*chans)
    m = _HSL_RE.match(v)
    if m:
        parts = _split_args(m.group(1))
        if len(parts) < 3:
            return None
        try:
            h = float(re.sub(r"deg$", "", parts[0])) % 360 / 360
            s = float(parts[1].rstrip("%")) / 100
            lum = float(parts[2].rstrip("%")) / 100
        except ValueError:
            return None
        if _alpha(parts[3] if len(parts) > 3 else None) == 0:
            return None
        r, g, b = colorsys.hls_to_rgb(h, lum, s)
        return _rgb_to_hex(r * 255, g * 255, b * 255)
    return None


def _colors_in(text: str) -> list[str]:
    if not text:
        return []
    text = _URL_RE.sub("", text)
    out: list[str] = []
    for m in _HEX_RE.finditer(text):
        c = normalize_color(m.group(0))
        if c:
            out.append(c)
    for rx in (_RGB_RE, _HSL_RE):
        for m in rx.finditer(text):
            c = normalize_color(m.group(0))
            if c:
                out.append(c)
    return out


# --------------------------------------------------------------------------- fuentes

_GENERIC_FONTS = {
    "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-sans-serif",
    "ui-serif", "ui-monospace", "ui-rounded", "inherit", "initial", "unset", "emoji", "math",
    "-apple-system", "blinkmacsystemfont", "apple color emoji", "segoe ui emoji", "segoe ui symbol",
    "noto color emoji", "revert", "var",
}
_FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
_FONT_FACE_RE = re.compile(r"@font-face\s*{[^}]*?font-family\s*:\s*([^;}]+)", re.I | re.S)


def _clean_font(name: str) -> str | None:
    n = name.strip().strip("'\"").strip()
    n = re.sub(r"\s*!important$", "", n)
    if not n or n.lower() in _GENERIC_FONTS or n.startswith("var(") or n.startswith("--"):
        return None
    if len(n) > 60 or "(" in n:
        return None
    return n


def _fonts_from_value(value: str) -> list[str]:
    fonts = []
    for part in value.split(","):
        f = _clean_font(part)
        if f:
            fonts.append(f)
    return fonts


def _google_families(href: str) -> list[str]:
    try:
        qs = parse_qs(urlparse(href).query)
    except ValueError:
        return []
    out = []
    for fam in qs.get("family", []):
        for f in fam.split("|"):
            name = f.split(":")[0].replace("+", " ").strip()
            if name:
                out.append(name)
    return out


# --------------------------------------------------------------------------- frameworks / iconos

_TAILWIND_RE = re.compile(
    r"(?:^|\s)(?:(?:sm|md|lg|xl|2xl|hover|focus|dark):[\w\-/\[\]\.]+|"
    r"(?:p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|gap|space-[xy])-\d+(?:\.\d)?|"
    r"text-(?:xs|sm|base|lg|xl|\dxl)|bg-[a-z]+-\d{2,3}|text-[a-z]+-\d{2,3}|rounded-(?:sm|md|lg|xl|full)|"
    r"font-(?:bold|semibold|medium|light)|items-center|justify-(?:center|between))(?=\s|$)"
)

_FRAMEWORK_CLASS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Bootstrap", re.compile(r"(?:^|\s)(?:col-(?:xs|sm|md|lg|xl)-\d+|btn-(?:primary|secondary|outline-\w+)|navbar-expand(?:-\w+)?|d-(?:flex|none|block)|form-control)(?=\s|$)")),
    ("Bulma", re.compile(r"(?:^|\s)(?:is-primary|columns|column\s|navbar-burger|is-size-\d|has-text-\w+)(?=\s|$)")),
    ("Foundation", re.compile(r"(?:^|\s)(?:small-\d+|medium-\d+|large-\d+|top-bar|callout|grid-x)(?=\s|$)")),
    ("Material UI (MUI)", re.compile(r"(?:^|\s)Mui[A-Z]\w+")),
    ("Chakra UI", re.compile(r"(?:^|\s)chakra-\w+")),
    ("Ant Design", re.compile(r"(?:^|\s)ant-\w+")),
    ("Material Design Lite", re.compile(r"(?:^|\s)mdl-\w+")),
    ("Materialize", re.compile(r"(?:^|\s)(?:waves-effect|materialize-\w+)")),
    ("UIkit", re.compile(r"(?:^|\s)uk-\w+")),
    ("Semantic UI", re.compile(r"(?:^|\s)ui (?:button|menu|grid|container|segment)(?=\s|$)")),
    ("Vuetify", re.compile(r"(?:^|\s)v-(?:application|btn|app-bar|card)\b")),
    ("Quasar", re.compile(r"(?:^|\s)q-(?:btn|layout|page)\b")),
    ("Mantine", re.compile(r"(?:^|\s)mantine-\w+")),
    ("DaisyUI", re.compile(r"(?:^|\s)(?:btn-ghost|drawer-toggle|navbar-start)(?=\s|$)")),
    ("PrimeFaces/PrimeNG", re.compile(r"(?:^|\s)p-(?:button|datatable|dialog)\b")),
    ("Elementor", re.compile(r"(?:^|\s)elementor-\w+")),
]

_FRAMEWORK_SHEET_PATTERNS: list[tuple[str, str]] = [
    ("Bootstrap", "bootstrap"), ("Tailwind CSS", "tailwind"), ("Bulma", "bulma"),
    ("Foundation", "foundation"), ("Materialize", "materialize"), ("UIkit", "uikit"),
    ("Semantic UI", "semantic"), ("Ant Design", "antd"), ("Material Design Lite", "material.min.css"),
    ("Pure.css", "pure-min"), ("Skeleton", "skeleton.css"), ("Vuetify", "vuetify"),
]

_ICON_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Font Awesome", re.compile(r"font-?awesome|fontawesome|kit\.fontawesome|(?:^|\s)fa[srbld]?\s+fa-|(?:^|\s)fa-(?:solid|regular|brands)", re.I)),
    ("Material Icons", re.compile(r"material-icons|Material\+Icons|material-symbols|Material\+Symbols", re.I)),
    ("Bootstrap Icons", re.compile(r"bootstrap-icons|(?:^|\s)bi\s+bi-|(?:^|\s)bi-[a-z]", re.I)),
    ("Ionicons", re.compile(r"ionicons|<ion-icon", re.I)),
    ("Heroicons", re.compile(r"heroicon", re.I)),
    ("Lucide", re.compile(r"lucide", re.I)),
    ("Feather Icons", re.compile(r"feather(?:-icons|\.min\.js)|data-feather", re.I)),
    ("Remix Icon", re.compile(r"remixicon|(?:^|\s)ri-[a-z]+-(?:line|fill)", re.I)),
    ("Boxicons", re.compile(r"boxicons|(?:^|\s)bx\s+bx-", re.I)),
    ("Line Awesome", re.compile(r"line-awesome", re.I)),
    ("Tabler Icons", re.compile(r"tabler-icon|@tabler/icons", re.I)),
]

_MEDIA_RE = re.compile(r"@media[^{]*?\(\s*(min|max)-width\s*:\s*([\d.]+)(px|em|rem)\s*\)", re.I)


def _collect_classes(tree) -> str:
    if tree is None:
        return ""
    parts: list[str] = []
    try:
        for node in tree.css("[class]"):
            cls = node.attributes.get("class")
            if cls:
                parts.append(" " + cls + " ")
                if len(parts) > 5000:
                    break
    except Exception:  # pragma: no cover - parser defensivo
        return ""
    return "\n".join(parts)


def _attr_values(tree, selector: str, attr: str) -> list[str]:
    if tree is None:
        return []
    out = []
    try:
        for node in tree.css(selector):
            v = node.attributes.get(attr)
            if v:
                out.append(v)
    except Exception:
        return []
    return out


# --------------------------------------------------------------------------- API

def page_design(page: PageResult, tree, computed: dict | None = None) -> DesignInfo:
    info = DesignInfo()
    css = page.css_text or ""
    html = page.html or ""

    # Colores
    counter: Counter[str] = Counter(_colors_in(css))
    for style in _attr_values(tree, "[style]", "style"):
        counter.update(_colors_in(style))
    for fill in _attr_values(tree, "[fill]", "fill") + _attr_values(tree, "[color]", "color"):
        c = normalize_color(fill)
        if c:
            counter[c] += 1
    # Solo los 24 más frecuentes
    info.colors = dict(counter.most_common(24))

    # Colores/fuentes computados por el navegador
    fonts: list[str] = []
    if computed:
        for key, val in computed.items():
            if not isinstance(val, str) or not val:
                continue
            if key.startswith("font"):
                fonts.extend(_fonts_from_value(val))
                continue
            c = normalize_color(val)
            if c:
                info.computed_colors[key] = c

    # Fuentes en CSS
    for m in _FONT_FACE_RE.finditer(css):
        fonts.extend(_fonts_from_value(m.group(1)))
    for m in _FONT_FAMILY_RE.finditer(css):
        fonts.extend(_fonts_from_value(m.group(1)))
    for style in _attr_values(tree, "[style]", "style"):
        for m in _FONT_FAMILY_RE.finditer(style):
            fonts.extend(_fonts_from_value(m.group(1)))

    sources: list[str] = []
    hrefs = _attr_values(tree, "link[href]", "href") + list(page.stylesheets)
    for href in hrefs:
        low = href.lower()
        if "fonts.googleapis.com" in low or "fonts.gstatic.com" in low:
            sources.append("Google Fonts")
            fonts.extend(_google_families(href))
        elif "use.typekit.net" in low or "p.typekit.net" in low:
            sources.append("Adobe Fonts (Typekit)")
        elif "fonts.bunny.net" in low:
            sources.append("Bunny Fonts")
            fonts.extend(_google_families(href))
        elif "fast.fonts.net" in low:
            sources.append("Fonts.com")
    if "@import" in css and "fonts.googleapis.com" in css:
        sources.append("Google Fonts")
        for m in re.finditer(r"@import\s+url\(['\"]?([^'\")]+)", css):
            if "fonts.googleapis.com" in m.group(1):
                fonts.extend(_google_families(m.group(1)))
    if "@font-face" in css:
        sources.append("Fuentes propias (@font-face)")
    info.fonts = _dedup(fonts)[:15]
    info.font_sources = _dedup(sources)

    # Frameworks CSS
    classes = _collect_classes(tree)
    frameworks: list[str] = []
    if len(_TAILWIND_RE.findall(classes)) >= 8:
        frameworks.append("Tailwind CSS")
    for name, rx in _FRAMEWORK_CLASS_PATTERNS:
        if len(rx.findall(classes)) >= 2:
            frameworks.append(name)
    sheet_text = " ".join(page.stylesheets + page.scripts).lower()
    for name, needle in _FRAMEWORK_SHEET_PATTERNS:
        if needle in sheet_text:
            frameworks.append(name)
    if "--tw-" in css:
        frameworks.append("Tailwind CSS")
    info.css_frameworks = _dedup(frameworks)

    # Iconos
    icon_haystack = " ".join([classes, " ".join(hrefs), " ".join(page.scripts)])
    icons = [name for name, rx in _ICON_PATTERNS if rx.search(icon_haystack)]
    if not icons and "<ion-icon" in html.lower():
        icons.append("Ionicons")
    if tree is not None and not icons:
        try:
            if len(tree.css("svg")) >= 5:
                icons.append("SVG inline")
        except Exception:
            pass
    info.icon_libraries = _dedup(icons)

    # Breakpoints
    bps: set[tuple[str, float, str]] = set()
    for m in _MEDIA_RE.finditer(css):
        bps.add((m.group(1).lower(), float(m.group(2)), m.group(3).lower()))
    info.breakpoints = [f"{k}-width: {v:g}{u}" for k, v, u in sorted(bps, key=lambda x: (x[2], x[1], x[0]))][:20]

    # Meta
    info.viewport = page.viewport or _first_attr(tree, 'meta[name="viewport"]', "content")
    info.theme_color = page.theme_color or _first_attr(tree, 'meta[name="theme-color"]', "content")
    info.favicon = _favicon(tree)

    # Landmarks
    landmarks = {}
    for tag, role in (("header", "banner"), ("nav", "navigation"), ("main", "main"),
                      ("footer", "contentinfo"), ("aside", "complementary")):
        found = False
        if tree is not None:
            try:
                found = bool(tree.css_first(tag) or tree.css_first(f'[role="{role}"]'))
            except Exception:
                found = False
        landmarks[tag] = found
    info.landmarks = landmarks

    info.dark_mode = bool(
        re.search(r"prefers-color-scheme\s*:\s*dark", css, re.I)
        or re.search(r"(?:^|\s)dark:[\w-]", classes)
        or re.search(r"(?:^|\s)(?:dark|dark-mode|theme-dark)(?=\s|$)", classes)
        or re.search(r"\[data-theme=['\"]?dark", css)
    )
    vp = (info.viewport or "").lower().replace(" ", "")
    info.responsive = "width=device-width" in vp or bool(info.breakpoints)
    return info


def merge_designs(designs: list[DesignInfo]) -> DesignInfo:
    designs = [d for d in designs if d is not None]
    out = DesignInfo()
    if not designs:
        return out
    colors: Counter[str] = Counter()
    computed_votes: dict[str, Counter[str]] = {}
    fonts: Counter[str] = Counter()
    landmarks: dict[str, bool] = {}
    for d in designs:
        colors.update(d.colors)
        for k, v in d.computed_colors.items():
            computed_votes.setdefault(k, Counter())[v] += 1
        fonts.update(d.fonts)
        for k, v in d.landmarks.items():
            landmarks[k] = landmarks.get(k, False) or v
    out.colors = dict(colors.most_common(24))
    out.computed_colors = {k: c.most_common(1)[0][0] for k, c in computed_votes.items()}
    out.fonts = [f for f, _ in fonts.most_common(15)]
    out.font_sources = _dedup(x for d in designs for x in d.font_sources)
    out.css_frameworks = _dedup(x for d in designs for x in d.css_frameworks)
    out.icon_libraries = _dedup(x for d in designs for x in d.icon_libraries)
    out.breakpoints = _dedup(x for d in designs for x in d.breakpoints)[:20]
    out.viewport = next((d.viewport for d in designs if d.viewport), "")
    out.theme_color = next((d.theme_color for d in designs if d.theme_color), "")
    out.favicon = next((d.favicon for d in designs if d.favicon), "")
    out.landmarks = landmarks
    out.dark_mode = any(d.dark_mode for d in designs)
    out.responsive = any(d.responsive for d in designs)
    return out


# --------------------------------------------------------------------------- helpers

def _dedup(items) -> list[str]:
    seen: set[str] = set()
    out = []
    for i in items:
        key = i.lower() if isinstance(i, str) else i
        if i and key not in seen:
            seen.add(key)
            out.append(i)
    return out


def _first_attr(tree, selector: str, attr: str) -> str:
    if tree is None:
        return ""
    try:
        node = tree.css_first(selector)
    except Exception:
        return ""
    return (node.attributes.get(attr) or "").strip() if node else ""


def _favicon(tree) -> str:
    if tree is None:
        return ""
    try:
        for node in tree.css("link[rel][href]"):
            rel = (node.attributes.get("rel") or "").lower()
            if "icon" in rel.split() or rel in ("shortcut icon", "apple-touch-icon"):
                return node.attributes.get("href") or ""
    except Exception:
        return ""
    return ""
