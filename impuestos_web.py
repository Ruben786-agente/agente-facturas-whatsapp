# -*- coding: utf-8 -*-
"""Página «Impuestos»: borrador orientativo del 303 y del 130 de un cliente y trimestre, calculado desde sus Excel."""
import logging
from datetime import datetime

from flask import Blueprint, request, session, render_template_string

from almacenamiento_tenant import storage_para_tenant
from basededatos import listar_clientes, obtener_estado_conexiones, resolver_empresa_cliente_por_cif, registrar_actividad
from estilo_web import pagina
from impuestos import juntar_facturas, modelo_303, modelo_130, ES_PERSONA, TRIMESTRES
from panel_web import login_requerido
from periodo_fiscal import MESES, PERIODO_UNICO, nombre_excel

log = logging.getLogger("impuestos_web")
bp_impuestos = Blueprint("impuestos", __name__)

PLANTILLA = pagina("Impuestos", """
<main class="pagina">
  <h1 style="font-size:34px;">Impuestos (borrador)</h1>
  <p class="tenue" style="margin-top:10px;">Borrador <strong>orientativo</strong> del modelo 303 (IVA) y del 130 (IRPF de autónomos), calculado con las facturas ya anotadas en los Excel del cliente.
  No presenta nada: sirve para adelantar trabajo y debe revisarlo usted antes de presentar.</p>
  <form method="get" class="estado-linea" style="margin-top:20px; gap:8px; flex-wrap:wrap;">
    <select name="cif" aria-label="Cliente" required>
      <option value="">Elija cliente…</option>
      {% for c in clientes %}<option value="{{ c.cif_nif }}" {% if c.cif_nif == cif %}selected{% endif %}>{{ c.nombre }} ({{ c.cif_nif }})</option>{% endfor %}
    </select>
    <select name="anio" aria-label="Año">{% for a in anios %}<option value="{{ a }}" {% if a == anio %}selected{% endif %}>{{ a }}</option>{% endfor %}</select>
    <select name="trimestre" aria-label="Trimestre">{% for t in (1,2,3,4) %}<option value="{{ t }}" {% if t == trimestre %}selected{% endif %}>{{ t }}T</option>{% endfor %}</select>
    <button class="btn" type="submit">Calcular</button>
  </form>
  {% if error %}<p class="mensaje" role="status" style="margin-top:16px;">{{ error }}</p>{% endif %}
  {% if r %}
  <h2 style="margin-top:28px;">{{ nombre }} · {{ trimestre }}T {{ anio }}</h2>
  <p class="tenue">Facturas leídas: {{ r.n_facturas }} ({{ r.n_excels }} Excel).</p>

  <h3 style="margin-top:20px;">Modelo 303 · IVA</h3>
  <table class="tabla"><thead><tr><th>Casilla</th><th>Concepto</th><th>Base</th><th>Cuota</th></tr></thead><tbody>
  {% for f in r.m303.repercutido %}<tr><td>{{ f.casilla }}</td><td>{{ f.texto }}</td><td>{{ f.base|eur }}</td><td>{{ f.cuota|eur }}</td></tr>{% endfor %}
  {% if not r.m303.repercutido %}<tr><td>—</td><td>Sin ventas en el trimestre</td><td>0,00 €</td><td>0,00 €</td></tr>{% endif %}
  <tr><td>27</td><td><strong>Total IVA devengado</strong></td><td></td><td><strong>{{ r.m303.total_devengado|eur }}</strong></td></tr>
  <tr><td>28 / 29</td><td>IVA soportado en compras (todo considerado deducible)</td><td>{{ r.m303.soportado_base|eur }}</td><td>{{ r.m303.soportado_cuota|eur }}</td></tr>
  <tr><td>45</td><td><strong>Total a deducir</strong></td><td></td><td><strong>{{ r.m303.soportado_cuota|eur }}</strong></td></tr>
  <tr><td>46 / 71</td><td><strong>{% if r.m303.resultado >= 0 %}Resultado: a ingresar{% else %}Resultado: a compensar / devolver{% endif %}</strong></td><td></td><td><strong>{{ r.m303.resultado|eur }}</strong></td></tr>
  </tbody></table>

  <h3 style="margin-top:24px;">Modelo 130 · IRPF (estimación directa)</h3>
  {% if r.persona %}
  <table class="tabla"><tbody>
  <tr><td>01</td><td>Ingresos acumulados desde el 1 de enero</td><td>{{ r.m130.ingresos|eur }}</td></tr>
  <tr><td>02</td><td>Gastos deducibles acumulados</td><td>{{ r.m130.gastos|eur }}</td></tr>
  <tr><td>03</td><td>Rendimiento neto</td><td>{{ r.m130.neto|eur }}</td></tr>
  <tr><td>04</td><td>20 % del rendimiento neto</td><td>{{ r.m130.pago20|eur }}</td></tr>
  <tr><td>06</td><td>Pagos de trimestres anteriores (calculados)</td><td>{{ r.m130.anteriores|eur }}</td></tr>
  <tr><td>07</td><td>Retenciones que le han practicado en sus ventas</td><td>{{ r.m130.retenciones|eur }}</td></tr>
  <tr><td>19</td><td><strong>Resultado a ingresar</strong></td><td><strong>{{ r.m130.resultado|eur }}</strong></td></tr>
  </tbody></table>
  {% else %}<p class="tenue">Este cliente es una sociedad: el 130 solo lo presentan autónomos (las sociedades tributan por el Impuesto de Sociedades).</p>{% endif %}

  <div class="tenue" style="margin-top:20px;">
    <strong>Qué debe revisar:</strong>
    <ul style="margin:6px 0 0 18px;">
      <li>Se considera deducible todo el IVA de las compras; si hay gastos no deducibles, réstelos.</li>
      <li>El 130 no incluye el 5 % de difícil justificación ni deducciones especiales, y supone que los pagos anteriores se hicieron como aquí se calculan.</li>
      <li>Operaciones intracomunitarias, inversión del sujeto pasivo, recargo de equivalencia, prorrata y regímenes especiales no se tratan: revíselas aparte.</li>
      <li>Solo cuenta lo que está en los Excel: si hay facturas pendientes en Revisión, faltarán.</li>
    </ul>
  </div>
  {% endif %}
</main>
""", activa="impuestos")


