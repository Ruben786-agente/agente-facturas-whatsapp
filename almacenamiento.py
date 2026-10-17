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
    @abstractmethod
    def crear_carpeta(self, carpeta_padre_id, nombre): ...
    @abstractmethod
    def crear_enlace_subida(self, carpeta_id): ...

    def eliminar_archivo(self, archivo_id):
        raise NotImplementedError

    def obtener_enlace(self, elemento_id):
        """Dirección web para abrir un archivo o carpeta en el navegador."""
        raise NotImplementedError


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

    def eliminar_archivo(self, archivo_id):
        resp = requests.delete(f"{self._drive_prefix()}/items/{archivo_id}", headers=self._headers())
        if resp.status_code != 404:
            resp.raise_for_status()

    def obtener_enlace(self, elemento_id):
        resp = requests.get(f"{self._drive_prefix()}/items/{elemento_id}?select=webUrl", headers=self._headers())
        resp.raise_for_status()
        return resp.json()["webUrl"]

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

    def crear_carpeta(self, carpeta_padre_id, nombre):
        """
        Crea una carpeta dentro de otra y devuelve su id. Es idempotente: si ya
        existe una con ese nombre, devuelve el id de la existente en vez de
        fallar (así repetir el alta no duplica carpetas).
        carpeta_padre_id puede ser "root" para crearla en la raíz del OneDrive.
        """
        url = f"{self._drive_prefix()}/items/{carpeta_padre_id}/children"
        body = {"name": nombre, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
        resp = requests.post(url, headers=self._headers(), json=body)
        if resp.status_code == 409:  # ya existe -> la buscamos
            existente = requests.get(
                f"{self._drive_prefix()}/items/{carpeta_padre_id}:/{nombre}", headers=self._headers()
            )
            existente.raise_for_status()
            return existente.json()["id"]
        resp.raise_for_status()
        return resp.json()["id"]

    def crear_enlace_subida(self, carpeta_id):
        """
        Enlace con el que otra persona (el cliente de la gestoría) puede subir
        archivos a esa carpeta sin tener cuenta. Devuelve None si no se puede:
        algunas empresas bloquean los enlaces anónimos por política de
        seguridad de Microsoft 365.
        """
        try:
            resp = requests.post(
                f"{self._drive_prefix()}/items/{carpeta_id}/createLink",
                headers=self._headers(), json={"type": "edit", "scope": "anonymous"},
            )
            resp.raise_for_status()
            return resp.json()["link"]["webUrl"]
        except Exception:
            return None

    def crear_suscripcion_cambios(self, carpeta_id, url_webhook):
        import datetime
        expira = (datetime.datetime.utcnow() + datetime.timedelta(days=29)).isoformat() + "Z"
        body = {"changeType": "updated", "notificationUrl": url_webhook,
                "resource": f"/me/drive/items/{carpeta_id}", "expirationDateTime": expira,
                "clientState": "verificacion_secreta_del_tenant"}
        resp = requests.post(f"{self.GRAPH_BASE}/subscriptions", headers=self._headers(), json=body)
        resp.raise_for_status()
        return resp.json()


class GoogleDriveStorage(AlmacenamientoDocumentos):
    """
    Google Drive con el permiso 'drive.file': el agente solo ve las carpetas y archivos que
    él mismo crea (la carpeta "Agente Facturas" y lo de dentro), no el resto del Drive.
    """
    API = "https://www.googleapis.com/drive/v3"
    API_SUBIDA = "https://www.googleapis.com/upload/drive/v3"
    TIPO_CARPETA = "application/vnd.google-apps.folder"
    TIPOS = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

    def __init__(self, access_token: str, http=None):
        self.access_token = access_token
        self._http = http or requests

    def _headers(self, extra=None):
        return {"Authorization": f"Bearer {self.access_token}", **(extra or {})}

    @staticmethod
    def _q(texto):
        return texto.replace("\\", "\\\\").replace("'", "\\'")

    def _archivo(self, item, carpeta_id):
        return ArchivoRemoto(id=item["id"], nombre=item["name"], carpeta_id=carpeta_id,
                             tamano_bytes=int(item.get("size") or 0), fecha_modificacion=item.get("modifiedTime", ""))

    def _listar(self, q, campos="files(id,name,size,modifiedTime)"):
        resp = self._http.get(f"{self.API}/files", headers=self._headers(),
                              params={"q": q, "fields": campos, "pageSize": 100, "spaces": "drive"})
        resp.raise_for_status()
        return resp.json().get("files", [])

    def _comprobar_carpeta(self, carpeta_id):
        """Si la carpeta no existe o está en la papelera, falla como un 404 (así se vuelve a crear)."""
        if carpeta_id == "root":
            return
        resp = self._http.get(f"{self.API}/files/{carpeta_id}", headers=self._headers(), params={"fields": "trashed"})
        if resp.status_code == 200 and resp.json().get("trashed"):
            falsa = requests.Response()
            falsa.status_code = 404
            raise requests.HTTPError("La carpeta está en la papelera de Google Drive", response=falsa)
        resp.raise_for_status()

    def listar_archivos_nuevos(self, carpeta_id, desde=None):
        q = f"'{carpeta_id}' in parents and trashed=false and mimeType != '{self.TIPO_CARPETA}'"
        if desde:
            q += f" and modifiedTime > '{desde}'"
        return [self._archivo(i, carpeta_id) for i in self._listar(q)]

    def descargar_archivo(self, archivo_id):
        resp = self._http.get(f"{self.API}/files/{archivo_id}", headers=self._headers(), params={"alt": "media"})
        resp.raise_for_status()
        return resp.content

    def mover_o_renombrar(self, archivo_id, carpeta_destino_id=None, nuevo_nombre=None):
        params, body = {}, {}
        if carpeta_destino_id:
            actual = self._http.get(f"{self.API}/files/{archivo_id}", headers=self._headers(), params={"fields": "parents"})
            actual.raise_for_status()
            params["addParents"] = carpeta_destino_id
            params["removeParents"] = ",".join(actual.json().get("parents", []))
        if nuevo_nombre:
            body["name"] = nuevo_nombre
        if not params and not body:
            return
        resp = self._http.patch(f"{self.API}/files/{archivo_id}", headers=self._headers(), params=params, json=body)
        resp.raise_for_status()

    def subir_archivo(self, carpeta_id, nombre, contenido):
        import json
        import os
        self._comprobar_carpeta(carpeta_id)
        tipo = self.TIPOS.get(os.path.splitext(nombre)[1].lower(), "application/octet-stream")
        existente = self.buscar_archivo_por_nombre(carpeta_id, nombre)
        if existente:  # mismo nombre: se sustituye el contenido, como en OneDrive
            resp = self._http.patch(f"{self.API_SUBIDA}/files/{existente.id}", headers=self._headers({"Content-Type": tipo}),
                                    params={"uploadType": "media", "fields": "id,name,size,modifiedTime"}, data=contenido)
        else:
            marca = "agente_facturas_limite"
            meta = json.dumps({"name": nombre, "parents": [carpeta_id]}).encode("utf-8")
            cuerpo = (f"--{marca}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta +
                      f"\r\n--{marca}\r\nContent-Type: {tipo}\r\n\r\n".encode() + contenido + f"\r\n--{marca}--".encode())
            resp = self._http.post(f"{self.API_SUBIDA}/files", params={"uploadType": "multipart", "fields": "id,name,size,modifiedTime"},
                                   headers=self._headers({"Content-Type": f"multipart/related; boundary={marca}"}), data=cuerpo)
        resp.raise_for_status()
        return self._archivo(resp.json(), carpeta_id)

    def buscar_archivo_por_nombre(self, carpeta_id, nombre):
        q = f"'{carpeta_id}' in parents and name='{self._q(nombre)}' and trashed=false and mimeType != '{self.TIPO_CARPETA}'"
        encontrados = self._listar(q)
        return self._archivo(encontrados[0], carpeta_id) if encontrados else None

    def crear_carpeta(self, carpeta_padre_id, nombre):
        """Idempotente: si ya hay una carpeta con ese nombre dentro de la otra, devuelve la existente."""
        q = f"'{carpeta_padre_id}' in parents and name='{self._q(nombre)}' and trashed=false and mimeType='{self.TIPO_CARPETA}'"
        encontradas = self._listar(q, campos="files(id)")
        if encontradas:
            return encontradas[0]["id"]
        resp = self._http.post(f"{self.API}/files", headers=self._headers(), params={"fields": "id"},
                               json={"name": nombre, "mimeType": self.TIPO_CARPETA, "parents": [carpeta_padre_id]})
        resp.raise_for_status()
        return resp.json()["id"]

    def crear_enlace_subida(self, carpeta_id):
        return None  # con el permiso drive.file no se pueden crear enlaces de subida anónimos

    def crear_suscripcion_cambios(self, carpeta_id, url_webhook):
        raise NotImplementedError("Google Drive no usa suscripciones de cambios; se revisa por sondeo")

    def eliminar_archivo(self, archivo_id):
        resp = self._http.patch(f"{self.API}/files/{archivo_id}", headers=self._headers(), json={"trashed": True})
        if resp.status_code != 404:
            resp.raise_for_status()

    def obtener_enlace(self, elemento_id):
        resp = self._http.get(f"{self.API}/files/{elemento_id}", headers=self._headers(), params={"fields": "webViewLink"})
        resp.raise_for_status()
        return resp.json()["webViewLink"]


def obtener_almacenamiento(proveedor: str, **kwargs) -> AlmacenamientoDocumentos:
    proveedores = {"onedrive": OneDriveStorage, "gdrive": GoogleDriveStorage}
    if proveedor not in proveedores:
        raise ValueError(f"Proveedor de almacenamiento '{proveedor}' no soportado todavía. Disponibles: {list(proveedores.keys())}")
    return proveedores[proveedor](**kwargs)
