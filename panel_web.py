# -*- coding: utf-8 -*-
"""
Panel web para que cada gestoría vea el estado de sus facturas.
Login simple (email + contraseña, una cuenta por gestoría), sin chat ni IA
de por medio -- solo números y una tabla de lo pendiente.
"""

import os
from functools import wraps

from flask import Blueprint, request, redirect, session, render_template_string, url_for, get_flashed_messages

from basededatos import verificar_login, obtener_resumen_panel, obtener_estado_conexiones, obtener_avisos, marcar_avisos_vistos

bp_panel = Blueprint("panel", __name__)


def login_requerido(vista):
    @wraps(vista)
    def envoltorio(*args, **kwargs):
        if "tenant_id" not in session:
            return redirect(url_for("panel.login"))
        return vista(*args, **kwargs)
    return envoltorio


PLANTILLA_LOGIN = """
<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Acceso - Agente Facturas</title>
<style>
  body { font-family: Arial, sans-serif; background: #f4f5f7; display: flex;
         justify-content: center; align-items: center; height: 100vh; margin: 0; }
  .caja { background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.1); width: 300px; }
  input { width: 100%; padding: 8px; margin: 6px 0 14px 0; box-sizing: border-box; }
  button { width: 100%; padding: 10px; background: #2d6cdf; color: white; border: none; border-radius: 4px; cursor: pointer; }
  .error { color: #c0392b; font-size: 0.9em; }
</style></head><body>
  <div class="caja">
    <h2>Acceso</h2>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <form method="post">
      <label>Email</label><input type="email" name="email" required>
      <label>Contraseña</label><input type="password" name="password" required>
      <button type="submit">Entrar</button>
    </form>
  </div>
</body></html>
"""

