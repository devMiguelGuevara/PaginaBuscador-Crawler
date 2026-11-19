from selectolax.lexbor import LexborHTMLParser

from crawler.analyzers.design import merge_designs, normalize_color, page_design
from crawler.models import PageResult

HTML = """<!doctype html><html lang="es"><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0f172a">
<link rel="icon" href="/favicon.ico">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&family=Roboto+Slab&display=swap">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
</head><body>
<header class="flex items-center justify-between px-4 py-2 bg-slate-900 text-white"><nav class="md:flex gap-4">
<a class="text-sm font-bold" href="/">Inicio</a></nav></header>
<main class="mx-auto mt-4 p-4 rounded-lg"><i class="fa-solid fa-user"></i>
<div style="color: rgb(255, 0, 0); background: hsl(120, 100%, 25%)">x</div></main>
<footer class="dark:bg-black text-lg">f</footer>
</body></html>"""

CSS = """
body { font-family: 'Inter', system-ui, sans-serif; color: #333; background: #FFFFFF; }
h1 { font-family: "Roboto Slab", serif; color: #333333; }
.btn { background: rgba(0,0,0,0); border-color: #0af; }
@font-face { font-family: 'MiFuente'; src: url(/f.woff2); }
@media (min-width: 768px) { .a { color: #123456 } }
@media screen and (max-width: 480px) { .b { color: #fff } }
@media (prefers-color-scheme: dark) { body { background: #000 } }
"""


def _page() -> PageResult:
    p = PageResult(url="https://ej.com/", html=HTML, css_text=CSS,
                   stylesheets=["https://fonts.googleapis.com/css2?family=Inter"])
    return p


def test_normalize_color():
    assert normalize_color("#FFF") == "#ffffff"
    assert normalize_color("#abcdef80") == "#abcdef"
    assert normalize_color("#abcdef00") is None
    assert normalize_color("rgb(255, 0, 0)") == "#ff0000"
    assert normalize_color("rgb(255 0 0 / 50%)") == "#ff0000"
    assert normalize_color("rgba(0,0,0,0)") is None
    assert normalize_color("hsl(120, 100%, 25%)") == "#008000"
    assert normalize_color("transparent") is None
    assert normalize_color("nonsense") is None


def test_page_design_full():
    page = _page()
    tree = LexborHTMLParser(HTML)
    computed = {"body_bg": "rgb(255, 255, 255)", "text": "rgb(51, 51, 51)", "button_bg": "rgba(0, 0, 0, 0)",
                "font_body": "Inter, system-ui, sans-serif", "font_heading": '"Roboto Slab", serif'}
    d = page_design(page, tree, computed)
    assert d.colors["#333333"] == 2
    assert "#ff0000" in d.colors and "#008000" in d.colors
    assert d.computed_colors == {"body_bg": "#ffffff", "text": "#333333"}
    assert d.fonts[:2] == ["Inter", "Roboto Slab"]
    assert "MiFuente" in d.fonts
    assert "Google Fonts" in d.font_sources
    assert "Tailwind CSS" in d.css_frameworks
    assert "Font Awesome" in d.icon_libraries
    assert "min-width: 768px" in d.breakpoints and "max-width: 480px" in d.breakpoints
    assert d.viewport.startswith("width=device-width")
    assert d.theme_color == "#0f172a"
    assert d.favicon == "/favicon.ico"
    assert d.landmarks == {"header": True, "nav": True, "main": True, "footer": True, "aside": False}
    assert d.dark_mode and d.responsive


def test_page_design_without_tree():
    d = page_design(PageResult(url="https://x.com/"), None, None)
    assert d.colors == {} and d.fonts == [] and not d.responsive


def test_merge_designs():
    a = page_design(_page(), LexborHTMLParser(HTML), {"text": "#111"})
    b = page_design(PageResult(url="https://ej.com/b", css_text="p{color:#333}"), None, {"text": "#111"})
    m = merge_designs([a, b])
    assert m.colors["#333333"] == 3
    assert m.computed_colors["text"] == "#111111"
    assert m.landmarks["header"] is True
    assert "Tailwind CSS" in m.css_frameworks
    assert merge_designs([]).colors == {}
