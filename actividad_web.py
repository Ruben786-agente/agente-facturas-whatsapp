"""Página «Actividad»: qué se ha hecho en la cuenta en los últimos 90 días."""
from flask import Blueprint, session, render_template_string

from basededatos import obtener_actividad, obtener_estado_conexiones
from estilo_web import pagina
from panel_web import login_requerido

bp_actividad = Blueprint("actividad", __name__)

CUERPO = """
<main class="contenedor"><h1>Actividad</h1>
<p class="suave">Lo que se ha hecho en su cuenta en los últimos 90 días (solo acciones hechas desde la web).</p>
{% if filas %}
<table class="tabla"><thead><tr><th>Cuándo</th><th>Qué</th><th>Detalle</th></tr></thead><tbody>
{% for f in filas %}<tr><td>{{ f.cuando.strftime('%d/%m/%Y %H:%M') }}</td><td>{{ f.accion }}</td><td>{{ f.detalle }}</td></tr>{% endfor %}
</tbody></table>
{% else %}<p>Todavía no hay actividad registrada.</p>{% endif %}
</main>
"""


@bp_actividad.route("/actividad")
@login_requerido
def lista():
    t = session["tenant_id"]
    return render_template_string(pagina("Actividad", CUERPO, activa="actividad"), filas=obtener_actividad(t),
                                  gestoria_nombre=obtener_estado_conexiones(t)["nombre"])
