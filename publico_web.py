# -*- coding: utf-8 -*-
"""
Páginas públicas del sitio (sin iniciar sesión): inicio, condiciones del servicio, política de privacidad,
contrato de encargo del tratamiento, robots.txt y sitemap.xml.

Los datos del titular se leen de variables de entorno, así no hay que tocar el código cuando se decidan:
    TITULAR_NOMBRE      nombre y apellidos o razón social
    TITULAR_NIF         NIF / CIF
    TITULAR_DOMICILIO   domicilio completo
    CONTACTO_EMAIL      correo de contacto (también para ejercer derechos de protección de datos)
    PRECIO_PROMO        (opcional) precio de lanzamiento, por ejemplo "29 €"
    PROMO_NOTA          (opcional) condición de la promoción, por ejemplo "Para las primeras 20 gestorías"
    PRECIO_MENSUAL      por ejemplo  "39 €"   (se muestra como "39 € al mes + IVA")
    JURISDICCION        ciudad cuyos tribunales serán competentes
    URL_PUBLICA         https://agentefacturas.es
Mientras falte alguno, el texto muestra [PENDIENTE] para que no se publique por descuido con huecos.
"""

import os
from datetime import date

from flask import Blueprint, Response, abort, render_template_string, session, url_for

from estilo_web import LOGO, pagina

bp_publico = Blueprint("publico", __name__)

VERSION_LEGAL = "2026-10"


def _datos():
    def v(nombre):
        return os.environ.get(nombre, "").strip() or "[PENDIENTE]"
    precio = os.environ.get("PRECIO_MENSUAL", "").strip()
    return {
        "nombre": v("TITULAR_NOMBRE"), "nif": v("TITULAR_NIF"), "domicilio": v("TITULAR_DOMICILIO"),
        "email": v("CONTACTO_EMAIL"), "jurisdiccion": v("JURISDICCION"),
        "precio": f"{precio} al mes + IVA" if precio else "",
        "promo": (os.environ.get("PRECIO_PROMO", "").strip() + " al mes + IVA") if os.environ.get("PRECIO_PROMO", "").strip() else "",
        "promo_nota": os.environ.get("PROMO_NOTA", "").strip(),
        "url": os.environ.get("URL_PUBLICA", "https://agentefacturas.es").rstrip("/"),
        "anio": date.today().year, "version": VERSION_LEGAL,
    }


def _render(plantilla, **extra):
    return render_template_string(plantilla, d=_datos(), logueada="tenant_id" in session, **extra)


# ---------------------------------------------------------------------------
# Estilo propio de las páginas públicas (usa los colores y tipografías del panel)
# ---------------------------------------------------------------------------

