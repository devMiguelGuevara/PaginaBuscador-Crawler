from selectolax.lexbor import LexborHTMLParser

from crawler.analyzers.forms import extract_forms

URL = "https://ejemplo.com/login"

LOGIN = """
<html><body>
<form action="/session" method="post" id="login-form">
  <input type="hidden" name="csrf_token" value="abc">
  <label for="u">Usuario</label><input id="u" name="username" type="text" required>
  <label>Contraseña <input name="password" type="password" required autocomplete="current-password"></label>
  <div class="g-recaptcha" data-sitekey="x"></div>
  <button type="submit">Iniciar sesión</button>
</form>
</body></html>
"""

REGISTER = """
<form action="/signup" method="POST">
  <input name="name" placeholder="Nombre">
  <input name="email" type="email" aria-label="Correo electrónico">
  <input name="password" type="password" autocomplete="new-password">
  <input name="password_confirm" type="password">
  <button>Crear cuenta</button>
</form>
"""

SEARCH = """
<form role="search" action="/buscar"><input type="search" name="q" placeholder="Buscar..."><button>Ir</button></form>
<form action="/contacto" method="post"><input name="nombre"><input type="email" name="email">
<textarea name="mensaje"></textarea><button>Enviar</button></form>
<form action="/subscribe" method="post"><input type="email" name="email" placeholder="Tu email">
<button>Suscríbete al newsletter</button></form>
"""

SPA = """
<div id="root"><div class="card"><h2>Welcome back</h2>
<input type="email" placeholder="Email"><input type="password" placeholder="Password">
<button>Sign in</button></div></div>
"""


def _forms(html):
    return extract_forms(LexborHTMLParser(html), URL)


def test_login_form_with_csrf_and_captcha():
    (f,) = _forms(LOGIN)
    assert f.kind == "login"
    assert f.method == "POST"
    assert f.action == "https://ejemplo.com/session"
    assert f.has_csrf and f.csrf_field == "csrf_token"
    assert f.captcha == "reCAPTCHA"
    assert f.submit_text == "Iniciar sesión"
    labels = {x.name: x.label for x in f.fields}
    assert labels["username"] == "Usuario"
    assert "Contraseña" in labels["password"]
    assert all(x.required for x in f.fields if x.type != "hidden")


def test_register_form():
    (f,) = _forms(REGISTER)
    assert f.kind == "register"
    assert not f.has_csrf
    assert {x.label for x in f.fields} >= {"Nombre", "Correo electrónico"}


def test_search_contact_newsletter():
    kinds = [f.kind for f in _forms(SEARCH)]
    assert kinds == ["search", "contact", "newsletter"]


def test_spa_password_without_form():
    forms = _forms(SPA)
    assert len(forms) == 1
    f = forms[0]
    assert f.kind == "login"
    assert f.form_id == "(sin form)"
    assert [x.type for x in f.fields] == ["email", "password"]
    assert f.submit_text == "Sign in"


CART = """
<form><input type="hidden" name="product_id" value="1"><button type="submit">Add to basket</button></form>
<form method="post"><select name="qty"><option>1</option></select><button>Añadir al carrito</button></form>
"""


def test_add_to_cart_without_action():
    forms = _forms(CART)
    assert [f.kind for f in forms] == ["add_to_cart", "add_to_cart"]
    assert all(f.action == "" for f in forms)


def test_no_tree():
    assert extract_forms(None, URL) == []
