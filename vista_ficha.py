# -*- coding: utf-8 -*-
"""
vista_ficha.py
==============

Lo que la FICHA de una parcela tiene que decir, sin decidir COMO se pinta. Sin
Tkinter y sin Qt: recibe la serie de pasadas y devuelve texto y numeros listos
para volcar en widgets.

POR QUE ESTA APARTE
-------------------
Esto vivia dentro de `FichaParcela._pintar_interp`, 100 lineas donde se mezclaban
el diagnostico, el aprendizaje por validaciones, la correccion que el usuario haya
hecho de ESA pasada y las llamadas a Tk. Al portar la ficha a Qt habria que
haberlo copiado, y una copia del ENCABEZADO DE LA INTERPRETACION es lo peor que se
puede duplicar: es lo que el agricultor lee para decidir si va a la finca. Dos
copias acabarian diciendo cosas distintas del mismo dia.

Aqui vive una vez, la usan las dos interfaces y se prueba sin pantalla.

QUE NO HACE
-----------
No pide la interpretacion larga a ChatGPT: eso es lento y va en un hilo, y cada
interfaz sabe como volver a su hilo principal. Aqui se prepara todo lo demas y se
deja dicho que texto cacheado hay, si lo hay.
"""

from typing import Any, Dict, List, Optional

import almacen as DB
import contraste_indices as CI
import registro_parcela as REG
from cultivo import spec_de
from interpretacion_fenologica import (evaluar_parcela, ajuste_por_validaciones,
                                       observaciones_del_agricultor, ambito_parcela)

# Estados que el usuario puede elegir al corregir un diagnostico.
ESTADOS_VALIDABLES = ["OK", "Vigilar", "Revisar", "Segado", "N.A."]

VENTANA_EVENTOS_DIAS = 20      # cuanto mira alrededor de la pasada en el cuaderno


def indice_pasada(regs: List[Dict[str, Any]], elegido: Optional[int]) -> int:
    """Posicion de la pasada que se interpreta. Por defecto, la ultima.

    Si el usuario habia elegido otra, se respeta mientras siga existiendo: al
    sincronizar entran pasadas nuevas y la lista crece."""
    if not regs:
        return -1
    if elegido is None or not (0 <= elegido < len(regs)):
        return len(regs) - 1
    return elegido


