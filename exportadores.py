# -*- coding: utf-8 -*-
"""
Convierte el Excel de miEOS (hojas COMPRAS y VENTAS, una fila por tipo de IVA) a los ficheros de importación de otros programas.
La fuente única sigue siendo el Excel de miEOS: así el agente no cambia, solo el último paso.

  ContaSOL (formato oficial «Importación Excel/Calc» de Software DELSOL): MAE (cuentas), APU (asientos), IVS e IVR (libros de IVA), en .xls.
  Sage 50 (importador oficial de facturas, Excel): un libro de facturas recibidas y otro de emitidas.
  Holded (plantilla oficial «Importar compras», Excel): solo facturas recibidas; las emitidas usan otra plantilla de Holded (pendiente).

Cuentas: no se conoce el plan contable de la gestoría, así que cada proveedor/cliente recibe una subcuenta ESTABLE derivada de su CIF
(400/430 + dígitos del CIF), igual en todos los meses. Las ventas sin NIF (alumnos, particulares) van a la subcuenta genérica de clientes.
"""
import zipfile
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook, load_workbook

PROGRAMAS_EXPORTABLES = {"contasol": "ContaSOL", "sage50": "Sage 50", "holded": "Holded"}

# Cuentas del PGC (prefijos). Se rellenan con ceros hasta los dígitos de la empresa.
CTA_GASTO, CTA_VENTA = "600", "700"
CTA_IVA_SOPORTADO, CTA_IVA_REPERCUTIDO = "472", "477"
CTA_PROVEEDORES, CTA_CLIENTES = "400", "430"
CTA_RET_PRACTICADA, CTA_RET_SOPORTADA = "4751", "473"
DIGITOS = {"contasol": 10, "sage50": 8}


def _cuenta(prefijo, digitos, sufijo=0):
    resto = digitos - len(prefijo)
    return (prefijo + str(int(sufijo)).zfill(resto)[-resto:]).ljust(digitos, "0")[:digitos]


def _sufijo_cif(cif, ocupados, digitos):
    """Número estable derivado del CIF (mismo CIF, misma subcuenta, todos los meses). Si chocaran dos, el segundo avanza."""
    base = 0
    for ch in (cif or "").upper():
        base = (base * 131 + ord(ch)) % (10 ** (digitos - 3))
    base = base or 1
    while base in ocupados and ocupados[base] != cif:
        base = (base % (10 ** (digitos - 3) - 1)) + 1
    ocupados[base] = cif
    return base


def leer_facturas(contenido_xlsx):
    """Agrupa las filas del Excel de miEOS por factura: [{tipo, fecha, num, cif, nombre, desgloses[], retencion, total, ...}]."""
    wb = load_workbook(BytesIO(contenido_xlsx), data_only=True)
    facturas = []
    for hoja, tipo in (("COMPRAS", "COMPRAS"), ("VENTAS", "VENTAS")):
        if hoja not in wb.sheetnames:
            continue
        por_clave = {}
        for f in wb[hoja].iter_rows(min_row=4, values_only=True):
            if not f or len(f) < 19 or not f[2]:
                continue
            clave = (str(f[1]), str(f[2]))
            fa = por_clave.get(clave)
            if not fa:
                fa = por_clave[clave] = {"tipo": tipo, "fecha": f[1], "num": str(f[2]), "cif": (f[4] or "").strip().upper(),
                                          "nombre": f[5] or "", "total": float(f[18] or 0), "desgloses": [], "ret_cuota": 0.0, "ret_pct": 0.0}
                facturas.append(fa)
            num = lambda v: float(v) if isinstance(v, (int, float)) else 0.0
            fa["desgloses"].append({"base": num(f[9]), "pct": num(f[10]), "cuota": num(f[11]), "pct_rec": num(f[12]), "cuota_rec": num(f[13])})
            fa["ret_cuota"] += num(f[15])
            fa["ret_pct"] = max(fa["ret_pct"], num(f[14]))
    return facturas


def _fecha(valor):
    if hasattr(valor, "year"):
        return datetime(valor.year, valor.month, valor.day)
    return datetime.strptime(str(valor).strip(), "%d/%m/%Y")


def _r(v):
    return round(float(v or 0), 2)


# ---------------------------------------------------------------- ContaSOL
def _xls(filas, cabecera=None):
    import xlwt
    libro = xlwt.Workbook(encoding="utf-8")
    hoja = libro.add_sheet("Hoja1")
    estilo_fecha = xlwt.easyxf(num_format_str="DD/MM/YYYY")
    # El formato oficial no lleva fila de títulos: cada registro va en su fila desde la primera.
    for i, fila in enumerate(filas):
        for j, v in enumerate(fila):
            if v is None or v == "":
                continue
            if isinstance(v, datetime):
                hoja.write(i, j, v, estilo_fecha)
            else:
                hoja.write(i, j, v)
    b = BytesIO()
    libro.save(b)
    return b.getvalue()