CSS_PUBLICO = """
<style>
  .p-cab { background: var(--superficie); border-bottom: 1px solid var(--linea); position: sticky; top: 0; z-index: 5; }
  .p-cab-in { max-width: 1120px; margin: 0 auto; padding: 0 24px; height: 64px; display: flex; align-items: center; gap: 18px; }
  .p-cab .marca { margin-right: auto; }
  .p-cab a.enlace { color: var(--tinta-2); text-decoration: none; font-weight: 500; }
  .p-cab a.enlace:hover { color: var(--marca); }
  .p-hero { background: var(--marca); color: #fff; }
  .p-hero-in { max-width: 1120px; margin: 0 auto; padding: 88px 24px 96px; }
  .p-hero h1 { color: #fff; font-size: clamp(34px, 5vw, 60px); line-height: 1.08; max-width: 16em; }
  .p-hero p.sub { color: #CFE0E4; font-size: 19px; max-width: 36em; margin-top: 22px; }
  .p-hero .acciones-hero { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 34px; align-items: center; }
  .p-hero .btn.principal { background: #fff; color: var(--marca); border-color: #fff; font-size: 17px; padding: 13px 24px; }
  .p-hero .btn.principal:hover { background: var(--marca-clara); }
  .p-hero .btn.sec { background: transparent; color: #fff; border-color: rgba(255,255,255,.45); font-size: 17px; padding: 13px 24px; }
  .p-hero .btn.sec:hover { border-color: #fff; background: rgba(255,255,255,.08); }
  .p-hero .nota-hero { color: #9FB9C0; font-size: 14px; margin-top: 16px; }
  .p-sec { max-width: 1120px; margin: 0 auto; padding: 72px 24px 0; }
  .p-sec h2 { font-size: clamp(26px, 3.2vw, 36px); max-width: 22em; }
  .p-sec .intro { color: var(--tinta-2); font-size: 17px; max-width: 40em; margin-top: 12px; }
  .pasos-p { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; margin-top: 32px; counter-reset: paso; }
  .pasos-p > div { background: var(--superficie); border: 1px solid var(--linea); border-radius: 12px; padding: 26px; counter-increment: paso; }
  .pasos-p > div::before { content: counter(paso); display: inline-flex; width: 32px; height: 32px; border-radius: 50%; background: var(--marca-clara);
    color: var(--marca); font: 600 18px var(--serif); align-items: center; justify-content: center; margin-bottom: 14px; }
  .pasos-p h3 { font-size: 19px; margin-bottom: 6px; }
  .pasos-p p { color: var(--tinta-2); margin: 0; }
  .rejilla { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-top: 32px; }
  .rejilla > div { border-top: 2px solid var(--marca); padding-top: 14px; }
  .rejilla h3 { font-size: 18px; margin-bottom: 4px; }
  .rejilla p { color: var(--tinta-2); margin: 0; font-size: 15.5px; }
  .datos-caja { background: var(--marca-clara); border-radius: 12px; padding: 30px 32px; margin-top: 28px; }
  .datos-caja ul { margin: 0; padding-left: 20px; display: grid; gap: 8px; color: var(--tinta); }
  .precio-caja { background: var(--superficie); border: 1px solid var(--linea); border-radius: 12px; padding: 32px; margin-top: 28px; max-width: 520px; }
  .precio-caja .cifra-p { font: 600 44px/1.1 var(--serif); color: var(--marca); }
  .etiqueta-promo { display: inline-block; background: var(--marca-clara); color: var(--marca); font-weight: 600; font-size: 13px; padding: 4px 10px; border-radius: 99px; margin-bottom: 10px; }
  .precio-habitual { color: var(--tinta-3); font-size: 14px; margin-top: 6px; }
  .precio-caja ul { padding-left: 20px; margin: 16px 0 24px; color: var(--tinta-2); display: grid; gap: 6px; }
  .faq details { border-bottom: 1px solid var(--linea); padding: 16px 0; }
  .faq summary { cursor: pointer; font-weight: 600; font-size: 17px; }
  .faq p { color: var(--tinta-2); margin: 10px 0 0; max-width: 46em; }
  .p-pie { margin-top: 88px; border-top: 1px solid var(--linea); background: var(--superficie); }
  .p-pie-in { max-width: 1120px; margin: 0 auto; padding: 32px 24px; display: flex; gap: 28px; flex-wrap: wrap; align-items: baseline; color: var(--tinta-3); font-size: 14px; }
  .p-pie a { color: var(--tinta-2); }
  .p-pie .resto { margin-left: auto; }
  .legal { max-width: 780px; margin: 0 auto; padding: 48px 24px 0; }
  .legal h1 { font-size: clamp(30px, 4vw, 42px); }
  .legal h2 { font-size: 22px; margin: 34px 0 8px; }
  .legal p, .legal li { color: var(--tinta-2); line-height: 1.65; }
  .legal ul, .legal ol { padding-left: 22px; display: grid; gap: 6px; }
  .legal .version { color: var(--tinta-3); font-size: 14px; margin-top: 6px; }
  .legal table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 15px; }
  .legal th, .legal td { border: 1px solid var(--linea); padding: 8px 10px; text-align: left; vertical-align: top; }
  .legal th { background: var(--papel); }
  @media (max-width: 800px) {
    .pasos-p, .rejilla { grid-template-columns: 1fr; }
    .p-hero-in { padding: 56px 20px 64px; }
    .p-sec { padding: 52px 20px 0; }
    .p-cab-in { padding: 0 16px; gap: 12px; }
    .p-cab a.enlace.oculto-movil { display: none; }
    .p-pie .resto { margin-left: 0; }
  }
</style>
"""

CABECERA = (
    '<header class="p-cab"><div class="p-cab-in">'
    '<a class="marca" href="{{ url_for(\'publico.inicio\') }}">' + LOGO + 'Agente Facturas</a>'
    '{% if logueada %}<a class="btn principal" href="{{ url_for(\'panel.panel\') }}">Ir al panel</a>'
    '{% else %}<a class="enlace" href="{{ url_for(\'panel.login\') }}">Entrar</a>'
    '<a class="btn principal" href="{{ url_for(\'alta.registro\') }}">Probar gratis</a>{% endif %}'
    '</div></header>'
)

PIE = (
    '<footer class="p-pie"><div class="p-pie-in">'
    '<span>&copy; {{ d.anio }} Agente Facturas</span>'
    '<a href="{{ url_for(\'publico.terminos\') }}">Condiciones del servicio</a>'
    '<a href="{{ url_for(\'publico.privacidad\') }}">Privacidad</a>'
    '<a href="{{ url_for(\'publico.encargo\') }}">Encargo del tratamiento</a>'
    '<span class="resto">Contacto: <a href="mailto:{{ d.email }}">{{ d.email }}</a></span>'
    '</div></footer>'
)


