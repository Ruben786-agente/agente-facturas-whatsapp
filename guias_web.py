# -*- coding: utf-8 -*-
"""
Guías públicas pensadas para lo que una gestoría busca en Google (SEO).

Cada guía responde a una búsqueda concreta y describe SOLO lo que el producto hace hoy:
lo que está en pruebas se dice como tal, y no se promete nada que no exista.
Rutas: /guias (índice) y /guias/<slug>. Se añaden al sitemap desde publico_web.
"""
import json
from html import escape

from flask import Blueprint, abort

from estilo_web import pagina
from publico_web import CABECERA, PIE, _meta, _render

bp_guias = Blueprint("guias", __name__)

# Aviso común: transparencia sobre el estado de cada programa contable.
NOTA_PROGRAMAS = ("El Excel sale en formato <strong>miEos</strong>. <strong>ContaSOL</strong> y "
                  "<strong>Sage 50</strong> están disponibles en pruebas. Para a3, Glasof, NCS, Sage Despachos y otros, "
                  "preparamos su formato a partir de un fichero de ejemplo con datos ficticios.")

GUIAS = [
    {
        "slug": "pasar-facturas-a-excel-gestoria",
        "titulo": "Cómo pasar las facturas de sus clientes a Excel automáticamente",
        "seo": "Pasar facturas a Excel automáticamente en una gestoría",
        "desc": "Cómo dejar de teclear facturas: el agente lee los PDF y fotos que llegan al correo y los anota en un Excel por cliente y periodo, con IVA, recargo y retención.",
        "resumen": "Teclear facturas una a una es la parte más lenta y menos valiosa de llevar la contabilidad de un cliente. Esto es lo que se puede automatizar hoy y lo que sigue necesitando su revisión.",
        "secciones": [
            ("El problema: facturas en todos los formatos",
             "<p>Los clientes mandan facturas por correo, en PDF, en foto del móvil o dentro de un ZIP. Cada una hay que abrirla, identificar proveedor, CIF, fecha, base, IVA y total, y pasarla a la hoja del cliente. Con decenas de clientes, esa entrada manual se come las primeras semanas de cada trimestre.</p>"),
            ("Qué hace el agente con cada factura",
             "<ul><li>Lee <strong>PDF e imágenes</strong>, también tickets. Si un PDF trae varias facturas, las separa y las lee una a una.</li>"
             "<li>Extrae fecha, número, CIF y nombre del proveedor, base imponible, tipo de IVA, recargo de equivalencia, retención y total.</li>"
             "<li>Las anota en el Excel <strong>del cliente y del periodo</strong> (mensual o trimestral, como prefiera la gestoría).</li>"
             "<li>Guarda el original en la carpeta de cada empresa, en su OneDrive o Google Drive.</li></ul>"),
            ("Lo dudoso no se mezcla con lo bueno",
             "<p>Si el agente no está seguro (falta el CIF, el destinatario no se reconoce, la imagen es ilegible), la factura <strong>no se anota en el Excel</strong>: va a una carpeta de Revisión con el motivo en el nombre. Los duplicados quedan señalados. Usted corrige o da por revisado desde el panel, y la factura se añade al Excel en ese momento.</p>"),
            ("Qué sigue siendo trabajo suyo",
             "<p>El agente es una ayuda, no sustituye la revisión profesional. Conviene repasar lo marcado como dudoso y hacer las comprobaciones habituales antes de presentar impuestos. La última palabra es siempre de la gestoría.</p>"),
            ("Con qué programa contable encaja",
             "<p>" + NOTA_PROGRAMAS + "</p>"),
        ],
        "faq": [
            ("¿Tengo que cambiar la forma en que mis clientes envían las facturas?",
             "No. Siguen enviándolas al correo habitual de la gestoría, en PDF o foto. Usted también puede subir archivos directamente al panel y el agente las leerá y ordenará por cliente."),
            ("¿Qué pasa con las facturas que la IA no entiende?",
             "No se anotan en el Excel: van a una carpeta de Revisión con el motivo, para que las corrija o las dé por revisadas desde el panel."),
        ],
    },
    {
        "slug": "importar-facturas-contasol-sage-mieos",
        "titulo": "Importar facturas en ContaSOL, Sage 50 o miEos a partir de PDF",
        "seo": "Importar facturas PDF en ContaSOL, Sage 50 y miEos",
        "desc": "Qué formatos de Excel genera el agente para importar facturas en miEos y Holded (disponibles) y en ContaSOL y Sage 50 (en pruebas), y cómo pedir el de otro programa.",
        "resumen": "Las facturas llegan en PDF, pero su programa contable quiere un fichero de importación. Así se cierra ese hueco sin teclear.",
        "secciones": [
            ("El hueco entre el PDF y el programa contable",
             "<p>El PDF de una factura no se puede importar tal cual en un programa contable. Hay que convertirlo en filas con campos concretos: fecha, número, NIF, nombre, base, tipo, cuota, recargo, retención y total. Ese paso es el que se hace a mano.</p>"),
            ("Estado de cada programa, sin adornos",
             "<ul><li><strong>miEos:</strong> disponible. El Excel se genera en su formato, con hojas de compras y ventas.</li>"
             "<li><strong>ContaSOL:</strong> en pruebas.</li>"
             "<li><strong>Sage 50:</strong> en pruebas.</li>"
             "<li><strong>Sage Despachos, Glasof, NCS y a3:</strong> en preparación. No los anunciamos como disponibles hasta haberlos probado.</li></ul>"),
            ("Qué contiene el fichero",
             "<p>Un archivo por cliente y periodo, con el desglose de IVA por tipo, recargo de equivalencia y retención de cada factura. Las facturas emitidas por el cliente y las recibidas se separan (compras y ventas).</p>"),
            ("Si usa otro programa",
             "<p>Díganoslo al registrarse. Le pediremos un fichero de ejemplo <strong>con datos ficticios</strong> (nunca datos reales de clientes) y preparamos su formato. Priorizamos los programas que más nos piden.</p>"),
            ("Antes de importar",
             "<p>Revise lo que el agente haya marcado como dudoso y haga una importación de prueba con un cliente. Como con cualquier fichero de importación, conviene comprobar los totales antes de dar el periodo por bueno.</p>"),
        ],
        "faq": [
            ("¿Funciona con ContaSOL y Sage 50?",
             "Están disponibles en pruebas: puede usarlos sabiendo que aún los estamos afinando con gestorías reales."),
            ("¿Qué programas están en preparación?",
             "Sage Despachos, Glasof, NCS y a3. Para preparar su formato le pediremos un fichero de ejemplo con datos ficticios."),
        ],
    },
    {
        "slug": "automatizar-entrada-facturas-clientes-gestoria",
        "titulo": "Automatizar la entrada de facturas de los clientes de una gestoría",
        "seo": "Automatizar la entrada de facturas en una gestoría",
        "desc": "Un solo flujo para todos los clientes: facturas del correo, carpetas por empresa, Excel por periodo y un panel con lo pendiente de revisar y los plazos.",
        "resumen": "Cuando una gestoría lleva decenas de clientes, el problema no es una factura: es tener el mismo orden en todas. Este es el flujo que automatiza el agente.",
        "secciones": [
            ("Un flujo, todos los clientes",
             "<ol><li>Conecta el correo de la gestoría (Gmail u Outlook / Microsoft 365) y su almacenamiento (OneDrive o Google Drive).</li>"
             "<li>Las facturas y tickets que llegan como adjunto se leen solas.</li>"
             "<li>El agente crea la carpeta de cada empresa a partir del destinatario y su CIF, y aparta los tickets.</li>"
             "<li>Cada factura se anota en el Excel del cliente y del periodo.</li></ol>"),
            ("Orden sin esfuerzo",
             "<p>Carpetas por empresa, un Excel por cliente y mes (o trimestre) y los originales siempre localizables. Los documentos que no se pueden asignar a un cliente van a una carpeta aparte para que usted los identifique, en lugar de quedar mezclados.</p>"),
            ("Un panel con lo que importa",
             "<p>Cuenta atrás del plazo del modelo 303, lo pendiente de revisar y los clientes que todavía no han enviado facturas. Así sabe a quién reclamar antes de que se acabe el plazo.</p>"),
            ("Sus archivos siguen siendo suyos",
             "<p>Los archivos se guardan en su OneDrive o Google Drive, no en nuestros servidores. Nosotros solo guardamos lo necesario para que el panel funcione: qué facturas se han leído y en qué estado están.</p>"),
            ("Para quién tiene sentido",
             "<p>Para gestorías y asesorías que reciben facturas de varios clientes por correo y hoy las teclean o las ordenan a mano. Hay 14 días de prueba, sin tarjeta y sin permanencia.</p>"),
        ],
        "faq": [
            ("¿Dónde se guardan los archivos de mis clientes?",
             "En su OneDrive o Google Drive. El agente no los almacena en sus propios servidores."),
            ("¿Hay permanencia?",
             "No. Puede cancelar cuando quiera y borrar su cuenta y sus datos desde el propio panel."),
        ],
    },
    {
        "slug": "leer-facturas-del-correo-con-ia",
        "titulo": "Leer las facturas del correo con IA: qué hace y qué no",
        "seo": "Leer facturas del correo con inteligencia artificial",
        "desc": "Qué puede leer una IA en las facturas que llegan por email (PDF, fotos, varias facturas en un PDF), dónde falla y cómo se controla el error en una gestoría.",
        "resumen": "La lectura con IA es útil si se sabe dónde se equivoca. Esto es lo que lee bien, lo que se aparta para revisar y cómo se mantiene el control.",
        "secciones": [
            ("Qué puede leer",
             "<p>Facturas y tickets que llegan como adjunto al correo, en PDF o imagen. Si un PDF contiene varias facturas, las separa y las trata una a una. También puede subir PDF, fotos escaneadas o lotes en ZIP desde el panel.</p>"),
            ("Dónde puede fallar",
             "<ul><li>Imágenes borrosas o cortadas.</li><li>Facturas sin CIF o con el destinatario poco claro.</li><li>Documentos que no son facturas.</li><li>Duplicados enviados dos veces.</li></ul>"),
            ("Cómo se controla el error",
             "<p>Lo que no está claro <strong>no se anota en el Excel</strong>. Va a una carpeta de Revisión con el motivo en el nombre del archivo, y los duplicados se señalan. Desde el panel se corrige una factura dudosa en un clic y se añade al Excel en el momento.</p>"),
            ("La responsabilidad sigue siendo de la gestoría",
             "<p>El agente es una ayuda y no sustituye su revisión profesional. Usted siempre tiene la última palabra sobre lo que se contabiliza.</p>"),
            ("Privacidad",
             "<p>Los archivos se guardan en su OneDrive o Google Drive. Puede consultar cómo tratamos los datos en nuestra política de privacidad y en el contrato de encargo del tratamiento.</p>"),
        ],
        "faq": [
            ("¿La IA puede equivocarse?",
             "Sí. Por eso lo dudoso no entra en el Excel: se aparta con el motivo para que lo revise la gestoría."),
            ("¿Lee tickets y fotos del móvil?",
             "Sí, en PDF o imagen. Si falta información clave, como el CIF, el documento se aparta para que usted lo identifique."),
        ],
    },
    {
        "slug": "borrador-modelo-303-desde-facturas",
        "titulo": "Borrador del modelo 303 y 130 a partir de las facturas ya leídas",
        "seo": "Borrador del modelo 303 y 130 desde las facturas",
        "desc": "Función en pruebas: el agente calcula un borrador de IVA (303) e IRPF (130) con las facturas ya anotadas, para que la gestoría lo contraste antes de presentar.",
        "resumen": "Con las facturas ya anotadas por cliente y trimestre, el agente puede calcular un borrador de IVA e IRPF. Es una función en pruebas y siempre un punto de partida, no una presentación.",
        "secciones": [
            ("Qué calcula",
             "<ul><li><strong>Modelo 303 (IVA):</strong> IVA devengado por tipo (21 %, 10 % y 4 %), IVA soportado y resultado del trimestre.</li>"
             "<li><strong>Modelo 130 (IRPF):</strong> para personas físicas, ingresos menos gastos acumulados desde el 1 de enero, el 20 %, menos retenciones y pagos de trimestres anteriores.</li></ul>"),
            ("Qué es y qué no es",
             "<p>Es un <strong>borrador para contrastar</strong>. No presenta nada ante la Agencia Tributaria y no tiene en cuenta casos particulares, como la reducción del 5 % por gastos de difícil justificación. La página incluye una lista de comprobaciones para el repaso.</p>"),
            ("Cómo probarlo",
             "<p>Dentro del panel, en <em>Impuestos (en pruebas)</em>, elija cliente, año y trimestre. Lo más útil es probarlo con un trimestre que ya haya presentado y comparar las cifras.</p>"),
            ("Por qué está en pruebas",
             "<p>Queremos contrastarlo con gestorías reales antes de darlo por bueno. Si encuentra una diferencia, nos ayuda a corregirlo.</p>"),
        ],
        "faq": [
            ("¿Presenta el modelo 303 por mí?",
             "No. Calcula un borrador a partir de las facturas anotadas; la presentación y la revisión son de la gestoría."),
            ("¿Cómo lo pruebo con seguridad?",
             "Con un trimestre ya presentado: compare las cifras del borrador con lo que presentó."),
        ],
    },
]
_POR_SLUG = {g["slug"]: g for g in GUIAS}

