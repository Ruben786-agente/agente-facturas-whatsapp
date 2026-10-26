# -*- coding: utf-8 -*-
"""
Acciones del panel sobre lo pendiente: abrir la carpeta en OneDrive o Google Drive, marcar como revisado,
y corregir a mano una factura en Revisión para añadirla al Excel.
"""

import logging

from validar_cif import comprobar as comprobar_cif
from io import BytesIO

from flask import Blueprint, request, redirect, session, render_template_string, url_for, flash, send_file

from almacenamiento_tenant import storage_para_tenant
from basededatos import (obtener_estado_conexiones, marcar_revisada, obtener_carpeta_sin_identificar,
                         obtener_revision, resolver_sin_identificar, resolver_empresa_cliente_por_cif,
                         listar_proveedores_aprendidos, olvidar_proveedor_aprendido,
                         obtener_sin_identificar, listar_empresas_activas)
from estilo_web import pagina
from panel_web import login_requerido
from periodo_fiscal import nombres_excel_posibles
from procesamiento import reprocesar_revision, asignar_sin_identificar
from clasificador_documentos import nombre_archivo_destino

log = logging.getLogger("revision_web")
bp_revision = Blueprint("revision", __name__)

FILAS_DESGLOSE = 4


def _storage(tenant_id):
    return storage_para_tenant(tenant_id)


def _numero(texto):
    """'1.234,56 €' / '1234.56' / '' -> float o None. Acepta coma decimal."""
    t = (texto or "").replace("€", "").replace(" ", "").strip()
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    return float(t)


# ---------------------------------------------------------------------------
# Marcar como revisado / abrir
# ---------------------------------------------------------------------------

@bp_revision.route("/revision/<factura_id>/revisada", methods=["POST"])
@login_requerido
def revisada(factura_id):
    if marcar_revisada(session["tenant_id"], factura_id):
        flash("Marcada como revisada. Ya no aparece en la lista.")
    return redirect(url_for("panel.panel"))


@bp_revision.route("/sin-identificar/<documento_id>/revisado", methods=["POST"])
@login_requerido
def sin_identificar_revisado(documento_id):
    if resolver_sin_identificar(session["tenant_id"], documento_id):
        flash("Documento quitado de la lista de sin identificar.")
    return redirect(url_for("panel.panel"))


def _abrir(enlace_fn):
    try:
        storage = _storage(session["tenant_id"])
        if not storage:
            raise RuntimeError("No hay almacenamiento conectado")
        return redirect(enlace_fn(storage))
    except Exception:
        log.exception("No se pudo abrir el enlace de OneDrive")
        flash("No se ha podido abrir la carpeta. Puede que ya no exista o que haya que volver a conectar el almacenamiento.")
        return redirect(url_for("panel.panel"))


@bp_revision.route("/abrir/revision/<factura_id>")
@login_requerido
def abrir_revision(factura_id):
    r = obtener_revision(session["tenant_id"], factura_id)
    if not r:
        return redirect(url_for("panel.panel"))
    carpeta = r["empresa"]["carpeta_revision_id"]
    nombre = (r["datos"] or {}).get("archivo")

    def enlace(storage):
        if nombre:
            archivo = storage.buscar_archivo_por_nombre(carpeta, nombre)
            if archivo:
                return storage.obtener_enlace(archivo.id)
        return storage.obtener_enlace(carpeta)
    return _abrir(enlace)


def _tipo_archivo(nombre, contenido):
    """Tipo de contenido para enseñar el original en el navegador (PDF o imagen)."""
    n = (nombre or "").lower()
    if contenido[:5] == b"%PDF-" or n.endswith(".pdf"):
        return "application/pdf"
    if contenido[:3] == b"\xff\xd8\xff" or n.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if contenido[:8] == b"\x89PNG\r\n\x1a\n" or n.endswith(".png"):
        return "image/png"
    return "application/octet-stream"


