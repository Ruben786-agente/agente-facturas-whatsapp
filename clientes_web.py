# -*- coding: utf-8 -*-
"""
«Clientes»: la lista de clientes de la gestoría, con tres cosas que hacer en cada uno:
  - elegir cómo se agrupan sus facturas en el Excel (como el resto, mensual, trimestral o un solo Excel con todas las fechas),
  - quitarlo de la lista (no se borra ninguna carpeta ni archivo),
  - y, arriba, añadir un cliente a mano (para no depender de que el agente lo deduzca de una factura).
"""

import logging

from flask import Blueprint, render_template_string, request, session, redirect, url_for, flash

from almacenamiento_tenant import storage_para_tenant
from basededatos import (reactivar_cliente, listar_clientes, guardar_periodicidad_cliente, quitar_cliente, obtener_periodicidad,
                         obtener_estado_conexiones)
from estilo_web import pagina
from onboarding import alta_empresa_cliente
from panel_web import login_requerido
from validar_cif import comprobar as comprobar_cif

log = logging.getLogger("clientes_web")
bp_clientes = Blueprint("clientes", __name__)

OPCIONES = (("", "Como el resto"), ("mensual", "Un Excel al mes"), ("trimestral", "Un Excel al trimestre"),
            ("unico", "Un solo Excel, con todas las fechas"))
NOMBRE_POR_DEFECTO = {"mensual": "un Excel al mes", "trimestral": "un Excel al trimestre", "unico": "un solo Excel con todas las fechas"}

PLANTILLA = pagina("Clientes", """
<main class="pagina">
  <h1 style="font-size:34px;">Clientes</h1>
  <p class="tenue" style="margin-top:10px;">Aquí están los clientes de su gestoría. Por defecto el agente crea {{ por_defecto }} para cada uno; puede cambiarlo cliente a cliente.
  «Un solo Excel» recoge todas las facturas aunque sean de meses distintos: la fecha de cada línea la puede ajustar usted en el Excel al contabilizarla.</p>
  {% with m = get_flashed_messages() %}{% if m %}<p class="mensaje" role="status" style="margin-top:16px;">{{ m[0] }}</p>{% endif %}{% endwith %}

  <form method="post" action="{{ url_for('clientes.nuevo') }}" class="estado-linea" style="margin-top:20px; gap:8px; flex-wrap:wrap;">
    <input name="nombre" placeholder="Nombre del cliente" aria-label="Nombre del cliente" required style="max-width:260px;">
    <input name="cif" placeholder="CIF/NIF" aria-label="CIF o NIF" required style="max-width:150px;">
    <button class="btn" type="submit">Añadir cliente</button>
  </form>

  {% if clientes %}
  <input id="buscar" type="search" placeholder="Buscar un cliente…" aria-label="Buscar un cliente" style="margin-top:18px; max-width:320px;">
  <div class="tabla" style="margin-top:12px;"><table class="apilable" id="tabla-clientes">
    <tr><th>Cliente</th><th>Excel</th><th></th></tr>
    {% for c in clientes %}
    <tr data-busca="{{ (c.nombre ~ ' ' ~ c.cif_nif)|lower }}">
      <td data-label="Cliente">{{ c.nombre }}<span class="sec">{{ c.cif_nif }}</span></td>
      <td data-label="Excel">
        <form method="post" action="{{ url_for('clientes.periodicidad', empresa_id=c.id) }}">
          <select name="periodicidad" aria-label="Excel de {{ c.nombre }}" onchange="this.form.submit()">
            {% for valor, texto in opciones %}<option value="{{ valor }}" {% if c.periodicidad == valor %}selected{% endif %}>{{ texto }}</option>{% endfor %}
          </select>
        </form>
      </td>
      <td data-label=""><form method="post" action="{{ url_for('clientes.quitar', empresa_id=c.id) }}"><button class="btn discreto" type="submit"
        onclick="return confirm('¿Quitar a {{ c.nombre|replace("'", "") }} de la lista? No se borra ninguna carpeta ni archivo. Si le llega una factura como comprador, irá a «Sin identificar».');">Quitar cliente</button></form></td>
    </tr>
    {% endfor %}
  </table></div>
  <script>
    document.getElementById("buscar").addEventListener("input", function () {
      var q = this.value.toLowerCase();
      document.querySelectorAll("#tabla-clientes tr[data-busca]").forEach(function (f) { f.style.display = f.dataset.busca.indexOf(q) >= 0 ? "" : "none"; });
    });
  </script>
  {% else %}
  <div class="vacio" style="margin-top:22px;"><strong>Todavía no hay clientes.</strong>Se darán de alta solos con la primera factura, o puede añadir uno arriba.</div>
  {% endif %}
</main>
""", activa="clientes")


@bp_clientes.route("/clientes")
@login_requerido
def lista():
    tenant_id = session["tenant_id"]
    return render_template_string(PLANTILLA, clientes=listar_clientes(tenant_id), opciones=OPCIONES,
                                  por_defecto=NOMBRE_POR_DEFECTO.get(obtener_periodicidad(tenant_id), "un Excel al mes"),
                                  gestoria_nombre=obtener_estado_conexiones(tenant_id)["nombre"])


@bp_clientes.route("/clientes/<empresa_id>/periodicidad", methods=["POST"])
@login_requerido
def periodicidad(empresa_id):
    if guardar_periodicidad_cliente(session["tenant_id"], empresa_id, request.form.get("periodicidad", "")):
        flash("Guardado. Vale para las facturas nuevas; los Excel que ya existen no se tocan.")
    else:
        flash("No se ha podido guardar el cambio.")
    return redirect(url_for("clientes.lista"))


@bp_clientes.route("/clientes/<empresa_id>/quitar", methods=["POST"])
@login_requerido
def quitar(empresa_id):
    nombre = quitar_cliente(session["tenant_id"], empresa_id)
    flash(f"{nombre} ya no está en la lista. Sus carpetas y archivos no se han tocado." if nombre else "Ese cliente ya no estaba en la lista.")
    return redirect(url_for("clientes.lista"))


@bp_clientes.route("/clientes/nuevo", methods=["POST"])
@login_requerido
def nuevo():
    tenant_id = session["tenant_id"]
    nombre, (cif, error) = request.form.get("nombre", "").strip(), comprobar_cif(request.form.get("cif", ""))
    if not nombre or error:
        flash(error or "Escriba el nombre del cliente.")
        return redirect(url_for("clientes.lista"))
    try:
        storage = storage_para_tenant(tenant_id)
        if not storage:
            flash("Conecte primero su almacenamiento en Conexiones.")
            return redirect(url_for("clientes.lista"))
        if reactivar_cliente(tenant_id, cif):
            flash(f"{nombre} vuelve a estar en la lista.")
            return redirect(url_for("clientes.lista"))
        r = alta_empresa_cliente(storage, tenant_id, nombre, cif)
        flash(f"{nombre} añadido." if r.get("nueva") else "Ese CIF ya estaba en la lista (o es un cliente que quitó antes).")
    except Exception:
        log.exception("No se pudo añadir el cliente")
        flash("No se ha podido crear el cliente. Compruebe que el almacenamiento sigue conectado.")
    return redirect(url_for("clientes.lista"))
