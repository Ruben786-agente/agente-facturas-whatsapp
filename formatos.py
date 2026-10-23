# -*- coding: utf-8 -*-
"""
Convierte lo que llegue (fotos del móvil, escaneos, ZIP...) a los tres formatos que lee la IA: PDF, JPG y PNG.

  - Fotos de iPhone (HEIC/HEIF), WebP, GIF, BMP, TIFF -> JPG (se corrige la orientación; un TIFF de varias páginas pasa a PDF).
  - Facturae (XML de factura electrónica) -> pasa tal cual: se lee sin IA (facturae.py).
  - ZIP -> se abren y se tratan sus archivos (hasta MAX_ARCHIVOS_ZIP, sin ZIP dentro de ZIP).
El formato se reconoce por el contenido, no por la extensión (una foto HEIC llamada .jpg se detecta igualmente).
"""

import io
import logging
import os
import zipfile

log = logging.getLogger("formatos")

EXTENSIONES = {".xml", ".xsig", ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".zip"}
EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".tif", ".tiff", ".bmp"}
MAX_ARCHIVOS_ZIP = 50
MAX_BYTES_ZIP_DESCOMPRIMIDO = 150 * 1024 * 1024
MAX_BYTES_IMAGEN_IA = 4_000_000   # la API de Claude admite hasta 5 MB por imagen
MAX_PIXELES = 24_000_000      # por encima, la imagen no se abre (una foto de 12 Mpx ya es grande de sobra para leer una factura)
LADO_MAX = 3000               # se reduce a este lado largo: la IA no gana nada con más y el servidor gasta mucha memoria

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:   # sin la librería, las fotos HEIC irán a revisión en vez de leerse
    pillow_heif = None


def tipo_real(contenido):
    """'pdf', 'jpg', 'png', 'zip', 'otra_imagen' (la reconoce Pillow) o None."""
    if contenido[:4] == b"%PDF":
        return "pdf"
    from facturae import es_facturae
    if es_facturae(contenido):
        return "facturae"
    if contenido[:3] == b"\xff\xd8\xff":
        return "jpg"
    if contenido[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if contenido[:4] == b"PK\x03\x04" and not _es_office(contenido):
        return "zip"
    if contenido[:4] in (b"RIFF", b"GIF8", b"II*\x00", b"MM\x00*") or contenido[:2] == b"BM" or contenido[4:12] in (
            b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypheim", b"ftypmsf1", b"ftyphevc", b"ftypavif"):
        return "otra_imagen"
    return None


def _es_office(contenido):
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            return any(n.startswith(("word/", "xl/", "ppt/")) for n in z.namelist()[:50])
    except zipfile.BadZipFile:
        return False


def _a_jpg_o_pdf(contenido, nombre):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 200_000_000
    img = Image.open(io.BytesIO(contenido))
    if img.width * img.height > MAX_PIXELES and (img.format or "").upper() != "JPEG":   # un JPEG se decodifica ya reducido (draft)
        raise ValueError("imagen demasiado grande")
    base = os.path.splitext(os.path.basename(nombre))[0]
    paginas = getattr(img, "n_frames", 1)
    if paginas > 1 and (img.format or "").upper() == "TIFF":
        marcos = []
        for i in range(min(paginas, 100)):
            img.seek(i)
            marco = img.convert("RGB")
            marco.thumbnail((LADO_MAX, LADO_MAX))
            marcos.append(marco)
        salida = io.BytesIO()
        marcos[0].save(salida, "PDF", save_all=True, append_images=marcos[1:], resolution=200.0)
        return salida.getvalue(), base + ".pdf"
    img.draft("RGB", (LADO_MAX, LADO_MAX))      # JPEG: se decodifica ya reducida
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        img = Image.new("RGB", rgba.size, "white")
        img.paste(rgba, mask=rgba.split()[-1])
        del rgba
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((LADO_MAX, LADO_MAX))
    ImageOps.exif_transpose(img, in_place=True)  # sin copia
    salida = io.BytesIO()
    img.save(salida, "JPEG", quality=90)
    return salida.getvalue(), base + ".jpg"


def normalizar(nombre, contenido, _nivel=0):
    """Devuelve (lista de (nombre, contenido) en PDF/JPG/PNG, lista de (nombre, motivo) de los que no se pudieron leer)."""
    tipo = tipo_real(contenido)
    if tipo in ("jpg", "png") and len(contenido) > MAX_BYTES_IMAGEN_IA:
        # la API de Claude rechaza imágenes de más de 5 MB: se reduce (y de paso se gasta menos memoria y menos IA)
        try:
            nuevo, nombre_nuevo = _a_jpg_o_pdf(contenido, nombre)
            return [(nombre_nuevo, nuevo)], []
        except Exception as e:
            log.warning("No se pudo reducir '%s': %s", nombre, e)
            return [], [(nombre, "imagen demasiado grande (reduzca su tamaño)")]
    if tipo in ("pdf", "jpg", "png", "facturae"):
        return [(nombre, contenido)], []
    if tipo == "otra_imagen":
        try:
            nuevo, nombre_nuevo = _a_jpg_o_pdf(contenido, nombre)
            return [(nombre_nuevo, nuevo)], []
        except Exception as e:
            log.warning("No se pudo convertir '%s': %s", nombre, e)
            motivo = "imagen demasiado grande (reduzca su tamaño)" if "demasiado grande" in str(e) or "decompression" in str(e).lower() else "imagen que no se puede abrir (si es una foto HEIC, expórtela como JPG)"
            return [], [(nombre, motivo)]
    if tipo == "zip":
        if _nivel >= 1:
            return [], [(nombre, "ZIP dentro de otro ZIP")]
        return _abrir_zip(nombre, contenido, _nivel)
    return [], [(nombre, "formato no admitido (use PDF o imagen)")]


def _abrir_zip(nombre, contenido, nivel):
    listos, fallidos = [], []
    try:
        z = zipfile.ZipFile(io.BytesIO(contenido))
    except zipfile.BadZipFile:
        return [], [(nombre, "ZIP dañado")]
    with z:
        entradas = [i for i in z.infolist() if not i.is_dir() and not os.path.basename(i.filename).startswith((".", "~$"))
                    and "__MACOSX" not in i.filename]
        if sum(i.file_size for i in entradas) > MAX_BYTES_ZIP_DESCOMPRIMIDO:
            return [], [(nombre, "ZIP demasiado grande al descomprimirlo")]
        for info in entradas[:MAX_ARCHIVOS_ZIP]:
            interno = os.path.basename(info.filename)
            if os.path.splitext(interno)[1].lower() not in EXTENSIONES:
                fallidos.append((f"{nombre}/{interno}", "formato no admitido (use PDF o imagen)"))
                continue
            ok, mal = normalizar(f"{os.path.splitext(nombre)[0]}__{interno}", z.read(info), nivel + 1)
            listos += ok
            fallidos += mal
        if len(entradas) > MAX_ARCHIVOS_ZIP:
            fallidos.append((nombre, f"el ZIP trae {len(entradas)} archivos; solo se leen los {MAX_ARCHIVOS_ZIP} primeros"))
    return listos, fallidos
