# -*- coding: utf-8 -*-
"""Acceso a Microsoft: OneDrive (archivos) y Outlook / Microsoft 365 (correo). Son dos autorizaciones distintas con la misma app."""
import os
import msal

SCOPES = ["Files.ReadWrite.All", "User.Read"]
SCOPES_CORREO = ["Mail.Read", "User.Read"]


class ErrorAutorizacionMicrosoft(ValueError):
    """El acceso de la gestoría ya no vale (lo revocó, caducó o cambió la contraseña): hay que volver a autorizar."""


def _config():
    return {
        "client_id": os.environ["AZURE_CLIENT_ID"],
        "client_secret": os.environ["AZURE_CLIENT_SECRET"],
        "authority": f"https://login.microsoftonline.com/{os.environ.get('AZURE_TENANT_ID', 'common')}",
        "redirect_uri": os.environ["AZURE_REDIRECT_URI"],
    }


def _app_confidencial():
    cfg = _config()
    return msal.ConfidentialClientApplication(client_id=cfg["client_id"], client_credential=cfg["client_secret"], authority=cfg["authority"])


def generar_url_autorizacion(state: str, scopes=None) -> str:
    app = _app_confidencial()
    return app.get_authorization_request_url(scopes=scopes or SCOPES, state=state, redirect_uri=_config()["redirect_uri"])


def procesar_callback(code: str, scopes=None) -> dict:
    app = _app_confidencial()
    resultado = app.acquire_token_by_authorization_code(code=code, scopes=scopes or SCOPES, redirect_uri=_config()["redirect_uri"])
    if "error" in resultado:
        raise ValueError(f"Error de autenticación: {resultado.get('error_description', resultado['error'])}")
    return resultado


def refrescar_token(refresh_token: str, scopes=None, servicio: str = "OneDrive") -> dict:
    app = _app_confidencial()
    resultado = app.acquire_token_by_refresh_token(refresh_token, scopes=scopes or SCOPES)
    if "error" in resultado:
        if resultado.get("error") in ("invalid_grant", "interaction_required"):
            raise ErrorAutorizacionMicrosoft(f"{servicio} desconectado: hay que volver a autorizar el acceso")
        raise ValueError(f"No se pudo renovar el token: {resultado.get('error_description', resultado['error'])}")
    return resultado
