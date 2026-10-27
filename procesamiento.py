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
  - Facturas válidas: original a Facturas + fila en el Excel del periodo (mes o trimestre).
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

from validar_cif import comprobar as comprobar_cif
from basededatos import aprender_proveedor, buscar_proveedor_aprendido, alta_automatica_activa
from basededatos import (
    crear_aviso, documento_ya_visto, eliminar_factura_cache, marcar_documento_visto, marcar_revisada,
    obtener_revision, registrar_sin_identificar, resolver_sin_identificar, cliente_quitado,
    guardar_factura_procesada, obtener_carpeta_sin_identificar,
    obtener_facturas_ya_registradas, resolver_empresa_cliente_por_cif,
)
from clasificador_documentos import es_ticket, nombre_archivo_destino, procesar_ticket
from extraccion_ia import extraer_factura, factura_a_ticket_ligero, _detectar_media_type, ServicioIANoDisponible
from generar_excel_mieos import anadir_factura_a_excel
from onboarding import alta_empresa_cliente, preparar_gestoria, reparar_empresa
from periodo_fiscal import periodo_para, nombre_excel as nombre_del_excel

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
    ext = ".xml" if contenido[:1] in (b"<", b"\xef") else {"application/pdf": ".pdf", "image/png": ".png"}.get(_detectar_media_type(contenido), ".jpg")
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


def _se_parece_a_una_anotada(tenant_id, empresa, factura, numero, cif_emisor, total):
    """Casi-duplicados que el control exacto no ve. Devuelve el motivo, o None si no hay nada sospechoso."""
    nombre = _palabras((factura.get("emisor") or {}).get("nombre"))
    for f in obtener_facturas_ya_registradas(tenant_id, empresa["cif_nif"]):
        if f.get("destino") != "PROCESADA" or f["num_factura"] != numero:
            continue
        cif_f = _normaliza_cif(f["emisor"].get("cif_nif"))
        mismo_total = abs(f["total_factura"] - total) <= 0.01
        if cif_f == cif_emisor and not mismo_total:
            return f"este proveedor ya tiene anotada una factura con el mismo número ({numero}) pero con otro importe"
        if cif_f != cif_emisor and mismo_total and nombre & _palabras(f["emisor"].get("nombre")):
            return "parece la misma factura que ya está anotada, pero el CIF del proveedor no coincide (posible error de lectura)"
    return None


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

    if numero and not reintento:
        sospechosa = _se_parece_a_una_anotada(tenant_id, empresa, factura, numero, cif_emisor, total)
        if sospechosa:
            return _a_revision(storage, tenant_id, empresa, nombre, contenido, factura, sospechosa)

    try:
        periodo = periodo_para(tenant_id, factura["fecha_factura"], empresa["cif_nif"])
    except (ValueError, KeyError, TypeError):
        if reintento:
            return {"accion": "revision", "motivo": "fecha de la factura ilegible"}
        return _a_revision(storage, tenant_id, empresa, nombre, contenido, factura, "fecha de la factura ilegible")

    nombre_excel = nombre_del_excel(empresa["cif_nif"], periodo)
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
    if factura.get("_error_servicio"):
        log.error("El servicio de IA no está disponible (¿sin saldo en Anthropic?): el documento '%s' se deja sin tocar", nombre_original)
        raise ServicioIANoDisponible(nombre_original)
    if not factura.get("es_documento_fiscal", True):
        return {"accion": "ignorado"}
    try:
        factura = _corregir_con_conocidos(tenant_id, factura)
    except Exception:
        log.exception("No se pudo comparar el CIF con los datos conocidos")
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


def _distancia(a, b):
    """Número de cambios de carácter para pasar de a a b (para comparar un CIF mal leído con uno conocido)."""
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (ca != cb)))
        anterior = actual
    return anterior[-1]


