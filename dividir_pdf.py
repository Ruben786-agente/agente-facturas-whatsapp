# -*- coding: utf-8 -*-
"""
Separa un PDF que trae varias facturas/tickets (un lote escaneado) en documentos sueltos.

Paso 1: se le pide a la IA que diga qué páginas forman cada documento
        (una factura puede ocupar varias páginas).
Paso 2: se corta el PDF en trozos con esas páginas; cada trozo se procesa después
        como una factura normal.
"""

import base64
import io
import json
import logging
import os

import anthropic
from pypdf import PdfReader, PdfWriter

from extraccion_ia import MODELO, _extraer_json

log = logging.getLogger("dividir_pdf")

MAX_PAGINAS = 100  # límite de la API de Claude para un PDF

PROMPT_DIVISION = """Te paso un PDF escaneado que puede contener VARIAS facturas, tickets o
abonos seguidos. Tu única tarea es decir qué páginas forman cada documento.

Devuelve ÚNICAMENTE un JSON con esta forma, sin explicaciones ni markdown:
{"documentos": [{"paginas": [1]}, {"paginas": [2, 3]}, {"paginas": [4]}]}

REGLAS:
1. Las páginas se numeran desde 1, en el orden del PDF.
2. Cada documento (factura, ticket o abono) es un elemento. Una factura que ocupa varias
   páginas va en un solo elemento con todas sus páginas (continúa con "Hoja 2 de 2",
   "Continúa", totales en la última página, etc.).
3. Todas las páginas deben aparecer exactamente una vez. Incluye también las páginas que
   no son facturas (portada, página en blanco, albarán): cada una como su propio elemento.
4. Si todo el PDF es un único documento, devuelve un solo elemento con todas las páginas.
5. Nunca mezcles en un mismo elemento facturas distintas (distinto número de factura,
   distinto emisor o distinta fecha).
"""


def contar_paginas(contenido: bytes) -> int:
    try:
        return len(PdfReader(io.BytesIO(contenido)).pages)
    except Exception:
        return 0


def _validar_grupos(grupos, total):
    """Cada página, exactamente una vez, dentro de rango. Devuelve la lista limpia o None."""
    try:
        limpios = []
        vistas = set()
        for g in grupos:
            paginas = sorted(int(p) for p in g["paginas"])
            if not paginas or any(p < 1 or p > total or p in vistas for p in paginas):
                return None
            vistas.update(paginas)
            limpios.append(paginas)
        if vistas != set(range(1, total + 1)):
            return None
        return sorted(limpios, key=lambda g: g[0])
    except (KeyError, TypeError, ValueError):
        return None


def detectar_documentos(contenido: bytes, total_paginas: int) -> list:
    """Lista de grupos de páginas, p. ej. [[1], [2, 3], [4]]. Si la IA falla o responde
    algo incoherente, cada página se trata como un documento suelto: así nada se pierde
    (una factura de dos páginas acabará en Revisión en vez de desaparecer)."""
    por_paginas = [[p] for p in range(1, total_paginas + 1)]
    try:
        cliente = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        respuesta = cliente.messages.create(
            model=MODELO, max_tokens=2000, system=PROMPT_DIVISION,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                "data": base64.b64encode(contenido).decode()}},
                {"type": "text", "text": f"Este PDF tiene {total_paginas} páginas. Indica cómo se agrupan."},
            ]}],
        )
        texto = "".join(b.text for b in respuesta.content if b.type == "text")
        grupos = _validar_grupos(_extraer_json(texto).get("documentos", []), total_paginas)
        if grupos is None:
            log.warning("División incoherente (%r); se trata cada página por separado", texto[:200])
            return por_paginas
        return grupos
    except (json.JSONDecodeError, anthropic.APIError, KeyError, Exception) as e:
        log.warning("No se pudo dividir el PDF (%s); se trata cada página por separado", e)
        return por_paginas


def cortar_pdf(contenido: bytes, grupos: list) -> list:
    """Devuelve un PDF (bytes) por cada grupo de páginas."""
    lector = PdfReader(io.BytesIO(contenido))
    partes = []
    for paginas in grupos:
        escritor = PdfWriter()
        for p in paginas:
            escritor.add_page(lector.pages[p - 1])
        salida = io.BytesIO()
        escritor.write(salida)
        partes.append(salida.getvalue())
    return partes
