# -*- coding: utf-8 -*-
"""
pruebas.py
==========

Bateria de pruebas del sistema que NO necesita entorno grafico (Tkinter) ni
satelite (Google Earth Engine). Cubre el motor de diagnostico, la fenologia por
especie, el contraste de indices, el cuaderno de campo, las credenciales y la
persistencia robusta (escritura atomica, lectura tolerante y concurrencia).

Uso:
    python pruebas.py

Sale con codigo 0 si todo pasa, 1 si algo falla (util para CI).
"""

import os
import re
import sys
import json
import math
import tempfile
import threading

_PASA, _FALLA = [], []


def check(nombre, fn, ok=None):
    """Ejecuta fn(); registra fallo si revienta o si `ok(resultado)` es falso."""
    try:
        r = fn()
        if ok is not None and not ok(r):
            _FALLA.append((nombre, "resultado inesperado: " + repr(r)[:90]))
        else:
            _PASA.append(nombre)
    except Exception as e:
        _FALLA.append((nombre, f"{type(e).__name__}: {e}"))


# =====================================================================
# 1. MOTOR DE DIAGNOSTICO (interpretacion_fenologica)
# =====================================================================
def pruebas_motor():
    from interpretacion_fenologica import (evaluar_parcela, delta, detectar_cubierta,
                                           fase_fenologica, texto_interpretacion)

    lenoso = [
        {"fecha": "2026-01-10", "ndvi": 0.55, "msavi": 0.42, "lai": 1.8, "ndmi": 0.10,
         "evi": 0.30, "savi": 0.40, "gndvi": 0.50},
        {"fecha": "2026-02-15", "ndvi": 0.62, "msavi": 0.44, "lai": 1.9, "ndmi": 0.12,
         "evi": 0.32, "savi": 0.42, "gndvi": 0.52},
    ]
    check("motor: lenoso normal", lambda: evaluar_parcela("LENOSO", "INTENSIVO", lenoso, "2026-02-15"),
          lambda r: r["clave"] in ("OK", "Vigilar", "Revisar"))
    check("motor: serie vacia", lambda: evaluar_parcela("LENOSO", "INTENSIVO", []),
          lambda r: r["clave"] == "Sin")
    check("motor: barbecho -> N.A.", lambda: evaluar_parcela("BARBECHO", "", [{"fecha": "2026-03-01", "ndvi": 0.1}]),
          lambda r: r["clave"] == "NA")
    check("motor: una sola pasada", lambda: evaluar_parcela("EXTENSIVO", "COSECHA_GRANO",
          [{"fecha": "2026-03-01", "ndvi": 0.6, "msavi": 0.5, "lai": 2.0, "ndmi": 0.2}]))
    check("motor: solo NDVI (faltan indices)", lambda: evaluar_parcela("LENOSO", "INTENSIVO",
          [{"fecha": "2026-03-01", "ndvi": 0.5}]))
    check("motor: ultima nublada + previa valida", lambda: evaluar_parcela("LENOSO", "INTENSIVO",
          [{"fecha": "2026-02-01", "ndvi": 0.5, "msavi": 0.4}, {"fecha": "2026-02-15", "ndvi": None, "msavi": None}]))
    check("motor: NDVI None", lambda: evaluar_parcela("LENOSO", "INTENSIVO",
          [{"fecha": "2026-03-01", "ndvi": None}]), lambda r: r["clave"] in ("Sin", "OK", "Vigilar", "Revisar"))
    check("motor: NDVI=0 exacto", lambda: evaluar_parcela("EXTENSIVO", "COSECHA_GRANO",
          [{"fecha": "2026-03-01", "ndvi": 0.0, "msavi": 0.0}]))
    check("motor: valores extremos", lambda: evaluar_parcela("LENOSO", "INTENSIVO",
          [{"fecha": "2026-03-01", "ndvi": 9.9, "msavi": -3.0, "lai": 50, "ndmi": -9}]))
    check("motor: fecha mal formada", lambda: evaluar_parcela("LENOSO", "INTENSIVO",
          [{"fecha": "03/2026", "ndvi": 0.5}]))
    check("motor: registro sin fecha", lambda: evaluar_parcela("LENOSO", "INTENSIVO",
          [{"ndvi": 0.5, "msavi": 0.4}]))
    check("motor: tipo desconocido", lambda: evaluar_parcela("PRADERA", "", [{"fecha": "2026-04-01", "ndvi": 0.6}]))

    # deteccion de cubierta -> juicio con MSAVI
    cub = [
        {"fecha": "2026-02-01", "ndvi": 0.50, "msavi": 0.30, "lai": 1.0, "ndmi": 0.20},
        {"fecha": "2026-03-01", "ndvi": 0.68, "msavi": 0.33, "lai": 1.1, "ndmi": 0.22},
    ]
    check("motor: cubierta -> MSAVI", lambda: evaluar_parcela("LENOSO", "INTENSIVO", cub, "2026-03-01"),
          lambda r: r is not None)

    # eventos del cuaderno explican caida
    siega = [{"fecha": "2026-04-01", "ndvi": 0.70, "msavi": 0.60, "lai": 3.0, "ndmi": 0.25},
             {"fecha": "2026-04-20", "ndvi": 0.35, "msavi": 0.32, "lai": 1.2, "ndmi": 0.15}]
    ev = [(2, {"tipo": "SIEGA", "fecha": "2026-04-18"})]
    check("motor: evento explica caida -> OK", lambda: evaluar_parcela("EXTENSIVO", "SIEGA_VERDE",
          siega, "2026-04-20", eventos_cerca=ev)["clave"], lambda r: r == "OK")

    # finalidad del cultivo: un corte en SIEGA_VERDE es normal (OK); en grano no
    corte = [{"fecha": "2026-03-16", "ndvi": 0.72, "msavi": 0.62, "lai": 3.1, "ndmi": 0.30},
             {"fecha": "2026-04-14", "ndvi": 0.34, "msavi": 0.31, "lai": 1.2, "ndmi": 0.16}]
    spec_forr = {"especie": "AVENA", "fecha_siembra": "2025-10-05"}
    check("motor: siega en verde -> corte = OK", lambda: evaluar_parcela("EXTENSIVO", "SIEGA_VERDE",
          corte, "2026-04-14", spec=spec_forr)["clave"], lambda r: r == "OK")
    check("motor: mismo corte en grano NO es OK", lambda: evaluar_parcela("EXTENSIVO", "COSECHA_GRANO",
          corte, "2026-04-14", spec=spec_forr)["clave"], lambda r: r in ("Vigilar", "Revisar"))

    # --- SIEGA EN VERDE: desplome en abril-mayo -> estado "Segado" ---
    seg = [{"fecha": "2026-04-20", "ndvi": 0.80, "ndmi": 0.30},
           {"fecha": "2026-05-05", "ndvi": 0.33, "ndmi": 0.20}]
    check("motor: siega verde, desplome en mayo -> Segado",
          lambda: evaluar_parcela("EXTENSIVO", "SIEGA_VERDE", seg, "2026-05-05")["estado"],
          lambda r: r == "Segado")
    seg_est = [{"fecha": "2026-04-20", "ndvi": 0.72}, {"fecha": "2026-05-05", "ndvi": 0.70}]
    check("motor: siega verde estable en mayo -> NO Segado",
          lambda: evaluar_parcela("EXTENSIVO", "SIEGA_VERDE", seg_est, "2026-05-05")["estado"],
          lambda r: r != "Segado")
    seg_ago = [{"fecha": "2026-07-20", "ndvi": 0.70}, {"fecha": "2026-08-05", "ndvi": 0.30}]
    check("motor: desplome en agosto NO se marca 'Segado' (fuera de abr-may)",
          lambda: evaluar_parcela("EXTENSIVO", "SIEGA_VERDE", seg_ago, "2026-08-05")["estado"],
          lambda r: r != "Segado")

    # --- AVISO TEMPRANO de foco: la dispersion crece antes que caiga la media ---
    _sp = {"especie": "ALMENDRO", "marco_calle": 6.0, "marco_pie": 5.0}
    def _serie(std2, p10_2, media2=0.59):
        return [{"fecha": "2026-03-01", "ndvi": 0.60, "ndvi_std": 0.05,
                 "ndvi_p10": 0.55, "ndvi_p50": 0.60, "ndvi_p90": 0.65, "n_pixeles": 800},
                {"fecha": "2026-03-20", "ndvi": media2, "ndvi_std": std2,
                 "ndvi_p10": p10_2, "ndvi_p50": 0.61, "ndvi_p90": 0.72, "n_pixeles": 800}]
    check("foco temprano: dispersion creciente -> Vigilar con aviso",
          lambda: evaluar_parcela("LENOSO", "", _serie(0.13, 0.38), spec=_sp),
          lambda d: d["estado"] == "Vigilar" and "AVISO TEMPRANO" in d["motivo"])
    check("foco temprano: nombra el rodal hundido (p50-p10)",
          lambda: evaluar_parcela("LENOSO", "", _serie(0.13, 0.38), spec=_sp)["motivo"],
          lambda m: "rodal hundido" in m)
    check("foco temprano: parcela uniforme y estable NO avisa",
          lambda: evaluar_parcela("LENOSO", "", _serie(0.05, 0.56), spec=_sp),
          lambda d: d["estado"] == "OK" and "AVISO" not in d["motivo"])
    check("foco temprano: invita a validar tras revisar la parcela",
          lambda: evaluar_parcela("LENOSO", "", _serie(0.13, 0.38), spec=_sp)["motivo"],
          lambda m: "validar el diagnostico" in m)
    # el foco YA confirmado (media cae + dispersion sube) manda: no se duplica el aviso
    _loc = [{"fecha": "2026-03-01", "ndvi": 0.60, "ndvi_std": 0.05, "ndvi_p10": 0.55,
             "ndvi_p50": 0.60, "ndvi_p90": 0.65, "n_pixeles": 800},
            {"fecha": "2026-03-20", "ndvi": 0.50, "ndvi_std": 0.14, "ndvi_p10": 0.30,
             "ndvi_p50": 0.52, "ndvi_p90": 0.70, "n_pixeles": 800}]
    check("foco temprano: no se solapa con el deterioro LOCALIZADO",
          lambda: evaluar_parcela("LENOSO", "", _loc, spec=_sp)["motivo"],
          lambda m: "LOCALIZADO" in m and "AVISO TEMPRANO" not in m)
    # una caida propia de la fase (senescencia) no debe convertirse en aviso de foco
    _sen = [{"fecha": "2026-05-14", "ndvi": 0.66, "ndvi_std": 0.05, "ndvi_p10": 0.60,
             "ndvi_p50": 0.66, "ndvi_p90": 0.72, "n_pixeles": 800},
            {"fecha": "2026-06-12", "ndvi": 0.34, "ndvi_std": 0.12, "ndvi_p10": 0.18,
             "ndvi_p50": 0.36, "ndvi_p90": 0.55, "n_pixeles": 800}]
    check("foco temprano: no pisa una caida esperada por la fase (senescencia)",
          lambda: evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", _sen,
                                  spec={"especie": "TRIGO", "fecha_siembra": "2025-11-10"}),
          lambda d: d["esperado"] is True and "AVISO TEMPRANO" not in d["motivo"])
    # y el usuario puede quitarlo: dos correcciones suyas ajustan el estado
    def _usuario_manda():
        from interpretacion_fenologica import ajuste_por_validaciones as _aj
        d = evaluar_parcela("LENOSO", "", _serie(0.13, 0.38), spec=_sp)
        vals = [{"cultivo": "LENOSO//ALMENDRO", "fase": d["fase"], "estado_sistema": "Vigilar",
                 "veredicto": "incorrecto", "estado_real": "OK"}] * 2
        return _aj("LENOSO//ALMENDRO", d["fase"], d["estado"], vals)
    check("foco temprano: el usuario puede corregirlo y se aprende",
          _usuario_manda, lambda r: r.get("corregido") == "OK")

    # --- APRENDIZAJE: las validaciones pasadas se resumen para la IA ---
    from interpretacion_fenologica import contexto_aprendizaje
    apr = [{"fase": "rebrote / cortes", "cultivo": "EXTENSIVO/SIEGA_VERDE", "estado_sistema": "Revisar",
            "veredicto": "incorrecto", "estado_real": "Segado", "nota": "se sego el 3 de mayo"}]
    check("aprendizaje: resume correccion incorrecta",
          lambda: contexto_aprendizaje(apr),
          lambda r: r and "Segado" in r and "3 de mayo" in r)
    check("aprendizaje: lista vacia -> None", lambda: contexto_aprendizaje([]), lambda r: r is None)
    check("aprendizaje: sin veredicto util -> None",
          lambda: contexto_aprendizaje([{"veredicto": "", "fase": "x"}]), lambda r: r is None)

    # --- aprendizaje que AJUSTA la prediccion (campanas anteriores) ---
    from interpretacion_fenologica import ajuste_por_validaciones
    vv = [{"cultivo": "EXTENSIVO/COSECHA_GRANO/TRIGO", "fase": "espigado / floracion",
           "estado_sistema": "Revisar", "veredicto": "incorrecto", "estado_real": "OK"},
          {"cultivo": "EXTENSIVO/COSECHA_GRANO/TRIGO", "fase": "espigado / floracion",
           "estado_sistema": "Revisar", "veredicto": "incorrecto", "estado_real": "OK"}]
    check("ajuste: 2 correcciones coherentes -> corrige la prediccion",
          lambda: ajuste_por_validaciones("EXTENSIVO/COSECHA_GRANO/TRIGO", "espigado / floracion", "Revisar", vv),
          lambda r: r.get("corregido") == "OK" and r.get("votos") == 2)
    check("ajuste: 1 sola correccion -> solo anota (no corrige)",
          lambda: ajuste_por_validaciones("EXTENSIVO/COSECHA_GRANO/TRIGO", "espigado / floracion", "Revisar", vv[:1]),
          lambda r: r.get("corregido") is None and "nota" in r)
    check("ajuste: cultivo/fase distintos -> sin ajuste",
          lambda: ajuste_por_validaciones("OTRO", "otra", "OK", vv), lambda r: r == {})
    check("ajuste: confirmaciones -> nota de confianza",
          lambda: ajuste_por_validaciones("C", "f", "OK",
                  [{"cultivo": "C", "fase": "f", "estado_sistema": "OK", "veredicto": "correcto"}]),
          lambda r: r.get("corregido") is None and "correcto" in r.get("nota", ""))

    # --- APRENDE DE LO QUE LA PERSONA ESCRIBE: se recuperan sus observaciones ---
    from interpretacion_fenologica import observaciones_del_agricultor
    obs = [{"cultivo": "T", "fase": "llenado", "veredicto": "incorrecto", "estado_real": "OK",
            "fecha": "2026-05-14", "nota": "es maduracion, el trigo amarillea"},
           {"cultivo": "T", "fase": "llenado", "veredicto": "correcto", "estado_sistema": "OK",
            "fecha": "2025-05-20", "nota": "igual que el ano pasado"},
           {"cultivo": "OTRO", "fase": "llenado", "veredicto": "incorrecto", "estado_real": "OK",
            "fecha": "2024-05-20", "nota": "no cuenta, otro cultivo"}]
    check("observaciones: recupera lo escrito para el mismo cultivo/fase",
          lambda: [o["nota"] for o in observaciones_del_agricultor("T", "llenado", obs)],
          lambda r: len(r) == 2 and "amarillea" in r[0])
    check("observaciones: usa estado_real si fue correccion",
          lambda: observaciones_del_agricultor("T", "llenado", obs)[0]["estado"],
          lambda r: r == "OK")
    check("observaciones: sin notas -> []",
          lambda: observaciones_del_agricultor("T", "llenado",
                  [{"cultivo": "T", "fase": "llenado", "veredicto": "correcto", "nota": ""}]),
          lambda r: r == [])
    check("observaciones: cultivo distinto no se mezcla",
          lambda: observaciones_del_agricultor("Z", "llenado", obs), lambda r: r == [])

    # --- AMBITO: correccion solo para una parcela vs para todo el cultivo ---
    from interpretacion_fenologica import ambito_parcela
    C, F = "EXTENSIVO/COSECHA_GRANO/TRIGO", "llenado de grano"
    def _v(clave, real="OK"):
        return {"cultivo": clave, "fase": F, "estado_sistema": "Revisar",
                "veredicto": "incorrecto", "estado_real": real, "fecha": "2026-05-14", "nota": ""}
    check("ambito: la clave de parcela lleva '@'",
          lambda: ambito_parcela(C, "Finca_Pobre"), lambda r: r == C + "@Finca_Pobre")
    solo_a = [_v(ambito_parcela(C, "Finca_Pobre"))] * 2
    check("ambito: 2 correcciones SOLO de una parcela ajustan esa parcela",
          lambda: ajuste_por_validaciones(C, F, "Revisar", solo_a, parcela="Finca_Pobre"),
          lambda r: r.get("corregido") == "OK" and r.get("ambito") == "parcela")
    check("ambito: NO contagian a otra parcela del mismo cultivo",
          lambda: ajuste_por_validaciones(C, F, "Revisar", solo_a, parcela="Otra_Finca"),
          lambda r: r == {})
    check("ambito: ni al cultivo en general (sin parcela)",
          lambda: ajuste_por_validaciones(C, F, "Revisar", solo_a), lambda r: r == {})
    generales = [_v(C)] * 2
    check("ambito: las generales SI llegan a cualquier parcela",
          lambda: ajuste_por_validaciones(C, F, "Revisar", generales, parcela="Otra_Finca"),
          lambda r: r.get("corregido") == "OK" and r.get("ambito") == "cultivo")
    # precedencia: lo propio de la parcela manda sobre lo general
    mixto = [_v(C, "Vigilar")] * 2 + [_v(ambito_parcela(C, "Finca_Pobre"), "OK")] * 2
    check("ambito: lo propio de la parcela MANDA sobre lo del cultivo",
          lambda: ajuste_por_validaciones(C, F, "Revisar", mixto, parcela="Finca_Pobre"),
          lambda r: r.get("corregido") == "OK" and r.get("ambito") == "parcela")
    check("ambito: sin historial propio, hereda el del cultivo",
          lambda: ajuste_por_validaciones(C, F, "Revisar", mixto, parcela="Finca_Normal"),
          lambda r: r.get("corregido") == "Vigilar" and r.get("ambito") == "cultivo")

    # deltas
    # delta devuelve (texto, delta_pts, delta_pct): uno con dato y el otro None
    check("delta: previo=0 -> sin variacion en ninguna unidad",
          lambda: delta("NDVI", 0.5, 0), lambda r: r[1] is None and r[2] is None)
    check("delta: previo None -> sin variacion en ninguna unidad",
          lambda: delta("NDVI", 0.5, None), lambda r: r[1] is None and r[2] is None)
    check("delta: NDMI se mide en PUNTOS (cruza 0), no en %",
          lambda: delta("NDMI", -0.05, 0.05),
          lambda r: r[1] is not None and r[2] is None and abs(r[1] + 0.10) < 1e-9)
    check("delta: NDVI se mide en PORCENTAJE",
          lambda: delta("NDVI", 0.60, 0.50),
          lambda r: r[2] is not None and r[1] is None and abs(r[2] - 20.0) < 1e-9)
    check("delta: previo casi cero -> se fuerza a PUNTOS (el % se dispararia)",
          lambda: delta("NDVI", 0.30, 0.05), lambda r: r[1] is not None and r[2] is None)
    def _exclusivos():
        casos = [("NDVI", 0.6, 0.5), ("NDMI", -0.05, 0.05), ("NDVI", 0.5, 0),
                 ("NDVI", None, 0.5), ("NDVI", 0.51, 0.50), ("NDVI", 0.30, 0.05)]
        return all((r[1] is None) or (r[2] is None) for r in (delta(*c) for c in casos))
    check("delta: nunca devuelve puntos y porcentaje a la vez", _exclusivos, lambda r: r is True)
    # el diagnostico expone las dos claves separadas
    def _claves():
        s = [{"fecha": "2026-04-01", "ndvi": 0.50, "ndmi": 0.05},
             {"fecha": "2026-04-20", "ndvi": 0.60, "ndmi": -0.05}]
        d = evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", s,
                            spec={"especie": "TRIGO", "fecha_siembra": "2025-11-10"})
        return d["deltas"]
    check("evaluar_parcela: deltas trae delta_pts y delta_pct (sin la bandera 'pct')",
          _claves,
          lambda r: ("delta_pts" in r["NDVI"] and "delta_pct" in r["NDVI"]
                     and "pct" not in r["NDVI"] and "delta" not in r["NDVI"]))
    check("evaluar_parcela: NDMI en puntos y NDVI en porcentaje",
          _claves,
          lambda r: (r["NDMI"]["delta_pts"] is not None and r["NDMI"]["delta_pct"] is None
                     and r["NDVI"]["delta_pct"] is not None and r["NDVI"]["delta_pts"] is None))

    # texto por reglas (sin OPENAI_API_KEY)
    check("texto: respaldo por reglas", lambda: texto_interpretacion("EXTENSIVO", "COSECHA_GRANO",
          [{"fecha": "2026-06-01", "ndvi": 0.3, "msavi": 0.28, "lai": 1.2, "ndmi": 0.05}],
          spec={"especie": "TRIGO", "fecha_siembra": "2025-11-10"})[0],
          lambda r: isinstance(r, str) and len(r) > 10)

    check("fase: cruce de enero (siega)", lambda: fase_fenologica("EXTENSIVO", "SIEGA_VERDE", "2026-01-15"))
    check("fase: fecha nula -> sin fase", lambda: fase_fenologica("LENOSO", "INTENSIVO", None),
          lambda r: r[0] == "sin fase")
    check("detectar_cubierta: fecha None -> None", lambda: detectar_cubierta("LENOSO", "INTENSIVO",
          [{"fecha": "2026-03-01", "ndvi": 0.5, "msavi": 0.4, "lai": 1.0}], None), lambda r: r is None)


# =====================================================================
# 2. FENOLOGIA POR ESPECIE
# =====================================================================
def pruebas_fenologia():
    from fenologia_especies import (fase_por_especie, densidad_arboles, tipo_plantacion,
                                    subtipo_canonico, fase_cereal, fase_lenoso)
    check("densidad: marco 0 -> None", lambda: densidad_arboles(0, 4), lambda r: r is None)
    check("densidad: None -> None", lambda: densidad_arboles(None, None), lambda r: r is None)
    check("densidad: negativa no revienta", lambda: densidad_arboles(-5, 4))
    check("tipo_plantacion: densidad None", lambda: tipo_plantacion("OLIVO", None))
    check("subtipo_canonico: 5x4 olivo -> INTENSIVO",
          lambda: subtipo_canonico("OLIVO", densidad_arboles(5, 4)), lambda r: r == "INTENSIVO")
    check("subtipo_canonico: especie rara", lambda: subtipo_canonico("MANGO", 300))
    # guardas de fecha (regresion del fallo detectado)
    check("fase_cereal: fecha_siembra basura no revienta",
          lambda: fase_cereal("TRIGO", "ayer", "2026-04-01"), lambda r: "fase" in r)
    check("fase_lenoso: fecha basura no revienta",
          lambda: fase_lenoso("OLIVO", "XX-YY", "5", "4"), lambda r: "fase" in r)
    check("fase_por_especie: cereal", lambda: fase_por_especie("EXTENSIVO", "TRIGO", "2026-04-01",
          fecha_siembra="2025-11-10"), lambda r: r.get("grupo") == "EXTENSIVO")
    check("fase_por_especie: lenoso", lambda: fase_por_especie("LENOSO", "OLIVO", "2026-06-01",
          marco_calle=5, marco_pie=4), lambda r: r.get("grupo") == "LENOSO")
    check("fase_por_especie: barbecho", lambda: fase_por_especie("BARBECHO", "", "2026-06-01"),
          lambda r: r.get("barbecho") is True)
    # --- calendario propio por cultivo extensivo (12 cultivos diferenciados) ---
    from fenologia_especies import EXTENSIVO_ESPECIES, ESPECIES, fase_extensivo
    check("extensivo: la UI lista los 12 cultivos",
          lambda: ESPECIES["EXTENSIVO"], lambda r: len(r) == 12 and "MAIZ" in r and "GIRASOL" in r)
    check("maiz: das~65 -> floracion, NDVI alto, sin caida",
          lambda: fase_extensivo("MAIZ", "2026-04-15", "2026-06-19"),
          lambda r: "floracion" in r["fase"] and r["lo"] >= 0.7 and r["caida"] is False)
    check("maiz: das~135 -> maduracion (dentado) con caida",
          lambda: fase_extensivo("MAIZ", "2026-04-15", "2026-08-28"),
          lambda r: "maduracion" in r["fase"] and r["caida"] is True)
    check("girasol: das~56 -> boton floral",
          lambda: fase_extensivo("GIRASOL", "2026-04-20", "2026-06-15"),
          lambda r: r["fase"] == "boton floral")
    check("cebada mas precoz que trigo (misma siembra, misma fecha)",
          lambda: (fase_extensivo("CEBADA", "2025-11-01", "2026-05-20")["das"],
                   fase_extensivo("CEBADA", "2025-11-01", "2026-05-20")["fase"],
                   fase_extensivo("TRIGO",  "2025-11-01", "2026-05-20")["fase"]),
          lambda r: r[1] != r[2])
    check("remolacha: engorde de raiz sin caida",
          lambda: fase_extensivo("REMOLACHA", "2026-03-15", "2026-07-15"),
          lambda r: "raiz" in r["fase"] and r["caida"] is False)
    check("colza: silicuas",
          lambda: fase_extensivo("COLZA", "2025-10-01", "2026-04-15"),
          lambda r: "silicua" in r["fase"])
    check("extensivo: cultivo desconocido no revienta (fallback)",
          lambda: fase_extensivo("QUINOA", "2026-04-15", "2026-06-15"), lambda r: "fase" in r)
    check("extensivo: sin fecha de siembra -> rango amplio",
          lambda: fase_extensivo("MAIZ", None, "2026-06-15"),
          lambda r: r["fase"] == "sin fecha de siembra" and r["lo"] == 0.15 and r["hi"] == 0.90)
    check("extensivo: presiembra (fecha anterior a siembra)",
          lambda: fase_extensivo("MAIZ", "2026-05-01", "2026-04-15"),
          lambda r: r["fase"] == "presiembra" and r["previo"] is True)


