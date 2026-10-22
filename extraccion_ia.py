# -*- coding: utf-8 -*-
"""
Lectura de facturas con IA (Claude con visión). Una sola llamada por documento.

El prompt y el esquema de salida viven dentro de este archivo (antes se leían
de un .md y el esquema nunca llegaba a enviarse al modelo).

Variables de entorno:
    ANTHROPIC_API_KEY    -- clave de la API de Claude
    MODELO_EXTRACCION    -- opcional; por defecto claude-sonnet-5-5
"""

import base64
import json
import logging
import os
import re

import anthropic

log = logging.getLogger("extraccion_ia")

MODELO = os.environ.get("MODELO_EXTRACCION", "claude-sonnet-5-5")
# Modelo barato para la primera lectura (opcional). Si está definido, sus lecturas dudosas se repiten con MODELO.
MODELO_RAPIDO = os.environ.get("MODELO_EXTRACCION_RAPIDA", "").strip()
# Con COMPARAR_MODELOS=1 (y MODELO_RAPIDO definido) se sigue usando MODELO para decidir, y además el barato lee lo mismo
# solo para anotar cuántas veces coincide (contadores, sin datos de nadie). Sirve para decidir con datos si activarlo.
COMPARAR_MODELOS = os.environ.get("COMPARAR_MODELOS", "") == "1"
# Con VERIFICACION_DOBLE=1 cada factura se lee dos veces, con modelos distintos si hay MODELO_RAPIDO, y solo se anota en el
# Excel si las dos lecturas coinciden en número, fecha, total, CIF e importes del desglose. Si no, va a Revisión.
VERIFICACION_DOBLE = os.environ.get("VERIFICACION_DOBLE", "") == "1"

PROMPT = """Eres un extractor de datos de facturas y tickets españoles para uso contable.
Analiza el documento adjunto (imagen o PDF) y devuelve ÚNICAMENTE un JSON válido con
exactamente la estructura de abajo. Sin explicaciones, sin markdown, sin texto fuera del JSON.

ESTRUCTURA (todos los campos son obligatorios):
{
  "es_documento_fiscal": true,
  "fecha_factura": "DD/MM/AAAA",
  "num_factura": "texto",
  "emisor": {"cif_nif": "", "nombre": "", "domicilio": "", "localidad": "", "cp": ""},
  "destinatario": {"cif_nif": "", "nombre": ""},
  "desgloses": [
    {"base": 0.0, "pct_iva": 0.0, "cuota_iva": 0.0,
     "pct_recargo": null, "cuota_recargo": null,
     "pct_retencion": null, "cuota_retencion": null}
  ],
  "total_factura": 0.0,
  "confianza": "alta",
  "es_factura_simplificada": false,
  "sin_cif_destinatario": false,
  "formato_ticket_tpv": false
}

REGLAS:
0. El documento puede venir girado (de lado o boca abajo), torcido o escaneado en baja resolución. Léelo igualmente
   como si estuviera derecho, fijándote con especial cuidado en cada dígito del NIF/CIF y de los importes.
1. es_documento_fiscal: true si es una factura, factura simplificada, ticket de compra o abono
   (factura rectificativa). false SOLO si es claramente otra cosa: albarán, presupuesto, pedido,
   contrato, publicidad, firma de correo, o una página completamente en blanco. Si dudas entre
   factura y otra cosa, pon true y baja la confianza. Si el documento parece una factura o un ticket
   pero está borroso, cortado, torcido o ilegible, NO lo descartes: pon true, confianza "baja" y deja
   vacío lo que no puedas leer. Que un documento se lea mal nunca es motivo para decir false. Si es
   false, el resto de campos puede ir vacío ("" o 0).
2. CIF/NIF: mayúsculas y sin espacios, puntos ni guiones. Si no aparece con claridad, "".
   Nunca inventes un CIF.
3. num_factura: siempre texto, conservando ceros a la izquierda, guiones y barras.
4. Fechas: siempre DD/MM/AAAA.
5. desgloses: un elemento por cada tipo de IVA distinto (agrupa por porcentaje, no por línea
   de producto, sumando las bases). Importes negativos en abonos.
6. Retención de IRPF o recargo de equivalencia: solo si aparecen impresos; si no, null.
7. emisor es quien emite la factura (proveedor); destinatario es el cliente. Distínguelos con
   cuidado: de ello depende a qué empresa se asigna el documento.
8. total_factura: el total impreso en el documento, no recalculado.
9. es_factura_simplificada: true si pone "factura simplificada" o equivalente.
   sin_cif_destinatario: true si en ningún sitio aparece el NIF/CIF del comprador.
   formato_ticket_tpv: true si parece un recibo de datáfono/TPV y no una factura formal.
10. confianza: que el documento sea una foto de papel, con sombras, algo torcido o con la página doblada
    NO baja la confianza si todos los datos se leen con claridad. "alta" si todo se lee con claridad; "media" si algún dato secundario es dudoso;
    "baja" si el CIF, los importes o el total no se leen con seguridad, o si la suma de bases
    y cuotas no coincide con el total.
"""

