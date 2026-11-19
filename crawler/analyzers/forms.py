"""Extracción y clasificación de formularios."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from ..models import FieldInfo, FormInfo

CSRF_RE = re.compile(
    r"csrf|xsrf|_token|authenticity_token|__requestverificationtoken|nonce|csrfmiddlewaretoken", re.I
)
CAPTCHA_CLASSES = {
    "g-recaptcha": "reCAPTCHA",
    "h-captcha": "hCaptcha",
    "cf-turnstile": "Cloudflare Turnstile",
    "frc-captcha": "Friendly Captcha",
}
CAPTCHA_SCRIPTS = {
    "recaptcha": "reCAPTCHA",
    "hcaptcha.com": "hCaptcha",
    "challenges.cloudflare.com/turnstile": "Cloudflare Turnstile",
    "friendlycaptcha": "Friendly Captcha",
}

FIELD_TAGS = "input, select, textarea"
SKIP_INPUT_TYPES = {"submit", "button", "image", "reset"}

_KW = {
    "password_reset": re.compile(
        r"forgot|reset|recover|olvid|recuper|restablec|restaurar", re.I),
    "register": re.compile(
        r"regist|sign.?up|signup|create.?account|crear.?cuenta|join|nueva.?cuenta|confirm|repeat|repetir", re.I),
    "login": re.compile(
        r"log.?in|sign.?in|signin|iniciar|ingresar|acceder|entrar|auth|session|sesi[oó]n", re.I),
    "search": re.compile(r"search|buscar|busca|b[uú]squeda|query|\bq\b|\bs\b|find", re.I),
    "newsletter": re.compile(r"newsletter|subscri|suscri|bolet[ií]n|mailing", re.I),
    "payment": re.compile(r"card|tarjeta|cvv|cvc|ccnum|cc-number|expir|vencim|checkout|pago|payment|billing", re.I),
    "comment": re.compile(r"comment|comentario|reply|respuesta|review|rese[nñ]a", re.I),
    "add_to_cart": re.compile(r"add.?to.?(basket|cart|bag)|a[nñ]adir (al|a la) (carrito|cesta|bolsa)|"
                              r"agregar al carrito|\bcomprar\b|buy now|comprar ahora|add-to-cart|addtocart", re.I),
    "contact": re.compile(r"contact|mensaje|message|asunto|subject|consulta|inquiry|tel[eé]fono|phone", re.I),
}


def _attr(node, name: str) -> str:
    v = node.attributes.get(name)
    return v.strip() if isinstance(v, str) else ""


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.text(strip=True) or "").strip()


def _label_for(node, tree, labels_by_id: dict[str, str]) -> str:
    fid = _attr(node, "id")
    if fid and fid in labels_by_id:
        return labels_by_id[fid]
    parent = node.parent
    depth = 0
    while parent is not None and depth < 4:
        if parent.tag == "label":
            return _text(parent)[:120]
        parent = parent.parent
        depth += 1
    for a in ("aria-label", "title", "placeholder"):
        v = _attr(node, a)
        if v:
            return v[:120]
    lb = _attr(node, "aria-labelledby")
    if lb and tree is not None:
        el = tree.css_first(f"#{lb.split()[0]}") if re.match(r"^[A-Za-z][\w\-]*$", lb.split()[0]) else None
        if el is not None:
            return _text(el)[:120]
    return ""


def _field(node, tree, labels_by_id) -> FieldInfo | None:
    tag = node.tag
    if tag == "input":
        ftype = (_attr(node, "type") or "text").lower()
        if ftype in SKIP_INPUT_TYPES:
            return None
    elif tag == "select":
        ftype = "select"
    else:
        ftype = "textarea"
    return FieldInfo(
        name=_attr(node, "name") or _attr(node, "id"),
        type=ftype,
        label=_label_for(node, tree, labels_by_id),
        placeholder=_attr(node, "placeholder"),
        required="required" in node.attributes or _attr(node, "aria-required") == "true",
        autocomplete=_attr(node, "autocomplete"),
    )


def _submit_text(container) -> str:
    for sel in ("button[type=submit]", "input[type=submit]", "button:not([type])", "button", "input[type=image]",
                "[role=button]"):
        el = container.css_first(sel)
        if el is not None:
            t = _text(el) or _attr(el, "value") or _attr(el, "aria-label") or _attr(el, "alt")
            if t:
                return t[:80]
    return ""


def _detect_captcha(container, tree) -> str | None:
    for cls, name in CAPTCHA_CLASSES.items():
        if container.css_first(f".{cls}") is not None:
            return name
    if container.css_first("iframe[src*='recaptcha']") is not None:
        return "reCAPTCHA"
    if tree is not None:
        for s in tree.css("script[src]"):
            src = _attr(s, "src").lower()
            for key, name in CAPTCHA_SCRIPTS.items():
                if key in src:
                    return name
    return None


def classify(fields: list[FieldInfo], context: str) -> str:
    """Infiere el tipo de formulario a partir de sus campos y del texto de contexto."""
    types = [f.type for f in fields if f.type != "hidden"]
    blob_fields = " ".join(f"{f.name} {f.label} {f.placeholder} {f.autocomplete}" for f in fields)
    blob = f"{context} {blob_fields}"
    n_pwd = types.count("password")
    autocompletes = " ".join(f.autocomplete for f in fields).lower()

    if n_pwd >= 2 or "new-password" in autocompletes:
        if _KW["password_reset"].search(context) and not _KW["register"].search(context.replace("confirm", "")):
            return "password_reset"
        return "register"
    if n_pwd == 1:
        if _KW["register"].search(context) and not _KW["login"].search(context):
            return "register"
        visible = [t for t in types if t not in ("checkbox", "radio")]
        if len(visible) >= 4 and _KW["register"].search(blob):
            return "register"
        return "login"
    if _KW["payment"].search(blob_fields) or "cc-" in autocompletes:
        return "payment"
    if _KW["password_reset"].search(context) and len(types) <= 2:
        return "password_reset"
    if types and all(t in ("search", "text", "select") for t in types) and len(types) <= 3 and (
            "search" in types or _KW["search"].search(blob)):
        return "search"
    if "textarea" in types:
        if _KW["comment"].search(blob):
            return "comment"
        return "contact"
    if _KW["newsletter"].search(blob) and len(types) <= 3 and "email" in " ".join(types + [blob_fields.lower()]):
        return "newsletter"
    if _KW["register"].search(context) and ("email" in types or "tel" in types):
        return "register"
    if _KW["login"].search(context) and ("email" in types or "text" in types) and len(types) <= 2:
        return "login"  # login en dos pasos (primero email/usuario)
    if _KW["contact"].search(blob):
        return "contact"
    if _KW["newsletter"].search(blob):
        return "newsletter"
    return "other"


def _build(container, tree, page_url: str, labels_by_id: dict[str, str], fields_nodes, *,
           action: str, method: str, form_id: str) -> FormInfo:
    fields: list[FieldInfo] = []
    csrf_field = ""
    for n in fields_nodes:
        f = _field(n, tree, labels_by_id)
        if f is None:
            continue
        if f.type == "hidden" and not csrf_field and CSRF_RE.search(f.name):
            csrf_field = f.name
        fields.append(f)
    submit = _submit_text(container)
    heading = ""
    for sel in ("h1", "h2", "h3", "legend"):
        el = container.css_first(sel)
        if el is not None:
            heading = _text(el)
            break
    context = " ".join([action, form_id, _attr(container, "class"), _attr(container, "name"),
                        _attr(container, "role"), _attr(container, "aria-label"), submit, heading])
    visible = [f for f in fields if f.type not in ("hidden", "select", "radio", "number")]
    if _attr(container, "role") == "search":
        kind = "search"
    elif not any(f.type == "password" for f in fields) and len(visible) <= 1 and \
            _KW["add_to_cart"].search(context):
        kind = "add_to_cart"
    else:
        kind = classify(fields, context)
    return FormInfo(
        page_url=page_url,
        action=urljoin(page_url, action) if action else "",
        method=(method or "GET").upper(),
        form_id=form_id,
        kind=kind,
        fields=fields,
        has_csrf=bool(csrf_field),
        csrf_field=csrf_field,
        captcha=_detect_captcha(container, tree),
        submit_text=submit,
    )


def _inside_form(node) -> bool:
    p = node.parent
    while p is not None:
        if p.tag == "form":
            return True
        p = p.parent
    return False


def extract_forms(tree, page_url: str) -> list[FormInfo]:
    if tree is None:
        return []
    labels_by_id: dict[str, str] = {}
    for lb in tree.css("label[for]"):
        key = _attr(lb, "for")
        if key:
            labels_by_id[key] = _text(lb)[:120]

    forms: list[FormInfo] = []
    for form in tree.css("form"):
        info = _build(
            form, tree, page_url, labels_by_id, form.css(FIELD_TAGS),
            action=_attr(form, "action"), method=_attr(form, "method") or "GET",
            form_id=_attr(form, "id") or _attr(form, "name"),
        )
        if not info.fields and not info.submit_text:
            continue  # <form> usado solo como contenedor: sin campos ni botón
        forms.append(info)

    # SPAs: inputs de contraseña fuera de <form>
    orphan_pwd = [n for n in tree.css("input[type=password]") if not _inside_form(n)]
    if orphan_pwd:
        container = orphan_pwd[0].parent
        # sube hasta un contenedor que agrupe varios campos
        for _ in range(6):
            if container is None or container.parent is None:
                break
            if len([n for n in container.css(FIELD_TAGS) if not _inside_form(n)]) >= 2 and \
                    container.css_first("button, [role=button], input[type=submit]") is not None:
                break
            container = container.parent
        if container is None:
            container = tree.body or tree.root
        nodes = [n for n in container.css(FIELD_TAGS) if not _inside_form(n)]
        info = _build(container, tree, page_url, labels_by_id, nodes,
                      action="", method="POST", form_id="(sin form)")
        if info.kind not in ("register", "password_reset"):
            info.kind = "login"
        forms.append(info)
    return forms
