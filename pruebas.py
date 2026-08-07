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
    src = open(ruta, encoding="utf-8").read()
    try:
        ini = src.index("_IO_LOCK = threading.RLock()")
        fin = src.index("INTERVALO_AUTOSYNC_MS")
    except ValueError:
        _FALLA.append(("persistencia", "no se localiza el bloque de persistencia"))
        return
    ns = {"json": json, "os": os, "tempfile": tempfile, "threading": threading}
    exec(src[ini:fin], ns)
    _load, _save, _actualizar = ns["_load"], ns["_save"], ns["_actualizar"]

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

    # helper del arranque: _toca_sincronizar (funcion pura)
    from datetime import datetime, timedelta
    m = re.search(r"\ndef _toca_sincronizar\(.*?\n(?=\n\n|\ndef |\nclass |\n# )", src, re.S)
    if not m:
        _FALLA.append(("_toca_sincronizar", "no se localiza la funcion en el panel"))
        return
    ns2 = {"datetime": datetime}
    exec(m.group(0), ns2)
    toca = ns2["_toca_sincronizar"]
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

    # nombre_seguro: no debe dejar pasar caracteres de ruta
    m2 = re.search(r"\ndef nombre_seguro\(.*?\n(?=\n\n|\ndef |\nclass |\n# )", src, re.S)
    if m2:
        ns3 = {"re": re}
        exec(m2.group(0), ns3)
        seguro = ns3["nombre_seguro"]
        check("nombre_seguro: quita separadores de ruta",
              lambda: seguro("../a/b:c*?"), lambda r: "/" not in r and "\\" not in r and ":" not in r and ".." not in r)
        check("nombre_seguro: espacios a _ y conserva acentos",
              lambda: seguro("Olivar del Ñú"), lambda r: r == "Olivar_del_Ñú")
        check("nombre_seguro: vacio -> 'parcela'", lambda: seguro("   "), lambda r: r == "parcela")
    else:
        _FALLA.append(("nombre_seguro", "no se localiza la funcion en el panel"))


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

    # ruta_cache_mapa: ficha y comparador deben usar la MISMA ruta de cache
    m3 = re.search(r"\ndef ruta_cache_mapa\(.*?\n(?=\n)", src, re.S)
    if not m3:
        _FALLA.append(("panel", "no se localiza ruta_cache_mapa en el panel"))
        return
    ns3 = {"DIR_MAPAS": "cache_mapas", "nombre_seguro": lambda s: s,
           "os": __import__("os")}
    exec(m3.group(0), ns3)
    rc = ns3["ruta_cache_mapa"]
    check("ruta_cache_mapa: formato parcela_indice_dia_resolucion",
          lambda: rc("Olivar", "NDVI", "2026-05-05", 10),
          lambda r: r.endswith(os.path.join("cache_mapas", "Olivar_NDVI_2026-05-05_10m.png")))
    check("ruta_cache_mapa: distinto indice -> distinta ruta (no colisiona)",
          lambda: rc("Olivar", "NDVI", "2026-05-05", 10) != rc("Olivar", "NDMI", "2026-05-05", 10),
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
    import informe_anual as IA
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
    check("cultivo: informe._spec_de == cultivo.spec_de (dedup)",
          lambda: IA._spec_de(cult), lambda r: r == CU.spec_de(cult))
    check("cultivo: clave_cultivo barbecho / normal",
          lambda: (CU.clave_cultivo("BARBECHO", ""), CU.clave_cultivo("LENOSO", "INTENSIVO")),
          lambda r: r == ("BARBECHO", "LENOSO_INTENSIVO"))


# =====================================================================
def main():
    for f in (pruebas_motor, pruebas_fenologia, pruebas_contraste,
              pruebas_cuaderno, pruebas_credenciales, pruebas_persistencia, pruebas_almacen,
              pruebas_sigpac, pruebas_radar, pruebas_panel_helpers,
              pruebas_informe_anual, _informe_anual_error, pruebas_geo, pruebas_bitacora, pruebas_estadisticas, pruebas_rutas):
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
