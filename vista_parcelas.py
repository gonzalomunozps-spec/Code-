# -*- coding: utf-8 -*-
"""
vista_parcelas.py
=================

Logica PURA de la LISTA de parcelas: filtrar, diagnosticar, ordenar y dar
formato. Sin Tkinter, sin Qt y sin base de datos: recibe los datos ya leidos y
devuelve las filas listas para pintar.

POR QUE ESTA APARTE
-------------------
Esto vivia dentro de `PanelGestionParcelas._refrescar`, mezclado con las llamadas
a Tk. Al portar la interfaz a Qt habria que haberlo copiado, y dos copias de la
misma decision -que estado sale, con que color, en que orden- acaban divergiendo:
la lista diria una cosa en una ventana y otra en la otra. Aqui vive una sola vez,
la usan los dos frontends y se prueba sin pantalla.

No decide NADA nuevo: el diagnostico lo sigue dando `evaluar_parcela`, y la
severidad y los nombres de cultivo son los que ya se usaban.
"""

from typing import Any, Callable, Dict, List, Optional

from cultivo import clave_cultivo, spec_de

# Nombre legible de cada cultivo. La clave la construye `clave_cultivo`.
NOMBRE_CULTIVO = {
    "LENOSO_TRADICIONAL": "Olivar tradicional", "LENOSO_INTENSIVO": "Olivar intensivo",
    "LENOSO_SUPERINTENSIVO": "Olivar superintensivo",
    "EXTENSIVO_SIEGA_VERDE": "Extensivo (siega verde)",
    "EXTENSIVO_COSECHA_GRANO": "Extensivo (grano)", "BARBECHO": "Barbecho",
}

# Orden de gravedad al ordenar por estado: primero lo que hay que mirar hoy.
SEVERIDAD = {"Revisar": 0, "Vigilar": 1, "OK": 2, "Segado": 2,
             "Sin dato": 3, "N.A.": 4, "Sin asignar": 5}

# Estados que llevan punto de color en la lista. Los demas (N.A., sin asignar) no
# son un juicio sobre el cultivo, asi que no se pintan como si lo fueran.
CON_SEMAFORO = ("OK", "Vigilar", "Revisar")

ORDENES = ("nombre", "cultivo", "superficie", "propietario", "estado")


def _texto_cultivo(clave: str) -> str:
    if clave in NOMBRE_CULTIVO:
        return NOMBRE_CULTIVO[clave]
    if clave == "SIN_ASIGNAR":
        return "Sin asignar"
    return clave.replace("_", " ").title()


def fila_de_parcela(nombre: str, ficha: Dict[str, Any], campana: str,
                    serie: Optional[List[Dict[str, Any]]],
                    evaluar: Callable) -> Dict[str, Any]:
    """Una fila de la lista. `evaluar` es `interpretacion_fenologica.evaluar_parcela`.

    Se inyecta en vez de importarlo para que este modulo no arrastre el motor
    entero cuando solo se quiere dar formato."""
    cult = (ficha.get("cultivos_por_campana") or {}).get(campana)
    if cult is None:                              # sin cultivo en esta campana
        clave_c, clave, txt = "SIN_ASIGNAR", "SinAsig", "Sin asignar"
    elif cult.get("tipo") == "BARBECHO":          # barbecho: no aplica vigor
        clave_c, clave, txt = "BARBECHO", "NA", "N.A."
    else:
        clave_c = clave_cultivo(cult.get("tipo"), cult.get("subtipo", ""))
        diag = evaluar(cult.get("tipo"), cult.get("subtipo", ""),
                       sorted(serie or [], key=lambda r: r.get("fecha", "")),
                       spec=spec_de(cult))
        clave, txt = diag["clave"], diag["estado"]
    sup = ficha.get("superficie_ha", 0.0) or 0.0
    return {"nombre": nombre.replace("_", " "),
            "id": nombre,
            "cultivo": _texto_cultivo(clave_c),
            "superficie": f"{sup:.2f} ha",
            "_sup": sup,
            "propietario": ficha.get("propietario", ""),
            "estado": txt,
            "_clave": clave,
            "semaforo": clave in CON_SEMAFORO}


