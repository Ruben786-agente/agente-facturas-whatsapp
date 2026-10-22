# -*- coding: utf-8 -*-
"""
Comprobaciones automáticas sobre lo que lee la IA, pensadas para cazar el error típico de lectura (un 6 por un 8, un 1 por un 7...)
antes de que llegue al Excel. Son aritmética y normas fiscales, no opinión de la IA, así que no se equivocan igual que ella:

  - Letra o dígito de control del NIF, NIE y CIF.
  - Cuota de IVA = base x porcentaje (y lo mismo con recargo de equivalencia y retención).
  - Porcentajes de IVA y de recargo que existen.
  - Fecha verosímil (ni en el futuro ni de hace años).
  - Que haya número de factura.

Cualquier fallo manda la factura a Revisión con el motivo, nunca se anota en el Excel. (La suma base + cuota = total ya se
comprueba aparte, en generar_excel_mieos.)
"""

import re
from datetime import datetime, timedelta

LETRAS_NIF = "TRWAGMYFPDXBNJZSQVHLCKE"
LETRAS_CIF = "JABCDEFGHI"
IVA_VALIDOS = {0.0, 4.0, 5.0, 10.0, 21.0}
RECARGO_DE = {21.0: 5.2, 10.0: 1.4, 5.0: 0.62, 4.0: 0.5, 0.0: 0.0}
MAX_ANTIGUEDAD = timedelta(days=366 * 5)
MARGEN_FUTURO = timedelta(days=7)


def _limpia(cif):
    cif = re.sub(r"[\s.\-]", "", (cif or "")).upper()
    return cif[2:] if len(cif) == 11 and cif.startswith("ES") else cif


def control_nif_cif_correcto(cif):
    """True / False si el documento tiene formato español reconocible y el control es / no es correcto.
    None si no se puede comprobar (vacío, extranjero, o un tipo cuyo control no se verifica aquí)."""
    c = _limpia(cif)
    if re.fullmatch(r"\d{8}[A-Z]", c):                                   # NIF de persona física
        return LETRAS_NIF[int(c[:8]) % 23] == c[8]
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", c):                              # NIE
        return LETRAS_NIF[int(str("XYZ".index(c[0])) + c[1:8]) % 23] == c[8]
    if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", c):             # CIF de sociedades y entidades
        d = c[1:8]
        pares = sum(int(d[i]) for i in (1, 3, 5))
        impares = sum(sum(divmod(int(d[i]) * 2, 10)) for i in (0, 2, 4, 6))
        control = (10 - (pares + impares) % 10) % 10
        return c[8] in (str(control), LETRAS_CIF[control])
    return None


def _dinero(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return None


def _tolerancia(esperado):
    # un redondeo por línea puede dar unos céntimos; un dígito mal leído da mucho más
    return max(0.06, 0.002 * abs(esperado))


def problemas_factura(factura, hoy=None):
    """Lista de motivos (en usted, cortos) por los que esta lectura no debe fiarse. Vacía si todo es coherente."""
    problemas = []
    hoy = hoy or datetime.now()

    for rol, clave in (("emisor", "emisor"), ("comprador", "destinatario")):
        cif = (factura.get(clave) or {}).get("cif_nif")
        if control_nif_cif_correcto(cif) is False:
            problemas.append(f"el NIF/CIF del {rol} no es válido ({_limpia(cif)}): posible error de lectura")

    if not (factura.get("num_factura") or "").strip():
        problemas.append("no se ha leído el número de factura")

    try:
        fecha = datetime.strptime(factura.get("fecha_factura") or "", "%d/%m/%Y")
        if fecha > hoy + MARGEN_FUTURO:
            problemas.append(f"la fecha ({factura['fecha_factura']}) es futura: posible error de lectura")
        elif fecha < hoy - MAX_ANTIGUEDAD:
            problemas.append(f"la fecha ({factura['fecha_factura']}) es de hace más de 5 años: posible error de lectura")
    except ValueError:
        problemas.append("fecha de la factura ilegible")

    for d in factura.get("desgloses") or []:
        base, cuota, pct = _dinero(d.get("base")), _dinero(d.get("cuota_iva")), _dinero(d.get("pct_iva"))
        if None in (base, cuota, pct):
            problemas.append("hay un importe del desglose que no es un número")
            continue
        if pct not in IVA_VALIDOS:
            problemas.append(f"porcentaje de IVA poco habitual ({pct:g} %)")
        esperado = base * pct / 100
        if abs(cuota - esperado) > _tolerancia(esperado):
            problemas.append(f"la cuota de IVA ({cuota:.2f}) no es el {pct:g} % de la base ({base:.2f}): posible error de lectura")
        pct_rec, cuota_rec = _dinero(d.get("pct_recargo")), _dinero(d.get("cuota_recargo"))
        if pct_rec:
            if RECARGO_DE.get(pct) != pct_rec:
                problemas.append(f"recargo de equivalencia del {pct_rec:g} % que no corresponde a un IVA del {pct:g} %")
            elif cuota_rec is None or abs(cuota_rec - base * pct_rec / 100) > _tolerancia(base * pct_rec / 100):
                problemas.append("la cuota del recargo de equivalencia no cuadra con la base")
        pct_ret, cuota_ret = _dinero(d.get("pct_retencion")), _dinero(d.get("cuota_retencion"))
        if pct_ret and (cuota_ret is None or abs(cuota_ret - base * pct_ret / 100) > _tolerancia(base * pct_ret / 100)):
            problemas.append("la cuota de la retención no cuadra con la base")
    return problemas