# =====================================================================
# 3. CONTRASTE E HETEROGENEIDAD
# =====================================================================
def pruebas_contraste():
    from contraste_indices import analizar_por_contraste, heterogeneidad
    check("contraste: serie sin msavi/lai", lambda: analizar_por_contraste("LENOSO", "INTENSIVO",
          [{"fecha": "2026-03-01", "ndvi": 0.5}]))
    check("contraste: fecha None -> None", lambda: analizar_por_contraste("LENOSO", "INTENSIVO",
          [{"fecha": None, "ndvi": 0.5}], None), lambda r: r is None)
    check("heterogeneidad: sin estadistica -> disponible False",
          lambda: heterogeneidad([{"fecha": "2026-03-01", "ndvi": 0.5}]), lambda r: r.get("disponible") is False)
    stat = [{"fecha": "2026-04-01", "ndvi": 0.60, "ndvi_std": 0.05, "ndvi_p10": 0.55, "ndvi_p50": 0.60, "ndvi_p90": 0.66},
            {"fecha": "2026-04-15", "ndvi": 0.50, "ndvi_std": 0.14, "ndvi_p10": 0.28, "ndvi_p50": 0.52, "ndvi_p90": 0.66}]
    check("heterogeneidad: deterioro localizado", lambda: heterogeneidad(stat).get("patron"),
          lambda r: r == "deterioro LOCALIZADO")


# =====================================================================
# 4. CUADERNO DE CAMPO
# =====================================================================
def pruebas_cuaderno():
    import registro_parcela as REG
    import almacen as DB
    DB.conectar(os.path.join(tempfile.mkdtemp(), "cuaderno.db"))   # BD temporal aislada
    serie = [{"fecha": "2026-04-01", "ndvi": 0.7, "ndmi": 0.25}, {"fecha": "2026-04-20", "ndvi": 0.35, "ndmi": 0.15}]
    check("efecto_producto: normal", lambda: REG.efecto_producto(serie,
          {"fecha": "2026-04-05", "tipo": "PRODUCTO", "objetivo": "fungicida"}))
    check("efecto_producto: fecha basura no revienta", lambda: REG.efecto_producto(serie,
          {"fecha": "XXX", "tipo": "PRODUCTO"}))
    check("efecto_producto: sin fecha -> None", lambda: REG.efecto_producto(serie, {"tipo": "PRODUCTO"}),
          lambda r: r is None)
    # elegir el dia del informe (varias pasadas posteriores)
    serie_d = [{"fecha": "2026-04-01", "ndvi": 0.40, "ndmi": 0.10},
               {"fecha": "2026-04-12", "ndvi": 0.46}, {"fecha": "2026-04-26", "ndvi": 0.56},
               {"fecha": "2026-05-12", "ndvi": 0.63}]
    ev_d = {"fecha": "2026-04-05", "tipo": "PRODUCTO", "objetivo": "fungicida"}
    check("efecto: dia informe por objetivo (pasada mas cercana)",
          lambda: REG.efecto_producto(serie_d, ev_d, fecha_objetivo="2026-04-26"),
          lambda r: r["disponible"] and r["dia_informe"] == "2026-04-26")
    check("efecto: dia informe guardado en el evento (fecha_informe)",
          lambda: REG.efecto_producto(serie_d, dict(ev_d, fecha_informe="2026-04-12")),
          lambda r: r["dia_informe"] == "2026-04-12")
    check("efecto: fecha_objetivo tiene prioridad sobre fecha_informe",
          lambda: REG.efecto_producto(serie_d, dict(ev_d, fecha_informe="2026-04-12"),
                                      fecha_objetivo="2026-05-12"),
          lambda r: r["dia_informe"] == "2026-05-12")
    check("efecto: sin objetivo usa el automatico (pasada mas tardia dentro de ventana)",
          lambda: REG.efecto_producto(serie_d, ev_d), lambda r: r["dia_informe"] == "2026-05-12")
    # HERBICIDA: el efecto se mide por la bajada de LAI
    serie_h = [{"fecha": "2026-04-01", "ndvi": 0.6, "lai": 2.5}, {"fecha": "2026-04-25", "ndvi": 0.5, "lai": 1.8}]
    ev_h = {"fecha": "2026-04-05", "tipo": "PRODUCTO", "objetivo": "herbicida (malas hierbas)"}
    check("efecto herbicida: baja de LAI -> efecto compatible",
          lambda: REG.efecto_producto(serie_h, ev_h),
          lambda r: r["es_herbicida"] and r["d_lai"] == -0.7 and "area foliar" in r["verdicto"])
    serie_hn = [{"fecha": "2026-04-01", "ndvi": 0.5, "lai": 2.0}, {"fecha": "2026-04-25", "ndvi": 0.55, "lai": 2.4}]
    check("efecto herbicida: LAI sube -> sin efecto visible",
          lambda: REG.efecto_producto(serie_hn, ev_h)["verdicto"], lambda r: "sin efecto" in r)
    # LAI CONSTANTE: la desambiguacion vive en el modulo OPCIONAL herbicida_contexto.
    # Estas dos comprobaciones solo se ejecutan si el modulo esta presente (si se
    # borra el fichero, se omiten y la suite sigue verde -> parte extraible limpia).
    s_homog = [{"fecha": "2026-04-01", "ndvi": 0.55, "lai": 2.2, "ndvi_std": 0.14},
               {"fecha": "2026-04-25", "ndvi": 0.56, "lai": 2.15, "ndvi_std": 0.07}]
    s_estanca = [{"fecha": "2026-03-10", "ndvi": 0.4, "lai": 1.5},
                 {"fecha": "2026-04-01", "ndvi": 0.55, "lai": 2.2},
                 {"fecha": "2026-04-25", "ndvi": 0.56, "lai": 2.2}]
    if REG._HB is not None:
        check("efecto herbicida: LAI plano + dispersion baja -> efecto probable (homogeneiza)",
              lambda: REG.efecto_producto(s_homog, ev_h)["verdicto"],
              lambda r: "probable" in r and "HOMOGENEIZA" in r)
        check("efecto herbicida: LAI plano pero venia subiendo -> efecto probable (frena)",
              lambda: REG.efecto_producto(s_estanca, ev_h)["verdicto"],
              lambda r: "probable" in r and "SUBIENDO" in r)
    s_plano = [{"fecha": "2026-04-01", "ndvi": 0.55, "lai": 2.2},
               {"fecha": "2026-04-25", "ndvi": 0.56, "lai": 2.2}]
    check("efecto herbicida: LAI plano sin contexto -> sin cambio claro",
          lambda: REG.efecto_producto(s_plano, ev_h)["verdicto"], lambda r: "sin cambio claro" in r)

    def _sin_modulo():
        # simula BORRAR el fichero herbicida_contexto.py: _HB queda a None
        guardado = REG._HB
        REG._HB = None
        try:
            return REG.efecto_producto(s_homog, ev_h)["verdicto"]
        finally:
            REG._HB = guardado                       # restaurar para el resto de pruebas
    check("efecto herbicida: sin el modulo opcional -> comportamiento base",
          _sin_modulo, lambda r: "sin cambio claro" in r)
    check("explicacion_por_eventos: siega explica caida", lambda: REG.explicacion_por_eventos(
          [(2, {"tipo": "SIEGA", "fecha": "2026-04-18"})], -0.3), lambda r: r[0] is True)
    check("explicacion_por_eventos: dN None", lambda: REG.explicacion_por_eventos(
          [(2, {"tipo": "SIEGA", "fecha": "2026-04-18"})], None), lambda r: r[0] is False)
    # regresion: ids unicos aunque se borre y se re-anada un evento con la misma fecha
    def _ids_unicos():
        a = REG.registrar_evento("P", "2025-2026", {"fecha": "2026-04-10", "tipo": "SIEGA"})
        b = REG.registrar_evento("P", "2025-2026", {"fecha": "2026-04-10", "tipo": "SIEGA"})
        REG.eliminar_evento("P", "2025-2026", a["id"])
        c = REG.registrar_evento("P", "2025-2026", {"fecha": "2026-04-10", "tipo": "SIEGA"})
        ids = [e["id"] for e in REG.eventos_de("P", "2025-2026")]
        return len(ids) == len(set(ids)) and b["id"] != c["id"]
    check("cuaderno: ids unicos tras borrar y re-anadir (misma fecha)", _ids_unicos, lambda r: r is True)
    # regresion: eventos_cercanos no revienta con fecha de referencia vacia/mal formada
    REG.registrar_evento("Q", "2025-2026", {"fecha": "2026-04-10", "tipo": "SIEGA"})
    check("cuaderno: eventos_cercanos con fecha_iso vacia -> [] (no crash)",
          lambda: REG.eventos_cercanos("Q", "2025-2026", ""), lambda r: r == [])
    check("cuaderno: eventos_cercanos con fecha_iso basura -> [] (no crash)",
          lambda: REG.eventos_cercanos("Q", "2025-2026", "10/2026"), lambda r: r == [])

    # ---- COSECHA: captura del rendimiento (kg/ha). Dato de bascula, no estimado.
    check("cosecha: humedad solo en grano de extensivo",
          lambda: REG.admite_humedad_grano({"tipo": "EXTENSIVO", "subtipo": "COSECHA_GRANO"}),
          lambda r: r is True)
    check("cosecha: lenoso no admite humedad de grano",
          lambda: REG.admite_humedad_grano({"tipo": "LENOSO", "subtipo": "ALMENDRO"}),
          lambda r: r is False)
    check("cosecha: sin cultivo no admite humedad",
          lambda: REG.admite_humedad_grano(None), lambda r: r is False)
    check("cosecha: siega en verde no admite humedad de grano",
          lambda: REG.admite_humedad_grano({"tipo": "EXTENSIVO", "subtipo": "SIEGA_VERDE"}),
          lambda r: r is False)
    check("cosecha: extensivo sin subtipo cuenta como grano (fichas antiguas)",
          lambda: REG.admite_humedad_grano({"tipo": "EXTENSIVO"}), lambda r: r is True)
    # al cargar historico, la campana vieja no tiene cultivo registrado: se hereda
    # el de la campana que se esta viendo, o la humedad desapareceria justo ahi
    trigo = {"tipo": "EXTENSIVO", "subtipo": "COSECHA_GRANO"}
    almendro = {"tipo": "LENOSO", "subtipo": "INTENSIVO"}
    check("cosecha: campana vieja sin cultivo hereda el de la campana vista",
          lambda: REG.admite_humedad_en_campana({}, trigo), lambda r: r is True)
    check("cosecha: campana vieja sin cultivo, parcela de lenoso -> sigue sin humedad",
          lambda: REG.admite_humedad_en_campana({}, almendro), lambda r: r is False)
    check("cosecha: si la campana vieja SI declara cultivo, manda ella",
          lambda: REG.admite_humedad_en_campana(almendro, trigo), lambda r: r is False)
    check("cosecha: numero_opcional acepta coma decimal",
          lambda: REG.numero_opcional(" 12,5 "), lambda r: r == 12.5)
    check("cosecha: numero_opcional vacio -> None",
          lambda: REG.numero_opcional("   "), lambda r: r is None)
    check("cosecha: numero_opcional negativo -> error",
          lambda: _lanza(REG.numero_opcional, ValueError, "-3"), lambda r: r is True)
    # 'nan' burlaria la comprobacion del signo y se escribiria como NaN (JSON invalido)
    for _basura in ("nan", "inf", "-inf", "NaN", "Infinity"):
        check(f"cosecha: numero_opcional rechaza '{_basura}'",
              (lambda b: lambda: _lanza(REG.numero_opcional, ValueError, b))(_basura),
              lambda r: r is True)
    check("cosecha: 'nan' no llega a la base como NaN",
          lambda: _lanza(REG.datos_cosecha, ValueError, "nan"), lambda r: r is True)
    check("cosecha: datos_cosecha completo",
          lambda: REG.datos_cosecha("4500", "12,5", "3.2", "bascula"),
          lambda r: r == {"rendimiento_kg_ha": 4500.0, "humedad_grano_pct": 12.5,
                          "superficie_cosechada_ha": 3.2, "fuente_dato": "bascula"})
    check("cosecha: todo vacio -> no se anota nada",
          lambda: REG.datos_cosecha("", "", "", ""), lambda r: r == {})
    check("cosecha: sin derecho a humedad, se ignora aunque venga escrita",
          lambda: REG.datos_cosecha("4500", "12,5", None, None, admite_humedad=False),
          lambda r: "humedad_grano_pct" not in r and r["rendimiento_kg_ha"] == 4500.0)
    check("cosecha: humedad > 100 % -> error nombrando el campo",
          lambda: _lanza(REG.datos_cosecha, ValueError, None, "120"), lambda r: r is True)
    check("cosecha: texto no numerico -> error nombrando el campo",
          lambda: _mensaje_error(REG.datos_cosecha, "cuatro mil"),
          lambda r: "rendimiento" in r)
    check("cosecha: fuente_dato incluye las cuatro origenes previstas",
          lambda: REG.FUENTES_DATO,
          lambda r: {"memoria", "bascula"} <= set(r) and len(r) == 4)

    # historico por campana: incluye campanas anteriores y solo eventos COSECHA con dato
    def _historico_rend():
        REG.registrar_evento("R", "2023-2024", {"fecha": "2024-07-05", "tipo": "COSECHA",
                                                "rendimiento_kg_ha": 3800.0,
                                                "humedad_grano_pct": 11.0, "fuente_dato": "albaran"})
        REG.registrar_evento("R", "2025-2026", {"fecha": "2026-07-01", "tipo": "COSECHA",
                                                "rendimiento_kg_ha": 4500.0})
        REG.registrar_evento("R", "2025-2026", {"fecha": "2026-07-02", "tipo": "COSECHA"})
        REG.registrar_evento("R", "2025-2026", {"fecha": "2026-05-01", "tipo": "SIEGA"})
        REG.registrar_evento("OTRA", "2025-2026", {"fecha": "2026-07-01", "tipo": "COSECHA",
                                                   "rendimiento_kg_ha": 9999.0})
        return DB.rendimientos("R")
    check("almacen.rendimientos: historico de varias campanas, solo cosechas con dato",
          _historico_rend,
          lambda r: [x["campana"] for x in r] == ["2023-2024", "2025-2026"] and
                    r[0]["rendimiento_kg_ha"] == 3800.0 and r[0]["fuente_dato"] == "albaran" and
                    r[1] == {"campana": "2025-2026", "fecha": "2026-07-01",
                             "rendimiento_kg_ha": 4500.0})
    check("almacen.rendimientos: parcela sin cosechas -> []",
          lambda: DB.rendimientos("SIN_COSECHA"), lambda r: r == [])

    # la COSECHA se archiva en la campana de SU fecha (asi se carga historico viejo)
    check("cosecha: fecha de julio de 2024 -> campana 2023-2024",
          lambda: REG.campana_de_evento("COSECHA", "2024-07-05", "2025-2026"),
          lambda r: r == "2023-2024")
    check("cosecha: fecha de octubre -> campana que empieza ese ano",
          lambda: REG.campana_de_evento("COSECHA", "2024-10-02", "2025-2026"),
          lambda r: r == "2024-2025")
    check("cuaderno: el resto de eventos se quedan en la campana vista",
          lambda: REG.campana_de_evento("SIEGA", "2024-07-05", "2025-2026"),
          lambda r: r == "2025-2026")
    check("cuaderno: fecha ilegible no cambia de campana",
          lambda: REG.campana_de_evento("COSECHA", "05/07/2024", "2025-2026"),
          lambda r: r == "2025-2026")
    check("cosecha: linea del historico con todos los datos",
          lambda: REG.linea_rendimiento({"campana": "2023-2024", "fecha": "2024-07-05",
                                         "rendimiento_kg_ha": 4500.0, "humedad_grano_pct": 12.5,
                                         "superficie_cosechada_ha": 3.2, "fuente_dato": "bascula"}),
          lambda r: "4.500 kg/ha" in r and "12,5 %" in r and "3,20 ha" in r and "bascula" in r)
    check("cosecha: linea con solo el rendimiento no inventa el resto",
          lambda: REG.linea_rendimiento({"campana": "2025-2026", "rendimiento_kg_ha": 4500.0}),
          lambda r: r == "2025-2026  ·  4.500 kg/ha")


def _lanza(fn, exc, *args, **kw):
    """True si `fn` lanza `exc`. Evita repetir try/except en cada comprobacion."""
    try:
        fn(*args, **kw)
    except exc:
        return True
    return False


