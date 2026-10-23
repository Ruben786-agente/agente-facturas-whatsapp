# -*- coding: utf-8 -*-
"""
Aspecto común de todas las pantallas (panel, conexiones, registro, corrección).

Tipografía: Newsreader (serif, para títulos y cifras) + Hanken Grotesk (texto e interfaz).
Colores: papel gris azulado, tinta casi negra y un verde petróleo como único color de marca;
el rojo, el ámbar, el verde y el violeta solo aparecen para indicar estados.
"""

FUENTES = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600'
    '&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap" rel="stylesheet">'
)

CSS = """
<style>
  :root {
    --papel: #F4F6F7;  --superficie: #FFFFFF;  --tinta: #17212B;  --tinta-2: #4F5B67;  --tinta-3: #85909B;
    --linea: #E1E6EA;  --linea-fuerte: #CBD3D9;
    --marca: #1E4D5C;  --marca-osc: #153A46;  --marca-clara: #E7F0F2;
    --ok: #2C7A58;  --aviso: #B07514;  --error: #B0413E;  --violeta: #6A5190;
    --serif: "Newsreader", Georgia, "Times New Roman", serif;
    --sans: "Hanken Grotesk", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body { margin: 0; background: var(--papel); color: var(--tinta); font: 400 15px/1.55 var(--sans); }
  a { color: var(--marca); text-underline-offset: 3px; }
  a:hover { color: var(--marca-osc); }
  h1, h2, h3 { font-family: var(--serif); font-weight: 500; letter-spacing: -.01em; margin: 0; color: var(--tinta); }
  h2 { font-size: 24px; line-height: 1.2; }
  p { margin: 0 0 .8em; }
  small, .tenue { color: var(--tinta-3); }
  :focus-visible { outline: 2px solid var(--marca); outline-offset: 2px; border-radius: 4px; }

  /* Barra superior */
  .barra { background: var(--superficie); border-bottom: 1px solid var(--linea); }
  .barra-in { max-width: 1120px; margin: 0 auto; padding: 0 24px; height: 62px; display: flex; align-items: center; gap: 28px; }
  .marca { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--tinta); font: 600 21px/1 var(--serif); letter-spacing: -.01em; }
  .marca:hover { color: var(--tinta); }
  .barra nav { display: flex; gap: 4px; margin-left: 8px; }
  .barra nav a { text-decoration: none; color: var(--tinta-2); padding: 7px 12px; border-radius: 6px; font-weight: 500; }
  .barra nav a:hover { background: var(--papel); color: var(--tinta); }
  .barra nav a.activa { color: var(--marca); background: var(--marca-clara); }
  .barra .usuario { margin-left: auto; display: flex; align-items: center; gap: 16px; color: var(--tinta-2); font-size: 14px; }
  .barra .usuario a { color: var(--tinta-2); }

  /* Estructura */
  .pagina { max-width: 1120px; margin: 0 auto; padding: 36px 24px 72px; }
  .pagina.estrecha { max-width: 640px; }
  .seccion { margin-top: 48px; }
  .seccion-cab { display: flex; align-items: baseline; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
  .seccion-cab .cuenta { color: var(--tinta-3); font-family: var(--serif); font-size: 20px; }
  .seccion-cab form { margin-left: auto; }
  .nota { color: var(--tinta-3); font-size: 13.5px; max-width: 70ch; margin-top: 12px; }

  /* Botones */
  .btn, button.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 7px 13px; border-radius: 7px;
    border: 1px solid var(--linea-fuerte); background: var(--superficie); color: var(--tinta); font: 500 13.5px/1.2 var(--sans);
    cursor: pointer; text-decoration: none; white-space: nowrap; transition: background .15s, border-color .15s; }
  .btn:hover { background: var(--papel); border-color: var(--tinta-3); color: var(--tinta); }
  .btn.principal { background: var(--marca); border-color: var(--marca); color: #fff; }
  .btn.principal:hover { background: var(--marca-osc); border-color: var(--marca-osc); color: #fff; }
  .btn.grande { padding: 11px 20px; font-size: 15px; }
  .btn.discreto { border-color: transparent; background: transparent; color: var(--tinta-2); }
  .btn.discreto:hover { background: var(--papel); }
  form.en-linea { display: inline; }

  /* Mensajes */
  .mensaje, .alerta { padding: 12px 16px; border-radius: 8px; margin-bottom: 14px; border: 1px solid var(--linea); border-left-width: 4px; background: var(--superficie); }
  .mensaje { border-left-color: var(--ok); }
  .alerta { border-left-color: var(--aviso); }
  .alerta.error { border-left-color: var(--error); }
  .alerta.info { border-left-color: var(--marca); }
  .alerta p { margin: 0 0 6px; }
  .alerta p:last-of-type { margin-bottom: 0; }
  .alerta .btn { margin-top: 10px; }

  /* Tablas */
  .tabla { overflow-x: auto; background: var(--superficie); border: 1px solid var(--linea); border-radius: 10px; }
  table { width: 100%; border-collapse: collapse; min-width: 760px; }
  th { text-align: left; font-weight: 500; font-size: 13px; color: var(--tinta-3); padding: 12px 16px; border-bottom: 1px solid var(--linea); white-space: nowrap; }
  td { padding: 14px 16px; border-bottom: 1px solid var(--linea); vertical-align: top; }
  tr:last-child td { border-bottom: 0; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  td .sec { display: block; color: var(--tinta-3); font-size: 13px; }
  .acciones { display: flex; gap: 6px; flex-wrap: wrap; }

  /* Estados: punto de color + palabra */
  .estado { display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; font-weight: 500; }
  .estado::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--tinta-3); }
  .estado.REVISION::before, .estado.ERROR::before { background: var(--error); }
  .estado.SIN_IDENTIFICAR::before { background: var(--violeta); }
  .estado.LISTO::before { background: var(--ok); }
  .estado.REVISAR::before { background: var(--aviso); }

  /* Formularios */
  label { display: block; font-size: 13.5px; font-weight: 500; color: var(--tinta-2); margin: 16px 0 6px; }
  input, select { width: 100%; padding: 10px 12px; border: 1px solid var(--linea-fuerte); border-radius: 7px; background: #fff;
    font: 400 15px/1.3 var(--sans); color: var(--tinta); }
  input:focus, select:focus { outline: 2px solid var(--marca); outline-offset: 0; border-color: var(--marca); }
  select { width: auto; padding: 7px 30px 7px 10px; }

  @media (max-width: 720px) {
    .barra-in { padding: 10px 16px 6px; gap: 6px 12px; height: auto; flex-wrap: wrap; }
    .barra nav { order: 3; flex-basis: 100%; margin: 0 -12px; overflow-x: auto; }
    .barra nav a { white-space: nowrap; }
    .barra .usuario { margin-left: auto; }
    .barra .usuario .nombre { display: none; }
    .cifra { padding: 16px 16px 14px; }
    /* Tablas en el móvil: cada fila pasa a ser una ficha con sus etiquetas */
    table.apilable { min-width: 0; }
    table.apilable tr:first-child { display: none; }
    table.apilable, table.apilable tbody, table.apilable tr, table.apilable td { display: block; width: 100%; }
    table.apilable tr { padding: 14px 16px; border-bottom: 1px solid var(--linea); }
    table.apilable tr:last-child { border-bottom: 0; }
    table.apilable td { display: flex; justify-content: space-between; gap: 16px; padding: 3px 0; border: 0; text-align: right; }
    table.apilable td::before { content: attr(data-label); color: var(--tinta-3); font-size: 13px; text-align: left; flex: none; }
    table.apilable td:first-child { display: block; text-align: left; font-weight: 500; font-size: 16px; padding-bottom: 6px; }
    table.apilable td:first-child::before { content: none; }
    table.apilable td .sec { text-align: left; }
    table.apilable td[data-label="Acciones"] { display: block; padding-top: 10px; }
    table.apilable td[data-label="Acciones"]::before { content: none; }
    table.apilable td[data-label="Estado"] { flex-wrap: wrap; justify-content: flex-end; }
    .pagina { padding: 24px 16px 56px; }
  }
</style>
"""

