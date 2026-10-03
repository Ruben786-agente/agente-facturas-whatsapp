# -*- coding: utf-8 -*-
import base64
import json
import logging
import os
import re

import anthropic

log = logging.getLogger("extraccion_ia")
MODELO = "claude-sonnet-4-5"
_RUTA_AQUI = os.path.dirname(os.path.abspath(__file__))


def _cargar_prompt():
    with open(os.path.join(_RUTA_AQUI, "prompt_extraccion.md"), encoding="utf-8") as f:
        return f.read()


def _detectar_media_type(contenido: bytes) -> str:
    if contenido[:4] == b"%PDF":
        return "application/pdf"
    if contenido[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if contenido[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def _extraer_json(texto: str) -> dict:
    texto = texto.strip()
    coincidencia = re.search(r"\{.*\}", texto, re.DOTALL)
    if coincidencia:
        texto = coincidencia.group(0)
    return json.loads(texto)


def _respuesta_por_defecto(motivo: str) -> dict:
    log.warning("Extracción con IA no fiable (%s) -- se envía a revisión manual", motivo)
    return {
        "fecha_factura": "", "num_factura": "",
        "emisor": {"cif_nif": "", "nombre": ""}, "destinatario": {"cif_nif": "", "nombre": ""},
        "desgloses": [{"base": 0, "pct_iva": 0, "cuota_iva": 0, "pct_recargo": None,
                       "cuota_recargo": None, "pct_retencion": None, "cuota_retencion": None}],
        "total_factura": 0, "confianza": "baja",
        "es_factura_simplificada": False, "sin_cif_destinatario": True, "formato_ticket_tpv": False,
    }


def extraer_factura(contenido: bytes) -> dict:
    media_type = _detectar_media_type(contenido)
    if media_type == "application/pdf":
        bloque_documento = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                             "data": base64.b64encode(contenido).decode()}}
    else:
        bloque_documento = {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                          "data": base64.b64encode(contenido).decode()}}
    try:
        cliente = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        respuesta = cliente.messages.create(
            model=MODELO, max_tokens=1500, system=_cargar_prompt(),
            messages=[{"role": "user", "content": [
                bloque_documento, {"type": "text", "text": "Extrae los datos de esta factura según las instrucciones."},
            ]}],
        )
        texto = "".join(bloque.text for bloque in respuesta.content if bloque.type == "text")
        datos = _extraer_json(texto)
        campos_obligatorios = ["fecha_factura", "num_factura", "emisor", "destinatario", "desgloses", "total_factura"]
        if not all(c in datos for c in campos_obligatorios):
            return _respuesta_por_defecto("faltan campos obligatorios en la respuesta")
        datos.setdefault("confianza", "baja")
        datos.setdefault("es_factura_simplificada", False)
        datos.setdefault("sin_cif_destinatario", not datos.get("destinatario", {}).get("cif_nif"))
        datos.setdefault("formato_ticket_tpv", False)
        return datos
    except json.JSONDecodeError:
        return _respuesta_por_defecto("la IA no devolvió un JSON válido")
    except anthropic.APIError as e:
        return _respuesta_por_defecto(f"error de la API de Claude: {e}")
    except Exception as e:
        return _respuesta_por_defecto(f"error inesperado: {e}")


def factura_a_ticket_ligero(factura: dict) -> dict:
    return {
        "fecha_factura": factura["fecha_factura"], "num_factura": factura["num_factura"],
        "proveedor": {"cif_nif": factura["emisor"].get("cif_nif", ""), "nombre": factura["emisor"].get("nombre", "")},
        "total_factura": factura["total_factura"],
        "es_factura_simplificada": factura.get("es_factura_simplificada", False),
        "sin_cif_destinatario": factura.get("sin_cif_destinatario", True),
        "formato_ticket_tpv": factura.get("formato_ticket_tpv", False),
    }