def _mensaje_error(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except ValueError as e:
        return str(e)
    return ""


# =====================================================================
# 4b. UMBRALES POR FASE Y CALIBRACION POR VALIDACIONES
# =====================================================================
def pruebas_umbrales():
    import fenologia_especies as FEN
    from interpretacion_fenologica import evaluar_parcela

    # --- estructura: las filas sin umbrales propios se comportan como siempre
    check("umbrales: por defecto son los de antes (NDMI cruzando el cero)",
          lambda: FEN.umbrales_de_fase(None),
          lambda r: r["ndmi_min"] == 0.0 and r["lai_min"] == 2.0 and r["critica"] is False)
    check("umbrales: lo declarado por la fase manda",
          lambda: FEN.umbrales_de_fase({"ndmi_min": 0.22, "critica": True}),
          lambda r: r["ndmi_min"] == 0.22 and r["critica"] is True and r["lai_min"] == 2.0)
    check("umbrales: None significa 'aqui el indice no dice nada'",
          lambda: FEN.umbrales_de_fase({"ndmi_min": None})["ndmi_min"], lambda r: r is None)
    check("umbrales: no se han tocado los seis valores de siempre de ninguna fila",
          lambda: [f for e in FEN.EXTENSIVO_ESPECIES.values() for f in e["fases"]
                   if not (isinstance(f[3], float) and isinstance(f[4], float)
                           and isinstance(f[5], bool))],
          lambda r: r == [])

    # --- el umbral sale de la FASE, no de una constante unica
    def _ndmi_por_fase(especie, siembra, fecha):
        serie = [{"fecha": fecha, "ndvi": 0.60, "ndmi": 0.05, "lai": 3.0}]
        return evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", serie,
                               spec={"especie": especie, "fecha_siembra": siembra})
    check("umbrales: maiz en floracion con NDMI 0.05 -> avisa (umbral 0.22)",
          lambda: _ndmi_por_fase("MAIZ", "2026-04-01", "2026-06-05"),
          lambda d: "hidrico" in d["motivo"] and "floracion" in d["fase"])
    check("umbrales: fase critica, se dice que lo es",
          lambda: _ndmi_por_fase("MAIZ", "2026-04-01", "2026-06-05")["motivo"],
          lambda t: "se lleva por delante el rendimiento" in t)
    check("umbrales: trigo en rastrojo con NDMI -0.3 -> ya NO avisa (secarse es normal)",
          lambda: evaluar_parcela("EXTENSIVO", "COSECHA_GRANO",
                                  [{"fecha": "2026-08-01", "ndvi": 0.10, "ndmi": -0.30, "lai": 0.3}],
                                  spec={"especie": "TRIGO", "fecha_siembra": "2025-10-15"}),
          lambda d: "hidrico" not in d["motivo"])
    check("umbrales: en barbecho el NDMI no se juzga",
          lambda: evaluar_parcela("BARBECHO", "",
                                  [{"fecha": "2026-05-01", "ndvi": 0.10, "ndmi": -0.4}]),
          lambda d: "hidrico" not in d["motivo"])

    # --- calibracion (modulo OPCIONAL: si se borra, estas se omiten)
    try:
        import calibracion_umbrales as CAL
    except Exception:
        return
    import almacen as DB
    DB.conectar(os.path.join(tempfile.mkdtemp(), "cal.db"))
    DB.guardar_ficha("Vega", {"propietario": "x", "coordenadas": [[0, 0]], "superficie_ha": 5,
                              "provincia": "47", "municipio": "47/186"})
    DB.guardar_ficha("Suelta", {"propietario": "x", "coordenadas": [[0, 0]], "superficie_ha": 5})
    check("calibracion: los ambitos salen de la ubicacion guardada",
          lambda: [a for a, _ in CAL.ambitos_de("Vega")],
          lambda r: r == ["parcela", "municipio", "provincia", "global"])
    check("calibracion: sin ubicacion solo hay parcela y global (no se inventa)",
          lambda: [a for a, _ in CAL.ambitos_de("Suelta")], lambda r: r == ["parcela", "global"])

    UMB = {"lo": 0.60, "hi": 0.92, "ndmi_min": 0.12, "lai_min": 3.0}
    check("calibracion: veredicto del sistema por indice",
          lambda: (CAL.veredicto_sistema("NDMI", 0.09, UMB),
                   CAL.veredicto_sistema("NDVI", 0.95, UMB),
                   CAL.veredicto_sistema("NDVI", 0.70, UMB)),
          lambda r: r == ("bajo", "alto", "normal"))
    check("calibracion: donde la fase no define umbral, no hay criterio",
          lambda: CAL.veredicto_sistema("NDMI", -0.2, {"ndmi_min": None}),
          lambda r: r == CAL.SIN_CRITERIO)
    # EVI, SAVI y GNDVI se usan por CONTRASTE entre ellos, no contra una constante:
    # no hay umbral que mover. MSAVI si, porque es el indice de la copa en lenosos.
    check("calibracion: los indices de contraste no son calibrables",
          lambda: [i for i in ("EVI", "SAVI", "GNDVI") if i in CAL.CALIBRABLES],
          lambda r: r == [])
    check("calibracion: MSAVI si lo es (es el indice de la copa)",
          lambda: "MSAVI" in CAL.CALIBRABLES, lambda r: r is True)

    spec = {"especie": "TRIGO", "fecha_siembra": "2025-11-01"}
    serie = [{"fecha": "2026-03-20", "ndvi": 0.70, "ndmi": 0.14, "lai": 3.2},
             {"fecha": "2026-04-05", "ndvi": 0.72, "ndmi": 0.09, "lai": 3.3}]
    d0 = evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", serie, spec=spec, parcela="Vega")
    FASE = d0["fase"]
    check("calibracion: sin validaciones manda la tabla",
          lambda: (d0["estado"], d0["umbrales"]["ndmi_min"]), lambda r: r == ("Vigilar", 0.12))

    def _valida(n, ambito="municipio", parcela="Vega", dijo="normal"):
        for k in range(n):
            CAL.registrar(parcela, "2025-2026", f"2026-04-0{k + 1}", "TRIGO", FASE,
                          {"NDMI": {"valor": 0.09 + k * 0.005, "sistema": "bajo"}},
                          {"NDMI": dijo}, ambito)

    def _ndmi(parcela="Vega"):
        return evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", serie, spec=spec,
                               parcela=parcela)["umbrales"]["ndmi_min"]

    # CUANTAS hacen falta. El minimo estaba en 2, y con 2 se podia mover el umbral
    # de una PROVINCIA entera. Ahora son MIN_OBSERVACIONES.
    check("calibracion: los dos frenos son numeros distintos y explicitos",
          lambda: (CAL.MIN_OBSERVACIONES, CAL.MIN_FECHAS, CAL.DESVIACION_MAX),
          lambda r: r == (5, 2, 0.10))
    _valida(1)
    check("calibracion: UNA sola validacion no mueve el umbral",
          lambda: _ndmi(), lambda r: r == 0.12)
    # numeros LITERALES a proposito: si alguien baja la constante, esta prueba
    # tiene que caerse por el comportamiento, no solo por el valor de la constante
    _valida(4)
    check("calibracion: cuatro validaciones de cuatro pasadas todavia no lo mueven",
          lambda: (len(DB.validaciones_indice(indice="NDMI",
                                              ambitos=[("municipio", "47/186")])), _ndmi()),
          lambda r: r == (4, 0.12))
    _valida(5)
    d1 = evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", serie, spec=spec, parcela="Vega")
    check("calibracion: con el minimo de coherentes el umbral baja y el estado cambia",
          lambda: (d1["estado"], d1["umbrales"]["ndmi_min"] < 0.12), lambda r: r == ("OK", True))
    check("calibracion: se explica de donde sale el umbral, y de cuantas pasadas",
          lambda: CAL.texto_calibracion(d1["umbrales"]),
          lambda t: "municipio" in t and "validaciones" in t and "pasadas" in t)

    # DE CUANTAS PASADAS. Un ambito amplio puede juntar el minimo en UN SOLO DIA:
    # basta con validar varias parcelas del mismo municipio esa tarde. Eso no son
    # N observaciones, es una: misma escena, misma correccion, misma visita.
    def _mismo_dia(n, fecha="2026-05-11"):
        """n parcelas del MISMO municipio validadas EL MISMO dia."""
        for k in range(n):
            p = f"Quincena_{k}"
            DB.guardar_ficha(p, {"propietario": "x", "coordenadas": [[0, 0]],
                                 "superficie_ha": 5, "provincia": "09",
                                 "municipio": "09/500"})
            CAL.registrar(p, "2025-2026", fecha, "TRIGO", FASE,
                          {"NDMI": {"valor": 0.09 + k * 0.005, "sistema": "bajo"}},
                          {"NDMI": "normal"}, "municipio")
        return p
    _mismo_dia(CAL.MIN_OBSERVACIONES + 2)
    check("calibracion: de sobra en numero pero TODAS del mismo dia -> no mueve nada",
          lambda: (len(DB.validaciones_indice(indice="NDMI",
                                              ambitos=[("municipio", "09/500")])),
                   CAL.umbral_calibrado("NDMI", "ndmi_min", 0.12, "TRIGO", FASE,
                                        [("municipio", "09/500")])),
          lambda r: r[0] == CAL.MIN_OBSERVACIONES + 2 and r[1] is None)
    CAL._invalidar()
    # una sola validacion mas, en OTRO dia, es lo que convierte esas lecturas en
    # observaciones repartidas en el tiempo
    _mismo_dia(1, fecha="2026-06-02")
    CAL._invalidar()
    check("calibracion: en cuanto hay una pasada de otro dia, ya se puede mover",
          lambda: CAL.umbral_calibrado("NDMI", "ndmi_min", 0.12, "TRIGO", FASE,
                                       [("municipio", "09/500")]),
          lambda r: r is not None and r["fechas"] == 2 and r["valor"] < 0.12)
    check("calibracion: la BIBLIOGRAFIA no se ha tocado",
          lambda: dict(FEN.EXTENSIVO_ESPECIES["TRIGO"]["fases"][3][6]),
          lambda r: r["ndmi_min"] == 0.12)
    check("calibracion: sin pasar parcela se juzga con la tabla",
          lambda: evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", serie,
                                  spec=spec)["umbrales"]["ndmi_min"], lambda r: r == 0.12)
    check("calibracion: otra parcela del mismo municipio hereda el ajuste",
          lambda: (DB.guardar_ficha("Otra", {"propietario": "x", "coordenadas": [[0, 0]],
                                             "superficie_ha": 5, "provincia": "47",
                                             "municipio": "47/186"}),
                   evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", serie, spec=spec,
                                   parcela="Otra")["umbrales"]["ndmi_min"])[1],
          lambda r: r < 0.12)
    check("calibracion: una parcela de OTRO municipio no se entera",
          lambda: (DB.guardar_ficha("Lejos", {"propietario": "x", "coordenadas": [[0, 0]],
                                              "superficie_ha": 5, "provincia": "09",
                                              "municipio": "09/001"}),
                   evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", serie, spec=spec,
                                   parcela="Lejos")["umbrales"]["ndmi_min"])[1],
          lambda r: r == 0.12)

    # el tope: por muchas validaciones locas que haya, no se desmadra
    def _desmadre():
        for k in range(30):
            CAL.registrar("Vega", "2025-2026", f"2027-01-{k + 1:02d}", "TRIGO", FASE,
                          {"NDMI": {"valor": -0.45, "sistema": "bajo"}}, {"NDMI": "normal"},
                          "parcela")
        return evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", serie, spec=spec,
                               parcela="Vega")["umbrales"]["ndmi_min"]
    check("calibracion: el ajuste esta acotado (no se lo lleva una racha de errores)",
          _desmadre, lambda r: r >= 0.12 - CAL.DESVIACION_MAX - 1e-9)
    check("calibracion: manda el ambito MAS concreto (parcela sobre municipio)",
          lambda: CAL.umbral_calibrado("NDMI", "ndmi_min", 0.12, "TRIGO", FASE,
                                       CAL.ambitos_de("Vega"))["ambito"],
          lambda r: r == "parcela")
    check("calibracion: donde la tabla no define umbral, no se inventa uno",
          lambda: CAL.umbral_calibrado("NDMI", "ndmi_min", None, "TRIGO", "rastrojo / cosecha",
                                       CAL.ambitos_de("Vega")), lambda r: r is None)
    check("almacen: las validaciones por indice se borran con la parcela",
          lambda: (DB.eliminar_parcela("Vega"),
                   DB.validaciones_indice(ambitos=[("parcela", "Vega")]))[1], lambda r: r == [])


# =====================================================================
# 4c. LEÑOSOS: FASES FISIOLOGICAS, REGIMEN HIDRICO Y COPA vs CUBIERTA
# =====================================================================
def pruebas_lenosos():
    import fenologia_especies as FEN
    from contraste_indices import separacion_copa_cubierta
    from interpretacion_fenologica import evaluar_parcela

    # --- fases fisiologicas, no meses con nombre generico
    check("lenoso: cada especie declara su calendario fisiologico",
          lambda: sorted(FEN.FASES_LENOSO), lambda r: r == ["ALMENDRO", "OLIVO", "PISTACHO", "VIÑA"])
    check("lenoso: el olivo tiene su ventana critica de endurecimiento de hueso",
          lambda: (FEN.FASES_LENOSO["OLIVO"][6], FEN.FASES_LENOSO["OLIVO"][7]),
          lambda r: r == ("endurecimiento de hueso", "endurecimiento de hueso"))
    check("lenoso: los 12 meses tienen fase en las cuatro especies",
          lambda: [e for e, t in FEN.FASES_LENOSO.items() if sorted(t) != list(range(1, 13))],
          lambda r: r == [])

    # --- el regimen cambia el juicio con el MISMO dato
    def _olivo(mes, reg, **kw):
        base = {"fecha": f"2026-{mes:02d}-15", "ndvi": 0.55, "msavi": 0.42, "ndmi": 0.06,
                "lai": 2.2, "evi": 0.33, "savi": 0.47, "gndvi": 0.52}
        base.update(kw)
        serie = [dict(base, fecha=f"2026-{mes:02d}-01"), base]
        return evaluar_parcela("LENOSO", "INTENSIVO", serie,
                               spec={"especie": "OLIVO", "marco_calle": 6.0,
                                     "marco_pie": 5.0, "regimen": reg})
    check("lenoso: en REGADIO un NDMI 0.06 en julio es aviso",
          lambda: _olivo(7, "REGADIO")["estado"], lambda r: r in ("Vigilar", "Revisar"))
    check("lenoso: en SECANO el mismo dato es normal (deficit por diseno)",
          lambda: _olivo(7, "SECANO")["estado"], lambda r: r == "OK")
    check("lenoso: y se explica por que no se avisa",
          lambda: _olivo(7, "SECANO")["motivo"],
          lambda t: "deficit hidrico es lo esperado" in t)
    check("lenoso: la fase critica se dice",
          lambda: _olivo(7, "REGADIO")["umbrales"].get("critica"), lambda r: r is True)
    check("lenoso: un regimen desconocido cae en SECANO (el que no alarma)",
          lambda: FEN.regimen_valido("lo que sea"), lambda r: r == "SECANO")
    check("lenoso: sin regimen declarado, tambien SECANO",
          lambda: _olivo(7, None)["estado"], lambda r: r == "OK")

    # --- viña en envero: el deficit es intencionado
    def _vina(mes):
        base = {"fecha": f"2026-{mes:02d}-15", "ndvi": 0.50, "msavi": 0.38, "ndmi": -0.02,
                "lai": 1.9, "evi": 0.30, "savi": 0.43, "gndvi": 0.47}
        return evaluar_parcela("LENOSO", "INTENSIVO",
                               [dict(base, fecha=f"2026-{mes:02d}-01"), base],
                               spec={"especie": "VIÑA", "marco_calle": 2.5,
                                     "marco_pie": 1.2, "regimen": "REGADIO"})
    check("lenoso: viña en envero -> el deficit es buscado, no se alarma",
          lambda: (_vina(7)["fase"], _vina(7)["estado"]), lambda r: r == ("envero", "OK"))
    check("lenoso: viña en floracion SI se juzga el agua",
          lambda: FEN.fase_lenoso("VIÑA", "2026-06-15", 2.5, 1.2, "REGADIO")["ndmi_min"],
          lambda r: r == 0.16)

    # --- sin hoja no se juzga ningun indice de copa
    check("lenoso: en parada sin hoja no hay umbral de copa ni de agua",
          lambda: FEN.fase_lenoso("ALMENDRO", "2026-01-15", 6.0, 5.0, "REGADIO"),
          lambda d: d["msavi_min"] is None and d["ndmi_min"] is None and d["sin_hoja"] is True)

    # --- la densidad entra por la FRACCION DE COPA, no por un factor a ojo
    # Antes esta prueba fijaba que el marco escalaba `msavi_min` por 0.82/1.12: un
    # +-15 % sobre una magnitud que cambia por un factor de 2 o 3 entre un
    # tradicional y un seto, y ademas de la forma equivocada (lo que cambia con la
    # densidad no es el vigor de la copa, es cuanto pixel ES copa). El umbral de
    # copa es ahora el mismo para los dos -es el arbol, no la plantacion- y lo que
    # cambia es su traduccion a la escala de la media de la parcela.
    _trad = FEN.fase_lenoso("OLIVO", "2026-07-15", 12.0, 12.0, "REGADIO")
    _seto = FEN.fase_lenoso("OLIVO", "2026-07-15", 1.5, 1.2, "REGADIO")
    check("lenoso: el umbral DE COPA no depende del marco (es el arbol, no el marco)",
          lambda: (_trad["msavi_min"], _seto["msavi_min"]),
          lambda r: r[0] == r[1] == 0.38)
    check("lenoso: un seto tapa mucho mas suelo que un olivar tradicional",
          lambda: (_trad["fraccion_copa"], _seto["fraccion_copa"]),
          lambda r: 0.15 < r[0] < 0.25 and r[1] > 0.7)
    check("lenoso: y por eso a un seto SI se le exige mas MSAVI de parcela",
          lambda: (_trad["msavi_min_parcela"], _seto["msavi_min_parcela"]),
          lambda r: r[0] < r[1] and r[1] > 2 * r[0])
    check("lenoso: el umbral de parcela de un tradicional queda donde ese olivar mide",
          lambda: _trad["msavi_min_parcela"],
          lambda v: 0.10 < v < 0.20)
    check("lenoso: sin marco no hay conversion posible y se deja el umbral de copa",
          lambda: FEN.fase_lenoso("OLIVO", "2026-07-15", None, None, "REGADIO"),
          lambda d: d["fraccion_copa"] is None and d["msavi_min_parcela"] == d["msavi_min"])
    check("lenoso: la fraccion de copa nunca llega al 100 % del suelo",
          lambda: FEN.fraccion_copa("OLIVO", 1.0, 1.0), lambda v: v == FEN.FC_MAXIMA)
    check("lenoso: con diametro de copa medido se usa ese, no la estimacion",
          lambda: (FEN.fraccion_copa("OLIVO", 10.0, 10.0),
                   FEN.fraccion_copa("OLIVO", 10.0, 10.0, diametro_copa=7.0)),
          lambda r: r[1] > r[0])

    # --- DIAMETRO DE COPA: el dato que quita la ultima suposicion ---
    # Dos olivares al MISMO marco, uno joven y otro viejo, tapan distinto suelo y
    # por tanto no se les puede pedir el mismo MSAVI de parcela. Sin el dato se
    # estima del marco y los dos salen iguales, que es como estaba antes.
    _joven = FEN.fase_lenoso("OLIVO", "2026-07-15", 10.0, 10.0, "SECANO", diametro_copa=2.5)
    _viejo = FEN.fase_lenoso("OLIVO", "2026-07-15", 10.0, 10.0, "SECANO", diametro_copa=7.0)
    _estim = FEN.fase_lenoso("OLIVO", "2026-07-15", 10.0, 10.0, "SECANO")
    check("copa: al mismo marco, un olivar viejo tapa mas suelo que uno joven",
          lambda: (_joven["fraccion_copa"], _viejo["fraccion_copa"]),
          lambda r: r[0] < r[1] and r[0] < 0.10 and r[1] > 0.35)
    check("copa: y por eso al viejo se le exige mas MSAVI de parcela",
          lambda: (_joven["msavi_min_parcela"], _viejo["msavi_min_parcela"]),
          lambda r: r[0] < r[1])
    check("copa: sin el dato se estima del marco y queda entre los dos",
          lambda: (_joven["fraccion_copa"], _estim["fraccion_copa"], _viejo["fraccion_copa"]),
          lambda r: r[0] < r[1] < r[2])
    check("copa: la ficha dice si la copa esta medida o estimada",
          lambda: (_viejo["copa_medida"], _estim["copa_medida"]),
          lambda r: r == (True, False))
    import cultivo as _CU
    check("copa: el modelo de cultivo lleva el diametro (y los registros viejos, None)",
          lambda: (_CU.spec_de({"especie": "OLIVO", "diametro_copa": 5.0})["diametro_copa"],
                   _CU.spec_de({"especie": "OLIVO"})["diametro_copa"]),
          lambda r: r == (5.0, None))
    check("copa: llega hasta el diagnostico por spec, no solo hasta la tabla",
          lambda: FEN.fase_por_especie("LENOSO", "OLIVO", "2026-07-15", marco_calle=10.0,
                                       marco_pie=10.0, regimen="SECANO",
                                       diametro_copa=7.0)["fraccion_copa"],
          lambda v: v == _viejo["fraccion_copa"])
    # el texto que se ve al teclear el marco: es donde el usuario se entera
    check("copa: el resumen del marco dice cuanto suelo tapa la copa",
          lambda: FEN.texto_marco("OLIVO", 10.0, 10.0, 7.0),
          lambda t: "100 arboles/ha" in t and "tradicional" in t and "%" in t
                    and "copa medida" in t)
    check("copa: y avisa cuando la copa esta estimada, no medida",
          lambda: FEN.texto_marco("OLIVO", 10.0, 10.0),
          lambda t: "copa estimada del marco" in t)
    check("copa: sin marco no hay resumen que dar",
          lambda: FEN.texto_marco("OLIVO", None, None), lambda t: t == "")
    check("lenoso: el umbral de parcela es una mezcla, entre el suelo y la copa",
          lambda: FEN.umbral_en_escala_parcela(0.38, 0.20),
          lambda v: v == round(0.20 * 0.38 + 0.80 * FEN.MSAVI_SUELO, 3))

    # --- EL AVISO FALSO DEL TRADICIONAL, de punta a punta ---
    # Un olivar tradicional a 12x12 mide NDVI 0.17 y MSAVI 0.11 con el arbol
    # PERFECTO, porque cuatro quintas partes del pixel son calle. Los rangos de
    # LENOSO_ESPECIES y los msavi_min de UMBRALES_LENOSO son valores de COPA. Antes
    # se comparaban directamente y saltaba "Revisar" siempre. Estas pruebas fijan
    # que la sana sale limpia y la floja sigue saltando, en los tres tipos de
    # plantacion: es lo unico que demuestra que no se ha tapado el aviso entero.
    def _grove(marco_calle, marco_pie, fc, copa, fondo=(0.28, 0.24), con_p10=True):
        """Parcela sintetica a partir de FISICA: se mezclan las reflectancias de
        copa y suelo segun la fraccion de copa, y de ahi salen los indices."""
        def _msavi(N, R):
            return round((2 * N + 1 - math.sqrt((2 * N + 1) ** 2 - 8 * (N - R))) / 2, 3)
        def _ndvi(N, R):
            return round((N - R) / (N + R), 3)
        def _mez(f):
            return (f * copa[0] + (1 - f) * fondo[0], f * copa[1] + (1 - f) * fondo[1])
        def _pasada(fecha):
            N, R = _mez(fc)
            Np, Rp = _mez(min(0.85, fc * 2.1))       # el mejor decil: pixeles con arbol
            Nc, Rc = _mez(fc * 0.15)                 # el peor decil: la CALLE
            evi = 2.5 * ((N - R) / (N + 6 * R - 7.5 * 0.05 + 1))
            p = {"fecha": fecha, "ndvi": _ndvi(N, R), "msavi": _msavi(N, R),
                 "ndmi": 0.05, "lai": round(max(0.0, 3.618 * evi - 0.118), 2),
                 "evi": round(evi, 3), "savi": round(1.5 * (N - R) / (N + R + 0.5), 3),
                 "gndvi": round(_ndvi(N, R) * 0.9, 3),
                 "n_pixeles": 800, "cobertura_valida": 0.96}
            if con_p10:
                p.update({"ndvi_p10": _ndvi(Nc, Rc), "ndvi_p50": _ndvi(N, R),
                          "ndvi_p90": _ndvi(Np, Rp), "msavi_p10": _msavi(Nc, Rc),
                          "msavi_p50": _msavi(N, R), "msavi_p90": _msavi(Np, Rp)})
            return p
        serie = [_pasada("2026-07-01"), _pasada("2026-07-15")]
        d = evaluar_parcela("LENOSO", "", serie,
                            spec={"especie": "OLIVO", "marco_calle": marco_calle,
                                  "marco_pie": marco_pie, "regimen": "SECANO"})
        return d["estado"], serie[-1]
    COPA_SANA, COPA_FLOJA = (0.32, 0.06), (0.26, 0.13)
    for etiq, mc, mp, fc in (("tradicional 12x12", 12.0, 12.0, 0.20),
                             ("tradicional 10x10", 10.0, 10.0, 0.20),
                             ("intensivo 6x4", 6.0, 4.0, 0.30),
                             ("seto 4x1.5", 4.0, 1.5, 0.40)):
        check(f"lenoso {etiq}: con la copa SANA no salta el aviso",
              lambda a=mc, b=mp, f=fc: _grove(a, b, f, COPA_SANA),
              lambda r: r[0] == "OK")
        check(f"lenoso {etiq}: con la copa FLOJA sigue saltando",
              lambda a=mc, b=mp, f=fc: _grove(a, b, f, COPA_FLOJA),
              lambda r: r[0] == "Revisar")
    check("lenoso tradicional: un suelo mas humedo tampoco lo convierte en aviso",
          lambda: _grove(12.0, 12.0, 0.20, COPA_SANA, fondo=(0.20, 0.15)),
          lambda r: r[0] == "OK")
    check("lenoso tradicional: con cubierta verde en la calle tampoco",
          lambda: _grove(12.0, 12.0, 0.20, COPA_SANA, fondo=(0.35, 0.10)),
          lambda r: r[0] == "OK")
    # y que la parcela sintetica es la que se dice: MSAVI de 0.11 con copa perfecta
    check("lenoso tradicional: un olivar sano mide 0.11 de MSAVI medio, no 0.43",
          lambda: _grove(12.0, 12.0, 0.20, COPA_SANA)[1],
          lambda p: 0.10 < p["msavi"] < 0.13 and 0.15 < p["ndvi"] < 0.19)

    # --- EL CASO DURO: COPA FLOJA DEBAJO DE UNA CUBIERTA VERDE ---
    # Con hierba entre lineas el MSAVI medio sube por el fondo y una copa floja se
    # esconde. Se sostiene porque el suelo de la mezcla se MIDE en la propia finca
    # (el p10 es la calle) en vez de suponerse: al subir el fondo sube el umbral
    # con el, y lo que acaba comparandose es la copa contra el umbral de copa.
    HIERBA = (0.35, 0.10)
    check("lenoso: bajo cubierta verde, una copa SANA no se convierte en aviso",
          lambda: _grove(12.0, 12.0, 0.20, COPA_SANA, fondo=HIERBA),
          lambda r: r[0] == "OK")
    check("lenoso: bajo cubierta verde, una copa FLOJA NO se esconde",
          lambda: _grove(12.0, 12.0, 0.20, COPA_FLOJA, fondo=HIERBA),
          lambda r: r[0] == "Revisar")
    check("lenoso: y lo mismo en seto, donde la cubierta pesa menos",
          lambda: (_grove(4.0, 1.5, 0.40, COPA_SANA, fondo=HIERBA)[0],
                   _grove(4.0, 1.5, 0.40, COPA_FLOJA, fondo=HIERBA)[0]),
          lambda r: r == ("OK", "Revisar"))
    check("lenoso: con cubierta verde el MSAVI medio de la floja SUPERA al de la "
          "sana con suelo desnudo (por eso hacia falta medir el fondo)",
          lambda: (_grove(12.0, 12.0, 0.20, COPA_FLOJA, fondo=HIERBA)[1]["msavi"],
                   _grove(12.0, 12.0, 0.20, COPA_SANA)[1]["msavi"]),
          lambda r: r[0] > r[1])
    check("lenoso: sin percentiles se cae a la constante y sigue sin dar falso aviso",
          lambda: _grove(12.0, 12.0, 0.20, COPA_SANA, con_p10=False),
          lambda r: r[0] == "OK")

    # --- el suelo de la mezcla: medido cuando se puede, supuesto cuando no ---
    check("suelo: sin percentiles se usa la constante y se dice que no es medido",
          lambda: FEN.suelo_de_la_parcela(None, FEN.MSAVI_SUELO),
          lambda r: r == (FEN.MSAVI_SUELO, False))
    check("suelo: con p10 se usa el de la parcela",
          lambda: FEN.suelo_de_la_parcela(0.062, FEN.MSAVI_SUELO),
          lambda r: r == (0.062, True))
    check("suelo: una calle VERDE es fondo valido y sube el umbral por encima del de copa",
          lambda: (FEN.suelo_de_la_parcela(0.37, FEN.MSAVI_SUELO, 0.30)[0],
                   FEN.umbral_en_escala_parcela(0.30, 0.20, 0.37)),
          lambda r: r[0] == 0.37 and r[1] > 0.30)
    check("suelo: un p10 negativo (agua o sombra) no es suelo y se descarta",
          lambda: FEN.suelo_de_la_parcela(-0.2, FEN.MSAVI_SUELO),
          lambda r: r == (FEN.MSAVI_SUELO, False))
    check("suelo: medirlo reduce el margen de error a la mitad",
          lambda: (FEN.margen_mezcla(0.2, medido=False), FEN.margen_mezcla(0.2, medido=True)),
          lambda r: r[0] > r[1] > 0)

    # --- cubierta dominando: el liston tambien cambia de indice ---
    # Se juzgaba el MSAVI contra el rango de NDVI de la fase. Son magnitudes
    # distintas: un MSAVI de 0.11 frente a un "0.16-0.23" de NDVI daba "Revisar"
    # por construccion.
    def _rango_en_msavi():
        f = FEN.fase_lenoso("OLIVO", "2026-07-15", 12.0, 12.0, "SECANO",
                            p10_ndvi=0.45, p10_msavi=0.37)
        return f["msavi_min_parcela"], f["msavi_max_parcela"], f["lo"]
    check("cubierta: hay un rango de MSAVI en escala de parcela para poder juzgar",
          _rango_en_msavi,
          lambda r: r[0] is not None and r[1] is not None and r[1] > r[0])
    check("cubierta: y ese rango NO es el de NDVI (son magnitudes distintas)",
          _rango_en_msavi, lambda r: abs(r[0] - r[2]) > 0.01)

    # --- separacion copa / cubierta
    def _sep(marco, con_percentiles, mes=3):
        reg = {"fecha": f"2026-{mes:02d}-20", "ndvi": 0.52, "msavi": 0.36, "lai": 1.3,
               "evi": 0.28, "gndvi": 0.50, "savi": 0.44, "ndmi": 0.22}
        if con_percentiles:
            # los nombres que USA LA BASE (gee_cliente los guarda asi). Antes esta
            # prueba ponia p10/p50/p90, que es como los deja `estadisticas_pasada`
            # para la tabla, y con eso el camino del p90 salia verde en las
            # pruebas mientras estaba muerto sobre datos reales.
            reg.update({"ndvi_p10": 0.42, "ndvi_p50": 0.52, "ndvi_p90": 0.66})
        serie = [dict(reg, fecha=f"2026-{mes:02d}-01", ndvi=0.42, msavi=0.30), reg]
        fase = FEN.fase_lenoso("OLIVO", reg["fecha"], marco, marco, "SECANO")
        return separacion_copa_cubierta(serie, fase, reg)
    check("copa/cubierta: con marco ancho y percentiles, confianza alta",
          lambda: _sep(14.0, True)["confianza"], lambda r: r == "alta")
    check("copa/cubierta: con marco estrecho baja la confianza (el pixel no separa)",
          lambda: _sep(6.0, True)["confianza"], lambda r: r == "media")
    check("copa/cubierta: sin percentiles, confianza baja",
          lambda: _sep(14.0, False)["confianza"], lambda r: r == "baja")
    check("copa/cubierta: el p90 sirve de proxy de la copa",
          lambda: _sep(14.0, True), lambda s: s["copa_ndvi_p90"] == 0.66 and s["copa_msavi"] is not None)
    check("copa/cubierta: la calle verde en primavera cuenta como cubierta",
          lambda: _sep(14.0, True)["evidencias_cubierta"],
          lambda r: any("calle esta verde" in e for e in r))
    check("copa/cubierta: un solo veredicto, no dos vocabularios",
          lambda: _sep(14.0, True)["veredicto"],
          lambda r: r in ("cubierta vegetal dominando la senal", "posible aporte de cubierta",
                          "senal atribuible a la copa",
                          "el arbol esta sin hoja: todo el verde es cubierta o suelo"))
    # antes habia DOS heuristicas: la cabecera podia decir "cubierta probable"
    # mientras el juicio iba por la copa. Ahora el veredicto que se ensena es el
    # mismo que decide con que indice se juzga.
    def _coherencia():
        malos = []
        for mes in range(1, 13):
            for ndvi, msavi in ((0.25, 0.20), (0.45, 0.28), (0.60, 0.50), (0.70, 0.44)):
                reg = {"fecha": f"2026-{mes:02d}-20", "ndvi": ndvi, "msavi": msavi,
                       "lai": 1.5, "ndmi": 0.18, "evi": ndvi * 0.6, "savi": ndvi * 0.85,
                       "gndvi": ndvi * 0.95, "ndvi_p10": ndvi - 0.08,
                       "ndvi_p50": ndvi, "ndvi_p90": ndvi + 0.08}
                serie = [dict(reg, fecha=f"2026-{mes:02d}-05"), reg]
                d = evaluar_parcela("LENOSO", "INTENSIVO", serie,
                                    spec={"especie": "OLIVO", "marco_calle": 14.0,
                                          "marco_pie": 12.0, "regimen": "REGADIO"})
                cub = (d.get("cubierta") or {}).get("hipotesis_preliminar", "")
                sep = ((d.get("copa") or {}).get("separacion") or {})
                if cub and sep and cub != sep.get("veredicto"):
                    malos.append((mes, ndvi, cub, sep.get("veredicto")))
        return malos
    check("copa/cubierta: la cabecera y el juicio nunca se contradicen",
          _coherencia, lambda r: r == [])
    # REGRESION. Esta es la prueba que faltaba: la pasada NO se fabrica, se pide a
    # la base. El camino del p90 estuvo muerto porque la funcion buscaba `p90` y la
    # base guarda `ndvi_p90`; con registros fabricados a medida no se veia.
    def _sep_desde_la_base():
        import almacen as _DB
        import gee_cliente as _G
        _DB.conectar(os.path.join(tempfile.mkdtemp(), "sep.db"))
        _DB.guardar_ficha("Olivar_p90", {"propietario": "x", "coordenadas": [[0, 0], [0, 1], [1, 1]]})
        # las MISMAS claves que escribe la sincronizacion (props de gee_cliente)
        pasada = {"fecha": "2026-07-15", "cobertura_valida": 0.95,
                  "ndvi": 0.161, "msavi": 0.109, "ndmi": 0.05, "lai": 0.6,
                  "evi": 0.20, "savi": 0.16, "gndvi": 0.20, "ndvi_std": 0.08,
                  "ndvi_p10": 0.09, "ndvi_p25": 0.12, "ndvi_p50": 0.15,
                  "ndvi_p75": 0.21, "ndvi_p90": 0.276, "n_pixeles": 800}
        _DB.anadir_pasadas("Olivar_p90", "2025-2026", [pasada])
        serie = _DB.pasadas("Olivar_p90", "2025-2026")
        fase = FEN.fase_lenoso("OLIVO", "2026-07-15", 14.0, 12.0, "SECANO")
        return separacion_copa_cubierta(serie, fase, serie[-1]), _G.INDICES_ORDEN
    check("copa/cubierta: los percentiles se leen de la pasada REAL, no de un dict a medida",
          lambda: _sep_desde_la_base()[0],
          lambda s: s["copa_ndvi_p90"] == 0.276 and s["confianza"] == "alta")
    check("copa/cubierta: y por tanto la copa NO se juzga con la media de la parcela",
          lambda: _sep_desde_la_base()[0],
          lambda s: s["copa_msavi"] is not None and s["copa_msavi"] > 0.109)
    # --- el p90 del PROPIO MSAVI, cuando la pasada lo trae ---
    def _sep_msavi(con_p90_msavi):
        reg = {"fecha": "2026-07-20", "ndvi": 0.52, "msavi": 0.36, "lai": 1.3,
               "evi": 0.28, "gndvi": 0.50, "savi": 0.44, "ndmi": 0.22,
               "ndvi_p10": 0.42, "ndvi_p50": 0.52, "ndvi_p90": 0.66}
        if con_p90_msavi:
            reg["msavi_p90"] = 0.58
        serie = [dict(reg, fecha="2026-07-05", ndvi=0.42, msavi=0.30), reg]
        fase = FEN.fase_lenoso("OLIVO", reg["fecha"], 14.0, 14.0, "SECANO")
        return separacion_copa_cubierta(serie, fase, reg)
    check("copa: si la pasada trae msavi_p90, es lo que se usa (sin trasladar nada)",
          lambda: _sep_msavi(True),
          lambda s: s["copa_msavi"] == 0.58 and s["copa_origen"] == "p90 de MSAVI")
    check("copa: sin msavi_p90 se traslada el p90 de NDVI, y se dice que es eso",
          lambda: _sep_msavi(False),
          lambda s: s["copa_origen"] == "p90 de NDVI trasladado" and s["copa_msavi"] is not None)
    check("copa: la traslacion INFRAVALORA la copa frente al p90 real de MSAVI",
          lambda: (_sep_msavi(False)["copa_msavi"], _sep_msavi(True)["copa_msavi"]),
          lambda r: r[0] < r[1])
    check("copa: sin ningun percentil se cae a la media, y se dice",
          lambda: separacion_copa_cubierta(
              [{"fecha": "2026-07-20", "ndvi": 0.52, "msavi": 0.36, "lai": 1.3, "evi": 0.28}] * 2,
              FEN.fase_lenoso("OLIVO", "2026-07-20", 14.0, 14.0, "SECANO")),
          lambda s: s["copa_msavi"] == 0.36 and s["copa_origen"] == "media de la parcela")
    check("copa/cubierta: sin hoja lo dice sin rodeos",
          lambda: separacion_copa_cubierta(
              [{"fecha": "2026-01-20", "ndvi": 0.30, "msavi": 0.20, "lai": 0.5, "evi": 0.15}],
              FEN.fase_lenoso("ALMENDRO", "2026-01-20", 6.0, 5.0, "SECANO"))["veredicto"],
          lambda r: "sin hoja" in r)

    # --- calibracion: los sistemas no se contaminan entre si
    try:
        import calibracion_umbrales as CAL
    except Exception:
        return
    import almacen as DB
    DB.conectar(os.path.join(tempfile.mkdtemp(), "len.db"))
    for n in ("Reg", "Sec"):
        DB.guardar_ficha(n, {"propietario": "x", "coordenadas": [[0, 0]], "superficie_ha": 8,
                             "provincia": "23", "municipio": "23/050"})
    spec = {"especie": "OLIVO", "marco_calle": 6.0, "marco_pie": 5.0}
    serie = [{"fecha": "2026-06-20", "ndvi": 0.52, "msavi": 0.34, "ndmi": 0.13, "lai": 2.0},
             {"fecha": "2026-07-10", "ndvi": 0.50, "msavi": 0.33, "ndmi": 0.12, "lai": 1.9}]
    d = evaluar_parcela("LENOSO", "INTENSIVO", serie, spec=dict(spec, regimen="REGADIO"),
                        parcela="Reg")
    check("lenoso: la clave de calibracion separa regimen y densidad",
          lambda: CAL.sistema_de(d["umbrales"]), lambda r: r == ("REGADIO", "intensivo"))
    # MIN_OBSERVACIONES validaciones, cada una de una PASADA distinta: antes
    # bastaban dos, y con dos se movia el umbral de un municipio entero
    for k, (f, v) in enumerate((("2026-07-10", 0.33), ("2026-06-20", 0.34),
                                ("2026-06-30", 0.33), ("2026-07-20", 0.34),
                                ("2026-07-30", 0.33), ("2026-08-05", 0.34))):
        if k >= CAL.MIN_OBSERVACIONES:
            break
        CAL.registrar("Reg", "2025-2026", f, "OLIVO", d["fase"],
                      {"MSAVI": {"valor": v, "sistema": "bajo"}}, {"MSAVI": "normal"},
                      "municipio", umbrales=d["umbrales"])
    d2 = evaluar_parcela("LENOSO", "INTENSIVO", serie, spec=dict(spec, regimen="REGADIO"),
                         parcela="Reg")
    check("lenoso: validar el MSAVI mueve el umbral de copa",
          lambda: d2["umbrales"]["msavi_min"] < d["umbrales"]["msavi_min"], lambda r: r is True)
    d3 = evaluar_parcela("LENOSO", "INTENSIVO", serie, spec=dict(spec, regimen="SECANO"),
                         parcela="Sec")
    check("lenoso: el SECANO del mismo municipio NO hereda lo del regadio",
          lambda: d3["umbrales"]["msavi_min"],
          lambda r: r == FEN.fase_lenoso("OLIVO", "2026-07-10", 6.0, 5.0, "SECANO")["msavi_min"])
    check("lenoso: la bibliografia sigue intacta",
          lambda: FEN.UMBRALES_LENOSO["OLIVO"]["endurecimiento de hueso"]["REGADIO"]["msavi_min"],
          lambda r: r == 0.38)


