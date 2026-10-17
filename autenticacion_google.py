# -*- coding: utf-8 -*-
"""Acceso de solo lectura al Gmail de la gestoría (OAuth de Google)."""
import os
from urllib.parse import urlencode

import requests

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]  # Gmail: solo lectura
SCOPES_DRIVE = ["https://www.googleapis.com/auth/drive.file"]  # Drive: solo lo que crea el agente
URL_AUTORIZACION = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"


class ErrorAutorizacionGoogle(Exception):
    pass


def _config():
    return {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "redirect_uri": os.environ["GOOGLE_REDIRECT_URI"],
    }


def generar_url_autorizacion(state: str, scopes=None) -> str:
    cfg = _config()
    params = {
        "client_id": cfg["client_id"], "redirect_uri": cfg["redirect_uri"], "response_type": "code",
        "scope": " ".join(scopes or SCOPES), "state": state,
        "access_type": "offline",   # para recibir refresh token
        "prompt": "consent",        # fuerza a devolver refresh token siempre
    }
    return f"{URL_AUTORIZACION}?{urlencode(params)}"


def procesar_callback(code: str) -> dict:
    cfg = _config()
    r = requests.post(URL_TOKEN, data={
        "code": code, "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
        "redirect_uri": cfg["redirect_uri"], "grant_type": "authorization_code",
    }, timeout=30)
    datos = r.json()
    if r.status_code != 200 or "error" in datos:
        raise ErrorAutorizacionGoogle(f"Error de autenticación con Google: {datos.get('error_description', datos.get('error'))}")
    return datos


def refrescar_token(refresh_token: str, servicio: str = "Gmail") -> dict:
    cfg = _config()
    r = requests.post(URL_TOKEN, data={
        "refresh_token": refresh_token, "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"], "grant_type": "refresh_token",
    }, timeout=30)
    datos = r.json()
    if r.status_code != 200 or "error" in datos:
        if datos.get("error") == "invalid_grant":
            raise ErrorAutorizacionGoogle(f"{servicio} desconectado: hay que volver a autorizar el acceso")
        raise ErrorAutorizacionGoogle(f"No se pudo renovar el acceso a {servicio}: {datos.get('error_description', datos.get('error'))}")
    return datos


def revocar_token(refresh_token: str) -> None:
    """Pide a Google que anule el acceso. Si falla no pasa nada: ya se ha borrado de nuestro lado."""
    try:
        requests.post("https://oauth2.googleapis.com/revoke", data={"token": refresh_token}, timeout=15)
    except Exception:
        pass
