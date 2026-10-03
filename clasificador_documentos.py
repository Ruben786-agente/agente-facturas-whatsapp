# -*- coding: utf-8 -*-
import re
import unicodedata

INDICADORES_TICKET = ["es_factura_simplificada", "sin_cif_destinatario", "formato_ticket_tpv"]


def es_ticket(metadatos_documento):
    return any(metadatos_documento.get(ind, False) for ind in INDICADORES_TICKET)


def clasificar_destino(factura, resultado_generador, metadatos_documento):
    if es_ticket(metadatos_documento):
        return "TICKETS"
    fue_a_revision = resultado_generador is not None and resultado_generador.get("motivo") is not None
    if fue_a_revision:
        return "REVISION"
    return "PROCESADA"


def nombre_archivo_destino(nombre_original, destino, motivo=None):
    base, ext = nombre_original.rsplit(".", 1) if "." in nombre_original else (nombre_original, "")
    sufijo = f".{ext}" if ext else ""
    if destino == "REVISION" and motivo:
        normalizado = unicodedata.normalize("NFKD", motivo).encode("ascii", "ignore").decode("ascii")
        motivo_slug = re.sub(r"[^A-Za-z0-9]+", "-", normalizado).strip("-").upper()[:40]
        return f"{base}__REVISAR-{motivo_slug}{sufijo}"
    return nombre_original


def procesar_ticket(ticket_extraido, tenant_id, empresa_cliente_cif, facturas_ya_registradas):
    from detector_duplicados import buscar_posible_duplicado

    factura_equivalente = {
        "num_factura": ticket_extraido["num_factura"],
        "fecha_factura": ticket_extraido["fecha_factura"],
        "emisor": {"cif_nif": ticket_extraido["proveedor"].get("cif_nif", ""),
                   "nombre": ticket_extraido["proveedor"]["nombre"]},
        "total_factura": ticket_extraido["total_factura"],
    }
    posible_duplicado = buscar_posible_duplicado(
        factura_nueva=factura_equivalente, facturas_ya_registradas=facturas_ya_registradas,
        tenant_id=tenant_id, empresa_cliente_cif=empresa_cliente_cif,
    )
    return {"destino": "TICKETS", "posible_duplicado": posible_duplicado}
