# -*- coding: utf-8 -*-
"""
Panel web para que cada gestoría vea el estado de sus facturas.
Login simple (email + contraseña, una cuenta por gestoría), sin chat ni IA
de por medio -- solo números y una tabla de lo pendiente.
"""

import os
from functools import wraps

from flask import Blueprint, request, redirect, session, render_template_string, url_for, get_flashed_messages

from basededatos import (login_bloqueado, registrar_fallo_login, limpiar_fallos_login,
                         verificar_login, obtener_resumen_panel, obtener_estado_conexiones, obtener_avisos, marcar_avisos_vistos, TIPOS_AVISO_INFORMATIVO)
from estilo_web import acceso, eur, pagina

bp_panel = Blueprint("panel", __name__)
bp_panel.add_app_template_filter(eur, "eur")


def login_requerido(vista):
    @wraps(vista)
    def envoltorio(*args, **kwargs):
        if "tenant_id" not in session:
            return redirect(url_for("panel.login"))
        return vista(*args, **kwargs)
    return envoltorio


PLANTILLA_LOGIN = acceso("Entrar", """
  <h2>Entrar</h2>
  <p class="tenue">Acceda al panel de su gestoría.</p>
  <form method="post">
    <label for="email">Email</label>
    <input id="email" type="email" name="email" autocomplete="email" required autofocus>
    <label for="password">Contraseña</label>
    <input id="password" type="password" name="password" autocomplete="current-password" required>
    {% if error %}<p class="error-texto" role="alert">{{ error }}</p>{% endif %}
    <button class="btn principal grande" type="submit">Entrar</button>
  </form>
  <p class="pie">¿Aún no tiene cuenta? <a href="{{ url_for('alta.registro') }}">Pruébelo 14 días gratis</a></p>
""")

CSS_PANEL = """
<style>
  /* Plazo del modelo 303: lo primero que se ve */
  .cierre { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 40px; align-items: end; padding: 8px 0 8px; }
  .cierre h1 { font-size: clamp(32px, 4.4vw, 50px); line-height: 1.08; }
  .cierre .sub { color: var(--tinta-2); font-size: 17px; margin: 12px 0 0; }
  .progreso .texto { display: flex; justify-content: space-between; gap: 12px; font-size: 14px; color: var(--tinta-2); margin-bottom: 8px; }
  .progreso .texto strong { color: var(--tinta); font-weight: 600; }
  .pista { height: 6px; border-radius: 3px; background: var(--linea); overflow: hidden; }
  .pista > span { display: block; height: 100%; width: var(--w); background: var(--marca); border-radius: 3px; animation: llenar .9s cubic-bezier(.2,.7,.2,1) both; }
  .cierre.urgente .pista > span { background: var(--aviso); }
  .cierre.critico .pista > span { background: var(--error); }
  @keyframes llenar { from { width: 0; } }
  @media (prefers-reduced-motion: reduce) { .pista > span { animation: none; } }

  /* Cifras */
  .sin-envios { margin: 22px 0 0; color: var(--tinta-2); max-width: 80ch; }
  .sin-envios strong { color: var(--tinta); font-weight: 600; }
  .cifras { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 1px; margin-top: 36px; background: var(--linea);
            border: 1px solid var(--linea); border-radius: 10px; overflow: hidden; }
  .cifra { background: var(--superficie); padding: 20px 22px 18px; }
  .cifra .valor { font: 500 36px/1.05 var(--serif); letter-spacing: -.02em; font-variant-numeric: lining-nums; }
  .cifra .valor small { font-size: 18px; color: var(--tinta-3); margin-left: 3px; }
  .cifra .nombre { margin-top: 8px; color: var(--tinta-2); font-size: 14px; }
  .cifra .detalle { color: var(--tinta-3); font-size: 12.5px; margin-top: 2px; }
  .cifra.destacada .valor { color: var(--marca); }

  .vacio { background: var(--superficie); border: 1px dashed var(--linea-fuerte); border-radius: 10px; padding: 28px; color: var(--tinta-2); }
  .vacio strong { display: block; font: 500 20px/1.3 var(--serif); color: var(--tinta); margin-bottom: 4px; }

  @media (max-width: 960px) {
    .cierre { grid-template-columns: 1fr; gap: 22px; }
    .cifras { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .cifra:last-child { grid-column: 1 / -1; }
  }
</style>
"""

