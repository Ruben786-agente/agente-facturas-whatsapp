# -*- coding: utf-8 -*-
import os
import msal

SCOPES = ["Files.ReadWrite.All", "User.Read"]


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


def generar_url_autorizacion(state: str) -> str:
    app = _app_confidencial()
    return app.get_authorization_request_url(scopes=SCOPES, state=state, redirect_uri=_config()["redirect_uri"])


def procesar_callback(code: str) -> dict:
    app = _app_confidencial()
    resultado = app.acquire_token_by_authorization_code(code=code, scopes=SCOPES, redirect_uri=_config()["redirect_uri"])
    if "error" in resultado:
        raise ValueError(f"Error de autenticación: {resultado.get('error_description', resultado['error'])}")
    return resultado


def refrescar_token(refresh_token: str) -> dict:
    app = _app_confidencial()
    resultado = app.acquire_token_by_refresh_token(refresh_token, scopes=SCOPES)
    if "error" in resultado:
        raise ValueError(f"No se pudo renovar el token: {resultado.get('error_description', resultado['error'])}")
    return resultado
