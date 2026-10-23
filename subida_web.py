# -*- coding: utf-8 -*-
"""
«Subir facturas»: la gestoría arrastra PDF, fotos o ZIP en el panel y el agente los lee como si hubieran llegado por correo.

Los archivos se guardan en «Agente Facturas / Entrada» de su OneDrive o Google Drive (una carpeta que crea el propio agente,
así que con Google Drive también la puede ver) y los recoge el mismo proceso que ya vigila esa carpeta (sondeo_entrada).
"""

import logging
import os
import re
import secrets

from flask import Blueprint, jsonify, render_template_string, request, session

from autenticacion_google import ErrorAutorizacionGoogle
from autenticacion_onedrive import ErrorAutorizacionMicrosoft
from basededatos import obtener_estado_conexiones, tenant_tiene_acceso
from estilo_web import pagina
from formatos import EXTENSIONES, tipo_real
from panel_web import login_requerido

log = logging.getLogger("subida_web")
bp_subida = Blueprint("subida", __name__)

MAX_BYTES = 25 * 1024 * 1024
PROVEEDORES = {"onedrive", "gdrive"}

CSS_SUBIDA = """
<style>
  .zona { margin-top: 24px; border: 2px dashed var(--linea-fuerte); border-radius: 12px; background: var(--superficie);
          padding: 40px 24px; text-align: center; transition: border-color .15s, background .15s; }
  .oculto { position: absolute; width: 1px; height: 1px; opacity: 0; overflow: hidden; }
  .zona.encima { border-color: var(--marca); background: var(--marca-clara); outline: none; }
  .zona strong { display: block; font-size: 20px; margin-bottom: 6px; }
  .zona p { margin: 0; color: var(--tinta-2); }
  .lista { list-style: none; margin: 22px 0 0; padding: 0; display: grid; gap: 8px; }
  .lista li { display: flex; gap: 12px; align-items: center; justify-content: space-between; background: var(--superficie);
              border: 1px solid var(--linea); border-radius: 8px; padding: 10px 14px; }
  .lista .nombre { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .lista .estado { flex: none; font-size: 14px; color: var(--tinta-3); }
  .lista .ok .estado { color: var(--ok); font-weight: 500; }
  .lista .mal .estado { color: var(--error); font-weight: 500; text-align: right; }
</style>
"""

PLANTILLA_SUBIR = pagina("Subir facturas", """
<main class="pagina estrecha" style="max-width:760px;">
  <h1 style="font-size:38px;">Subir facturas</h1>
  <p class="tenue" style="margin-top:6px;">Arrastre aquí facturas, tickets o fotos de facturas. El agente las lee y las archiva igual que las del correo.</p>

  {% if not conectado %}
    <p class="alerta" role="alert" style="margin-top:20px;">Antes de subir facturas hace falta conectar su almacenamiento (OneDrive o Google Drive).
      <a class="btn" href="{{ url_for('alta.conexiones') }}">Ir a Conexiones</a></p>
  {% elif not acceso %}
    <p class="alerta error" role="alert" style="margin-top:20px;">Su prueba gratuita ha terminado. Suscríbase en
      <a href="{{ url_for('alta.conexiones') }}">Conexiones y suscripción</a> para seguir subiendo facturas.</p>
  {% else %}
  <form id="formulario" method="post" onsubmit="return false;">
    <div class="zona" id="zona">
      <strong>Arrastre los archivos aquí</strong>
      <p>PDF, fotos (JPG, PNG, HEIC...), ZIP o factura electrónica (XML). Hasta 25 MB cada uno.</p>
      <label class="btn principal grande" for="archivos" style="margin-top:18px;">Elegir archivos del dispositivo</label>
    </div>
    <input id="archivos" class="oculto" type="file" multiple accept="{{ aceptar }}">
  </form>
  <ul class="lista" id="lista" aria-live="polite"></ul>
  <p class="tenue" id="resumen" style="margin-top:16px;"></p>
  <script>
  (function () {
    var zona = document.getElementById('zona'), entrada = document.getElementById('archivos');
    var lista = document.getElementById('lista'), resumen = document.getElementById('resumen');
    var token = (document.querySelector('input[name=csrf_token]') || {}).value || '';
    var MAX = 25 * 1024 * 1024, cola = [], ocupado = false, subidos = 0, fallidos = 0;
    ['dragenter', 'dragover'].forEach(function (n) { zona.addEventListener(n, function (e) { e.preventDefault(); zona.classList.add('encima'); }); });
    ['dragleave', 'drop'].forEach(function (n) { zona.addEventListener(n, function (e) { e.preventDefault(); zona.classList.remove('encima'); }); });
    zona.addEventListener('drop', function (e) { anadir(e.dataTransfer.files); });
    entrada.addEventListener('change', function () { anadir(entrada.files); entrada.value = ''; });

    function anadir(archivos) {
      Array.prototype.forEach.call(archivos, function (f) {
        var li = document.createElement('li'), n = document.createElement('span'), s = document.createElement('span');
        n.className = 'nombre'; n.textContent = f.name; s.className = 'estado'; s.textContent = 'En espera';
        li.appendChild(n); li.appendChild(s); lista.appendChild(li);
        if (f.size > MAX) { marcar(li, s, false, 'Pesa más de 25 MB'); return; }
        cola.push({ f: f, li: li, s: s });
      });
      siguiente();
    }
    function marcar(li, s, bien, texto) {
      li.className = bien ? 'ok' : 'mal'; s.textContent = texto;
      if (bien) { subidos++; } else { fallidos++; }
      resumen.textContent = subidos ? subidos + ' archivo(s) recibido(s). El agente los procesará en uno o dos minutos y los verá en el panel.' + (fallidos ? ' ' + fallidos + ' con problemas.' : '') : '';
    }
    function siguiente() {
      if (ocupado || !cola.length) { return; }
      ocupado = true;
      var t = cola.shift(); t.s.textContent = 'Subiendo...';
      var datos = new FormData(); datos.append('archivo', t.f);
      fetch('{{ url_for("subida.subir_archivo") }}', { method: 'POST', body: datos, headers: { 'X-CSRF-Token': token }, credentials: 'same-origin' })
        .then(function (r) { return r.json().catch(function () { return { ok: false, mensaje: 'Error inesperado' }; }); })
        .then(function (j) { marcar(t.li, t.s, j.ok, j.ok ? 'Recibido' : (j.mensaje || 'No se pudo subir')); })
        .catch(function () { marcar(t.li, t.s, false, 'Sin conexión. Inténtelo de nuevo'); })
        .then(function () { ocupado = false; siguiente(); });
    }
  })();
  </script>
  {% endif %}
</main>
""", activa="subir", extra_head=CSS_SUBIDA)