def _corregir_con_conocidos(tenant_id, factura):
    """Un CIF que no pasa el dígito de control casi siempre es un dígito mal leído. Si se parece mucho al de un proveedor ya aceptado
    (y el nombre coincide), o al de una empresa cliente de la gestoría, se corrige. Solo si hay una única candidata."""
    from basededatos import listar_empresas_activas, proveedores_conocidos
    from validaciones import control_nif_cif_correcto
    if factura.get("_lectura_fallida"):
        return factura
    cambios = {}
    emisor = factura.get("emisor") or {}
    cif = _normaliza_cif(emisor.get("cif_nif"))
    ticket = factura.get("es_factura_simplificada") or factura.get("formato_ticket_tpv") or factura.get("sin_cif_destinatario")
    if not ticket and comprobar_cif(cif)[1] and (emisor.get("nombre") or "").strip():
        # El CIF del proveedor falta o no es válido: si la gestoría ya confirmó a mano el de ese proveedor (mismo nombre), se usa.
        # Un CIF bien leído nunca se sustituye.
        aprendido = buscar_proveedor_aprendido(tenant_id, emisor.get("nombre"))
        if aprendido:
            crear_aviso(tenant_id, "cif_aprendido",
                        f"Se ha completado el CIF de {aprendido['nombre']} ({aprendido['cif_nif']}) con el que usted confirmó antes. "
                        "Puede ver y borrar lo que el agente recuerda en «Proveedores recordados».")
            return {**factura, "emisor": {**emisor, "cif_nif": aprendido["cif_nif"]},
                    "relectura": factura.get("relectura") or "cif_aprendido"}
    if cif and control_nif_cif_correcto(cif) is False:
        palabras = _palabras(emisor.get("nombre"))
        candidatos = {_normaliza_cif(k["cif_nif"]) for k in proveedores_conocidos(tenant_id)
                      if control_nif_cif_correcto(_normaliza_cif(k["cif_nif"])) is not False
                      and _distancia(cif, _normaliza_cif(k["cif_nif"])) <= 3
                      and len(palabras) >= 1 and palabras & _palabras(k["nombre"])}
        if len(candidatos) == 1:
            cambios["emisor"] = {**emisor, "cif_nif": next(iter(candidatos))}
    destinatario = factura.get("destinatario") or {}
    cif = _normaliza_cif(destinatario.get("cif_nif"))
    if cif and control_nif_cif_correcto(cif) is False:
        candidatos = {_normaliza_cif(e["cif_nif"]) for e in listar_empresas_activas(tenant_id)
                      if _distancia(cif, _normaliza_cif(e["cif_nif"])) <= 2}
        if len(candidatos) == 1:
            cambios["destinatario"] = {**destinatario, "cif_nif": next(iter(candidatos))}
    if cambios:
        log.info("CIF corregido con los datos que ya conoce la gestoría: %s", list(cambios))
        return {**factura, **cambios, "relectura": factura.get("relectura") or "cif_conocido"}
    return factura


def _palabras(texto):
    import re
    import unicodedata
    t = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode().upper()
    return {p for p in re.findall(r"[A-Z0-9]+", t) if len(p) >= 3 and p not in {"SOCIEDAD", "LIMITADA", "SLU", "SAU"}}


def _empresa_por_pistas(tenant_id, destinatario):
    """El CIF del comprador falta o está cortado/ilegible, pero el nombre (o el principio del CIF) coincide con UNA sola empresa
    ya dada de alta de la gestoría: se devuelve esa empresa. Si hay dudas (ninguna o varias), None."""
    from basededatos import listar_empresas_activas
    destinatario = destinatario or {}
    parcial = _normaliza_cif(destinatario.get("cif_nif"))
    palabras = _palabras(destinatario.get("nombre"))
    candidatas = []
    for e in listar_empresas_activas(tenant_id):
        cif_e = _normaliza_cif(e["cif_nif"])
        por_cif = len(parcial) >= 5 and cif_e.startswith(parcial)
        otras = _palabras(e["nombre"])
        menor, mayor = (palabras, otras) if len(palabras) <= len(otras) else (otras, palabras)
        por_nombre = len(menor) >= 2 and menor <= mayor
        if por_cif or por_nombre:
            candidatas.append(e)
    if len(candidatas) != 1:
        return None
    return resolver_empresa_cliente_por_cif(tenant_id, [_normaliza_cif(candidatas[0]["cif_nif"])])