LOGO = (
    '<svg width="30" height="30" viewBox="0 0 120 120" aria-hidden="true">'
    '<rect width="120" height="120" rx="26" fill="#1E4D5C"/><path d="M30 22h34l16 16v58a4 4 0 0 1-4 4H30a4 4 0 0 1-4-4V26a4 4 0 0 1 4-4z" fill="#fff"/><path d="M64 22v12a4 4 0 0 0 4 4h12z" fill="#9FD0C0"/><path d="M37 62h30M37 74h20" stroke="#1E4D5C" stroke-width="6" stroke-linecap="round" fill="none" opacity=".35"/><path d="M37 88l6 6 11-13" stroke="#1E4D5C" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" fill="none"/><path transform="translate(88 38) scale(22)" d="M0,-1 C0.1,-0.25 0.25,-0.1 1,0 C0.25,0.1 0.1,0.25 0,1 C-0.1,0.25 -0.25,0.1 -1,0 C-0.25,-0.1 -0.1,-0.25 0,-1Z" fill="#F5B73B"/><path transform="translate(100 66) scale(7)" d="M0,-1 C0.1,-0.25 0.25,-0.1 1,0 C0.25,0.1 0.1,0.25 0,1 C-0.1,0.25 -0.25,0.1 -1,0 C-0.25,-0.1 -0.1,-0.25 0,-1Z" fill="#F5B73B"/></svg>'
)

