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

import almacen as DB
import registro_parcela as REG
import contraste_indices as CI
from interpretacion_fenologica import (evaluar_parcela, ajuste_por_validaciones,
                                       observaciones_del_agricultor)
from cultivo import spec_de
from gee_cliente import INDICES_ORDEN

try:
    import calibracion_umbrales as _CALIB
except Exception:
    _CALIB = None


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

    eventos_cerca = REG.eventos_cercanos(nombre, campana, actual.get("fecha", ""),
                                         ventana_dias=20)

    # diagnostico fenologico. `parcela` aplica los umbrales que el usuario calibro.
    diag = evaluar_parcela(tipo, sub, regs, eventos_cerca=eventos_cerca, spec=spec,
                           parcela=nombre, heterogeneidad_activa=hetero_on)
    estado_bruto = diag["estado"]          # el que produce el motor (base del aprendizaje)
    cultivo_id = f"{tipo}/{sub}" + (f"/{spec['especie']}" if spec and spec.get("especie") else "")

    historial = DB.validaciones_recientes(limite=300)
    # aprendizaje de campanas anteriores: lo de ESTA parcela manda; si no, el cultivo
    aj = ajuste_por_validaciones(cultivo_id, diag.get("fase"), estado_bruto, historial,
                                 parcela=nombre)
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

    val_ctx = {"fecha": actual.get("fecha"), "fase": fase_sistema,
               "estado": estado_bruto, "cultivo": cultivo_id}
    idx_ctx = None
    if _CALIB is not None:
        idx_ctx = {
            "fecha": actual.get("fecha"), "fase": diag.get("fase"),
            "especie": (spec or {}).get("especie", ""),
            "lecturas": _CALIB.lectura_de_pasada(actual, diag.get("umbrales") or {},
                                                 INDICES_ORDEN),
            "umbrales": diag.get("umbrales") or {}}

    encabezado = _encabezado(diag, actual, aj, nota_usuario, cultivo_id, historial, nombre)

    return {
        "vacio": False,
        "regs": regs, "actual": actual,
        "tipo": tipo, "sub": sub, "spec": spec,
        "hetero_on": hetero_on,
        "eventos_cerca": eventos_cerca,
        "estado": diag["estado"], "estado_bruto": estado_bruto,
        "fase": diag.get("fase"), "cultivo_id": cultivo_id, "diag": diag,
        "val_ctx": val_ctx, "idx_ctx": idx_ctx,
        "encabezado": encabezado,
        "es_barbecho": tipo == "BARBECHO",
        "motivo": diag.get("motivo", ""),
        "interpretacion_cache": actual.get("interpretacion"),
    }


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
