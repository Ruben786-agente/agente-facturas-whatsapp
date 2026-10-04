# -*- coding: utf-8 -*-
"""
Receptor de webhooks de WhatsApp Cloud API (Meta).
"""

import hashlib
import hmac
import logging
import os
import threading
from datetime import datetime, timezone

import requests
from flask import Blueprint, request, abort

from basededatos import (
    resolver_tenant_por_phone_number_id, resolver_empresa_cliente_por_cif,
    obtener_carpeta_sin_identificar, obtener_refresh_token_onedrive, guardar_factura_procesada,
)
from clasificador_documentos import es_ticket, nombre_archivo_destino, procesar_ticket
from almacenamiento import obtener_almacenamiento
from autenticacion_onedrive import refrescar_token
from generar_excel_mieos import anadir_factura_a_excel
from periodo_fiscal import calcular_periodo_trimestral, periodo_a_slug
from extraccion_ia import extraer_factura, factura_a_ticket_ligero

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("webhook_whatsapp")

GRAPH_BASE = "https://graph.facebook.com/v21.0"

bp_whatsapp = Blueprint("whatsapp", __name__)


@bp_whatsapp.route("/webhook/whatsapp", methods=["GET"])
def verificar_webhook():
    modo = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if modo == "subscribe" and token == os.environ["WHATSAPP_VERIFY_TOKEN"]:
        return challenge, 200
    return "Verificación fallida", 403


