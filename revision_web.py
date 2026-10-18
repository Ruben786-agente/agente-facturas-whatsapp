# -*- coding: utf-8 -*-
"""
Acciones del panel sobre lo pendiente: abrir la carpeta en OneDrive o Google Drive, marcar como revisado,
y corregir a mano una factura en Revisión para añadirla al Excel.
"""

import logging

from flask import Blueprint, request, redirect, session, render_template_string, url_for, flash

from almacenamiento_tenant import storage_para_tenant
from basededatos import (obtener_estado_conexiones, marcar_revisada, obtener_carpeta_sin_identificar,
                         obtener_revision, resolver_sin_identificar)
from estilo_web import pagina
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
      <button class="btn principal grande" type="submit">Añadir al Excel</button>
      <a class="btn" href="{{ url_for('revision.abrir_revision', factura_id=factura_id) }}" target="_blank" rel="noopener">Ver el original</a>
    </div>
  </form>
</main>
""", extra_head=CSS_CORREGIR)


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
            error = str(e) or "revise que los números estén bien escritos"
        except Exception:
            log.exception("Fallo corrigiendo la factura %s", factura_id)
            error = "ha habido un problema al guardar en su almacenamiento; inténtelo de nuevo"

    return render_template_string(PLANTILLA_CORREGIR, factura_id=factura_id, empresa=r["empresa"]["nombre"],
                                  motivo=r["motivo"] or "-", v=valores, error=error,
                                  gestoria_nombre=obtener_estado_conexiones(tenant_id)["nombre"])