def _meta(titulo_seo, descripcion, ruta):
    return (
        CSS_PUBLICO
        + f'<meta name="description" content="{descripcion}">'
        + '<link rel="canonical" href="{{ d.url }}' + ruta + '">'
        + f'<meta property="og:title" content="{titulo_seo}"><meta property="og:description" content="{descripcion}">'
        + '<meta property="og:type" content="website"><meta property="og:locale" content="es_ES">'
        + '<meta property="og:url" content="{{ d.url }}' + ruta + '">'
    )


# ---------------------------------------------------------------------------
# Inicio
# ---------------------------------------------------------------------------

PLANTILLA_INICIO = pagina("Las facturas de sus clientes, directas al Excel de miEos", CABECERA + """
<section class="p-hero"><div class="p-hero-in">
  <h1>Sus clientes envían las facturas. El Excel del trimestre ya está hecho.</h1>
  <p class="sub">El agente lee cada factura que llega a su correo, la anota en el formato de miEos y la archiva en la carpeta de cada cliente, en su OneDrive o Google Drive.</p>
  <div class="acciones-hero">
    {% if logueada %}<a class="btn principal" href="{{ url_for('panel.panel') }}">Ir al panel</a>
    {% else %}<a class="btn principal" href="{{ url_for('alta.registro') }}">Probar 14 días gratis</a>
    <a class="btn sec" href="{{ url_for('panel.login') }}">Ya tengo cuenta</a>{% endif %}
  </div>
  <p class="nota-hero">Sin tarjeta para empezar. Cancele cuando quiera.</p>
</div></section>

<section class="p-sec">
  <h2>Cómo funciona</h2>
  <div class="pasos-p">
    <div><h3>Conecte su correo y su almacenamiento</h3><p>Gmail u Outlook / Microsoft 365 para recibir, y OneDrive o Google Drive para archivar. Son dos clics y no instala nada.</p></div>
    <div><h3>Sus clientes siguen enviando como siempre</h3><p>Facturas y tickets, en PDF o en foto, a su correo habitual. No tienen que cambiar nada.</p></div>
    <div><h3>El agente lo deja hecho</h3><p>Lee cada documento, lo anota en el Excel del cliente y del trimestre y guarda el original en su carpeta.</p></div>
  </div>
</section>

<section class="p-sec">
  <h2>Lo que hace por usted</h2>
  <div class="rejilla">
    <div><h3>Lee facturas y tickets</h3><p>PDF e imágenes. Si un PDF trae varias facturas, las separa y las lee una a una.</p></div>
    <div><h3>Excel en formato miEos</h3><p>Un archivo por cliente y trimestre, con el desglose de IVA, recargo y retención.</p></div>
    <div><h3>Carpetas en orden</h3><p>Crea sola la carpeta de cada empresa a partir del destinatario y su CIF, y aparta los tickets.</p></div>
    <div><h3>Lo dudoso, aparte</h3><p>Lo que no está claro va a una carpeta de Revisión con el motivo en el nombre. Los duplicados quedan señalados.</p></div>
    <div><h3>Corrección en un clic</h3><p>Desde el panel corrige una factura dudosa y se añade al Excel en el momento.</p></div>
    <div><h3>Un panel con sus plazos</h3><p>Cuenta atrás del modelo 303, lo que está pendiente de revisar y los clientes que aún no han enviado facturas.</p></div>
  </div>
</section>

<section class="p-sec">
  <h2>Sus datos, bajo su control</h2>
  <div class="datos-caja"><ul>
    <li>Sus archivos siguen en <strong>su propio OneDrive o Google Drive</strong>: usted decide qué carpetas existen y puede cerrar el acceso cuando quiera.</li>
    <li>Cada gestoría ve <strong>solo sus datos</strong>. Las conexiones se guardan cifradas y las contraseñas, protegidas.</li>
    <li>Puede <strong>eliminar su cuenta y todos sus datos</strong> desde el panel, en cualquier momento.</li>
    <li>Para leer cada documento se envía a un proveedor de IA, únicamente con ese fin. Lo explicamos en la <a href="{{ url_for('publico.privacidad') }}">política de privacidad</a>.</li>
  </ul></div>
</section>

<section class="p-sec">
  <h2>Un solo plan, todo incluido</h2>
  <div class="precio-caja">
    {% if d.promo %}<div class="etiqueta-promo">Precio de lanzamiento</div>
    <div class="cifra-p">{{ d.promo }}</div>
    {% if d.precio %}<div class="precio-habitual">Precio habitual: <s>{{ d.precio }}</s></div>{% endif %}
    {% if d.promo_nota %}<div class="precio-habitual">{{ d.promo_nota }}</div>{% endif %}
    {% elif d.precio %}<div class="cifra-p">{{ d.precio }}</div>{% else %}<div class="cifra-p">14 días gratis</div>{% endif %}
    <ul>
      <li>Prueba gratuita de 14 días, sin tarjeta</li>
      <li>Todas las funciones incluidas</li>
      <li>Sin permanencia: cancela cuando quiera</li>
    </ul>
    {% if logueada %}<a class="btn principal grande" href="{{ url_for('alta.conexiones') }}">Mi suscripción</a>
    {% else %}<a class="btn principal grande" href="{{ url_for('alta.registro') }}">Empezar la prueba</a>{% endif %}
  </div>
</section>

<section class="p-sec faq">
  <h2>Preguntas frecuentes</h2>
  <details><summary>¿Qué necesito para empezar?</summary><p>Una cuenta de correo (Gmail u Outlook / Microsoft 365) y un almacenamiento (OneDrive o Google Drive). Si su Microsoft 365 es de empresa, puede que un administrador tenga que aprobar el permiso una sola vez; le damos un enlace para enviárselo.</p></details>
  <details><summary>¿Y si la IA se equivoca?</summary><p>Lo que no está claro no se anota en el Excel: va a Revisión con el motivo, y usted lo corrige o lo da por revisado desde el panel. El agente es una ayuda y no sustituye su revisión profesional: usted siempre tiene la última palabra.</p></details>
  <details><summary>¿Qué documentos lee?</summary><p>Facturas y tickets que lleguen como adjunto al correo, en PDF o imagen. Si el destinatario no se reconoce o falta el CIF, el documento se aparta para que usted lo identifique.</p></details>
  <details><summary>¿Dónde se guardan mis archivos?</summary><p>En su OneDrive o Google Drive, no en nuestros servidores. Nosotros solo guardamos los datos necesarios para que el panel funcione: qué facturas se han leído y su estado.</p></details>
  <details><summary>¿Puedo cancelar cuando quiera?</summary><p>Sí. No hay permanencia. Y si lo desea, puede borrar su cuenta y todos sus datos desde el propio panel.</p></details>
</section>
""" + PIE, barra=False, extra_head=_meta(
    "Agente Facturas: las facturas de sus clientes, directas al Excel de miEos",
    "El agente lee las facturas que llegan al correo de su gestoría, las anota en Excel con formato miEos y las archiva en OneDrive o Google Drive. Pruébelo 14 días gratis.",
    "/"))