def _firma_valida(payload_bytes, firma_header):
    if not firma_header or not firma_header.startswith("sha256="):
        return False
    secreto = os.environ["WHATSAPP_APP_SECRET"].encode()
    esperado = hmac.new(secreto, payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={esperado}", firma_header)


@bp_whatsapp.route("/webhook/whatsapp", methods=["POST"])
def recibir_webhook():
    if not _firma_valida(request.get_data(), request.headers.get("X-Hub-Signature-256")):
        log.warning("Firma inválida en webhook entrante -- descartado")
        abort(403)
    payload = request.get_json(force=True)
    threading.Thread(target=_procesar_payload, args=(payload,), daemon=True).start()
    return "OK", 200


def _procesar_payload(payload):
    try:
        for entrada in payload.get("entry", []):
            for cambio in entrada.get("changes", []):
                valor = cambio.get("value", {})
                phone_number_id = valor.get("metadata", {}).get("phone_number_id")
                for mensaje in valor.get("messages", []):
                    _procesar_mensaje(phone_number_id, mensaje)
    except Exception:
        log.exception("Error procesando payload de WhatsApp")


def _descargar_media(media_id, access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    meta = requests.get(f"{GRAPH_BASE}/{media_id}", headers=headers).json()
    return requests.get(meta["url"], headers=headers).content


def _procesar_mensaje(phone_number_id, mensaje):
    tenant = resolver_tenant_por_phone_number_id(phone_number_id)
    if not tenant:
        log.warning("Mensaje de un phone_number_id no registrado: %s", phone_number_id)
        return

    tipo = mensaje.get("type")
    if tipo not in ("image", "document"):
        log.info("Mensaje de tipo '%s' ignorado (no es una imagen/documento)", tipo)
        return

    media_id = mensaje[tipo]["id"]
    nombre_archivo = mensaje[tipo].get("filename", f"whatsapp_{media_id}.jpg")
    contenido = _descargar_media(media_id, tenant["access_token"])

    refresh_token_onedrive = obtener_refresh_token_onedrive(tenant["tenant_id"])
    if not refresh_token_onedrive:
        log.error("Tenant %s no tiene OneDrive conectado -- no se puede archivar nada", tenant["tenant_id"])
        return
    tokens_onedrive = refrescar_token(refresh_token_onedrive)
    storage = obtener_almacenamiento("onedrive", access_token=tokens_onedrive["access_token"])

    factura_completa = extraer_factura(contenido)

    if es_ticket(factura_completa):
        ticket_extraido = factura_a_ticket_ligero(factura_completa)
        cif_candidato = ticket_extraido["proveedor"].get("cif_nif", "")
        empresa = resolver_empresa_cliente_por_cif(tenant["tenant_id"], [cif_candidato])

        resultado = procesar_ticket(
            ticket_extraido, tenant_id=tenant["tenant_id"],
            empresa_cliente_cif=empresa["cif_nif"] if empresa else "",
            facturas_ya_registradas=[],
        )
        motivo_duplicado = resultado["posible_duplicado"]["motivo"] if resultado["posible_duplicado"] else None
        nuevo_nombre = nombre_archivo_destino(nombre_archivo, "TICKETS", motivo_duplicado)

        carpeta_destino = empresa["carpeta_tickets_id"] if empresa else obtener_carpeta_sin_identificar(tenant["tenant_id"])
        storage.subir_archivo(carpeta_destino, nuevo_nombre, contenido)
        if empresa:
            guardar_factura_procesada(
                tenant_id=tenant["tenant_id"], cif_empresa_cliente=empresa["cif_nif"],
                tipo_documento="ticket", num_factura=ticket_extraido["num_factura"],
                fecha_factura=ticket_extraido["fecha_factura"],
                proveedor_cif=ticket_extraido["proveedor"].get("cif_nif"),
                proveedor_nombre=ticket_extraido["proveedor"]["nombre"],
                total_factura=ticket_extraido["total_factura"], destino="TICKETS",
            )
        log.info("Ticket de WhatsApp archivado en %s%s",
                  "empresa " + empresa["nombre"] if empresa else "carpeta sin identificar",
                  " (posible duplicado)" if motivo_duplicado else "")
        return

    factura = factura_completa
    cifs_candidatos = [factura["emisor"].get("cif_nif", ""), factura["destinatario"].get("cif_nif", "")]
    empresa = resolver_empresa_cliente_por_cif(tenant["tenant_id"], cifs_candidatos)

    if not empresa:
        carpeta_destino = obtener_carpeta_sin_identificar(tenant["tenant_id"])
        storage.subir_archivo(carpeta_destino, nombre_archivo, contenido)
        log.info("Factura de WhatsApp sin empresa-cliente identificada -> carpeta sin identificar")
        return

    periodo = calcular_periodo_trimestral(factura["fecha_factura"])
    nombre_excel = f"Export_{empresa['cif_nif']}_{periodo_a_slug(periodo)}.xlsx"
    archivo_existente = storage.buscar_archivo_por_nombre(empresa["carpeta_excel_id"], nombre_excel)
    contenido_existente = storage.descargar_archivo(archivo_existente.id) if archivo_existente else None

    nuevo_contenido, resultado = anadir_factura_a_excel(
        contenido_existente, cif_empresa=empresa["cif_nif"], nombre_empresa=empresa["nombre"],
        periodo=periodo, factura=factura,
    )

    if not resultado["ok"]:
        nuevo_nombre = nombre_archivo_destino(nombre_archivo, "REVISION", resultado["motivo"])
        storage.subir_archivo(empresa["carpeta_revision_id"], nuevo_nombre, contenido)
        # --- ARREGLO: registrar también las que van a Revisión, para que el panel las muestre ---
        guardar_factura_procesada(
            tenant_id=tenant["tenant_id"], cif_empresa_cliente=empresa["cif_nif"],
            tipo_documento="factura_completa", num_factura=factura.get("num_factura") or "(desconocido)",
            fecha_factura=factura.get("fecha_factura") or datetime.now(timezone.utc).strftime("%d/%m/%Y"),
            proveedor_cif=factura.get("emisor", {}).get("cif_nif"),
            proveedor_nombre=factura.get("emisor", {}).get("nombre") or "(desconocido)",
            total_factura=factura.get("total_factura") or 0, destino="REVISION", motivo=resultado["motivo"],
        )
        log.info("Factura de WhatsApp a Revisión (%s, empresa %s)", resultado["motivo"], empresa["nombre"])
    else:
        storage.subir_archivo(empresa["carpeta_excel_id"], nombre_excel, nuevo_contenido)
        guardar_factura_procesada(
            tenant_id=tenant["tenant_id"], cif_empresa_cliente=empresa["cif_nif"],
            tipo_documento="factura_completa", num_factura=factura["num_factura"],
            fecha_factura=factura["fecha_factura"], proveedor_cif=factura["emisor"].get("cif_nif"),
            proveedor_nombre=factura["emisor"]["nombre"], total_factura=factura["total_factura"],
            destino="PROCESADA",
        )
        log.info("Factura de WhatsApp procesada correctamente para %s", empresa["nombre"])