# =====================================================================
# 4d. REJILLA DE PIXELES (NDVI pixel a pixel y su georreferenciacion)
# =====================================================================
def pruebas_rejilla():
    import json as _json
    import math as _math
    import random as _random
    import statistics as _stat
    import rejilla as R
    import almacen as DB

    GEO = {"crs": "EPSG:32630", "escala": 10.0, "i0": 399123, "j0": 455678,
           "filas": 4, "columnas": 5}
    vals = [0.60, 0.62, 0.58, 0.61, 0.59, 0.63, 0.65, 0.61, 0.60, 0.62,
            0.58, 0.30, 0.29, 0.57, 0.59, 0.61, 0.60, 0.62, 0.61, 0.63]
    validos = [True] * 20
    validos[3] = False                       # un pixel tapado por nube

    def _ida_vuelta():
        d = R.decodificar(R.codificar(vals, validos, GEO))
        return all(abs(a - b) <= 1.0 / R.ESCALA_NDVI
                   for a, b, ok in zip(d["valores"], vals, validos) if ok)
    check("rejilla: el NDVI vuelve con la precision declarada", _ida_vuelta,
          lambda r: r is True)
    check("rejilla: un pixel con nube vuelve como None, NO como NDVI bajo",
          lambda: R.decodificar(R.codificar(vals, validos, GEO))["valores"][3],
          lambda r: r is None)
    check("rejilla: la mascara de validos se conserva",
          lambda: R.decodificar(R.codificar(vals, validos, GEO))["validos"],
          lambda r: r == validos)
    check("rejilla: un NDVI de 0.0 legitimo NO se confunde con invalido",
          lambda: R.decodificar(R.codificar([0.0] * 20, [True] * 20, GEO))["valores"][0],
          lambda r: r == 0.0)
    check("rejilla: la georreferenciacion se guarda entera",
          lambda: R.decodificar(R.codificar(vals, validos, GEO))["geo"],
          lambda r: r == GEO)
    check("rejilla: si el tamano no cuadra con filas x columnas, se rechaza",
          lambda: _lanza(R.codificar, ValueError, vals[:5], validos[:5], GEO),
          lambda r: r is True)
    check("rejilla: un formato desconocido no se interpreta a lo loco",
          lambda: R.decodificar(dict(R.codificar(vals, validos, GEO), v=99)),
          lambda r: r is None)

    # --- comparabilidad: el nucleo del asunto
    otra_zona = dict(GEO, crs="EPSG:32629")
    desplazada = dict(GEO, i0=GEO["i0"] + 1)
    check("rejilla: misma reticula -> comparables",
          lambda: R.misma_geometria(GEO, dict(GEO)), lambda r: r is True)
    check("rejilla: otro huso UTM -> NO comparables",
          lambda: R.misma_geometria(GEO, otra_zona), lambda r: r is False)
    check("rejilla: desplazada un solo pixel -> NO comparables",
          lambda: R.misma_geometria(GEO, desplazada), lambda r: r is False)

    def _filtra():
        rs = [{"geo": GEO, "fecha": "2026-01-10"}, {"geo": dict(GEO), "fecha": "2026-02-10"},
              {"geo": otra_zona, "fecha": "2026-03-10"}, {"geo": dict(GEO), "fecha": "2026-04-10"}]
        buenas, fuera = R.comparables(rs)
        return [r["fecha"] for r in buenas], [r["fecha"] for r in fuera]
    check("rejilla: se descarta la fecha que no comparte reticula, no todo el historico",
          _filtra,
          lambda r: r == (["2026-01-10", "2026-02-10", "2026-04-10"], ["2026-03-10"]))
    check("rejilla: sin ninguna geometria valida no se compara nada",
          lambda: R.comparables([{"geo": {}}, {"geo": None}]), lambda r: r[0] == [])

    # --- TAMANO: el requisito era 1.5-2 KB por pasada en 5-10 ha
    def _tam(ha, relacion, rugosidad=0.05, semilla=3):
        _random.seed(semilla)
        area = ha * 10000.0
        ancho, alto = _math.sqrt(area * relacion), _math.sqrt(area / relacion)
        cols, filas = int(_math.ceil(ancho / 10)) + 1, int(_math.ceil(alto / 10)) + 1
        g = [[0.0] * cols for _ in range(filas)]
        for i in range(filas):
            for j in range(cols):
                vec = [x for x in (g[i - 1][j] if i else None, g[i][j - 1] if j else None) if x]
                g[i][j] = max(0.0, min(0.95, (_stat.fmean(vec) if vec else 0.62)
                                       + _random.gauss(0, rugosidad)))
        planos = [x for f in g for x in f]
        mask = [_random.random() > 0.05 for _ in planos]
        d = R.codificar(planos, mask, dict(GEO, filas=filas, columnas=cols))
        return len(_json.dumps(d, ensure_ascii=False).encode("utf-8"))

    for ha in (5, 10):
        for rel, etiq in ((1.0, "cuadrada"), (5.0, "alargada 5:1"), (10.0, "alargada 10:1")):
            check(f"rejilla: {ha} ha {etiq} cabe en 2 KB",
                  lambda ha=ha, rel=rel: _tam(ha, rel), lambda t: t <= 2048)
    check("rejilla: un campo muy heterogeneo (que comprime mal) tambien cabe",
          lambda: _tam(10, 1.0, rugosidad=0.20), lambda t: t <= 2048)
    check("rejilla: la cota superior teorica avisa antes de descargar",
          lambda: R.tamano_estimado(33, 33), lambda t: 1500 <= t <= 2500)

    # --- persistencia
    d_e = tempfile.mkdtemp()
    DB.conectar(os.path.join(d_e, "rej.db"))
    DB.guardar_ficha("P", {"propietario": "x", "coordenadas": [[0, 0]], "superficie_ha": 8})
    DB.guardar_rejilla("P", "2025-2026", "2026-04-10", R.codificar(vals, validos, GEO))
    DB.guardar_rejilla("P", "2024-2025", "2025-04-10", R.codificar(vals, validos, GEO))
    check("almacen: las rejillas se leen ordenadas y de todas las campanas",
          lambda: [(r["campana"], r["fecha"]) for r in DB.rejillas("P")],
          lambda r: r == [("2024-2025", "2025-04-10"), ("2025-2026", "2026-04-10")])
    check("almacen: se puede pedir solo una campana",
          lambda: len(DB.rejillas("P", "2025-2026")), lambda r: r == 1)
    check("almacen: fechas_con_rejilla evita volver a descargar lo que ya esta",
          lambda: DB.fechas_con_rejilla("P", "2025-2026"), lambda r: r == {"2026-04-10"})
    check("almacen: guardar la misma fecha la sustituye, no la duplica",
          lambda: (DB.guardar_rejilla("P", "2025-2026", "2026-04-10",
                                      R.codificar(vals, validos, GEO)),
                   len(DB.rejillas("P", "2025-2026")))[1], lambda r: r == 1)
    check("almacen: el espacio ocupado se puede consultar",
          lambda: DB.tamano_rejillas("P"), lambda r: r[0] == 2 and r[1] > 0)
    check("almacen: una rejilla ilegible se salta sin tumbar la lectura",
          lambda: (DB._c().execute("INSERT OR REPLACE INTO pixeles VALUES(?,?,?,?)",
                                   ("P", "2025-2026", "2026-05-01", "{roto")),
                   DB._c().commit(), len(DB.rejillas("P")))[2], lambda r: r == 2)
    check("almacen: las rejillas se borran con la parcela",
          lambda: (DB.eliminar_parcela("P"), DB.tamano_rejillas("P"))[1],
          lambda r: r == (0, 0))


# =====================================================================
# 5. CREDENCIALES (degradacion sin librerias externas)
# =====================================================================
def pruebas_credenciales():
    import credenciales as C
    check("credenciales: openai sin clave -> aviso", lambda: C.probar_openai(""), lambda r: r[0] == "aviso")
    check("credenciales: gee devuelve tupla valida", lambda: C.probar_gee(),
          lambda r: isinstance(r, tuple) and r[0] in ("ok", "aviso", "fallo"))
    check("credenciales: estado no revienta", lambda: C.estado_credenciales({}),
          lambda r: "gee" in r and "openai" in r)
    # roundtrip atomico + aplicar_entorno con fichero temporal
    d = tempfile.mkdtemp(); C.ARCHIVO_CRED = os.path.join(d, "cfg.json")
    check("credenciales: cargar inexistente -> {}", lambda: C.cargar(), lambda r: r == {})
    C.guardar({"openai_api_key": "sk-demo", "gee_project": "p1"})
    check("credenciales: roundtrip", lambda: C.cargar().get("gee_project"), lambda r: r == "p1")
    os.environ.pop("OPENAI_API_KEY", None)
    C.aplicar_entorno({"openai_api_key": " sk-x "})
    check("credenciales: aplicar_entorno vuelca la clave",
          lambda: os.environ.get("OPENAI_API_KEY"), lambda r: r == "sk-x")
    # seguridad de la clave (ofuscacion, recordar y prioridad del entorno)
    C.guardar({"openai_api_key": "sk-secreta-999", "gee_project": "pz"}, recordar_openai=True)
    check("credenciales: clave NO en texto plano",
          lambda: "sk-secreta-999" in open(C.ARCHIVO_CRED, encoding="utf-8").read(), lambda r: r is False)
    check("credenciales: clave ofuscada + roundtrip",
          lambda: C.cargar().get("openai_api_key"), lambda r: r == "sk-secreta-999")
    C.guardar({"openai_api_key": "sk-no-guardar", "gee_project": "pz"}, recordar_openai=False)
    check("credenciales: recordar=False no escribe la clave",
          lambda: "sk-no-guardar" in open(C.ARCHIVO_CRED, encoding="utf-8").read()
                  or "openai_api_key_b64" in open(C.ARCHIVO_CRED, encoding="utf-8").read(), lambda r: r is False)
    os.environ["OPENAI_API_KEY"] = "sk-entorno"
    C.aplicar_entorno({"openai_api_key": "sk-guardada"})
    check("credenciales: la variable de entorno tiene prioridad",
          lambda: os.environ.get("OPENAI_API_KEY"), lambda r: r == "sk-entorno")
    os.environ.pop("OPENAI_API_KEY", None)


