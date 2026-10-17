# -*- coding: utf-8 -*-
"""
Alta automática de carpetas. La gestoría solo da el nombre y el CIF de cada
empresa-cliente; el agente crea todo en su OneDrive:

  Agente Facturas/
     Sin identificar/            (para documentos que no se saben asignar)
     <Nombre empresa> - <CIF>/
        Facturas/                (aquí suben los clientes sus facturas)
        Tickets/
        Revisión/
        Excel/                   (aquí aparecen los Excel por trimestre)
"""

import re

from basededatos import registrar_empresa_cliente, actualizar_carpetas_empresa, guardar_carpeta_sin_identificar, resolver_empresa_cliente_por_cif

CARPETA_RAIZ = "Agente Facturas"
SUBCARPETAS = {"facturas": "Facturas", "tickets": "Tickets", "revision": "Revisión", "excel": "Excel"}


def _nombre_seguro(texto):
    """OneDrive no admite \\ / : * ? " < > | en nombres de carpeta."""
    return re.sub(r'[\\/:*?"<>|]', "-", texto).strip()


def preparar_gestoria(storage, tenant_id):
    """Crea la carpeta raíz y la de 'Sin identificar'. Se puede repetir sin duplicar nada."""
    raiz_id = storage.crear_carpeta("root", CARPETA_RAIZ)
    sin_identificar_id = storage.crear_carpeta(raiz_id, "Sin identificar")
    guardar_carpeta_sin_identificar(tenant_id, sin_identificar_id)
    return raiz_id


def alta_empresa_cliente(storage, tenant_id, nombre, cif):
    """
    Crea las carpetas de una empresa-cliente y la registra en la base de datos.
    Devuelve un dict con el id de la empresa y el enlace de subida para que la
    gestoría se lo pase a su cliente (o None si OneDrive no deja crearlo).
    """
    nombre = nombre.strip()
    cif = cif.strip().upper()
    if not nombre or not cif:
        raise ValueError("Hace falta el nombre y el CIF de la empresa")

    # El CIF manda, no el nombre: en las facturas el nombre se escribe de
    # formas distintas, el CIF no. Si ya existe, se reutiliza su carpeta.
    existente = resolver_empresa_cliente_por_cif(tenant_id, [cif])
    if existente:
        return {"empresa_id": existente["id"], "enlace_subida": None, "nueva": False}

    raiz_id = storage.crear_carpeta("root", CARPETA_RAIZ)
    empresa_id_carpeta = storage.crear_carpeta(raiz_id, _nombre_seguro(f"{nombre} - {cif}"))

    carpetas = {"raiz": empresa_id_carpeta}
    for clave, nombre_carpeta in SUBCARPETAS.items():
        carpetas[clave] = storage.crear_carpeta(empresa_id_carpeta, nombre_carpeta)

    empresa_id = registrar_empresa_cliente(tenant_id, cif, nombre, carpetas)
    enlace = storage.crear_enlace_subida(carpetas["facturas"])
    return {"empresa_id": empresa_id, "enlace_subida": enlace, "nueva": True}


def reparar_empresa(storage, tenant_id, nombre, cif):
    """Vuelve a crear (o a encontrar) las carpetas de una empresa y actualiza la base de datos.
    Se usa cuando alguien ha borrado o movido carpetas en OneDrive."""
    raiz_id = storage.crear_carpeta("root", CARPETA_RAIZ)
    empresa_carpeta = storage.crear_carpeta(raiz_id, _nombre_seguro(f"{nombre} - {cif}"))
    carpetas = {"raiz": empresa_carpeta}
    for clave, nombre_carpeta in SUBCARPETAS.items():
        carpetas[clave] = storage.crear_carpeta(empresa_carpeta, nombre_carpeta)
    actualizar_carpetas_empresa(tenant_id, cif, carpetas)
    return carpetas


def reconstruir_carpetas_empresas(storage, tenant_id):
    """Tras conectar un almacenamiento nuevo: crea (o encuentra) las carpetas de las empresas que ya existen.
    Se puede repetir sin duplicar nada."""
    from basededatos import listar_empresas_activas
    for e in listar_empresas_activas(tenant_id):
        reparar_empresa(storage, tenant_id, e["nombre"], e["cif_nif"])


def alta_varias_empresas(storage, tenant_id, empresas):
    """
    empresas: lista de (nombre, cif), por ejemplo leída de un Excel o de un
    formulario. Cada una se procesa por separado: si una falla, el resto sigue.
    """
    resultados = []
    for nombre, cif in empresas:
        try:
            resultados.append({"nombre": nombre, "cif": cif, "ok": True, **alta_empresa_cliente(storage, tenant_id, nombre, cif)})
        except Exception as e:
            resultados.append({"nombre": nombre, "cif": cif, "ok": False, "error": str(e)})
    return resultados