PLANTILLA_PANEL = """
<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel - Agente Facturas</title>
<meta http-equiv="refresh" content="30">
<style>
  body { font-family: Arial, sans-serif; background: #f4f5f7; margin: 0; padding: 2rem; color: #222; }
  h2 { margin: 2rem 0 .6rem 0; font-size: 1.15rem; }
  .resumen { display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .tarjeta { background: white; padding: 1rem 1.4rem; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); flex: 1; min-width: 120px; }
  .tarjeta .numero { font-size: 1.8rem; font-weight: bold; }
  .tarjeta.ok .numero { color: #27ae60; }
  .tarjeta.tickets .numero { color: #e67e22; }
  .tarjeta.revision .numero { color: #c0392b; }
  .tarjeta.sinid .numero { color: #8e44ad; }
  .tabla { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; }
  th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #eee; font-size: 0.92em; }
  th { background: #fafafa; }
  td.num, th.num { text-align: right; white-space: nowrap; }
  .etiqueta { padding: 2px 9px; border-radius: 10px; font-size: 0.8em; color: white; white-space: nowrap; }
  .etiqueta.REVISION, .etiqueta.REVISAR { background: #c0392b; }
  .etiqueta.SIN_IDENTIFICAR { background: #8e44ad; }
  .etiqueta.LISTO { background: #27ae60; }
  .etiqueta.SIN_FACTURAS { background: #999; }
  .plazo { padding: 12px 16px; border-radius: 8px; margin-bottom: 1rem; background: #eaf2ff; }
  .plazo.urgente { background: #fff1e0; }
  .plazo.critico { background: #fdecea; }
  a.salir { float: right; color: #888; text-decoration: none; }
  .btn { display: inline-block; padding: 4px 10px; border-radius: 4px; border: 1px solid #ccd; background: white;
         color: #2d6cdf; font-size: .82em; cursor: pointer; text-decoration: none; white-space: nowrap; margin: 2px 2px 2px 0; }
  .btn.principal { background: #2d6cdf; border-color: #2d6cdf; color: white; }
  .btn:hover { opacity: .85; }
  form.en-linea { display: inline; }
  .ahorro .numero { color: #2d6cdf; }
  .mensaje { background: #e8f6ee; padding: 10px 14px; border-radius: 4px; margin-bottom: 1rem; }
  .filtro { margin-bottom: .6rem; font-size: .9em; }
</style></head><body>
  <a class="salir" href="{{ url_for('panel.logout') }}">Cerrar sesión</a>
  <h1>Panel de facturas</h1>
  {% if avisos %}
  <div style="background:#fdecea;padding:10px 14px;border-radius:4px;margin-bottom:1rem;">
    {% for a in avisos %}<p style="margin:6px 0;">⚠ {{ a.mensaje }} <small style="color:#888;">({{ a.creado_en.strftime("%d/%m/%Y %H:%M") }})</small></p>{% endfor %}
    <form method="post" action="{{ url_for('panel.avisos_vistos') }}"><button type="submit">Entendido</button></form>
  </div>
  {% endif %}
  {% if aviso %}<p style="background:#fff4e5;padding:10px;border-radius:4px;">⚠ {{ aviso }} <a href="{{ url_for('alta.conexiones') }}">Resolver</a></p>{% endif %}
  {% for m in mensajes %}<p class="mensaje">{{ m }}</p>{% endfor %}
  <p><a href="{{ url_for('alta.conexiones') }}">Conexiones y suscripción</a></p>

  {% if plazo %}
  <div class="plazo {% if plazo.dias <= 3 %}critico{% elif plazo.dias <= 7 %}urgente{% endif %}">
    <strong>IVA {{ plazo.trimestre }}T {{ plazo.anio }} (modelo 303):</strong>
    {% if plazo.dias == 0 %}el plazo termina hoy{% elif plazo.dias == 1 %}queda 1 día{% else %}quedan {{ plazo.dias }} días{% endif %}
    (hasta el {{ plazo.plazo.strftime("%d/%m/%Y") }}).
    {% if plazo.clientes == 0 %}Todavía no hay facturas de ese trimestre.
    {% elif plazo.con_revision == 0 %}Los {{ plazo.clientes }} clientes con facturas están sin nada pendiente de revisar.
    {% else %}{{ plazo.con_revision }} de {{ plazo.clientes }} clientes tienen facturas pendientes de revisar.{% endif %}
  </div>
  {% endif %}

  <div class="resumen">
    <div class="tarjeta ok"><div class="numero">{{ resumen.PROCESADA }}</div>Procesadas</div>
    <div class="tarjeta tickets"><div class="numero">{{ resumen.TICKETS }}</div>Tickets</div>
    <div class="tarjeta revision"><div class="numero">{{ resumen.REVISION }}</div>En revisión</div>
    <div class="tarjeta sinid"><div class="numero">{{ resumen.SIN_IDENTIFICAR }}</div>Sin identificar</div>
    <div class="tarjeta ahorro" title="Facturas leídas y archivadas este mes × {{ ahorro.minutos_por_doc }} min cada una">
      <div class="numero">{% if ahorro.horas %}{{ ahorro.horas }} h {% endif %}{{ ahorro.minutos }} min</div>
      Tiempo ahorrado este mes<br><small style="color:#888;">{{ ahorro.documentos }} facturas × {{ ahorro.minutos_por_doc }} min</small>
    </div>
  </div>

  <h2>Qué tienes que revisar</h2>
  {% if atencion %}
  <div class="tabla"><table>
    <tr><th>Empresa</th><th>Fecha</th><th>Proveedor / archivo</th><th class="num">Total</th><th>Estado</th><th>Motivo</th><th>Acciones</th></tr>
    {% for p in atencion %}
    <tr>
      <td>{{ p.empresa }}</td><td>{{ p.fecha }}</td><td>{{ p.proveedor }}</td>
      <td class="num">{% if p.total is not none %}{{ "%.2f"|format(p.total) }} €{% else %}-{% endif %}</td>
      <td><span class="etiqueta {{ p.destino }}">{{ p.destino.replace("_", " ") }}</span></td>
      <td>{{ p.motivo or "-" }}</td>
      <td>
        {% if p.destino == "REVISION" %}
          <a class="btn" href="{{ url_for('revision.abrir_revision', factura_id=p.id) }}" target="_blank">Abrir en OneDrive</a>
          {% if p.corregible %}<a class="btn principal" href="{{ url_for('revision.corregir', factura_id=p.id) }}">Corregir y añadir al Excel</a>{% endif %}
          <form class="en-linea" method="post" action="{{ url_for('revision.revisada', factura_id=p.id) }}"><button class="btn" type="submit">Marcar como revisada</button></form>
        {% else %}
          <a class="btn" href="{{ url_for('revision.abrir_sin_identificar') }}" target="_blank">Abrir en OneDrive</a>
          <form class="en-linea" method="post" action="{{ url_for('revision.sin_identificar_revisado', documento_id=p.id) }}"><button class="btn" type="submit">Marcar como revisado</button></form>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </table></div>
  <p style="color:#888;font-size:.85em;">«Marcar como revisada» quita la línea de esta lista cuando ya la has gestionado por tu cuenta. «Corregir y añadir al Excel» te deja arreglar los datos y la anota en el Excel del trimestre.</p>
  {% else %}
  <p>No hay nada pendiente ahora mismo 🎉</p>
  {% endif %}

  <h2>Clientes por trimestre</h2>
  {% if trimestres %}
  <form class="filtro" method="get">
    Trimestre:
    <select name="t" onchange="this.form.submit()">
      <option value="">Todos</option>
      {% for a, t in trimestres %}<option value="{{ a }}-{{ t }}" {% if filtro == (a ~ '-' ~ t) %}selected{% endif %}>{{ t }}T {{ a }}</option>{% endfor %}
    </select>
  </form>
  {% endif %}
  {% if clientes %}
  <div class="tabla"><table>
    <tr><th>Cliente</th><th>Trimestre</th><th class="num">Facturas</th><th class="num">Total</th><th class="num">Tickets</th><th class="num">En revisión</th><th class="num">Revisadas a mano</th><th>Estado</th></tr>
    {% for c in clientes %}
    <tr>
      <td>{{ c.empresa }}<br><small style="color:#888;">{{ c.cif }}</small></td>
      <td>{{ c.trimestre }}T {{ c.anio }}</td>
      <td class="num">{{ c.facturas }}</td>
      <td class="num">{{ "%.2f"|format(c.total) }} €</td>
      <td class="num">{{ c.tickets }}</td>
      <td class="num">{{ c.revision }}</td>
      <td class="num">{{ c.revisadas }}</td>
      <td><span class="etiqueta {{ c.estado }}">{{ {"LISTO": "Listo", "REVISAR": "Revisar", "SIN_FACTURAS": "Sin facturas"}[c.estado] }}</span></td>
    </tr>
    {% endfor %}
  </table></div>
  {% else %}
  <p>Todavía no hay facturas procesadas.</p>
  {% endif %}
</body></html>
"""


