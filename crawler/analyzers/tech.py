"""Detección de tecnologías (estilo Wappalyzer) con huellas curadas."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from ..models import PageResult, TechHit

FINGERPRINTS = Path(__file__).resolve().parent.parent / "fingerprints" / "technologies.json"
HTML_LIMIT = 300_000


def _compile(pattern: str) -> re.Pattern | None:
    try:
        return re.compile(pattern, re.I) if pattern else None
    except re.error:
        return None


def _skip_group(s: str, i: int) -> int:
    """Devuelve el índice posterior al grupo `(...)` o clase `[...]` que empieza en i."""
    n = len(s)
    if s[i] == "[":
        i += 1
        while i < n and s[i] != "]":
            i += 2 if s[i] == "\\" else 1
        return i + 1
    depth = 0
    while i < n:
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":
            i = _skip_group(s, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _split_branches(pattern: str) -> list[str]:
    out, cur, depth, in_cls, i = [], [], 0, False, 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            cur.append(pattern[i:i + 2])
            i += 2
            continue
        if in_cls:
            in_cls = ch != "]"
        elif ch == "[":
            in_cls = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "|" and depth == 0:
            out.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def _longest_literal(branch: str) -> str:
    runs: list[str] = []
    cur, i, n = "", 0, len(branch)
    while i < n:
        ch = branch[i]
        if ch in "([":
            runs.append(cur)
            cur = ""
            i = _skip_group(branch, i)
        elif ch == "\\":
            nxt = branch[i + 1:i + 2]
            i += 2
            if nxt and not nxt.isalnum():
                cur += nxt
            else:
                runs.append(cur)
                cur = ""
        elif ch in "*?{":
            runs.append(cur[:-1])  # el carácter cuantificado es opcional
            cur = ""
            if ch == "{":
                j = branch.find("}", i)
                i = j + 1 if j != -1 else n
            else:
                i += 1
        elif ch in "+.^$":
            runs.append(cur)
            cur = ""
            i += 1
        else:
            cur += ch
            i += 1
    runs.append(cur)
    return max(runs, key=len)


def prefilter(pattern: str, min_len: int = 3) -> tuple[str, ...] | None:
    """Literales obligatorios (uno por rama, en minúscula) para descartar un regex sin ejecutarlo.

    Devuelve None si alguna rama no tiene un literal fiable (entonces hay que ejecutar el regex siempre).
    """
    lits: list[str] = []
    for branch in _split_branches(pattern):
        lit = _longest_literal(branch).lower()
        if len(lit) < min_len:
            return None
        lits.append(lit)
    return tuple(lits)


def could_match(lits: tuple[str, ...] | None, text_lower: str) -> bool:
    return lits is None or any(lit in text_lower for lit in lits)


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    raw = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
    db: dict[str, dict] = {}
    for name, fp in raw.items():
        c: dict = {
            "cats": fp.get("cats", ["Otros"]),
            "website": fp.get("website", ""),
            "implies": fp.get("implies", []),
            "headers": {k.lower(): _compile(v) for k, v in fp.get("headers", {}).items()},
            "cookies": [(_compile("^" + k + "$"), _compile(v)) for k, v in fp.get("cookies", {}).items()],
            "meta": {k.lower(): _compile(v) for k, v in fp.get("meta", {}).items()},
            "scriptSrc": [p for p in (_compile(x) for x in fp.get("scriptSrc", [])) if p],
            "html": [(p, prefilter(x)) for x in fp.get("html", []) if (p := _compile(x))],
            "url": [p for p in (_compile(x) for x in fp.get("url", [])) if p],
            "js": list(fp.get("js", [])),
        }
        # Cabeceras con nombre regex (p. ej. "x-vtex-.*")
        c["header_patterns"] = [(_compile("^" + k + "$"), v) for k, v in c["headers"].items()
                                if any(ch in k for ch in "*.[]")]
        db[name] = c
    return db


def js_probe_names() -> list[str]:
    """Todas las rutas de globals JS a comprobar en el navegador."""
    names: list[str] = []
    for fp in _load().values():
        for j in fp["js"]:
            if j not in names:
                names.append(j)
    return names


def _version(m: re.Match | None) -> str | None:
    if not m:
        return None
    try:
        v = m.group("version")
    except (IndexError, KeyError):
        return None
    return v or None


def _meta_tags(page: PageResult, tree) -> dict[str, list[str]]:
    metas: dict[str, list[str]] = {}
    if page.generator:
        metas.setdefault("generator", []).append(page.generator)
    if tree is not None:
        for m in tree.css("meta[name][content]"):
            name = (m.attributes.get("name") or "").lower()
            content = m.attributes.get("content") or ""
            if name and content and content not in metas.get(name, []):
                metas.setdefault(name, []).append(content)
    return metas


def detect(page: PageResult, tree) -> list[TechHit]:
    db = _load()
    headers = {k.lower(): v for k, v in page.headers.items()}
    cookie_names = [c.name for c in page.cookies]
    metas = _meta_tags(page, tree)
    scripts = list(page.scripts)
    if tree is not None and not scripts:
        scripts = [s.attributes.get("src") or "" for s in tree.css("script[src]")]
    html = (page.html or "")[:HTML_LIMIT]
    html_lower = html.lower()
    urls =[page.final_url or page.url] + [c.url for c in page.api_calls]
    js_globals = set(page.js_globals)

    found: dict[str, TechHit] = {}

    def hit(name: str, evidence: str, version: str | None = None, confidence: int = 100) -> None:
        fp = db[name]
        h = found.get(name)
        if h is None:
            h = TechHit(name=name, category=fp["cats"][0], confidence=confidence, website=fp["website"])
            found[name] = h
        else:
            h.confidence = max(h.confidence, confidence)
        if version and not h.version:
            h.version = version
        if evidence and evidence not in h.evidence and len(h.evidence) < 5:
            h.evidence.append(evidence[:160])

    for name, fp in db.items():
        # Cabeceras
        for hname, rx in fp["headers"].items():
            if hname in headers:
                val = headers[hname]
                if rx is None:
                    hit(name, f"cabecera {hname}")
                else:
                    m = rx.search(val)
                    if m:
                        hit(name, f"cabecera {hname}: {val[:60]}", _version(m))
        for krx, _vrx in fp["header_patterns"]:
            if krx is None:
                continue
            for hname in headers:
                if krx.match(hname):
                    hit(name, f"cabecera {hname}")
                    break
        # Cookies
        for krx, vrx in fp["cookies"]:
            if krx is None:
                continue
            for cn in cookie_names:
                if krx.match(cn):
                    hit(name, f"cookie {cn}")
                    break
        # Meta
        for mname, rx in fp["meta"].items():
            for content in metas.get(mname, []):
                m = rx.search(content) if rx else None
                if rx is None or m:
                    hit(name, f"meta {mname}: {content[:60]}", _version(m))
        # Scripts
        for rx in fp["scriptSrc"]:
            for src in scripts:
                m = rx.search(src)
                if m:
                    hit(name, f"script {src[:100]}", _version(m))
                    break
        # HTML
        if html:
            for rx, lits in fp["html"]:
                if not could_match(lits, html_lower):
                    continue
                m = rx.search(html)
                if m:
                    hit(name, f"HTML «{m.group(0)[:60]}»", _version(m), confidence=80)
        # URL
        for rx in fp["url"]:
            for u in urls:
                if rx.search(u):
                    hit(name, f"URL {u[:100]}", confidence=90)
                    break
        # Globals JS
        for j in fp["js"]:
            if j in js_globals:
                hit(name, f"JS global {j}")

    # Versiones reportadas por el navegador ("React.version=18.2.0")
    for g in page.js_globals:
        if "=" in g:
            key, _, val = g.partition("=")
            for name, fp in db.items():
                if key in fp["js"]:
                    hit(name, f"JS global {key}", val.strip() or None)

    # Implicaciones
    queue = list(found)
    while queue:
        name = queue.pop()
        for imp in db[name]["implies"]:
            if imp in db and imp not in found:
                hit(imp, f"implicado por {name}", confidence=70)
                queue.append(imp)
    return list(found.values())


def merge(hits: list[TechHit]) -> list[TechHit]:
    merged: dict[str, TechHit] = {}
    for h in hits:
        cur = merged.get(h.name)
        if cur is None:
            merged[h.name] = h.model_copy(deep=True)
            merged[h.name].evidence = merged[h.name].evidence[:5]
            continue
        cur.confidence = max(cur.confidence, h.confidence)
        if h.version and not cur.version:
            cur.version = h.version
        for e in h.evidence:
            if e not in cur.evidence and len(cur.evidence) < 5:
                cur.evidence.append(e)
    return sorted(merged.values(), key=lambda t: (t.category, -t.confidence, t.name))
