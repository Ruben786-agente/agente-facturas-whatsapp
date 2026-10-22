# -*- coding: utf-8 -*-
"""
Lectura directa de Facturae (el XML oficial de la factura electrónica española, versiones 3.x, también firmado .xsig).
Los datos ya vienen estructurados, así que se leen sin IA: coste cero y sin riesgo de confundir un 6 con un 8.
Devuelve el mismo formato de diccionario que la lectura con IA, para que siga el camino de siempre (validaciones, Excel...).
"""

import re
import xml.etree.ElementTree as ET


def es_facturae(contenido):
    cabeza = contenido[:4000].lstrip(b"\xef\xbb\xbf \t\r\n")
    return cabeza[:1] == b"<" and b"Facturae" in cabeza and b"<!DOCTYPE" not in contenido[:4000].upper() \
        and b"<!ENTITY" not in contenido.upper()


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _hijo(el, *camino):
    for nombre in camino:
        if el is None:
            return None
        el = next((h for h in el if _local(h.tag) == nombre), None)
    return el


def _hijos(el, nombre):
    return [h for h in (el if el is not None else []) if _local(h.tag) == nombre]


def _txt(el, *camino):
    h = _hijo(el, *camino)
    return (h.text or "").strip() if h is not None and h.text else ""


def _num(el, *camino):
    t = _txt(el, *camino)
    try:
        return round(float(t), 2) if t else 0.0
    except ValueError:
        raise ValueError(f"importe no numérico en Facturae: {t!r}")


def _pct(el, *camino):
    t = _txt(el, *camino)
    return float(t) if t else 0.0


def _parte(parte):
    """Vendedor o comprador: NIF, nombre y domicilio."""
    nif = re.sub(r"[\s.\-]", "", _txt(parte, "TaxIdentification", "TaxIdentificationNumber")).upper()
    if len(nif) == 11 and nif.startswith("ES"):
        nif = nif[2:]
    empresa = _hijo(parte, "LegalEntity")
    persona = _hijo(parte, "Individual")
    if empresa is not None:
        nombre = _txt(empresa, "CorporateName") or _txt(empresa, "TradeName")
        dom = _hijo(empresa, "AddressInSpain") or _hijo(empresa, "OverseasAddress")
    else:
        nombre = " ".join(x for x in (_txt(persona, "Name"), _txt(persona, "FirstSurname"), _txt(persona, "SecondSurname")) if x)
        dom = _hijo(persona, "AddressInSpain") or _hijo(persona, "OverseasAddress")
    return {"cif_nif": nif, "nombre": nombre, "domicilio": _txt(dom, "Address"), "localidad": _txt(dom, "Town"),
            "cp": _txt(dom, "PostCode")}


def leer_facturae(contenido):
    """Lista de facturas (casi siempre una) en el formato de la lectura con IA. Lanza ValueError si el XML no se entiende."""
    try:
        raiz = ET.fromstring(contenido)
    except ET.ParseError as e:
        raise ValueError(f"XML no válido: {e}")
    if _local(raiz.tag) != "Facturae":
        raise ValueError("no es un Facturae")
    partes = _hijo(raiz, "Parties")
    vendedor, comprador = _parte(_hijo(partes, "SellerParty")), _parte(_hijo(partes, "BuyerParty"))
    resultado = []
    for inv in _hijos(_hijo(raiz, "Invoices"), "Invoice"):
        problemas = []
        cab = _hijo(inv, "InvoiceHeader")
        num = _txt(cab, "InvoiceSeriesCode") + _txt(cab, "InvoiceNumber")
        d = _txt(inv, "InvoiceIssueData", "IssueDate")
        fecha = f"{d[8:10]}/{d[5:7]}/{d[0:4]}" if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", d) else ""

        desgloses = {}
        for t in _hijos(_hijo(inv, "TaxesOutputs"), "Tax"):
            if _txt(t, "TaxTypeCode") not in ("", "01"):
                problemas.append("impuesto distinto del IVA (IGIC o IPSI): revíselo a mano")
            pct = _pct(t, "TaxRate")
            g = desgloses.setdefault(pct, {"base": 0.0, "pct_iva": pct, "cuota_iva": 0.0, "pct_recargo": None,
                                           "cuota_recargo": None, "pct_retencion": None, "cuota_retencion": None})
            g["base"] = round(g["base"] + _num(t, "TaxableBase", "TotalAmount"), 2)
            g["cuota_iva"] = round(g["cuota_iva"] + _num(t, "TaxAmount", "TotalAmount"), 2)
            if _txt(t, "EquivalenceSurcharge"):
                g["pct_recargo"] = _pct(t, "EquivalenceSurcharge")
                g["cuota_recargo"] = round((g["cuota_recargo"] or 0) + _num(t, "EquivalenceSurchargeAmount", "TotalAmount"), 2)
        lista = list(desgloses.values())

        for t in _hijos(_hijo(inv, "TaxesWithheld"), "Tax"):
            base_ret = _num(t, "TaxableBase", "TotalAmount")
            destino = next((g for g in lista if abs(g["base"] - base_ret) <= 0.01), lista[0] if len(lista) == 1 else None)
            if destino is None or destino["pct_retencion"] is not None:
                problemas.append("retención de IRPF que no se puede asignar a un tipo de IVA: revísela a mano")
                continue
            destino["pct_retencion"] = _pct(t, "TaxRate")
            destino["cuota_retencion"] = _num(t, "TaxAmount", "TotalAmount")

        tipo_doc = _txt(cab, "InvoiceDocumentType")
        f = {
            "es_documento_fiscal": True, "fecha_factura": fecha, "num_factura": num,
            "emisor": vendedor, "destinatario": comprador, "desgloses": lista,
            "total_factura": _num(inv, "InvoiceTotals", "InvoiceTotal"),
            "confianza": "alta" if not problemas else "baja",
            "es_factura_simplificada": tipo_doc == "FA", "sin_cif_destinatario": not comprador["cif_nif"],
            "formato_ticket_tpv": False, "_origen": "facturae",
        }
        if problemas:
            f["_motivo_revision"] = problemas[0]
        resultado.append(f)
    if not resultado:
        raise ValueError("el Facturae no contiene facturas")
    return resultado
