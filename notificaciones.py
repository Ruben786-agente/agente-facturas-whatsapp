# -*- coding: utf-8 -*-
"""
Avisos por correo electrónico a la gestoría (así no depende de abrir el panel para enterarse).

Se envían con Resend (https://resend.com) por su API web: el plan gratuito de Render bloquea el envío
por SMTP clásico. Variables de entorno:
    RESEND_API_KEY     -- clave de la API de Resend. Si falta, no se envía nada (el resto sigue igual).
    EMAIL_REMITENTE    -- por ejemplo  Agente Facturas <avisos@sudominio.com>  (el dominio debe estar verificado en Resend)
    URL_PUBLICA        -- dirección del panel, para el botón del correo
    AVISOS_POR_CORREO  -- poner 0 para desactivarlos todos

Cada tipo de aviso se manda como máximo una vez cada 24 h por gestoría (no se inunda el buzón), y los
avisos del plazo del modelo 303 se mandan una sola vez por hito (a 7, 3 y 1 días).
"""

import html
import logging
import os
from datetime import date, datetime, timedelta, timezone

import requests

log = logging.getLogger("notificaciones")

API_RESEND = "https://api.resend.com/emails"

ASUNTOS = {
    "drive_desconectado": "Hay que volver a conectar su almacenamiento",
    "correo_fallido": "Un correo con facturas no se ha podido procesar",
    "carpeta_recreada": "El agente ha recreado una carpeta que faltaba",
    "correo_desconectado": "Hay que volver a conectar su correo",
}


def _activadas():
    return os.environ.get("AVISOS_POR_CORREO", "1") != "0" and bool(os.environ.get("RESEND_API_KEY"))


def _url_panel():
    return os.environ.get("URL_PUBLICA", "https://agente-facturas-whatsapp.onrender.com").rstrip("/") + "/panel"


def _cuerpo_html(titulo, parrafos):
    ps = "".join(f'<p style="margin:0 0 14px;color:#4F5B67;font-size:15px;line-height:1.55;">{html.escape(p)}</p>' for p in parrafos)
    return (
        '<div style="background:#F4F6F7;padding:28px 16px;font-family:Helvetica,Arial,sans-serif;">'
        '<div style="max-width:560px;margin:0 auto;background:#fff;border:1px solid #E1E6EA;border-radius:10px;padding:28px;">'
        '<div style="font-family:Georgia,serif;font-size:19px;font-weight:600;color:#17212B;margin-bottom:18px;">Agente Facturas</div>'
        f'<h1 style="font-family:Georgia,serif;font-weight:500;font-size:24px;line-height:1.2;color:#17212B;margin:0 0 16px;">{html.escape(titulo)}</h1>'
        f'{ps}'
        f'<p style="margin:22px 0 0;"><a href="{html.escape(_url_panel())}" style="background:#1E4D5C;color:#fff;text-decoration:none;'
        'padding:11px 20px;border-radius:7px;font-size:15px;display:inline-block;">Abrir el panel</a></p>'
        '</div></div>'
    )


def enviar_correo(destino, asunto, titulo, parrafos):
    """Envía un correo. Nunca lanza una excepción: devuelve True si Resend lo aceptó."""
    if not _activadas():
        log.info("Avisos por correo no activados: no se envía '%s'", asunto)
        return False
    remitente = os.environ.get("EMAIL_REMITENTE", "Agente Facturas <onboarding@resend.dev>")
    try:
        r = requests.post(
            API_RESEND, timeout=20,
            headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}", "User-Agent": "agente-facturas/1.0"},
            json={"from": remitente, "to": [destino], "subject": f"Agente Facturas: {asunto}",
                  "html": _cuerpo_html(titulo, parrafos), "text": "\n\n".join([titulo] + list(parrafos)) + f"\n\n{_url_panel()}"},
        )
        if r.status_code >= 300:
            log.warning("Resend rechazó el correo (%s): %s", r.status_code, r.text[:300])
            return False
        return True
    except Exception:
        log.exception("No se pudo enviar el correo '%s'", asunto)
        return False


