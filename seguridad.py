# -*- coding: utf-8 -*-
"""
Protecciones de seguridad comunes a todo el servidor, activadas con una sola llamada: seguridad.iniciar(app).

  - Clave de las sesiones: nunca se usa una clave conocida.
  - Cookie de sesión: solo por HTTPS, no accesible desde JavaScript y caduca a las 12 horas.
  - CSRF: todo formulario POST lleva un código oculto que se comprueba (se añade solo a las páginas HTML).
  - Cabeceras de seguridad y páginas privadas sin caché.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import timedelta

from flask import request, session

log = logging.getLogger("seguridad")

_FORM_POST = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
_METODO_POST = re.compile(r"""method\s*=\s*["']?post["']?""", re.IGNORECASE)
_SIN_CSRF = ("/webhook/", "/tareas/")  # los llaman servicios externos con su propia firma o clave

CABECERAS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
}


def _clave_sesiones():
    clave = os.environ.get("FLASK_SECRET_KEY", "")
    if clave and clave != "cambia-esto-en-produccion":
        return clave
    base = os.environ.get("FERNET_KEY", "")
    if base:
        log.warning("FLASK_SECRET_KEY no está definida: se deriva de otra clave secreta")
        return hashlib.sha256(("sesiones:" + base).encode()).hexdigest()
    log.warning("FLASK_SECRET_KEY no está definida: se usa una clave aleatoria (las sesiones se cierran al reiniciar)")
    return secrets.token_hex(32)


def _token_csrf():
    if not session.get("csrf_token"):
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def iniciar(app):
    app.secret_key = _clave_sesiones()
    app.config.update(
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SEGURA", "1") != "0",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",   # Lax permite volver de Microsoft, Google y Stripe
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=40 * 1024 * 1024,
    )

    @app.before_request
    def _comprobar_csrf():
        if request.method in ("GET", "HEAD", "OPTIONS") or request.path.startswith(_SIN_CSRF):
            return None
        enviado = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        esperado = session.get("csrf_token", "")
        if not esperado or not hmac.compare_digest(esperado.encode(), enviado.encode()):
            log.warning("POST rechazado por falta de código CSRF: %s", request.path)
            return ("<p style='font-family:sans-serif;padding:32px'>La página ha caducado. "
                    "Vuelva atrás, recárguela e inténtelo de nuevo.</p>", 400)
        return None

    @app.after_request
    def _despues(resp):
        for nombre, valor in CABECERAS.items():
            resp.headers.setdefault(nombre, valor)
        if resp.mimetype == "text/html" and not resp.direct_passthrough:
            resp.headers["Cache-Control"] = "no-store"
            cuerpo = resp.get_data(as_text=True)
            if "<form" in cuerpo.lower():
                campo = f'<input type="hidden" name="csrf_token" value="{_token_csrf()}">'

                def _anadir(m):
                    etiqueta = m.group(0)
                    return etiqueta + campo if _METODO_POST.search(etiqueta) else etiqueta
                resp.set_data(_FORM_POST.sub(_anadir, cuerpo))
        return resp


# ---------------------------------------------------------------------------
# Contraseñas: 8 caracteres con mayúscula, minúscula, número y símbolo; y se rechazan las típicas
# ---------------------------------------------------------------------------

_COMUNES = {
    "123456", "1234567", "12345678", "123456789", "1234567890", "12345678910", "0123456789", "111111", "000000",
    "password", "password1", "password123", "passw0rd", "contrasena", "contraseña", "contrasena1", "contraseña1",
    "contrasena123", "contraseña123", "qwerty", "qwerty123", "qwertyuiop", "qwertyuiop123", "abc123", "abcd1234",
    "asdfghjkl", "zxcvbnm", "iloveyou", "admin", "admin123", "administrador", "letmein", "welcome", "bienvenido",
    "gestoria", "gestoria123", "gestoria2024", "gestoria2025", "gestoria2026", "facturas", "facturas123",
    "123123123", "1q2w3e4r", "1qaz2wsx", "q1w2e3r4", "mypassword", "changeme", "cambiame", "clave123", "clave1234",
    "coche-verde", "madrid", "barcelona", "valencia", "alicante", "futbol", "realmadrid", "barcelona1", "sevilla",
}


def contrasena_debil(password, email=""):
    """Devuelve un mensaje (en usted) si la contraseña es demasiado fácil de adivinar; None si vale."""
    p = password or ""
    minusculas = p.lower()
    if len(p) < 8:
        return "La contraseña debe tener al menos 8 caracteres."
    faltan = []
    if not any(c.isupper() for c in p):
        faltan.append("una mayúscula")
    if not any(c.islower() for c in p):
        faltan.append("una minúscula")
    if not any(c.isdigit() for c in p):
        faltan.append("un número")
    if not any(not c.isalnum() for c in p):
        faltan.append("un símbolo (por ejemplo ! ? - _ . @ #)")
    if faltan:
        return "A la contraseña le falta " + ", ".join(faltan[:-1]) + (" y " if len(faltan) > 1 else "") + faltan[-1] + "."
    if minusculas in _COMUNES or minusculas.rstrip("0123456789!.") in _COMUNES:
        return "Esa contraseña es de las más usadas y se adivina enseguida. Elija otra."
    if len(set(minusculas)) <= 3:
        return "La contraseña es demasiado repetitiva. Elija otra."
    if all(c.isdigit() for c in p):
        return "Una contraseña solo de números es muy fácil de adivinar. Añada letras."
    local = (email or "").split("@")[0].lower()
    if len(local) >= 4 and local in minusculas:
        return "La contraseña no debe contener su email. Elija otra."
    secuencias = ("abcdefghijklmnopqrstuvwxyz", "qwertyuiopasdfghjklzxcvbnm", "0123456789")
    if any(minusculas in s or minusculas[::-1] in s for s in secuencias):
        return "Esa contraseña es una secuencia muy fácil de adivinar. Elija otra."
    return None
