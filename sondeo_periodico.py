# -*- coding: utf-8 -*-
"""
Job de sondeo periódico (polling) de OneDrive.
"""

import logging
import time
from datetime import datetime, timezone

from almacenamiento import obtener_almacenamiento
from autenticacion_onedrive import refrescar_token
from basededatos import proveedor_almacenamiento_activo
from clasificador_documentos import es_ticket, nombre_archivo_destino, procesar_ticket
from generar_excel_mieos import anadir_factura_a_excel
from periodo_fiscal import periodo_para, nombre_excel as nombre_del_excel
from extraccion_ia import extraer_factura, factura_a_ticket_ligero
from basededatos import (
    obtener_tenants_activos, obtener_facturas_ya_registradas,
    guardar_factura_procesada, actualizar_ultima_revision,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sondeo")

INTERVALO_SEGUNDOS = 5 * 60  # 5 minutos -- ajustable


def procesar_archivo(storage, archivo, cliente, facturas_ya_registradas):
    contenido = storage.descargar_archivo(archivo.id)

    # Una única llamada a la IA: devuelve todos los campos, incluidas las
    # banderas que dicen si es un ticket o una factura completa.
    factura_completa = extraer_factura(contenido)

    if es_ticket(factura_completa):
        ticket_extraido = factura_a_ticket_ligero(factura_completa)
        resultado = procesar_ticket(
            ticket_extraido, tenant_id=cliente["tenant_id"],
            empresa_cliente_cif=cliente["cif_empresa_cliente"],
            facturas_ya_registradas=facturas_ya_registradas,
        )
        motivo_duplicado = None
        if resultado["posible_duplicado"]:
            motivo_duplicado = resultado["posible_duplicado"]["motivo"]
        nuevo_nombre = nombre_archivo_destino(archivo.nombre, "TICKETS", motivo_duplicado)
        storage.mover_o_renombrar(archivo.id, cliente["carpeta_tickets_id"], nuevo_nombre)
        guardar_factura_procesada(
            tenant_id=cliente["tenant_id"], cif_empresa_cliente=cliente["cif_empresa_cliente"],
            tipo_documento="ticket", num_factura=ticket_extraido["num_factura"],
            fecha_factura=ticket_extraido["fecha_factura"],
            proveedor_cif=ticket_extraido["proveedor"].get("cif_nif"),
            proveedor_nombre=ticket_extraido["proveedor"]["nombre"],
            total_factura=ticket_extraido["total_factura"], destino="TICKETS",
        )
        log.info("Ticket archivado: %s%s", archivo.nombre,
                  " (posible duplicado)" if motivo_duplicado else "")
        return

    # No es un ticket -> factura completa: Excel del periodo (mes o trimestre) que le corresponde.
    factura = factura_completa

    periodo = periodo_para(cliente["tenant_id"], factura["fecha_factura"])
    nombre_excel = nombre_del_excel(cliente["cif_empresa_cliente"], periodo)

    archivo_excel_existente = storage.buscar_archivo_por_nombre(cliente["carpeta_excel_id"], nombre_excel)
    contenido_existente = storage.descargar_archivo(archivo_excel_existente.id) if archivo_excel_existente else None

    nuevo_contenido, resultado = anadir_factura_a_excel(
        contenido_existente, cif_empresa=cliente["cif_empresa_cliente"],
        nombre_empresa=cliente["nombre_empresa"], periodo=periodo, factura=factura,
    )

    if not resultado["ok"]:
        nuevo_nombre = nombre_archivo_destino(archivo.nombre, "REVISION", resultado["motivo"])
        storage.mover_o_renombrar(archivo.id, cliente["carpeta_revision_id"], nuevo_nombre)
        # --- ARREGLO: registrar también las que van a Revisión, para que el panel las muestre ---
        guardar_factura_procesada(
            tenant_id=cliente["tenant_id"], cif_empresa_cliente=cliente["cif_empresa_cliente"],
            tipo_documento="factura_completa", num_factura=factura.get("num_factura") or "(desconocido)",
            fecha_factura=factura.get("fecha_factura") or datetime.now(timezone.utc).strftime("%d/%m/%Y"),
            proveedor_cif=factura.get("emisor", {}).get("cif_nif"),
            proveedor_nombre=factura.get("emisor", {}).get("nombre") or "(desconocido)",
            total_factura=factura.get("total_factura") or 0, destino="REVISION", motivo=resultado["motivo"],
        )
        log.info("Factura a revisión (%s): %s", resultado["motivo"], archivo.nombre)
    else:
        storage.subir_archivo(cliente["carpeta_excel_id"], nombre_excel, nuevo_contenido)
        storage.mover_o_renombrar(archivo.id, cliente.get("carpeta_procesadas_id"), None)
        guardar_factura_procesada(
            tenant_id=cliente["tenant_id"], cif_empresa_cliente=cliente["cif_empresa_cliente"],
            tipo_documento="factura_completa", num_factura=factura["num_factura"],
            fecha_factura=factura["fecha_factura"],
            proveedor_cif=factura["emisor"].get("cif_nif"), proveedor_nombre=factura["emisor"]["nombre"],
            total_factura=factura["total_factura"], destino="PROCESADA",
        )
        log.info("Factura procesada correctamente: %s", archivo.nombre)


def ciclo_de_sondeo():
    try:
        tenants = obtener_tenants_activos()
    except Exception:
        log.exception("Error obteniendo tenants activos")
        return

    for cliente in tenants:
        try:
            if proveedor_almacenamiento_activo(cliente["tenant_id"]) != "onedrive":
                continue  # esta gestoría guarda ya en Google Drive
            tokens = refrescar_token(cliente["refresh_token"])
            storage = obtener_almacenamiento("onedrive", access_token=tokens["access_token"])

            archivos_nuevos = storage.listar_archivos_nuevos(
                carpeta_id=cliente["carpeta_facturas_id"], desde=cliente.get("ultima_revision_iso"),
            )
            log.info("Tenant %s / empresa %s: %d archivo(s) nuevo(s)",
                      cliente["tenant_id"], cliente["cif_empresa_cliente"], len(archivos_nuevos))

            facturas_ya_registradas = obtener_facturas_ya_registradas(
                cliente["tenant_id"], cliente["cif_empresa_cliente"],
            )

            for archivo in archivos_nuevos:
                try:
                    procesar_archivo(storage, archivo, cliente, facturas_ya_registradas)
                except Exception:
                    log.exception("Error procesando el archivo %s (tenant %s)", archivo.nombre, cliente["tenant_id"])
                    continue

            actualizar_ultima_revision(cliente["_empresa_cliente_id"])

        except Exception:
            log.exception("Error procesando el tenant %s", cliente.get("tenant_id"))
            continue


def ejecutar_en_bucle():
    log.info("Arrancando sondeo periódico cada %d segundos", INTERVALO_SEGUNDOS)
    while True:
        inicio = datetime.now(timezone.utc)
        ciclo_de_sondeo()
        duracion = (datetime.now(timezone.utc) - inicio).total_seconds()
        espera = max(0, INTERVALO_SEGUNDOS - duracion)
        log.info("Ciclo completado en %.1fs, esperando %.1fs hasta el siguiente", duracion, espera)
        time.sleep(espera)


if __name__ == "__main__":
    ejecutar_en_bucle()