# =====================================================================
# 6. PERSISTENCIA ROBUSTA (extraida del propio panel, sin importar tkinter)
# =====================================================================
def pruebas_persistencia():
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel_gestion_parcelas.py")
    if not os.path.exists(ruta):
        _FALLA.append(("persistencia", "no se encuentra panel_gestion_parcelas.py"))
        return
    # la persistencia atomica vive en sincronizacion.py: se importa, no se extrae
    from sincronizacion import _load, _save, _actualizar

    d = tempfile.mkdtemp(); p = os.path.join(d, "hist.json")
    check("persistencia: cargar inexistente -> {}", lambda: _load(p), lambda r: r == {})
    open(p, "w").write("{ json roto ")
    check("persistencia: cargar corrupto -> {}", lambda: _load(p), lambda r: r == {})
    _save(p, {"a": [1, 2, 3], "n": "áéí"})
    check("persistencia: roundtrip", lambda: _load(p), lambda r: r == {"a": [1, 2, 3], "n": "áéí"})
    check("persistencia: sin temporales sueltos",
          lambda: [x for x in os.listdir(d) if x.startswith(".tmp_")], lambda r: r == [])

    # concurrencia: 20 hilos x 50 incrementos, sin perdidas
    _save(p, {"n": 0})
    def worker():
        for _ in range(50):
            _actualizar(p, lambda dct: dct.__setitem__("n", dct["n"] + 1))
    ts = [threading.Thread(target=worker) for _ in range(20)]
    [t.start() for t in ts]; [t.join() for t in ts]
    check("persistencia: 1000 incrementos concurrentes sin perdidas",
          lambda: _load(p)["n"], lambda r: r == 1000)
    check("persistencia: fichero final es JSON valido", lambda: json.load(open(p)), lambda r: True)

    # ritmo del arranque: funcion pura de sincronizacion.py
    from datetime import datetime, timedelta
    from sincronizacion import toca_sincronizar as toca

    UN_DIA = 24 * 3600 * 1000
    ahora = datetime(2026, 7, 21, 12, 0, 0)
    check("arranque: sin marca -> toca sincronizar", lambda: toca(None, UN_DIA, ahora), lambda r: r is True)
    check("arranque: marca invalida -> toca", lambda: toca("basura", UN_DIA, ahora), lambda r: r is True)
    check("arranque: hace 2 dias -> toca (paso el intervalo)",
          lambda: toca((ahora - timedelta(days=2)).isoformat(), UN_DIA, ahora), lambda r: r is True)
    check("arranque: hace 3 horas -> NO toca (aun no)",
          lambda: toca((ahora - timedelta(hours=3)).isoformat(), UN_DIA, ahora), lambda r: r is False)
    check("arranque: intervalo 2 dias, hace 1 dia -> NO toca",
          lambda: toca((ahora - timedelta(days=1)).isoformat(), 2 * UN_DIA, ahora), lambda r: r is False)

    # nombre_seguro vive en mapas_cache.py
    from mapas_cache import nombre_seguro as seguro
    check("nombre_seguro: quita separadores de ruta",
          lambda: seguro("../a/b:c*?"),
          lambda r: "/" not in r and "\\" not in r and ":" not in r and ".." not in r)
    check("nombre_seguro: espacios a _ y conserva acentos",
          lambda: seguro("Olivar del Ñú"), lambda r: r == "Olivar_del_Ñú")
    check("nombre_seguro: vacio -> 'parcela'", lambda: seguro("   "), lambda r: r == "parcela")


# =====================================================================
# 7. ALMACEN (SQLite): roundtrip, dedup, cascada y migracion desde JSON
# =====================================================================
def pruebas_almacen():
    import json as _json
    import almacen as DB
    d = tempfile.mkdtemp()
    DB.conectar(os.path.join(d, "a.db"))
    ficha = {"propietario": "Coop", "coordenadas": [[-4, 37], [-4, 38], [-3, 38]],
             "superficie_ha": 12.3, "anio_inicio_monitoreo": "2025-2026",
             "cultivos_por_campana": {"2025-2026": {"tipo": "LENOSO", "especie": "OLIVO"}}}
    DB.guardar_ficha("Olivar", ficha)
    check("almacen: roundtrip ficha + cultivo",
          lambda: DB.ficha("Olivar")["cultivos_por_campana"]["2025-2026"]["especie"], lambda r: r == "OLIVO")
    DB.anadir_pasadas("Olivar", "2025-2026",
                      [{"fecha": "2026-01-10", "ndvi": 0.5, "ndvi_std": 0.05, "interpretacion": "viejo"},
                       {"fecha": "2026-02-10", "ndvi": 0.6}])
    check("almacen: ultima_fecha (MAX indexado)", lambda: DB.ultima_fecha("Olivar", "2025-2026"),
          lambda r: r == "2026-02-10")
    DB.anadir_pasadas("Olivar", "2025-2026", [{"fecha": "2026-01-10", "ndvi": 0.99}])  # ya existe
    check("almacen: anadir_pasadas no sobrescribe (conserva interpretacion)",
          lambda: DB.pasadas("Olivar", "2025-2026")[0], lambda r: r["ndvi"] == 0.5 and r["interpretacion"] == "viejo")
    DB.set_interpretacion("Olivar", "2025-2026", "2026-02-10", "nuevo")
    check("almacen: set_interpretacion", lambda: DB.pasadas("Olivar", "2025-2026")[1].get("interpretacion"),
          lambda r: r == "nuevo")
    check("almacen: pasadas_de_campana", lambda: len(DB.pasadas_de_campana("2025-2026")["Olivar"]), lambda r: r == 2)
    check("almacen: campanas_con_datos solo las que tienen pasadas",
          lambda: DB.campanas_con_datos(), lambda r: r == {"2025-2026"})
    # validaciones del diagnostico (aprendizaje)
    DB.guardar_validacion("Olivar", "2025-2026", "2026-02-10", "floracion", "LENOSO/INTENSIVO",
                          "Revisar", "incorrecto", estado_real="OK", nota="estaba sano")
    check("almacen: validacion_de roundtrip",
          lambda: DB.validacion_de("Olivar", "2025-2026", "2026-02-10"),
          lambda r: r and r["veredicto"] == "incorrecto" and r["estado_real"] == "OK")
    DB.guardar_validacion("Olivar", "2025-2026", "2026-02-10", "floracion", "LENOSO/INTENSIVO",
                          "Revisar", "correcto")     # upsert sobre la misma pasada
    check("almacen: validacion upsert (una por pasada)",
          lambda: (DB.validacion_de("Olivar", "2025-2026", "2026-02-10")["veredicto"],
                   len(DB.validaciones_recientes(50))),
          lambda r: r == ("correcto", 1))
    check("almacen: validaciones_recientes prioriza el mismo cultivo",
          lambda: DB.validaciones_recientes(5, cultivo="LENOSO/INTENSIVO"),
          lambda r: len(r) == 1 and r[0]["cultivo"] == "LENOSO/INTENSIVO")
    # --- version del esquema (PRAGMA user_version) ---
    import sqlite3 as _sq
    def _uv(p):
        c = _sq.connect(p)
        try:
            return c.execute("PRAGMA user_version").fetchone()[0]
        finally:
            c.close()
    d_e = tempfile.mkdtemp()
    p_nueva = os.path.join(d_e, "nueva.db")
    DB.conectar(p_nueva); DB.cerrar()
    check("esquema: una base nueva queda marcada con la version actual",
          lambda: _uv(p_nueva), lambda v: v == DB.ESQUEMA_VERSION)
    # base "antigua": las de hoy tienen user_version = 0
    p_vieja = os.path.join(d_e, "vieja.db")
    _c0 = _sq.connect(p_vieja); _c0.execute("PRAGMA user_version=0"); _c0.commit(); _c0.close()
    DB.conectar(p_vieja); DB.cerrar()
    check("esquema: una base antigua se pone al dia al abrirla",
          lambda: _uv(p_vieja), lambda v: v == DB.ESQUEMA_VERSION)
    # el mecanismo aplica de verdad una migracion futura, y solo una vez
    def _migracion_futura():
        orig_v, orig_m = DB.ESQUEMA_VERSION, DB._MIGRACIONES
        try:
            DB.ESQUEMA_VERSION = orig_v + 1
            DB._MIGRACIONES = {orig_v + 1:
                               lambda conn: conn.execute("ALTER TABLE parcelas ADD COLUMN riego TEXT")}
            DB.conectar(p_vieja); DB.cerrar()
            cols = [r[1] for r in _sq.connect(p_vieja).execute("PRAGMA table_info(parcelas)")]
            v1 = _uv(p_vieja)
            DB.conectar(p_vieja); DB.cerrar()          # reabrir NO debe reaplicarla
            return ("riego" in cols, v1, _uv(p_vieja))
        finally:
            DB.ESQUEMA_VERSION, DB._MIGRACIONES = orig_v, orig_m
    # la version de destino se calcula, no se escribe: asi la prueba sigue valiendo
    # cuando ESQUEMA_VERSION suba (antes estaba clavada a 2 y fallaba al subirla)
    check("esquema: aplica una migracion pendiente y no la repite",
          _migracion_futura,
          lambda r: r[0] is True and r[1] == r[2] == DB.ESQUEMA_VERSION + 1)
    # Regresion: un indice sobre columnas que anade una migracion NO puede estar en
    # _crear_tablas. En una base que ya existe, CREATE TABLE IF NOT EXISTS no anade
    # las columnas y el CREATE INDEX revienta al abrirla ("no such column").
    def _base_de_cada_version():
        fallos = []
        for v in range(0, DB.ESQUEMA_VERSION):
            p = os.path.join(d_e, f"v{v}.db")
            c0 = _sq.connect(p)
            c0.executescript("""
                CREATE TABLE IF NOT EXISTS parcelas(nombre TEXT PRIMARY KEY, propietario TEXT,
                    coordenadas TEXT, superficie_ha REAL, anio_inicio TEXT);
                CREATE TABLE IF NOT EXISTS validaciones_indice(id TEXT PRIMARY KEY,
                    nombre TEXT, campana TEXT, fecha TEXT, indice TEXT, valor REAL,
                    especie TEXT, fase TEXT, dijo_sistema TEXT, dijo_usuario TEXT,
                    ambito TEXT, clave_ambito TEXT, ts TEXT);""")
            c0.execute(f"PRAGMA user_version={v}")
            c0.commit(); c0.close()
            try:
                DB.conectar(p); DB.cerrar()
            except Exception as e:
                fallos.append(f"v{v}: {type(e).__name__}: {e}")
        return fallos
    check("esquema: una base de CUALQUIER version anterior se abre sin reventar",
          _base_de_cada_version, lambda r: r == [])

    # una base de una version MAS NUEVA no se toca
    p_futura = os.path.join(d_e, "futura.db")
    _c9 = _sq.connect(p_futura); _c9.execute("PRAGMA user_version=99"); _c9.commit(); _c9.close()
    DB.conectar(p_futura); DB.cerrar()
    check("esquema: una base de un programa mas nuevo se abre sin tocarla",
          lambda: _uv(p_futura), lambda v: v == 99)
    DB.conectar(os.path.join(d, "t.db"))       # se restaura la base de las pruebas

    DB.eliminar_parcela("Olivar")
    check("almacen: borrado en cascada", lambda: (DB.nombres(), DB.pasadas("Olivar", "2025-2026")),
          lambda r: r == ([], []))

    # Borrado COMPLETO: si queda alguna fila huerfana, una parcela nueva con el
    # mismo nombre heredaria radar/validaciones de la anterior.
    def _borrado_completo():
        DB.guardar_ficha("Efimera", {"propietario": "x", "coordenadas": [[0, 0], [0, 1], [1, 1]]})
        DB.anadir_pasadas("Efimera", "2025-2026", [{"fecha": "2026-03-01", "ndvi": 0.4}])
        DB.anadir_radar("Efimera", "2025-2026", [{"fecha": "2026-03-02", "vv": -9.0, "vh": -15.0}])
        DB.registrar_evento("Efimera", "2025-2026", {"fecha": "2026-03-03", "tipo": "SIEGA"})
        DB.guardar_validacion("Efimera", "2025-2026", "2026-03-01", "ahijado",
                              "EXTENSIVO//TRIGO", "Revisar", "incorrecto", estado_real="OK")
        DB.eliminar_parcela("Efimera")
        c = DB._c()
        with DB._LOCK:                     # se consulta la BD directamente, sin filtros
            return {t: c.execute(f"SELECT COUNT(*) FROM {t} WHERE nombre=?",
                                 ("Efimera",)).fetchone()[0]
                    for t in ("parcelas", "cultivos", "pasadas", "pasadas_radar",
                              "eventos", "validaciones")}
    check("almacen: eliminar_parcela no deja filas huerfanas en NINGUNA tabla",
          _borrado_completo, lambda r: all(n == 0 for n in r.values()))
    # migracion desde JSON antiguos
    d2 = tempfile.mkdtemp(); cwd = os.getcwd(); os.chdir(d2)
    try:
        _json.dump({"P": {"propietario": "x", "coordenadas": [[0, 0]], "superficie_ha": 1.0,
                          "cultivos_por_campana": {"2025-2026": {"tipo": "BARBECHO"}}}},
                   open("parcelas.json", "w"))
        _json.dump({"P": {"2025-2026": [{"fecha": "2026-03-01", "ndvi": 0.2}]}}, open("historico_reportes.json", "w"))
        _json.dump({"P": {"2025-2026": [{"id": "e1", "fecha": "2026-03-02", "tipo": "SIEGA"}]}}, open("eventos_parcela.json", "w"))
        DB.conectar(os.path.join(d2, "mig.db"))
        check("almacen: migracion JSON->SQLite", lambda: (DB.nombres(), DB.ultima_fecha("P", "2025-2026"),
                                                          DB.eventos_de("P", "2025-2026")[0]["id"]),
              lambda r: r == (["P"], "2026-03-01", "e1"))
        check("almacen: migracion renombra a .bak",
              lambda: os.path.exists("parcelas.json.bak") and not os.path.exists("parcelas.json"), lambda r: r is True)
    finally:
        os.chdir(cwd)


