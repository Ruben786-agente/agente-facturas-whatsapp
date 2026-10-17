# -*- coding: utf-8 -*-
"""
Dónde guarda cada gestoría sus archivos: OneDrive o Google Drive (solo uno a la vez, porque
los ids de las carpetas son de cada servicio). Todo el código que necesita archivar algo
pide el almacenamiento aquí en vez de asumir OneDrive.
"""

from almacenamiento import obtener_almacenamiento
from autenticacion_google import refrescar_token as refrescar_token_google
from autenticacion_onedrive import refrescar_token as refrescar_token_ms
from basededatos import obtener_refresh_token, proveedor_almacenamiento_activo

NOMBRES = {"onedrive": "OneDrive", "gdrive": "Google Drive"}


def proveedor_almacenamiento(tenant_id):
    """'onedrive', 'gdrive' o None si aún no ha conectado ninguno."""
    return proveedor_almacenamiento_activo(tenant_id)


def storage_para_tenant(tenant_id):
    """
    Almacenamiento listo para usar (con el acceso ya renovado), o None si no hay ninguno conectado.
    Con Google Drive puede lanzar ErrorAutorizacionGoogle si la gestoría revocó el permiso o caducó.
    """
    proveedor = proveedor_almacenamiento(tenant_id)
    if proveedor == "onedrive":
        refresh = obtener_refresh_token(tenant_id, "onedrive")
        return obtener_almacenamiento("onedrive", access_token=refrescar_token_ms(refresh)["access_token"])
    if proveedor == "gdrive":
        refresh = obtener_refresh_token(tenant_id, "gdrive")
        return obtener_almacenamiento("gdrive", access_token=refrescar_token_google(refresh, servicio="Google Drive")["access_token"])
    return None