def _archivar(storage, tenant_id, contenido, nombre_original, factura, diferir=False, forzar_revision=None):
    nombre = _nombre_unico(nombre_original, factura, contenido)
    destinatario = factura.get("destinatario") or {}
    cif = _normaliza_cif(destinatario.get("cif_nif"))

    # Factura EMITIDA por un cliente de la gestoría (una venta suya): el comprador es un cliente de SU cliente, no de la gestoría.
    # Se archiva en el cliente emisor (hoja VENTAS) y no se da de alta al comprador.
    emisor_cif = _normaliza_cif((factura.get("emisor") or {}).get("cif_nif"))
    if emisor_cif and emisor_cif != cif and not (cif and resolver_empresa_cliente_por_cif(tenant_id, [cif])):
        emisora = resolver_empresa_cliente_por_cif(tenant_id, [emisor_cif])
        if emisora:
            if forzar_revision:
                return _a_revision(storage, tenant_id, emisora, nombre, contenido, factura, forzar_revision)
            # Una factura emitida por el propio cliente es una VENTA aunque el comprador no tenga NIF (alumnos, particulares):
            # solo un ticket de verdad (simplificada/TPV) va a Tickets.
            if factura.get("es_factura_simplificada") or factura.get("formato_ticket_tpv"):
                return _guardar_ticket(storage, tenant_id, emisora, nombre, contenido, factura)
            return _guardar_factura(storage, tenant_id, emisora, nombre, contenido, factura)

    ticket_de_verdad = factura.get("es_factura_simplificada") or factura.get("formato_ticket_tpv")
    if (not cif or not _cif_valido(cif)) and not ticket_de_verdad and not factura.get("_lectura_fallida") \
            and (factura.get("num_factura") or factura.get("total_factura")):
        # CIF del comprador cortado o ilegible: si el nombre (o el principio del CIF) encaja con una sola empresa conocida, se
        # asigna a ella, pero siempre a Revisión para que la gestoría lo confirme.
        empresa_pista = _empresa_por_pistas(tenant_id, destinatario)
        if empresa_pista:
            factura = {**factura, "sin_cif_destinatario": False,
                       "destinatario": {**destinatario, "cif_nif": empresa_pista["cif_nif"]}}
            return _archivar(storage, tenant_id, contenido, nombre_original, factura, False,
                             forzar_revision or "el CIF del comprador no se leyó entero; asignada a "
                             f"{empresa_pista['nombre']} por el nombre")

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

    if cliente_quitado(tenant_id, cif):
        return _sin_identificar(storage, tenant_id, nombre, contenido, "el comprador es un cliente que usted quitó de la lista")

    # El CIF ya normalizado se usa también dentro de la factura, para que coincida con el de la empresa.
    factura = {**factura, "destinatario": {**destinatario, "cif_nif": cif}}

    if not resolver_empresa_cliente_por_cif(tenant_id, [cif]) and not alta_automatica_activa(tenant_id):
        return _sin_identificar(storage, tenant_id, nombre, contenido, "empresa que no esta en su lista de clientes")

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


LECTURAS_PARALELAS = max(1, int(os.environ.get("LECTURAS_PARALELAS", "4")))


