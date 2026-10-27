# -*- coding: utf-8 -*-
"""
Carpeta «Entrada»: la gestoría sube a mano (sueltos o en subcarpetas) PDF o fotos de facturas a

    Agente Facturas / Entrada

y el agente los lee con el mismo proceso que los adjuntos del correo (divide los PDF con varias facturas, asigna
cada una a su empresa por el CIF, controla duplicados y manda lo dudoso a Revisión o «Sin identificar»).
Cuando un archivo está tratado se mueve a «Entrada / Procesados»; los que no se pueden leer, a «Entrada / No procesables».

Se vigila en OneDrive y en Google Drive (ENTRADA_PROVEEDORES). Con Google Drive, el permiso actual («drive.file») solo deja
ver lo que crea el propio agente, así que allí no sirven los archivos que la gestoría arrastra a mano a la carpeta: se suben
desde «Subir facturas» del panel (subida_web.py), que los guarda en Entrada a través del agente.

Variables opcionales: ENTRADA_MAX_POR_CICLO (por defecto 15 archivos por gestoría y ciclo), ENTRADA_PROVEEDORES.
"""

import logging
import os
from datetime import datetime, timezone

import requests

from autenticacion_google import ErrorAutorizacionGoogle
from autenticacion_onedrive import ErrorAutorizacionMicrosoft
from almacenamiento_tenant import storage_para_tenant
from basededatos import (crear_aviso, guardar_carpetas_entrada, obtener_carpetas_entrada, olvidar_carpetas_entrada,
                         proveedor_almacenamiento_activo, registrar_intento_fallido, tenants_con_almacenamiento)
from onboarding import CARPETA_RAIZ
from procesamiento import procesar_archivo
from extraccion_ia import ServicioIANoDisponible

log = logging.getLogger("sondeo_entrada")

NOMBRE_ENTRADA = "Entrada"
NOMBRE_PROCESADOS = "Procesados"
NOMBRE_NO_PROCESABLES = "No procesables"

from formatos import EXTENSIONES
IGNORAR = {".ds_store", "thumbs.db", "desktop.ini"}  # archivos que crean el sistema o el sincronizador
MAX_BYTES = 25 * 1024 * 1024
MAX_INTENTOS = 5          # a los 5 fallos seguidos se aparta el archivo y se avisa
SEGUNDOS_ASENTAR = 30     # no se toca un archivo modificado hace menos: puede estar aún subiéndose
MAX_CARPETAS = 200
MAX_PROFUNDIDAD = 6


def _proveedores_activos():
    return {p.strip() for p in os.environ.get("ENTRADA_PROVEEDORES", "onedrive,gdrive").split(",") if p.strip()}


def asegurar_carpetas(storage, tenant_id, proveedor, comprobar=False):
    """Devuelve los ids de las carpetas de entrada, creándolas si hace falta. Repetirlo no duplica nada.
    Con comprobar=True se verifica que «Entrada» siga existiendo; si la gestoría la borró, se vuelve a crear."""
    carpetas = obtener_carpetas_entrada(tenant_id, proveedor)
    if carpetas and comprobar:
        try:
            storage.obtener_enlace(carpetas["entrada"])
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", None) not in (404, 410):
                raise
            olvidar_carpetas_entrada(tenant_id)
            carpetas = None
    if carpetas:
        return carpetas
    raiz = storage.crear_carpeta("root", CARPETA_RAIZ)
    entrada = storage.crear_carpeta(raiz, NOMBRE_ENTRADA)
    procesados = storage.crear_carpeta(entrada, NOMBRE_PROCESADOS)
    no_procesables = storage.crear_carpeta(entrada, NOMBRE_NO_PROCESABLES)
    guardar_carpetas_entrada(tenant_id, proveedor, entrada, procesados, no_procesables)
    return {"entrada": entrada, "procesados": procesados, "no_procesables": no_procesables}