def _nombre_seguro(nombre):
    base = os.path.basename((nombre or "").replace("\\", "/"))
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", base).strip(" .") or "factura"
    raiz, ext = os.path.splitext(base)
    return f"{secrets.token_hex(3)}_{raiz[:80]}{ext.lower()[:10]}"


@bp_subida.route("/subir")
@login_requerido
def subir():
    tenant_id = session["tenant_id"]
    estado = obtener_estado_conexiones(tenant_id)
    return render_template_string(
        PLANTILLA_SUBIR, gestoria_nombre=estado["nombre"], conectado=estado["almacenamiento"] in PROVEEDORES,
        acceso=tenant_tiene_acceso(tenant_id), aceptar=",".join(sorted(EXTENSIONES)))


@bp_subida.route("/subir/archivo", methods=["POST"])
@login_requerido
def subir_archivo():
    """Recibe UN archivo y lo deja en «Entrada». Responde JSON para que la página muestre el resultado de cada uno."""
    from almacenamiento_tenant import proveedor_almacenamiento, storage_para_tenant
    from sondeo_entrada import asegurar_carpetas
    tenant_id = session["tenant_id"]
    if not tenant_tiene_acceso(tenant_id):
        return jsonify(ok=False, mensaje="Su prueba gratuita ha terminado"), 403
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        return jsonify(ok=False, mensaje="No se ha recibido ningún archivo"), 400
    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in EXTENSIONES:
        return jsonify(ok=False, mensaje="Formato no admitido (use PDF, imagen, ZIP o XML)"), 400
    contenido = archivo.read(MAX_BYTES + 1)
    if len(contenido) > MAX_BYTES:
        return jsonify(ok=False, mensaje="Pesa más de 25 MB"), 400
    if not contenido or tipo_real(contenido) is None:
        return jsonify(ok=False, mensaje="El archivo está vacío o no se puede leer"), 400
    try:
        proveedor = proveedor_almacenamiento(tenant_id)
        if proveedor not in PROVEEDORES:
            return jsonify(ok=False, mensaje="Conecte primero su almacenamiento"), 400
        storage = storage_para_tenant(tenant_id)
        if storage is None:
            return jsonify(ok=False, mensaje="Conecte primero su almacenamiento"), 400
        carpetas = asegurar_carpetas(storage, tenant_id, proveedor)
        storage.subir_archivo(carpetas["entrada"], _nombre_seguro(archivo.filename), contenido)
    except (ErrorAutorizacionGoogle, ErrorAutorizacionMicrosoft):
        return jsonify(ok=False, mensaje="Vuelva a conectar su almacenamiento en Conexiones"), 409
    except Exception:
        log.exception("No se pudo guardar '%s' de la gestoría %s", archivo.filename, tenant_id)
        return jsonify(ok=False, mensaje="No se pudo guardar. Inténtelo de nuevo"), 500
    return jsonify(ok=True)
