# -*- coding: utf-8 -*-
"""Revisa cada pocos minutos el Gmail de cada gestoría y pasa los adjuntos por el proceso común."""
import logging
import time

from autenticacion_google import ErrorAutorizacionGoogle, refrescar_token as refrescar_token_google
from almacenamiento_tenant import storage_para_tenant
from basededatos import (correo_ya_procesado, crear_aviso, guardar_estado_correo, marcar_correo_procesado,
                         obtener_estado_correo, obtener_refresh_token, registrar_intento_fallido, tenants_con_correo)
from lector_gmail import LectorGmail
from procesamiento import procesar_archivo

log = logging.getLogger("sondeo_correo")

INTERVALO_SEGUNDOS = 5 * 60
DIAS_PRIMERA_LECTURA = 3
MARGEN_SEGUNDOS = 3600
MAX_INTENTOS = 3  # un correo que falla 3 veces se aparta y se avisa, para no gastar IA sin fin


def _procesar_tenant(tenant_id, lector=None, storage=None):
    if lector is None or storage is None:
        refresh_gmail = obtener_refresh_token(tenant_id, "gmail")
        if not refresh_gmail:
            return
        try:
            token_gmail = refrescar_token_google(refresh_gmail)["access_token"]
        except ErrorAutorizacionGoogle as e:
            guardar_estado_correo(tenant_id, error=str(e))
            return
        lector = LectorGmail(token_gmail)
        try:
            storage = storage_para_tenant(tenant_id)
        except ErrorAutorizacionGoogle as e:  # Google Drive revocado o caducado
            crear_aviso(tenant_id, "drive_desconectado", f"{e}. Entra en Conexiones y vuelve a conectar Google Drive.")
            return
        if storage is None:
            return

    punto_actual = obtener_estado_correo(tenant_id)["ultimo_mensaje_ts"] or int(time.time()) - DIAS_PRIMERA_LECTURA * 86400
    ids = lector.mensajes_nuevos(max(0, punto_actual - MARGEN_SEGUNDOS))
    pendientes = [m for m in ids if not correo_ya_procesado(tenant_id, m)]
    log.info("Correo %s: %d mensajes con adjunto encontrados, %d por procesar", tenant_id, len(ids), len(pendientes))

    max_ok, primer_fallo = None, None
    for mensaje_id in ids:
        if correo_ya_procesado(tenant_id, mensaje_id):
            log.debug("Correo %s: mensaje %s ya procesado, se salta", tenant_id, mensaje_id)
            continue
        fecha = None
        try:
            fecha, adjuntos = lector.adjuntos_utiles(mensaje_id)
            log.info("Correo %s: mensaje %s con %d adjuntos útiles", tenant_id, mensaje_id, len(adjuntos))
            for nombre, contenido in adjuntos:
                resultados = procesar_archivo(storage, tenant_id, contenido, nombre)
                log.info("Correo %s: '%s' -> %s", tenant_id, nombre, [(r or {}).get("accion") for r in resultados])
            marcar_correo_procesado(tenant_id, mensaje_id)
            max_ok = max(max_ok or 0, fecha)
        except Exception as e:
            intentos = registrar_intento_fallido(tenant_id, mensaje_id, f"{type(e).__name__}: {e}")
            f = fecha or punto_actual
            if intentos >= MAX_INTENTOS:
                log.exception("Correo %s: falló %d veces; se aparta y se avisa a la gestoría", mensaje_id, intentos)
                crear_aviso(tenant_id, "correo_fallido",
                            "No se ha podido procesar un correo después de 3 intentos y se ha dejado de reintentar. "
                            "Revisa en tu Gmail el correo con facturas de esa fecha y súbelas a mano si hace falta. "
                            f"({type(e).__name__})")
                marcar_correo_procesado(tenant_id, mensaje_id)
                max_ok = max(max_ok or 0, f)
            else:
                log.exception("Fallo procesando correo %s (intento %d de %d)", mensaje_id, intentos, MAX_INTENTOS)
                primer_fallo = f if primer_fallo is None else min(primer_fallo, f)

    candidato = max_ok if max_ok is not None else punto_actual
    if primer_fallo is not None:
        candidato = min(candidato, primer_fallo - 1)
    guardar_estado_correo(tenant_id, ultimo_mensaje_ts=max(punto_actual, candidato), error=None)


def ciclo_correo():
    tenants = tenants_con_correo()
    log.info("Ciclo de correo: %d gestorías con Gmail y almacenamiento conectados", len(tenants))
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