def _coincide(nombre: str, ficha: Dict[str, Any], texto: str) -> bool:
    if not texto:
        return True
    t = texto.lower()
    return t in nombre.lower() or t in (ficha.get("propietario", "") or "").lower()


def filas(parcelas: Dict[str, Any], historico: Dict[str, Any], campana: str,
          evaluar: Callable, texto: str = "", orden: str = "nombre") -> List[Dict[str, Any]]:
    """Las filas de la lista, filtradas y ordenadas.

    `parcelas` es {nombre: ficha} y `historico` {nombre: [pasadas]} de esa
    campana, tal como los devuelve `almacen`. Un `orden` desconocido ordena por
    nombre, que es el comportamiento de siempre."""
    salida = [fila_de_parcela(n, f, campana, historico.get(n), evaluar)
              for n, f in (parcelas or {}).items() if _coincide(n, f, texto)]
    claves = {"superficie": lambda r: -r["_sup"],
              "cultivo": lambda r: r["cultivo"].lower(),
              "propietario": lambda r: r["propietario"].lower(),
              "estado": lambda r: SEVERIDAD.get(r["estado"], 9),
              "nombre": lambda r: r["nombre"].lower()}
    salida.sort(key=claves.get(orden, claves["nombre"]))
    return salida


def resumen(filas_lista: List[Dict[str, Any]]) -> Dict[str, int]:
    """Cuantas parcelas hay en cada estado. Para la barra de cabecera."""
    out = {}
    for r in filas_lista or []:
        out[r["estado"]] = out.get(r["estado"], 0) + 1
    return out


# =====================================================================
# ALTA Y EDICION DE UNA PARCELA
# =====================================================================
def guardar_parcela(db, fen, superficie, nombre, propietario, tipo, spec, coords,
                    campana, sigpac=None, buffer_m=None):
    """Escribe la parcela y su cultivo de esa campana. Devuelve la ficha guardada.

    Estaba dentro del panel de Tkinter. Se saca porque el alta de Qt necesita
    exactamente las mismas reglas, y son reglas de DATOS, no de ventana:

      - el poligono se CIERRA si no venia cerrado, y de ahi sale la superficie;
      - los codigos SIGPAC se guardan (provincia y municipio son la unidad en la
        que se corrige un umbral para una comarca; antes se tecleaban, servian
        para bajar el recinto y se tiraban);
      - el SUBTIPO se deriva: en lenoso, del marco; en extensivo, de la finalidad.
        Nadie lo teclea, para que no pueda contradecir al marco.

    `db`, `fen` y `superficie` se inyectan (almacen, fenologia_especies y
    geo.superficie_ha) para que este modulo siga sin dependencias propias."""
    cerrado = coords + [coords[0]] if coords and coords[0] != coords[-1] else coords
    ficha = db.ficha(nombre) or {}
    ficha.update({"propietario": propietario, "coordenadas": cerrado,
                  "superficie_ha": superficie(cerrado),
                  "anio_inicio_monitoreo": ficha.get("anio_inicio_monitoreo", campana)})
    if sigpac and sigpac.get("Prov") and sigpac.get("Mun"):
        prov, mun = str(sigpac["Prov"]).strip(), str(sigpac["Mun"]).strip()
        ficha["provincia"] = prov
        ficha["municipio"] = f"{prov}/{mun}"
        ficha["sigpac"] = {k: str(v).strip() for k, v in sigpac.items() if str(v).strip()}
    if buffer_m is not None:
        ficha["buffer_m"] = float(buffer_m)
    spec = dict(spec or {})
    subtipo = ""
    if tipo == "LENOSO" and spec.get("marco_calle"):
        dens = fen.densidad_arboles(spec["marco_calle"], spec["marco_pie"])
        subtipo = fen.subtipo_canonico(spec.get("especie", "OLIVO"), dens)
    elif tipo == "EXTENSIVO":
        subtipo = (spec.get("finalidad")
                   if spec.get("finalidad") in ("SIEGA_VERDE", "COSECHA_GRANO")
                   else "COSECHA_GRANO")
    cultivo = {"tipo": tipo, "subtipo": subtipo}
    cultivo.update(spec)
    ficha.setdefault("cultivos_por_campana", {})[campana] = cultivo
    db.guardar_ficha(nombre, ficha)
    return ficha