def contexto(nombre: str, campana: str, regs: List[Dict[str, Any]],
             elegido: Optional[int] = None, calib=None,
             indices: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Todo lo que la ficha necesita saber de la pasada elegida.

    Devuelve None si no hay pasadas. Las claves del resultado:

        idx, actual        cual es la pasada y sus datos
        diag               lo que dice el motor (fase, estado, motivo, umbrales...)
        estado_bruto       el estado ANTES de aplicar aprendizaje y validaciones;
                           es el que se guarda al validar, para aprender coherente
        estado             el que se ensena (bruto + aprendizaje + tu correccion)
        encabezado         las lineas de cabecera, ya redactadas
        cacheado           interpretacion larga ya guardada de ese dia, o None
        val_ctx / idx_ctx  contexto para los dos dialogos de validacion
        tipo, sub, spec, eventos_cerca, aprendizaje  lo que hace falta para pedir
                           la interpretacion larga sin volver a calcularlo

    `calib` es el modulo opcional `calibracion_umbrales` (o None si se borro) e
    `indices` la lista de indices en su orden. Los dos se INYECTAN: el primero
    para no depender de una pieza extraible, el segundo para no importar
    `gee_cliente`, que arrastra `ee` y no tiene sitio en un modulo de logica.
    """
    if not regs:
        return None
    idx = indice_pasada(regs, elegido)
    # Para juzgar un dia anterior hay que dar al motor la serie HASTA ese dia: con
    # la serie entera, las variaciones se calcularian contra pasadas del futuro.
    hasta = regs[:idx + 1]
    actual = hasta[-1]

    ficha = DB.ficha(nombre) or {}
    cult = (ficha.get("cultivos_por_campana") or {}).get(campana, {}) or {}
    tipo, sub = cult.get("tipo", "BARBECHO"), cult.get("subtipo", "")
    spec = spec_de(cult)
    hetero_on = ficha.get("heterogeneidad", True)

    eventos_cerca = REG.eventos_cercanos(nombre, campana, actual.get("fecha", ""),
                                         ventana_dias=VENTANA_EVENTOS_DIAS)
    diag = evaluar_parcela(tipo, sub, hasta, eventos_cerca=eventos_cerca, spec=spec,
                           parcela=nombre, heterogeneidad_activa=hetero_on)
    estado_bruto = diag["estado"]
    cultivo_id = f"{tipo}/{sub}" + (f"/{spec['especie']}" if spec and spec.get("especie") else "")

    historial = DB.validaciones_recientes(limite=300)
    # lo aprendido en ESTA parcela manda; si no hay, se usa lo del cultivo
    aj = ajuste_por_validaciones(cultivo_id, diag.get("fase"), estado_bruto, historial,
                                 parcela=nombre)
    if aj.get("corregido"):
        diag["estado"] = aj["corregido"]

    # lo que TU dijiste de ESTA pasada manda sobre lo mostrado
    val_actual = DB.validacion_de(nombre, campana, actual.get("fecha"))
    nota_usuario = None
    if val_actual:
        if val_actual.get("veredicto") == "incorrecto" and val_actual.get("estado_real"):
            diag["estado"] = val_actual["estado_real"]
            nota_usuario = (f"Corregido por ti a '{val_actual['estado_real']}' "
                            f"(el sistema decia '{estado_bruto}'). El programa lo recuerda.")
        elif val_actual.get("veredicto") == "correcto":
            nota_usuario = f"Confirmado por ti como '{estado_bruto}'."
        obs = (val_actual.get("nota") or "").strip()
        if obs:
            nota_usuario = (nota_usuario or "") + f"  Tu observacion: “{obs}”."

    idx_ctx = None
    if calib is not None and indices:
        idx_ctx = {"fecha": actual.get("fecha"), "fase": diag.get("fase"),
                   "especie": (spec or {}).get("especie", ""),
                   "lecturas": calib.lectura_de_pasada(actual, diag.get("umbrales") or {},
                                                       indices),
                   "umbrales": diag.get("umbrales") or {}}

    return {
        "idx": idx, "actual": actual, "serie_hasta": hasta,
        "diag": diag, "estado": diag["estado"], "estado_bruto": estado_bruto,
        "tipo": tipo, "sub": sub, "spec": spec, "cultivo_id": cultivo_id,
        "hetero_on": bool(hetero_on),
        "eventos_cerca": eventos_cerca,
        "encabezado": encabezado(nombre, diag, actual, aj, nota_usuario,
                                 cultivo_id, historial),
        "cacheado": actual.get("interpretacion"),
        "aprendizaje": DB.validaciones_recientes(limite=8, cultivo=cultivo_id),
        "val_ctx": {"fecha": actual.get("fecha"), "fase": diag.get("fase"),
                    "estado": estado_bruto, "cultivo": cultivo_id},
        "idx_ctx": idx_ctx,
    }


def encabezado(nombre: str, diag: Dict[str, Any], actual: Dict[str, Any],
               aj: Dict[str, Any], nota_usuario: Optional[str],
               cultivo_id: str, historial: List[Dict[str, Any]]) -> str:
    """Las lineas de cabecera de la interpretacion, ya redactadas.

    Orden deliberado: primero el juicio, luego lo que se ve en la parcela, luego
    lo que el programa ha aprendido, y al final lo que dijo la persona. De lo mas
    automatico a lo mas humano."""
    cab = f"[{diag['estado']}]  Fase: {diag['fase']}"
    c = diag.get("cubierta")
    if c and c.get("señales", 0) >= 2:
        cab += f"  ·  Cubierta: {c['hipotesis_preliminar']} ({c['señales']}/4)"
    lineas = [cab]
    txt_est = CI.texto_estadisticas(actual, diag.get("heterogeneidad"))
    if txt_est:
        lineas.append("📊 " + txt_est)
    if aj.get("nota"):
        lineas.append("🧠 " + aj["nota"])
    if nota_usuario:
        lineas.append("🧠 " + nota_usuario)
    previas = [o for o in observaciones_del_agricultor(cultivo_id, diag.get("fase"),
                                                       historial, parcela=nombre)
               if o.get("fecha") != actual.get("fecha")]
    if previas:
        lineas.append("🗣️ Segun tus validaciones anteriores:")
        for o in previas:
            lineas.append(f"   • [{o.get('estado', '?')}] {o['nota']}")
    return "\n".join(lineas) + "\n\n"


def guardar_validacion(nombre: str, campana: str, val_ctx: Dict[str, Any], veredicto: str,
                       estado_real: Optional[str] = None, nota: str = "",
                       solo_parcela: bool = False) -> bool:
    """Anota lo que el usuario dice del diagnostico de una pasada.

    Devuelve True si se guardo. Dos decisiones que NO son de interfaz y por eso
    estan aqui, para que las dos den lo mismo:

      - AMBITO. Si el usuario marca "solo esta parcela", la correccion se guarda
        con la clave acotada (`ambito_parcela`) y no contamina al resto de sus
        parcelas del mismo cultivo.
      - APRENDER AL MOMENTO. Si corrige, o escribe una observacion, se tira la
        interpretacion cacheada de esa pasada: la siguiente se redactara teniendo
        en cuenta lo que acaba de decir. Confirmar sin nota no la tira, porque no
        hay nada nuevo que contar."""
    if not val_ctx or not val_ctx.get("fecha"):
        return False
    clave = val_ctx.get("cultivo")
    if solo_parcela:
        clave = ambito_parcela(clave, nombre)
    DB.guardar_validacion(nombre, campana, val_ctx["fecha"], val_ctx.get("fase"),
                          clave, val_ctx.get("estado"), veredicto,
                          estado_real=estado_real, nota=nota)
    if veredicto == "incorrecto" or (nota or "").strip():
        DB.set_interpretacion(nombre, campana, val_ctx["fecha"], None)
    return True


def texto_validacion(nombre: str, campana: str, fecha: Optional[str]) -> Dict[str, str]:
    """Que poner en la linea de validacion: texto y color («ok», «mal» o «neutro»).

    Se devuelve el PAPEL del color, no el color: quien pinta decide el tono, y asi
    este modulo no tiene que saber de paletas."""
    if not fecha:
        return {"texto": "Sin pasada que validar.", "papel": "neutro"}
    v = DB.validacion_de(nombre, campana, fecha)
    if not v:
        return {"texto": "¿El diagnostico es correcto?", "papel": "neutro"}
    if v.get("veredicto") == "correcto":
        return {"texto": "✓ Validado como correcto.", "papel": "ok"}
    return {"texto": f"✗ Corregido a: {v.get('estado_real', '?')}.", "papel": "mal"}


# ---------------------------------------------------------------------------
# Tablas de la ficha
# ---------------------------------------------------------------------------
# Columnas de la estadistica espacial: (clave, titulo, ancho, decimales).
# `pct` significa "es una fraccion y se ensena en porcentaje".
COLS_ESTADISTICA = [("fecha", "FECHA", 88, None), ("media", "MEDIA", 62, 3),
                    ("std", "DESV.", 62, 3), ("cv", "CV", 56, 2),
                    ("p10", "P10", 56, 2), ("p25", "P25", 56, 2), ("p50", "MEDIANA", 66, 2),
                    ("p75", "P75", 56, 2), ("p90", "P90", 56, 2),
                    ("amplitud", "P90-P10", 66, 2), ("n_pixeles", "PIXELES", 62, 0),
                    ("cobertura_valida", "COB.%", 56, "pct")]

PIE_ESTADISTICA = ("MEDIA/DESV. del NDVI entre los pixeles de la parcela · CV = desv./media "
                   "(dispersion relativa) · P90-P10 = distancia entre el mejor y el peor 10 % · "
                   "COB.% = pixeles validos tras descartar nubes.")
PIE_SIN_ESTADISTICA = ("Las pasadas de esta parcela no traen estadistica espacial (son anteriores "
                       "al enmascarado por SCL). Al sincronizar pasadas nuevas apareceran aqui.")


def celda_estadistica(valor, decimales):
    """Un numero de la tabla de estadistica, con su formato. Sin dato, un guion."""
    if valor is None:
        return "-"
    if decimales == "pct":
        return f"{valor * 100:.0f}" if valor <= 1 else f"{valor:.0f}"
    if decimales is None:
        return str(valor)
    return f"{valor:.{decimales}f}"


def filas_estadistica(regs: List[Dict[str, Any]]) -> List[List[str]]:
    """La tabla de estadistica espacial, ya formateada.

    Las pasadas sin estadistica (anteriores al enmascarado por SCL) no salen: una
    fila entera de guiones no informa de nada."""
    salida = []
    for e in (CI.estadisticas_pasada(r) for r in regs or []):
        if not e:
            continue
        salida.append([celda_estadistica(e.get(clave), dec)
                       for clave, _t, _a, dec in COLS_ESTADISTICA])
    return salida


def filas_indices(regs: List[Dict[str, Any]], indices: List[str]) -> List[List[str]]:
    """El historico de indices: una fila por pasada, con tres decimales."""
    salida = []
    for r in regs or []:
        fila = [r.get("fecha", "")]
        for k in indices:
            v = r.get(k.lower())
            fila.append(f"{v:.3f}" if v is not None else "-")
        salida.append(fila)
    return salida
