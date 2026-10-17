# -*- coding: utf-8 -*-
"""
Alta de una gestoría nueva y conexión de sus cuentas:
  /registro      -> crea la gestoría (prueba gratuita de 14 días) y su contraseña
  /conexiones    -> conectar OneDrive o Google Drive, Gmail, y suscribirse
  callbacks      -> donde Microsoft y Google devuelven a la gestoría tras autorizar
"""

import logging
import os
import re
import secrets
from urllib.parse import urlparse

import requests
from flask import Blueprint, redirect, render_template_string, request, session, url_for

import autenticacion_google as google
import autenticacion_onedrive as microsoft
from almacenamiento import obtener_almacenamiento
from basededatos import (crear_gestoria_prueba, establecer_password, existe_email_gestoria,
                         guardar_credencial, obtener_estado_conexiones, eliminar_credencial)
from onboarding import preparar_gestoria, reconstruir_carpetas_empresas
from panel_web import login_requerido

log = logging.getLogger("alta_web")
bp_alta = Blueprint("alta", __name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ESTILO = """
<style>
  body { font-family: Arial, sans-serif; background: #f4f5f7; margin: 0; padding: 2rem; }
  .caja { background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.1); max-width: 520px; margin: 0 auto; }
  input { width: 100%; padding: 8px; margin: 6px 0 14px 0; box-sizing: border-box; }
  .boton, button { display: inline-block; padding: 10px 16px; background: #2d6cdf; color: white; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; font-size: 1em; }
  .boton.gris { background: #888; }
  .error { color: #c0392b; } .ok { color: #27ae60; } .aviso { background: #fff4e5; padding: 10px; border-radius: 4px; }
  .paso { border-top: 1px solid #eee; padding: 1rem 0; }
</style>
"""

PLANTILLA_REGISTRO = ESTILO + """
<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Crear cuenta - Agente Facturas</title></head><body>
<div class="caja">
  <h2>Prueba gratis 14 días</h2>
  <p>Sin tarjeta. Solo necesitas tu cuenta de OneDrive o de Google Drive, y tu Gmail.</p>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <form method="post">
    <label>Nombre de la gestoría</label><input name="nombre" required>
    <label>Email</label><input type="email" name="email" required>
    <label>Contraseña (mínimo 8 caracteres)</label><input type="password" name="password" required minlength="8">
    <button type="submit">Crear cuenta</button>
  </form>
  <p><a href="{{ url_for('panel.login') }}">Ya tengo cuenta</a></p>
</div></body></html>
"""

PLANTILLA_CONEXIONES = ESTILO + """
<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Conexiones - Agente Facturas</title></head><body>
{% macro desconectar(clave, nombre) %}
<form method="post" action="{{ url_for('alta.desconectar', proveedor=clave) }}" style="display:inline"
  onsubmit="return confirm('¿Desconectar {{ nombre }}? El agente dejará de usarlo. Lo que ya está guardado no se borra y podrás volver a conectarlo cuando quieras.');">
  <button type="submit" class="boton gris" style="border:0;cursor:pointer;">Desconectar</button>
</form>
{% endmacro %}
<div class="caja">
  <h2>Hola, {{ e.nombre }}</h2>
  {% if mensaje %}<p class="ok">{{ mensaje }}</p>{% endif %}
  {% if error %}<p class="error">{{ error }}</p>{% endif %}

  <div class="paso">
    <b>1. Dónde guardar facturas y Excel</b> (elige OneDrive o Google Drive)<br>
    {% if e.almacenamiento == "onedrive" %}<span class="ok">✔ OneDrive conectado</span> {{ e.onedrive_cuenta or "" }}
      {{ desconectar("onedrive", "OneDrive") }}
    {% elif e.almacenamiento == "gdrive" %}
      <span class="ok">✔ Google Drive conectado</span> {{ e.gdrive_cuenta or "" }}
      <a class="boton gris" href="{{ url_for('alta.conectar_gdrive') }}">Volver a autorizar</a>
      {{ desconectar("gdrive", "Google Drive") }}
    {% else %}
      <a class="boton" href="{{ url_for('alta.conectar_onedrive') }}">Conectar OneDrive</a>
      <a class="boton" href="{{ url_for('alta.conectar_gdrive') }}">Conectar Google Drive</a>
    {% endif %}
  </div>

  <div class="paso">
    <b>2. Gmail</b> (el agente lee los correos con facturas)<br>
    {% if e.gmail_error %}<p class="aviso">⚠ {{ e.gmail_error }}</p>{% endif %}
    {% if e.gmail and not e.gmail_error %}<span class="ok">✔ Conectado</span> {{ e.gmail_cuenta or "" }}
    {% else %}<a class="boton" href="{{ url_for('alta.conectar_gmail') }}">{{ "Volver a autorizar Gmail" if e.gmail else "Conectar Gmail" }}</a>{% endif %}
    {% if e.gmail %}{{ desconectar("gmail", "Gmail") }}{% endif %}
  </div>

  <div class="paso">
    <b>WhatsApp</b> (opcional)<br>
    <span style="color:#888;">Próximamente: podrás recibir también las facturas que tus clientes envíen por WhatsApp.</span>
  </div>

  <div class="paso">
    <b>3. Suscripción</b><br>
    {% if e.plan == "activo" %}<span class="ok">✔ Suscripción activa</span>
    {% else %}
      {% if e.plan == "trial" and e.trial_expira_en %}Prueba gratuita hasta el {{ e.trial_expira_en.strftime("%d/%m/%Y") }}.<br>{% endif %}
      <a class="boton" href="{{ url_for('alta.suscribirme') }}">Suscribirme</a>
    {% endif %}
  </div>

  <p><a class="boton gris" href="{{ url_for('panel.panel') }}">Ir al panel</a></p>
</div></body></html>
"""


def _ruta_callback_microsoft():
    """Misma ruta que la ya registrada en Azure (AZURE_REDIRECT_URI)."""
    return urlparse(os.environ.get("AZURE_REDIRECT_URI", "")).path or "/onboarding/callback"


@bp_alta.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        error = None
        if not nombre or not _EMAIL.match(email):
            error = "Revisa el nombre y el email."
        elif len(password) < 8:
            error = "La contraseña debe tener al menos 8 caracteres."
        elif existe_email_gestoria(email):
            error = "Ya existe una cuenta con ese email."
        if error:
            return render_template_string(PLANTILLA_REGISTRO, error=error)
        tenant_id = crear_gestoria_prueba(nombre, email)
        establecer_password(tenant_id, password)
        session.clear()
        session["tenant_id"] = tenant_id
        return redirect(url_for("alta.conexiones"))
    return render_template_string(PLANTILLA_REGISTRO, error=None)


@bp_alta.route("/conexiones")
@login_requerido
def conexiones():
    return render_template_string(PLANTILLA_CONEXIONES, e=obtener_estado_conexiones(session["tenant_id"]),
                                  mensaje=request.args.get("ok"), error=request.args.get("error"))


@bp_alta.route("/onboarding/onedrive")
@login_requerido
def conectar_onedrive():
    if obtener_estado_conexiones(session["tenant_id"])["gdrive"]:
        return redirect(url_for("alta.conexiones", error="Ya tienes Google Drive conectado. Solo se puede usar un almacenamiento."))
    session["state_ms"] = secrets.token_urlsafe(24)
    return redirect(microsoft.generar_url_autorizacion(session["state_ms"]))


def callback_onedrive():
    if "tenant_id" not in session:
        return redirect(url_for("panel.login"))
    if request.args.get("error") or request.args.get("state") != session.get("state_ms"):
        return redirect(url_for("alta.conexiones", error="No se pudo conectar OneDrive. Inténtalo de nuevo."))
    try:
        token = microsoft.procesar_callback(request.args["code"])
        tenant_id = session["tenant_id"]
        cuenta = (token.get("id_token_claims") or {}).get("preferred_username")
        guardar_credencial(tenant_id, "onedrive", token["refresh_token"], cuenta)
        _storage = obtener_almacenamiento("onedrive", access_token=token["access_token"])
        preparar_gestoria(_storage, tenant_id)
        reconstruir_carpetas_empresas(_storage, tenant_id)
    except Exception:
        log.exception("Fallo conectando OneDrive")
        return redirect(url_for("alta.conexiones", error="No se pudo conectar OneDrive. Inténtalo de nuevo."))
    return redirect(url_for("alta.conexiones", ok="OneDrive conectado."))


bp_alta.add_url_rule(_ruta_callback_microsoft(), "callback_onedrive", callback_onedrive)


@bp_alta.route("/onboarding/gmail")
@login_requerido
def conectar_gmail():
    session["state_g"] = secrets.token_urlsafe(24)
    session["google_proposito"] = "gmail"
    return redirect(google.generar_url_autorizacion(session["state_g"]))


@bp_alta.route("/onboarding/gdrive")
@login_requerido
def conectar_gdrive():
    if obtener_estado_conexiones(session["tenant_id"])["onedrive"]:
        return redirect(url_for("alta.conexiones", error="Ya tienes OneDrive conectado. Solo se puede usar un almacenamiento."))
    session["state_g"] = secrets.token_urlsafe(24)
    session["google_proposito"] = "gdrive"  # vuelve por la misma dirección que Gmail
    return redirect(google.generar_url_autorizacion(session["state_g"], scopes=google.SCOPES_DRIVE))


def _callback_gdrive(token):
    tenant_id = session["tenant_id"]
    datos = requests.get("https://www.googleapis.com/drive/v3/about", params={"fields": "user(emailAddress)"},
                         headers={"Authorization": f"Bearer {token['access_token']}"}, timeout=30).json()
    guardar_credencial(tenant_id, "gdrive", token["refresh_token"], (datos.get("user") or {}).get("emailAddress"))
    _storage = obtener_almacenamiento("gdrive", access_token=token["access_token"])
    preparar_gestoria(_storage, tenant_id)
    reconstruir_carpetas_empresas(_storage, tenant_id)


@bp_alta.route("/onboarding/gmail/callback")
def callback_gmail():
    if "tenant_id" not in session:
        return redirect(url_for("panel.login"))
    proposito = session.get("google_proposito", "gmail")
    nombre = "Google Drive" if proposito == "gdrive" else "Gmail"
    if request.args.get("error") or request.args.get("state") != session.get("state_g"):
        return redirect(url_for("alta.conexiones", error=f"No se pudo conectar {nombre}. Inténtalo de nuevo."))
    try:
        token = google.procesar_callback(request.args["code"])
        if "refresh_token" not in token:
            raise ValueError("Google no devolvió refresh token")
        if proposito == "gdrive":
            _callback_gdrive(token)
            return redirect(url_for("alta.conexiones", ok="Google Drive conectado."))
        perfil = requests.get("https://gmail.googleapis.com/gmail/v1/users/me/profile",
                              headers={"Authorization": f"Bearer {token['access_token']}"}, timeout=30).json()
        tenant_id = session["tenant_id"]
        guardar_credencial(tenant_id, "gmail", token["refresh_token"], perfil.get("emailAddress"))
        from basededatos import guardar_estado_correo
        guardar_estado_correo(tenant_id, error=None)  # limpia el aviso "Gmail desconectado"
    except Exception:
        log.exception("Fallo conectando %s", nombre)
        return redirect(url_for("alta.conexiones", error=f"No se pudo conectar {nombre}. Inténtalo de nuevo."))
    return redirect(url_for("alta.conexiones", ok="Gmail conectado."))


_NOMBRES = {"onedrive": "OneDrive", "gdrive": "Google Drive", "gmail": "Gmail"}


@bp_alta.route("/conexiones/desconectar/<proveedor>", methods=["POST"])
@login_requerido
def desconectar(proveedor):
    if proveedor not in _NOMBRES:
        return redirect(url_for("alta.conexiones", error="Conexión no válida."))
    token = eliminar_credencial(session["tenant_id"], proveedor)
    if token and proveedor in ("gmail", "gdrive"):
        google.revocar_token(token)
    log.info("Gestoría %s desconectó %s", session["tenant_id"], proveedor)
    return redirect(url_for("alta.conexiones", ok=f"{_NOMBRES[proveedor]} desconectado."))


@bp_alta.route("/suscribirme")
@login_requerido
def suscribirme():
    base = request.url_root.rstrip("/")
    try:
        from stripe_integracion import crear_sesion_pago
        e = obtener_estado_conexiones(session["tenant_id"])
        url = crear_sesion_pago(session["tenant_id"], e["email"],
                                base + url_for("alta.conexiones", ok="¡Gracias! Tu suscripción se activará en unos segundos."),
                                base + url_for("alta.conexiones"))
    except Exception:
        log.exception("Fallo creando sesión de pago")
        return redirect(url_for("alta.conexiones", error="No se pudo abrir el pago. Inténtalo más tarde."))
    return redirect(url)