def notificar(tenant_id, clave, asunto, titulo, parrafos, cada_horas=24):
    """Manda un aviso a la gestoría salvo que ya se mandara uno con la misma clave hace menos de `cada_horas`."""
    from basededatos import email_de_gestoria, notificacion_reciente, registrar_notificacion
    if not _activadas():
        return False
    destino = email_de_gestoria(tenant_id)
    if not destino or notificacion_reciente(tenant_id, clave, cada_horas):
        return False
    if enviar_correo(destino, asunto, titulo, parrafos):
        registrar_notificacion(tenant_id, clave)
        return True
    return False


def notificar_aviso(tenant_id, tipo, mensaje):
    """Para los avisos del panel que son un problema (los informativos no se mandan por correo)."""
    from basededatos import TIPOS_AVISO_INFORMATIVO
    if tipo in TIPOS_AVISO_INFORMATIVO:
        return False
    asunto = ASUNTOS.get(tipo, "Aviso del agente")
    return notificar(tenant_id, f"aviso-{tipo}", asunto, asunto, [mensaje, "Puede ver el detalle y resolverlo en el panel."])


def notificar_correo_desconectado(tenant_id, motivo):
    asunto = ASUNTOS["correo_desconectado"]
    return notificar(tenant_id, "correo-error", asunto, asunto,
                     [motivo, "Mientras tanto el agente no puede leer los correos nuevos. Entre en «Conexiones y suscripción» "
                              "y pulse «Volver a autorizar»; los correos recibidos mientras tanto se leerán al reconectar."])


def _hito(dias):
    """7, 3 o 1 según lo cerca que esté el plazo (None si falta más de una semana)."""
    return 1 if dias <= 1 else 3 if dias <= 3 else 7 if dias <= 7 else None


def revisar_plazos(hoy=None):
    """
    Una vez al día: a las gestorías con algo pendiente (revisiones, documentos sin identificar o clientes sin facturas)
    se les avisa a 7, 3 y 1 días del plazo del modelo 303. Si no hay nada pendiente no se manda nada.
    """
    from basededatos import (notificacion_reciente, obtener_resumen_panel, registrar_notificacion,
                             tenants_con_correo, TENANT_GLOBAL)
    if not _activadas():
        return 0
    hoy = hoy or date.today()
    marca = f"chequeo-plazos-{hoy.isoformat()}"
    if notificacion_reciente(TENANT_GLOBAL, marca, 24):
        return 0
    registrar_notificacion(TENANT_GLOBAL, marca)
    enviados = 0
    for tenant_id in tenants_con_correo():
        try:
            datos = obtener_resumen_panel(tenant_id, hoy_fecha=hoy)
            plazo = datos["plazo"]
            hito = _hito(plazo["dias"]) if plazo else None
            if hito is None:
                continue
            pendientes = datos["resumen"]["REVISION"] + datos["resumen"]["SIN_IDENTIFICAR"]
            sin = plazo.get("sin_facturas") or []
            if not pendientes and not sin:
                continue
            t = f'{plazo["trimestre"]}T {plazo["anio"]}'
            cuando = "vence hoy" if plazo["dias"] == 0 else "queda 1 día" if plazo["dias"] == 1 else f'quedan {plazo["dias"]} días'
            lineas = [f'Para el IVA del {t} (modelo 303) {cuando}, hasta el {plazo["plazo"].strftime("%d/%m/%Y")}.']
            if pendientes:
                r, si = datos["resumen"]["REVISION"], datos["resumen"]["SIN_IDENTIFICAR"]
                lineas.append(f'Tiene {r} {"factura" if r == 1 else "facturas"} en revisión y {si} {"documento" if si == 1 else "documentos"} sin identificar.')
            if sin:
                lista = ", ".join(sin[:8]) + (f" y {len(sin) - 8} más" if len(sin) > 8 else "")
                lineas.append(("Este cliente todavía no ha enviado facturas de este trimestre: " if len(sin) == 1
                               else "Estos clientes todavía no han enviado facturas de este trimestre: ")
                              + lista + ("" if lista.endswith(".") else "."))
            titulo = f'Plazo del modelo 303: {cuando}'
            if notificar(tenant_id, f'303-{plazo["anio"]}-{plazo["trimestre"]}-{hito}', titulo, titulo, lineas, cada_horas=24 * 90):
                enviados += 1
        except Exception:
            log.exception("No se pudo revisar el plazo de la gestoría %s", tenant_id)
    return enviados
