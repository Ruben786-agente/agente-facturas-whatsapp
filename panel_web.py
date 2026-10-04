# -*- coding: utf-8 -*-
"""
Panel web para que cada gestoría vea el estado de sus facturas.
Login simple (email + contraseña, una cuenta por gestoría), sin chat ni IA
de por medio -- solo números y una tabla de lo pendiente.
"""

import os
from functools import wraps

from flask import Blueprint, request, redirect, session, render_template_string, url_for

from basededatos import verificar_login, obtener_resumen_panel

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
<title>Panel - Agente Facturas</title>
<style>
  body { font-family: Arial, sans-serif; background: #f4f5f7; margin: 0; padding: 2rem; }
  .resumen { display: flex; gap: 1rem; margin-bottom: 2rem; }
  .tarjeta { background: white; padding: 1.2rem 1.5rem; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); flex: 1; }
  .tarjeta .numero { font-size: 2rem; font-weight: bold; }
  .tarjeta.ok .numero { color: #27ae60; }
  .tarjeta.tickets .numero { color: #e67e22; }
  .tarjeta.revision .numero { color: #c0392b; }
  table { width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; }
  th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #eee; font-size: 0.92em; }
  th { background: #fafafa; }
  .etiqueta { padding: 2px 8px; border-radius: 10px; font-size: 0.8em; color: white; }
  .etiqueta.TICKETS { background: #e67e22; }
  .etiqueta.REVISION { background: #c0392b; }
  a.salir { float: right; color: #888; text-decoration: none; }
</style></head><body>
  <a class="salir" href="{{ url_for('panel.logout') }}">Cerrar sesión</a>
  <h1>Panel de facturas</h1>
  <div class="resumen">
    <div class="tarjeta ok"><div class="numero">{{ resumen.PROCESADA }}</div>Procesadas</div>
    <div class="tarjeta tickets"><div class="numero">{{ resumen.TICKETS }}</div>Tickets</div>
    <div class="tarjeta revision"><div class="numero">{{ resumen.REVISION }}</div>En revisión</div>
  </div>
  <h2>Pendientes de atención</h2>
  {% if pendientes %}
  <table>
    <tr><th>Empresa</th><th>Fecha</th><th>Proveedor</th><th>Total</th><th>Estado</th><th>Motivo</th></tr>
    {% for p in pendientes %}
    <tr>
      <td>{{ p.empresa }}</td><td>{{ p.fecha }}</td><td>{{ p.proveedor }}</td>
      <td>{{ "%.2f"|format(p.total) }} €</td>
      <td><span class="etiqueta {{ p.destino }}">{{ p.destino }}</span></td>
      <td>{{ p.motivo or "-" }}</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p>No hay nada pendiente ahora mismo 🎉</p>
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
    datos = obtener_resumen_panel(session["tenant_id"])
    return render_template_string(PLANTILLA_PANEL, resumen=datos["resumen"], pendientes=datos["pendientes"])