CSS_GUIA = """<style>
  .g-cab { background: var(--marca); color: #fff; }
  .g-cab-in { max-width: 860px; margin: 0 auto; padding: 56px 24px 60px; }
  .g-cab h1 { color: #fff; font-size: clamp(28px, 4.2vw, 44px); line-height: 1.12; }
  .g-cab p { color: #CFE0E4; font-size: 18px; margin-top: 16px; max-width: 40em; }
  .g-cuerpo { max-width: 860px; margin: 0 auto; padding: 40px 24px 0; }
  .g-cuerpo h2 { font-size: 26px; margin: 38px 0 10px; }
  .g-cuerpo p, .g-cuerpo li { color: var(--tinta-2); font-size: 17px; line-height: 1.65; }
  .g-cuerpo ul, .g-cuerpo ol { padding-left: 22px; display: grid; gap: 8px; }
  .g-cta { background: var(--marca-clara); border-radius: 12px; padding: 28px 30px; margin-top: 44px; }
  .g-cta h2 { margin-top: 0; font-size: 24px; }
  .g-mas { margin-top: 40px; }
  .g-mas ul { list-style: none; padding: 0; }
  .g-lista { display: grid; gap: 14px; margin-top: 28px; }
  .g-lista a.tarjeta { display: block; background: var(--superficie); border: 1px solid var(--linea); border-radius: 12px; padding: 22px 24px; text-decoration: none; }
  .g-lista a.tarjeta:hover { border-color: var(--marca); }
  .g-lista h2 { font-size: 21px; margin: 0 0 4px; color: var(--marca); }
  .g-lista p { margin: 0; color: var(--tinta-2); font-size: 16px; }
</style>"""