def _cargar_excels(tenant_id, empresa, anio, trimestre):
    storage = storage_para_tenant(tenant_id)
    if not storage:
        raise RuntimeError("No hay almacenamiento conectado")
    nombres = [nombre_excel(empresa["cif_nif"], PERIODO_UNICO)]
    for t in range(1, trimestre + 1):
        nombres.append(nombre_excel(empresa["cif_nif"], f"Trimestre {t} - {anio}"))
    for m in range(1, TRIMESTRES[trimestre][1] + 1):
        nombres.append(nombre_excel(empresa["cif_nif"], f"{MESES[m - 1]} {anio}"))
    contenidos = []
    for n in nombres:
        archivo = storage.buscar_archivo_por_nombre(empresa["carpeta_excel_id"], n)
        if archivo:
            contenidos.append(storage.descargar_archivo(archivo.id))
    return contenidos


@bp_impuestos.route("/impuestos")
@login_requerido
def borrador():
    t = session["tenant_id"]
    hoy = datetime.now()
    cif = (request.args.get("cif") or "").strip().upper()
    try:
        anio = int(request.args.get("anio") or hoy.year)
        trimestre = int(request.args.get("trimestre") or (hoy.month - 1) // 3 + 1)
    except ValueError:
        anio, trimestre = hoy.year, 1
    trimestre = trimestre if trimestre in TRIMESTRES else 1
    error, r, nombre = None, None, ""
    if cif:
        empresa = resolver_empresa_cliente_por_cif(t, [cif])
        if not empresa or not empresa.get("carpeta_excel_id"):
            error = "No se encuentra ese cliente."
        else:
            nombre = empresa["nombre"]
            try:
                excels = _cargar_excels(t, empresa, anio, trimestre)
                facturas = juntar_facturas(excels, anio)
                r = {"m303": modelo_303(facturas, trimestre), "m130": modelo_130(facturas, trimestre), "persona": ES_PERSONA(cif),
                     "n_facturas": len(facturas), "n_excels": len(excels)}
                if not excels:
                    error = "No hay ningún Excel de ese cliente para esas fechas."
                    r = None
                else:
                    registrar_actividad(t, "Borrador de impuestos consultado", f"{nombre} · {trimestre}T {anio}")
            except Exception:
                log.exception("No se pudo calcular el borrador de impuestos")
                error = "No se ha podido calcular. Compruebe que el almacenamiento sigue conectado en Conexiones."
    return render_template_string(PLANTILLA, clientes=listar_clientes(t), cif=cif, anio=anio, anios=range(hoy.year, hoy.year - 4, -1),
                                  trimestre=trimestre, error=error, r=r, nombre=nombre,
                                  gestoria_nombre=obtener_estado_conexiones(t)["nombre"])