PLANTILLA_PANEL = pagina("Panel", """
<main class="pagina">
  {% for m in mensajes %}<p class="mensaje" role="status">{{ m }}</p>{% endfor %}

  {% if avisos_info %}
  <div class="alerta info">
    <p>{% if avisos_info|length == 1 %}Empresa nueva detectada: <strong>{{ avisos_info[0].mensaje }}</strong>. Se ha creado su carpeta;
      revise su primera factura por si el nombre o el CIF no son los esperados.
      {% else %}{{ avisos_info|length }} empresas nuevas detectadas: <strong>{{ avisos_info|map(attribute='mensaje')|join(', ') }}</strong>.
      Se han creado sus carpetas; revise la primera factura de cada una por si el nombre o el CIF no son los esperados.{% endif %}</p>
    <form method="post" action="{{ url_for('panel.avisos_vistos', grupo='info') }}"><button class="btn" type="submit">Entendido</button></form>
  </div>
  {% endif %}
  {% if avisos %}
  <div class="alerta error">
    {% for a in avisos %}<p>{{ a.mensaje }} <small>({{ a.creado_en.strftime("%d/%m/%Y %H:%M") }})</small></p>{% endfor %}
    <form method="post" action="{{ url_for('panel.avisos_vistos', grupo='alertas') }}"><button class="btn" type="submit">Entendido</button></form>
  </div>
  {% endif %}
  {% if aviso %}
  <div class="alerta"><p>{{ aviso }}</p><a class="btn" href="{{ url_for('alta.conexiones') }}">Resolver en Conexiones</a></div>
  {% endif %}

  {% if plazo %}
  {% set pendientes = plazo.con_revision %}
  <section class="cierre {% if plazo.dias <= 3 %}critico{% elif plazo.dias <= 7 %}urgente{% endif %}">
    <div>
      <h1>{% if plazo.dias == 0 %}El modelo 303 vence hoy{% elif plazo.dias == 1 %}Queda 1 día para el modelo 303{% else %}Quedan {{ plazo.dias }} días para el modelo 303{% endif %}</h1>
      <p class="sub">IVA del {{ plazo.trimestre }}T {{ plazo.anio }}, hasta el {{ plazo.plazo.strftime("%d/%m/%Y") }}.</p>
    </div>
    <div class="progreso">
      {% if plazo.clientes == 0 %}
        <div class="texto"><span>Todavía no hay facturas de este trimestre.</span></div>
        <div class="pista"><span style="--w:0%"></span></div>
      {% else %}
        <div class="texto"><span><strong>{{ plazo.clientes - pendientes }} de {{ plazo.clientes }}</strong> clientes sin nada pendiente</span></div>
        <div class="pista"><span style="--w:{{ ((plazo.clientes - pendientes) * 100 / plazo.clientes)|round|int }}%"></span></div>
      {% endif %}
    </div>
  </section>
  {% elif cierre %}
  {% set pendientes = cierre.con_revision %}
  <section class="cierre">
    <div>
      <h1>Cierre de {{ cierre.etiqueta }}</h1>
      <p class="sub">Para tener el Excel del mes listo para importar.</p>
    </div>
    <div class="progreso">
      {% if cierre.clientes == 0 %}
        <div class="texto"><span>Todavía no hay facturas de este mes.</span></div>
        <div class="pista"><span style="--w:0%"></span></div>
      {% else %}
        <div class="texto"><span><strong>{{ cierre.clientes - pendientes }} de {{ cierre.clientes }}</strong> clientes sin nada pendiente</span></div>
        <div class="pista"><span style="--w:{{ ((cierre.clientes - pendientes) * 100 / cierre.clientes)|round|int }}%"></span></div>
      {% endif %}
    </div>
  </section>
  {% else %}
  <section class="cierre"><div><h1>Panel de facturas</h1><p class="sub">Lo que el agente ha leído y lo que necesita que mires.</p></div></section>
  {% endif %}

  {% set foco = plazo or cierre %}
  {% if foco and foco.sin_facturas %}
  <p class="sin-envios"><strong>Sin facturas de {% if plazo %}{{ plazo.trimestre }}T {{ plazo.anio }}{% else %}{{ cierre.etiqueta }}{% endif %}:</strong>
    {% set lista = foco.sin_facturas[:6]|join(", ") %}{{ lista }}{% if foco.sin_facturas|length > 6 %} y {{ foco.sin_facturas|length - 6 }} más{% endif %}{% if not lista.endswith(".") or foco.sin_facturas|length > 6 %}.{% endif %}
    Todavía no han enviado ninguna factura de {% if plazo %}este trimestre{% else %}este mes{% endif %}.</p>
  {% endif %}

  <section class="cifras" aria-label="Resumen">
    <div class="cifra"><div class="valor">{{ resumen.PROCESADA }}</div><div class="nombre">Procesadas</div><div class="detalle">en el Excel de su cliente</div></div>
    <div class="cifra"><div class="valor">{{ resumen.TICKETS }}</div><div class="nombre">Tickets</div><div class="detalle">archivados aparte</div></div>
    <div class="cifra"><div class="valor">{{ resumen.REVISION }}</div><div class="nombre">En revisión</div><div class="detalle">esperan su visto bueno</div></div>
    <div class="cifra"><div class="valor">{{ resumen.SIN_IDENTIFICAR }}</div><div class="nombre">Sin identificar</div><div class="detalle">sin empresa asignada</div></div>
    <div class="cifra destacada" title="Facturas leídas y archivadas este mes × {{ ahorro.minutos_por_doc }} min cada una">
      <div class="valor">{% if ahorro.horas %}{{ ahorro.horas }}<small>h</small> {% endif %}{{ ahorro.minutos }}<small>min</small></div>
      <div class="nombre">Tiempo ahorrado este mes</div><div class="detalle">{{ ahorro.documentos }} facturas × {{ ahorro.minutos_por_doc }} min</div>
    </div>
  </section>

  <section class="seccion">
    <div class="seccion-cab"><h2>Qué tiene que revisar</h2>{% if atencion %}<span class="cuenta">{{ atencion|length }}</span>{% endif %}</div>
    {% if atencion %}
    <div class="tabla"><table class="apilable">
      <tr><th>Documento</th><th>Fecha</th><th class="num">Total</th><th>Estado y motivo</th><th>Acciones</th></tr>
      {% for p in atencion %}
      <tr>
        <td data-label="Documento">{{ p.proveedor }}<span class="sec">{{ p.empresa }}</span></td>
        <td data-label="Fecha">{{ p.fecha }}</td>
        <td data-label="Total" class="num">{% if p.total is not none %}{{ p.total|eur }}{% else %}-{% endif %}</td>
        <td data-label="Estado"><span class="estado {{ p.destino }}">{{ {"REVISION": "En revisión", "SIN_IDENTIFICAR": "Sin identificar"}.get(p.destino, p.destino) }}</span>
            <span class="sec">{{ p.motivo or "" }}</span></td>
        <td data-label="Acciones"><div class="acciones">
          {% if p.destino == "REVISION" %}
            {% if p.corregible %}<a class="btn principal" href="{{ url_for('revision.corregir', factura_id=p.id) }}">Corregir y añadir al Excel</a>{% endif %}
            <a class="btn" href="{{ url_for('revision.ver_revision', factura_id=p.id) }}" target="_blank" rel="noopener">Ver factura</a>
            <a class="btn discreto" href="{{ url_for('revision.abrir_revision', factura_id=p.id) }}" target="_blank" rel="noopener">Abrir carpeta</a>
            <form class="en-linea aparte" method="post" action="{{ url_for('revision.revisada', factura_id=p.id) }}"><button class="btn discreto" type="submit" onclick="return confirm('¿Marcar como gestionada? Desaparecerá de esta lista y no se añadirá al Excel.');">Marcar como gestionada</button></form>
          {% else %}
            <a class="btn" href="{{ url_for('revision.abrir_sin_identificar') }}" target="_blank" rel="noopener">Abrir carpeta</a>
            <form class="en-linea aparte" method="post" action="{{ url_for('revision.sin_identificar_revisado', documento_id=p.id) }}"><button class="btn discreto" type="submit" onclick="return confirm('¿Marcar como gestionado? Desaparecerá de esta lista.');">Marcar como gestionado</button></form>
          {% endif %}
        </div></td>
      </tr>
      {% endfor %}
    </table></div>
    <p class="nota">«Marcar como gestionada» quita la línea de esta lista, sin añadirla al Excel, cuando ya la ha resuelto por su cuenta. «Corregir y añadir al Excel» le deja arreglar los datos y la anota en el Excel del {{ 'mes' if periodicidad == 'mensual' else 'trimestre' }}.</p>
    {% else %}
    <div class="vacio"><strong>No hay nada pendiente.</strong>Si una factura necesita su revisión, aparecerá aquí.</div>
    {% endif %}
  </section>

  <section class="seccion">
    <div class="seccion-cab"><h2>{% if periodicidad == "mensual" %}Excel del mes por cliente{% else %}Excel del trimestre por cliente{% endif %}</h2>
      {% if periodos %}
      <form method="get"><label for="t" style="display:inline;margin:0 8px 0 0;">{% if periodicidad == "mensual" %}Mes{% else %}Trimestre{% endif %}</label>
        <select id="t" name="t" onchange="this.form.submit()">
          {% if periodicidad != "mensual" %}<option value="">Todos</option>{% endif %}
          {% for clave, etiqueta in periodos %}<option value="{{ clave }}" {% if periodo_activo == clave %}selected{% endif %}>{{ etiqueta }}</option>{% endfor %}
        </select>
      </form>
      {% endif %}
    </div>
    {% if clientes %}
    <div class="tabla"><table class="apilable">
      <tr><th>Cliente</th>{% if periodicidad != "mensual" %}<th>Trimestre</th>{% endif %}<th class="num">Facturas</th><th class="num">Total</th><th class="num">Tickets</th><th class="num">En revisión</th><th>Estado</th><th>Excel</th></tr>
      {% for c in clientes %}
      <tr>
        <td data-label="Cliente">{{ c.empresa }}<span class="sec">{{ c.cif }}</span></td>
        {% if periodicidad != "mensual" %}<td data-label="Trimestre">{{ c.etiqueta }}</td>{% endif %}
        <td data-label="Facturas" class="num">{{ c.facturas }}</td>
        <td data-label="Total" class="num">{{ c.total|eur }}</td>
        <td data-label="Tickets" class="num">{{ c.tickets }}</td>
        <td data-label="En revisión" class="num">{{ c.revision }}</td>
        <td data-label="Estado"><span class="estado {{ c.estado }}">{{ {"LISTO": "Listo para importar", "REVISAR": "Tiene pendientes", "SIN_FACTURAS": "Sin facturas"}[c.estado] }}</span></td>
        <td data-label="Excel">{% if c.facturas %}<div class="acciones"><a class="btn principal" href="{{ url_for('revision.descargar_excel', cif=c.cif, periodo=c.periodo) }}">Descargar Excel</a>
          <a class="btn discreto" href="{{ url_for('revision.abrir_excel', cif=c.cif, periodo=c.periodo) }}" target="_blank" rel="noopener">Abrir en su carpeta</a></div>{% else %}<span class="sec">-</span>{% endif %}</td>
      </tr>
      {% endfor %}
    </table></div>
    {% else %}
    <div class="vacio"><strong>Todavía no hay facturas procesadas.</strong>Cuando lleguen facturas a su correo, o las <a href="{{ url_for('subida.subir') }}">suba usted directamente</a>, verá aquí cada cliente con su Excel.</div>
    {% endif %}
  </section>
</main>
""", activa="panel", extra_head=CSS_PANEL + '<meta http-equiv="refresh" content="30">')


