# -*- coding: utf-8 -*-
"""
Borrador ORIENTATIVO del modelo 303 (IVA trimestral) y del 130 (pago fraccionado del IRPF de autónomos),
calculado a partir de las facturas ya anotadas en los Excel de miEOS. No presenta nada: es una ayuda para la gestoría, que lo revisa.

Supuestos (se muestran siempre en pantalla):
  - Todo el IVA soportado se considera deducible (no sabemos qué gastos no lo son).
  - 130: método de estimación directa; ingresos y gastos = bases imponibles de VENTAS y COMPRAS desde el 1 de enero.
    Los pagos de trimestres anteriores se calculan con el mismo criterio. No incluye el 5 % de difícil justificación ni deducciones especiales.
"""
from datetime import datetime

from exportadores import leer_facturas, _fecha, _r

TRIMESTRES = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
ES_PERSONA = lambda cif: bool(cif) and (cif[0].isdigit() or cif[0] in "XYZKLM")


def _en_rango(f, desde, hasta):
    try:
        d = _fecha(f["fecha"])
    except Exception:
        return False
    return desde <= (d.month) <= hasta and d.year == f["_anio"]


def juntar_facturas(excels, anio):
    """Une las facturas de varios Excel sin repetir ninguna (por si un mismo Excel se ha leído dos veces)."""
    vistas, resultado = set(), []
    for contenido in excels:
        for f in leer_facturas(contenido):
            clave = (f["tipo"], str(f["fecha"]), f["num"], f["cif"])
            if clave in vistas:
                continue
            vistas.add(clave)
            f["_anio"] = anio
            resultado.append(f)
    return resultado


def _iva(facturas, tipo, mes_ini, mes_fin):
    por_tipo, retenciones = {}, 0.0
    for f in facturas:
        if f["tipo"] != tipo or not _en_rango(f, mes_ini, mes_fin):
            continue
        retenciones += f["ret_cuota"]
        for d in f["desgloses"]:
            t = por_tipo.setdefault(round(d["pct"], 2), {"base": 0.0, "cuota": 0.0, "n": 0})
            t["base"] += d["base"]
            t["cuota"] += d["cuota"] + d["cuota_rec"]
    for t in por_tipo.values():
        t["base"], t["cuota"] = _r(t["base"]), _r(t["cuota"])
    return por_tipo, _r(retenciones)


def modelo_303(facturas, trimestre):
    ini, fin = TRIMESTRES[trimestre]
    rep, _ = _iva(facturas, "VENTAS", ini, fin)
    sop, _ = _iva(facturas, "COMPRAS", ini, fin)
    casillas_rep = {21.0: ("01", "03"), 10.0: ("04", "06"), 4.0: ("07", "09")}
    filas_rep = []
    for pct in sorted(rep, reverse=True):
        base, cuota = rep[pct]["base"], rep[pct]["cuota"]
        if pct in casillas_rep:
            filas_rep.append({"casilla": casillas_rep[pct][0] + " / " + casillas_rep[pct][1], "texto": f"IVA repercutido al {pct:g} %", "base": base, "cuota": cuota})
        else:
            filas_rep.append({"casilla": "—", "texto": f"Ventas al {pct:g} % (exentas o tipo no estándar: revisar casilla)", "base": base, "cuota": cuota})
    devengado = _r(sum(t["cuota"] for t in rep.values()))
    base_sop = _r(sum(t["base"] for t in sop.values()))
    cuota_sop = _r(sum(t["cuota"] for t in sop.values()))
    return {"trimestre": trimestre, "repercutido": filas_rep, "total_devengado": devengado,
            "soportado_base": base_sop, "soportado_cuota": cuota_sop, "resultado": _r(devengado - cuota_sop)}


def modelo_130(facturas, trimestre):
    """Acumulado desde el 1 de enero hasta el final del trimestre, menos lo de trimestres anteriores."""
    def acumulado(t):
        fin = TRIMESTRES[t][1]
        ing, _ = _iva(facturas, "VENTAS", 1, fin)
        gas, _ = _iva(facturas, "COMPRAS", 1, fin)
        _, ret = _iva(facturas, "VENTAS", 1, fin)
        ingresos = _r(sum(v["base"] for v in ing.values()))
        gastos = _r(sum(v["base"] for v in gas.values()))
        neto = _r(ingresos - gastos)
        pago = _r(max(neto, 0) * 0.20)
        return ingresos, gastos, neto, pago, ret
    ingresos, gastos, neto, pago20, ret = acumulado(trimestre)
    anteriores = 0.0
    for t in range(1, trimestre):
        _, _, _, p, r = acumulado(t)
        anteriores += max(p - r - anteriores, 0)   # lo que se habría ingresado en ese trimestre
    anteriores = _r(anteriores)
    resultado = _r(max(pago20 - ret - anteriores, 0))
    return {"trimestre": trimestre, "ingresos": ingresos, "gastos": gastos, "neto": neto, "pago20": pago20,
            "retenciones": ret, "anteriores": anteriores, "resultado": resultado}