@bp_publico.route("/")
def inicio():
    return _render(PLANTILLA_INICIO)


# ---------------------------------------------------------------------------
# Textos legales (borrador: deben revisarlos un abogado antes de empezar a vender)
# ---------------------------------------------------------------------------

def _legal(titulo, cuerpo, descripcion, ruta):
    return pagina(titulo, CABECERA + '<main class="legal">' + cuerpo + "</main>" + PIE, barra=False,
                  extra_head=_meta(titulo + " - Agente Facturas", descripcion, ruta))


PLANTILLA_TERMINOS = _legal("Condiciones del servicio", """
<h1>Condiciones del servicio</h1>
<p class="version">Versión {{ d.version }}</p>

<h2>1. Quién presta el servicio</h2>
<p>El servicio «Agente Facturas» (en adelante, el Servicio) lo presta {{ d.nombre }}, con NIF {{ d.nif }} y domicilio en {{ d.domicilio }} (en adelante, el Prestador). Contacto: {{ d.email }}.</p>

<h2>2. En qué consiste</h2>
<p>El Servicio lee, mediante inteligencia artificial, las facturas y tickets que llegan como adjunto al correo electrónico de la gestoría usuaria (en adelante, el Cliente), los anota en hojas de Excel por empresa y trimestre, y los archiva en el almacenamiento (OneDrive o Google Drive) que el Cliente conecta. También ofrece un panel web para consultar y corregir lo leído.</p>

<h2>3. Contratación y prueba gratuita</h2>
<ul>
  <li>El Servicio se contrata a través de la web. El Cliente declara ser una gestoría o profesional que actúa en el ámbito de su actividad.</li>
  <li>Se ofrece una prueba gratuita de 14 días, sin tarjeta. Al terminar, para seguir usándolo hay que suscribirse.</li>
  <li>Precio: {% if d.promo %}{{ d.promo }} (precio de lanzamiento; precio habitual: {{ d.precio }}){% elif d.precio %}{{ d.precio }}{% else %}[PENDIENTE]{% endif %}. Se cobra por periodos mensuales mediante la pasarela de pago Stripe y se renueva automáticamente cada mes.</li>
  <li>El Cliente puede cancelar en cualquier momento; la cancelación surte efecto al final del periodo ya pagado. No hay permanencia y no se reembolsan periodos ya iniciados, salvo error imputable al Prestador.</li>
</ul>

<h2>4. Obligaciones del Cliente</h2>
<ul>
  <li>Disponer de la autorización de sus propios clientes para tratar sus documentos, y cumplir la normativa de protección de datos como responsable del tratamiento.</li>
  <li>Mantener la confidencialidad de su contraseña y de las cuentas que conecte, y comunicar cualquier acceso no autorizado.</li>
  <li>No usar el Servicio para fines ilícitos ni intentar acceder a datos de otros clientes del Servicio.</li>
  <li><strong>Revisar el resultado.</strong> El Servicio es una herramienta de ayuda: la lectura mediante inteligencia artificial puede contener errores. El Cliente es el responsable de verificar los datos antes de usarlos en declaraciones, libros de registro u otras obligaciones fiscales o contables.</li>
</ul>

<h2>5. Disponibilidad y cambios</h2>
<p>El Prestador procura que el Servicio funcione de forma continua, pero no garantiza una disponibilidad ininterrumpida: puede haber interrupciones por mantenimiento o por fallos de proveedores externos (correo, almacenamiento, alojamiento, inteligencia artificial). El Prestador podrá mejorar o modificar el Servicio y avisará con antelación razonable de los cambios que afecten de forma sustancial al Cliente.</p>

<h2>6. Datos y confidencialidad</h2>
<p>Los archivos del Cliente permanecen en su propio almacenamiento. El tratamiento de datos personales se rige por la <a href="{{ url_for('publico.privacidad') }}">Política de privacidad</a> y, respecto de los datos de los clientes finales de la gestoría, por el <a href="{{ url_for('publico.encargo') }}">Contrato de encargo del tratamiento</a>. El Cliente puede eliminar su cuenta y todos sus datos en cualquier momento desde el panel. El Prestador mantendrá la confidencialidad de la información a la que acceda por razón del Servicio.</p>

<h2>7. Propiedad intelectual</h2>
<p>El software y el diseño del Servicio pertenecen al Prestador. El Cliente conserva todos los derechos sobre sus documentos y datos.</p>

<h2>8. Responsabilidad</h2>
<p>El Prestador responde de los daños que cause por su culpa o negligencia grave, con el límite máximo del importe pagado por el Cliente en los 12 meses anteriores al hecho. No responde de los daños indirectos, de la pérdida de beneficios, ni de las sanciones, recargos o consecuencias derivadas de declaraciones o registros elaborados con datos que el Cliente no haya verificado. Nada de lo anterior limita la responsabilidad que no pueda excluirse legalmente.</p>

<h2>9. Duración y terminación</h2>
<p>El contrato dura mientras el Cliente mantenga su cuenta. El Prestador podrá suspender el Servicio por impago, uso fraudulento o incumplimiento grave, previo aviso cuando sea posible. Al terminar, los datos se tratan conforme al contrato de encargo del tratamiento.</p>

<h2>10. Ley aplicable y tribunales</h2>
<p>Estas condiciones se rigen por la ley española. Para cualquier controversia, las partes se someten a los juzgados y tribunales de {{ d.jurisdiccion }}, salvo que la ley imponga otro fuero.</p>
""", "Condiciones del servicio de Agente Facturas: prueba gratuita, precio, obligaciones, responsabilidad y cancelación.", "/terminos")