_RUTA_AQUI = os.path.dirname(os.path.abspath(__file__))


def _detectar_media_type(contenido: bytes) -> str:
    if contenido[:4] == b"%PDF":
        return "application/pdf"
    if contenido[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if contenido[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def _extraer_json(texto: str) -> dict:
    """Coge el PRIMER objeto JSON completo de la respuesta, aunque venga con texto,
    bloques de código o varios objetos seguidos."""
    decodificador = json.JSONDecoder()
    inicio = texto.find("{")
    while inicio != -1:
        try:
            objeto, _ = decodificador.raw_decode(texto[inicio:])
            if isinstance(objeto, dict):
                return objeto
        except json.JSONDecodeError:
            pass
        inicio = texto.find("{", inicio + 1)
    raise json.JSONDecodeError("No hay ningún objeto JSON en la respuesta", texto, 0)


def _respuesta_por_defecto(motivo: str) -> dict:
    """Si algo falla nunca se frena el proceso: confianza 'baja' y es_documento_fiscal True,
    para que el documento llegue a una carpeta de revisión y no se pierda."""
    log.warning("Extracción con IA no fiable (%s) -- se envía a revisión manual", motivo)
    return {
        "es_documento_fiscal": True,
        "fecha_factura": "", "num_factura": "",
        "emisor": {"cif_nif": "", "nombre": ""}, "destinatario": {"cif_nif": "", "nombre": ""},
        "desgloses": [{"base": 0, "pct_iva": 0, "cuota_iva": 0, "pct_recargo": None,
                       "cuota_recargo": None, "pct_retencion": None, "cuota_retencion": None}],
        "total_factura": 0, "confianza": "baja",
        "es_factura_simplificada": False, "sin_cif_destinatario": True, "formato_ticket_tpv": False,
        "_lectura_fallida": True,
    }


def _llamar_api(bloque, modelo=None):
    """Una llamada a la IA. Devuelve (texto, stop_reason)."""
    modelo = modelo or MODELO
    cliente = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    respuesta = cliente.messages.create(
        model=modelo, max_tokens=4000, system=PROMPT,
        messages=[{"role": "user", "content": [
            bloque, {"type": "text", "text": "Extrae los datos de este documento según las instrucciones."},
        ]}],
    )
    try:  # contar el consumo no puede romper nunca la lectura
        from basededatos import registrar_uso_ia
        registrar_uso_ia(respuesta.usage.input_tokens, respuesta.usage.output_tokens, modelo)
    except Exception:
        log.debug("No se pudo registrar el consumo de la IA")
    return "".join(b.text for b in respuesta.content if b.type == "text"), respuesta.stop_reason


def _leer(contenido: bytes, modelo=None) -> dict:
    media_type = _detectar_media_type(contenido)
    datos_b64 = base64.b64encode(contenido).decode()
    if media_type == "application/pdf":
        bloque = {"type": "document", "source": {"type": "base64", "media_type": media_type, "data": datos_b64}}
    else:
        bloque = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": datos_b64}}

    try:
        texto, motivo_parada = _llamar_api(bloque, modelo)
        if motivo_parada == "max_tokens":
            log.warning("La respuesta de la IA se cortó por longitud")
        try:
            datos = _extraer_json(texto)
        except json.JSONDecodeError:
            log.warning("Respuesta de la IA no válida (%d caracteres)", len(texto))
            raise

        if datos.get("es_documento_fiscal") is False:
            return {**_respuesta_por_defecto("no es un documento fiscal"), "es_documento_fiscal": False}

        obligatorios = ["fecha_factura", "num_factura", "emisor", "destinatario", "desgloses", "total_factura"]
        if not all(c in datos for c in obligatorios):
            return _respuesta_por_defecto("faltan campos obligatorios en la respuesta")

        datos.setdefault("es_documento_fiscal", True)
        datos.setdefault("confianza", "baja")
        datos.setdefault("es_factura_simplificada", False)
        datos.setdefault("sin_cif_destinatario", not (datos.get("destinatario") or {}).get("cif_nif"))
        datos.setdefault("formato_ticket_tpv", False)
        return datos

    except json.JSONDecodeError:
        return _respuesta_por_defecto("la IA no devolvió un JSON válido")
    except anthropic.APIError as e:
        return _respuesta_por_defecto(f"error de la API de Claude: {e}")
    except Exception as e:
        return _respuesta_por_defecto(f"error inesperado: {e}")


def _cif(x):
    return re.sub(r"[\s.\-]", "", (x or "")).upper()


def _coinciden(a: dict, b: dict) -> bool:
    """Dos lecturas independientes dicen lo mismo en lo que importa: número, fecha, total y los dos CIF."""
    try:
        return (
            (a.get("num_factura") or "").strip().upper() == (b.get("num_factura") or "").strip().upper()
            and (a.get("fecha_factura") or "").strip() == (b.get("fecha_factura") or "").strip()
            and abs(float(a.get("total_factura") or 0) - float(b.get("total_factura") or 0)) <= 0.01
            and _cif((a.get("emisor") or {}).get("cif_nif")) == _cif((b.get("emisor") or {}).get("cif_nif"))
            and _cif((a.get("destinatario") or {}).get("cif_nif")) == _cif((b.get("destinatario") or {}).get("cif_nif"))
        )
    except (TypeError, ValueError):
        return False


def _cuadra(datos: dict) -> bool:
    """Bases + cuotas (+ recargo - retención) suman el total impreso. Sin desglose no se puede comprobar: False."""
    try:
        desgloses = datos.get("desgloses") or []
        if not desgloses:
            return False
        suma = sum(float(d.get("base") or 0) + float(d.get("cuota_iva") or 0) + float(d.get("cuota_recargo") or 0)
                   - float(d.get("cuota_retencion") or 0) for d in desgloses)
        return abs(suma - float(datos.get("total_factura") or 0)) <= 0.05
    except (TypeError, ValueError):
        return False


def _diferencias(a: dict, b: dict) -> list:
    """Campos críticos en los que dos lecturas del mismo documento no coinciden. Vacía si dicen lo mismo."""
    dif = []
    try:
        if (a.get("num_factura") or "").strip().upper() != (b.get("num_factura") or "").strip().upper():
            dif.append("número de factura")
        if (a.get("fecha_factura") or "").strip() != (b.get("fecha_factura") or "").strip():
            dif.append("fecha")
        if abs(float(a.get("total_factura") or 0) - float(b.get("total_factura") or 0)) > 0.01:
            dif.append("total")
        if _cif((a.get("emisor") or {}).get("cif_nif")) != _cif((b.get("emisor") or {}).get("cif_nif")):
            dif.append("CIF del emisor")
        if _cif((a.get("destinatario") or {}).get("cif_nif")) != _cif((b.get("destinatario") or {}).get("cif_nif")):
            dif.append("CIF del comprador")

        def _lineas(x):
            return sorted((round(float(d.get("base") or 0), 2), float(d.get("pct_iva") or 0), round(float(d.get("cuota_iva") or 0), 2))
                          for d in (x.get("desgloses") or []))
        if _lineas(a) != _lineas(b):
            dif.append("importes del desglose")
    except (TypeError, ValueError):
        dif.append("formato de los datos")
    return dif


def _acordar(elegida: dict, verificadora: dict) -> dict:
    """Doble lectura: si la segunda opinión no existe o discrepa en algo crítico, la factura va a Revisión diciendo en qué."""
    if verificadora.get("_lectura_fallida") or verificadora.get("es_documento_fiscal") is False:
        return {**elegida, "confianza": "baja", "_motivo_revision": "la segunda lectura de comprobación no ha podido confirmar el documento"}
    dif = _diferencias(elegida, verificadora)
    if dif:
        return {**elegida, "confianza": "baja", "_motivo_revision": "las dos lecturas no coinciden en: " + ", ".join(dif)}
    return elegida


def _fiable(datos: dict) -> bool:
    """Una lectura del modelo barato se acepta solo si es clara y cuadra; si no, se repite con el modelo principal."""
    if datos.get("_lectura_fallida") or datos.get("es_documento_fiscal") is False:
        return False  # que algo «no sea una factura» lo confirma siempre el modelo principal
    if datos.get("confianza") != "alta":
        return False
    if datos.get("es_factura_simplificada") or datos.get("formato_ticket_tpv"):
        return float(datos.get("total_factura") or 0) > 0   # los tickets suelen no traer desglose
    from validaciones import problemas_factura
    return _cuadra(datos) and not problemas_factura(datos)


def _extraer_con_modelo_principal(contenido: bytes) -> dict:
    """
    Lee el documento con MODELO. Si sale con confianza 'baja' se lee una segunda vez; si la segunda ya no sale 'baja' y coincide con la
    primera en número, fecha, total y CIF, se acepta (dos lecturas independientes que dicen lo
    mismo). Si no, se queda como estaba: 'baja' y a Revisión.
    """
    primera = _leer(contenido)
    if primera.get("es_documento_fiscal") is False or primera.get("confianza") != "baja":
        return primera

    segunda = _leer(contenido)
    if segunda.get("es_documento_fiscal") is False or segunda.get("confianza") == "baja":
        log.info("Segunda lectura: sigue con confianza baja, va a Revisión")
        return primera
    if primera.get("_lectura_fallida"):  # la primera no llegó a leerse (fallo puntual): vale la segunda
        log.info("Segunda lectura: la primera falló y la segunda es válida")
        return {**segunda, "relectura": "tras_fallo"}
    if _coinciden(primera, segunda):
        log.info("Segunda lectura: coincide con la primera, se acepta")
        return {**segunda, "confianza": "media", "relectura": "confirmada"}
    log.info("Segunda lectura: no coincide con la primera, va a Revisión")
    return primera


def _debe_verificarse(resultado: dict) -> bool:
    return VERIFICACION_DOBLE and resultado.get("es_documento_fiscal") is not False and resultado.get("confianza") != "baja" \
        and not resultado.get("_lectura_fallida")


def extraer_factura(contenido: bytes) -> dict:
    """
    Sin variables: lectura con el modelo principal (repetida si sale dudosa) y, después, las comprobaciones de validaciones.py.
    MODELO_EXTRACCION_RAPIDA: primera lectura con el modelo barato; si es clara y cuadra se acepta; si no, se lee con el principal.
    VERIFICACION_DOBLE=1: además, solo se acepta si una segunda lectura (con el otro modelo) coincide en lo crítico.
    COMPARAR_MODELOS=1: se sigue decidiendo con el principal y el barato solo anota cuántas veces coincide.
    """
    if MODELO_RAPIDO and not COMPARAR_MODELOS:
        rapida = _leer(contenido, MODELO_RAPIDO)
        if _fiable(rapida):
            if not _debe_verificarse(rapida):
                return rapida
            return _acordar(rapida, _leer(contenido))          # segunda opinión del modelo principal
        log.info("Lectura rápida dudosa: se repite con el modelo principal")
        resultado = _extraer_con_modelo_principal(contenido)
        return _acordar(resultado, rapida) if _debe_verificarse(resultado) else resultado

    resultado = _extraer_con_modelo_principal(contenido)
    if MODELO_RAPIDO and COMPARAR_MODELOS and resultado.get("es_documento_fiscal") is not False and not resultado.get("_lectura_fallida"):
        try:  # solo para medir: el resultado que se usa es el del modelo principal
            from basededatos import registrar_comparacion
            rapida = _leer(contenido, MODELO_RAPIDO)
            registrar_comparacion(_fiable(rapida) and _coinciden(resultado, rapida))
        except Exception:
            log.debug("No se pudo anotar la comparación de modelos")
    if _debe_verificarse(resultado):  # sin modelo barato, la segunda lectura es otra pasada del principal
        return _acordar(resultado, _leer(contenido, MODELO_RAPIDO or None))
    return resultado


def factura_a_ticket_ligero(factura: dict) -> dict:
    return {
        "fecha_factura": factura["fecha_factura"], "num_factura": factura["num_factura"],
        "proveedor": {"cif_nif": factura["emisor"].get("cif_nif", ""), "nombre": factura["emisor"].get("nombre", "")},
        "total_factura": factura["total_factura"],
        "es_factura_simplificada": factura.get("es_factura_simplificada", False),
        "sin_cif_destinatario": factura.get("sin_cif_destinatario", True),
        "formato_ticket_tpv": factura.get("formato_ticket_tpv", False),
    }