def _ld_guia(g):
    grafo = {"@context": "https://schema.org", "@graph": [
        {"@type": "Article", "headline": g["titulo"], "description": g["desc"], "inLanguage": "es-ES",
         "mainEntityOfPage": "{URL}/guias/" + g["slug"],
         "author": {"@type": "Organization", "name": "Agente Facturas"},
         "publisher": {"@type": "Organization", "name": "Agente Facturas"}},
        {"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in g["faq"]]},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Inicio", "item": "{URL}/"},
            {"@type": "ListItem", "position": 2, "name": "Guías", "item": "{URL}/guias"},
            {"@type": "ListItem", "position": 3, "name": g["seo"], "item": "{URL}/guias/" + g["slug"]}]}]}
    return ('<script type="application/ld+json">'
            + json.dumps(grafo, ensure_ascii=False).replace("{URL}", "{{ d.url }}") + "</script>")


def _plantilla_guia(g):
    cuerpo = "".join(f"<h2>{escape(t)}</h2>{html}" for t, html in g["secciones"])
    faq = "".join(f"<details><summary>{escape(q)}</summary><p>{escape(a)}</p></details>" for q, a in g["faq"])
    otras = "".join(f'<li><a href="{{{{ url_for(\'guias.guia\', slug=\'{o["slug"]}\') }}}}">{escape(o["titulo"])}</a></li>'
                    for o in GUIAS if o["slug"] != g["slug"])
    cuerpo_html = (
        CABECERA
        + f'<section class="g-cab"><div class="g-cab-in"><h1>{escape(g["titulo"])}</h1><p>{escape(g["resumen"])}</p></div></section>'
        + f'<article class="g-cuerpo">{cuerpo}'
        + f'<section class="faq"><h2>Preguntas frecuentes</h2>{faq}</section>'
        + '<div class="g-cta"><h2>Pruébelo con sus clientes</h2>'
          '<p>14 días gratis, sin tarjeta y sin permanencia.</p>'
          '{% if logueada %}<a class="btn principal" href="{{ url_for(\'panel.panel\') }}">Ir al panel</a>'
          '{% else %}<a class="btn principal" href="{{ url_for(\'alta.registro\') }}">Probar 14 días gratis</a>{% endif %}</div>'
        + f'<div class="g-mas"><h2>Más guías</h2><ul>{otras}</ul></div></article>'
        + PIE)
    return pagina(g["seo"], cuerpo_html, barra=False,
                  extra_head=CSS_GUIA + _meta(g["seo"] + " - Agente Facturas", g["desc"], "/guias/" + g["slug"],
                                              json_ld=_ld_guia(g)))


