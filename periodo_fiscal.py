# -*- coding: utf-8 -*-
"""Calcula a qué trimestre fiscal pertenece una factura, según su fecha."""

from datetime import datetime


def calcular_periodo_trimestral(fecha_factura: str) -> str:
    fecha = datetime.strptime(fecha_factura, "%d/%m/%Y")
    trimestre = (fecha.month - 1) // 3 + 1
    return f"Trimestre {trimestre} - {fecha.year}"


def periodo_a_slug(periodo: str) -> str:
    return periodo.replace(" - ", "_").replace(" ", "_")
