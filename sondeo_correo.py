# -*- coding: utf-8 -*-
"""Revisa cada pocos minutos el Gmail de cada gestoría y pasa los adjuntos por el proceso común."""
import logging
import time

from almacenamiento import obtener_almacenamiento
from autenticacion_google import ErrorAutorizacionGoogle, refrescar_token as refrescar_token_google
from autenticacion_onedrive import refrescar_token as refrescar_token_ms
from basededatos import (correo_ya_procesado, guardar_estado_correo, marcar_correo_procesado,
                         obtener_estado_correo, obtener_refresh_token, tenants_con_correo)
from lector_gmail import LectorGmail
from procesamiento import procesar_documento

log = logging.getLogger("sondeo_correo")

INTERVALO_SEGUNDOS = 5 * 60
DIAS_PRIMERA_LECTURA = 3
MARGEN_SEGUNDOS = 3600


def _procesar_tenant(tenant_id, lector=None, storage=None):
    if lector is None or storage is None:
        refresh_gmail = obtener_refresh_token(tenant_id, "gmail")
        refresh_onedrive = obtener_refresh_token(tenant_id, "onedrive")
        if not refresh_gmail or not refresh_onedrive:
            return
        try:
            token_gmail = refrescar_token_google(refresh_gmail)["access_token"]
        except ErrorAutorizacionGoogle as e:
            guardar_estado_correo(tenant_id, error=str(e))
            return
        lector = LectorGmail(token_gmail)
        storage = obtener_almacenamiento("onedrive", access_token=refrescar_token_ms(refresh_onedrive)["access_token"])

    punto_actual = obtener_estado_correo(tenant_id)["ultimo_mensaje_ts"] or int(time.time()) - DIAS_PRIMERA_LECTURA * 86400
    ids = lector.mensajes_nuevos(max(0, punto_actual - MARGEN_SEGUNDOS))
    log.info("Correo %s: %d mensajes con adjunto desde el punto de lectura", tenant_id, len(ids))

    max_ok, primer_fallo = None, None
    for mensaje_id in ids:
        if correo_ya_procesado(tenant_id, mensaje_id):
            continue
        fecha = None
        try:
            fecha, adjuntos = lector.adjuntos_utiles(mensaje_id)
            log.info("Correo %s: mensaje %s con %d adjuntos útiles", tenant_id, mensaje_id, len(adjuntos))
            for nombre, contenido in adjuntos:
                resultado = procesar_documento(storage, tenant_id, contenido, nombre)
                log.info("Correo %s: '%s' -> %s", tenant_id, nombre, (resultado or {}).get("accion"))
            marcar_correo_procesado(tenant_id, mensaje_id)
            max_ok = max(max_ok or 0, fecha)
        except Exception:
            log.exception("Fallo procesando correo %s (se reintentará)", mensaje_id)
            f = fecha or punto_actual
            primer_fallo = f if primer_fallo is None else min(primer_fallo, f)

    candidato = max_ok if max_ok is not None else punto_actual
    if primer_fallo is not None:
        candidato = min(candidato, primer_fallo - 1)
    guardar_estado_correo(tenant_id, ultimo_mensaje_ts=max(punto_actual, candidato), error=None)


def ciclo_correo():
    tenants = tenants_con_correo()
    log.info("Ciclo de correo: %d gestorías con Gmail y OneDrive conectados", len(tenants))
    for tenant_id in tenants:
        try:
            _procesar_tenant(tenant_id)
        except Exception:
            log.exception("Error en el correo de la gestoría %s", tenant_id)


def ejecutar_en_bucle():
    while True:
        ciclo_correo()
        time.sleep(INTERVALO_SEGUNDOS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ejecutar_en_bucle()
