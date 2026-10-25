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
from urllib.parse import urlencode, urlparse

import requests
from flask import Blueprint, redirect, render_template_string, request, session, url_for

import autenticacion_google as google
import autenticacion_onedrive as microsoft
from almacenamiento import obtener_almacenamiento
from basededatos import (crear_gestoria_prueba, establecer_password, existe_email_gestoria,
                         guardar_credencial, guardar_estado_correo, obtener_estado_conexiones, eliminar_credencial,
                         eliminar_gestoria, email_de_gestoria, obtener_suscripcion_stripe, verificar_login)
from onboarding import preparar_gestoria, reconstruir_carpetas_empresas
from estilo_web import acceso, pagina
from panel_web import login_requerido
from seguridad import contrasena_debil

log = logging.getLogger("alta_web")
bp_alta = Blueprint("alta", __name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PLANTILLA_REGISTRO = acceso("Crear cuenta", """
  <h2>Prueba 14 días gratis</h2>
  <p class="tenue">Sin tarjeta. Solo necesita su cuenta de OneDrive o de Google Drive, y su correo (Gmail u Outlook).</p>
  <form method="post">
    <label for="nombre">Nombre de la gestoría</label>
    <input id="nombre" name="nombre" autocomplete="organization" required autofocus>
    <label for="email">Email</label>
    <input id="email" type="email" name="email" autocomplete="email" required>
    <label for="password">Contraseña</label>
    <input id="password" type="password" name="password" autocomplete="new-password" required minlength="8">
    <ul id="reglas" style="list-style:none;margin:10px 0 0;padding:0;font-size:14px;line-height:1.7;color:var(--tinta-3);">
      <li data-r="largo"><span>○</span> Al menos 8 caracteres</li>
      <li data-r="mayus"><span>○</span> Una mayúscula</li>
      <li data-r="minus"><span>○</span> Una minúscula</li>
      <li data-r="num"><span>○</span> Un número</li>
      <li data-r="simbolo"><span>○</span> Un símbolo (por ejemplo ! ? - _ . @ #)</li>
    </ul>
    <p class="tenue" style="font-size:14px;margin:8px 0 0;">Truco: junte dos o tres palabras con guiones y añada un número y un signo, por ejemplo <em>Coche-verde7!</em> (invente la suya). Es fácil de recordar y difícil de adivinar.</p>
    <script>
      (function () {
        var campo = document.getElementById("password");
        var pruebas = {
          largo: function (p) { return p.length >= 8; },
          mayus: function (p) { return /[A-ZÁÉÍÓÚÑÜ]/.test(p); },
          minus: function (p) { return /[a-záéíóúñü]/.test(p); },
          num: function (p) { return /[0-9]/.test(p); },
          simbolo: function (p) { return /[^A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü]/.test(p); }
        };
        function revisar() {
          var items = document.querySelectorAll("#reglas li");
          for (var i = 0; i < items.length; i++) {
            var cumple = pruebas[items[i].getAttribute("data-r")](campo.value);
            items[i].style.color = cumple ? "var(--ok)" : "";
            items[i].firstChild.textContent = cumple ? "✓" : "○";
          }
        }
        campo.addEventListener("input", revisar);
      })();
    </script>
    <label style="display:flex;gap:10px;align-items:flex-start;margin-top:18px;font-weight:400;font-size:14px;">
      <input type="checkbox" name="acepto" value="1" required style="width:auto;margin-top:3px;">
      <span>He leído y acepto las <a href="/terminos" target="_blank">condiciones del servicio</a>, la <a href="/privacidad" target="_blank">política de privacidad</a> y el <a href="/encargo" target="_blank">contrato de encargo del tratamiento</a>.</span>
    </label>
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
  .paso > :not(.n) { grid-column: 2; }
  .paso h3 { font-size: 20px; }
  .paso .que { color: var(--tinta-2); margin: 0; }
  .paso .estado-linea { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
  .conectado { color: var(--ok); font-weight: 500; }
  .paso.opcional .n { border-style: dashed; }
  @media (max-width: 560px) { .paso { grid-template-columns: 1fr; } .paso .n { display: none; } .paso > :not(.n) { grid-column: 1; } }
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
      {% if e.almacenamiento %}
      <p class="tenue" style="margin-top:12px;">¿Tiene facturas escaneadas o fotos? Súbalas desde <a href="{{ url_for('subida.subir') }}">Subir facturas</a> y el agente las lee y las archiva solo, igual que las del correo.
        {% if entrada_activa %}También puede dejarlas, sueltas o en carpetas, en <strong>Agente Facturas / Entrada</strong> de su OneDrive.{% endif %}
        <a href="{{ url_for('alta.abrir_entrada') }}" target="_blank" rel="noopener">Abrir la carpeta Entrada</a></p>
      {% endif %}
    </section>

    <section class="paso {% if e.correo and not e.correo_error %}hecho{% endif %}">
      <span class="n">{% if e.correo and not e.correo_error %}✓{% else %}2{% endif %}</span>
      <h3>Correo</h3>
      <p class="que">El agente lee los correos con facturas adjuntas. Elija Gmail o Outlook / Microsoft 365; solo se usa uno a la vez.</p>
      <div class="estado-linea">
        {% if e.correo_error %}<span class="alerta" style="margin:0;padding:8px 12px;">{{ e.correo_error }}</span>{% endif %}
        {% if e.correo == "gmail" %}
          {% if not e.correo_error %}<span class="conectado">Gmail conectado</span> <span class="tenue">{{ e.correo_cuenta or "" }}</span>{% endif %}
          <a class="btn {% if e.correo_error %}principal{% endif %}" href="{{ url_for('alta.conectar_gmail') }}">Volver a autorizar</a> {{ desconectar("gmail", "Gmail") }}
        {% elif e.correo == "outlook" %}
          {% if not e.correo_error %}<span class="conectado">Outlook conectado</span> <span class="tenue">{{ e.correo_cuenta or "" }}</span>{% endif %}
          <a class="btn {% if e.correo_error %}principal{% endif %}" href="{{ url_for('alta.conectar_outlook') }}">Volver a autorizar</a> {{ desconectar("outlook", "Outlook") }}
        {% else %}
          <a class="btn principal" href="{{ url_for('alta.conectar_gmail') }}">Conectar Gmail</a>
          <a class="btn principal" href="{{ url_for('alta.conectar_outlook') }}">Conectar Outlook / Microsoft 365</a>
        {% endif %}
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

  {% if not e.almacenamiento or not e.correo %}
  <p class="tenue" style="margin-top:22px;max-width:640px;">¿Su Microsoft 365 le pide permiso de un administrador? Envíele este enlace; con un solo clic aprueba el acceso para toda su organización y después usted ya puede conectar: <br><strong style="word-break:break-all;">{{ url_for('alta.permiso_administrador', _external=True, _scheme='https') }}</strong></p>
  {% endif %}

  <p style="margin-top:28px;"><a class="btn" href="{{ url_for('panel.panel') }}">Ir al panel</a></p>

  <details style="margin-top:36px;max-width:640px;">
    <summary class="tenue" style="cursor:pointer;">Eliminar mi cuenta y mis datos</summary>
    <form method="post" action="{{ url_for('alta.eliminar_cuenta') }}" style="margin-top:14px;">
      <p class="tenue">Se borran su cuenta, las conexiones y todo lo que el agente tiene guardado de sus clientes (facturas leídas, avisos...). <strong>Los archivos de su OneDrive o Google Drive no se tocan</strong>: siguen siendo suyos. Si tiene una suscripción, se cancela. No se puede deshacer.</p>
      <label for="password_borrar">Escriba su contraseña para confirmar</label>
      <input id="password_borrar" type="password" name="password" autocomplete="current-password" required>
      <button class="btn" type="submit" style="margin-top:12px;">Eliminar definitivamente</button>
    </form>
  </details>
</main>
""", activa="conexiones", extra_head=CSS_CONEXIONES)

PLANTILLA_ADMIN = pagina("Permiso de administrador", """
<main class="pagina estrecha" style="max-width:640px;padding-top:56px;">
  <h1 style="font-size:34px;">{{ titulo }}</h1>
  <p>{{ texto }}</p>
</main>
""", barra=False)


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
        elif not request.form.get("acepto"):
            error = "Para crear la cuenta debe aceptar las condiciones del servicio y la política de privacidad."
        elif contrasena_debil(password, email):
            error = contrasena_debil(password, email)
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
    from sondeo_entrada import _proveedores_activos
    estado = obtener_estado_conexiones(session["tenant_id"])
    return render_template_string(PLANTILLA_CONEXIONES, e=estado, gestoria_nombre=estado["nombre"],
                                  entrada_activa=estado["almacenamiento"] == "onedrive",
                                  mensaje=request.args.get("ok"), error=request.args.get("error"))


@bp_alta.route("/conexiones/entrada")
@login_requerido
def abrir_entrada():
    """Lleva a la gestoría a su carpeta «Entrada» (la crea si aún no existe)."""
    from almacenamiento_tenant import proveedor_almacenamiento, storage_para_tenant
    from sondeo_entrada import _proveedores_activos, asegurar_carpetas
    tenant_id = session["tenant_id"]
    try:
        proveedor = proveedor_almacenamiento(tenant_id)
        storage = storage_para_tenant(tenant_id)
        enlace = storage.obtener_enlace(asegurar_carpetas(storage, tenant_id, proveedor, comprobar=True)["entrada"])
        if enlace.startswith("https://"):
            from sondeo_entrada import CARPETA_RAIZ, NOMBRE_ENTRADA
            log.info("Entrada de %s: enlace hacia %s", tenant_id, urlparse(enlace).netloc)
            estado = obtener_estado_conexiones(tenant_id)
            cuenta = estado.get("onedrive_cuenta") if proveedor == "onedrive" else estado.get("gdrive_cuenta")
            return render_template_string(PLANTILLA_ENTRADA, enlace=enlace, ruta=f"{CARPETA_RAIZ} › {NOMBRE_ENTRADA}", soltar=(proveedor == "onedrive"), cuenta=cuenta)
    except Exception:
        log.exception("No se pudo abrir la carpeta Entrada de %s", tenant_id)
    return redirect(url_for("alta.conexiones", error="No hemos podido abrir la carpeta Entrada. Inténtelo de nuevo en un momento."))


PLANTILLA_ENTRADA = pagina("Carpeta Entrada", """
<main class="pagina" style="max-width:640px;">
  <h1>Su carpeta Entrada</h1>
  <p class="que">Está en su almacenamiento, dentro de <strong>{{ ruta }}</strong>.
  {% if soltar %}Los archivos que deje ahí los lee el agente.{% else %}Con Google Drive, para que el agente lea facturas use <a href="{{ url_for('subida.subir') }}">Subir facturas</a>: los archivos soltados a mano en esa carpeta no los ve.{% endif %}</p>
  {% if cuenta %}<p class="alerta">Esta carpeta pertenece a la cuenta <strong>{{ cuenta }}</strong>. Para abrirla, su navegador debe tener iniciada la sesión con <strong>esa</strong> cuenta; si tiene otra abierta (por ejemplo, la de trabajo), no cargará. Pruebe en una ventana de incógnito.</p>{% endif %}
  <p><a class="btn principal" href="{{ enlace }}" target="_blank" rel="noopener">Abrir la carpeta</a>
     <a class="btn" href="{{ url_for('alta.conexiones') }}">Volver</a></p>
  <p class="tenue">Si no se abre, copie esta dirección en el navegador o busque la carpeta a mano en su OneDrive:</p>
  <p class="tenue" style="word-break:break-all;">{{ enlace }}</p>
</main>
""", activa="conexiones")


@bp_alta.route("/permiso-administrador")
def permiso_administrador():
    """Enlace para el administrador de un Microsoft 365: aprueba el acceso de la aplicación para toda su organización."""
    destino = "https://login.microsoftonline.com/organizations/adminconsent?" + urlencode({
        "client_id": os.environ["AZURE_CLIENT_ID"], "redirect_uri": os.environ["AZURE_REDIRECT_URI"]})
    return redirect(destino)


@bp_alta.route("/onboarding/onedrive")
@login_requerido
def conectar_onedrive():
    if obtener_estado_conexiones(session["tenant_id"])["gdrive"]:
        return redirect(url_for("alta.conexiones", error="Ya tiene Google Drive conectado. Solo se puede usar un almacenamiento."))
    session["state_ms"] = secrets.token_urlsafe(24)
    session["ms_proposito"] = "onedrive"
    return redirect(microsoft.generar_url_autorizacion(session["state_ms"]))


@bp_alta.route("/onboarding/outlook")
@login_requerido
def conectar_outlook():
    session["state_ms"] = secrets.token_urlsafe(24)
    session["ms_proposito"] = "outlook"  # vuelve por la misma dirección que OneDrive
    return redirect(microsoft.generar_url_autorizacion(session["state_ms"], scopes=microsoft.SCOPES_CORREO))


def callback_onedrive():
    # Vuelta del administrador tras aprobar (o rechazar) el permiso: no trae sesión de ninguna gestoría.
    if request.args.get("admin_consent"):
        if request.args["admin_consent"].lower() == "true":
            return render_template_string(PLANTILLA_ADMIN, titulo="Permiso concedido",
                                          texto="Gracias. Ya puede cerrar esta ventana: su gestoría puede conectar ahora su Microsoft 365.")
        return render_template_string(PLANTILLA_ADMIN, titulo="No se ha concedido el permiso",
                                      texto="No se ha podido aprobar el acceso. Si cree que es un error, vuelva a abrir el enlace que le enviaron.")
    if "tenant_id" not in session:
        return redirect(url_for("panel.login"))
    proposito = session.get("ms_proposito", "onedrive")
    nombre = "Outlook" if proposito == "outlook" else "OneDrive"
    if request.args.get("error"):
        detalle = ((request.args.get("error") or "") + " " + (request.args.get("error_description") or "")).lower()
        if any(p in detalle for p in ("admin", "consent_required", "access_denied", "aadsts65001", "aadsts90094", "aadsts900941")):
            return redirect(url_for("alta.conexiones", error=f"Su Microsoft 365 necesita que un administrador apruebe el permiso para conectar {nombre}. "
                                                              "Envíele el enlace que aparece al final de esta página y vuelva a intentarlo después."))
    if request.args.get("error") or request.args.get("state") != session.get("state_ms"):
        return redirect(url_for("alta.conexiones", error=f"No se pudo conectar {nombre}. Inténtelo de nuevo."))
    try:
        tenant_id = session["tenant_id"]
        if proposito == "outlook":
            token = microsoft.procesar_callback(request.args["code"], scopes=microsoft.SCOPES_CORREO)
            cuenta = (token.get("id_token_claims") or {}).get("preferred_username")
            guardar_credencial(tenant_id, "outlook", token["refresh_token"], cuenta)
            guardar_estado_correo(tenant_id, error=None)  # limpia el aviso "Outlook desconectado"
        else:
            token = microsoft.procesar_callback(request.args["code"])
            cuenta = (token.get("id_token_claims") or {}).get("preferred_username")
            guardar_credencial(tenant_id, "onedrive", token["refresh_token"], cuenta)
            _storage = obtener_almacenamiento("onedrive", access_token=token["access_token"])
            preparar_gestoria(_storage, tenant_id)
            reconstruir_carpetas_empresas(_storage, tenant_id)
    except Exception:
        log.exception("Fallo conectando %s", nombre)
        return redirect(url_for("alta.conexiones", error=f"No se pudo conectar {nombre}. Inténtelo de nuevo."))
    return redirect(url_for("alta.conexiones", ok=f"{nombre} conectado."))


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
        guardar_estado_correo(tenant_id, error=None)  # limpia el aviso "Gmail desconectado"
    except Exception:
        log.exception("Fallo conectando %s", nombre)
        return redirect(url_for("alta.conexiones", error=f"No se pudo conectar {nombre}. Inténtelo de nuevo."))
    return redirect(url_for("alta.conexiones", ok="Gmail conectado."))


_NOMBRES = {"onedrive": "OneDrive", "gdrive": "Google Drive", "gmail": "Gmail", "outlook": "Outlook"}


@bp_alta.route("/conexiones/desconectar/<proveedor>", methods=["POST"])
@login_requerido
def desconectar(proveedor):
    if proveedor not in _NOMBRES:
        return redirect(url_for("alta.conexiones", error="Conexión no válida."))
    token = eliminar_credencial(session["tenant_id"], proveedor)
    if token and proveedor in ("gmail", "gdrive"):  # Microsoft no ofrece anular el acceso desde aquí
        google.revocar_token(token)
    log.info("Gestoría %s desconectó %s", session["tenant_id"], proveedor)
    return redirect(url_for("alta.conexiones", ok=f"{_NOMBRES[proveedor]} desconectado."))


@bp_alta.route("/cuenta/eliminar", methods=["POST"])
@login_requerido
def eliminar_cuenta():
    tenant_id = session["tenant_id"]
    if not verificar_login(email_de_gestoria(tenant_id) or "", request.form.get("password", "")):
        return redirect(url_for("alta.conexiones", error="La contraseña no es correcta. No se ha borrado nada."))
    suscripcion = obtener_suscripcion_stripe(tenant_id)
    if suscripcion:
        try:
            from stripe_integracion import cancelar_suscripcion
            cancelar_suscripcion(suscripcion)
        except Exception:
            log.exception("No se pudo cancelar la suscripción al eliminar la cuenta %s", tenant_id)
            return redirect(url_for("alta.conexiones", error="No hemos podido cancelar su suscripción, así que no se ha borrado nada. Inténtelo de nuevo en unos minutos."))
    for proveedor in ("gmail", "gdrive"):
        try:
            token = eliminar_credencial(tenant_id, proveedor)
            if token:
                google.revocar_token(token)
        except Exception:
            log.exception("No se pudo anular el acceso de %s al eliminar la cuenta", proveedor)
    eliminar_gestoria(tenant_id)
    session.clear()
    log.info("Cuenta %s eliminada por su titular", tenant_id)
    return render_template_string(PLANTILLA_ADMIN, titulo="Cuenta eliminada",
                                  texto="Hemos borrado su cuenta y todos los datos que el agente guardaba. Los archivos de su OneDrive o Google Drive no se han tocado. Gracias por probar el servicio.")


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
