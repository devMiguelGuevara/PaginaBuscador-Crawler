"""Etiquetas en español para valores internos (tipos de formulario, etc.)."""

FORM_KINDS = {
    "login": "Inicio de sesión",
    "register": "Registro",
    "password_reset": "Recuperar contraseña",
    "search": "Búsqueda",
    "contact": "Contacto",
    "newsletter": "Newsletter",
    "payment": "Pago",
    "comment": "Comentario",
    "add_to_cart": "Añadir al carrito",
    "other": "Otro",
}


def form_kind(kind: str) -> str:
    return FORM_KINDS.get(kind or "other", kind or "Otro")
