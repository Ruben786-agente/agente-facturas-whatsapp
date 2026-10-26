# -*- coding: utf-8 -*-
"""
«Archivos»: ver y descargar lo que el agente ha guardado (facturas, tickets, revisión y Excel de cada cliente) sin salir
del panel. Sirve igual para OneDrive y Google Drive, y no depende de que la web de OneDrive o Drive abra en el navegador.

Seguridad: solo se entra en las carpetas que el propio agente creó para esa gestoría, y solo se abre un archivo si de verdad
está dentro de la carpeta elegida (nunca se acepta una carpeta ni un archivo cualquiera por su identificador).
"""

import logging
from datetime import datetime
from io import BytesIO

from flask import Blueprint, render_template_string, request, session, send_file, redirect, url_for, flash

from almacenamiento_tenant import storage_para_tenant
from basededatos import obtener_empresas_con_carpetas, obtener_carpeta_sin_identificar, obtener_estado_conexiones
from estilo_web import pagina
from panel_web import login_requerido
from revision_web import _tipo_archivo

log = logging.getLogger("archivos_web")
bp_archivos = Blueprint("archivos", __name__)

CARPETAS = {"facturas": "Facturas", "tickets": "Tickets", "revision": "Revisión", "excel": "Excel"}
MAX_ARCHIVOS = 300

CSS_ARCHIVOS = """
<style>
  .tarjetas { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; margin-top: 24px; }
  .tarjeta { background: var(--superficie); border: 1px solid var(--linea); border-radius: 10px; padding: 18px 20px; }
  .tarjeta h3 { margin: 0 0 2px; font-size: 18px; }
  .tarjeta .cif { color: var(--tinta-3); font-size: 14px; margin-bottom: 12px; display: block; }
  .tarjeta .enlaces { display: flex; gap: 8px; flex-wrap: wrap; }
  .migas { margin: 4px 0 0; color: var(--tinta-2); }
  .migas a { color: var(--tinta-2); text-decoration: none; }
  .migas a:hover { color: var(--marca); }
</style>
"""

PLANTILLA_INICIO = pagina("Archivos", """
<main class="pagina">
  <h1 style="font-size:38px;">Archivos</h1>
  <p class="tenue" style="margin-top:6px;">Lo que el agente ha guardado de cada cliente. Puede verlo y descargarlo desde aquí, sin abrir OneDrive o Google Drive.</p>
  {% if not conectado %}
    <p class="alerta" role="alert" style="margin-top:20px;">Conecte su almacenamiento (OneDrive o Google Drive) para ver aquí los archivos.
      <a class="btn" href="{{ url_for('alta.conexiones') }}">Ir a Conexiones</a></p>
  {% else %}
  <div class="tarjetas">
    {% for e in empresas %}
    <div class="tarjeta">
      <h3>{{ e.nombre }}</h3><span class="cif">{{ e.cif_nif }}</span>
      <div class="enlaces">
        {% for clave, titulo in carpetas.items() %}{% if e[clave] %}<a class="btn" href="{{ url_for('archivos.carpeta', empresa_id=e.id, clave=clave) }}">{{ titulo }}</a>{% endif %}{% endfor %}
      </div>
    </div>
    {% endfor %}
    {% if sin_identificar %}
    <div class="tarjeta">
      <h3>Sin identificar</h3><span class="cif">Documentos sin empresa asignada</span>
      <div class="enlaces"><a class="btn" href="{{ url_for('archivos.carpeta', empresa_id='sin-identificar', clave='sin-identificar') }}">Ver archivos</a></div>
    </div>
    {% endif %}
  </div>
  {% if not empresas and not sin_identificar %}
    <div class="vacio"><strong>Todavía no hay clientes.</strong>Cuando el agente lea la primera factura, aquí aparecerá la carpeta de cada cliente.</div>
  {% endif %}
  {% endif %}
</main>
""", activa="archivos", extra_head=CSS_ARCHIVOS)

PLANTILLA_CARPETA = pagina("Archivos", """
<main class="pagina">
  <p class="migas"><a href="{{ url_for('archivos.inicio') }}">Archivos</a> › {{ cliente }}</p>
  <h1 style="font-size:34px;">{{ titulo }}</h1>
  {% if error %}<p class="alerta error" role="alert" style="margin-top:20px;">{{ error }}</p>
  {% elif archivos %}
  <div class="tabla" style="margin-top:22px;"><table class="apilable">
    <tr><th>Archivo</th><th>Modificado</th><th class="num">Tamaño</th><th>Acciones</th></tr>
    {% for a in archivos %}
    <tr>
      <td data-label="Archivo">{{ a.nombre }}</td>
      <td data-label="Modificado">{{ a.fecha }}</td>
      <td data-label="Tamaño" class="num">{{ a.tamano }}</td>
      <td data-label="Acciones"><div class="acciones">
        <a class="btn principal" href="{{ url_for('archivos.archivo', empresa_id=empresa_id, clave=clave, archivo_id=a.id, accion='ver') }}" target="_blank" rel="noopener">Ver</a>
        <a class="btn" href="{{ url_for('archivos.archivo', empresa_id=empresa_id, clave=clave, archivo_id=a.id, accion='descargar') }}">Descargar</a>
      </div></td>
    </tr>
    {% endfor %}
  </table></div>
  {% if mas %}<p class="tenue" style="margin-top:12px;">Se muestran los {{ archivos|length }} más recientes de {{ total }}.</p>{% endif %}
  {% else %}
  <div class="vacio" style="margin-top:22px;"><strong>No hay archivos en esta carpeta.</strong></div>
  {% endif %}
</main>
""", activa="archivos", extra_head=CSS_ARCHIVOS)


