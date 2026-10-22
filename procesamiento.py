# -*- coding: utf-8 -*-
"""
Proceso común de un documento, venga de donde venga (correo, OneDrive, WhatsApp).

Reglas acordadas:
  - Lo que no es factura ni ticket se ignora (no se sube nada).
  - La empresa-cliente es la que RECIBE la factura (el destinatario), y se
    identifica por su CIF, no por el nombre.
  - Si esa empresa no tiene carpeta, se crea; si ya la tiene, se reutiliza.
  - Sin CIF de comprador (típico de tickets), CIF con formato no válido, o
    lectura dudosa de una empresa desconocida -> "Sin identificar".
  - Una lectura dudosa nunca crea empresas nuevas (evita carpetas basura por
    un CIF mal leído).
  - Facturas válidas: original a Facturas + fila en el Excel del trimestre.
    Facturas que no cuadran: a Revisión. Tickets: a Tickets.
  - Una factura idéntica ya procesada no se vuelve a anotar en el Excel.
"""

import hashlib
import json
import logging
import os
import re

import requests
from datetime import datetime

from basededatos import (
    crear_aviso, documento_ya_visto, eliminar_factura_cache, marcar_documento_visto, marcar_revisada,
    obtener_revision, registrar_sin_identificar,
    guardar_factura_procesada, obtener_carpeta_sin_identificar,
    obtener_facturas_ya_registradas, resolver_empresa_cliente_por_cif,
)
from clasificador_documentos import es_ticket, nombre_archivo_destino, procesar_ticket
from extraccion_ia import extraer_factura, factura_a_ticket_ligero, _detectar_media_type
from generar_excel_mieos import anadir_factura_a_excel
from onboarding import alta_empresa_cliente, preparar_gestoria, reparar_empresa
from periodo_fiscal import calcular_periodo_trimestral, periodo_a_slug

log = logging.getLogger("procesamiento")

_FORMATOS_CIF = (
    re.compile(r"^[A-HJNPQRSUVW]\d{7}[0-9A-J]$"),  # CIF de sociedades
    re.compile(r"^\d{8}[A-Z]$"),                    # NIF de persona física
    re.compile(r"^[XYZ]\d{7}[A-Z]$"),               # NIE
    re.compile(r"^[KLM]\d{7}[A-Z]$"),               # NIF especiales
)


def _normaliza_cif(cif):
    cif = re.sub(r"[\s.\-]", "", (cif or "")).upper()
    if len(cif) == 11 and cif.startswith("ES"):
        cif = cif[2:]
    return cif


def _cif_valido(cif):
    return any(p.match(cif) for p in _FORMATOS_CIF)


def _fecha_valida(fecha):
    try:
        datetime.strptime(fecha, "%d/%m/%Y")
        return True
    except (ValueError, TypeError):
        return False


def _fecha_o_hoy(fecha):
    return fecha if _fecha_valida(fecha) else datetime.now().strftime("%d/%m/%Y")


def _nombre_unico(nombre_original, factura, contenido):
    """
    Nombre con el que se guarda el original. Dos adjuntos distintos que se
    llamen igual ("factura.pdf") no deben pisarse, así que el nombre sale de
    los datos de la factura más una huella corta del contenido.
    """
    ext = {"application/pdf": ".pdf", "image/png": ".png"}.get(_detectar_media_type(contenido), ".jpg")
    sello = hashlib.sha1(contenido).hexdigest()[:8]
    partes = []
    fecha = factura.get("fecha_factura") or ""
    if _fecha_valida(fecha):
        d, m, a = fecha.split("/")
        partes.append(f"{a}-{m}-{d}")
    proveedor = ((factura.get("emisor") or {}).get("nombre") or "").strip()
    if proveedor:
        partes.append(proveedor[:25])
    numero = (factura.get("num_factura") or "").strip()
    if numero:
        partes.append(numero)
    base = "_".join(partes) if partes else os.path.splitext(nombre_original)[0]
    base = re.sub(r'[\\/:*?"<>|\s]+', "-", base).strip("-")[:80]
    return f"{base}_{sello}{ext}"