@bp_revision.route("/ver/revision/<factura_id>")
@login_requerido
def ver_revision(factura_id):
    """Enseña la factura original en el navegador, leyéndola del almacenamiento a través del agente
    (no hace falta abrir OneDrive ni Google Drive)."""
    r = obtener_revision(session["tenant_id"], factura_id)
    if not r:
        return redirect(url_for("panel.panel"))
    nombre = (r["datos"] or {}).get("archivo")
    try:
        storage = _storage(session["tenant_id"])
        if not storage:
            raise RuntimeError("No hay almacenamiento conectado")
        archivo = storage.buscar_archivo_por_nombre(r["empresa"]["carpeta_revision_id"], nombre) if nombre else None
        if not archivo:
            flash("No se encuentra el original en la carpeta de revisión (puede que lo haya movido o borrado).")
            return redirect(url_for("panel.panel"))
        contenido = storage.descargar_archivo(archivo.id)
    except Exception:
        log.exception("No se pudo leer la factura original")
        flash("No se ha podido abrir la factura. Compruebe que el almacenamiento sigue conectado en Conexiones.")
        return redirect(url_for("panel.panel"))
    tipo = _tipo_archivo(nombre, contenido)
    return send_file(BytesIO(contenido), mimetype=tipo, as_attachment=(tipo == "application/octet-stream"),
                     download_name=nombre or "factura")


@bp_revision.route("/sin-identificar/<documento_id>/ver")
@login_requerido
def ver_sin_identificar(documento_id):
    """Enseña un documento de «Sin identificar» leyéndolo a través del agente."""
    d = obtener_sin_identificar(session["tenant_id"], documento_id)
    carpeta = obtener_carpeta_sin_identificar(session["tenant_id"])
    if not d or not carpeta:
        return redirect(url_for("panel.panel"))
    nombre = nombre_archivo_destino(d["nombre_archivo"], "REVISION", d["motivo"])
    try:
        storage = _storage(session["tenant_id"])
        archivo = storage.buscar_archivo_por_nombre(carpeta, nombre) if storage else None
        if not archivo:
            flash("No se encuentra el documento en la carpeta «Sin identificar» (puede que lo haya movido o borrado).")
            return redirect(url_for("panel.panel"))
        contenido = storage.descargar_archivo(archivo.id)
    except Exception:
        log.exception("No se pudo leer el documento sin identificar")
        flash("No se ha podido abrir el documento. Compruebe que el almacenamiento sigue conectado en Conexiones.")
        return redirect(url_for("panel.panel"))
    tipo = _tipo_archivo(nombre, contenido)
    return send_file(BytesIO(contenido), mimetype=tipo, as_attachment=(tipo == "application/octet-stream"), download_name=nombre)




@bp_revision.route("/sin-identificar/<documento_id>/asignar", methods=["GET", "POST"])
@login_requerido
def asignar(documento_id):
    tenant_id = session["tenant_id"]
    d = obtener_sin_identificar(tenant_id, documento_id)
    if not d:
        flash("Ese documento ya no está pendiente.")
        return redirect(url_for("panel.panel"))
    error = None
    if request.method == "POST":
        try:
            storage = _storage(tenant_id)
            if not storage:
                raise RuntimeError("No hay almacenamiento conectado")
            res = asignar_sin_identificar(storage, tenant_id, d, request.form.get("cif_empresa", ""))
            if res["accion"] == "error":
                error = res["motivo"]
            else:
                destino = {"procesada": "Anotada en el Excel.", "duplicado_exacto": "Ya estaba anotada, no se ha duplicado.",
                           "ticket": "Guardada como ticket.", "revision": "Ha quedado en la Revisión de ese cliente para que la corrija (" + str(res.get("motivo") or "") + ")."
                           }.get(res["accion"], "Hecho.")
                flash(f"Asignada a {res['empresa']}. {destino}")
                return redirect(url_for("panel.panel"))
        except Exception:
            log.exception("Fallo asignando el documento %s", documento_id)
            error = "Ha habido un problema. Inténtelo de nuevo."
    return render_template_string(PLANTILLA_ASIGNAR, documento_id=documento_id, motivo=d["motivo"] or "-", error=error,
                                  empresas=listar_empresas_activas(tenant_id),
                                  gestoria_nombre=obtener_estado_conexiones(tenant_id)["nombre"])


