# -*- coding: utf-8 -*-
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import requests


@dataclass
class ArchivoRemoto:
    id: str
    nombre: str
    carpeta_id: str
    tamano_bytes: int
    fecha_modificacion: str


class AlmacenamientoDocumentos(ABC):
    @abstractmethod
    def listar_archivos_nuevos(self, carpeta_id, desde=None): ...
    @abstractmethod
    def descargar_archivo(self, archivo_id): ...
    @abstractmethod
    def mover_o_renombrar(self, archivo_id, carpeta_destino_id, nuevo_nombre): ...
    @abstractmethod
    def subir_archivo(self, carpeta_id, nombre, contenido): ...
    @abstractmethod
    def buscar_archivo_por_nombre(self, carpeta_id, nombre): ...
    @abstractmethod
    def crear_suscripcion_cambios(self, carpeta_id, url_webhook): ...


class OneDriveStorage(AlmacenamientoDocumentos):
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, access_token: str, drive_id: Optional[str] = None):
        self.access_token = access_token
        self.drive_id = drive_id

    def _headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def _drive_prefix(self):
        return f"{self.GRAPH_BASE}/drives/{self.drive_id}" if self.drive_id else f"{self.GRAPH_BASE}/me/drive"

    def listar_archivos_nuevos(self, carpeta_id, desde=None):
        url = f"{self._drive_prefix()}/items/{carpeta_id}/children"
        resp = requests.get(url, headers=self._headers())
        resp.raise_for_status()
        items = resp.json().get("value", [])
        archivos = []
        for item in items:
            if "file" not in item:
                continue
            if desde and item["lastModifiedDateTime"] <= desde:
                continue
            archivos.append(ArchivoRemoto(id=item["id"], nombre=item["name"], carpeta_id=carpeta_id,
                                           tamano_bytes=item["size"], fecha_modificacion=item["lastModifiedDateTime"]))
        return archivos

    def descargar_archivo(self, archivo_id):
        resp = requests.get(f"{self._drive_prefix()}/items/{archivo_id}/content", headers=self._headers())
        resp.raise_for_status()
        return resp.content

    def mover_o_renombrar(self, archivo_id, carpeta_destino_id=None, nuevo_nombre=None):
        body = {}
        if carpeta_destino_id:
            body["parentReference"] = {"id": carpeta_destino_id}
        if nuevo_nombre:
            body["name"] = nuevo_nombre
        if not body:
            return
        resp = requests.patch(f"{self._drive_prefix()}/items/{archivo_id}", headers=self._headers(), json=body)
        resp.raise_for_status()

    def subir_archivo(self, carpeta_id, nombre, contenido):
        url = f"{self._drive_prefix()}/items/{carpeta_id}:/{nombre}:/content"
        resp = requests.put(url, headers={**self._headers(), "Content-Type": "application/octet-stream"}, data=contenido)
        resp.raise_for_status()
        item = resp.json()
        return ArchivoRemoto(id=item["id"], nombre=item["name"], carpeta_id=carpeta_id,
                              tamano_bytes=item["size"], fecha_modificacion=item["lastModifiedDateTime"])

    def buscar_archivo_por_nombre(self, carpeta_id, nombre):
        resp = requests.get(f"{self._drive_prefix()}/items/{carpeta_id}:/{nombre}", headers=self._headers())
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        item = resp.json()
        return ArchivoRemoto(id=item["id"], nombre=item["name"], carpeta_id=carpeta_id,
                              tamano_bytes=item["size"], fecha_modificacion=item["lastModifiedDateTime"])

    def crear_suscripcion_cambios(self, carpeta_id, url_webhook):
        import datetime
        expira = (datetime.datetime.utcnow() + datetime.timedelta(days=29)).isoformat() + "Z"
        body = {"changeType": "updated", "notificationUrl": url_webhook,
                "resource": f"/me/drive/items/{carpeta_id}", "expirationDateTime": expira,
                "clientState": "verificacion_secreta_del_tenant"}
        resp = requests.post(f"{self.GRAPH_BASE}/subscriptions", headers=self._headers(), json=body)
        resp.raise_for_status()
        return resp.json()


def obtener_almacenamiento(proveedor: str, **kwargs) -> AlmacenamientoDocumentos:
    proveedores = {"onedrive": OneDriveStorage}
    if proveedor not in proveedores:
        raise ValueError(f"Proveedor de almacenamiento '{proveedor}' no soportado todavía. Disponibles: {list(proveedores.keys())}")
    return proveedores[proveedor](**kwargs)