PLANTILLA_PRIVACIDAD = _legal("Política de privacidad", """
<h1>Política de privacidad</h1>
<p class="version">Versión {{ d.version }}</p>

<h2>1. Responsable del tratamiento</h2>
<p>{{ d.nombre }}, NIF {{ d.nif }}, domicilio {{ d.domicilio }}. Contacto de privacidad: {{ d.email }}.</p>
<p>Esta política se refiere a los datos de las <strong>personas que usan el panel</strong> (gestorías). Los datos de los clientes finales de la gestoría que aparecen en las facturas los trata el Prestador como <em>encargado del tratamiento</em>, en nombre de la gestoría: véase el <a href="{{ url_for('publico.encargo') }}">contrato de encargo</a>.</p>

<h2>2. Qué datos tratamos y para qué</h2>
<table>
<tr><th>Datos</th><th>Finalidad</th><th>Base jurídica</th></tr>
<tr><td>Nombre de la gestoría, correo electrónico, contraseña (almacenada de forma protegida)</td><td>Crear y gestionar su cuenta, iniciar sesión</td><td>Ejecución del contrato</td></tr>
<tr><td>Accesos autorizados a su correo y almacenamiento (guardados cifrados) y cuentas conectadas</td><td>Prestar el Servicio: leer los correos con facturas y archivar</td><td>Ejecución del contrato</td></tr>
<tr><td>Datos de suscripción y pago (los gestiona Stripe; no guardamos su tarjeta)</td><td>Cobro de la suscripción y facturación</td><td>Ejecución del contrato y obligación legal</td></tr>
<tr><td>Avisos y comunicaciones sobre el estado del Servicio</td><td>Informarle de incidencias o plazos</td><td>Ejecución del contrato e interés legítimo</td></tr>
<tr><td>Registros técnicos mínimos de funcionamiento</td><td>Seguridad y detección de abusos (por ejemplo, intentos de acceso)</td><td>Interés legítimo</td></tr>
</table>

<h2>3. Con quién compartimos los datos</h2>
<p>Usamos proveedores que tratan datos por nuestra cuenta y con las garantías exigidas por el RGPD:</p>
<table>
<tr><th>Proveedor</th><th>Para qué</th><th>Ubicación</th></tr>
<tr><td>Anthropic</td><td>Lectura de los documentos mediante inteligencia artificial</td><td>EE. UU.</td></tr>
<tr><td>Render</td><td>Alojamiento de la aplicación</td><td>[PENDIENTE: región]</td></tr>
<tr><td>Supabase</td><td>Base de datos</td><td>UE (París)</td></tr>
<tr><td>Stripe</td><td>Pagos y suscripciones</td><td>UE / EE. UU.</td></tr>
<tr><td>Resend</td><td>Envío de avisos por correo</td><td>EE. UU.</td></tr>
<tr><td>Microsoft y Google</td><td>Correo y almacenamiento que usted mismo conecta</td><td>Según su cuenta</td></tr>
</table>
<p>Las transferencias a EE. UU. se amparan en el Marco de Privacidad de Datos UE-EE. UU. o en cláusulas contractuales tipo de la Comisión Europea. No vendemos sus datos ni los usamos para publicidad.</p>

<h2>4. Cuánto tiempo los conservamos</h2>
<p>Mientras mantenga su cuenta. Puede eliminarla desde el panel («Eliminar mi cuenta y mis datos») y se borran todos los datos del Servicio de forma inmediata. Los datos de facturación pueden conservarse el tiempo que exija la normativa fiscal.</p>

<h2>5. Sus derechos</h2>
<p>Puede ejercer sus derechos de acceso, rectificación, supresión, oposición, limitación y portabilidad escribiendo a {{ d.email }}. Si considera que no hemos tratado sus datos correctamente, puede reclamar ante la Agencia Española de Protección de Datos (www.aepd.es).</p>

<h2>6. Seguridad</h2>
<p>Aplicamos medidas técnicas y organizativas adecuadas: comunicaciones cifradas, accesos y credenciales guardados cifrados, contraseñas protegidas, separación de los datos de cada gestoría y límite de intentos de acceso. Ante una brecha que le afecte, se lo comunicaremos sin dilación indebida.</p>

<h2>7. Cookies</h2>
<p>Solo usamos una cookie técnica de sesión, necesaria para mantener su sesión iniciada. No usamos cookies de publicidad ni de seguimiento.</p>
""", "Política de privacidad de Agente Facturas: qué datos tratamos, con qué finalidad, proveedores y sus derechos.", "/privacidad")