def _segundos_desde(fecha_iso):
    """Segundos desde una fecha ISO 8601 (la de Microsoft Graph o la de Google Drive). None si no se entiende."""
    try:
        f = datetime.fromisoformat((fecha_iso or "").replace("Z", "+00:00"))
        if f.tzinfo is None:
            f = f.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - f).total_seconds()
    except ValueError:
        return None


def _recorrer(storage, carpetas):
    """Todos los archivos de «Entrada» y sus subcarpetas, salvo «Procesados» y «No procesables»."""
    excluidas = {carpetas["procesados"], carpetas["no_procesables"]}
    pendientes, vistas, archivos = [(carpetas["entrada"], 0)], 0, []
    while pendientes:
        carpeta_id, nivel = pendientes.pop(0)
        sueltos, subcarpetas = storage.listar_contenido(carpeta_id)
        archivos.extend(sueltos)
        if nivel >= MAX_PROFUNDIDAD:
            continue
        for sub_id, _nombre in subcarpetas:
            if sub_id in excluidas:
                continue
            vistas += 1
            if vistas > MAX_CARPETAS:
                log.warning("Entrada: demasiadas subcarpetas, se dejan las demás para otro momento")
                return archivos
            pendientes.append((sub_id, nivel + 1))
    return archivos


def _listar_con_reparacion(storage, tenant_id, proveedor, carpetas):
    """Si la gestoría borró la carpeta «Entrada», se vuelve a crear en vez de fallar para siempre."""
    try:
        return carpetas, _recorrer(storage, carpetas)
    except requests.HTTPError as e:
        if getattr(e.response, "status_code", None) != 404:
            raise
        log.info("Entrada %s: la carpeta ya no existe, se vuelve a crear", tenant_id)
        olvidar_carpetas_entrada(tenant_id)
        carpetas = asegurar_carpetas(storage, tenant_id, proveedor)
        return carpetas, _recorrer(storage, carpetas)


def _es_lectura_posible(contenido):
    """PDF, imagen o ZIP de verdad (la extensión puede engañar)."""
    from formatos import tipo_real
    return tipo_real(contenido) is not None


def _mover(storage, archivo, carpeta_destino, con_fecha=True):
    nuevo = f"{datetime.now():%Y%m%d-%H%M%S}_{archivo.nombre}" if con_fecha else None
    storage.mover_o_renombrar(archivo.id, carpeta_destino, nuevo)