def _sin_identificar(storage, tenant_id, nombre, contenido, motivo):
    carpeta = obtener_carpeta_sin_identificar(tenant_id)
    if not carpeta:
        preparar_gestoria(storage, tenant_id)
        carpeta = obtener_carpeta_sin_identificar(tenant_id)
    storage.subir_archivo(carpeta, nombre_archivo_destino(nombre, "REVISION", motivo), contenido)
    registrar_sin_identificar(tenant_id, nombre, motivo)
    return {"accion": "sin_identificar", "motivo": motivo}


def _a_revision(storage, tenant_id, empresa, nombre, contenido, factura, motivo):
    nombre_en_revision = nombre_archivo_destino(nombre, "REVISION", motivo)
    storage.subir_archivo(empresa["carpeta_revision_id"], nombre_en_revision, contenido)
    guardar_factura_procesada(
        tenant_id=tenant_id, cif_empresa_cliente=empresa["cif_nif"], tipo_documento="factura_completa",
        num_factura=(factura.get("num_factura") or "").strip() or "(sin número)",
        fecha_factura=_fecha_o_hoy(factura.get("fecha_factura")),
        proveedor_cif=(factura.get("emisor") or {}).get("cif_nif"),
        proveedor_nombre=((factura.get("emisor") or {}).get("nombre") or "").strip() or "(desconocido)",
        total_factura=factura.get("total_factura") or 0, destino="REVISION", motivo=motivo,
        datos_json=json.dumps({"factura": factura, "archivo": nombre_en_revision, "original": nombre}, default=str),
    )
    return {"accion": "revision", "empresa": empresa["nombre"], "cif": empresa["cif_nif"], "motivo": motivo}


def _guardar_ticket(storage, tenant_id, empresa, nombre, contenido, factura):
    ticket = factura_a_ticket_ligero(factura)
    registradas = obtener_facturas_ya_registradas(tenant_id, empresa["cif_nif"])
    try:
        posible_duplicado = procesar_ticket(ticket, tenant_id, empresa["cif_nif"], registradas)["posible_duplicado"]
    except ValueError:  # fecha ilegible: no se puede comparar
        posible_duplicado = None
    nombre_final = nombre_archivo_destino(nombre, "REVISION", "posible duplicado") if posible_duplicado else nombre
    storage.subir_archivo(empresa["carpeta_tickets_id"], nombre_final, contenido)
    guardar_factura_procesada(
        tenant_id=tenant_id, cif_empresa_cliente=empresa["cif_nif"], tipo_documento="ticket",
        num_factura=(ticket["num_factura"] or "").strip() or "(sin número)",
        fecha_factura=_fecha_o_hoy(ticket["fecha_factura"]),
        proveedor_cif=ticket["proveedor"].get("cif_nif"), proveedor_nombre=ticket["proveedor"]["nombre"] or "(desconocido)",
        total_factura=ticket["total_factura"] or 0, destino="TICKETS",
    )
    return {"accion": "ticket", "empresa": empresa["nombre"], "cif": empresa["cif_nif"], "posible_duplicado": bool(posible_duplicado)}


def _guardar_factura(storage, tenant_id, empresa, nombre, contenido, factura, reintento=False):
    numero = (factura.get("num_factura") or "").strip()
    cif_emisor = _normaliza_cif((factura.get("emisor") or {}).get("cif_nif"))
    total = factura.get("total_factura") or 0

    if numero:
        for f in obtener_facturas_ya_registradas(tenant_id, empresa["cif_nif"]):
            if (f.get("destino") == "PROCESADA" and f["num_factura"] == numero
                    and _normaliza_cif(f["emisor"].get("cif_nif")) == cif_emisor
                    and abs(f["total_factura"] - total) <= 0.01):
                return {"accion": "duplicado_exacto", "empresa": empresa["nombre"], "cif": empresa["cif_nif"]}

    try:
        periodo = calcular_periodo_trimestral(factura["fecha_factura"])
    except (ValueError, KeyError, TypeError):
        if reintento:
            return {"accion": "revision", "motivo": "fecha de la factura ilegible"}
        return _a_revision(storage, tenant_id, empresa, nombre, contenido, factura, "fecha de la factura ilegible")

    nombre_excel = f"Export_{empresa['cif_nif']}_{periodo_a_slug(periodo)}.xlsx"
    existente = storage.buscar_archivo_por_nombre(empresa["carpeta_excel_id"], nombre_excel)
    contenido_excel = storage.descargar_archivo(existente.id) if existente else None

    nuevo_excel, resultado = anadir_factura_a_excel(
        contenido_excel, cif_empresa=empresa["cif_nif"], nombre_empresa=empresa["nombre"],
        periodo=periodo, factura=factura,
    )
    if not resultado["ok"]:
        if reintento:
            return {"accion": "revision", "motivo": resultado["motivo"]}
        return _a_revision(storage, tenant_id, empresa, nombre, contenido, factura, resultado["motivo"])

    if contenido is not None:
        storage.subir_archivo(empresa["carpeta_facturas_id"], nombre, contenido)
    storage.subir_archivo(empresa["carpeta_excel_id"], nombre_excel, nuevo_excel)
    guardar_factura_procesada(
        tenant_id=tenant_id, cif_empresa_cliente=empresa["cif_nif"], tipo_documento="factura_completa",
        num_factura=numero or "(sin número)", fecha_factura=factura["fecha_factura"],
        proveedor_cif=(factura.get("emisor") or {}).get("cif_nif"),
        proveedor_nombre=((factura.get("emisor") or {}).get("nombre") or "").strip() or "(desconocido)",
        total_factura=total, destino="PROCESADA",
    )
    return {"accion": "procesada", "empresa": empresa["nombre"], "cif": empresa["cif_nif"], "excel": nombre_excel}


