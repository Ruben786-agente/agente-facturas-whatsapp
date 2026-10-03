# -*- coding: utf-8 -*-
from datetime import datetime

TOLERANCIA_IMPORTE = 0.05
VENTANA_DIAS = 15


def _fecha(s):
    return datetime.strptime(s, "%d/%m/%Y")


def _normaliza_cif(cif):
    return (cif or "").replace(".", "").replace("-", "").replace(" ", "").upper()


def buscar_posible_duplicado(factura_nueva, facturas_ya_registradas, tenant_id, empresa_cliente_cif):
    cif_proveedor_nuevo = _normaliza_cif(factura_nueva["emisor"].get("cif_nif"))
    nombre_proveedor_nuevo = (factura_nueva["emisor"].get("nombre") or "").strip().upper()
    total_nuevo = factura_nueva["total_factura"]
    fecha_nueva = _fecha(factura_nueva["fecha_factura"])

    for existente in facturas_ya_registradas:
        if existente.get("tenant_id") != tenant_id:
            continue
        if existente.get("cif_empresa_cliente") != empresa_cliente_cif:
            continue
        if existente["num_factura"] == factura_nueva["num_factura"]:
            continue

        mismo_importe = abs(existente["total_factura"] - total_nuevo) <= TOLERANCIA_IMPORTE
        if not mismo_importe:
            continue

        dias_diferencia = abs((_fecha(existente["fecha_factura"]) - fecha_nueva).days)
        if dias_diferencia > VENTANA_DIAS:
            continue

        cif_existente = _normaliza_cif(existente["emisor"].get("cif_nif"))
        nombre_existente = (existente["emisor"].get("nombre") or "").strip().upper()
        mismo_proveedor = (
            (cif_existente and cif_proveedor_nuevo and cif_existente == cif_proveedor_nuevo)
            or (nombre_existente and nombre_proveedor_nuevo and nombre_existente == nombre_proveedor_nuevo)
        )
        if not mismo_proveedor:
            continue

        return {
            "factura_existente": existente,
            "motivo": (
                f"Importe {total_nuevo:.2f} € y proveedor '{nombre_proveedor_nuevo}' coinciden "
                f"con la factura nº {existente['num_factura']} ya registrada "
                f"({dias_diferencia} día(s) de diferencia)."
            ),
        }
    return None