def leer_por_adelantado(contenidos, extraer=None, al_terminar=None):
    """
    Lee con IA varios documentos A LA VEZ (máx. LECTURAS_PARALELAS). Solo se paraleliza la lectura:
    comprobar duplicados, anotar en el Excel y archivar siguen haciéndose de uno en uno y en orden.
    Devuelve una lista con la factura leída de cada documento (None si esa lectura falló: se leerá
    de nuevo de forma normal al llegarle el turno). 'al_terminar(hechos, total)' avisa cada vez que acaba una lectura.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor
    leer = extraer or extraer_factura
    cuenta, cerrojo = [0], threading.Lock()

    def una(c):
        try:
            return leer(c) if c is not None else None
        except Exception:
            log.exception("Lectura previa fallida; se repetirá en su turno")
            return None
        finally:
            if al_terminar:
                with cerrojo:
                    cuenta[0] += 1
                    hechos = cuenta[0]
                try:
                    al_terminar(hechos, len(contenidos))
                except Exception:
                    log.debug("No se pudo avisar del progreso", exc_info=True)

    if len(contenidos) <= 1 or LECTURAS_PARALELAS <= 1:
        return [una(c) for c in contenidos]
    with ThreadPoolExecutor(max_workers=LECTURAS_PARALELAS) as pool:
        return list(pool.map(una, contenidos))


def detectar_cliente_emisor(storage, tenant_id, facturas):
    """
    Un emisor que firma la mayoría de las facturas de un lote y se las manda a varios compradores distintos es el libro de ventas
    de ese emisor: el emisor es el cliente de la gestoría y los compradores son clientes SUYOS.
    Si aún no está dado de alta, se da de alta (con aviso) para que sus facturas vayan a su hoja VENTAS y no se creen sus
    compradores como clientes de la gestoría. Devuelve el CIF dado de alta, o None.
    Prudencia: hacen falta >= 3 facturas del emisor y >= 2 compradores distintos en el lote, el emisor debe firmar la mitad del lote, ningún
    comprador del lote puede ser ya cliente activo (entonces el emisor es un proveedor), el emisor no puede ser un cliente
    quitado a mano y la gestoría no puede tener desactivada el alta automática.
    """
    from collections import Counter, defaultdict
    docs = [f for f in (facturas or []) if f and not f.get("_lectura_fallida") and f.get("es_documento_fiscal", True)]
    if not docs:
        return None
    por_emisor = defaultdict(list)
    for f in docs:
        e = _normaliza_cif((f.get("emisor") or {}).get("cif_nif"))
        if e:
            por_emisor[e].append(f)
    for cif_e, fs in sorted(por_emisor.items(), key=lambda kv: -len(kv[1])):
        if len(fs) * 2 < len(docs):
            break
        if comprobar_cif(cif_e)[1]:
            continue
        if resolver_empresa_cliente_por_cif(tenant_id, [cif_e]) or cliente_quitado(tenant_id, cif_e):
            continue
        comp_lote = {_normaliza_cif((f.get("destinatario") or {}).get("cif_nif")) for f in fs} - {"", cif_e}
        if len(fs) < 3 or len(comp_lote) < 2:
            continue
        if any(resolver_empresa_cliente_por_cif(tenant_id, [c]) for c in comp_lote):
            continue
        if not alta_automatica_activa(tenant_id):
            continue
        nombre = Counter((f.get("emisor") or {}).get("nombre", "").strip() for f in fs).most_common(1)[0][0] or cif_e
        if alta_empresa_cliente(storage, tenant_id, nombre, cif_e).get("nueva"):
            crear_aviso(tenant_id, "empresa_nueva", f"{nombre} ({cif_e})")
            crear_aviso(tenant_id, "emisor_detectado",
                        f"Estas facturas las emite {nombre} ({cif_e}), así que lo hemos dado de alta como cliente y sus facturas van a su hoja de VENTAS; "
                        f"sus compradores no se dan de alta como clientes de la gestoría. Si no es cliente suyo, quítelo en Clientes.")
            log.info("Emisor %s detectado como cliente por repetirse en el lote (%d facturas, %d compradores)", cif_e, len(fs), len(comp_lote))
            return cif_e
    return None


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


def procesar_archivo(storage, tenant_id, contenido, nombre_original, extraer=None, dividir=None, progreso=None, parar=None):
    """
    Punto de entrada para los canales (correo, OneDrive, WhatsApp). Si el archivo es un PDF
    con varias páginas, lo separa en documentos sueltos (un lote escaneado trae varias
    facturas) y procesa cada uno; si no, equivale a procesar_documento.
    Devuelve una lista de resultados, uno por documento. Si algún documento falla, se
    procesan igualmente los demás y al final se vuelve a lanzar el error para que el canal
    reintente (las facturas ya anotadas no se duplican).
    """
    import dividir_pdf
    import formatos

    if formatos.tipo_real(contenido) not in ("pdf", "jpg", "png", "facturae"):
        # HEIC, WebP, TIFF, ZIP...: se convierte a PDF/JPG/PNG y cada archivo resultante sigue el camino normal.
        listos, fallidos = formatos.normalizar(nombre_original, contenido)
        resultados = []
        for nombre_n, contenido_n in listos:
            resultados += procesar_archivo(storage, tenant_id, contenido_n, nombre_n, extraer, dividir, progreso, parar)
        if fallidos:
            motivo = fallidos[0][1] if len(fallidos) == 1 else f"{len(fallidos)} archivos no legibles"
            log.info("'%s': no se pudieron leer %s", nombre_original, fallidos)
            resultados.append(_sin_identificar(storage, tenant_id, nombre_original, contenido, motivo))
        return resultados

    if formatos.tipo_real(contenido) == "facturae":
        from facturae import leer_facturae
        try:
            facturas = leer_facturae(contenido)
        except ValueError as e:
            return [_sin_identificar(storage, tenant_id, nombre_original, contenido, f"Facturae no legible ({str(e)[:40]})")]
        if len(facturas) > 1:
            return [_sin_identificar(storage, tenant_id, nombre_original, contenido, f"Facturae con {len(facturas)} facturas, repártalas")]
        return [_procesar_sin_repetir(storage, tenant_id, contenido, nombre_original, extraer or (lambda c: facturas[0]))]

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

    # Las lecturas con IA van varias a la vez; guardar y anotar sigue siendo de una en una, en orden.
    ya_vistas = []
    for parte in partes:
        try:
            ya_vistas.append(documento_ya_visto(tenant_id, _huella(parte)))
        except Exception:
            ya_vistas.append(False)
    if progreso:
        progreso("leyendo", 0, len(partes))
    leidas = leer_por_adelantado([None if v else p for v, p in zip(ya_vistas, partes)], extraer,
                                 (lambda h, t: progreso("leyendo", h, t)) if progreso else None)
    try:
        detectar_cliente_emisor(storage, tenant_id, leidas)
    except Exception:
        log.exception("No se pudo comprobar si el emisor del lote es un cliente")

    resultados, primer_error, en_espera = [], None, []
    for indice, (grupo, parte, leida) in enumerate(zip(grupos, partes, leidas)):
        if parar and parar():
            # La gestoría canceló: lo ya anotado se queda; el resto no se toca (y las lecturas hechas no se archivan).
            resultados.extend({"accion": "cancelada"} for _ in range(len(partes) - indice))
            break
        if progreso:
            progreso("guardando", indice, len(partes))
        rango = f"p{grupo[0]}" if len(grupo) == 1 else f"p{grupo[0]}-{grupo[-1]}"
        nombre_parte = f"{base}_{rango}.pdf"
        try:
            huella = _huella(parte)
            if documento_ya_visto(tenant_id, huella):  # reintento de un correo: esta parte ya se leyó
                log.info("'%s' %s: ya leída hace poco, se salta", nombre_original, rango)
                resultados.append({"accion": "ya_visto"})
                continue
            extraer_parte = (lambda _c, f=leida: f) if leida is not None else extraer
            res = procesar_documento(storage, tenant_id, parte, nombre_parte, extraer=extraer_parte, diferir_dudosas=True)
            if res.get("accion") != "en_espera" and not res.get("lectura_fallida"):
                marcar_documento_visto(tenant_id, huella)
        except ServicioIANoDisponible:
            raise   # se para todo el archivo: lo ya leído queda marcado como visto y el resto se lee cuando vuelva el servicio
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
                factura = {**factura, "sin_cif_destinatario": False,
                           "destinatario": {**(factura.get("destinatario") or {}), "cif_nif": cif_lote}}
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


def asignar_sin_identificar(storage, tenant_id, documento, cif_empresa):
    """
    La gestoría indica a qué cliente pertenece un documento de «Sin identificar». Se vuelve a leer, se le pone ese cliente como comprador
    y sigue el camino normal: al Excel si todo cuadra, a la Revisión de ese cliente si hay algo dudoso (ahí podrá corregirlo).
    """
    empresa = resolver_empresa_cliente_por_cif(tenant_id, [cif_empresa])
    if not empresa:
        return {"accion": "error", "motivo": "Ese cliente ya no existe."}
    carpeta = obtener_carpeta_sin_identificar(tenant_id)
    nombre_en_carpeta = nombre_archivo_destino(documento["nombre_archivo"], "REVISION", documento["motivo"])
    archivo = storage.buscar_archivo_por_nombre(carpeta, nombre_en_carpeta) if carpeta else None
    if not archivo:
        return {"accion": "error", "motivo": "No se encuentra el archivo en la carpeta «Sin identificar» (puede que lo haya movido o borrado)."}
    contenido = storage.descargar_archivo(archivo.id)
    factura = extraer_factura(contenido)
    if factura.get("_lectura_fallida"):
        return {"accion": "error", "motivo": "No se ha podido leer ahora mismo. Inténtelo de nuevo en un momento."}
    if factura.get("es_documento_fiscal") is False:
        return {"accion": "error", "motivo": "El documento no parece una factura ni un ticket."}
    factura = {**factura, "sin_cif_destinatario": False,
               "destinatario": {**(factura.get("destinatario") or {}), "cif_nif": empresa["cif_nif"]}}
    res = _archivar_con_reparacion(storage, tenant_id, contenido, documento["nombre_archivo"], factura)
    if res.get("accion") == "sin_identificar":
        return {"accion": "error", "motivo": res.get("motivo") or "No se ha podido asignar."}
    storage.eliminar_archivo(archivo.id)
    resolver_sin_identificar(tenant_id, documento["id"])
    return {**res, "empresa": empresa["nombre"]}


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

    # La ha revisado una persona: ya no valen la duda de la IA ni el motivo que la mandó a Revisión (p. ej. «las dos lecturas no coinciden»).
    factura = {k: v for k, v in factura.items() if k not in ("_motivo_revision", "relectura")}
    factura["confianza"] = "alta"
    factura["_confirmada_por_persona"] = True   # una persona ha mirado la factura: p. ej. vale que el proveedor no lleve CIF
    res = _guardar_factura(storage, tenant_id, empresa, original, contenido, factura, reintento=True)
    if res["accion"] == "procesada":
        try:  # el CIF que la persona ha escrito o corregido se recuerda para la próxima factura de ese proveedor
            antes = _normaliza_cif(((datos.get("factura") or {}).get("emisor") or {}).get("cif_nif"))
            ahora = _normaliza_cif((factura.get("emisor") or {}).get("cif_nif"))
            if ahora and ahora != antes:
                aprender_proveedor(tenant_id, (factura.get("emisor") or {}).get("nombre"), ahora)
        except Exception:
            log.exception("No se pudo recordar el proveedor")
        eliminar_factura_cache(tenant_id, factura_id)  # _guardar_factura ya ha creado su registro PROCESADA
        if archivo:
            storage.eliminar_archivo(archivo.id)  # el original ya está en Facturas
    elif res["accion"] == "duplicado_exacto":
        marcar_revisada(tenant_id, factura_id)
    return res


def marcar_venta_propia(storage, tenant_id, factura_id, aplicar_a_todas=False):
    """
    La gestoría indica que una factura en Revisión (emisor sin CIF) la ha emitido el propio cliente: se le pone
    el CIF del cliente como emisor y se reprocesa (va a su hoja de VENTAS y se recuerda el nombre para las siguientes).
    Con aplicar_a_todas, lo mismo para las demás de ese cliente con el mismo emisor sin CIF.
    Devuelve {"hechas": n, "fallidas": n, "duplicadas": n, "primera": resultado}.
    """
    from basededatos import listar_revisiones_mismo_emisor_sin_cif, _nombre_sin_cif_emisor
    r = obtener_revision(tenant_id, factura_id)
    if not r or r["destino"] != "REVISION" or not (r["datos"] or {}).get("factura"):
        return {"hechas": 0, "fallidas": 1, "duplicadas": 0, "primera": {"accion": "error", "motivo": "Ya no está pendiente."}}
    ids = [factura_id]
    if aplicar_a_todas:
        norm = _nombre_sin_cif_emisor(__import__("json").dumps(r["datos"]))
        if norm:
            ids += [i for i in listar_revisiones_mismo_emisor_sin_cif(tenant_id, r["empresa"]["id"], norm) if i != factura_id]
    out = {"hechas": 0, "fallidas": 0, "duplicadas": 0, "primera": None}
    for i in ids:
        ri = obtener_revision(tenant_id, i)
        if not ri or ri["destino"] != "REVISION" or not (ri["datos"] or {}).get("factura"):
            out["fallidas"] += 1
            continue
        factura = dict(ri["datos"]["factura"])
        emisor = dict(factura.get("emisor") or {})
        emisor["cif_nif"] = ri["empresa"]["cif_nif"]
        factura["emisor"] = emisor
        try:
            res = reprocesar_revision(storage, tenant_id, i, factura)
        except Exception:
            log.exception("Fallo marcando venta propia %s", i)
            res = {"accion": "error"}
        if i == factura_id:
            out["primera"] = res
        if res["accion"] == "procesada":
            out["hechas"] += 1
        elif res["accion"] == "duplicado_exacto":
            out["duplicadas"] += 1
        else:
            out["fallidas"] += 1
    return out
