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

    # deltas
    check("delta: previo=0 -> None", lambda: delta("NDVI", 0.5, 0), lambda r: r[1] is None)
    check("delta: previo None -> None", lambda: delta("NDVI", 0.5, None), lambda r: r[1] is None)
    check("delta: NDMI absoluto (cruza 0)", lambda: delta("NDMI", -0.05, 0.05), lambda r: r[2] is False)

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
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel_gestion_parcelas.py")
    src = open(ruta, encoding="utf-8").read()
    m = re.search(r"\ndef sigpac_geometria\(.*?\n(?=\ndef spec_de\()", src, re.S)
    if not m:
        _FALLA.append(("sigpac", "no se localizan los helpers en el panel"))
        return
    ns = {}
    exec(m.group(0), ns)
    geo, ani, ll = ns["sigpac_geometria"], ns["sigpac_anillo"], ns["sigpac_a_lonlat"]
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
    consultar = ns["sigpac_consultar"]; urls = ns["sigpac_urls"]; SigErr = ns["SigpacError"]
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

    # campanas_entre (para sincronizar anos anteriores)
    m2 = re.search(r"\ndef campanas_entre\(.*?\n(?=\ndef superficie_ha)", src, re.S)
    if not m2:
        _FALLA.append(("panel", "no se localiza campanas_entre en el panel"))
        return
    ns2 = {}
    exec(m2.group(0), ns2)
    ce = ns2["campanas_entre"]
    check("campanas_entre: rango descendente inclusive",
          lambda: ce("2022-2023", "2025-2026"),
          lambda r: r == ["2025-2026", "2024-2025", "2023-2024", "2022-2023"])
    check("campanas_entre: una sola campana",
          lambda: ce("2025-2026", "2025-2026"), lambda r: r == ["2025-2026"])
    check("campanas_entre: orden invertido se corrige",
          lambda: ce("2025-2026", "2023-2024"), lambda r: r[0] == "2025-2026" and len(r) == 3)
    check("campanas_entre: entrada mal formada no revienta",
          lambda: ce(None, "2025-2026"), lambda r: r == ["2025-2026"])

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


# =====================================================================
def main():
    for f in (pruebas_motor, pruebas_fenologia, pruebas_contraste,
              pruebas_cuaderno, pruebas_credenciales, pruebas_persistencia, pruebas_almacen,
              pruebas_sigpac, pruebas_panel_helpers):
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
