# -*- coding: utf-8 -*-
"""
Proceso común de un documento, venga de donde venga (correo, OneDrive, WhatsApp).

Reglas acordadas:
  - Lo que no es factura ni ticket se ignora (no se sube nada).
  - La empresa-cliente es la que RECIBE la factura (el destinatario), y se
    identifica por su CIF, no por el nombre.
  - Si esa empresa no tiene carpeta, se crea; si ya la tiene, se reutiliza.
  - Sin CIF de comprador (típico de tickets), CIF con formato no válido, o
    lectura dudosa de una empresa desconocida -> "Sin identificar".
  - Una lectura dudosa nunca crea empresas nuevas (evita carpetas basura por
    un CIF mal leído).
  - Facturas válidas: original a Facturas + fila en el Excel del trimestre.
    Facturas que no cuadran: a Revisión. Tickets: a Tickets.
  - Una factura idéntica ya procesada no se vuelve a anotar en el Excel.
"""

import hashlib
import logging
import os
import re
from datetime import datetime

from basededatos import (
    guardar_factura_procesada, obtener_carpeta_sin_identificar,
    obtener_facturas_ya_registradas, resolver_empresa_cliente_por_cif,
)
from clasificador_documentos import es_ticket, nombre_archivo_destino, procesar_ticket
from extraccion_ia import extraer_factura, factura_a_ticket_ligero, _detectar_media_type
from generar_excel_mieos import anadir_factura_a_excel
from onboarding import alta_empresa_cliente, preparar_gestoria
from periodo_fiscal import calcular_periodo_trimestral, periodo_a_slug

log = logging.getLogger("procesamiento")

_FORMATOS_CIF = (
    re.compile(r"^[A-HJNPQRSUVW]\d{7}[0-9A-J]$"),  # CIF de sociedades
    re.compile(r"^\d{8}[A-Z]$"),                    # NIF de persona física
    re.compile(r"^[XYZ]\d{7}[A-Z]$"),               # NIE
    re.compile(r"^[KLM]\d{7}[A-Z]$"),               # NIF especiales
)


def _normaliza_cif(cif):
    cif = re.sub(r"[\s.\-]", "", (cif or "")).upper()
    if len(cif) == 11 and cif.startswith("ES"):
        cif = cif[2:]
    return cif


def _cif_valido(cif):
    return any(p.match(cif) for p in _FORMATOS_CIF)


def _fecha_valida(fecha):
    try:
        datetime.strptime(fecha, "%d/%m/%Y")
        return True
    except (ValueError, TypeError):
        return False


def _fecha_o_hoy(fecha):
    return fecha if _fecha_valida(fecha) else datetime.now().strftime("%d/%m/%Y")


def _nombre_unico(nombre_original, factura, contenido):
    """
    Nombre con el que se guarda el original. Dos adjuntos distintos que se
    llamen igual ("factura.pdf") no deben pisarse, así que el nombre sale de
    los datos de la factura más una huella corta del contenido.
    """
    ext = {"application/pdf": ".pdf", "image/png": ".png"}.get(_detectar_media_type(contenido), ".jpg")
    sello = hashlib.sha1(contenido).hexdigest()[:8]
    partes = []
    fecha = factura.get("fecha_factura") or ""
    if _fecha_valida(fecha):
        d, m, a = fecha.split("/")
        partes.append(f"{a}-{m}-{d}")
    proveedor = ((factura.get("emisor") or {}).get("nombre") or "").strip()
    if proveedor:
        partes.append(proveedor[:25])
    numero = (factura.get("num_factura") or "").strip()
    if numero:
        partes.append(numero)
    base = "_".join(partes) if partes else os.path.splitext(nombre_original)[0]
    base = re.sub(r'[\\/:*?"<>|\s]+', "-", base).strip("-")[:80]
    return f"{base}_{sello}{ext}"


def _sin_identificar(storage, tenant_id, nombre, contenido, motivo):
    carpeta = obtener_carpeta_sin_identificar(tenant_id)
    if not carpeta:
        preparar_gestoria(storage, tenant_id)
        carpeta = obtener_carpeta_sin_identificar(tenant_id)
    storage.subir_archivo(carpeta, nombre_archivo_destino(nombre, "REVISION", motivo), contenido)
    return {"accion": "sin_identificar", "motivo": motivo}


def _a_revision(storage, tenant_id, empresa, nombre, contenido, factura, motivo):
    storage.subir_archivo(empresa["carpeta_revision_id"], nombre_archivo_destino(nombre, "REVISION", motivo), contenido)
    guardar_factura_procesada(
        tenant_id=tenant_id, cif_empresa_cliente=empresa["cif_nif"], tipo_documento="factura_completa",
        num_factura=(factura.get("num_factura") or "").strip() or "(sin número)",
        fecha_factura=_fecha_o_hoy(factura.get("fecha_factura")),
        proveedor_cif=(factura.get("emisor") or {}).get("cif_nif"),
        proveedor_nombre=((factura.get("emisor") or {}).get("nombre") or "").strip() or "(desconocido)",
        total_factura=factura.get("total_factura") or 0, destino="REVISION", motivo=motivo,
    )
    return {"accion": "revision", "empresa": empresa["nombre"], "motivo": motivo}