# =====================================================================
# 8. SIGPAC: parseo robusto de la respuesta GeoJSON (helpers extraidos del panel)
# =====================================================================
def pruebas_sigpac():
    # los helpers SIGPAC viven en sigpac.py (modulo puro): se importan directamente
    import sigpac as _SG
    geo, ani, ll = _SG.sigpac_geometria, _SG.sigpac_anillo, _SG.sigpac_a_lonlat
    anillo = [[-4.78, 37.88], [-4.77, 37.88], [-4.77, 37.89], [-4.78, 37.89]]
    check("sigpac: FeatureCollection", lambda: ani(geo(
        {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [anillo]}}]})),
        lambda r: r == anillo)
    check("sigpac: Feature", lambda: ani(geo(
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [anillo]}})), lambda r: r == anillo)
    check("sigpac: MultiPolygon suelto", lambda: ani(geo(
        {"type": "MultiPolygon", "coordinates": [[anillo]]})), lambda r: r == anillo)
    check("sigpac: respuesta vacia -> None", lambda: ani(geo({"type": "FeatureCollection", "features": []})),
          lambda r: r is None)
    check("sigpac: lon/lat se conserva", lambda: ll(anillo), lambda r: r[0] == [-4.78, 37.88])
    def _utm():
        try:
            ll([[345000.0, 4193000.0], [345100.0, 4193000.0], [345100.0, 4193100.0]])
            return "sin-error"
        except ValueError:
            return "error-claro"
    check("sigpac: UTM sin pyproj -> error claro (no coloca mal en silencio)", _utm,
          lambda r: r in ("error-claro", "sin-error"))   # con pyproj convierte; sin el, avisa
    # --- consulta con varios endpoints y mensajes de error claros ---
    consultar = _SG.sigpac_consultar; urls = _SG.sigpac_urls; SigErr = _SG.SigpacError
    V = {"Prov": "14", "Mun": "21", "Agr": "0", "Zona": "0", "Pol": "5", "Par": "12", "Rec": "1"}
    poly = {"type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [anillo]}}]}
    class _Resp:
        def __init__(self, code, payload=None): self.status_code = code; self._p = payload; self.text = ""
        def json(self):
            if self._p is None: raise ValueError("sin json")
            return self._p
    check("sigpac: urls -> 2 endpoints con los 7 codigos",
          lambda: urls(V), lambda r: len(r) == 2 and r[0].endswith("14/21/0/0/5/12/1.geojson"))
    check("sigpac: consulta OK devuelve el anillo",
          lambda: consultar(V, lambda u: _Resp(200, poly)), lambda r: r == anillo)
    def _fallback(u): return _Resp(200, poly) if "mapa.gob.es" in u else _Resp(404)
    check("sigpac: usa el 2o endpoint si el 1o da 404",
          lambda: consultar(V, _fallback), lambda r: r == anillo)
    def _cae(get):
        try: consultar(V, get); return "sin-error"
        except SigErr as e: return str(e)
    check("sigpac: 404 en todos -> mensaje claro (codigos / suelo urbano)",
          lambda: _cae(lambda u: _Resp(404)), lambda r: "404" in r and "urban" in r.lower())
    check("sigpac: 503 -> servicio no disponible",
          lambda: _cae(lambda u: _Resp(503)), lambda r: "disponible" in r.lower())
    def _boom(u): raise RuntimeError("timeout")
    check("sigpac: fallo de red -> mensaje de conexion",
          lambda: _cae(_boom), lambda r: "conectar" in r.lower())
    check("sigpac: respuesta 200 sin recinto -> mensaje 'revisa codigos'",
          lambda: _cae(lambda u: _Resp(200, {"type": "FeatureCollection", "features": []})),
          lambda r: "recinto" in r.lower())


# =====================================================================
# 9b. SENTINEL-1 (RADAR): indices e interpretacion cruzada con el optico
# =====================================================================
def pruebas_radar():
    import sentinel1 as S1
    import almacen as DB
    check("radar: db->lineal 0 dB = 1.0", lambda: S1.db_a_lineal(0.0), lambda r: abs(r - 1.0) < 1e-9)
    check("radar: db->lineal None -> None", lambda: S1.db_a_lineal(None), lambda r: r is None)
    check("radar: RVI en [0,1]", lambda: S1.rvi(-10, -17), lambda r: 0.0 <= r <= 1.0)
    check("radar: RVI None si falta banda", lambda: S1.rvi(None, -12), lambda r: r is None)
    check("radar: cross ratio VH-VV", lambda: S1.cross_ratio_db(-10, -17), lambda r: r == -7.0)
    # incertidumbre
    check("radar: error estandar = std/sqrt(n)", lambda: S1.error_estandar(1.0, 100), lambda r: r == 0.1)
    check("radar: error estandar n=0 -> None", lambda: S1.error_estandar(1.0, 0), lambda r: r is None)
    check("radar: RVI con incertidumbre da rango lo<=base<=hi",
          lambda: S1.rvi_incertidumbre(-9, -14, 0.5, 0.5),
          lambda r: r[1] <= r[0] <= r[2])
    check("radar: fiabilidad alta (muchos pixeles, poca dispersion)",
          lambda: S1.fiabilidad_radar(80, 1.0, 1.2), lambda r: r == "alta")
    check("radar: fiabilidad baja (pocos pixeles)",
          lambda: S1.fiabilidad_radar(5, 4.0, 5.0), lambda r: r == "baja")
    check("radar: fiabilidad desconocida sin n", lambda: S1.fiabilidad_radar(None, 1, 1),
          lambda r: r == "desconocida")
    # cambio de orbita resta validez a la tendencia
    opt_o = [{"fecha": "2026-06-01", "ndvi": 0.7}, {"fecha": "2026-06-13", "ndvi": 0.45}]
    rad_o = [{"fecha": "2026-06-02", "rvi": 0.55, "rvi_lo": 0.50, "rvi_hi": 0.60,
              "orbita": "ASCENDING", "fiabilidad": "alta", "n_pixeles": 80},
             {"fecha": "2026-06-14", "rvi": 0.40, "rvi_lo": 0.35, "rvi_hi": 0.45,
              "orbita": "DESCENDING", "fiabilidad": "media", "n_pixeles": 30}]
    check("radar: cambio de orbita -> tendencia no fiable + cautela",
          lambda: S1.interpretar_radar(opt_o, rad_o, {"estado": "Revisar", "fase": "x"}),
          lambda r: r["tendencia_fiable"] is False and any("ORBITA" in c.upper() for c in r["cautelas"]))
    check("radar: fiabilidad baja aparece como cautela",
          lambda: S1.interpretar_radar(
              [{"fecha": "2026-06-01", "ndvi": 0.6}, {"fecha": "2026-06-13", "ndvi": 0.55}],
              [{"fecha": "2026-06-14", "rvi": 0.4, "fiabilidad": "baja", "n_pixeles": 5}])["cautelas"],
          lambda r: any("fiable" in c for c in r))
    # interpretacion cruzada con el optico
    check("radar: sin pasadas -> no disponible",
          lambda: S1.interpretar_radar([{"fecha": "2026-05-01", "ndvi": 0.5}], []),
          lambda r: r["disponible"] is False)
    opt_nube = [{"fecha": "2026-05-01", "ndvi": 0.6}, {"fecha": "2026-05-13", "ndvi": None}]
    rad = [{"fecha": "2026-05-02", "rvi": 0.42, "vv": -9, "vh": -15},
           {"fecha": "2026-05-14", "rvi": 0.50, "vv": -9, "vh": -14}]
    check("radar: optico nublado -> aporta continuidad",
          lambda: S1.interpretar_radar(opt_nube, rad, {"estado": "OK", "fase": "encanado"}),
          lambda r: r["concordancia"] == "continuidad" and "continuidad" in r["texto"].lower())
    opt_baja = [{"fecha": "2026-06-01", "ndvi": 0.7}, {"fecha": "2026-06-13", "ndvi": 0.45}]
    rad_baja = [{"fecha": "2026-06-02", "rvi": 0.55}, {"fecha": "2026-06-14", "rvi": 0.40}]
    check("radar: bajan juntos -> descenso confirmado",
          lambda: S1.interpretar_radar(opt_baja, rad_baja)["concordancia"], lambda r: r == "bajan juntos")
    opt_verde = [{"fecha": "2026-03-01", "ndvi": 0.4}, {"fecha": "2026-03-13", "ndvi": 0.6}]
    rad_plano = [{"fecha": "2026-03-02", "rvi": 0.40}, {"fecha": "2026-03-14", "rvi": 0.39}]
    check("radar: NDVI sube sin radar -> verdor sin estructura",
          lambda: S1.interpretar_radar(opt_verde, rad_plano)["concordancia"],
          lambda r: r == "verdor sin estructura")
    # almacen: serie de radar independiente
    DB.conectar(os.path.join(tempfile.mkdtemp(), "radar.db"))
    DB.guardar_ficha("P", {"propietario": "x", "coordenadas": [[0, 0], [0, 1], [1, 1]],
                           "superficie_ha": 1.0})
    DB.anadir_radar("P", "2025-2026", [{"fecha": "2026-05-02", "vv": -9, "vh": -15, "rvi": 0.42},
                                       {"fecha": "2026-05-14", "vv": -9, "vh": -14, "rvi": 0.50}])
    DB.anadir_radar("P", "2025-2026", [{"fecha": "2026-05-02", "rvi": 0.99}])  # ya existe: no pisa
    check("radar: almacen roundtrip + no sobrescribe",
          lambda: (len(DB.radar("P", "2025-2026")), DB.radar("P", "2025-2026")[0]["rvi"],
                   DB.ultima_fecha_radar("P", "2025-2026")),
          lambda r: r == (2, 0.42, "2026-05-14"))


# =====================================================================
# 9. TOOLTIP DE LA GRAFICA (valores del dia + fiabilidad) - helper del panel
# =====================================================================
def pruebas_panel_helpers():
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel_gestion_parcelas.py")
    src = open(ruta, encoding="utf-8").read()
    m = re.search(r"\ndef tooltip_pasada\(.*?\n(?=\ndef _colores_estado)", src, re.S)
    if not m:
        _FALLA.append(("panel", "no se localiza tooltip_pasada en el panel"))
        return
    ns = {"INDICES_ORDEN": ["NDVI", "EVI", "SAVI", "GNDVI", "LAI", "MSAVI", "NDMI"]}
    exec(m.group(0), ns)
    tip = ns["tooltip_pasada"]
    reg = {"fecha": "2026-05-05", "ndvi": 0.812, "ndmi": 0.21, "cobertura_valida": 0.97}
    check("tooltip: incluye fecha, NDVI y fiabilidad alta",
          lambda: tip(reg),
          lambda r: "2026-05-05" in r and "NDVI: 0.812" in r and "Fiabilidad: 97%" in r and "alta" in r)
    check("tooltip: fiabilidad baja se etiqueta",
          lambda: tip({"fecha": "2026-05-05", "ndvi": 0.5, "cobertura_valida": 0.82}),
          lambda r: "baja" in r)
    check("tooltip: sin cobertura no revienta",
          lambda: tip({"fecha": "2026-05-05", "ndvi": 0.5}), lambda r: "Fiabilidad" not in r)
    check("tooltip: registro vacio -> cadena vacia", lambda: tip({}), lambda r: r == "" or "None" not in r)

    # No todas las clases del panel son widgets: FichaParcela, LienzoMapa y
    # PanelMapaComparado son clases normales que PINTAN sobre un master. Pasarles
    # `self` como padre de un widget revienta con
    #   AttributeError: 'FichaParcela' object has no attribute 'tk'
    # y, como ocurre dentro de un callback de Tk, no se ve: el menu contextual del
    # cuaderno simplemente no abria, y era la unica forma de borrar un evento.
    # Se comprueba sobre el fuente porque la suite corre sin pantalla.
    import ast as _ast
    arbol = _ast.parse(src)
    _WIDGET = ("tk.Frame", "tk.Toplevel", "ttk.Frame", "tk.Canvas", "tk.Tk")

    def _es_widget(cls):
        for b in cls.bases:
            if (isinstance(b, _ast.Attribute)
                    and f"{getattr(b.value, 'id', '')}.{b.attr}" in _WIDGET):
                return True
        return False

    def _self_como_padre():
        malos = []
        for cls in [n for n in arbol.body if isinstance(n, _ast.ClassDef)]:
            if _es_widget(cls):
                continue                      # es un widget: `self` como padre es valido
            for n in _ast.walk(cls):
                if (isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
                        and getattr(n.func.value, "id", "") in ("tk", "ttk")
                        and n.args and isinstance(n.args[0], _ast.Name)
                        and n.args[0].id == "self"):
                    malos.append(f"{cls.name}:{n.lineno} {n.func.attr}")
        return malos
    check("panel: ninguna clase que NO es widget se pasa a si misma como padre",
          _self_como_padre, lambda r: r == [])

    # Suplentes UTF-16 sueltos. Escribir un emoji como dos escapes ("\\uD83D\\uDCE1")
    # NO produce el emoji: produce dos medios caracteres que no se pueden codificar en
    # UTF-8. Al pasarselos a Tk saltaba UnicodeEncodeError y la ficha de parcela no
    # llegaba a abrirse. Un emoji se escribe de una pieza: "\\U0001F4E1".
    def _suplentes_sueltos():
        malos = []
        carpeta = os.path.dirname(os.path.abspath(__file__))
        for f in sorted(x for x in os.listdir(carpeta) if x.endswith(".py")):
            with open(os.path.join(carpeta, f), encoding="utf-8") as fh:
                for i, linea in enumerate(fh, 1):
                    if any(0xD800 <= ord(c) <= 0xDFFF for c in linea):
                        malos.append(f"{f}:{i}")
        return malos
    check("fuente: ningun caracter a medias (suplentes UTF-16 sueltos)",
          _suplentes_sueltos, lambda r: r == [])

    # campanas_entre (para sincronizar anos anteriores): vive en campanas.py (modulo puro)
    from campanas import campanas_entre as ce
    check("campanas_entre: rango descendente inclusive",
          lambda: ce("2022-2023", "2025-2026"),
          lambda r: r == ["2025-2026", "2024-2025", "2023-2024", "2022-2023"])
    check("campanas_entre: una sola campana",
          lambda: ce("2025-2026", "2025-2026"), lambda r: r == ["2025-2026"])
    check("campanas_entre: orden invertido se corrige",
          lambda: ce("2025-2026", "2023-2024"), lambda r: r[0] == "2025-2026" and len(r) == 3)
    check("campanas_entre: entrada mal formada no revienta",
          lambda: ce(None, "2025-2026"), lambda r: r == ["2025-2026"])
    from datetime import datetime as _dtc
    from campanas import campana_actual as _ca, rango_campana as _rc
    check("campana_actual: octubre -> anio-anio+1",
          lambda: _ca(_dtc(2025, 10, 1)), lambda r: r == "2025-2026")
    check("campana_actual: marzo -> anio-1-anio",
          lambda: _ca(_dtc(2026, 3, 1)), lambda r: r == "2025-2026")
    check("rango_campana: 1-sep a 31-ago",
          lambda: _rc("2025-2026"), lambda r: r == ("2025-09-01", "2026-08-31"))

    # --- QUE CAMPANAS OFRECER EN LA FICHA ---
    # El limite lo pone el satelite (Sentinel-2 L2A empieza en la 2017-2018), no
    # una constante inventada. Y lo que hay guardado mas atras NO se esconde: se
    # marca "solo archivo", porque es lo unico que queda de esos anos.
    from campanas import (campanas_de_parcela as cdp, campanas_sincronizables as cs,
                          PRIMERA_CAMPANA_S2, PRIMERA_CAMPANA_S2_GLOBAL)
    HOY = _dtc(2026, 3, 1)                    # campana en curso: 2025-2026
    check("campanas sincronizables: de la primera de Sentinel-2 a la actual",
          lambda: cs(HOY),
          lambda r: r[0] == "2025-2026" and r[-1] == PRIMERA_CAMPANA_S2 and len(r) == 9)
    todas = cdp((), HOY)
    check("campanas ficha: sin datos se ofrecen igual todas las descargables",
          lambda: [c["campana"] for c in todas],
          lambda r: r == cs(HOY))
    check("campanas ficha: la mas reciente primero y marcada como en curso",
          lambda: (todas[0]["campana"], todas[0]["actual"], todas[1]["actual"]),
          lambda r: r == ("2025-2026", True, False))
    check("campanas ficha: la 2017-2018 se marca parcial (cobertura no global)",
          lambda: {c["campana"]: c["parcial"] for c in todas},
          lambda r: r[PRIMERA_CAMPANA_S2] is True and r[PRIMERA_CAMPANA_S2_GLOBAL] is False)
    con = cdp(["2024-2025", "2013-2014"], HOY)
    check("campanas ficha: una campana con datos se marca con datos",
          lambda: [c for c in con if c["campana"] == "2024-2025"][0],
          lambda c: c["tiene_datos"] and c["sincronizable"] and not c["solo_archivo"])
    check("campanas ficha: una campana anterior al satelite NO se pierde de la lista",
          lambda: [c for c in con if c["campana"] == "2013-2014"],
          lambda r: len(r) == 1)
    check("campanas ficha: y sale como solo archivo (se ve, no se sincroniza)",
          lambda: [c for c in con if c["campana"] == "2013-2014"][0],
          lambda c: c["solo_archivo"] and c["tiene_datos"] and not c["sincronizable"])
    check("campanas ficha: el archivo va al final, detras de las descargables",
          lambda: [c["campana"] for c in con][-1], lambda r: r == "2013-2014")
    check("campanas ficha: una campana guardada sin cobertura no inventa 'con datos'",
          lambda: [c["tiene_datos"] for c in cdp((), HOY)], lambda r: not any(r))
    check("campanas ficha: entrada vacia o None no revienta",
          lambda: (len(cdp(None, HOY)), len(cdp(["", None], HOY))),
          lambda r: r == (9, 9))

    # ruta_cache_mapa: ficha y comparador deben usar la MISMA ruta de cache.
    # Vive en mapas_cache.py: se importa, no se extrae del panel.
    from mapas_cache import ruta_cache_mapa as rc, ruta_cache_radar as rcr
    check("ruta_cache_mapa: formato parcela_indice_dia_resolucion",
          lambda: rc("Olivar", "NDVI", "2026-05-05", 10),
          lambda r: r.endswith(os.path.join("cache_mapas", "Olivar_NDVI_2026-05-05_10m.png")))
    check("ruta_cache_mapa: distinto indice -> distinta ruta (no colisiona)",
          lambda: rc("Olivar", "NDVI", "2026-05-05", 10) != rc("Olivar", "NDMI", "2026-05-05", 10),
          lambda r: r is True)
    check("ruta_cache_mapa: nombre con espacios/barras se sanea",
          lambda: rc("../Olivar del Sur", "NDVI", "2026-05-05", 10),
          lambda r: ".." not in os.path.basename(r) and "Olivar_del_Sur" in r)
    check("ruta_cache_radar: no colisiona con la del optico",
          lambda: rcr("Olivar", "VV", "2026-05-05", 10) != rc("Olivar", "VV", "2026-05-05", 10),
          lambda r: r is True)

    # conversores de fecha: el usuario ve dd-mm-aaaa, el programa guarda ISO.
    # Ya viven en fechas.py (modulo puro): se importan directamente, sin extraer del panel.
    from fechas import ddmmaaaa_a_iso as a_iso, iso_a_ddmmaaaa as a_disp
    from fechas import enmascarar_fecha as mask, filtrar_fecha_digitos as filt
    check("fecha: iso -> dd-mm-aaaa", lambda: a_disp("2026-05-04"), lambda r: r == "04-05-2026")
    check("fecha: dd-mm-aaaa -> iso", lambda: a_iso("04-05-2026"), lambda r: r == "2026-05-04")
    check("fecha: 8 digitos sin guiones -> iso", lambda: a_iso("04052026"), lambda r: r == "2026-05-04")
    check("fecha: incompleta -> ''", lambda: a_iso("04-05"), lambda r: r == "")
    check("fecha: dia invalido -> ''", lambda: a_iso("32-01-2026"), lambda r: r == "")
    check("fecha: mascara pone los guiones sola", lambda: mask("04052026"), lambda r: r == "04-05-2026")
    check("fecha: mascara parcial", lambda: mask("0405"), lambda r: r == "04-05")
    check("fecha: iso invalido -> '' (display)", lambda: a_disp("no-fecha"), lambda r: r == "")
    # validacion al vuelo mientras se teclea
    check("fecha viva: fecha valida pasa entera", lambda: filt("04052026"), lambda r: r == "04052026")
    check("fecha viva: dia 32 se corta (mantiene el 3)", lambda: filt("32"), lambda r: r == "3")
    check("fecha viva: decena de dia > 3 se rechaza", lambda: filt("4"), lambda r: r == "")
    check("fecha viva: mes 13 se corta (mantiene el 1)", lambda: filt("0413"), lambda r: r == "041")
    check("fecha viva: decena de mes > 1 se rechaza", lambda: filt("042"), lambda r: r == "04")
    check("fecha viva: dia 00 se rechaza", lambda: filt("00"), lambda r: r == "0")
    check("fecha viva: dia 31 valido", lambda: filt("3112"), lambda r: r == "3112")


# =====================================================================
# 11. INFORME ANUAL (modulo OPCIONAL informe_anual; se omite si se borra)
# =====================================================================
def pruebas_informe_anual():
    """El informe anual vive en un modulo aparte y extraible. Si el fichero no
    existe, o falta reportlab, estas pruebas se OMITEN y la suite sigue verde."""
    try:
        import informe_anual as IA
    except Exception:
        return                                   # modulo borrado -> nada que probar
    if not getattr(IA, "DISPONIBLE", False):
        return                                   # sin reportlab -> se omite (no es un fallo)

    ficha = {"propietario": "Prueba", "coordenadas":
             [[-4.10, 41.65], [-4.093, 41.65], [-4.093, 41.654], [-4.10, 41.654], [-4.10, 41.65]]}
    cultivo = {"tipo": "EXTENSIVO", "especie": "TRIGO", "fecha_siembra": "2025-11-10"}
    serie = [{"fecha": "2025-12-05", "ndvi": 0.22, "lai": 0.6, "ndmi": 0.18},
             {"fecha": "2026-02-12", "ndvi": 0.55, "lai": 2.1, "ndmi": 0.30},
             {"fecha": "2026-04-15", "ndvi": 0.80, "lai": 3.8, "ndmi": 0.30},
             {"fecha": "2026-06-12", "ndvi": 0.34, "lai": 1.3, "ndmi": 0.06}]
    d = tempfile.mkdtemp(); out = os.path.join(d, "inf.pdf")
    check("informe anual: genera un PDF no vacio",
          lambda: (IA.generar_informe_anual("Prueba_Parcela", "2025-2026", ficha, cultivo,
                                            serie, ruta_salida=out),
                   os.path.getsize(out))[1],
          lambda r: r > 1000)
    # informe TECNICO (PDF): mismo motor, mas detalle
    tec = os.path.join(d, "tec.pdf")
    check("informe tecnico: genera un PDF no vacio",
          lambda: (IA.generar_informe_tecnico("Prueba_Parcela", "2025-2026", ficha, cultivo,
                                              serie, ruta_salida=tec),
                   os.path.getsize(tec))[1],
          lambda r: r > 1000)
    # agregado mensual (puro): una fila por mes con medias
    check("informe: agregado mensual = una fila por mes",
          lambda: [f["label"] for f in IA._agregado_mensual(serie)],
          lambda r: len(r) == 4 and r[0].startswith("Diciembre"))
    check("informe: media mensual correcta (abril)",
          lambda: next(f for f in IA._agregado_mensual(serie) if f["mes"] == 4)["ndvi"],
          lambda r: abs(r - 0.80) < 1e-6)
    # el helper de superficie es puro y no depende del PDF
    check("informe anual: superficie_ha coherente (>0)",
          lambda: IA._superficie_ha(ficha["coordenadas"]), lambda r: r and r > 0)
    # EXCEL: solo si openpyxl esta presente (si no, se omite, no es fallo)
    if getattr(IA, "EXCEL_DISPONIBLE", False):
        xls = os.path.join(d, "idx.xlsx")
        check("informe excel: genera un .xlsx con hojas de indices",
              lambda: (IA.generar_excel("Prueba_Parcela", "2025-2026", ficha, cultivo,
                                        serie, ruta_salida=xls),
                       os.path.getsize(xls))[1],
              lambda r: r > 2000)

        def _hojas():
            import openpyxl
            return openpyxl.load_workbook(xls).sheetnames
        check("informe excel: incluye hoja de variacion mensual",
              _hojas, lambda r: "Variación mensual" in r and "Medias mensuales" in r)


# la comprobacion de "debe lanzar" se maneja aparte: check marca fallo si NO revienta,
# asi que la envolvemos para invertir la logica.
def _informe_anual_error():
    try:
        import informe_anual as IA
    except Exception:
        return
    if not getattr(IA, "DISPONIBLE", False):
        return
    ficha = {"propietario": "P", "coordenadas": [[0, 0], [0, 1], [1, 1]]}
    cultivo = {"tipo": "EXTENSIVO", "especie": "TRIGO"}
    d = tempfile.mkdtemp(); out = os.path.join(d, "x.pdf")
    lanzo = False
    try:
        IA.generar_informe_anual("P", "2025-2026", ficha, cultivo, [], ruta_salida=out)
    except Exception:
        lanzo = True
    check("informe anual: serie vacia lanza RuntimeError", lambda: lanzo, lambda r: r is True)


# =====================================================================
# 16. CLIENTE DE EARTH ENGINE con un `ee` FALSO (descarga probada sin red)
# =====================================================================
class _EeFalso:
    """Doble de `ee` para probar la descarga SIN RED.

    Cualquier atributo o llamada devuelve el propio objeto, de modo que toda la
    cadena de Earth Engine (`ee.Geometry.Polygon(...)`, `ee.ImageCollection(...)
    .filterBounds(...).filterDate(...).map(...)`) se recorre sin hacer nada. Lo
    unico que responde de verdad es `getInfo`, que entrega las pasadas indicadas:
    asi se puede comprobar el FILTRADO posterior, que es la logica del programa.
    """
    def __init__(self, features):
        object.__setattr__(self, "_features", features)

    def __getattr__(self, _nombre):
        return self                  # ee.Geometry, .Reducer, .Filter, .mean...

    def __call__(self, *a, **k):
        return self                  # ...y todas ellas son llamables

    def getInfo(self):
        return {"features": object.__getattribute__(self, "_features")}


class _EeRejilla:
    """Doble de `ee` para probar la descarga de la REJILLA sin red.

    A diferencia de `_EeFalso`, aqui hacen falta varias respuestas distintas: la
    proyeccion nativa, las areas (para decidir el buffer), la envolvente y las
    matrices de cada fecha. Se devuelven en el orden en que las pide el codigo, y
    cada llamada a `getInfo` consume la siguiente.
    """
    def __init__(self, respuestas):
        object.__setattr__(self, "_pendientes", list(respuestas))
        object.__setattr__(self, "_pedidas", [])

    def __getattr__(self, nombre):
        object.__getattribute__(self, "_pedidas").append(nombre)
        return self

    def __call__(self, *a, **k):
        return self

    def getInfo(self):
        pend = object.__getattribute__(self, "_pendientes")
        if not pend:
            raise AssertionError("el codigo pidio mas getInfo de los previstos")
        return pend.pop(0)


def _matriz(filas, columnas, valor=0.6, invalidos=()):
    ndvi = [[valor] * columnas for _ in range(filas)]
    val = [[1] * columnas for _ in range(filas)]
    for i, j in invalidos:
        val[i][j] = 0
    return ndvi, val


def pruebas_buffer_y_zonas():
    """Buffer interior por parcela y encendido/apagado del analisis de zonas."""
    import almacen as DB
    import gee_cliente as G
    from interpretacion_fenologica import evaluar_parcela

    DB.conectar(os.path.join(tempfile.mkdtemp(), "buf.db"))
    DB.guardar_ficha("P", {"propietario": "x", "coordenadas": [[0, 0]], "superficie_ha": 8})
    check("buffer: por defecto no se guarda nada (NULL = usa el del programa)",
          lambda: DB.ficha("P")["buffer_m"], lambda r: r is None)
    check("buffer: sin valor propio se usa el de por defecto",
          lambda: G.buffer_de(DB.ficha("P")), lambda r: r == G.BUFFER_INTERIOR_M)
    check("buffer: se puede subir",
          lambda: (DB.guardar_ficha("P", dict(DB.ficha("P"), buffer_m=30.0)),
                   G.buffer_de(DB.ficha("P")))[1], lambda r: r == 30.0)
    check("buffer: se puede bajar",
          lambda: (DB.guardar_ficha("P", dict(DB.ficha("P"), buffer_m=5.0)),
                   G.buffer_de(DB.ficha("P")))[1], lambda r: r == 5.0)
    check("buffer: un 0 explicito es 'sin margen', no 'por defecto'",
          lambda: (DB.guardar_ficha("P", dict(DB.ficha("P"), buffer_m=0.0)),
                   DB.ficha("P")["buffer_m"], G.buffer_de(DB.ficha("P")))[1:],
          lambda r: r == (0.0, 0.0))
    check("buffer: un guardado que no lo menciona NO lo pisa",
          lambda: (DB.guardar_ficha("P", {"propietario": "y", "coordenadas": [[0, 0]],
                                          "superficie_ha": 9}),
                   DB.ficha("P")["buffer_m"])[1], lambda r: r == 0.0)
    check("buffer: un valor absurdo no rompe, cae al de por defecto",
          lambda: G.buffer_de({"buffer_m": "lo que sea"}), lambda r: r == G.BUFFER_INTERIOR_M)
    check("buffer: negativo se trata como 0 (no se ensancha la parcela)",
          lambda: G.buffer_de({"buffer_m": -10}), lambda r: r == 0.0)

    # --- analisis de zonas: se apaga el JUICIO, no el dato
    serie = [{"fecha": "2026-04-01", "ndvi": 0.70, "ndvi_std": 0.05, "p10": 0.64,
              "p50": 0.70, "p90": 0.76, "ndmi": 0.20, "lai": 3.0},
             {"fecha": "2026-04-20", "ndvi": 0.60, "ndvi_std": 0.14, "p10": 0.38,
              "p50": 0.62, "p90": 0.74, "ndmi": 0.18, "lai": 2.8}]
    spec = {"especie": "TRIGO", "fecha_siembra": "2025-11-01"}

    def _con(on):
        return evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", serie, spec=spec,
                               heterogeneidad_activa=on)
    check("zonas: encendido (por defecto) avisa del foco y sube a Vigilar",
          lambda: _con(True),
          lambda d: d["estado"] == "Vigilar" and ("FOCO" in d["motivo"]
                                                  or "AVISO TEMPRANO" in d["motivo"]))
    check("zonas: apagado no avisa ni cambia el estado",
          lambda: _con(False),
          lambda d: d["estado"] == "OK" and "FOCO" not in d["motivo"]
          and "AVISO TEMPRANO" not in d["motivo"])
    check("zonas: apagado NO deja de calcular los estadisticos (solo el juicio)",
          lambda: _con(False)["heterogeneidad"], lambda r: r is not None)
    check("zonas: el valor por defecto de la firma conserva el comportamiento de siempre",
          lambda: evaluar_parcela("EXTENSIVO", "COSECHA_GRANO", serie, spec=spec)["estado"],
          lambda r: r == "Vigilar")

    # --- persistencia del ajuste
    DB.guardar_ficha("Q", {"propietario": "x", "coordenadas": [[0, 0]], "superficie_ha": 8})
    check("zonas: por defecto vienen encendidas (como se ha comportado siempre)",
          lambda: DB.ficha("Q")["heterogeneidad"], lambda r: r is True)
    check("zonas: apagarlas se guarda con la parcela",
          lambda: (DB.guardar_ficha("Q", dict(DB.ficha("Q"), heterogeneidad=False)),
                   DB.ficha("Q")["heterogeneidad"])[1], lambda r: r is False)
    check("zonas: un guardado que no las menciona NO las vuelve a encender",
          lambda: (DB.guardar_ficha("Q", {"propietario": "z", "coordenadas": [[0, 0]],
                                          "superficie_ha": 8}),
                   DB.ficha("Q")["heterogeneidad"])[1], lambda r: r is False)
    check("zonas: solo afectan a su parcela",
          lambda: DB.ficha("P")["heterogeneidad"], lambda r: r is True)


def pruebas_rejilla_coherencia():
    """El contraste cruzado: la media de la rejilla contra la del servidor.

    Es la unica comprobacion automatica que caza una rejilla desplazada o mal
    enmascarada, que es justo lo que no se puede probar contra Earth Engine sin
    credenciales. Si se cuela, la etapa de heterogeneidad mediria ruido dandolo
    por bueno."""
    import rejilla as R

    vals = [0.60] * 20
    validos = [True] * 20
    check("coherencia: media de los pixeles validos",
          lambda: R.media_valida([0.5, 0.7, 0.9], [True, True, False]), lambda r: r == 0.6)
    check("coherencia: sin pixeles validos no hay media",
          lambda: R.media_valida([0.5], [False]), lambda r: r is None)
    check("coherencia: si la rejilla cuadra con el servidor, pasa",
          lambda: R.coherente(vals, validos, 0.60), lambda r: r == (True, 0.0))
    check("coherencia: una diferencia dentro de la cuantificacion pasa",
          lambda: R.coherente(vals, validos, 0.605)[0], lambda r: r is True)
    check("coherencia: una rejilla DESPLAZADA no cuadra y se caza",
          lambda: R.coherente(vals, validos, 0.42), lambda r: r[0] is False and r[1] == 0.18)
    check("coherencia: una mascara invertida tampoco cuadra",
          lambda: R.coherente([0.6] * 10 + [0.1] * 10, [False] * 10 + [True] * 10, 0.60)[0],
          lambda r: r is False)
    check("coherencia: sin referencia se da por buena (mejor eso que nada)",
          lambda: R.coherente(vals, validos, None), lambda r: r == (True, None))
    check("coherencia: si dice tener pixeles y no tiene ninguno, se rechaza",
          lambda: R.coherente(vals, [False] * 20, 0.60), lambda r: r == (False, None))
    check("coherencia: la tolerancia cubre medio paso de cuantificacion",
          lambda: R.TOLERANCIA_MEDIA, lambda t: t >= 1.0 / R.ESCALA_NDVI / 2)