def a_contasol(contenido_xlsx, ejercicio_diario=1):
    d = DIGITOS["contasol"]
    facturas = leer_facturas(contenido_xlsx)
    ocup = {}
    cuentas_nuevas = {}   # cuenta -> descripción
    apu, ivs, ivr = [], [], []
    asiento, cod_iva = 0, {"S": 0, "R": 0}
    for fa in sorted(facturas, key=lambda x: (_fecha(x["fecha"]), x["num"])):
        compra = fa["tipo"] == "COMPRAS"
        if fa["cif"]:
            tercero = _cuenta(CTA_PROVEEDORES if compra else CTA_CLIENTES, d, _sufijo_cif(fa["cif"], ocup, d))
        else:
            tercero = _cuenta(CTA_PROVEEDORES if compra else CTA_CLIENTES, d, 0)
        cuentas_nuevas[tercero] = fa["nombre"] or ("PROVEEDOR GENÉRICO" if compra else "CLIENTE GENÉRICO")
        base_t = _r(sum(x["base"] for x in fa["desgloses"]))
        iva_t = _r(sum(x["cuota"] + x["cuota_rec"] for x in fa["desgloses"]))
        ret = _r(fa["ret_cuota"])
        total = _r(fa["total"])
        asiento += 1
        fecha = _fecha(fa["fecha"])
        concepto = (f'{fa["num"]} {fa["nombre"]}').strip()[:60]
        doc = fa["num"][:30]
        orden = [0]
        tipo_iva = "S" if compra else "R"
        cod_iva[tipo_iva] += 1
        cod = cod_iva[tipo_iva]

        def linea(cuenta, debe=0.0, haber=0.0, iva=False):
            orden[0] += 1
            apu.append([ejercicio_diario, fecha, asiento, orden[0], int(cuenta), 0, concepto, doc, _r(debe), _r(haber), "E", 0,
                        tipo_iva if iva else "", cod if iva else "", "", "", ""])
        if compra:
            linea(_cuenta(CTA_GASTO, d), debe=base_t)
            if iva_t:
                linea(_cuenta(CTA_IVA_SOPORTADO, d), debe=iva_t, iva=True)
            if ret:
                linea(_cuenta(CTA_RET_PRACTICADA, d), haber=ret)
            linea(tercero, haber=total)
        else:
            linea(tercero, debe=total)
            if ret:
                linea(_cuenta(CTA_RET_SOPORTADA, d), debe=ret)
            linea(_cuenta(CTA_VENTA, d), haber=base_t)
            if iva_t:
                linea(_cuenta(CTA_IVA_REPERCUTIDO, d), haber=iva_t, iva=True)
        # Libro de IVA: hasta 3 tipos por factura en las columnas oficiales (Base 1-3, % 1-3, cuota 1-3)
        ds = sorted(fa["desgloses"], key=lambda x: -x["pct"])
        extra_exento = _r(sum(x["base"] for x in ds[3:] if x["pct"] == 0))
        ds = ds[:3]
        pad = lambda lista: list(lista) + [0] * (3 - len(lista))
        bases = pad([_r(x["base"]) for x in ds])
        pcts = pad([x["pct"] for x in ds])
        cuotas = pad([_r(x["cuota"]) for x in ds])
        pct_rec = pad([x["pct_rec"] for x in ds])
        cuo_rec = pad([_r(x["cuota_rec"]) for x in ds])
        if compra:
            f = [None] * 108                      # IVS: columnas A..DD del formato oficial
            f[0], f[1], f[2], f[3], f[4] = cod, 1, fecha, int(tercero), fa["num"][:30]
            f[5], f[6], f[7], f[8] = (fa["nombre"] or "")[:100], fa["cif"], 0, 0
            f[9:12], f[12:15], f[15:18], f[18:21], f[21:24] = bases, pcts, pct_rec, cuotas, cuo_rec
            f[24] = total
            f[44] = 1 if fa["cif"] else 0         # incluir en el modelo 347
            f[45], f[46] = fa["ret_pct"], ret     # % e importe de retención
            if extra_exento:
                f[50] = extra_exento
            ivs.append(f)
        else:
            f = [None] * 102                      # IVR: columnas A..CX del formato oficial
            f[0], f[1], f[2], f[3], f[4] = cod, 1, fecha, tercero, fa["num"][:30]
            f[5], f[6], f[7] = (fa["nombre"] or "")[:40], fa["cif"], 0
            f[8:11], f[11:14], f[14:17], f[17:20], f[20:23] = bases, pcts, pct_rec, cuotas, cuo_rec
            f[23] = total
            f[42] = 1 if fa["cif"] else 0
            f[43], f[44] = fa["ret_pct"], ret
            if extra_exento:
                f[48] = extra_exento
            ivr.append(f)
    mae = [[int(c), n[:40]] for c, n in sorted(cuentas_nuevas.items())]
    for pref, nom in ((CTA_GASTO, "COMPRAS Y GASTOS"), (CTA_VENTA, "VENTAS"), (CTA_IVA_SOPORTADO, "H.P. IVA SOPORTADO"),
                      (CTA_IVA_REPERCUTIDO, "H.P. IVA REPERCUTIDO"), (CTA_RET_PRACTICADA, "H.P. ACREEDORA RETENCIONES"),
                      (CTA_RET_SOPORTADA, "H.P. RETENCIONES Y PAGOS A CUENTA")):
        mae.append([int(_cuenta(pref, d)), nom])
    archivos = [("1_MAE.xls", _xls(mae)), ("2_APU.xls", _xls(apu))]
    if ivs:
        archivos.append(("3_IVS.xls", _xls(ivs)))
    if ivr:
        archivos.append(("4_IVR.xls", _xls(ivr)))
    return archivos