def procesar_documento(storage, tenant_id, contenido, nombre_original, extraer=None, diferir_dudosas=False):
    """
    Procesa un documento (bytes) y lo archiva en el OneDrive de la gestoría.
    Devuelve un dict con "accion": ignorado | sin_identificar | ticket | procesada |
    revision | duplicado_exacto. El llamador se encarga de lo que hay en el canal de
    origen (marcar el correo como leído, borrar el archivo de la carpeta de entrada...).
    'extraer' permite sustituir la lectura con IA (útil para pruebas).
    'diferir_dudosas': usado por los lotes; una lectura dudosa de una empresa aún desconocida
    no se archiva todavía y devuelve "en_espera" (con la factura leída) para reintentarla
    cuando termine el lote.
    """
    factura = (extraer or extraer_factura)(contenido)
    if not factura.get("es_documento_fiscal", True):
        return {"accion": "ignorado"}
    res = _archivar_con_reparacion(storage, tenant_id, contenido, nombre_original, factura, diferir_dudosas)
    if factura.get("_lectura_fallida"):
        res = {**res, "lectura_fallida": True}  # no se pudo leer: no debe darse por "visto"
    return res


def _archivar_con_reparacion(storage, tenant_id, contenido, nombre_original, factura, diferir=False, forzar_revision=None):
    try:
        return _archivar(storage, tenant_id, contenido, nombre_original, factura, diferir, forzar_revision)
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 404:
            raise
        # Una carpeta guardada ya no existe en OneDrive (alguien la borró o la movió):
        # se recrean las que falten y se reintenta UNA vez, sin volver a llamar a la IA.
        log.warning("Carpeta no encontrada en el almacenamiento; se recrean y se reintenta")
        preparar_gestoria(storage, tenant_id)
        cif = _normaliza_cif(((factura.get("destinatario") or {}).get("cif_nif")))
        empresa = resolver_empresa_cliente_por_cif(tenant_id, [cif]) if cif else None
        if empresa:
            reparar_empresa(storage, tenant_id, empresa["nombre"], empresa["cif_nif"])
            donde = f"la carpeta de {empresa['nombre']} ({empresa['cif_nif']})"
        else:
            donde = "una carpeta de Agente Facturas (por ejemplo «Sin identificar»)"
        crear_aviso(
            tenant_id, "carpeta_recreada",
            f"Faltaba {donde} en su almacenamiento (OneDrive o Google Drive): se borró o se movió. El agente la ha vuelto a crear. "
            "Lo que había dentro no se recupera solo: puede buscarlo en la papelera de su OneDrive o Google Drive.",
        )
        return _archivar(storage, tenant_id, contenido, nombre_original, factura, diferir, forzar_revision)


