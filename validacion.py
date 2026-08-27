# -*- coding: utf-8 -*-
"""
validacion.py
=============

Mide CUANTO ACIERTA el sistema comparando lo que predijo con lo que se observo
de verdad en campo (a pie de finca, con sonda o con un vuelo de dron). Es la
"nota" del modelo: matriz de confusion de fases, error del GDD en dias,
correlacion indice<->rendimiento y error de la humedad de suelo.

Filosofia (importante para no viciar la medida):
  - Este modulo NO decide, NO corrige y NO toca ningun umbral. Solo compara y
    puntua. La observacion de campo se guarda como VERDAD; la prediccion que se
    mide es la ORIGINAL del sistema, nunca una ya "corregida" con esa verdad
    (eso seria examinarse con las respuestas delante: circularidad).
  - Nucleo PURO: recibe listas de pares (predicho, observado) y devuelve numeros.
    Sin base de datos, sin motor, sin red, sin Tkinter. Asi se prueba entero y,
    como el resto de modulos opcionales, se puede borrar sin romper nada: quien
    lo use lo hace tras un try/except.

El emparejamiento (buscar que predijo el sistema para la parcela y fecha de cada
observacion) NO vive aqui, sino en la capa que ya conoce el almacen y el motor
(`vista_ficha`), que arma los pares y llama a estas funciones.
"""

import math


# ---------------------------------------------------------------------------
# FASES: matriz de confusion
# ---------------------------------------------------------------------------
def matriz_fases(pares):
    """Matriz de confusion de fases fenologicas.

    `pares`: iterable de (fase_predicha, fase_observada), ya como texto. Se
    descartan los pares con algun lado vacio (una observacion sin fase, o una
    fecha sin prediccion no cuentan).

    Devuelve dict:
      etiquetas   lista ordenada de fases que aparecen (predichas u observadas)
      matriz      dict {predicha: {observada: n}} solo con las celdas > 0
      total       pares validos
      aciertos    pares en la diagonal (predicha == observada)
      exactitud   aciertos/total en [0,1] (None si total 0)
      kappa       kappa de Cohen: acuerdo por encima del azar (None si no aplica)
    """
    limpio = [(str(p).strip(), str(o).strip()) for p, o in pares
              if str(p).strip() and str(o).strip()]
    total = len(limpio)
    etiquetas = sorted({x for par in limpio for x in par})
    matriz = {}
    aciertos = 0
    for p, o in limpio:
        matriz.setdefault(p, {}).setdefault(o, 0)
        matriz[p][o] += 1
        if p == o:
            aciertos += 1
    exactitud = aciertos / total if total else None
    return {"etiquetas": etiquetas, "matriz": matriz, "total": total,
            "aciertos": aciertos, "exactitud": exactitud,
            "kappa": _kappa(limpio, total)}


def _kappa(pares, total):
    """Kappa de Cohen sobre los pares (predicha, observada).

    Corrige la exactitud por el acuerdo que saldria SOLO por azar: con pocas
    fases y muy desbalanceadas, un 80 % puede ser casi todo azar. kappa=1 es
    acuerdo perfecto, 0 es el del azar, <0 peor que el azar. None si no hay
    pares o si el azar ya es 1 (una sola fase: la formula se indetermina)."""
    if not total:
        return None
    po = sum(1 for p, o in pares if p == o) / total
    pred = {}
    obs = {}
    for p, o in pares:
        pred[p] = pred.get(p, 0) + 1
        obs[o] = obs.get(o, 0) + 1
    pe = sum((pred.get(e, 0) / total) * (obs.get(e, 0) / total)
             for e in set(pred) | set(obs))
    if pe >= 1.0:
        return None
    return (po - pe) / (1 - pe)


# ---------------------------------------------------------------------------
# NUMEROS: error del GDD (dias), humedad (%), y ajuste indice<->rendimiento
# ---------------------------------------------------------------------------
def _numericos(pares):
    """Filtra a pares (predicho, observado) numericos y finitos."""
    out = []
    for p, o in pares:
        try:
            p, o = float(p), float(o)
        except (TypeError, ValueError):
            continue
        if math.isfinite(p) and math.isfinite(o):
            out.append((p, o))
    return out


def rmse(pares):
    """Raiz del error cuadratico medio entre predicho y observado. None si no
    hay pares numericos. Mismas unidades que el dato (dias para el GDD, % para
    la humedad)."""
    xs = _numericos(pares)
    if not xs:
        return None
    return math.sqrt(sum((p - o) ** 2 for p, o in xs) / len(xs))


def mae(pares):
    """Error absoluto medio. None si no hay pares numericos."""
    xs = _numericos(pares)
    if not xs:
        return None
    return sum(abs(p - o) for p, o in xs) / len(xs)


def sesgo(pares):
    """Media de (predicho - observado): >0 el sistema sobreestima, <0 subestima.
    None si no hay pares numericos."""
    xs = _numericos(pares)
    if not xs:
        return None
    return sum(p - o for p, o in xs) / len(xs)


