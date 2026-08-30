# -*- coding: utf-8 -*-
"""
vista_ficha.py
==============

La LOGICA de la ficha de parcela, sin nada de Tkinter. Decide QUE mostrar; la
clase `FichaParcela` (en `ui_ficha.py`) solo lo pinta.

Por que existe: esta tubería de decision -recortar la serie hasta la pasada
elegida, evaluar, afinar con el historial, dejar que la validacion propia mande,
y montar los contextos que consumen los dialogos- vivia dentro de un metodo de
DIBUJO (`_pintar_interp`, 127 lineas). Ahi no la veia la bateria de pruebas sin
pantalla, y fue justo donde se colo el fallo de que la cabecera y el texto
mostraban diagnosticos distintos. Sacada aqui, se prueba sin abrir una ventana.

Es puro salvo que LEE de la base (`almacen`), igual que el resto de la capa de
dominio; no escribe ni toca widgets. Las entidades viajan como `dict`, como en
todo el programa.
"""

from datetime import date

import almacen as DB
import registro_parcela as REG
import contraste_indices as CI
from interpretacion_fenologica import (evaluar_parcela, ajuste_por_validaciones,
                                       observaciones_del_agricultor)
from cultivo import spec_de
from gee_cliente import INDICES_ORDEN
from bitacora import log

try:
    import calibracion_umbrales as _CALIB
except Exception:
    _CALIB = None

try:
    import validacion as _VAL
except Exception:
    _VAL = None


def preparar_interpretacion(nombre, campana, regs, idx):
    """Decide que ensenar en el panel de interpretacion de UNA pasada.

    `regs` es el historico de la campana ordenado por fecha; `idx` es la pasada
    elegida (la lo calcula la ficha a partir del desplegable). Devuelve un dict con
    el diagnostico ya resuelto -historial y validacion propia aplicados-, los
    contextos de validacion (`val_ctx`, `idx_ctx`) y el encabezado de texto ya
    montado. Si no hay pasadas, `{"vacio": True}`.

    No toca Tk. La ficha se limita a pintar `encabezado`, sincronizar la casilla
    de heterogeneidad con `hetero_on` y, si no es barbecho ni hay cache, lanzar la
    interpretacion larga con los campos que aqui se devuelven."""
    if not regs:
        return {"vacio": True}

    # Para juzgar un dia anterior hay que dar al motor la serie HASTA ese dia: con
    # la serie entera, las variaciones se calcularian contra pasadas del futuro.
    regs = regs[:idx + 1]
    actual = regs[-1]

    ficha = DB.ficha(nombre) or {}
    cult = (ficha.get("cultivos_por_campana", {}) or {}).get(campana, {})
    tipo, sub = cult.get("tipo", "BARBECHO"), cult.get("subtipo", "")
    spec = spec_de(cult)
    hetero_on = ficha.get("heterogeneidad", True)
    arbolado = bool(ficha.get("arbolado"))

    eventos_cerca = REG.eventos_cercanos(nombre, campana, actual.get("fecha", ""),
                                         ventana_dias=20)

    # diagnostico fenologico. `parcela` aplica los umbrales que el usuario calibro;
    # `arbolado` enmascara las encinas para juzgar el cultivo, no los arboles.
    diag = evaluar_parcela(tipo, sub, regs, eventos_cerca=eventos_cerca, spec=spec,
                           parcela=nombre, heterogeneidad_activa=hetero_on, arbolado=arbolado)
    # El CRUDO, no el que se ensena. El semaforo puede estar reteniendo un cambio a
    # la espera de la segunda pasada (ver `interpretacion_fenologica`, persistencia),
    # y eso es una decision de PRESENTACION. Si el aprendizaje mirase el estado
    # retenido, estaria aprendiendo del filtro en vez de del cultivo: el usuario
    # corregiria un veredicto que el motor no ha emitido.
    estado_bruto = diag.get("estado_crudo", diag["estado"])
    cultivo_id = f"{tipo}/{sub}" + (f"/{spec['especie']}" if spec and spec.get("especie") else "")

    # «Revisar datos» NO es un juicio agronomico: dice que lo declarado no cuadra
    # con lo observado. Dejarlo entrar en el aprendizaje seria pedirle al usuario
    # que valide como "correcto o incorrecto" un aviso sobre SUS PROPIOS datos, y
    # ensenarle al motor umbrales a partir de una parcela mal declarada.
    from interpretacion_fenologica import ESTADO_DATOS as _ED
    revisar_datos = (estado_bruto == _ED)

    historial = DB.validaciones_recientes(limite=300)
    # aprendizaje de campanas anteriores: lo de ESTA parcela manda; si no, el cultivo
    aj = {} if revisar_datos else ajuste_por_validaciones(
        cultivo_id, diag.get("fase"), estado_bruto, historial, parcela=nombre)
    if aj.get("corregido"):
        diag["estado"] = aj["corregido"]

    # validacion propia de esta pasada: lo que TU dijiste manda sobre lo mostrado
    fase_sistema = diag.get("fase")        # la del motor: se guarda para aprender
    val_actual = DB.validacion_de(nombre, campana, actual.get("fecha"))
    nota_usuario = None
    if val_actual:
        if val_actual.get("veredicto") == "incorrecto" and val_actual.get("estado_real"):
            diag["estado"] = val_actual["estado_real"]
            nota_usuario = (f"Corregido por ti a '{val_actual['estado_real']}' "
                            f"(el sistema decia '{estado_bruto}'). El programa lo recuerda.")
        elif val_actual.get("veredicto") == "correcto":
            nota_usuario = f"Confirmado por ti como '{estado_bruto}'."
        # FASE corregida a mano: manda sobre la mostrada, igual que el estado. La
        # fase del sistema se conserva en val_ctx para que el aprendizaje sea coherente.
        fase_real = (val_actual.get("fase_real") or "").strip()
        if fase_real and fase_real != (fase_sistema or ""):
            diag["fase"] = fase_real
            nota_usuario = (nota_usuario or "") + (
                f"  Fase corregida por ti a «{fase_real}» "
                f"(el calendario decia «{fase_sistema or '?'}»).")
        obs_txt = (val_actual.get("nota") or "").strip()
        if obs_txt:
            nota_usuario = (nota_usuario or "") + f"  Tu observacion: “{obs_txt}”."

    # sin contexto de validacion: no se ofrece validar un aviso de datos
    val_ctx = None if revisar_datos else {
        "fecha": actual.get("fecha"), "fase": fase_sistema,
        "estado": estado_bruto, "cultivo": cultivo_id}
    idx_ctx = None
    if _CALIB is not None and not revisar_datos:
        idx_ctx = {
            "fecha": actual.get("fecha"), "fase": diag.get("fase"),
            "especie": (spec or {}).get("especie", ""),
            # la variedad acota lo que se valida: lo dicho de una variedad no
            # mueve los umbrales de otra ni los de la especie a secas
            "variedad": (spec or {}).get("variedad", ""),
            "lecturas": _CALIB.lectura_de_pasada(actual, diag.get("umbrales") or {},
                                                 INDICES_ORDEN),
            "umbrales": diag.get("umbrales") or {}}

    encabezado = _encabezado(diag, actual, aj, nota_usuario, cultivo_id, historial, nombre)

    return {
        "vacio": False,
        "regs": regs, "actual": actual,
        "tipo": tipo, "sub": sub, "spec": spec,
        "hetero_on": hetero_on,
        "arbolado": arbolado,
        "eventos_cerca": eventos_cerca,
        "estado": diag["estado"], "estado_bruto": estado_bruto,
        "fase": diag.get("fase"), "cultivo_id": cultivo_id, "diag": diag,
        "val_ctx": val_ctx, "idx_ctx": idx_ctx,
        "encabezado": encabezado,
        "es_barbecho": tipo == "BARBECHO",
        "motivo": diag.get("motivo", ""),
        "interpretacion_cache": actual.get("interpretacion"),
    }