def _guardar_ticket(storage, tenant_id, empresa, nombre, contenido, factura):
    ticket = factura_a_ticket_ligero(factura)
    registradas = obtener_facturas_ya_registradas(tenant_id, empresa["cif_nif"])
    try:
        posible_duplicado = procesar_ticket(ticket, tenant_id, empresa["cif_nif"], registradas)["posible_duplicado"]
    except ValueError:  # fecha ilegible: no se puede comparar
        posible_duplicado = None
    nombre_final = nombre_archivo_destino(nombre, "REVISION", "posible duplicado") if posible_duplicado else nombre
    storage.subir_archivo(empresa["carpeta_tickets_id"], nombre_final, contenido)
    guardar_factura_procesada(
        tenant_id=tenant_id, cif_empresa_cliente=empresa["cif_nif"], tipo_documento="ticket",
        num_factura=(ticket["num_factura"] or "").strip() or "(sin número)",
        fecha_factura=_fecha_o_hoy(ticket["fecha_factura"]),
        proveedor_cif=ticket["proveedor"].get("cif_nif"), proveedor_nombre=ticket["proveedor"]["nombre"] or "(desconocido)",
        total_factura=ticket["total_factura"] or 0, destino="TICKETS",
    )
    return {"accion": "ticket", "empresa": empresa["nombre"], "posible_duplicado": bool(posible_duplicado)}


def _guardar_factura(storage, tenant_id, empresa, nombre, contenido, factura):
    numero = (factura.get("num_factura") or "").strip()
    cif_emisor = _normaliza_cif((factura.get("emisor") or {}).get("cif_nif"))
    total = factura.get("total_factura") or 0

    if numero:
        for f in obtener_facturas_ya_registradas(tenant_id, empresa["cif_nif"]):
            if (f.get("destino") == "PROCESADA" and f["num_factura"] == numero
                    and _normaliza_cif(f["emisor"].get("cif_nif")) == cif_emisor
                    and abs(f["total_factura"] - total) <= 0.01):
                return {"accion": "duplicado_exacto", "empresa": empresa["nombre"]}

    try:
        periodo = calcular_periodo_trimestral(factura["fecha_factura"])
    except (ValueError, KeyError, TypeError):
        return _a_revision(storage, tenant_id, empresa, nombre, contenido, factura, "fecha de la factura ilegible")

    nombre_excel = f"Export_{empresa['cif_nif']}_{periodo_a_slug(periodo)}.xlsx"
    existente = storage.buscar_archivo_por_nombre(empresa["carpeta_excel_id"], nombre_excel)
    contenido_excel = storage.descargar_archivo(existente.id) if existente else None

    nuevo_excel, resultado = anadir_factura_a_excel(
        contenido_excel, cif_empresa=empresa["cif_nif"], nombre_empresa=empresa["nombre"],
        periodo=periodo, factura=factura,
    )
    if not resultado["ok"]:
        return _a_revision(storage, tenant_id, empresa, nombre, contenido, factura, resultado["motivo"])

    storage.subir_archivo(empresa["carpeta_facturas_id"], nombre, contenido)
    storage.subir_archivo(empresa["carpeta_excel_id"], nombre_excel, nuevo_excel)
    guardar_factura_procesada(
        tenant_id=tenant_id, cif_empresa_cliente=empresa["cif_nif"], tipo_documento="factura_completa",
        num_factura=numero or "(sin número)", fecha_factura=factura["fecha_factura"],
        proveedor_cif=(factura.get("emisor") or {}).get("cif_nif"),
        proveedor_nombre=((factura.get("emisor") or {}).get("nombre") or "").strip() or "(desconocido)",
        total_factura=total, destino="PROCESADA",
    )
    return {"accion": "procesada", "empresa": empresa["nombre"], "excel": nombre_excel}


def procesar_documento(storage, tenant_id, contenido, nombre_original, extraer=None):
    """
    Procesa un documento (bytes) y lo archiva en el OneDrive de la gestoría.
    Devuelve un dict con "accion": ignorado | sin_identificar | ticket | procesada |
    revision | duplicado_exacto. El llamador se encarga de lo que hay en el canal de
    origen (marcar el correo como leído, borrar el archivo de la carpeta de entrada...).
    'extraer' permite sustituir la lectura con IA (útil para pruebas).
    """
    factura = (extraer or extraer_factura)(contenido)
    if not factura.get("es_documento_fiscal", True):
        return {"accion": "ignorado"}

    nombre = _nombre_unico(nombre_original, factura, contenido)
    destinatario = factura.get("destinatario") or {}
    cif = _normaliza_cif(destinatario.get("cif_nif"))

    if not cif:
        return _sin_identificar(storage, tenant_id, nombre, contenido, "sin CIF del comprador")
    if not _cif_valido(cif):
        return _sin_identificar(storage, tenant_id, nombre, contenido, "CIF del comprador con formato no válido")

    # El CIF ya normalizado se usa también dentro de la factura, para que coincida con el de la empresa.
    factura = {**factura, "destinatario": {**destinatario, "cif_nif": cif}}

    if factura.get("confianza") != "baja":
        alta_empresa_cliente(storage, tenant_id, (destinatario.get("nombre") or "").strip() or cif, cif)
    empresa = resolver_empresa_cliente_por_cif(tenant_id, [cif])
    if not empresa:
        return _sin_identificar(storage, tenant_id, nombre, contenido, "lectura dudosa de una empresa desconocida")

    if es_ticket(factura):
        return _guardar_ticket(storage, tenant_id, empresa, nombre, contenido, factura)
    return _guardar_factura(storage, tenant_id, empresa, nombre, contenido, factura)