@bp_panel.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        tenant_id = verificar_login(request.form["email"], request.form["password"])
        if tenant_id:
            session["tenant_id"] = tenant_id
            return redirect(url_for("panel.panel"))
        return render_template_string(PLANTILLA_LOGIN, error="Email o contraseña incorrectos")
    return render_template_string(PLANTILLA_LOGIN, error=None)


@bp_panel.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("panel.login"))


@bp_panel.route("/panel")
@login_requerido
def panel():
    filtro = request.args.get("t", "").strip()
    datos = obtener_resumen_panel(session["tenant_id"], trimestre=filtro or None)
    e = obtener_estado_conexiones(session["tenant_id"])
    aviso = e["gmail_error"] or (None if e["onedrive"] else "Falta conectar OneDrive.")
    return render_template_string(
        PLANTILLA_PANEL, resumen=datos["resumen"], atencion=datos["atencion"], clientes=datos["clientes"],
        trimestres=datos["trimestres"], plazo=datos["plazo"], ahorro=datos["ahorro"], filtro=filtro, aviso=aviso,
        mensajes=get_flashed_messages(),
        avisos=obtener_avisos(session["tenant_id"]))


@bp_panel.route("/avisos/vistos", methods=["POST"])
@login_requerido
def avisos_vistos():
    marcar_avisos_vistos(session["tenant_id"])
    return redirect(url_for("panel.panel"))