PLANTILLA_ENCARGO = _legal("Contrato de encargo del tratamiento", """
<h1>Contrato de encargo del tratamiento</h1>
<p class="version">Versión {{ d.version }} · Artículo 28 del Reglamento (UE) 2016/679</p>

<h2>1. Partes y objeto</h2>
<p><strong>Responsable:</strong> la gestoría que contrata el Servicio (el Cliente). <strong>Encargado:</strong> {{ d.nombre }}, NIF {{ d.nif }}, domicilio {{ d.domicilio }} (el Prestador).</p>
<p>El Prestador tratará datos personales por cuenta del Cliente únicamente para prestar el Servicio descrito en las <a href="{{ url_for('publico.terminos') }}">Condiciones del servicio</a>.</p>

<h2>2. Descripción del tratamiento</h2>
<ul>
  <li><strong>Naturaleza y finalidad:</strong> lectura de facturas y tickets recibidos por correo, registro en hojas de cálculo, archivo en el almacenamiento del Cliente y consulta en el panel.</li>
  <li><strong>Tipos de datos:</strong> datos identificativos y fiscales que aparecen en facturas y tickets (nombre o razón social, NIF/CIF, domicilio, importes).</li>
  <li><strong>Interesados:</strong> clientes, proveedores y otras personas que figuren en los documentos del Cliente.</li>
  <li><strong>Duración:</strong> mientras dure la prestación del Servicio.</li>
</ul>

<h2>3. Obligaciones del Prestador</h2>
<ul>
  <li>Tratar los datos solo siguiendo las instrucciones documentadas del Cliente, que son las de estas condiciones y el uso normal del Servicio.</li>
  <li>Garantizar que las personas autorizadas se comprometen a la confidencialidad.</li>
  <li>Aplicar las medidas de seguridad descritas en la política de privacidad y otras equivalentes al riesgo.</li>
  <li>Asistir al Cliente, en lo posible, en la atención de los derechos de los interesados y en el cumplimiento de sus obligaciones de seguridad, notificación de brechas y evaluación de impacto.</li>
  <li>Notificar al Cliente sin dilación indebida las brechas de seguridad que afecten a sus datos, para que pueda cumplir el plazo de 72 horas ante la autoridad de control.</li>
  <li>No comunicar los datos a terceros salvo a los subencargados autorizados o por obligación legal.</li>
</ul>

<h2>4. Subencargados autorizados</h2>
<p>El Cliente autoriza con carácter general a los siguientes subencargados, que ofrecen garantías equivalentes: Anthropic (lectura mediante inteligencia artificial, EE. UU.), Render (alojamiento) y Supabase (base de datos, UE). El Prestador informará de cualquier cambio con antelación suficiente para que el Cliente pueda oponerse. Las transferencias internacionales se amparan en el Marco de Privacidad de Datos UE-EE. UU. o en cláusulas contractuales tipo.</p>

<h2>5. Devolución o supresión</h2>
<p>Al terminar el Servicio, o cuando el Cliente lo pida, el Prestador suprimirá los datos que conserve. El Cliente puede hacerlo en cualquier momento desde el panel («Eliminar mi cuenta y mis datos»). Los archivos originales y los Excel están en el almacenamiento del propio Cliente y no se tocan.</p>

<h2>6. Auditoría</h2>
<p>El Prestador pondrá a disposición del Cliente la información necesaria para demostrar el cumplimiento de estas obligaciones y permitirá auditorías razonables, con preaviso y sin perturbar el Servicio.</p>
""", "Contrato de encargo del tratamiento de datos (art. 28 RGPD) entre la gestoría y Agente Facturas.", "/encargo")