def _iso_a_dia(iso):
    try:
        a, m, d = (iso or "").split("-")
        return date(int(a), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _pasada_cercana(regs, iso):
    """La pasada mas cercana en el tiempo a una fecha ISO (o None). Empareja la
    observacion de campo con el satelite: el dia exacto casi nunca coincide."""
    obj = _iso_a_dia(iso)
    if not obj or not regs:
        return None
    mejor, mejor_d = None, None
    for r in regs:
        d = _iso_a_dia(r.get("fecha", ""))
        if not d:
            continue
        dist = abs((d - obj).days)
        if mejor_d is None or dist < mejor_d:
            mejor, mejor_d = r, dist
    return mejor


def _fase_sistema(nombre, campana, regs, iso):
    """La fase que el sistema daria para la pasada mas cercana a `iso`. Es la
    prediccion ORIGINAL del motor (sin correcciones a mano): con ella se mide,
    para no examinarse con las respuestas. None si no se puede calcular."""
    obj = _iso_a_dia(iso)
    if not obj or not regs:
        return None
    # indice de la pasada mas cercana; el motor necesita la serie HASTA ese dia
    idx, mejor_d = None, None
    for i, r in enumerate(regs):
        d = _iso_a_dia(r.get("fecha", ""))
        if not d:
            continue
        dist = abs((d - obj).days)
        if mejor_d is None or dist < mejor_d:
            idx, mejor_d = i, dist
    if idx is None:
        return None
    ficha = DB.ficha(nombre) or {}
    cult = (ficha.get("cultivos_por_campana", {}) or {}).get(campana, {})
    tipo, sub = cult.get("tipo", "BARBECHO"), cult.get("subtipo", "")
    if tipo == "BARBECHO":
        return None
    spec = spec_de(cult)
    diag = evaluar_parcela(tipo, sub, regs[:idx + 1], spec=spec, parcela=nombre,
                           heterogeneidad_activa=ficha.get("heterogeneidad", True),
                           arbolado=bool(ficha.get("arbolado")))
    return diag.get("fase")


def resumen_validacion(nombre):
    """Puntua el sistema contra las OBSERVACIONES DE CAMPO de la parcela.

    Empareja lo observado con lo que el sistema predijo -la prediccion original,
    nunca la corregida a mano- y llama al modulo `validacion` para las metricas.
    Cuatro emparejamientos:
      fase        fase observada  vs  fase del motor en la pasada mas cercana
      rendimiento kg/ha medidos   vs  NDVI maximo de la campana (predictor clasico)
      dron        NDVI/NDRE de vuelo vs  el mismo indice del satelite mas cercano
      humedad     (pendiente de modelo de suelo; se guarda pero aun no se empareja)

    Robusto: nunca lanza. Devuelve dict con la lista de observaciones y, si el
    modulo `validacion` esta y hay pares, el informe y su texto. Sin modulo o sin
    datos, `informe`/`texto` van vacios pero las observaciones se listan igual."""
    try:
        obs = DB.observaciones(nombre)
    except Exception:
        log.debug("no se pudieron leer las observaciones de campo", exc_info=True)
        obs = []
    base = {"observaciones": obs, "n_obs": len(obs), "informe": None, "texto": ""}
    if not obs or _VAL is None:
        return base

    # regs por campana, una sola vez (varias observaciones comparten campana)
    regs_cache = {}
    def _regs(campana):
        if campana not in regs_cache:
            try:
                regs_cache[campana] = sorted(DB.pasadas(nombre, campana),
                                             key=lambda r: r.get("fecha", ""))
            except Exception:
                regs_cache[campana] = []
        return regs_cache[campana]

    pares_fase, pares_rend, pares_dron = [], [], []
    for o in obs:
        camp = o.get("campana", "")
        fecha = o.get("fecha", "")
        regs = _regs(camp)
        # FASE observada vs fase del motor
        if o.get("fase_obs"):
            try:
                fsis = _fase_sistema(nombre, camp, regs, fecha)
                if fsis:
                    pares_fase.append((fsis, o["fase_obs"]))
            except Exception:
                log.debug("no se pudo emparejar la fase observada", exc_info=True)
        # RENDIMIENTO medido vs NDVI maximo de la campana
        if o.get("rendimiento_kg_ha") is not None:
            ndvis = [r.get("ndvi") for r in regs if r.get("ndvi") is not None]
            if ndvis:
                pares_rend.append((max(ndvis), o["rendimiento_kg_ha"]))
        # DRON vs satelite (mismo indice, pasada mas cercana)
        if o.get("valor_dron") is not None and o.get("indice_dron"):
            r = _pasada_cercana(regs, fecha)
            if r is not None:
                sat = r.get(o["indice_dron"].lower())
                if sat is not None:
                    pares_dron.append((sat, o["valor_dron"]))

    inf = _VAL.informe(pares_fase=pares_fase, pares_rend=pares_rend)
    # el dron valida satelite<->dron: va como su propio bloque de regresion
    if pares_dron:
        inf["dron"] = _VAL.regresion(pares_dron)
    base["informe"] = inf
    partes = [t for t in (_VAL.texto(inf),) if t]
    if pares_dron and inf.get("dron") and inf["dron"].get("r2") is not None:
        d = inf["dron"]
        partes.append(f"Dron↔satélite: R²={d['r2']:.2f}, error {d['rmse']:.3f}, n={d['n']}")
    base["texto"] = "\n".join(partes)
    return base


def _encabezado(diag, actual, aj, nota_usuario, cultivo_id, historial, nombre):
    """El bloque de texto de cabecera: estado, fase, cubierta, estadistica de la
    pasada, notas de aprendizaje y las observaciones que la persona dejo antes."""
    cab = f"[{diag['estado']}]  Fase: {diag['fase']}"
    c = diag.get("cubierta")
    if c and c["señales"] >= 2:
        cab += f"  ·  Cubierta: {c['hipotesis_preliminar']} ({c['señales']}/4)"
    lineas = [cab]

    txt_est = CI.texto_estadisticas(actual, diag.get("heterogeneidad"))
    if txt_est:
        lineas.append("📊 " + txt_est)
    if aj.get("nota"):
        lineas.append("🧠 " + aj["nota"])
    if nota_usuario:
        lineas.append("🧠 " + nota_usuario)

    # lo que la PERSONA dijo antes en este cultivo/fase (haya o no ChatGPT)
    obs_prev = [o for o in observaciones_del_agricultor(cultivo_id, diag.get("fase"),
                                                        historial, parcela=nombre)
                if o.get("fecha") != actual.get("fecha")]
    if obs_prev:
        lineas.append("🗣️ Segun tus validaciones anteriores:")
        for o in obs_prev:
            lineas.append(f"   • [{o.get('estado', '?')}] {o['nota']}")
    return "\n".join(lineas) + "\n\n"