def pruebas_rejilla_descarga():
    """La descarga de la rejilla, con `ee` sustituido por un doble."""
    import gee_cliente as G
    import almacen as DB
    import rejilla as R

    d = tempfile.mkdtemp()
    DB.conectar(os.path.join(d, "rd.db"))
    DB.guardar_ficha("P", {"propietario": "x", "superficie_ha": 8,
                           "coordenadas": [[-4.10, 41.65], [-4.093, 41.65],
                                           [-4.093, 41.654], [-4.10, 41.654]]})
    TR = [10.0, 0.0, 399960.0, 0.0, -10.0, 4600020.0]
    ESQ = [[[400120.0, 4599730.0], [400290.0, 4599730.0],
            [400290.0, 4599880.0], [400120.0, 4599880.0]]]
    # 15x17 = 255 pixeles segun el encaje de esa envolvente
    i0, j0, filas, columnas, _rect = R.encajar(ESQ[0], TR)

    def _monta(area_buf=90000.0, crs_por_fecha=None, forma=None, media=0.6):
        nd, va = _matriz(*(forma or (filas, columnas)), invalidos=[(0, 0), (1, 1)])
        fechas = ["2026-04-10", "2026-04-20"]
        rasgos = []
        for f in fechas:
            rasgos.append({"properties": {"fecha": f, "ndvi": nd, "valido": va,
                                          "media": media,
                                          "crs": (crs_por_fecha or {}).get(f, "EPSG:32630")}})
        return _EeRejilla([
            {"crs": "EPSG:32630", "transform": TR},        # proyeccion nativa
            {"buf": area_buf, "todo": 100000.0},           # areas: decide el buffer
            ESQ,                                           # envolvente en ese CRS
            {"features": rasgos},                          # las matrices
        ]), fechas

    orig = G.ee
    try:
        G.ee, fechas = _monta()
        n = G._descargar_rejillas("P", "2025-2026", G.ee, fechas)
        check("rejilla/descarga: guarda una rejilla por fecha", lambda: n, lambda r: r == 2)
        guardadas = DB.rejillas("P", "2025-2026")
        check("rejilla/descarga: la georreferenciacion sale de la reticula nativa",
              lambda: {k: guardadas[0][k] for k in ("crs", "escala", "i0", "j0",
                                                    "filas", "columnas")},
              lambda r: r == {"crs": "EPSG:32630", "escala": 10.0, "i0": i0, "j0": j0,
                              "filas": filas, "columnas": columnas})
        check("rejilla/descarga: las dos fechas comparten reticula",
              lambda: len(R.comparables(guardadas)[0]), lambda r: r == 2)
        check("rejilla/descarga: la mascara de nubes llega hasta el dato guardado",
              lambda: R.decodificar(guardadas[0])["valores"][0], lambda r: r is None)
        check("rejilla/descarga: con buffer amplio se aplica el buffer interior",
              lambda: (guardadas[0]["sin_buffer"], guardadas[0]["buffer_m"]),
              lambda r: r == (False, G.BUFFER_INTERIOR_M))
        check("rejilla/descarga: cabe en el presupuesto de 2 KB",
              lambda: DB.tamano_rejillas("P")[1] / 2.0, lambda b: b <= 2048)

        # buffer que deja la parcela por debajo del minimo -> se guarda sin buffer
        DB.conectar(os.path.join(d, "rd2.db"))
        DB.guardar_ficha("P", {"propietario": "x", "superficie_ha": 0.3,
                               "coordenadas": [[-4.10, 41.65], [-4.099, 41.65],
                                               [-4.099, 41.6505], [-4.10, 41.6505]]})
        G.ee, fechas = _monta(area_buf=500.0)          # 5 pixeles: por debajo de 20
        G._descargar_rejillas("P", "2025-2026", G.ee, fechas)
        check("rejilla/descarga: si el buffer deja menos de 20 pixeles, se marca",
              lambda: [(r["sin_buffer"], r["buffer_m"]) for r in DB.rejillas("P")],
              lambda r: r and all(x == (True, 0) for x in r))

        # una fecha que llega en OTRO huso no se guarda con la geometria de las demas
        DB.conectar(os.path.join(d, "rd3.db"))
        DB.guardar_ficha("P", {"propietario": "x", "superficie_ha": 8,
                               "coordenadas": [[-4.10, 41.65], [-4.093, 41.65],
                                               [-4.093, 41.654], [-4.10, 41.654]]})
        G.ee, fechas = _monta(crs_por_fecha={"2026-04-20": "EPSG:32629"})
        n3 = G._descargar_rejillas("P", "2025-2026", G.ee, fechas)
        check("rejilla/descarga: la fecha de otro huso UTM se omite, no se guarda mal",
              lambda: (n3, [r["fecha"] for r in DB.rejillas("P")]),
              lambda r: r == (1, ["2026-04-10"]))

        # matriz con otra forma -> se descarta esa fecha
        DB.conectar(os.path.join(d, "rd4.db"))
        DB.guardar_ficha("P", {"propietario": "x", "superficie_ha": 8,
                               "coordenadas": [[-4.10, 41.65], [-4.093, 41.65],
                                               [-4.093, 41.654], [-4.10, 41.654]]})
        G.ee, fechas = _monta(forma=(filas - 1, columnas))
        n4 = G._descargar_rejillas("P", "2025-2026", G.ee, fechas)
        check("rejilla/descarga: una matriz de otra forma se descarta (no se desplaza)",
              lambda: (n4, DB.tamano_rejillas("P")[0]), lambda r: r == (0, 0))

        # LO MAS IMPORTANTE: si la rejilla falla, las pasadas NO se pierden y el
        # mensaje que ve el usuario no cambia. La rejilla es un extra.
        class _EeRejillaRota:
            def __init__(self):
                object.__setattr__(self, "n", 0)

            def __getattr__(self, _n):
                return self

            def __call__(self, *a, **k):
                return self

            def getInfo(self):
                object.__setattr__(self, "n", object.__getattribute__(self, "n") + 1)
                if object.__getattribute__(self, "n") == 1:
                    return {"features": [{"properties": {
                        "fecha": "2026-04-10", "cobertura_valida": 0.95, "ndvi": 0.55,
                        "evi": 0.3, "savi": 0.4, "gndvi": 0.4, "lai": 2.0, "msavi": 0.4,
                        "ndmi": 0.2, "ndvi_std": 0.05, "n_pixeles": 800}}]}
                raise RuntimeError("Earth Engine dice que no")

        DB.conectar(os.path.join(d, "rd5.db"))
        DB.guardar_ficha("P", {"propietario": "x", "superficie_ha": 8,
                               "coordenadas": [[-4.10, 41.65], [-4.093, 41.65],
                                               [-4.093, 41.654], [-4.10, 41.654]]})
        G.ee = _EeRejillaRota()
        res = G.sincronizar_parcela("P", "2025-2026")
        check("rejilla/descarga: si la rejilla falla, la pasada SI se guarda",
              lambda: (res, len(DB.pasadas("P", "2025-2026")), DB.tamano_rejillas("P")[0]),
              lambda r: r == ((1, "anadidas 1 fechas nuevas"), 1, 0))

        # una rejilla que no cuadra con la media del servidor NO se guarda: dejarla
        # pasar seria peor que no tenerla, porque la heterogeneidad la daria por
        # buena y mediria ruido con aspecto de dato
        DB.conectar(os.path.join(d, "rd7.db"))
        DB.guardar_ficha("P", {"propietario": "x", "superficie_ha": 8,
                               "coordenadas": [[-4.10, 41.65], [-4.093, 41.65],
                                               [-4.093, 41.654], [-4.10, 41.654]]})
        G.ee, fechas = _monta(media=0.20)          # la rejilla trae 0.6: no cuadra
        n7 = G._descargar_rejillas("P", "2025-2026", G.ee, fechas)
        check("rejilla/descarga: la que no cuadra con el servidor no se guarda",
              lambda: (n7, DB.tamano_rejillas("P")[0]), lambda r: r == (0, 0))

        # ---- RELLENO DEL HISTORICO: campanas anteriores, ya descargadas antes de
        # que existiera la rejilla. Sin esto habria que esperar una campana entera.
        DB.conectar(os.path.join(d, "rd6.db"))
        DB.guardar_ficha("P", {"propietario": "x", "superficie_ha": 8,
                               "coordenadas": [[-4.10, 41.65], [-4.093, 41.65],
                                               [-4.093, 41.654], [-4.10, 41.654]]})
        for camp, fs in (("2023-2024", ["2024-04-10", "2024-04-20"]),
                         ("2024-2025", ["2025-04-10"]),
                         ("2025-2026", ["2026-04-10", "2026-04-20"])):
            DB.anadir_pasadas("P", camp, [{"fecha": f, "ndvi": 0.5} for f in fs])
        check("rejilla/relleno: se ven las campanas de la parcela",
              lambda: DB.campanas_de("P"),
              lambda r: r == ["2023-2024", "2024-2025", "2025-2026"])

        def _relleno():
            # una tanda de respuestas por campana: proyeccion, areas, envolvente y datos
            resp = []
            for fs in (["2024-04-10", "2024-04-20"], ["2025-04-10"],
                       ["2026-04-10", "2026-04-20"]):
                nd, va = _matriz(filas, columnas)
                resp += [{"crs": "EPSG:32630", "transform": TR},
                         {"buf": 90000.0, "todo": 100000.0}, ESQ,
                         {"features": [{"properties": {"fecha": f, "ndvi": nd,
                                                       "valido": va, "media": 0.6,
                                                       "crs": "EPSG:32630"}} for f in fs]}]
            G.ee = _EeRejilla(resp)
            return G.rellenar_rejillas("P")
        check("rejilla/relleno: baja las rejillas de TODAS las campanas anteriores",
              _relleno, lambda r: r[0] == 5)
        check("rejilla/relleno: quedan guardadas por campana",
              lambda: sorted({r["campana"] for r in DB.rejillas("P")}),
              lambda r: r == ["2023-2024", "2024-2025", "2025-2026"])
        check("rejilla/relleno: no vuelve a pedir lo que ya esta",
              lambda: (setattr(G, "ee", _EeRejilla([])), G.rellenar_rejillas("P"))[1],
              lambda r: r == (0, "todas las pasadas ya tienen su rejilla"))

        # ---- ESPACIO: el requisito era 1.5-2 KB por pasada en 5-10 ha
        check("rejilla/relleno: el gasto por pasada se mantiene en el presupuesto",
              lambda: DB.tamano_rejillas("P"),
              lambda r: r[0] == 5 and r[1] / r[0] <= 2048)
    finally:
        G.ee = orig


def pruebas_gee_cliente():
    import gee_cliente as G
    import almacen as DB

    def _pasada(fecha, cobertura, ndvi=0.55):
        return {"properties": {"fecha": fecha, "cobertura_valida": cobertura,
                               "ndvi": ndvi, "evi": 0.3, "savi": 0.4, "gndvi": 0.4,
                               "lai": 2.0, "msavi": 0.4, "ndmi": 0.2,
                               "ndvi_std": 0.05, "n_pixeles": 800}}

    d = tempfile.mkdtemp()
    DB.conectar(os.path.join(d, "gee.db"))
    DB.guardar_ficha("Parcela_EE", {"propietario": "x",
                                    "coordenadas": [[-4.1, 41.65], [-4.09, 41.65],
                                                    [-4.09, 41.66], [-4.1, 41.66]]})
    # dos pasadas: una con cobertura suficiente y otra por DEBAJO del umbral (0.80)
    falso = _EeFalso([_pasada("2026-03-01", 0.97), _pasada("2026-03-11", 0.42)])
    real_ee = G.ee
    try:
        G.ee = falso
        check("gee: con ee inyectado, hay_ee() es True", lambda: G.hay_ee(), lambda r: r is True)
        n, msg = G.sincronizar_parcela("Parcela_EE", "2025-2026")
        check("gee: solo se guarda la pasada con cobertura suficiente",
              lambda: (n, [p["fecha"] for p in DB.pasadas("Parcela_EE", "2025-2026")]),
              lambda r: r[0] == 1 and r[1] == ["2026-03-01"])
        check("gee: la pasada bajo el umbral se descarta y se dice por que",
              lambda: DB.pasadas("Parcela_EE", "2025-2026"),
              lambda ps: all(p["fecha"] != "2026-03-11" for p in ps))
        check("gee: la cobertura guardada se redondea a 3 decimales",
              lambda: DB.pasadas("Parcela_EE", "2025-2026")[0]["cobertura_valida"],
              lambda v: v == 0.97)
        # segunda vuelta: no duplica lo ya guardado
        check("gee: repetir la sincronizacion no duplica pasadas",
              lambda: (G.sincronizar_parcela("Parcela_EE", "2025-2026")[0],
                       len(DB.pasadas("Parcela_EE", "2025-2026"))),
              lambda r: r[0] == 0 and r[1] == 1)
        # sin geometria no se intenta nada
        DB.guardar_ficha("Sin_Geo", {"propietario": "x", "coordenadas": []})
        check("gee: parcela sin geometria -> no descarga",
              lambda: G.sincronizar_parcela("Sin_Geo", "2025-2026"),
              lambda r: r[0] == 0 and "geometria" in r[1])
    finally:
        G.ee = real_ee
    check("gee: sin ee disponible lo dice y no revienta",
          lambda: (setattr(G, "ee", None), G.sincronizar_parcela("Parcela_EE", "2025-2026"),
                   setattr(G, "ee", real_ee))[1],
          lambda r: r[0] == 0 and "earthengine" in r[1])
    # --- RADAR (Sentinel-1): misma descarga inyectable ---
    def _pasada_radar(fecha, vv, vh, n=60, orbita="ASCENDING"):
        return {"properties": {"fecha": fecha, "vv": vv, "vh": vh,
                               "vv_std": 1.2, "vh_std": 1.3, "n": n, "orbita": orbita}}
    DB.guardar_ficha("Radar_EE", {"propietario": "x",
                                  "coordenadas": [[-4.1, 41.65], [-4.09, 41.65],
                                                  [-4.09, 41.66], [-4.1, 41.66]]})
    falso_r = _EeFalso([_pasada_radar("2026-03-02", -9.0, -15.0),
                        _pasada_radar("2026-03-14", None, -14.0),      # sin VV: se descarta
                        _pasada_radar("2026-03-02", -8.0, -14.5)])     # dia repetido: no duplica
    real_ee = G.ee
    try:
        G.ee = falso_r
        n, _msg = G.sincronizar_radar("Radar_EE", "2025-2026")
        rad = DB.radar("Radar_EE", "2025-2026")
        check("gee radar: descarta la pasada sin VV y no duplica el mismo dia",
              lambda: (n, [p["fecha"] for p in rad]),
              lambda r: r[0] == 1 and r[1] == ["2026-03-02"])
        check("gee radar: guarda RVI con su rango de incertidumbre y la fiabilidad",
              lambda: rad[0],
              lambda p: (p["rvi"] is not None and p["rvi_lo"] <= p["rvi"] <= p["rvi_hi"]
                         and p["fiabilidad"] in ("alta", "media", "baja")))
        check("gee radar: conserva VV/VH redondeados y el nº de pixeles",
              lambda: rad[0],
              lambda p: p["vv"] == -9.0 and p["vh"] == -15.0 and p["n_pixeles"] == 60)
        check("gee radar: repetir no anade nada",
              lambda: G.sincronizar_radar("Radar_EE", "2025-2026")[0], lambda v: v == 0)
    finally:
        G.ee = real_ee
    check("gee radar: sin ee disponible lo dice y no revienta",
          lambda: (setattr(G, "ee", None), G.sincronizar_radar("Radar_EE", "2025-2026"),
                   setattr(G, "ee", real_ee))[1],
          lambda r: r[0] == 0 and "earthengine" in r[1])
    # el modulo de radar sigue siendo PURO: interpreta sin tocar red ni base de datos
    import sentinel1 as S1
    check("sentinel1: sigue siendo puro (sin ee ni almacen)",
          lambda: [n for n in ("ee", "DB") if hasattr(S1, n)], lambda r: r == [])

    # helper puro de dimensionado
    poli = [[-4.10, 41.650], [-4.093, 41.650], [-4.093, 41.654], [-4.10, 41.654]]
    check("gee: dimensiones_para respeta el tope de pixeles",
          lambda: G.dimensiones_para(poli, 1), lambda v: 64 <= v <= G.MAX_PIXELES)
    check("gee: a menos m/pixel, mas pixeles",
          lambda: (G.dimensiones_para(poli, 1), G.dimensiones_para(poli, 60)),
          lambda r: r[0] > r[1])
    check("gee: nunca baja de 64 pixeles por lado",
          lambda: G.dimensiones_para(poli, 10000), lambda v: v == 64)


# =====================================================================
# 15. RUTAS: los datos viven en el perfil del usuario, no en el cwd
# =====================================================================
def pruebas_rutas():
    import subprocess
    base = os.path.dirname(os.path.abspath(__file__))

    def _en_subproceso(codigo, entorno=None, cwd=None):
        env = dict(os.environ)
        env.pop("GESTOR_PARCELAS_DIR", None)
        env.update(entorno or {})
        r = subprocess.run([sys.executable, "-c",
                            f"import sys; sys.path.insert(0, {base!r})\n" + codigo],
                           capture_output=True, text=True, env=env, cwd=cwd or base)
        return r.stdout.strip()

    d = tempfile.mkdtemp()
    check("rutas: la variable de entorno manda",
          lambda: _en_subproceso("import rutas; print(rutas.directorio_datos())",
                                 {"GESTOR_PARCELAS_DIR": d}),
          lambda r: r == os.path.abspath(d))
    check("rutas: sin variable, cae en el perfil del usuario (no en el cwd)",
          lambda: _en_subproceso("import rutas, os; print(rutas.directorio_datos())"),
          lambda r: os.path.isabs(r) and r != os.getcwd())
    check("rutas: crea el directorio si no existe",
          lambda: _en_subproceso("import rutas, os; print(os.path.isdir(rutas.directorio_datos()))",
                                 {"GESTOR_PARCELAS_DIR": os.path.join(d, "nuevo", "hondo")}),
          lambda r: r == "True")
    check("rutas: ruta() cuelga del directorio de datos",
          lambda: _en_subproceso("import rutas; print(rutas.ruta('parcelas.db'))",
                                 {"GESTOR_PARCELAS_DIR": d}),
          lambda r: r == os.path.join(os.path.abspath(d), "parcelas.db"))
    # lo importante: el mismo fichero SE ENCUENTRA desde cualquier directorio
    d2 = tempfile.mkdtemp()
    otro = tempfile.mkdtemp()
    check("rutas: la BD es la MISMA arrancando desde otra carpeta",
          lambda: (_en_subproceso("import almacen; print(almacen.RUTA_DB)",
                                  {"GESTOR_PARCELAS_DIR": d2}, cwd=base),
                   _en_subproceso("import almacen; print(almacen.RUTA_DB)",
                                  {"GESTOR_PARCELAS_DIR": d2}, cwd=otro)),
          lambda r: r[0] == r[1] and r[0].startswith(os.path.abspath(d2)))
    # --- traslado, UNA sola vez, de la BD que estaba en el directorio de trabajo ---
    def _mudanza(preexiste_destino):
        viejo, nuevo = tempfile.mkdtemp(), tempfile.mkdtemp()
        prep = ("import almacen as DB\n"
                "DB.conectar('parcelas.db')\n"
                "DB.guardar_ficha('De_La_Vieja', {'propietario':'A','coordenadas':[[0,0],[0,1],[1,1]]})\n"
                "DB.cerrar()\n")
        if preexiste_destino:
            prep += (f"DB.conectar(os.path.join({nuevo!r}, 'parcelas.db'))\n"
                     "DB.guardar_ficha('De_La_Nueva', {'propietario':'B','coordenadas':[[0,0],[0,1],[1,1]]})\n"
                     "DB.cerrar()\n")
        _en_subproceso("import os\n" + prep + "print('ok')", cwd=viejo)
        salida = _en_subproceso(
            "import os, almacen as DB\n"
            "DB.conectar()\n"
            "print(DB.RUTA_DB)\n"
            "print(','.join(DB.nombres()))\n"
            "print(os.path.exists('parcelas.db'))\n",
            {"GESTOR_PARCELAS_DIR": nuevo}, cwd=viejo).splitlines()
        return {"bd": salida[0], "parcelas": salida[1], "queda_en_cwd": salida[2],
                "nuevo": os.path.abspath(nuevo)}

    check("mudanza: la BD del cwd se traslada y conserva los datos",
          lambda: _mudanza(False),
          lambda r: (r["bd"].startswith(r["nuevo"]) and r["parcelas"] == "De_La_Vieja"
                     and r["queda_en_cwd"] == "False"))
    check("mudanza: si ya hay BD en destino NO se pisa y la antigua se conserva",
          lambda: _mudanza(True),
          lambda r: (r["parcelas"] == "De_La_Nueva" and r["queda_en_cwd"] == "True"))

    # --- purga de la cache de mapas: borra PNG viejos, NUNCA datos ---
    import rutas as R
    import time as _t
    def _cache():
        c = tempfile.mkdtemp()
        viejo, nuevo = _t.time() - 60 * 86400, _t.time() - 2 * 86400
        for n, ts in (("mapa_viejo.png", viejo), ("MAPA_VIEJO2.PNG", viejo),
                      ("mapa_reciente.png", nuevo), ("parcelas.db", viejo),
                      ("config_credenciales.json", viejo), ("parcelas.log", viejo),
                      ("parcelas.db-wal", viejo)):
            f = os.path.join(c, n)
            open(f, "w").write("x")
            os.utime(f, (ts, ts))
        return c
    def _purgado():
        c = _cache()
        n = R.purgar_png_antiguos(c, dias=30)
        return n, sorted(os.listdir(c))
    check("cache: borra los PNG con mas dias de la cuenta (tambien .PNG)",
          _purgado, lambda r: r[0] == 2 and "mapa_viejo.png" not in r[1]
                              and "MAPA_VIEJO2.PNG" not in r[1])
    check("cache: conserva los PNG recientes",
          _purgado, lambda r: "mapa_reciente.png" in r[1])
    check("cache: NO borra datos aunque sean mas viejos (db, json, log, wal)",
          _purgado,
          lambda r: all(f in r[1] for f in ("parcelas.db", "config_credenciales.json",
                                            "parcelas.log", "parcelas.db-wal")))
    check("cache: dias=0 desactiva la purga",
          lambda: R.purgar_png_antiguos(_cache(), dias=0), lambda n: n == 0)
    check("cache: directorio inexistente -> 0 (no revienta)",
          lambda: R.purgar_png_antiguos(os.path.join(tempfile.mkdtemp(), "nada"), dias=30),
          lambda n: n == 0)

    # la cache no puede impedir el arranque: si no se puede crear la carpeta (aqui
    # se pone un FICHERO con ese nombre), el modulo tiene que importarse igual.
    d3 = tempfile.mkdtemp()
    open(os.path.join(d3, "cache_mapas"), "w").close()
    check("cache: si no se puede crear la carpeta, el modulo importa igual",
          lambda: _en_subproceso("import mapas_cache; print('ARRANCA')",
                                 {"GESTOR_PARCELAS_DIR": d3}),
          lambda r: r == "ARRANCA")
    check("cache: y el panel puede seguir pidiendo rutas de PNG",
          lambda: _en_subproceso("import mapas_cache as M; "
                                 "print(M.ruta_cache_mapa('P', 'NDVI', '2026-01-01', 10))",
                                 {"GESTOR_PARCELAS_DIR": d3}),
          lambda r: r.endswith("P_NDVI_2026-01-01_10m.png"))

    check("rutas: bitacora y credenciales tambien cuelgan de ahi",
          lambda: _en_subproceso(
              "import bitacora, credenciales; print(bitacora.RUTA_LOG); "
              "print(credenciales.ARCHIVO_CRED)", {"GESTOR_PARCELAS_DIR": d2}),
          lambda r: all(l.startswith(os.path.abspath(d2)) for l in r.splitlines()))