@bp_publico.route("/terminos")
def terminos():
    return _render(PLANTILLA_TERMINOS)


@bp_publico.route("/privacidad")
def privacidad():
    return _render(PLANTILLA_PRIVACIDAD)


@bp_publico.route("/encargo")
def encargo():
    return _render(PLANTILLA_ENCARGO)


# ---------------------------------------------------------------------------
# Para buscadores
# ---------------------------------------------------------------------------

@bp_publico.route("/robots.txt")
def robots():
    base = _datos()["url"]
    texto = ("User-agent: *\nAllow: /\nDisallow: /panel\nDisallow: /conexiones\nDisallow: /revision\n"
             "Disallow: /abrir\nDisallow: /sin-identificar\nDisallow: /onboarding\nDisallow: /tareas\nDisallow: /webhook\n"
             f"\nSitemap: {base}/sitemap.xml\n")
    return Response(texto, mimetype="text/plain")


@bp_publico.route("/sitemap.xml")
def sitemap():
    base = _datos()["url"]
    rutas = ["/", "/registro", "/login", "/terminos", "/privacidad", "/encargo"]
    cuerpo = "".join(f"<url><loc>{base}{r}</loc></url>" for r in rutas)
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    + cuerpo + "</urlset>", mimetype="application/xml")


# ---------------------------------------------------------------------------
# Consumo de la IA (solo para el titular: el email debe coincidir con ADMIN_EMAIL)
# ---------------------------------------------------------------------------