def _ip_cliente():
    return (request.headers.get("X-Forwarded-For", "") or request.remote_addr or "").split(",")[0].strip()


@bp_panel.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        clave_cuenta, clave_ip = f"cuenta:{email}", f"ip:{_ip_cliente()}"
        espera = max(login_bloqueado(clave_cuenta), login_bloqueado(clave_ip))
        if espera:
            minutos = max(1, -(-espera // 60))
            return render_template_string(PLANTILLA_LOGIN, error=f"Demasiados intentos. Espere {minutos} minutos y vuelva a probar.")
        tenant_id = verificar_login(email, request.form.get("password", ""))
        if tenant_id:
            limpiar_fallos_login(clave_cuenta)
            session.clear()  # sesión nueva al entrar
            session["tenant_id"] = tenant_id
            session.permanent = True
            return redirect(url_for("panel.panel"))
        registrar_fallo_login(clave_cuenta, maximo=8)
        registrar_fallo_login(clave_ip, maximo=40)
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
    aviso = e["correo_error"] or (None if e["almacenamiento"] else "Falta conectar OneDrive o Google Drive.") \
        or (None if e["correo"] else "Falta conectar su correo (Gmail u Outlook).")
    todos_avisos = obtener_avisos(session["tenant_id"])
    return render_template_string(
        PLANTILLA_PANEL, resumen=datos["resumen"], atencion=datos["atencion"], clientes=datos["clientes"],
        periodos=datos["periodos"], periodo_activo=datos["periodo_activo"], periodicidad=datos["periodicidad"],
        plazo=datos["plazo"], cierre=datos["cierre"], ahorro=datos["ahorro"], filtro=filtro, aviso=aviso,
        mensajes=get_flashed_messages(), gestoria_nombre=e["nombre"],
        avisos=[a for a in todos_avisos if a["tipo"] not in TIPOS_AVISO_INFORMATIVO],
        avisos_info=[a for a in todos_avisos if a["tipo"] in TIPOS_AVISO_INFORMATIVO])


@bp_panel.route("/avisos/vistos", methods=["POST"])
@login_requerido
def avisos_vistos():
    marcar_avisos_vistos(session["tenant_id"], grupo=request.args.get("grupo"))
    return redirect(url_for("panel.panel"))