LEEME_CONTASOL = """IMPORTAR EN CONTASOL (formato oficial «Importación Excel/Calc»)
Utilidades > Importaciones > Ficheros > XLS/XLSX. Importe en este orden:
  1) 1_MAE.xls  cuentas (proveedores, clientes y cuentas de gasto, venta e IVA)
  2) 2_APU.xls  asientos
  3) 3_IVS.xls  libro de IVA soportado (si hay compras)
  4) 4_IVR.xls  libro de IVA repercutido (si hay ventas)
Antes: todas las cuentas de la empresa deben tener {d} dígitos (Empresa > Configuración > Vínculo contable).
Cada proveedor/cliente recibe siempre la misma subcuenta (derivada de su CIF). Las ventas sin NIF van a la cuenta genérica de clientes.
Si ya tiene esas cuentas con otro número, importe primero y unifique. Si el programa avisa de cuentas existentes, ignore el MAE.
Primera vez: pruebe con un solo cliente y revise asientos y libros de IVA antes de importar el resto. No importe dos veces el mismo fichero.
"""


# ---------------------------------------------------------------- Sage 50
def a_sage50(contenido_xlsx):
    d = DIGITOS["sage50"]
    facturas = leer_facturas(contenido_xlsx)
    ocup = {}
    archivos = []
    for tipo, nombre in (("COMPRAS", "facturas_recibidas.xlsx"), ("VENTAS", "facturas_emitidas.xlsx")):
        fs = [f for f in facturas if f["tipo"] == tipo]
        if not fs:
            continue
        wb = Workbook()
        ws = wb.active
        ws.title = "Facturas"
        ws.append(["Cuenta", "Fecha", "Factura", "BaseIva", "ImporteIva", "TipoIva", "Contrapartida", "Importe contrapartida", "Referencia"])
        for fa in sorted(fs, key=lambda x: (_fecha(x["fecha"]), x["num"])):
            if fa["cif"]:
                cuenta = _cuenta(CTA_PROVEEDORES if tipo == "COMPRAS" else CTA_CLIENTES, d, _sufijo_cif(fa["cif"], ocup, d))
            else:
                cuenta = _cuenta(CTA_PROVEEDORES if tipo == "COMPRAS" else CTA_CLIENTES, d, 0)
            contra = _cuenta(CTA_GASTO if tipo == "COMPRAS" else CTA_VENTA, d)
            for ds in fa["desgloses"]:
                ws.append([int(cuenta), _fecha(fa["fecha"]), fa["num"], _r(ds["base"]), _r(ds["cuota"] + ds["cuota_rec"]), None,
                           int(contra), _r(ds["base"]), (fa["nombre"] or "")[:40]])
        for fila in ws.iter_rows(min_row=2, min_col=2, max_col=2):
            fila[0].number_format = "DD/MM/YYYY"
        b = BytesIO()
        wb.save(b)
        archivos.append((nombre, b.getvalue()))
    return archivos


