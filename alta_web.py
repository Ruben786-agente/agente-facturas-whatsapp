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
from estilo_web import acceso, pagina
from panel_web import login_requerido

log = logging.getLogger("alta_web")
bp_alta = Blueprint("alta", __name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PLANTILLA_REGISTRO = acceso("Crear cuenta", """
  <h2>Prueba 14 días gratis</h2>
  <p class="tenue">Sin tarjeta. Solo necesita su cuenta de OneDrive o de Google Drive, y su Gmail.</p>
  <form method="post">
    <label for="nombre">Nombre de la gestoría</label>
    <input id="nombre" name="nombre" autocomplete="organization" required autofocus>
    <label for="email">Email</label>
    <input id="email" type="email" name="email" autocomplete="email" required>
    <label for="password">Contraseña (mínimo 8 caracteres)</label>
    <input id="password" type="password" name="password" autocomplete="new-password" required minlength="8">
    {% if error %}<p class="error-texto" role="alert">{{ error }}</p>{% endif %}
    <button class="btn principal grande" type="submit">Crear cuenta</button>
  </form>
  <p class="pie"><a href="{{ url_for('panel.login') }}">Ya tengo cuenta</a></p>
""")

CSS_CONEXIONES = """
<style>
  .pasos { display: grid; gap: 14px; margin-top: 28px; }
  .paso { background: var(--superficie); border: 1px solid var(--linea); border-radius: 10px; padding: 20px 22px; display: grid;
          grid-template-columns: 36px minmax(0, 1fr); gap: 4px 16px; }
  .paso .n { grid-row: span 3; width: 30px; height: 30px; border-radius: 50%; border: 1px solid var(--linea-fuerte); display: grid; place-items: center;
             font: 500 16px/1 var(--serif); color: var(--tinta-2); }
  .paso.hecho .n { background: var(--ok); border-color: var(--ok); color: #fff; }
  .paso h3 { font-size: 20px; }
  .paso .que { color: var(--tinta-2); margin: 0; }
  .paso .estado-linea { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
  .conectado { color: var(--ok); font-weight: 500; }
  .paso.opcional .n { border-style: dashed; }
  @media (max-width: 560px) { .paso { grid-template-columns: 1fr; } .paso .n { display: none; } }
</style>
"""

PLANTILLA_CONEXIONES = pagina("Conexiones", """
{% macro desconectar(clave, nombre) %}
<form method="post" action="{{ url_for('alta.desconectar', proveedor=clave) }}" class="en-linea"
  onsubmit="return confirm('¿Desconectar {{ nombre }}? El agente dejará de usarlo. Lo que ya está guardado no se borra y podrá volver a conectarlo cuando quiera.');">
  <button type="submit" class="btn discreto">Desconectar</button>
</form>
{% endmacro %}
<main class="pagina estrecha">
  <h1 style="font-size:38px;">Conexiones y suscripción</h1>
  <p class="tenue" style="margin-top:6px;">Conecte su correo y su almacenamiento una vez y el agente trabaja solo.</p>
  {% if mensaje %}<p class="mensaje" role="status" style="margin-top:20px;">{{ mensaje }}</p>{% endif %}
  {% if error %}<p class="alerta error" role="alert" style="margin-top:20px;">{{ error }}</p>{% endif %}

  <div class="pasos">
    <section class="paso {% if e.almacenamiento %}hecho{% endif %}">
      <span class="n">{% if e.almacenamiento %}✓{% else %}1{% endif %}</span>
      <h3>Dónde guardar facturas y Excel</h3>
      <p class="que">Elija OneDrive o Google Drive. Solo se usa uno a la vez.</p>
      <div class="estado-linea">
        {% if e.almacenamiento == "onedrive" %}<span class="conectado">OneDrive conectado</span> <span class="tenue">{{ e.onedrive_cuenta or "" }}</span> {{ desconectar("onedrive", "OneDrive") }}
        {% elif e.almacenamiento == "gdrive" %}
          <span class="conectado">Google Drive conectado</span> <span class="tenue">{{ e.gdrive_cuenta or "" }}</span>
          <a class="btn" href="{{ url_for('alta.conectar_gdrive') }}">Volver a autorizar</a> {{ desconectar("gdrive", "Google Drive") }}
        {% else %}
          <a class="btn principal" href="{{ url_for('alta.conectar_onedrive') }}">Conectar OneDrive</a>
          <a class="btn principal" href="{{ url_for('alta.conectar_gdrive') }}">Conectar Google Drive</a>
        {% endif %}
      </div>
    </section>

    <section class="paso {% if e.gmail and not e.gmail_error %}hecho{% endif %}">
      <span class="n">{% if e.gmail and not e.gmail_error %}✓{% else %}2{% endif %}</span>
      <h3>Gmail</h3>
      <p class="que">El agente lee los correos con facturas adjuntas.</p>
      <div class="estado-linea">
        {% if e.gmail_error %}<span class="alerta" style="margin:0;padding:8px 12px;">{{ e.gmail_error }}</span>{% endif %}
        {% if e.gmail and not e.gmail_error %}<span class="conectado">Gmail conectado</span> <span class="tenue">{{ e.gmail_cuenta or "" }}</span>
        {% else %}<a class="btn principal" href="{{ url_for('alta.conectar_gmail') }}">{{ "Volver a autorizar Gmail" if e.gmail else "Conectar Gmail" }}</a>{% endif %}
        {% if e.gmail %}{{ desconectar("gmail", "Gmail") }}{% endif %}
      </div>
    </section>

    <section class="paso {% if e.plan == 'activo' %}hecho{% endif %}">
      <span class="n">{% if e.plan == 'activo' %}✓{% else %}3{% endif %}</span>
      <h3>Suscripción</h3>
      <div class="estado-linea">
        {% if e.plan == "activo" %}<span class="conectado">Suscripción activa</span>
        {% else %}
          {% if e.plan == "trial" and e.trial_expira_en %}<span class="que">Prueba gratuita hasta el {{ e.trial_expira_en.strftime("%d/%m/%Y") }}.</span>{% endif %}
          <a class="btn principal" href="{{ url_for('alta.suscribirme') }}">Suscribirme</a>
        {% endif %}
      </div>
    </section>

    <section class="paso opcional">
      <span class="n">+</span>
      <h3>WhatsApp <small>(opcional)</small></h3>
      <p class="que">Próximamente podrá recibir también las facturas que sus clientes envíen por WhatsApp.</p>
    </section>
  </div>

  <p style="margin-top:28px;"><a class="btn" href="{{ url_for('panel.panel') }}">Ir al panel</a></p>
</main>
""", activa="conexiones", extra_head=CSS_CONEXIONES)


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
            error = "Revise el nombre y el email."
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
    estado = obtener_estado_conexiones(session["tenant_id"])
    return render_template_string(PLANTILLA_CONEXIONES, e=estado, gestoria_nombre=estado["nombre"],
                                  mensaje=request.args.get("ok"), error=request.args.get("error"))


@bp_alta.route("/onboarding/onedrive")
@login_requerido
def conectar_onedrive():
    if obtener_estado_conexiones(session["tenant_id"])["gdrive"]:
        return redirect(url_for("alta.conexiones", error="Ya tiene Google Drive conectado. Solo se puede usar un almacenamiento."))
    session["state_ms"] = secrets.token_urlsafe(24)
    return redirect(microsoft.generar_url_autorizacion(session["state_ms"]))


def callback_onedrive():
    if "tenant_id" not in session:
        return redirect(url_for("panel.login"))
    if request.args.get("error") or request.args.get("state") != session.get("state_ms"):
        return redirect(url_for("alta.conexiones", error="No se pudo conectar OneDrive. Inténtelo de nuevo."))
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
        return redirect(url_for("alta.conexiones", error="No se pudo conectar OneDrive. Inténtelo de nuevo."))
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
        return redirect(url_for("alta.conexiones", error="Ya tiene OneDrive conectado. Solo se puede usar un almacenamiento."))
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
        return redirect(url_for("alta.conexiones", error=f"No se pudo conectar {nombre}. Inténtelo de nuevo."))
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
        return redirect(url_for("alta.conexiones", error=f"No se pudo conectar {nombre}. Inténtelo de nuevo."))
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
                                base + url_for("alta.conexiones", ok="¡Gracias! Su suscripción se activará en unos segundos."),
                                base + url_for("alta.conexiones"))
    except Exception:
        log.exception("Fallo creando sesión de pago")
        return redirect(url_for("alta.conexiones", error="No se pudo abrir el pago. Inténtelo más tarde."))
    return redirect(url)
