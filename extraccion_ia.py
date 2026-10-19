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
1. es_documento_fiscal: true si es una factura, factura simplificada, ticket de compra o abono
   (factura rectificativa). false si es otra cosa: albarán, presupuesto, pedido, contrato,
   publicidad, firma de correo, foto sin factura, documento ilegible o en blanco. Si dudas
   entre factura y otra cosa, pon true y baja la confianza. Si es false, el resto de campos
   puede ir vacío ("" o 0).
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
10. confianza: "alta" si todo se lee con claridad; "media" si algún dato secundario es dudoso;
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


def _llamar_api(bloque):
    """Una llamada a la IA. Devuelve (texto, stop_reason)."""
    cliente = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    respuesta = cliente.messages.create(
        model=MODELO, max_tokens=4000, system=PROMPT,
        messages=[{"role": "user", "content": [
            bloque, {"type": "text", "text": "Extrae los datos de este documento según las instrucciones."},
        ]}],
    )
    return "".join(b.text for b in respuesta.content if b.type == "text"), respuesta.stop_reason


def _leer(contenido: bytes) -> dict:
    media_type = _detectar_media_type(contenido)
    datos_b64 = base64.b64encode(contenido).decode()
    if media_type == "application/pdf":
        bloque = {"type": "document", "source": {"type": "base64", "media_type": media_type, "data": datos_b64}}
    else:
        bloque = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": datos_b64}}

    try:
        texto, motivo_parada = _llamar_api(bloque)
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


def extraer_factura(contenido: bytes) -> dict:
    """
    Lee el documento con la IA. Si sale con confianza 'baja' se lee una segunda vez; si la segunda ya no sale 'baja' y coincide con la
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


def factura_a_ticket_ligero(factura: dict) -> dict:
    return {
        "fecha_factura": factura["fecha_factura"], "num_factura": factura["num_factura"],
        "proveedor": {"cif_nif": factura["emisor"].get("cif_nif", ""), "nombre": factura["emisor"].get("nombre", "")},
        "total_factura": factura["total_factura"],
        "es_factura_simplificada": factura.get("es_factura_simplificada", False),
        "sin_cif_destinatario": factura.get("sin_cif_destinatario", True),
        "formato_ticket_tpv": factura.get("formato_ticket_tpv", False),
    }