def _archivar(storage, tenant_id, contenido, nombre_original, factura, diferir=False, forzar_revision=None):
    nombre = _nombre_unico(nombre_original, factura, contenido)
    destinatario = factura.get("destinatario") or {}
    cif = _normaliza_cif(destinatario.get("cif_nif"))

    if not cif:
        if diferir and not es_ticket(factura):
            # En un lote, la empresa puede deducirse de las demás facturas (se decide al final).
            return {"accion": "en_espera", "razon": "sin_cif", "factura": factura}
        if factura.get("confianza") == "baja" and not (factura.get("num_factura") or factura.get("total_factura")):
            return _sin_identificar(storage, tenant_id, nombre, contenido, "documento ilegible o borroso")
        return _sin_identificar(storage, tenant_id, nombre, contenido, "sin CIF del comprador")
    if not _cif_valido(cif):
        return _sin_identificar(storage, tenant_id, nombre, contenido, "CIF del comprador con formato no válido")
    from validaciones import control_nif_cif_correcto
    if control_nif_cif_correcto(cif) is False and not resolver_empresa_cliente_por_cif(tenant_id, [cif]):
        # Un dígito mal leído crearía una empresa fantasma y archivaría la factura donde no toca: se aparta para revisarla.
        return _sin_identificar(storage, tenant_id, nombre, contenido, "CIF del comprador con dígito de control incorrecto (posible error de lectura)")

    # El CIF ya normalizado se usa también dentro de la factura, para que coincida con el de la empresa.
    factura = {**factura, "destinatario": {**destinatario, "cif_nif": cif}}

    if factura.get("confianza") != "baja":
        nombre_empresa = (destinatario.get("nombre") or "").strip() or cif
        if alta_empresa_cliente(storage, tenant_id, nombre_empresa, cif).get("nueva"):
            crear_aviso(tenant_id, "empresa_nueva",
                        f"{nombre_empresa} ({cif})")
    empresa = resolver_empresa_cliente_por_cif(tenant_id, [cif])
    if not empresa:
        if diferir:
            return {"accion": "en_espera", "razon": "dudosa", "factura": factura}
        return _sin_identificar(storage, tenant_id, nombre, contenido, "lectura dudosa de una empresa desconocida")

    if forzar_revision:
        return _a_revision(storage, tenant_id, empresa, nombre, contenido, factura, forzar_revision)

    if es_ticket(factura):
        return _guardar_ticket(storage, tenant_id, empresa, nombre, contenido, factura)
    return _guardar_factura(storage, tenant_id, empresa, nombre, contenido, factura)


def _huella(contenido):
    return hashlib.sha256(contenido).hexdigest()


def _procesar_sin_repetir(storage, tenant_id, contenido, nombre_original, extraer=None):
    """Como procesar_documento, pero si este mismo archivo se leyó hace poco no vuelve a gastar IA."""
    huella = _huella(contenido)
    if documento_ya_visto(tenant_id, huella):
        log.info("'%s': ya leído hace poco, se salta", nombre_original)
        return {"accion": "ya_visto"}
    res = procesar_documento(storage, tenant_id, contenido, nombre_original, extraer=extraer)
    if not res.get("lectura_fallida"):
        marcar_documento_visto(tenant_id, huella)
    return res