_PLANTILLAS = {g["slug"]: _plantilla_guia(g) for g in GUIAS}


def _plantilla_indice():
    tarjetas = "".join(
        f'<a class="tarjeta" href="{{{{ url_for(\'guias.guia\', slug=\'{g["slug"]}\') }}}}">'
        f'<h2>{escape(g["titulo"])}</h2><p>{escape(g["desc"])}</p></a>' for g in GUIAS)
    cuerpo = (CABECERA
              + '<section class="g-cab"><div class="g-cab-in"><h1>Guías para gestorías</h1>'
                '<p>Cómo automatizar la entrada de facturas de sus clientes, sin prometer más de lo que hace.</p></div></section>'
              + f'<div class="g-cuerpo"><div class="g-lista">{tarjetas}</div></div>' + PIE)
    return pagina("Guías para gestorías", cuerpo, barra=False,
                  extra_head=CSS_GUIA + _meta("Guías para gestorías - Agente Facturas",
                                              "Guías prácticas para gestorías: pasar facturas a Excel, importarlas en ContaSOL, Sage 50 o miEos y automatizar la entrada de facturas.",
                                              "/guias"))


_INDICE = _plantilla_indice()


@bp_guias.route("/guias")
def indice():
    return _render(_INDICE)


@bp_guias.route("/guias/<slug>")
def guia(slug):
    if slug not in _PLANTILLAS:
        abort(404)
    return _render(_PLANTILLAS[slug])


def rutas_sitemap():
    return ["/guias"] + [f"/guias/{g['slug']}" for g in GUIAS]