def procesar_entrada(storage, tenant_id, proveedor, max_archivos=None):
    """Un ciclo para una gestoría. Devuelve un resumen con los archivos tratados, apartados y pendientes."""
    max_archivos = max_archivos or int(os.environ.get("ENTRADA_MAX_POR_CICLO", "15"))
    carpetas = asegurar_carpetas(storage, tenant_id, proveedor)
    carpetas, archivos = _listar_con_reparacion(storage, tenant_id, proveedor, carpetas)
    archivos = [a for a in archivos if a.nombre.lower() not in IGNORAR and not a.nombre.startswith("~$")]
    archivos.sort(key=lambda a: a.fecha_modificacion or "")

    resumen = {"procesados": 0, "apartados": 0, "fallidos": 0, "pendientes": 0}
    apartados_no_leibles = []
    tratados = 0
    for archivo in archivos:
        edad = _segundos_desde(archivo.fecha_modificacion)
        if (edad is not None and edad < SEGUNDOS_ASENTAR) or archivo.tamano_bytes == 0:
            resumen["pendientes"] += 1   # aún se está subiendo (o está vacío): se mira en el siguiente ciclo
            continue
        if tratados >= max_archivos:
            resumen["pendientes"] += 1
            continue
        tratados += 1
        extension = os.path.splitext(archivo.nombre)[1].lower()
        try:
            if extension not in EXTENSIONES or archivo.tamano_bytes > MAX_BYTES:
                motivo = "formato no admitido (use PDF, imagen o ZIP)" if extension not in EXTENSIONES else "pesa demasiado (más de 25 MB)"
                _mover(storage, archivo, carpetas["no_procesables"])
                apartados_no_leibles.append(f"{archivo.nombre} ({motivo})")
                resumen["apartados"] += 1
                continue
            contenido = storage.descargar_archivo(archivo.id)
            if not _es_lectura_posible(contenido):
                _mover(storage, archivo, carpetas["no_procesables"])
                apartados_no_leibles.append(f"{archivo.nombre} (el archivo no se puede leer; si es una foto, guárdela como JPG)")
                resumen["apartados"] += 1
                continue
            resultados = procesar_archivo(storage, tenant_id, contenido, archivo.nombre)
            log.info("Entrada %s: '%s' -> %s", tenant_id, archivo.nombre, [(r or {}).get("accion") for r in resultados])
            try:
                _mover(storage, archivo, carpetas["procesados"])
            except Exception:
                # El archivo ya está tratado y su huella guardada: si no se pudo mover, la próxima vez no se vuelve a pagar la IA.
                log.exception("Entrada %s: tratado '%s' pero no se pudo mover a Procesados", tenant_id, archivo.nombre)
            resumen["procesados"] += 1
        except ServicioIANoDisponible:
            # Sin saldo o caída del servicio de IA: el archivo se queda en Entrada y no cuenta como fallo. Se para el ciclo.
            resumen["pendientes"] += 1
            crear_aviso(tenant_id, "ia_no_disponible",
                        "El servicio de lectura de facturas no está disponible en este momento. No se ha perdido nada: sus documentos "
                        "siguen en la carpeta Entrada y se leerán solos en cuanto se recupere. Si el aviso dura más de un día, escríbanos.")
            break
        except Exception as e:
            intentos = registrar_intento_fallido(tenant_id, f"entrada:{archivo.id}", f"{type(e).__name__}: {e}")
            resumen["fallidos"] += 1
            if intentos >= MAX_INTENTOS:
                log.exception("Entrada %s: '%s' falló %d veces; se aparta", tenant_id, archivo.nombre, intentos)
                try:
                    _mover(storage, archivo, carpetas["no_procesables"])
                except Exception:
                    log.exception("Entrada %s: no se pudo apartar '%s'", tenant_id, archivo.nombre)
                crear_aviso(tenant_id, "entrada_fallida",
                            f"No se ha podido procesar el archivo «{archivo.nombre}» de la carpeta Entrada después de varios intentos. "
                            "Lo hemos dejado en Entrada / No procesables: revíselo y, si es una factura, súbala de nuevo o anótela a mano.")
            else:
                log.exception("Entrada %s: fallo con '%s' (intento %d de %d)", tenant_id, archivo.nombre, intentos, MAX_INTENTOS)

    if apartados_no_leibles:
        lista = "; ".join(apartados_no_leibles[:5]) + (f" y {len(apartados_no_leibles) - 5} más" if len(apartados_no_leibles) > 5 else "")
        crear_aviso(tenant_id, "entrada_apartados",
                    f"Hemos apartado {len(apartados_no_leibles)} archivo(s) de la carpeta Entrada porque no se pueden leer: {lista}. "
                    "Los encontrará en Entrada / No procesables.")
    return resumen


def _procesar_tenant(tenant_id):
    proveedor = proveedor_almacenamiento_activo(tenant_id)
    if proveedor not in _proveedores_activos():
        return None
    try:
        storage = storage_para_tenant(tenant_id)
    except (ErrorAutorizacionGoogle, ErrorAutorizacionMicrosoft) as e:
        crear_aviso(tenant_id, "drive_desconectado", f"{e}. Entre en Conexiones y vuelva a conectar su almacenamiento.")
        return None
    if storage is None:
        return None
    return procesar_entrada(storage, tenant_id, proveedor)


def ciclo_entrada():
    """Lo llama el mismo ciclo que revisa el correo (el cron de cada minuto)."""
    tenants = tenants_con_almacenamiento()
    for tenant_id in tenants:
        try:
            resumen = _procesar_tenant(tenant_id)
            if resumen and (resumen["procesados"] or resumen["apartados"] or resumen["fallidos"]):
                log.info("Entrada %s: %s", tenant_id, resumen)
        except Exception:
            log.exception("Error en la carpeta de entrada de la gestoría %s", tenant_id)
