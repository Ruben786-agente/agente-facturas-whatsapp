# -*- coding: utf-8 -*-
"""Avisa de proveedores que parecen el mismo con dos CIF distintos (CIF mal leído, o el mismo proveedor dado de alta dos veces).
Solo SUGIERE: no fusiona nada. Cada pareja se avisa una vez cada 90 días."""
import logging

log = logging.getLogger("proveedores_duplicados")


def buscar_duplicados(proveedores):
    """proveedores: [{'cif_nif','nombre'}]. Devuelve parejas (a, b) que parecen el mismo proveedor con distinto CIF."""
    from procesamiento import _distancia, _normaliza_cif, _palabras
    unicos = {}
    for p in proveedores:
        cif = _normaliza_cif(p.get("cif_nif"))
        if cif and cif not in unicos:
            unicos[cif] = p.get("nombre") or ""
    lista = sorted(unicos.items())
    parejas = []
    for i, (c1, n1) in enumerate(lista):
        for c2, n2 in lista[i + 1:]:
            w1, w2 = _palabras(n1), _palabras(n2)
            comunes = w1 & w2
            mismo_nombre = bool(w1) and w1 == w2
            cif_parecido = _distancia(c1, c2) <= 1 and bool(comunes)
            nombre_casi_igual = bool(w1 and w2) and len(comunes) >= 2 and len(comunes) / max(len(w1), len(w2)) >= 0.75 and _distancia(c1, c2) <= 3
            if mismo_nombre or cif_parecido or nombre_casi_igual:
                parejas.append(({"cif_nif": c1, "nombre": n1}, {"cif_nif": c2, "nombre": n2}))
    return parejas


def avisar_duplicados(tenant_id):
    """Crea un aviso informativo en el panel por cada pareja nueva. Devuelve cuántos avisos nuevos."""
    from basededatos import (crear_aviso, notificacion_reciente, proveedores_conocidos, registrar_notificacion)
    nuevos = 0
    for a, b in buscar_duplicados(proveedores_conocidos(tenant_id)):
        clave = f'dup-{a["cif_nif"]}-{b["cif_nif"]}'
        if notificacion_reciente(tenant_id, clave, 24 * 90):
            continue
        registrar_notificacion(tenant_id, clave)
        crear_aviso(tenant_id, "proveedor_duplicado",
                    f'Posible proveedor repetido: «{a["nombre"] or "sin nombre"}» ({a["cif_nif"]}) y «{b["nombre"] or "sin nombre"}» ({b["cif_nif"]}). '
                    "Compruebe cuál es el CIF correcto: si uno está mal leído, corríjalo desde «Corregir y añadir» en la factura afectada.")
        nuevos += 1
    return nuevos
