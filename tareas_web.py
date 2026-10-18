# -*- coding: utf-8 -*-
"""
Tareas periódicas disparadas desde fuera.

En el plan gratuito de Render el servicio se duerme si nadie lo visita. Un
servicio externo gratuito (cron-job.org, UptimeRobot...) visita esta dirección
cada pocos minutos: eso despierta el servidor y hace que revise el correo.
La dirección está protegida con una clave (variable TAREAS_CLAVE).
"""

import hmac
import logging
import os
import threading

from flask import Blueprint, request

log = logging.getLogger("tareas_web")
bp_tareas = Blueprint("tareas", __name__)

_candado = threading.Lock()
_en_marcha = False


def _ejecutar_ciclo():
    global _en_marcha
    try:
        from sondeo_correo import ciclo_correo
        ciclo_correo()
    except Exception:
        log.exception("Fallo en el ciclo de correo")
    finally:
        with _candado:
            _en_marcha = False


@bp_tareas.route("/tareas/correo")
def tarea_correo():
    esperada = os.environ.get("TAREAS_CLAVE", "")
    # La clave debe viajar en una cabecera (X-Clave): así no aparece en los logs de Render.
    # Mientras se migra, la dirección con ?clave=... sigue funcionando; ponga CLAVE_EN_URL=0 para apagarla.
    recibida = request.headers.get("X-Clave", "")
    if not recibida and os.environ.get("CLAVE_EN_URL", "1") != "0":
        recibida = request.args.get("clave", "")
    if not esperada or not hmac.compare_digest(esperada.encode(), recibida.encode()):
        return "No autorizado", 403

    global _en_marcha
    with _candado:
        if _en_marcha:
            return "Ya hay una revisión en marcha", 202
        _en_marcha = True
    # Se responde enseguida (el servicio externo no espera) y se trabaja en segundo plano.
    threading.Thread(target=_ejecutar_ciclo, daemon=True).start()
    return "Revisión iniciada", 202