# =====================================================================
# 14. ESTADISTICA ESPACIAL POR PASADA (lectura de lo que ya venia del satelite)
# =====================================================================
def pruebas_estadisticas():
    from contraste_indices import estadisticas_pasada, texto_estadisticas
    r = {"fecha": "2026-04-15", "ndvi": 0.66, "ndvi_std": 0.099,
         "ndvi_p10": 0.52, "ndvi_p25": 0.58, "ndvi_p50": 0.66,
         "ndvi_p75": 0.72, "ndvi_p90": 0.78, "n_pixeles": 820, "cobertura_valida": 0.97}
    check("estadisticas: recoge media, desviacion y percentiles",
          lambda: estadisticas_pasada(r),
          lambda e: e["media"] == 0.66 and e["std"] == 0.099 and e["p50"] == 0.66)
    check("estadisticas: amplitud = p90 - p10",
          lambda: estadisticas_pasada(r)["amplitud"], lambda v: abs(v - 0.26) < 1e-9)
    check("estadisticas: cv = desviacion / media",
          lambda: estadisticas_pasada(r)["cv"], lambda v: abs(v - 0.15) < 0.01)
    check("estadisticas: pasada sin estadistica espacial -> None",
          lambda: estadisticas_pasada({"fecha": "x", "ndvi": 0.5}), lambda v: v is None)
    check("estadisticas: registro vacio -> None (no revienta)",
          lambda: estadisticas_pasada({}), lambda v: v is None)
    # no se inventan derivados si faltan los percentiles
    check("estadisticas: sin percentiles no hay amplitud",
          lambda: estadisticas_pasada({"ndvi": 0.5, "ndvi_std": 0.1}),
          lambda e: e is not None and "amplitud" not in e)
    # texto para la interpretacion
    check("texto estadistico: nombra media, desviacion y percentiles",
          lambda: texto_estadisticas(r),
          lambda t: "media 0.660" in t and "desviacion 0.099" in t and "mediana 0.66" in t)
    check("texto estadistico: incluye la lectura de uniformidad si se le pasa",
          lambda: texto_estadisticas(r, {"uniformidad": "parcela uniforme"}),
          lambda t: "parcela uniforme" in t)
    check("texto estadistico: sin estadistica -> None",
          lambda: texto_estadisticas({"ndvi": 0.5}), lambda t: t is None)
    # pasadas antiguas: solo p10/p50/p90; deben salir igualmente los que haya
    r3 = {"ndvi": 0.44, "ndvi_std": 0.16, "ndvi_p10": 0.22, "ndvi_p50": 0.47,
          "ndvi_p90": 0.62, "n_pixeles": 820}
    check("texto estadistico: muestra los percentiles disponibles (sin P25/P75)",
          lambda: texto_estadisticas(r3),
          lambda t: "P10 0.22" in t and "mediana 0.47" in t and "P90 0.62" in t
                    and "P25" not in t and "P75" not in t)


# =====================================================================
# 13. BITACORA: registra sin molestar y sin poder tumbar el programa
# =====================================================================
def pruebas_bitacora():
    import subprocess
    base = os.path.dirname(os.path.abspath(__file__))
    # a) registra en fichero y NO escribe en consola
    d = tempfile.mkdtemp()
    codigo = ("import sys; sys.path.insert(0, %r)\n"
              "import bitacora\n"
              "bitacora.log.warning('incidencia de prueba')\n") % base
    # el directorio de datos se fuerza con la variable de entorno (ver rutas.py)
    entorno = dict(os.environ, GESTOR_PARCELAS_DIR=d)
    r = subprocess.run([sys.executable, "-c", codigo], cwd=d,
                       capture_output=True, text=True, env=entorno)
    check("bitacora: no escribe nada en la consola del usuario",
          lambda: (r.stdout + r.stderr).strip(), lambda x: x == "")
    check("bitacora: deja la incidencia en parcelas.log",
          lambda: open(os.path.join(d, "parcelas.log"), encoding="utf-8").read(),
          lambda x: "incidencia de prueba" in x and "WARNING" in x)
    # b) si el log NO se puede escribir, el programa sigue (manejador nulo)
    d2 = tempfile.mkdtemp()
    os.mkdir(os.path.join(d2, "parcelas.log"))      # ocupar el nombre con una carpeta
    codigo2 = ("import sys; sys.path.insert(0, %r)\n"
               "import bitacora, logging\n"
               "bitacora.log.warning('no debe romper')\n"
               "print(type(bitacora.log.handlers[0]).__name__)\n") % base
    r2 = subprocess.run([sys.executable, "-c", codigo2], cwd=d2,
                        capture_output=True, text=True,
                        env=dict(os.environ, GESTOR_PARCELAS_DIR=d2))
    check("bitacora: sin poder escribir usa manejador nulo y no falla",
          lambda: (r2.returncode, r2.stdout.strip()),
          lambda x: x[0] == 0 and x[1] == "NullHandler")


# =====================================================================
# 12. GEOMETRIA (geo.py) y contratos de superficie_ha en cada llamador
# =====================================================================
def pruebas_geo():
    import geo
    sq = [[-4.10, 41.650], [-4.093, 41.650], [-4.093, 41.654], [-4.10, 41.654], [-4.10, 41.650]]
    check("geo: superficie de un cuadrado conocido (~25.87 ha)",
          lambda: geo.superficie_ha(sq), lambda r: abs(r - 25.868) < 0.05)
    check("geo: sin redondear (contrato del panel)",
          lambda: geo.superficie_ha(sq), lambda r: r != round(r, 2))
    check("geo: poligono invalido -> 0.0", lambda: geo.superficie_ha([[0, 0], [1, 1]]),
          lambda r: r == 0.0)
    # los llamadores conservan su contrato exacto
    import demo_sistema as D
    check("demo: superficie redondeada a 2 (== round(geo))",
          lambda: D.superficie_ha(sq), lambda r: r == round(geo.superficie_ha(sq), 2))
    # informe_anual es OPCIONAL: si se borra el fichero, estas comprobaciones se
    # omiten y la suite sigue verde (es lo que promete ARQUITECTURA.md §6).
    try:
        import informe_anual as IA
    except Exception:
        IA = None
    if IA is not None:
        check("informe: poligono invalido -> None (contrato propio)",
              lambda: IA._superficie_ha([[0, 0], [1, 1]]), lambda r: r is None)
        check("informe: valido -> round(geo, 2)",
              lambda: IA._superficie_ha(sq), lambda r: r == round(geo.superficie_ha(sq), 2))
    # modelo de cultivo (cultivo.py): mismo resultado en panel e informe
    import cultivo as CU
    cult = {"especie": "TRIGO", "fecha_siembra": "2025-11-10", "marco_calle": None, "marco_pie": None}
    check("cultivo: spec_de extrae especie y siembra",
          lambda: CU.spec_de(cult), lambda r: r and r["especie"] == "TRIGO" and r["fecha_siembra"] == "2025-11-10")
    check("cultivo: sin especie -> None", lambda: CU.spec_de({"tipo": "BARBECHO"}), lambda r: r is None)
    if IA is not None:
        check("cultivo: informe._spec_de == cultivo.spec_de (dedup)",
              lambda: IA._spec_de(cult), lambda r: r == CU.spec_de(cult))
    check("cultivo: clave_cultivo barbecho / normal",
          lambda: (CU.clave_cultivo("BARBECHO", ""), CU.clave_cultivo("LENOSO", "INTENSIVO")),
          lambda r: r == ("BARBECHO", "LENOSO_INTENSIVO"))


# =====================================================================
# 24. ESCALA DE LAS BANDAS: los indices, con numeros de verdad
# =====================================================================
# El agujero que dejo pasar el fallo de escala fue que TODAS las pruebas de
# interpretacion parten de diccionarios ya bien escalados ("ndvi": 0.55, "lai":
# 1.8). Se comprobaba el razonamiento dando por buena la entrada, y la entrada era
# justo lo que estaba mal. Aqui se entra un escalon mas abajo: bandas crudas tal
# como las entrega la coleccion, y se fija el numero que sale.
class _ImgNum:
    """Doble de `ee.Image` que SI CALCULA, sobre un unico pixel.

    A diferencia de `_EeFalso`, que se limita a devolverse a si mismo, este
    implementa las cuatro operaciones que usa `construir_indice` (`select`,
    `multiply`, `normalizedDifference`, `expression`) con aritmetica de Python.
    Asi se puede fijar el VALOR del indice, no solo que la cadena de llamadas no
    reviente. La formula de `expression` se evalua tal cual, que es lo que hace
    Earth Engine con esa misma cadena de texto.
    """
    def __init__(self, bandas, valor=None):
        self.bandas = dict(bandas)
        self.valor = valor            # resultado, cuando ya es un indice

    def select(self, b):
        if isinstance(b, (list, tuple)):
            return _ImgNum({k: self.bandas[k] for k in b})
        return _ImgNum({b: self.bandas[b]}, self.bandas[b])

    def multiply(self, k):
        return _ImgNum({n: v * k for n, v in self.bandas.items()},
                       None if self.valor is None else self.valor * k)

    def normalizedDifference(self, par):
        a, b = self.bandas[par[0]], self.bandas[par[1]]
        return _ImgNum({}, (a - b) / (a + b))

    def expression(self, formula, variables):
        ns = {n: (im.valor if isinstance(im, _ImgNum) else im)
              for n, im in variables.items()}
        ns["sqrt"] = math.sqrt
        return _ImgNum({}, eval(formula, {"__builtins__": {}}, ns))

    def rename(self, _n):
        return self


# Tres escenas con reflectancias de bibliografia, en [0,1]. Son las que se
# convierten a enteros de la coleccion para alimentar al codigo.
_ESCENAS = {
    "olivar":   {"B2": 0.05, "B3": 0.10, "B4": 0.09, "B8": 0.28, "B11": 0.20},
    "encanado": {"B2": 0.03, "B3": 0.09, "B4": 0.05, "B8": 0.45, "B11": 0.18},
    "desnudo":  {"B2": 0.13, "B3": 0.16, "B4": 0.19, "B8": 0.22, "B11": 0.28},
}

# VALORES DE ORO. Calculados a mano con las formulas sobre reflectancia. Si un
# cambio los mueve, o la formula ha cambiado o el escalado se ha vuelto a perder;
# en ninguno de los dos casos vale con actualizar el numero sin mirar por que.
_ORO = {
    "olivar":   {"NDVI": 0.5135, "EVI": 0.3287, "SAVI": 0.3276, "GNDVI": 0.4737,
                 "LAI": 1.0713, "MSAVI": 0.3021, "NDMI": 0.1667},
    "encanado": {"NDVI": 0.8000, "EVI": 0.6557, "SAVI": 0.6000, "GNDVI": 0.6667,
                 "LAI": 2.2545, "MSAVI": 0.6298, "NDMI": 0.4286},
    "desnudo":  {"NDVI": 0.0732, "EVI": 0.0542, "SAVI": 0.0495, "GNDVI": 0.1579,
                 "LAI": 0.0779, "MSAVI": 0.0429, "NDMI": -0.1200},
}

# Rango FISICO de cada indice: fuera de aqui el numero no es un indice mal
# calibrado, es un numero imposible.
_RANGO_FISICO = {
    "NDVI":  (-1.0, 1.0),      # cociente normalizado
    "GNDVI": (-1.0, 1.0),
    "NDMI":  (-1.0, 1.0),
    "EVI":   (-1.0, 1.0),      # con reflectancia valida no se sale de ahi
    "SAVI":  (-1.0, 1.5),      # el 1.5 es el factor (1+L) de la formula
    "MSAVI": (-1.0, 1.5),
    "LAI":   (0.0, 10.0),      # indice de area foliar: nunca negativo
}


def pruebas_escala_indices():
    import gee_cliente as G

    def cruda(refl):
        """La escena, en enteros de la coleccion (reflectancia / 0.0001)."""
        return _ImgNum({b: v / G.ESCALA_SR for b, v in refl.items()})

    def valor(refl, idx):
        return G.construir_indice(cruda(refl), idx).valor

    check("escala: la constante es la del catalogo (SR escalada por 10000)",
          lambda: G.ESCALA_SR, lambda r: r == 0.0001)

    # --- 1. VALORES DE ORO: el numero exacto de los siete indices ---
    for esc, refl in _ESCENAS.items():
        for idx in G.INDICES_ORDEN:
            check(f"indice {idx} sobre {esc}: vale {_ORO[esc][idx]:.4f}",
                  lambda r=refl, i=idx: valor(r, i),
                  lambda v, e=esc, i=idx: abs(v - _ORO[e][i]) < 5e-4)

    # --- 2. RANGO FISICO ---
    for esc, refl in _ESCENAS.items():
        for idx in G.INDICES_ORDEN:
            check(f"indice {idx} sobre {esc}: dentro de su rango fisico",
                  lambda r=refl, i=idx: valor(r, i),
                  lambda v, i=idx: _RANGO_FISICO[i][0] <= v <= _RANGO_FISICO[i][1])

    # --- 3. LOS RANGOS DE PINTADO CUBREN LO QUE SALE ---
    # Un rango de paleta por debajo de lo que el indice alcanza satura el mapa;
    # muy por encima lo deja plano. Se comprueba contra la escena mas verde.
    for idx in G.INDICES_ORDEN:
        check(f"paleta {idx}: el rango cubre la escena de dosel cerrado",
              lambda i=idx: (valor(_ESCENAS["encanado"], i), G.INDICES[i]["rango"]),
              lambda r: r[1][0] <= r[0] <= r[1][1])
    check("paleta: ningun rango triplica el valor de dosel cerrado (mapas planos)",
          lambda: [i for i in G.INDICES_ORDEN
                   if G.INDICES[i]["rango"][1] > 3 * abs(valor(_ESCENAS["encanado"], i))],
          lambda r: r == [])

    # --- 4. INVARIANZA DE ESCALA: los tres normalizados no se enteran ---
    # NDVI, GNDVI y NDMI dan lo MISMO con enteros que con reflectancia. Esto fija
    # que el arreglo no les ha cambiado el valor: su historico sigue valiendo.
    for idx in ("NDVI", "GNDVI", "NDMI"):
        for esc, refl in _ESCENAS.items():
            check(f"{idx} sobre {esc}: invariante de escala (mismo valor sin escalar)",
                  lambda r=refl, i=idx: (G.construir_indice(_ImgNum(r), i).valor,
                                         valor(r, i)),
                  lambda p: abs(p[0] - p[1]) < 1e-12)

    # --- 5. REGRESION: si se quita el escalado, se nota ---
    # Los cuatro indices con constante aditiva TIENEN que dar distinto sobre
    # enteros. Si esta prueba pasara a dar "igual", es que construir_indice ha
    # dejado de escalar y el fallo ha vuelto.
    for idx in ("SAVI", "EVI", "MSAVI", "LAI"):
        for esc, refl in _ESCENAS.items():
            check(f"{idx} sobre {esc}: sin escalar da otra cosa (deteccion de regresion)",
                  lambda r=refl, i=idx: (_sin_escalar(r, i), valor(r, i)),
                  lambda p: abs(p[0] - p[1]) > 0.01)
    # y en concreto, el valor inflado que se estaba guardando hasta ahora
    check("regresion: EVI sin escalar sobre olivar se salia del rango fisico (1.07)",
          lambda: _sin_escalar(_ESCENAS["olivar"], "EVI"),
          lambda v: abs(v - 1.0672) < 5e-4 and v > 1.0)
    check("regresion: MSAVI sin escalar sobre olivar daba 0.68 (umbral lenoso 0.26-0.38)",
          lambda: _sin_escalar(_ESCENAS["olivar"], "MSAVI"),
          lambda v: abs(v - 0.6785) < 5e-4)
    check("regresion: LAI sin escalar sobre olivar daba 3.74 (umbral lenoso 1.0-3.5)",
          lambda: _sin_escalar(_ESCENAS["olivar"], "LAI"),
          lambda v: abs(v - 3.7430) < 5e-4)

    # --- 6. EL UMBRAL DE BIBLIOGRAFIA AHORA DISPARA ---
    # Es el sentido agronomico de todo esto: con el indice bien, los umbrales de
    # fenologia_especies (que no se han tocado) caen dentro del rango del indice.
    import fenologia_especies as FE

    def _umbrales(clave):
        """Todos los valores de ese umbral en UMBRALES_LENOSO (especie/fase/regimen).

        Las fases sin hoja lo tienen a None: ahi no se mira el indice."""
        return [u[clave]
                for fases in FE.UMBRALES_LENOSO.values()
                for regs in fases.values()
                for u in regs.values()
                if u.get(clave) is not None]

    msavis = _umbrales("msavi_min")
    check("umbral: los msavi_min de bibliografia caen dentro del MSAVI real",
          lambda: (min(msavis), max(msavis), valor(_ESCENAS["desnudo"], "MSAVI"),
                   valor(_ESCENAS["encanado"], "MSAVI")),
          lambda r: r[2] < r[0] and r[1] < r[3])
    lais = _umbrales("lai_min")
    check("umbral: los lai_min de bibliografia caen dentro del LAI real",
          lambda: (min(lais), max(lais), valor(_ESCENAS["desnudo"], "LAI"),
                   valor(_ESCENAS["encanado"], "LAI")),
          lambda r: r[2] < r[0] and r[1] < r[3])


def _sin_escalar(refl, idx):
    """El indice como se calculaba ANTES: la formula directa sobre los enteros.

    No llama a `gee_cliente`; replica el codigo viejo a proposito, para que la
    prueba de regresion siga midiendo lo mismo aunque el modulo cambie."""
    import gee_cliente as G
    nir = refl["B8"] / G.ESCALA_SR
    red = refl["B4"] / G.ESCALA_SR
    blue = refl["B2"] / G.ESCALA_SR
    if idx == "SAVI":
        return ((nir - red) / (nir + red + 0.5)) * 1.5
    if idx == "MSAVI":
        return (2 * nir + 1 - math.sqrt((2 * nir + 1) ** 2 - 8 * (nir - red))) / 2
    evi = 2.5 * ((nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0))
    return evi if idx == "EVI" else 3.618 * evi - 0.118


# =====================================================================
# 26. LA LISTA DE PARCELAS (pura, compartida por las dos interfaces)
# =====================================================================
# Esto vivia dentro del `_refrescar` de Tkinter. Al portar la interfaz a Qt habria
# que haberlo copiado, y dos copias de la misma decision acaban divergiendo. Vive
# en `vista_parcelas` y se prueba sin pantalla, que es lo que permite cambiar de
# interfaz sin cambiar lo que la lista dice.
def pruebas_vista_parcelas():
    import vista_parcelas as VP
    from interpretacion_fenologica import evaluar_parcela

    fichas = {
        "La_Vega": {"propietario": "Ana", "superficie_ha": 12.4,
                    "cultivos_por_campana": {"2025-2026": {"tipo": "EXTENSIVO",
                                                           "subtipo": "COSECHA_GRANO",
                                                           "especie": "TRIGO",
                                                           "fecha_siembra": "2025-11-01"}}},
        "El_Olivar": {"propietario": "Luis", "superficie_ha": 5.0,
                      "cultivos_por_campana": {"2025-2026": {"tipo": "LENOSO",
                                                             "subtipo": "INTENSIVO",
                                                             "especie": "OLIVO",
                                                             "marco_calle": 6.0,
                                                             "marco_pie": 4.0}}},
        "Barbecho_Sur": {"propietario": "Ana", "superficie_ha": 30.0,
                         "cultivos_por_campana": {"2025-2026": {"tipo": "BARBECHO"}}},
        "Sin_Cultivo": {"propietario": "Marta", "superficie_ha": 1.0},
    }
    hist = {"La_Vega": [{"fecha": "2026-04-05", "ndvi": 0.72, "ndmi": 0.20, "lai": 3.3}],
            "El_Olivar": [{"fecha": "2026-04-05", "ndvi": 0.30, "msavi": 0.12, "lai": 0.9}]}

    def _filas(**kw):
        return VP.filas(fichas, hist, "2025-2026", evaluar_parcela, **kw)

    check("lista: hay una fila por parcela",
          lambda: len(_filas()), lambda r: r == 4)
    check("lista: el barbecho no recibe juicio de vigor",
          lambda: [f for f in _filas() if f["id"] == "Barbecho_Sur"][0],
          lambda f: f["estado"] == "N.A." and f["cultivo"] == "Barbecho" and not f["semaforo"])
    check("lista: una parcela sin cultivo en esa campana lo dice, no falla",
          lambda: [f for f in _filas() if f["id"] == "Sin_Cultivo"][0],
          lambda f: f["estado"] == "Sin asignar" and not f["semaforo"])
    check("lista: el cultivo se ensena con su nombre legible",
          lambda: [f["cultivo"] for f in _filas(orden="nombre")],
          lambda r: "Olivar intensivo" in r and "Extensivo (grano)" in r)
    check("lista: la superficie va formateada y con su valor para ordenar",
          lambda: [f for f in _filas() if f["id"] == "La_Vega"][0],
          lambda f: f["superficie"] == "12.40 ha" and f["_sup"] == 12.4)
    check("lista: el guion bajo del nombre no se ensena",
          lambda: [f["nombre"] for f in _filas()],
          lambda r: all("_" not in n for n in r))

    # --- filtro ---
    check("lista: la busqueda mira nombre Y propietario",
          lambda: (len(_filas(texto="olivar")), len(_filas(texto="ana")),
                   len(_filas(texto="zzz"))),
          lambda r: r == (1, 2, 0))
    check("lista: la busqueda no distingue mayusculas",
          lambda: len(_filas(texto="LA_VEGA")), lambda r: r == 1)

    # --- orden ---
    check("lista: por nombre, alfabetico",
          lambda: [f["nombre"] for f in _filas(orden="nombre")],
          lambda r: r == sorted(r, key=str.lower))
    check("lista: por superficie, de mayor a menor",
          lambda: [f["_sup"] for f in _filas(orden="superficie")],
          lambda r: r == sorted(r, reverse=True))
    check("lista: por estado, lo urgente primero",
          lambda: [VP.SEVERIDAD.get(f["estado"], 9) for f in _filas(orden="estado")],
          lambda r: r == sorted(r))
    check("lista: un criterio de orden desconocido no revienta, ordena por nombre",
          lambda: [f["nombre"] for f in _filas(orden="loquesea")],
          lambda r: r == [f["nombre"] for f in _filas(orden="nombre")])
    check("lista: los criterios anunciados son los que de verdad ordenan",
          lambda: [o for o in VP.ORDENES
                   if [f["id"] for f in _filas(orden=o)] == [f["id"] for f in _filas(orden="__no__")]
                   and o != "nombre"],
          lambda r: r == [])

    # --- resumen y bordes ---
    check("lista: el resumen cuenta por estado",
          lambda: VP.resumen(_filas()),
          lambda r: sum(r.values()) == 4 and r.get("N.A.") == 1 and r.get("Sin asignar") == 1)
    check("lista: sin parcelas no hay filas ni resumen, y no falla",
          lambda: (VP.filas({}, {}, "2025-2026", evaluar_parcela), VP.resumen([])),
          lambda r: r == ([], {}))
    check("lista: una parcela sin historico se juzga igual (sin dato, no excepcion)",
          lambda: [f for f in VP.filas({"Nueva": {"propietario": "x", "superficie_ha": 2,
                                                  "cultivos_por_campana": {
                                                      "2025-2026": {"tipo": "EXTENSIVO",
                                                                    "subtipo": "COSECHA_GRANO",
                                                                    "especie": "TRIGO"}}}},
                                       {}, "2025-2026", evaluar_parcela)][0],
          lambda f: f["estado"] and f["id"] == "Nueva")
    check("lista: solo llevan punto de color los estados que son un juicio",
          lambda: {f["estado"]: f["semaforo"] for f in _filas()},
          lambda r: all(v is (k in VP.CON_SEMAFORO) for k, v in r.items()))
    # la lista de Tk y la de Qt piden EXACTAMENTE lo mismo a este modulo
    check("lista: el panel de Tk usa este modulo y no una copia propia",
          lambda: open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "panel_gestion_parcelas.py"), encoding="utf-8").read(),
          lambda src: "VP.filas(" in src and "sev = {" not in src)


# =====================================================================
def main():
    for f in (pruebas_motor, pruebas_fenologia, pruebas_contraste,
              pruebas_cuaderno, pruebas_umbrales, pruebas_lenosos, pruebas_rejilla, pruebas_credenciales, pruebas_persistencia, pruebas_almacen,
              pruebas_sigpac, pruebas_radar, pruebas_panel_helpers,
              pruebas_informe_anual, _informe_anual_error, pruebas_geo, pruebas_bitacora, pruebas_estadisticas, pruebas_rutas, pruebas_gee_cliente, pruebas_rejilla_descarga,
              pruebas_rejilla_coherencia, pruebas_buffer_y_zonas,
              pruebas_escala_indices, pruebas_vista_parcelas):
        try:
            f()
        except Exception as e:
            _FALLA.append((f.__name__, f"error montando el grupo: {type(e).__name__}: {e}"))

    print("=" * 66)
    print(f"  PRUEBAS DEL SISTEMA   ·   PASA: {len(_PASA)}   FALLA: {len(_FALLA)}")
    print("=" * 66)
    for n in _PASA:
        print(f"  ok   {n}")
    for n, e in _FALLA:
        print(f"  XX   {n}  ->  {e}")
    print("-" * 66)
    if _FALLA:
        print(f"  {len(_FALLA)} prueba(s) FALLARON")
        return 1
    print(f"  Todas las pruebas pasan ({len(_PASA)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