# Precios en dólares por millón de tokens (entrada, salida), según las tarifas públicas consultadas en octubre de 2026.
# Se pueden cambiar sin tocar el código con la variable PRECIOS_IA, por ejemplo: {"claude-haiku-5-5": [0.10, 0.50]}
PRECIOS_IA = {"claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}


def _precios_ia():
    precios = dict(PRECIOS_IA)
    try:
        import json
        for modelo, (entrada, salida) in json.loads(os.environ.get("PRECIOS_IA", "{}") or "{}").items():
            precios[modelo] = (float(entrada), float(salida))
    except (ValueError, TypeError):
        pass
    return precios


@bp_publico.route("/admin/uso-ia")
def uso_ia():
    from basededatos import email_de_gestoria, obtener_comparacion, obtener_uso_ia
    admin = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    tenant = session.get("tenant_id")
    if not admin or not tenant or (email_de_gestoria(tenant) or "").lower() != admin:
        abort(404)
    precios = _precios_ia()
    filas = obtener_uso_ia(60)
    por_modelo = {}
    for f in filas:
        p = precios.get(f["modelo"])
        f["usd"] = (f["entrada"] * p[0] + f["salida"] * p[1]) / 1e6 if p else None
        f["usd_llamada"] = f["usd"] / f["llamadas"] if f["usd"] is not None and f["llamadas"] else None
        m = por_modelo.setdefault(f["modelo"], {"modelo": f["modelo"], "llamadas": 0, "entrada": 0, "salida": 0, "usd": 0.0, "conocido": p is not None})
        m["llamadas"] += f["llamadas"]; m["entrada"] += f["entrada"]; m["salida"] += f["salida"]
        m["usd"] += f["usd"] or 0.0
    resumen = sorted(por_modelo.values(), key=lambda m: m["usd"], reverse=True)
    total_usd = sum(m["usd"] for m in resumen)
    total_llamadas = sum(m["llamadas"] for m in resumen)
    comparadas, coinciden = obtener_comparacion()
    plantilla = pagina("Consumo de la IA", """
<main class="pagina" style="padding-top:40px;max-width:980px;">
  <h1 style="font-size:32px;">Consumo de la IA</h1>
  <p class="tenue">Cada llamada lee un documento o divide un PDF (una relectura cuenta como otra llamada). Últimos 60 días con actividad.</p>

  <h2 style="font-size:20px;margin-top:26px;">Total por modelo</h2>
  <table style="width:100%;border-collapse:collapse;margin-top:8px;">
    <tr><th align="left">Modelo</th><th align="right">Llamadas</th><th align="right">Tokens entrada</th><th align="right">Tokens salida</th><th align="right">Coste (USD)</th><th align="right">USD / llamada</th></tr>
    {% for m in resumen %}<tr><td>{{ m.modelo }}</td><td align="right">{{ m.llamadas }}</td><td align="right">{{ m.entrada }}</td><td align="right">{{ m.salida }}</td>
      <td align="right">{{ "%.2f"|format(m.usd) if m.conocido else "sin precio" }}</td><td align="right">{{ "%.4f"|format(m.usd / m.llamadas) if m.conocido and m.llamadas else "-" }}</td></tr>{% endfor %}
    <tr style="font-weight:600;border-top:1px solid var(--linea);"><td>Total</td><td align="right">{{ total_llamadas }}</td><td></td><td></td><td align="right">{{ "%.2f"|format(total_usd) }}</td><td align="right">{{ "%.4f"|format(total_usd / total_llamadas) if total_llamadas else "-" }}</td></tr>
  </table>

  {% if comparadas %}
  <h2 style="font-size:20px;margin-top:26px;">Modelo barato frente al principal</h2>
  <p>Ha leído lo mismo (número, fecha, total y los dos CIF, y con lectura clara que cuadra) en <strong>{{ coinciden }} de {{ comparadas }}</strong> documentos ({{ "%.0f"|format(100 * coinciden / comparadas) }} %).</p>
  {% endif %}

  <h2 style="font-size:20px;margin-top:26px;">Por día</h2>
  <table style="width:100%;border-collapse:collapse;margin-top:8px;">
    <tr><th align="left">Día</th><th align="left">Modelo</th><th align="right">Llamadas</th><th align="right">Tokens entrada</th><th align="right">Tokens salida</th><th align="right">Coste (USD)</th></tr>
    {% for f in filas %}<tr><td>{{ f.dia }}</td><td>{{ f.modelo }}</td><td align="right">{{ f.llamadas }}</td><td align="right">{{ f.entrada }}</td><td align="right">{{ f.salida }}</td>
      <td align="right">{{ "%.2f"|format(f.usd) if f.usd is not none else "-" }}</td></tr>{% endfor %}
  </table>
  <p class="tenue" style="margin-top:16px;">Precios usados (USD por millón de tokens, entrada / salida): {% for k, v in precios.items() %}{{ k }}: {{ v[0] }} / {{ v[1] }}{% if not loop.last %}; {% endif %}{% endfor %}. Confírmelos en la consola de Anthropic.</p>
</main>""")
    return render_template_string(plantilla, filas=filas, resumen=resumen, total_usd=total_usd, total_llamadas=total_llamadas,
                                  comparadas=comparadas, coinciden=coinciden, precios=precios)