def regresion(pares):
    """Ajuste lineal observado = pendiente*x + ordenada, con x el indice
    (NDVI/NDRE) y observado el rendimiento medido. Es el numero estrella de la
    teledeteccion agricola: cuanta de la variacion de cosecha explica el indice.

    `pares`: (indice, rendimiento_real). Devuelve dict con n, r2, rmse,
    pendiente, ordenada, r (Pearson). None si hay menos de 2 puntos o el indice
    no varia (no se puede ajustar una recta a una columna vertical)."""
    xs = _numericos(pares)
    n = len(xs)
    if n < 2:
        return None
    mx = sum(x for x, _ in xs) / n
    my = sum(y for _, y in xs) / n
    sxx = sum((x - mx) ** 2 for x, _ in xs)
    syy = sum((y - my) ** 2 for _, y in xs)
    sxy = sum((x - mx) * (y - my) for x, y in xs)
    if sxx == 0:
        return None                      # el indice no varia: recta indefinida
    pendiente = sxy / sxx
    ordenada = my - pendiente * mx
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else None
    r = math.copysign(math.sqrt(r2), sxy) if r2 is not None else None
    resid = math.sqrt(sum((y - (pendiente * x + ordenada)) ** 2 for x, y in xs) / n)
    return {"n": n, "r2": r2, "r": r, "rmse": resid,
            "pendiente": pendiente, "ordenada": ordenada}


# ---------------------------------------------------------------------------
# INFORME: junta las cuatro medidas en una estructura para pintar o exportar
# ---------------------------------------------------------------------------
def informe(pares_fase=(), pares_gdd=(), pares_rend=(), pares_humedad=()):
    """Agrupa las metricas de las cuatro hipotesis del sistema.

      pares_fase     (fase_predicha, fase_observada)         -> matriz de confusion
      pares_gdd      (dia_predicho_de_fase, dia_observado)   -> RMSE en dias
      pares_rend     (indice, rendimiento_real)              -> R2 y RMSE
      pares_humedad  (humedad_modelo, humedad_sonda)         -> RMSE y sesgo en %

    Cada bloque es None si no habia datos, para que la vista sepa que no pintar.
    """
    fases = matriz_fases(pares_fase) if pares_fase else None
    gdd = None
    if pares_gdd:
        gdd = {"n": len(_numericos(pares_gdd)), "rmse": rmse(pares_gdd),
               "sesgo": sesgo(pares_gdd)}
        if not gdd["n"]:
            gdd = None
    rend = regresion(pares_rend) if pares_rend else None
    hum = None
    if pares_humedad:
        hum = {"n": len(_numericos(pares_humedad)), "rmse": rmse(pares_humedad),
               "sesgo": sesgo(pares_humedad)}
        if not hum["n"]:
            hum = None
    return {"fases": fases, "gdd": gdd, "rendimiento": rend, "humedad": hum}


def texto(inf):
    """Renderiza el informe a texto llano para la ficha o la memoria.

    Robusto ante bloques vacios: solo escribe las lineas de lo que hay datos.
    Devuelve cadena vacia si no hay ninguna medida (nada que mostrar)."""
    if not inf:
        return ""
    lineas = []
    f = inf.get("fases")
    if f and f.get("total"):
        ex = f.get("exactitud")
        k = f.get("kappa")
        linea = (f"Fases: {f['aciertos']}/{f['total']} aciertos "
                 f"({ex * 100:.0f}%)" if ex is not None else "Fases:")
        if k is not None:
            linea += f"  ·  kappa {k:.2f}"
        lineas.append(linea)
    g = inf.get("gdd")
    if g and g.get("rmse") is not None:
        s = g.get("sesgo")
        extra = f" (sesgo {s:+.1f})" if s is not None else ""
        lineas.append(f"GDD: error de {g['rmse']:.1f} días en la fecha de fase, "
                      f"n={g['n']}{extra}")
    r = inf.get("rendimiento")
    if r and r.get("r2") is not None:
        lineas.append(f"Índice↔rendimiento: R²={r['r2']:.2f}, "
                      f"error {r['rmse']:.0f} kg/ha, n={r['n']}")
    h = inf.get("humedad")
    if h and h.get("rmse") is not None:
        s = h.get("sesgo")
        extra = f" (sesgo {s:+.1f})" if s is not None else ""
        lineas.append(f"Humedad de suelo: error de {h['rmse']:.1f} % frente a "
                      f"sonda, n={h['n']}{extra}")
    return "\n".join(lineas)


def texto_matriz(fases):
    """La matriz de confusion de fases como tabla de texto monoespaciado, lista
    para pegar en la memoria. Cadena vacia si no hay fases."""
    if not fases or not fases.get("etiquetas"):
        return ""
    etq = fases["etiquetas"]
    mat = fases["matriz"]
    corto = [e[:8] for e in etq]
    ancho = max([7] + [len(c) for c in corto])
    cab = " " * (ancho + 2) + "".join(f"{c:>{ancho + 1}}" for c in corto) + "   (obs)"
    filas = [cab]
    for e, ce in zip(etq, corto):
        celdas = "".join(f"{mat.get(e, {}).get(o, 0):>{ancho + 1}}" for o in etq)
        filas.append(f"{ce:<{ancho + 2}}{celdas}")
    filas.append("(pred, filas)")
    return "\n".join(filas)