def _tamano(n):
    n = int(n or 0)
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB".replace(".", ",")
    return f"{max(1, round(n / 1024))} KB" if n else "-"


def _fecha(texto):
    try:
        return datetime.fromisoformat((texto or "").replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return "-"


def _resolver(tenant_id, empresa_id, clave):
    """(id de la carpeta, nombre del cliente, título) o None si no es una carpeta que el agente creó para esta gestoría."""
    if empresa_id == "sin-identificar" and clave == "sin-identificar":
        carpeta = obtener_carpeta_sin_identificar(tenant_id)
        return (carpeta, "Sin identificar", "Documentos sin identificar") if carpeta else None
    if clave not in CARPETAS:
        return None
    for e in obtener_empresas_con_carpetas(tenant_id):
        if e["id"] == empresa_id and e[clave]:
            return e[clave], e["nombre"], f'{CARPETAS[clave]} de {e["nombre"]}'
    return None


@bp_archivos.route("/archivos")
@login_requerido
def inicio():
    tenant_id = session["tenant_id"]
    conectado = bool(obtener_estado_conexiones(tenant_id)["almacenamiento"])
    return render_template_string(
        PLANTILLA_INICIO, conectado=conectado, carpetas=CARPETAS,
        empresas=obtener_empresas_con_carpetas(tenant_id) if conectado else [],
        sin_identificar=bool(conectado and obtener_carpeta_sin_identificar(tenant_id)))


@bp_archivos.route("/archivos/<empresa_id>/<clave>")
@login_requerido
def carpeta(empresa_id, clave):
    tenant_id = session["tenant_id"]
    resuelta = _resolver(tenant_id, empresa_id, clave)
    if not resuelta:
        return redirect(url_for("archivos.inicio"))
    carpeta_id, cliente, titulo = resuelta
    archivos, error, total = [], None, 0
    try:
        storage = storage_para_tenant(tenant_id)
        if not storage:
            raise RuntimeError("No hay almacenamiento conectado")
        lista, _subcarpetas = storage.listar_contenido(carpeta_id)
        lista = sorted(lista, key=lambda a: a.fecha_modificacion or "", reverse=True)
        total = len(lista)
        archivos = [{"id": a.id, "nombre": a.nombre, "fecha": _fecha(a.fecha_modificacion), "tamano": _tamano(a.tamano_bytes)}
                    for a in lista[:MAX_ARCHIVOS]]
    except Exception:
        log.exception("No se pudo leer la carpeta")
        error = "No se ha podido leer la carpeta. Compruebe que el almacenamiento sigue conectado en Conexiones."
    return render_template_string(PLANTILLA_CARPETA, empresa_id=empresa_id, clave=clave, cliente=cliente, titulo=titulo,
                                  archivos=archivos, error=error, total=total, mas=total > len(archivos))


@bp_archivos.route("/archivos/<empresa_id>/<clave>/<archivo_id>/<accion>")
@login_requerido
def archivo(empresa_id, clave, archivo_id, accion):
    tenant_id = session["tenant_id"]
    resuelta = _resolver(tenant_id, empresa_id, clave)
    if not resuelta or accion not in ("ver", "descargar"):
        return redirect(url_for("archivos.inicio"))
    try:
        storage = storage_para_tenant(tenant_id)
        if not storage:
            raise RuntimeError("No hay almacenamiento conectado")
        lista, _ = storage.listar_contenido(resuelta[0])
        elegido = next((a for a in lista if a.id == archivo_id), None)   # solo si está de verdad en esa carpeta
        if not elegido:
            flash("Ese archivo ya no está en la carpeta.")
            return redirect(url_for("archivos.carpeta", empresa_id=empresa_id, clave=clave))
        contenido = storage.descargar_archivo(elegido.id)
    except Exception:
        log.exception("No se pudo abrir el archivo")
        flash("No se ha podido abrir el archivo. Compruebe que el almacenamiento sigue conectado en Conexiones.")
        return redirect(url_for("archivos.carpeta", empresa_id=empresa_id, clave=clave))
    tipo = _tipo_archivo(elegido.nombre, contenido)
    if elegido.nombre.lower().endswith(".xlsx"):
        tipo = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    en_pantalla = accion == "ver" and tipo in ("application/pdf", "image/jpeg", "image/png")
    return send_file(BytesIO(contenido), mimetype=tipo, as_attachment=not en_pantalla, download_name=elegido.nombre)
