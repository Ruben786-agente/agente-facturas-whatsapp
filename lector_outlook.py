# -*- coding: utf-8 -*-
"""Lee correos nuevos con adjuntos de Outlook / Microsoft 365 (Microsoft Graph) y extrae solo los que pueden ser facturas/tickets.
Misma interfaz que LectorGmail: mensajes_nuevos(desde_ts) y adjuntos_utiles(mensaje_id)."""
import base64
from datetime import datetime, timezone

import requests

from lector_gmail import EXTENSIONES, MIN_BYTES_IMAGEN, _ext

API = "https://graph.microsoft.com/v1.0/me"
CARPETAS_EXCLUIDAS = ("sentitems", "drafts", "deleteditems", "junkemail", "outbox")


def _a_epoch(texto):
    return int(datetime.fromisoformat((texto or "").replace("Z", "+00:00")).timestamp()) if texto else 0


class LectorOutlook:
    def __init__(self, access_token):
        # IdType inmutable: el id del correo no cambia si el usuario lo mueve de carpeta.
        self._h = {"Authorization": f"Bearer {access_token}", "Prefer": 'IdType="ImmutableId"'}
        self._excluidas = None
        self._propio = None

    def _get(self, ruta_o_url, **params):
        url = ruta_o_url if ruta_o_url.startswith("http") else f"{API}{ruta_o_url}"
        r = requests.get(url, headers=self._h, params=params or None, timeout=60)
        r.raise_for_status()
        return r.json()

    def _carpetas_excluidas(self):
        if self._excluidas is None:
            ids = set()
            for nombre in CARPETAS_EXCLUIDAS:
                try:
                    ids.add(self._get(f"/mailFolders/{nombre}", **{"$select": "id"})["id"])
                except requests.HTTPError:
                    pass
            self._excluidas = ids
        return self._excluidas

    def _direccion_propia(self):
        if self._propio is None:
            datos = self._get("", **{"$select": "mail,userPrincipalName"})
            self._propio = (datos.get("mail") or datos.get("userPrincipalName") or "").lower()
        return self._propio

    def mensajes_nuevos(self, desde_ts, maximo=200):
        """IDs de correos RECIBIDOS con adjunto posteriores a desde_ts (segundos epoch).
        Se ignoran enviados, borradores, eliminados, correo no deseado y los enviados por la propia cuenta."""
        desde = datetime.fromtimestamp(int(desde_ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        excluidas, propio = self._carpetas_excluidas(), self._direccion_propia()
        encontrados, url, params = [], "/messages", {
            "$filter": f"hasAttachments eq true and receivedDateTime ge {desde}",
            "$select": "id,receivedDateTime,parentFolderId,isDraft,from", "$top": 100,
        }
        while url and len(encontrados) < maximo:
            datos = self._get(url, **(params or {}))
            params = None  # las páginas siguientes ya traen todo en la dirección
            for m in datos.get("value", []):
                remitente = (((m.get("from") or {}).get("emailAddress") or {}).get("address") or "").lower()
                if m.get("isDraft") or m.get("parentFolderId") in excluidas or (propio and remitente == propio):
                    continue
                encontrados.append((_a_epoch(m.get("receivedDateTime")), m["id"]))
            url = datos.get("@odata.nextLink")
        encontrados.sort()
        return [i for _, i in encontrados[:maximo]]

    def adjuntos_utiles(self, mensaje_id):
        """Devuelve (fecha_en_segundos, [(nombre, bytes)]) solo con PDF/JPG/PNG relevantes."""
        msg = self._get(f"/messages/{mensaje_id}", **{"$select": "receivedDateTime"})
        fecha = _a_epoch(msg.get("receivedDateTime"))
        resultado, url = [], f"/messages/{mensaje_id}/attachments"
        params = {"$select": "id,name,contentType,size,isInline,contentBytes"}
        while url:
            datos = self._get(url, **(params or {}))
            params = None
            for adj in datos.get("value", []):
                if adj.get("@odata.type") != "#microsoft.graph.fileAttachment":
                    continue  # p. ej. un correo adjunto o un enlace a la nube
                nombre = adj.get("name") or ""
                ext = _ext(nombre)
                if ext is None:
                    continue
                if ext != ".pdf" and (adj.get("isInline") or adj.get("size", 0) < MIN_BYTES_IMAGEN):
                    continue  # logos y firmas
                contenido = adj.get("contentBytes")
                if contenido:
                    resultado.append((nombre, base64.b64decode(contenido)))
                else:  # adjuntos grandes: Graph no incluye el contenido en la lista
                    r = requests.get(f"{API}/messages/{mensaje_id}/attachments/{adj['id']}/$value", headers=self._h, timeout=120)
                    r.raise_for_status()
                    resultado.append((nombre, r.content))
            url = datos.get("@odata.nextLink")
        return fecha, resultado
