# -*- coding: utf-8 -*-
"""A qué periodo (mes o trimestre, según lo que use la gestoría) pertenece una factura, según su fecha."""

import re
from datetime import datetime

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]
PERIODICIDADES = ("mensual", "trimestral")
PERIODICIDAD_POR_DEFECTO = "mensual"


def calcular_periodo_trimestral(fecha_factura: str) -> str:
    fecha = datetime.strptime(fecha_factura, "%d/%m/%Y")
    trimestre = (fecha.month - 1) // 3 + 1
    return f"Trimestre {trimestre} - {fecha.year}"


def calcular_periodo_mensual(fecha_factura: str) -> str:
    fecha = datetime.strptime(fecha_factura, "%d/%m/%Y")
    return f"{MESES[fecha.month - 1]} {fecha.year}"


def calcular_periodo(fecha_factura: str, periodicidad: str = PERIODICIDAD_POR_DEFECTO) -> str:
    if periodicidad == "trimestral":
        return calcular_periodo_trimestral(fecha_factura)
    return calcular_periodo_mensual(fecha_factura)


def periodo_para(tenant_id, fecha_factura: str) -> str:
    """El periodo de una factura según la periodicidad que tiene elegida la gestoría."""
    from basededatos import obtener_periodicidad
    return calcular_periodo(fecha_factura, obtener_periodicidad(tenant_id))


def periodo_a_slug(periodo: str) -> str:
    """Parte del nombre del Excel: 'Trimestre_1_2026' o, en mensual, '2026-10' (se ordenan bien en la carpeta)."""
    m = re.fullmatch(r"(\w+) (\d{4})", periodo)
    if m and m.group(1) in MESES:
        return f"{m.group(2)}-{MESES.index(m.group(1)) + 1:02d}"
    return periodo.replace(" - ", "_").replace(" ", "_")


def nombre_excel(cif_empresa: str, periodo: str) -> str:
    return f"Export_{cif_empresa}_{periodo_a_slug(periodo)}.xlsx"


def nombres_excel_posibles(cif_empresa: str, periodo: str) -> list:
    """Nombre del Excel de un periodo y, si es un mes, también el del trimestre que lo contiene: los Excel que se
    crearon cuando la gestoría trabajaba por trimestres siguen con ese nombre y hay que poder encontrarlos."""
    nombres = [nombre_excel(cif_empresa, periodo)]
    m = re.fullmatch(r"(\w+) (\d{4})", periodo)
    if m and m.group(1) in MESES:
        trimestre = (MESES.index(m.group(1))) // 3 + 1
        nombres.append(nombre_excel(cif_empresa, f"Trimestre {trimestre} - {m.group(2)}"))
    return nombres