LEEME_SAGE50 = """IMPORTAR EN SAGE 50 (importador oficial de asientos y facturas, Excel)
Contabilidad > Importador de asientos de facturas. Importe primero facturas_recibidas.xlsx y después facturas_emitidas.xlsx.
Pulse «Capturar», revise las líneas en naranja (indican el problema) e importe las correctas.
Hay una fila por factura y tipo de IVA. Las subcuentas de proveedor/cliente son estables (derivadas del CIF) y deben existir en la empresa;
configure también las cuentas por defecto y las equivalencias de tipo de IVA en la pantalla de configuración del importador.
Este importador no lleva retenciones de IRPF: si hay facturas con retención, contabilice esa parte a mano.
Primera vez: pruebe con un solo cliente. No importe dos veces el mismo fichero.
"""


# ---------------------------------------------------------------- Holded
CABECERA_HOLDED = ["Num factura", "Fecha dd/mm/yyyy", "Fecha de vencimiento dd/mm/yyyy", "Fecha deducción dd/mm/yyyy", "Descripción",
                   "Nombre del contacto", "NIF", "Dirección", "Población", "Código postal", "Provincia", "País", "Concepto",
                   "Descripción del producto", "SKU", "Precio unidad", "Unidades", "Descuento %", "IVA %", "Retención %",
                   "Inv. Suj. Pasivo (1/0)", "Operación", "Cantidad cobrada", "Fecha de cobro", "Cuenta de pago",
                   "Tags separados por -", "Nombre cuenta de gasto", "Num. Cuenta de gasto", "Moneda", "Cambio de moneda", "Almacén"]


def a_holded(contenido_xlsx):
    """Plantilla «Importar compras» de Holded: una fila por factura y tipo de IVA, mismas cabeceras que la muestra oficial.
    Solo compras. La factura queda pendiente de pago (sin «Cantidad cobrada»)."""
    fs = [f for f in leer_facturas(contenido_xlsx) if f["tipo"] == "COMPRAS"]
    if not fs:
        return []
    wb = Workbook()
    ws = wb.active
    ws.title = "Holded"
    ws.append(CABECERA_HOLDED)
    for fa in sorted(fs, key=lambda x: (_fecha(x["fecha"]), x["num"])):
        fecha = _fecha(fa["fecha"]).strftime("%d/%m/%Y")
        for ds in fa["desgloses"]:
            fila = [None] * len(CABECERA_HOLDED)
            fila[0] = fa["num"]
            fila[1] = fila[2] = fecha
            fila[5] = fa["nombre"] or fa["cif"]
            fila[6] = fa["cif"]
            fila[12] = "Factura " + fa["num"]
            fila[15] = _r(ds["base"])
            fila[16] = 1
            fila[17] = 0
            fila[18] = ds["pct"]
            fila[19] = fa["ret_pct"] or 0
            fila[20] = 0
            fila[21] = "general"
            fila[28] = "eur"
            ws.append(fila)
    b = BytesIO()
    wb.save(b)
    return [("holded_compras.xlsx", b.getvalue())]


LEEME_HOLDED = """IMPORTAR EN HOLDED (plantilla oficial «Importar compras»)  -  FORMATO EN PRUEBAS
Compras > Facturas > Importar compras > Subir archivo > holded_compras.xlsx.
Hay una fila por factura y tipo de IVA; las facturas quedan pendientes de pago. No importe dos veces el mismo fichero.
Solo facturas recibidas: las emitidas se importan con otra plantilla de Holded (aún no incluida).
El recargo de equivalencia no tiene columna en esta plantilla: si hay facturas con recargo, revíselas a mano tras importar.
Primera vez: pruebe con pocas facturas y compruebe importes y proveedores.
"""


def convertir(programa, contenido_xlsx):
    """(archivos, leeme) para el programa elegido, o None si ese programa se importa con el Excel de miEOS tal cual."""
    if programa == "contasol":
        return a_contasol(contenido_xlsx), LEEME_CONTASOL.format(d=DIGITOS["contasol"])
    if programa == "sage50":
        return a_sage50(contenido_xlsx), LEEME_SAGE50
    if programa == "holded":
        return a_holded(contenido_xlsx), LEEME_HOLDED
    return None


def paquete_zip(programa, contenido_xlsx, nombre_original):
    """ZIP listo para descargar con los ficheros del programa, el LEEME y el Excel de miEOS original. None si no aplica."""
    res = convertir(programa, contenido_xlsx)
    if not res:
        return None
    archivos, leeme = res
    b = BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("LEEME.txt", leeme)
        for n, c in archivos:
            z.writestr(n, c)
        z.writestr("original_" + nombre_original, contenido_xlsx)
    return b.getvalue()
