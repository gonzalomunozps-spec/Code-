# -*- coding: utf-8 -*-
"""
rejilla.py
==========

Rejilla de NDVI de una parcela: como se codifica para caber en la base y como se
comprueba que dos fechas son COMPARABLES.

Modulo PURO: no importa Tkinter, ni matplotlib, ni `ee`. La descarga vive en
`gee_cliente`; aqui solo esta el formato y las reglas de comparacion.

POR QUE HACE FALTA GUARDAR LA GEOREFERENCIACION
-----------------------------------------------
Comparar el pixel (i,j) de dos fechas solo tiene sentido si es EL MISMO TROZO DE
TERRENO. Sentinel-2 entrega sus bandas en una reticula UTM fija; si se reproyecta
o se recorta con origenes distintos, el (i,j) de marzo y el de abril dejan de ser
el mismo sitio y cualquier comparacion posterior es ruido con aspecto de dato.

Por eso cada rejilla guarda:
  crs        el sistema de coordenadas de la imagen (p. ej. "EPSG:32630")
  escala     tamano de pixel en metros (10 en las bandas que se usan)
  i0, j0     indice del pixel de la esquina superior izquierda EN LA RETICULA
             GLOBAL de ese CRS, no un desplazamiento relativo. Son enteros: se
             comparan exacto, sin margenes de coma flotante.
  filas, columnas

Dos rejillas son comparables si y solo si esos seis valores coinciden. Si no,
`comparables()` las descarta en vez de compararlas mal. El caso realista en que
NO coinciden es una parcela a caballo entre dos husos UTM: segun la pasada, la
imagen llega en un huso o en otro.

FORMATO Y TAMANO
----------------
El objetivo es no pasar de ~2 KB por pasada en una parcela de 5-10 ha:

  ndvi      un byte por pixel. Entero con signo, NDVI x 100, recortado a
            [-100, 100]. Precision 0.01, que esta por debajo del ruido propio de
            la medida: afinar mas seria gastar espacio en decimales que no
            significan nada.
  validos   un BIT por pixel. Un pixel tapado por nube no es un pixel raro: sin
            esta mascara se confundirian, y ese es el error mas facil de cometer.
  ambos     comprimidos con zlib y en base64. El NDVI de una parcela varia poco
            entre vecinos, asi que comprime muy bien; los pixeles de fuera del
            recinto son todos iguales y comprimen casi a nada.
"""

import base64
import zlib

FORMATO = 1                 # version del formato; se guarda con los datos
ESCALA_NDVI = 100           # NDVI x 100 -> un byte por pixel, precision 0.01
FUERA = -128                # marca de "sin dato" dentro del byte (no es un NDVI)
CLAVES_GEO = ("crs", "escala", "i0", "j0", "filas", "columnas")


# ---------------------------------------------------------------------------
# Empaquetado
# ---------------------------------------------------------------------------
def _a_bytes(valores, validos):
    """NDVI a un byte por pixel. Lo invalido va como FUERA, no como 0: un 0 es un
    NDVI legitimo (suelo desnudo) y confundirlos seria justo el fallo a evitar."""
    out = bytearray(len(valores))
    for k, v in enumerate(valores):
        if not validos[k] or v is None:
            out[k] = FUERA & 0xFF
            continue
        e = int(round(float(v) * ESCALA_NDVI))
        out[k] = max(-100, min(100, e)) & 0xFF
    return bytes(out)


def _de_bytes(crudo):
    vals = []
    for b in crudo:
        e = b - 256 if b > 127 else b
        vals.append(None if e == FUERA else e / float(ESCALA_NDVI))
    return vals


