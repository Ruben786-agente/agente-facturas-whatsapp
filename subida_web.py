# -*- coding: utf-8 -*-
"""
«Subir facturas»: la gestoría arrastra PDF, fotos o ZIP en el panel y el agente los lee como si hubieran llegado por correo.

Los archivos se guardan en «Agente Facturas / Entrada» de su OneDrive o Google Drive (una carpeta que crea el propio agente,
así que con Google Drive también la puede ver) y los recoge el mismo proceso que ya vigila esa carpeta (sondeo_entrada).
"""

import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template_string, request, session

from autenticacion_google import ErrorAutorizacionGoogle
from autenticacion_onedrive import ErrorAutorizacionMicrosoft
from basededatos import crear_subida, listar_subidas, obtener_estado_conexiones, tenant_tiene_acceso
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
  .lista li { flex-wrap: wrap; }
  .lista .estado { max-width: 100%; text-align: right; }
  .progreso { flex-basis: 100%; height: 6px; border-radius: 3px; background: var(--linea); overflow: hidden; }
  .progreso > i { display: block; height: 100%; width: 0; background: var(--marca); transition: width .4s; }
  .lista .ok .progreso > i { background: var(--ok); }
  .lista .aviso .progreso > i { background: #d9a400; }
  .lista .mal .progreso > i { background: var(--error); }
  .lista .aviso .estado { color: #8a6500; font-weight: 500; }
  .lista .detalle { flex-basis: 100%; font-size: 14px; color: var(--tinta-2); margin: 0; }
</style>
"""

PLANTILLA_SUBIR = pagina("Subir facturas", """
<main class="pagina estrecha" style="max-width:760px;">
  <h1 style="font-size:38px;">Subir facturas</h1>
  <p class="tenue" style="margin-top:6px;">Arrastre aquí facturas, tickets o fotos de facturas. El agente las lee y las archiva igual que las del correo. Abajo verá cómo va cada archivo.</p>

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
      <p>PDF, fotos (JPG, PNG, HEIC...), ZIP o factura electrónica (XML). Hasta 25 MB cada uno. También puede arrastrar una carpeta entera.</p>
      <div style="margin-top:18px; display:flex; gap:10px; justify-content:center; flex-wrap:wrap;">
        <label class="btn principal grande" for="archivos">Elegir archivos</label>
        <label class="btn grande" for="carpeta">Subir una carpeta entera</label>
      </div>
    </div>
    <input id="archivos" class="oculto" type="file" multiple accept="{{ aceptar }}">
    <input id="carpeta" class="oculto" type="file" webkitdirectory multiple>
  </form>
  <ul class="lista" id="lista" aria-live="polite"></ul>
  <p class="tenue" id="resumen" style="margin-top:16px;"></p>
  <script>
  (function () {
    var zona = document.getElementById('zona'), entrada = document.getElementById('archivos');
    var lista = document.getElementById('lista'), resumen = document.getElementById('resumen');
    var token = (document.querySelector('input[name=csrf_token]') || {}).value || '';
    var MAX = 25 * 1024 * 1024, cola = [], locales = [], remotos = [], activos = 0, PARALELO = 3, omitidos = 0, temporizador = null;
    var VALIDAS = '{{ aceptar }}'.split(',');
    function valida(nombre) { var i = nombre.lastIndexOf('.'); return i > 0 && VALIDAS.indexOf(nombre.slice(i).toLowerCase()) >= 0; }
    ['dragenter', 'dragover'].forEach(function (n) { zona.addEventListener(n, function (e) { e.preventDefault(); zona.classList.add('encima'); }); });
    ['dragleave', 'drop'].forEach(function (n) { zona.addEventListener(n, function (e) { e.preventDefault(); zona.classList.remove('encima'); }); });
    var carpeta = document.getElementById('carpeta');
    zona.addEventListener('drop', function (e) {
      var items = e.dataTransfer.items;
      if (items && items.length && items[0].webkitGetAsEntry) {
        var entradas = [];
        for (var i = 0; i < items.length; i++) { var en = items[i].webkitGetAsEntry(); if (en) { entradas.push(en); } }
        recoger(entradas);
      } else { anadir(e.dataTransfer.files); }
    });
    entrada.addEventListener('change', function () { anadir(entrada.files); entrada.value = ''; });
    carpeta.addEventListener('change', function () { anadir(carpeta.files); carpeta.value = ''; });

    // Arrastrar carpetas: se recorren (con sus subcarpetas) y se suben los archivos que sirven.
    function recoger(entradas) {
      var pendientes = 0, encontrados = [];
      function fin() { if (pendientes === 0) { anadir(encontrados); } }
      function visitar(en) {
        if (en.isFile) {
          pendientes++;
          en.file(function (f) { encontrados.push(f); pendientes--; fin(); }, function () { pendientes--; fin(); });
        } else if (en.isDirectory) {
          pendientes++;
          var lector = en.createReader(), todos = [];
          (function leer() {
            lector.readEntries(function (lote) {
              if (lote.length) { todos = todos.concat(Array.prototype.slice.call(lote)); leer(); }
              else { todos.forEach(visitar); pendientes--; fin(); }
            }, function () { pendientes--; fin(); });
          })();
        }
      }
      entradas.forEach(visitar);
    }

    function anadir(archivos) {
      Array.prototype.forEach.call(archivos, function (f) {
        if (f.name.charAt(0) === '.' || f.name.charAt(0) === '~' || !valida(f.name)) { omitidos++; return; }
        var it = { nombre: f.name, texto: 'En espera', clase: 'curso', pct: 2 };
        locales.unshift(it);
        if (f.size > MAX) { it.texto = 'Pesa más de 25 MB'; it.clase = 'error'; it.pct = 100; return; }
        cola.push({ f: f, it: it });
      });
      pintar();
      for (var k = 0; k < PARALELO; k++) { siguiente(); }
    }
    function siguiente() {
      if (activos >= PARALELO || !cola.length) { return; }
      activos++;
      var t = cola.shift(); t.it.texto = 'Subiendo...'; t.it.pct = 6; pintar();
      var datos = new FormData(); datos.append('archivo', t.f);
      fetch('{{ url_for("subida.subir_archivo") }}', { method: 'POST', body: datos, headers: { 'X-CSRF-Token': token }, credentials: 'same-origin' })
        .then(function (r) { return r.json().catch(function () { return { ok: false, mensaje: 'Error inesperado' }; }); })
        .then(function (j) {
          if (j.ok) { locales.splice(locales.indexOf(t.it), 1); consultar(); }
          else { t.it.texto = j.mensaje || 'No se pudo subir'; t.it.clase = 'error'; t.it.pct = 100; }
        })
        .catch(function () { t.it.texto = 'Sin conexión. Inténtelo de nuevo'; t.it.clase = 'error'; t.it.pct = 100; })
        .then(function () { activos--; pintar(); siguiente(); });
    }

    function fila(it) {
      var li = document.createElement('li'), n = document.createElement('span'), s = document.createElement('span'), b = document.createElement('div');
      li.className = it.clase === 'ok' ? 'ok' : it.clase === 'aviso' ? 'aviso' : it.clase === 'error' ? 'mal' : '';
      n.className = 'nombre'; n.textContent = it.nombre; s.className = 'estado'; s.textContent = it.texto;
      b.className = 'progreso'; var i = document.createElement('i'); i.style.width = (it.pct || 0) + '%'; b.appendChild(i);
      li.appendChild(n); li.appendChild(s); li.appendChild(b);
      if (it.detalle) { var d = document.createElement('p'); d.className = 'detalle'; d.textContent = it.detalle; li.appendChild(d); }
      return li;
    }
    function pintar() {
      lista.textContent = '';
      locales.concat(remotos).forEach(function (it) { lista.appendChild(fila(it)); });
      var enCurso = remotos.filter(function (r) { return r.clase === 'curso'; }).length;
      resumen.textContent = (omitidos ? omitidos + ' archivo(s) omitido(s) por no ser PDF, imagen, ZIP o XML. ' : '') +
        (enCurso ? 'El agente está trabajando en ' + enCurso + ' archivo(s); esta página se actualiza sola, no hace falta quedarse.' : '');
    }
    function consultar() {
      clearTimeout(temporizador);
      fetch('{{ url_for("subida.estado") }}', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (j) {
        remotos = j.subidas || []; pintar();
        var enCurso = remotos.some(function (r) { return r.clase === 'curso'; }) || locales.length;
        temporizador = setTimeout(consultar, enCurso ? 3000 : 30000);
      }).catch(function () { temporizador = setTimeout(consultar, 8000); });
    }
    consultar();
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
        carpetas = asegurar_carpetas(storage, tenant_id, proveedor, comprobar=True)
        guardado = _nombre_seguro(archivo.filename)
        storage.subir_archivo(carpetas["entrada"], guardado, contenido)
        crear_subida(tenant_id, os.path.basename(archivo.filename), guardado)
    except (ErrorAutorizacionGoogle, ErrorAutorizacionMicrosoft):
        return jsonify(ok=False, mensaje="Vuelva a conectar su almacenamiento en Conexiones"), 409
    except Exception:
        log.exception("No se pudo guardar '%s' de la gestoría %s", archivo.filename, tenant_id)
        return jsonify(ok=False, mensaje="No se pudo guardar. Inténtelo de nuevo"), 500
    return jsonify(ok=True)


def _describir(s):
    """(texto, clase, porcentaje, detalle) de una subida: clase = curso | ok | aviso | error."""
    estado, total, hechos = s["estado"], s["total"] or 0, s["hechos"] or 0
    try:
        resumen = json.loads(s["resumen"]) if s["resumen"] else {}
    except ValueError:
        resumen = {}
    antiguo = (datetime.now(timezone.utc) - s["actualizado_en"]).total_seconds() > 8 * 60 if s["actualizado_en"] else False
    if estado == "terminado":
        buenas = resumen.get("procesada", 0)
        partes = []
        if buenas:
            partes.append(f"{buenas} factura(s) anotada(s) en el Excel")
        if resumen.get("ticket"):
            partes.append(f"{resumen['ticket']} ticket(s) archivado(s)")
        dudosas = resumen.get("revision", 0)
        sin_id = resumen.get("sin_identificar", 0)
        if dudosas:
            partes.append(f"{dudosas} en Revisión")
        if sin_id:
            partes.append(f"{sin_id} sin identificar")
        if resumen.get("duplicado_exacto"):
            partes.append(f"{resumen['duplicado_exacto']} duplicada(s), no se vuelven a anotar")
        if resumen.get("ya_visto"):
            partes.append(f"{resumen['ya_visto']} ya leída(s) antes")
        if resumen.get("ignorado"):
            partes.append(f"{resumen['ignorado']} página(s) que no eran facturas")
        if resumen.get("error") or resumen.get("en_espera"):
            partes.append(f"{resumen.get('error', 0) + resumen.get('en_espera', 0)} con fallo")
        if not partes:
            partes.append("Terminado")
        necesita = dudosas or sin_id or resumen.get("error") or resumen.get("en_espera")
        detalle = "Mírelas en el panel: lo que está en Revisión o Sin identificar necesita su decisión." if (dudosas or sin_id) else None
        return "Terminado: " + ", ".join(partes), ("aviso" if necesita else "ok"), 100, detalle
    if estado == "problema":
        return resumen.get("mensaje") or "No se ha podido procesar este archivo.", "error", 100, None
    if estado == "esperando":
        return "El servicio de lectura no está disponible ahora. Su archivo espera y se leerá solo.", "curso", 15, None
    if estado == "reintentando":
        return "Ha habido un fallo y se está reintentando.", "curso", 30, None
    lento = "Tarda más de lo normal; si sigue así, avísenos." if antiguo else None
    if estado == "leyendo":
        pct = 15 + (int(45 * hechos / total) if total else 10)
        return (f"Leyendo las facturas ({hechos} de {total})" if total > 1 else "Leyendo la factura…"), "curso", pct, lento
    if estado == "guardando":
        pct = 60 + (int(38 * hechos / total) if total else 20)
        return (f"Anotando en el Excel ({hechos} de {total})" if total > 1 else "Anotando en el Excel…"), "curso", pct, lento
    return "Recibido. Esperando su turno (menos de un minuto)", "curso", 12, lento


@bp_subida.route("/subir/estado")
@login_requerido
def estado():
    """Cómo va cada archivo subido hace poco (lo pide la página cada pocos segundos)."""
    salida = []
    for s in listar_subidas(session["tenant_id"]):
        texto, clase, pct, detalle = _describir(s)
        salida.append({"id": s["id"], "nombre": s["nombre"], "texto": texto, "clase": clase, "pct": pct, "detalle": detalle})
    return jsonify(subidas=salida)