FAVICON = '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,' + __import__("urllib.parse").parse.quote('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><rect width="120" height="120" rx="26" fill="#1E4D5C"/><path d="M30 22h34l16 16v58a4 4 0 0 1-4 4H30a4 4 0 0 1-4-4V26a4 4 0 0 1 4-4z" fill="#fff"/><path d="M64 22v12a4 4 0 0 0 4 4h12z" fill="#9FD0C0"/><path d="M37 62h30M37 74h20" stroke="#1E4D5C" stroke-width="6" stroke-linecap="round" fill="none" opacity=".35"/><path d="M37 88l6 6 11-13" stroke="#1E4D5C" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" fill="none"/><path transform="translate(88 38) scale(22)" d="M0,-1 C0.1,-0.25 0.25,-0.1 1,0 C0.25,0.1 0.1,0.25 0,1 C-0.1,0.25 -0.25,0.1 -1,0 C-0.25,-0.1 -0.1,-0.25 0,-1Z" fill="#F5B73B"/><path transform="translate(100 66) scale(7)" d="M0,-1 C0.1,-0.25 0.25,-0.1 1,0 C0.25,0.1 0.1,0.25 0,1 C-0.1,0.25 -0.25,0.1 -1,0 C-0.25,-0.1 -0.1,-0.25 0,-1Z" fill="#F5B73B"/></svg>') + '">'

BARRA = (
    '<header class="barra"><div class="barra-in">'
    '<a class="marca" href="{{ url_for(\'panel.panel\') }}">' + LOGO + 'Agente Facturas</a>'
    '<nav aria-label="Principal">'
    '<a href="{{ url_for(\'panel.panel\') }}" {% if activa == \'panel\' %}class="activa" aria-current="page"{% endif %}>Panel</a>'
    '<a href="{{ url_for(\'subida.subir\') }}" {% if activa == \'subir\' %}class="activa" aria-current="page"{% endif %}>Subir facturas</a>'
    '<a href="{{ url_for(\'alta.conexiones\') }}" {% if activa == \'conexiones\' %}class="activa" aria-current="page"{% endif %}>Conexiones y suscripción</a>'
    '</nav>'
    '<div class="usuario"><span class="nombre">{{ gestoria_nombre or "" }}</span>'
    '<a href="{{ url_for(\'panel.logout\') }}">Cerrar sesión</a></div>'
    '</div></header>'
)


