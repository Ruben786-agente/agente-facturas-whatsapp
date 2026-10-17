# -*- coding: utf-8 -*-
"""
Acciones del panel sobre lo pendiente: abrir la carpeta en OneDrive o Google Drive, marcar como revisado,
y corregir a mano una factura en Revisión para añadirla al Excel.
"""

import logging

from flask import Blueprint, request, redirect, session, render_template_string, url_for, flash

from almacenamiento_tenant import storage_para_tenant
from basededatos import (marcar_revisada, obtener_carpeta_sin_identificar,
                         obtener_revision, resolver_sin_identificar)
from panel_web import login_requerido
from procesamiento import reprocesar_revision

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


@bp_revision.route("/abrir/sin-identificar")
@login_requerido
def abrir_sin_identificar():
    carpeta = obtener_carpeta_sin_identificar(session["tenant_id"])
    if not carpeta:
        return redirect(url_for("panel.panel"))
    return _abrir(lambda storage: storage.obtener_enlace(carpeta))


# ---------------------------------------------------------------------------
# Corregir y añadir al Excel
# ---------------------------------------------------------------------------

PLANTILLA_CORREGIR = """
<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Corregir factura - Agente Facturas</title>
<style>
  body { font-family: Arial, sans-serif; background: #f4f5f7; margin: 0; padding: 2rem; color: #222; }
  .caja { background: white; padding: 1.5rem 2rem; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); max-width: 860px; }
  label { display: block; font-size: .85em; color: #555; margin-top: 10px; }
  input { padding: 7px; box-sizing: border-box; width: 100%; }
  .fila { display: flex; gap: 12px; flex-wrap: wrap; }
  .fila > div { flex: 1; min-width: 140px; }
  table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  td, th { padding: 4px; font-size: .85em; text-align: left; }
  button { padding: 10px 18px; background: #2d6cdf; color: white; border: none; border-radius: 4px; cursor: pointer; margin-top: 16px; }
  .motivo { background: #fdecea; padding: 10px 14px; border-radius: 4px; }
  .error { background: #fff4e5; padding: 10px 14px; border-radius: 4px; margin-top: 10px; }
</style></head><body>
<div class="caja">
  <p><a href="{{ url_for('panel.panel') }}">&larr; Volver al panel</a> ·
     <a href="{{ url_for('revision.abrir_revision', factura_id=factura_id) }}" target="_blank">Ver el original</a></p>
  <h2>Corregir factura de {{ empresa }}</h2>
  <p class="motivo">Motivo de la revisión: <strong>{{ motivo }}</strong></p>
  {% if error %}<p class="error">Sigue sin poder añadirse: <strong>{{ error }}</strong>. Revisa los importes.</p>{% endif %}
  <form method="post">
    <div class="fila">
      <div><label>Fecha (dd/mm/aaaa)</label><input name="fecha" value="{{ v.fecha }}" required></div>
      <div><label>Nº de factura</label><input name="numero" value="{{ v.numero }}" required></div>
      <div><label>Total factura (€)</label><input name="total" value="{{ v.total }}" required></div>
    </div>
    <div class="fila">
      <div><label>Proveedor</label><input name="emisor_nombre" value="{{ v.emisor_nombre }}"></div>
      <div><label>CIF del proveedor</label><input name="emisor_cif" value="{{ v.emisor_cif }}"></div>
    </div>
    <label>Desglose por tipo de IVA (deja en blanco las filas que no uses)</label>
    <table>
      <tr><th>Base</th><th>% IVA</th><th>Cuota IVA</th><th>Cuota recargo</th><th>Cuota retención</th></tr>
      {% for d in v.desgloses %}
      <tr>
        <td><input name="base{{ loop.index0 }}" value="{{ d.base }}"></td>
        <td><input name="pct_iva{{ loop.index0 }}" value="{{ d.pct_iva }}"></td>
        <td><input name="cuota_iva{{ loop.index0 }}" value="{{ d.cuota_iva }}"></td>
        <td><input name="cuota_recargo{{ loop.index0 }}" value="{{ d.cuota_recargo }}"></td>
        <td><input name="cuota_retencion{{ loop.index0 }}" value="{{ d.cuota_retencion }}"></td>
      </tr>
      {% endfor %}
    </table>
    <button type="submit">Añadir al Excel</button>
  </form>
</div></body></html>
"""


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
    emisor = {**(original.get("emisor") or {}), "nombre": form.get("emisor_nombre", "").strip(),
              "cif_nif": form.get("emisor_cif", "").strip()}
    return {**original, "fecha_factura": form.get("fecha", "").strip(), "num_factura": form.get("numero", "").strip(),
            "total_factura": _numero(form.get("total")), "emisor": emisor, "desgloses": desgloses}


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

    if request.method == "POST":
        try:
            nueva = _factura_desde_formulario(original, request.form)
            valores = _valores_formulario(nueva)
            storage = _storage(tenant_id)
            if not storage:
                raise RuntimeError("No hay almacenamiento conectado")
            res = reprocesar_revision(storage, tenant_id, factura_id, nueva)
            if res["accion"] == "procesada":
                flash("Factura añadida al Excel.")
                return redirect(url_for("panel.panel"))
            if res["accion"] == "duplicado_exacto":
                flash("Esa factura ya estaba anotada en el Excel; se ha quitado de la lista.")
                return redirect(url_for("panel.panel"))
            error = res.get("motivo") or "no se pudo añadir"
        except ValueError as e:
            error = str(e) or "revisa que los números estén bien escritos"
        except Exception:
            log.exception("Fallo corrigiendo la factura %s", factura_id)
            error = "ha habido un problema al guardar en tu almacenamiento; inténtalo de nuevo"

    return render_template_string(PLANTILLA_CORREGIR, factura_id=factura_id, empresa=r["empresa"]["nombre"],
                                  motivo=r["motivo"] or "-", v=valores, error=error)