@bp_revision.route("/abrir/sin-identificar")
@login_requerido
def abrir_sin_identificar():
    carpeta = obtener_carpeta_sin_identificar(session["tenant_id"])
    if not carpeta:
        return redirect(url_for("panel.panel"))
    return _abrir(lambda storage: storage.obtener_enlace(carpeta))


@bp_revision.route("/abrir/excel")
@login_requerido
def abrir_excel():
    """Abre en OneDrive o Google Drive el Excel de un cliente y periodo (o, si ya no está, la carpeta de Excel)."""
    empresa = resolver_empresa_cliente_por_cif(session["tenant_id"], [request.args.get("cif", "")])
    periodo = request.args.get("periodo", "")
    if not empresa or not empresa.get("carpeta_excel_id"):
        return redirect(url_for("panel.panel"))
    carpeta = empresa["carpeta_excel_id"]
    nombres = nombres_excel_posibles(empresa["cif_nif"], periodo)

    def enlace(storage):
        for nombre in nombres:
            archivo = storage.buscar_archivo_por_nombre(carpeta, nombre)
            if archivo:
                return storage.obtener_enlace(archivo.id)
        return storage.obtener_enlace(carpeta)
    return _abrir(enlace)


@bp_revision.route("/descargar/excel")
@login_requerido
def descargar_excel():
    """Descarga el Excel de un cliente y periodo a través del agente: no hace falta abrir OneDrive ni Google Drive."""
    empresa = resolver_empresa_cliente_por_cif(session["tenant_id"], [request.args.get("cif", "")])
    if not empresa or not empresa.get("carpeta_excel_id"):
        return redirect(url_for("panel.panel"))
    nombres = nombres_excel_posibles(empresa["cif_nif"], request.args.get("periodo", ""))
    try:
        storage = _storage(session["tenant_id"])
        if not storage:
            raise RuntimeError("No hay almacenamiento conectado")
        archivo, nombre = None, nombres[0]
        for candidato in nombres:
            archivo = storage.buscar_archivo_por_nombre(empresa["carpeta_excel_id"], candidato)
            if archivo:
                nombre = candidato
                break
        if not archivo:
            flash("Ese Excel ya no está en la carpeta (puede que lo haya retirado). Las facturas nuevas irán a uno nuevo.")
            return redirect(url_for("panel.panel"))
        contenido = storage.descargar_archivo(archivo.id)
    except Exception:
        log.exception("No se pudo descargar el Excel")
        flash("No se ha podido descargar el Excel. Compruebe que el almacenamiento sigue conectado en Conexiones.")
        return redirect(url_for("panel.panel"))
    return send_file(BytesIO(contenido), as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------------------
# Corregir y añadir al Excel
# ---------------------------------------------------------------------------

CSS_CORREGIR = """
<style>
  .volver { display: inline-block; margin-bottom: 18px; text-decoration: none; color: var(--tinta-2); }
  .volver:hover { color: var(--marca); }
  .motivo { margin: 18px 0 0; }
  .formulario { margin-top: 24px; background: var(--superficie); border: 1px solid var(--linea); border-radius: 10px; padding: 8px 28px 28px; }
  .fila { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0 18px; }
  .desglose { width: 100%; min-width: 0; border-collapse: separate; border-spacing: 0 6px; margin-top: 4px; }
  .desglose th { padding: 4px 6px 2px; border: 0; }
  .desglose td { padding: 0 6px 0 0; border: 0; }
  .desglose input { padding: 8px 10px; }
  .desglose-envoltorio { overflow-x: auto; }
  .desglose-envoltorio .desglose { min-width: 560px; }
  .pie-formulario { display: flex; gap: 12px; align-items: center; margin-top: 22px; flex-wrap: wrap; }
  .otra-via { margin-top: 44px; padding-top: 18px; border-top: 1px solid var(--linea); display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
  .otra-via p { margin: 0; flex: 1 1 260px; }
  .trabajando { position: fixed; inset: 0; z-index: 50; display: none; align-items: center; justify-content: center; flex-direction: column; gap: 16px;
    background: rgba(255,255,255,.92); text-align: center; padding: 24px; }
  .trabajando.activo { display: flex; }
  .trabajando .rueda { width: 44px; height: 44px; border-radius: 50%; border: 4px solid var(--linea); border-top-color: var(--marca); animation: gira 0.9s linear infinite; }
  .trabajando strong { font-size: 20px; }
  @keyframes gira { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .trabajando .rueda { animation: none; } }
</style>
"""

PLANTILLA_CORREGIR = pagina("Corregir factura", """
<main class="pagina estrecha" style="max-width:860px;">
  <a class="volver" href="{{ url_for('panel.panel') }}">&larr; Volver al panel</a>
  <h1 style="font-size:36px;">Corregir factura de {{ empresa }}</h1>
  <p class="alerta motivo">Motivo de la revisión: <strong>{{ motivo }}</strong></p>
  {% if error %}<p class="alerta error" role="alert">Sigue sin poder añadirse: <strong>{{ error }}</strong>. Revise los importes.</p>{% endif %}
  <form class="formulario" method="post">
    <div class="fila">
      <div><label for="fecha">Fecha (dd/mm/aaaa)</label><input id="fecha" name="fecha" value="{{ v.fecha }}" required></div>
      <div><label for="numero">Nº de factura</label><input id="numero" name="numero" value="{{ v.numero }}" required></div>
      <div><label for="total">Total factura (€)</label><input id="total" name="total" value="{{ v.total }}" required inputmode="decimal"></div>
    </div>
    <div class="fila">
      <div><label for="emisor_nombre">Proveedor</label><input id="emisor_nombre" name="emisor_nombre" value="{{ v.emisor_nombre }}"></div>
      <div><label for="emisor_cif">CIF del proveedor</label><input id="emisor_cif" name="emisor_cif" value="{{ v.emisor_cif }}"></div>
    </div>
    <label>Desglose por tipo de IVA <small>(deje en blanco las filas que no use)</small></label>
    <div class="desglose-envoltorio"><table class="desglose">
      <tr><th>Base</th><th>% IVA</th><th>Cuota IVA</th><th>Cuota recargo</th><th>Cuota retención</th></tr>
      {% for d in v.desgloses %}
      <tr>
        <td><input name="base{{ loop.index0 }}" value="{{ d.base }}" inputmode="decimal" aria-label="Base, fila {{ loop.index }}"></td>
        <td><input name="pct_iva{{ loop.index0 }}" value="{{ d.pct_iva }}" inputmode="decimal" aria-label="Porcentaje de IVA, fila {{ loop.index }}"></td>
        <td><input name="cuota_iva{{ loop.index0 }}" value="{{ d.cuota_iva }}" inputmode="decimal" aria-label="Cuota de IVA, fila {{ loop.index }}"></td>
        <td><input name="cuota_recargo{{ loop.index0 }}" value="{{ d.cuota_recargo }}" inputmode="decimal" aria-label="Cuota de recargo, fila {{ loop.index }}"></td>
        <td><input name="cuota_retencion{{ loop.index0 }}" value="{{ d.cuota_retencion }}" inputmode="decimal" aria-label="Cuota de retención, fila {{ loop.index }}"></td>
      </tr>
      {% endfor %}
    </table></div>
    <div class="pie-formulario">
      <button class="btn principal grande" type="submit" name="accion" value="anadir">Añadir al Excel</button>
      <a class="btn" href="{{ url_for('revision.ver_revision', factura_id=factura_id) }}" target="_blank" rel="noopener">Ver el original</a>
    </div>
    <div class="otra-via">
      <p class="tenue">¿Ya la ha gestionado por otra vía? Puede retirarla de la lista sin añadirla al Excel.</p>
      <button class="btn discreto" type="submit" name="accion" value="gestionada" formnovalidate
        onclick="return confirm('¿Marcar como gestionada? Ya no aparecerá en el panel y no se añadirá al Excel desde aquí.');">Marcar como gestionada</button>
    </div>
  </form>
</main>
<div class="trabajando" id="trabajando" role="alert" aria-live="assertive">
  <div class="rueda" aria-hidden="true"></div>
  <strong id="trabajando-texto">Añadiendo al Excel…</strong>
  <span class="tenue">Puede tardar unos segundos. No cierre ni recargue esta página.</span>
</div>
<script>
(function () {
  var f = document.querySelector("form.formulario"), enviado = false;
  f.addEventListener("submit", function (e) {
    if (enviado) { e.preventDefault(); return; }
    enviado = true;
    var b = e.submitter, h = document.createElement("input");
    h.type = "hidden"; h.name = "accion"; h.value = b ? b.value : "anadir"; f.appendChild(h);
    document.getElementById("trabajando-texto").textContent = (h.value === "gestionada") ? "Guardando…" : "Añadiendo al Excel…";
    document.getElementById("trabajando").classList.add("activo");
    setTimeout(function () { f.querySelectorAll("button").forEach(function (x) { x.disabled = true; }); }, 0);
  });
  window.addEventListener("pageshow", function (ev) {  // al volver atrás con el navegador, se vuelve a poder usar
    if (ev.persisted) { enviado = false; document.getElementById("trabajando").classList.remove("activo"); f.querySelectorAll("button").forEach(function (x) { x.disabled = false; }); }
  });
})();
</script>
""", extra_head=CSS_CORREGIR)


PLANTILLA_CONFIRMACION = pagina("Hecho", """
<main class="pagina estrecha" style="max-width:700px;">
  <div class="mensaje" role="status" style="margin-top:28px; padding:22px 24px;">
    <h1 style="font-size:30px; margin:0 0 8px;">&#10003; {{ titulo }}</h1>
    <p style="margin:0;">{{ detalle }}</p>
  </div>
  <div class="pie-formulario" style="margin-top:24px;">
    <a class="btn principal grande" href="{{ url_for('panel.panel') }}">Volver al panel</a>
    <a class="btn" href="{{ url_for('revision.recordados') }}">Proveedores recordados</a>
    {% if otra %}<a class="btn" href="{{ url_for('revision.corregir', factura_id=otra) }}">Corregir la siguiente en Revisión</a>{% endif %}
  </div>
</main>
""", extra_head=CSS_CORREGIR)


PLANTILLA_ASIGNAR = pagina("Asignar a un cliente", """
<main class="pagina estrecha" style="max-width:700px;">
  <a class="volver" href="{{ url_for('panel.panel') }}">&larr; Volver al panel</a>
  <h1 style="font-size:36px;">¿De qué cliente es este documento?</h1>
  <p class="alerta motivo">Por qué está sin identificar: <strong>{{ motivo }}</strong></p>
  {% if error %}<p class="alerta error" role="alert">{{ error }}</p>{% endif %}
  <form class="formulario" method="post">
    <label for="cif_empresa">Cliente al que pertenece</label>
    <select id="cif_empresa" name="cif_empresa" required>
      {% if empresas|length != 1 %}<option value="">Elija un cliente…</option>{% endif %}
      {% for e in empresas %}<option value="{{ e.cif_nif }}" {% if empresas|length == 1 %}selected{% endif %}>{{ e.nombre }} ({{ e.cif_nif }})</option>{% endfor %}
    </select>
    <p class="tenue" style="margin-top:10px;">El agente volverá a leer el documento con ese cliente como comprador. Si todo cuadra, lo anota en el Excel; si algo
    es dudoso, lo deja en la Revisión de ese cliente para que lo corrija.</p>
    <div class="pie-formulario">
      <button class="btn principal grande" type="submit">Asignar y añadir</button>
      <a class="btn" href="{{ url_for('revision.ver_sin_identificar', documento_id=documento_id) }}" target="_blank" rel="noopener">Ver el documento</a>
    </div>
  </form>
</main>
<div class="trabajando" id="trabajando" role="alert" aria-live="assertive">
  <div class="rueda" aria-hidden="true"></div>
  <strong>Leyendo y añadiendo…</strong>
  <span class="tenue">Puede tardar unos segundos. No cierre ni recargue esta página.</span>
</div>
<script>
(function () {
  var f = document.querySelector("form.formulario"), enviado = false;
  f.addEventListener("submit", function (e) {
    if (enviado) { e.preventDefault(); return; }
    enviado = true; document.getElementById("trabajando").classList.add("activo");
    setTimeout(function () { f.querySelectorAll("button").forEach(function (x) { x.disabled = true; }); }, 0);
  });
  window.addEventListener("pageshow", function (ev) {
    if (ev.persisted) { enviado = false; document.getElementById("trabajando").classList.remove("activo"); f.querySelectorAll("button").forEach(function (x) { x.disabled = false; }); }
  });
})();
</script>
""", extra_head=CSS_CORREGIR)


def _confirmacion(tenant_id, titulo, detalle, excluir=None):
    try:
        from basededatos import obtener_otra_revision
        otra = obtener_otra_revision(tenant_id, excluir)
    except Exception:
        otra = None
    return render_template_string(PLANTILLA_CONFIRMACION, titulo=titulo, detalle=detalle, otra=otra,
                                  gestoria_nombre=obtener_estado_conexiones(tenant_id)["nombre"])


def _valores_formulario(factura):
    def f(x):
        return "" if x is None else x
    desgloses = [
        {"base": f(d.get("base")), "pct_iva": f(d.get("pct_iva")), "cuota_iva": f(d.get("cuota_iva")),
         "cuota_recargo": f(d.get("cuota_recargo")), "cuota_retencion": f(d.get("cuota_retencion"))}
        for d in (factura.get("desgloses") or [])[:FILAS_DESGLOSE]
    ]
    while len(desgloses) < FILAS_DESGLOSE:
        desgloses.append({"base": "", "pct_iva": "", "cuota_iva": "", "cuota_recargo": "", "cuota_retencion": ""})
    emisor = factura.get("emisor") or {}
    return {
        "fecha": f(factura.get("fecha_factura")), "numero": f(factura.get("num_factura")),
        "total": f(factura.get("total_factura")), "emisor_nombre": f(emisor.get("nombre")),
        "emisor_cif": f(emisor.get("cif_nif")), "desgloses": desgloses,
    }


def _factura_desde_formulario(original, form):
    """Mezcla lo escrito en el formulario con la lectura original (domicilio, destinatario...)."""
    desgloses = []
    previos = original.get("desgloses") or []
    for i in range(FILAS_DESGLOSE):
        base = _numero(form.get(f"base{i}"))
        if base is None:
            continue
        previo = previos[i] if i < len(previos) else {}
        desgloses.append({
            "base": base, "pct_iva": _numero(form.get(f"pct_iva{i}")) or 0,
            "cuota_iva": _numero(form.get(f"cuota_iva{i}")) or 0,
            "pct_recargo": previo.get("pct_recargo"), "cuota_recargo": _numero(form.get(f"cuota_recargo{i}")),
            "pct_retencion": previo.get("pct_retencion"), "cuota_retencion": _numero(form.get(f"cuota_retencion{i}")),
        })
    if not desgloses:
        raise ValueError("Hace falta al menos una fila de desglose.")
    cif, error_cif = comprobar_cif(form.get("emisor_cif", ""))
    if error_cif:
        raise ValueError(error_cif)
    emisor = {**(original.get("emisor") or {}), "nombre": form.get("emisor_nombre", "").strip(), "cif_nif": cif}
    return {**original, "fecha_factura": form.get("fecha", "").strip(), "num_factura": form.get("numero", "").strip(),
            "total_factura": _numero(form.get("total")), "emisor": emisor, "desgloses": desgloses}


PLANTILLA_RECORDADOS = pagina("Proveedores recordados", """
<main class="pagina" style="max-width:820px;">
  <h1 style="font-size:34px;">Proveedores recordados</h1>
  <p class="tenue" style="margin-top:10px;">Cuando usted corrige a mano el CIF de un proveedor, el agente lo recuerda. Si una factura posterior de ese mismo
  proveedor llega con el CIF ilegible o incompleto, lo completa con el que usted confirmó. Nunca cambia un CIF que haya leído bien.
  Aquí puede ver lo que recuerda y borrarlo.</p>
  {% with m = get_flashed_messages() %}{% if m %}<p class="mensaje" role="status" style="margin-top:16px;">{{ m[0] }}</p>{% endif %}{% endwith %}
  {% if filas %}
  <div class="tabla" style="margin-top:22px;"><table class="apilable">
    <tr><th>Proveedor</th><th>CIF recordado</th><th class="num">Veces usado</th><th></th></tr>
    {% for f in filas %}
    <tr>
      <td data-label="Proveedor">{{ f.nombre }}</td><td data-label="CIF recordado">{{ f.cif_nif }}</td><td data-label="Veces usado" class="num">{{ f.veces }}</td>
      <td><form method="post" action="{{ url_for('revision.olvidar', aprendido_id=f.id) }}"><button class="btn" type="submit">Olvidar</button></form></td>
    </tr>
    {% endfor %}
  </table></div>
  {% else %}
  <div class="vacio" style="margin-top:22px;"><strong>Todavía no recuerda ningún proveedor.</strong>Aparecerán aquí cuando corrija el CIF de una factura en Revisión.</div>
  {% endif %}
  <p style="margin-top:22px;"><a class="btn" href="{{ url_for('panel.panel') }}">Volver al panel</a></p>
</main>
""")


@bp_revision.route("/proveedores-recordados")
@login_requerido
def recordados():
    tenant_id = session["tenant_id"]
    return render_template_string(PLANTILLA_RECORDADOS, filas=listar_proveedores_aprendidos(tenant_id),
                                  gestoria_nombre=obtener_estado_conexiones(tenant_id)["nombre"])


@bp_revision.route("/proveedores-recordados/<aprendido_id>/olvidar", methods=["POST"])
@login_requerido
def olvidar(aprendido_id):
    flash("Hecho: el agente ya no recuerda ese proveedor." if olvidar_proveedor_aprendido(session["tenant_id"], aprendido_id)
          else "Ese proveedor ya no estaba en la lista.")
    return redirect(url_for("revision.recordados"))


@bp_revision.route("/revision/<factura_id>/corregir", methods=["GET", "POST"])
@login_requerido
def corregir(factura_id):
    tenant_id = session["tenant_id"]
    r = obtener_revision(tenant_id, factura_id)
    if not r or r["destino"] != "REVISION" or not r["datos"] or not r["datos"].get("factura"):
        flash("Esta factura no se puede corregir desde aquí.")
        return redirect(url_for("panel.panel"))
    original = r["datos"]["factura"]
    error, valores = None, _valores_formulario(original)

    if request.method == "POST" and request.form.get("accion") == "gestionada":
        if marcar_revisada(tenant_id, factura_id):
            return _confirmacion(tenant_id, "Marcada como gestionada",
                                 "Ya no aparece en la lista de Revisión. No se ha añadido nada al Excel.", factura_id)
        flash("Esta factura ya no estaba pendiente.")
        return redirect(url_for("panel.panel"))

    if request.method == "POST":
        try:
            nueva = _factura_desde_formulario(original, request.form)
            valores = _valores_formulario(nueva)
            storage = _storage(tenant_id)
            if not storage:
                raise RuntimeError("No hay almacenamiento conectado")
            res = reprocesar_revision(storage, tenant_id, factura_id, nueva)
            resumen = f"Factura {nueva.get('num_factura') or ''} de {(nueva.get('emisor') or {}).get('nombre') or 'su proveedor'}, total {nueva.get('total_factura')} €."
            if res["accion"] == "procesada":
                return _confirmacion(tenant_id, "Factura añadida al Excel",
                                     f"{resumen} Se ha anotado en el Excel de {r['empresa']['nombre']}"
                                     + (f" ({res['excel']})." if res.get("excel") else "."), factura_id)
            if res["accion"] == "duplicado_exacto":
                return _confirmacion(tenant_id, "Esa factura ya estaba en el Excel",
                                     f"{resumen} Ya estaba anotada, así que no se ha duplicado y se ha quitado de la lista.", factura_id)
            error = res.get("motivo") or "no se pudo añadir"
        except ValueError as e:
            error = str(e) or "revise que los números estén bien escritos"
        except Exception:
            log.exception("Fallo corrigiendo la factura %s", factura_id)
            error = "ha habido un problema al guardar en su almacenamiento; inténtelo de nuevo"

    return render_template_string(PLANTILLA_CORREGIR, factura_id=factura_id, empresa=r["empresa"]["nombre"],
                                  motivo=r["motivo"] or "-", v=valores, error=error,
                                  gestoria_nombre=obtener_estado_conexiones(tenant_id)["nombre"])