def pagina(titulo, cuerpo, barra=True, activa="", extra_head=""):
    """Plantilla Jinja completa: cabecera, barra superior (opcional) y el cuerpo que se le pase."""
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{titulo} - Agente Facturas</title>{FUENTES}{FAVICON}{CSS}{extra_head}</head><body>'
        + ("{% set activa = '" + activa + "' %}" + BARRA if barra else "")
        + cuerpo + "</body></html>"
    )


# Pantallas de acceso (entrar y crear cuenta): texto de presentación a la izquierda, formulario a la derecha.
CSS_ACCESO = """
<style>
  .acceso { min-height: 100vh; display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); }
  .acceso-marca { background: var(--marca); color: #fff; padding: 56px 64px; display: flex; flex-direction: column; justify-content: space-between; gap: 48px; }
  .acceso-marca .marca { color: #fff; }
  .acceso-marca h1 { color: #fff; font-size: clamp(30px, 3.4vw, 46px); line-height: 1.12; max-width: 17em; }
  .acceso-marca p { color: #CFE0E4; font-size: 17px; max-width: 34em; margin-top: 18px; }
  .acceso-marca ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; color: #CFE0E4; }
  .acceso-marca li { display: flex; align-items: center; gap: 12px; }
  .acceso-marca li::before { content: ""; flex: none; width: 20px; height: 20px; border-radius: 50%; background: #3FA57C url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'%3E%3Cpath d='M5.5 10.5l3 3 6-6.5' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / 20px 20px no-repeat; }
  .acceso-form { display: flex; align-items: center; justify-content: center; padding: 48px 32px; }
  .acceso-form .interior { width: 100%; max-width: 380px; }
  .acceso-form h2 { font-size: 30px; margin-bottom: 6px; }
  .acceso-form button.btn { width: 100%; margin-top: 22px; }
  .acceso-form .pie { margin-top: 22px; color: var(--tinta-2); font-size: 14px; }
  .error-texto { color: var(--error); margin: 14px 0 0; font-size: 14px; }
  @media (max-width: 860px) {
    .acceso { grid-template-columns: 1fr; }
    .acceso-marca { padding: 28px 24px 32px; gap: 20px; }
    .acceso-marca ul { display: none; }
    .acceso-marca p { font-size: 15px; margin-top: 12px; }
    .acceso-form { padding: 32px 24px 48px; align-items: flex-start; }
  }
</style>
"""

PRESENTACION = (
    '<aside class="acceso-marca"><a class="marca" href="#">' + LOGO + 'Agente Facturas</a>'
    '<div><h1>Sus clientes envían las facturas. El Excel del trimestre ya está hecho.</h1>'
    '<p>El agente lee cada factura, la anota en el formato de miEos y la archiva en la carpeta de cada cliente en su OneDrive o Google Drive.</p></div>'
    '<ul><li>Lee las facturas que llegan a su correo o WhatsApp</li><li>Un Excel por cliente y trimestre</li>'
    '<li>Lo dudoso queda aparte, para que lo revise usted</li></ul></aside>'
)


def acceso(titulo, formulario):
    """Pantalla de acceso a pantalla completa (sin barra superior)."""
    cuerpo = '<main class="acceso">' + PRESENTACION + '<section class="acceso-form"><div class="interior">' + formulario + '</div></section></main>'
    return pagina(titulo, cuerpo, barra=False, extra_head=CSS_ACCESO)


def eur(valor):
    """1234.5 -> '1.234,50 €' (formato español)."""
    try:
        s = f"{float(valor):,.2f}"
    except (TypeError, ValueError):
        return "-"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " €"
