# -*- coding: utf-8 -*-
"""Lee correos nuevos con adjuntos y extrae solo los que pueden ser facturas/tickets."""
import base64

import requests

API = "https://gmail.googleapis.com/gmail/v1/users/me"
MIN_BYTES_IMAGEN = 30_000  # descarta logos y firmas
EXTENSIONES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _ext(nombre):
    n = (nombre or "").lower()
    return next((e for e in EXTENSIONES if n.endswith(e)), None)


class LectorGmail:
    def __init__(self, access_token):
        self._h = {"Authorization": f"Bearer {access_token}"}

    def _get(self, ruta, **params):
        r = requests.get(f"{API}{ruta}", headers=self._h, params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def mensajes_nuevos(self, desde_ts, maximo=200):
        """IDs de correos con adjunto posteriores a desde_ts (segundos epoch)."""
        ids, token = [], None
        while len(ids) < maximo:
            params = {"q": f"has:attachment after:{int(desde_ts)}", "maxResults": min(100, maximo - len(ids))}
            if token:
                params["pageToken"] = token
            datos = self._get("/messages", **params)
            ids += [m["id"] for m in datos.get("messages", [])]
            token = datos.get("nextPageToken")
            if not token:
                break
        return ids

    def mensaje(self, mensaje_id):
        return self._get(f"/messages/{mensaje_id}", format="full")

    def descargar_adjunto(self, mensaje_id, adjunto_id):
        datos = self._get(f"/messages/{mensaje_id}/attachments/{adjunto_id}")
        return base64.urlsafe_b64decode(datos["data"] + "=" * (-len(datos["data"]) % 4))

    def _partes(self, parte):
        yield parte
        for sub in parte.get("parts", []) or []:
            yield from self._partes(sub)

    def adjuntos_utiles(self, mensaje_id):
        """Devuelve (fecha_en_segundos, [(nombre, bytes)]) solo con PDF/JPG/PNG relevantes."""
        msg = self.mensaje(mensaje_id)
        fecha = int(msg.get("internalDate", "0")) // 1000
        resultado = []
        for parte in self._partes(msg.get("payload", {})):
            nombre = parte.get("filename") or ""
            adj_id = (parte.get("body") or {}).get("attachmentId")
            if not nombre or not adj_id:
                continue
            ext = _ext(nombre)
            mime = parte.get("mimeType", "")
            if ext is None:
                continue
            if mime not in ("application/octet-stream", EXTENSIONES[ext], "") and not mime.startswith(("application/", "image/")):
                continue
            cabeceras = {h["name"].lower(): h["value"] for h in parte.get("headers", [])}
            es_imagen = ext != ".pdf"
            if es_imagen and "content-id" in cabeceras:
                continue  # imagen incrustada en el cuerpo (firma, logo)
            if es_imagen and (parte["body"].get("size", 0) < MIN_BYTES_IMAGEN):
                continue
            resultado.append((nombre, self.descargar_adjunto(mensaje_id, adj_id)))
        return fecha, resultado
