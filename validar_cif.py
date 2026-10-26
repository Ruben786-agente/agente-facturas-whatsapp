# -*- coding: utf-8 -*-
"""Comprobación de NIF / NIE / CIF españoles (formato y letra o dígito de control)."""
import re

_LETRAS_NIF = "TRWAGMYFPDXBNJZSQVHLCKE"
_CONTROL_CIF = "JABCDEFGHI"
_SOLO_LETRA = set("KPQRSNW")
_SOLO_DIGITO = set("ABEH")


def normalizar(valor):
    v = re.sub(r"[\s.\-/]", "", (valor or "").upper())
    return v[2:] if re.fullmatch(r"ES[A-Z0-9]{9}", v) else v


def es_espanol_valido(valor):
    v = normalizar(valor)
    if re.fullmatch(r"\d{8}[A-Z]", v):                                  # DNI/NIF
        return v[8] == _LETRAS_NIF[int(v[:8]) % 23]
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", v):                             # NIE
        return v[8] == _LETRAS_NIF[int(str("XYZ".index(v[0])) + v[1:8]) % 23]
    if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", v):            # CIF de sociedad
        d = v[1:8]
        suma = sum(int(d[i]) if i % 2 else sum(divmod(int(d[i]) * 2, 10)) for i in range(7))
        c = (10 - suma % 10) % 10
        if v[0] in _SOLO_LETRA:
            return v[8] == _CONTROL_CIF[c]
        if v[0] in _SOLO_DIGITO:
            return v[8] == str(c)
        return v[8] in (str(c), _CONTROL_CIF[c])
    return False


def comprobar(valor):
    """Devuelve (valor_normalizado, error o None). Acepta también IVA intracomunitario de otro país (p. ej. FR12345678901)."""
    original = (valor or "").strip()
    if not original:
        return "", "Falta el CIF del proveedor."
    v = normalizar(original)
    if es_espanol_valido(v):
        return v, None
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{8,12}", v) and not v.startswith("ES"):
        return v, None                                                  # proveedor de otro país de la UE
    return v, ("El CIF \"%s\" no es válido: debe tener 9 caracteres (por ejemplo B12345674 o 12345678Z) "
               "y la letra o el dígito final tiene que coincidir. Revíselo en la factura." % original)