def procesar_archivo(storage, tenant_id, contenido, nombre_original, extraer=None, dividir=None):
    """
    Punto de entrada para los canales (correo, OneDrive, WhatsApp). Si el archivo es un PDF
    con varias páginas, lo separa en documentos sueltos (un lote escaneado trae varias
    facturas) y procesa cada uno; si no, equivale a procesar_documento.
    Devuelve una lista de resultados, uno por documento. Si algún documento falla, se
    procesan igualmente los demás y al final se vuelve a lanzar el error para que el canal
    reintente (las facturas ya anotadas no se duplican).
    """
    import dividir_pdf

    total = dividir_pdf.contar_paginas(contenido) if contenido[:4] == b"%PDF" else 0
    if total <= 1:
        return [_procesar_sin_repetir(storage, tenant_id, contenido, nombre_original, extraer)]
    if total > dividir_pdf.MAX_PAGINAS:
        log.warning("PDF de %d páginas, demasiado largo para dividir; va a Sin identificar", total)
        return [_sin_identificar(storage, tenant_id, nombre_original, contenido,
                                 f"PDF de {total} paginas, dividir a mano")]

    grupos = (dividir or dividir_pdf.detectar_documentos)(contenido, total)
    partes = dividir_pdf.cortar_pdf(contenido, grupos)
    base = os.path.splitext(os.path.basename(nombre_original))[0]
    log.info("'%s': %d páginas -> %d documentos", nombre_original, total, len(partes))

    resultados, primer_error, en_espera = [], None, []
    for grupo, parte in zip(grupos, partes):
        rango = f"p{grupo[0]}" if len(grupo) == 1 else f"p{grupo[0]}-{grupo[-1]}"
        nombre_parte = f"{base}_{rango}.pdf"
        try:
            huella = _huella(parte)
            if documento_ya_visto(tenant_id, huella):  # reintento de un correo: esta parte ya se leyó
                log.info("'%s' %s: ya leída hace poco, se salta", nombre_original, rango)
                resultados.append({"accion": "ya_visto"})
                continue
            res = procesar_documento(storage, tenant_id, parte, nombre_parte, extraer=extraer, diferir_dudosas=True)
            if res.get("accion") != "en_espera" and not res.get("lectura_fallida"):
                marcar_documento_visto(tenant_id, huella)
        except Exception as e:
            log.exception("Fallo procesando %s de '%s'", rango, nombre_original)
            primer_error = primer_error or e
            continue
        if res.get("accion") == "en_espera":
            en_espera.append((len(resultados), parte, nombre_parte, res["factura"], res.get("razon")))
        resultados.append(res)

    # Segunda vuelta, ya con el lote entero procesado:
    #  - lectura dudosa de una empresa desconocida: otra factura del lote pudo crearla ya;
    #  - factura sin CIF del comprador: si todas las demás del lote son de una única empresa,
    #    se asigna a ella, pero siempre a Revisión para que la gestoría lo confirme.
    empresas_del_lote = {r["cif"] for r in resultados if r.get("cif")}
    for posicion, parte, nombre_parte, factura, razon in en_espera:
        forzar = None
        if razon == "sin_cif":
            if len(empresas_del_lote) == 1:
                cif_lote = next(iter(empresas_del_lote))
                factura = {**factura, "destinatario": {**(factura.get("destinatario") or {}), "cif_nif": cif_lote}}
                forzar = "no se leyó el CIF del comprador; asignada a la empresa del resto del lote"
        try:
            resultados[posicion] = _archivar_con_reparacion(storage, tenant_id, parte, nombre_parte, factura,
                                                            forzar_revision=forzar)
            if not factura.get("_lectura_fallida"):
                marcar_documento_visto(tenant_id, _huella(parte))
        except Exception as e:
            log.exception("Fallo en la segunda vuelta de %s", nombre_parte)
            primer_error = primer_error or e
            resultados[posicion] = {"accion": "error"}
    if primer_error:
        raise primer_error
    return resultados


def reprocesar_revision(storage, tenant_id, factura_id, factura):
    """
    La gestoría ha corregido a mano los datos de una factura en Revisión (desde el panel).
    Se vuelve a validar y, si ya cuadra, se añade al Excel, el original pasa a la carpeta
    Facturas y la factura sale de Revisión. Si sigue sin cuadrar, no se toca nada y se
    devuelve {"accion": "revision", "motivo": ...} para que el panel lo enseñe.
    Si el archivo ya no está en la carpeta Revisión (la gestoría lo movió), igualmente se añade
    la fila al Excel; solo se omite el traslado del original.
    """
    r = obtener_revision(tenant_id, factura_id)
    if not r or r["destino"] != "REVISION":
        return {"accion": "error", "motivo": "Esta factura ya no está pendiente de revisión."}
    empresa = r["empresa"]
    datos = r["datos"] or {}
    nombre_revision, original = datos.get("archivo"), datos.get("original") or datos.get("archivo") or "factura.pdf"

    archivo = storage.buscar_archivo_por_nombre(empresa["carpeta_revision_id"], nombre_revision) if nombre_revision else None
    contenido = storage.descargar_archivo(archivo.id) if archivo else None

    factura = {**factura, "confianza": "alta"}  # la ha revisado una persona
    res = _guardar_factura(storage, tenant_id, empresa, original, contenido, factura, reintento=True)
    if res["accion"] == "procesada":
        eliminar_factura_cache(tenant_id, factura_id)  # _guardar_factura ya ha creado su registro PROCESADA
        if archivo:
            storage.eliminar_archivo(archivo.id)  # el original ya está en Facturas
    elif res["accion"] == "duplicado_exacto":
        marcar_revisada(tenant_id, factura_id)
    return res