def _bits(validos):
    """Un bit por pixel, en bloques de 8 (el primero es el bit mas significativo)."""
    out = bytearray((len(validos) + 7) // 8)
    for k, v in enumerate(validos):
        if v:
            out[k >> 3] |= 0x80 >> (k & 7)
    return bytes(out)


def _de_bits(crudo, n):
    return [bool(crudo[k >> 3] & (0x80 >> (k & 7))) for k in range(n)]


def _comprimir(crudo):
    return base64.b64encode(zlib.compress(crudo, 9)).decode("ascii")


def _descomprimir(txt):
    return zlib.decompress(base64.b64decode(txt))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def codificar(valores, validos, geo, sin_buffer=False, buffer_m=0):
    """Empaqueta una rejilla para guardarla como JSON.

    `valores` y `validos` van en orden de lectura (fila 0 de izquierda a derecha,
    luego fila 1...) y tienen que medir filas x columnas.
    """
    n = int(geo["filas"]) * int(geo["columnas"])
    if len(valores) != n or len(validos) != n:
        raise ValueError(f"la rejilla dice {geo['filas']}x{geo['columnas']} = {n} "
                         f"pero llegan {len(valores)} valores y {len(validos)} marcas")
    d = {"v": FORMATO, "sin_buffer": bool(sin_buffer), "buffer_m": buffer_m,
         "n_validos": sum(1 for x in validos if x),
         "ndvi": _comprimir(_a_bytes(valores, validos)),
         "validos": _comprimir(_bits(validos))}
    for k in CLAVES_GEO:
        d[k] = geo[k]
    return d


def decodificar(d):
    """Devuelve {"valores": [...], "validos": [...], "geo": {...}, ...}.

    Los pixeles invalidos vienen como None en `valores`: quien los use no puede
    confundirlos con un NDVI bajo."""
    if not d or d.get("v") != FORMATO:
        return None
    n = int(d["filas"]) * int(d["columnas"])
    validos = _de_bits(_descomprimir(d["validos"]), n)
    valores = _de_bytes(_descomprimir(d["ndvi"]))
    if len(valores) != n:
        return None                       # datos truncados: mejor nada que mal
    return {"valores": valores, "validos": validos,
            "geo": {k: d[k] for k in CLAVES_GEO},
            "sin_buffer": bool(d.get("sin_buffer")),
            "buffer_m": d.get("buffer_m", 0),
            "n_validos": d.get("n_validos", sum(1 for x in validos if x))}


# ---------------------------------------------------------------------------
# Comparabilidad
# ---------------------------------------------------------------------------
def clave_geometria(d):
    """Identidad de la reticula. Dos fechas con la misma clave describen el mismo
    trozo de terreno, pixel a pixel."""
    if not d:
        return None
    try:
        return (str(d["crs"]), round(float(d["escala"]), 6),
                int(d["i0"]), int(d["j0"]), int(d["filas"]), int(d["columnas"]))
    except (KeyError, TypeError, ValueError):
        return None


def misma_geometria(a, b):
    ka, kb = clave_geometria(a), clave_geometria(b)
    return ka is not None and ka == kb


def comparables(rejillas):
    """Filtra un histórico dejando SOLO las fechas que comparten reticula.

    Devuelve (lista_comparable, descartadas). Se conserva el grupo MAS GRANDE; si
    empatan, el que contenga la rejilla mas reciente. Asi una sola fecha rara -por
    ejemplo la que llego en otro huso UTM- no invalida todo el histórico, pero
    tampoco se cuela en una comparacion donde el (i,j) significa otra cosa.
    """
    utiles = [r for r in (rejillas or []) if clave_geometria(r.get("geo") or r)]
    if not utiles:
        return [], list(rejillas or [])
    grupos = {}
    for r in utiles:
        grupos.setdefault(clave_geometria(r.get("geo") or r), []).append(r)
    ultima = clave_geometria(utiles[-1].get("geo") or utiles[-1])
    mejor = max(grupos, key=lambda k: (len(grupos[k]), k == ultima))
    buenas = grupos[mejor]
    descartadas = [r for r in (rejillas or []) if r not in buenas]
    return buenas, descartadas


def tamano_estimado(filas, columnas):
    """Bytes que ocuparia, en el peor caso (datos sin correlacion, que no comprimen).

    Sirve para decidir ANTES de descargar si una parcela cabe en el presupuesto."""
    n = filas * columnas
    crudo = n + (n + 7) // 8                 # un byte de NDVI + un bit de mascara
    return int(crudo * 1.37) + 220           # base64 sin ganancia + la cabecera JSON
