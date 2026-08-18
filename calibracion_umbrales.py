# -*- coding: utf-8 -*-
"""
calibracion_umbrales.py
=======================

MODULO OPCIONAL Y EXTRAIBLE. Ajusta los umbrales de los indices con lo que el
agricultor valida, SIN tocar los valores de la bibliografia.

Si borras este fichero, el programa sigue funcionando: vuelve a juzgar con los
valores de `fenologia_especies` y desaparecen el desplegable de validacion por
indice y el historial de la ficha. No hay ningun interruptor que tocar. La tabla
`validaciones_indice` se queda quieta en la base, con lo ya anotado, por si lo
vuelves a poner.

QUE PROBLEMA RESUELVE
---------------------
Los umbrales de la bibliografia son un punto de partida razonable, no una verdad
local. El NDMI absoluto se mueve con el sensor, la correccion atmosferica, el
suelo y la comarca: un 0.12 que en Valladolid es sequia en otra zona es normal.
Pedirle al agricultor que toque numeros seria absurdo; lo que si sabe decir es
"ese dia el cultivo estaba bien" mirando la parcela.

COMO FUNCIONA
-------------
1. En cada pasada, el sistema dice de cada indice si lo ve BAJO, NORMAL o ALTO,
   segun los umbrales de la fase.
2. El usuario confirma o corrige, indice a indice, y elige a que ALCANCE aplica:
   solo esta parcela, todo el municipio, toda la provincia o siempre.
3. Con >= MIN_OBSERVACIONES coherentes Y de >= MIN_FECHAS pasadas distintas, el
   umbral se mueve hasta separar lo que el usuario llama "bajo" de lo que llama
   "normal".
4. El desplazamiento esta ACOTADO (DESVIACION_MAX). Una racha de errores no
   puede llevarse el umbral a cualquier sitio.

POR QUE HACEN FALTA LAS DOS CONDICIONES, Y NO SOLO UN NUMERO
------------------------------------------------------------
Con el minimo en 2 bastaba con validar dos indices de UNA MISMA PASADA para mover
un umbral, y ese umbral podia aplicarse a una PROVINCIA entera. Dos indices del
mismo dia no son dos observaciones independientes: son la misma escena, la misma
correccion atmosferica, el mismo estado de humedad del suelo y la misma opinion
del agricultor formada en una sola visita. Si ese dia habia bruma, o el riego se
habia dado la vispera, el sesgo entra entero y se queda.

Por eso ahora se exigen dos cosas distintas:
  - CANTIDAD (MIN_OBSERVACIONES): un numero de validaciones que no se alcanza sin
    querer, para que una racha corta no mueva nada.
  - INDEPENDENCIA (MIN_FECHAS): que vengan de pasadas de DIAS DISTINTOS. Es lo que
    distingue "esto pasa en mi parcela" de "esto paso aquel dia". Diez
    validaciones de una sola fecha siguen sin mover el umbral, y es correcto:
    diez lecturas del mismo momento no dicen mas que una.

El tope DESVIACION_MAX no cambia. Es otra cosa: limita CUANTO se mueve, no CUANDO
se mueve. Los dos frenos son independientes y se quedan los dos.

REGLAS QUE NO SE SALTAN
-----------------------
- La bibliografia NO se toca. El ajuste es una capa encima; quitar este fichero
  la deja intacta.
- Solo se ajustan umbrales que la bibliografia HAYA definido. Donde dice "en esta
  fase el indice no significa nada" (`ndmi_min: None`: senescencia, barbecho,
  lenoso sin hoja) no se inventa un umbral, por muchas validaciones que haya. Si
  no, el sistema acabaria alarmando de un cultivo que se seca a proposito.
- Nunca se nombra una enfermedad. Aqui solo se mueven numeros.
"""

import threading

import almacen as DB
from bitacora import log

# ---------------------------------------------------------------------------
# Vocabulario
# ---------------------------------------------------------------------------
ESTADOS = ["bajo", "normal", "alto"]
SIN_CRITERIO = "sin criterio"       # la fase no define umbral para ese indice

# De mas concreto a mas general. La precedencia es esta y no se discute: lo que
# dices de TU parcela manda sobre lo que dijiste del municipio.
AMBITOS = ["parcela", "municipio", "provincia", "global"]
ETIQUETA_AMBITO = {"parcela": "Solo esta parcela",
                   "municipio": "Todo el municipio",
                   "provincia": "Toda la provincia",
                   "global": "Siempre (todos mis cultivos)"}

# Indices con umbral en la tabla de fases: son los unicos que se pueden calibrar.
# EVI, SAVI y GNDVI NO estan aqui a proposito: se usan por CONTRASTE entre ellos
# (NDVI/EVI, GNDVI/NDVI...), no contra una constante, asi que no hay umbral que
# mover. Se muestran en el dialogo y se anota lo que diga el usuario, pero hoy no
# cambian el diagnostico, y ahi se dice.
# MSAVI si esta: es EL indice de la copa en lenosos, porque corrige el efecto del
# suelo y mide el arbol y no la calle. Su umbral es el mas util de calibrar ahi.
CALIBRABLES = {"NDVI": ("lo", "hi"), "NDMI": ("ndmi_min", None), "LAI": ("lai_min", None),
               "MSAVI": ("msavi_min", None)}

MIN_OBSERVACIONES = 5       # cuantas validaciones coherentes hacen falta
MIN_FECHAS = 2              # ...y de cuantas pasadas DISTINTAS deben venir
DESVIACION_MAX = 0.10       # cuanto puede alejarse de la bibliografia, como mucho
MARGEN = 0.01               # holgura al colocar el umbral entre bajo y normal
LIMITES = {"NDVI": (0.0, 1.0), "NDMI": (-0.5, 0.6), "LAI": (0.0, 8.0),
           "MSAVI": (0.0, 1.0)}

# ---------------------------------------------------------------------------
# Cache: evaluar_parcela se llama una vez por parcela en cada refresco de la
# lista. Sin cache serian varias consultas por parcela y por pasada.
# ---------------------------------------------------------------------------
_CACHE = {}
_LOCK = threading.RLock()


def _invalidar(_nombre=None):
    with _LOCK:
        _CACHE.clear()


# Si se BORRA una parcela, sus validaciones se van con ella y cualquier umbral que
# saliera de ellas deja de estar justificado. La cache no se entera sola: sin esto
# el ajuste seguia aplicandose con datos que ya no existen hasta cerrar el
# programa. Se pide el aviso a `almacen`, que es quien sabe cuando pasa.
DB.al_eliminar_parcela(_invalidar)


# ---------------------------------------------------------------------------
# Ambitos
# ---------------------------------------------------------------------------
def ambitos_de(parcela, ficha=None):
    """Lista de (ambito, clave) de esa parcela, de mas concreto a mas general.

    Municipio y provincia salen de los codigos SIGPAC guardados en la ficha. Si
    la parcela no los tiene -no se capturo por SIGPAC, o es anterior a que se
    guardaran- esos dos ambitos sencillamente no aparecen, y quedan parcela y
    global. No se inventa una ubicacion."""
    if not parcela:
        return [("global", "")]
    if ficha is None:
        ficha = DB.ficha(parcela) or {}
    fuera = [("parcela", parcela)]
    mun = (ficha.get("municipio") or "").strip()
    prov = (ficha.get("provincia") or "").strip()
    if mun:
        fuera.append(("municipio", mun))
    if prov:
        fuera.append(("provincia", prov))
    fuera.append(("global", ""))
    return fuera


def ambitos_disponibles(parcela, ficha=None):
    """Los ambitos que se le pueden ofrecer al usuario para esta parcela."""
    return [(a, ETIQUETA_AMBITO[a]) for a, _ in ambitos_de(parcela, ficha)]


# ---------------------------------------------------------------------------
# Que dice el SISTEMA de cada indice
# ---------------------------------------------------------------------------
def veredicto_sistema(indice, valor, umbrales):
    """bajo / normal / alto / sin criterio, segun los umbrales de la fase."""
    if valor is None:
        return SIN_CRITERIO
    if indice == "NDVI":
        lo, hi = umbrales.get("lo"), umbrales.get("hi")
        if lo is None or hi is None:
            return SIN_CRITERIO
        return "bajo" if valor < lo else ("alto" if valor > hi else "normal")
    if indice == "NDMI":
        m = umbrales.get("ndmi_min")
        return SIN_CRITERIO if m is None else ("bajo" if valor < m else "normal")
    if indice == "LAI":
        m = umbrales.get("lai_min")
        return SIN_CRITERIO if m is None else ("bajo" if valor < m else "normal")
    if indice == "MSAVI":
        m = umbrales.get("msavi_min")
        return SIN_CRITERIO if m is None else ("bajo" if valor < m else "normal")
    return SIN_CRITERIO


def lectura_de_pasada(reg, umbrales, indices):
    """Que dice el sistema de CADA indice de una pasada.

    Devuelve {INDICE: {"valor": v, "sistema": veredicto, "calibrable": bool}}."""
    out = {}
    for idx in indices:
        v = reg.get(idx.lower())
        out[idx] = {"valor": v,
                    "sistema": veredicto_sistema(idx, v, umbrales),
                    "calibrable": idx in CALIBRABLES}
    return out


# ---------------------------------------------------------------------------
# Registrar lo que dice el USUARIO
# ---------------------------------------------------------------------------
def sistema_de(umbrales):
    """(regimen, densidad) del cultivo, para no mezclar sistemas distintos.

    Un olivar de secano tradicional y un seto superintensivo de regadio no tienen
    nada que ver: si comparten clave de calibracion, sus validaciones se
    contaminan. En herbaceos esto no aplica y queda vacio, que actua de comodin."""
    umbrales = umbrales or {}
    regimen = umbrales.get("regimen") or ""
    tipo = (umbrales.get("tipo") or "").lower()
    densidad = ("seto" if "seto" in tipo or "alta densidad" in tipo else
                "intensivo" if "intensivo" in tipo else
                "tradicional" if "tradicional" in tipo or "vaso" in tipo else "")
    return regimen, densidad


def registrar(parcela, campana, fecha, especie, fase, lecturas, respuestas, ambito,
              umbrales=None):
    """Guarda las respuestas del usuario para una pasada.

    `lecturas` es lo que devolvio `lectura_de_pasada`; `respuestas` es
    {INDICE: "bajo"|"normal"|"alto"}. Solo se guarda lo que tiene valor medido:
    validar un indice que ese dia no se midio no aporta nada.
    """
    ficha = DB.ficha(parcela) or {}
    clave = dict(ambitos_de(parcela, ficha)).get(ambito, "")
    regimen, densidad = sistema_de(umbrales)
    n = 0
    for idx, dijo in (respuestas or {}).items():
        lec = (lecturas or {}).get(idx) or {}
        if lec.get("valor") is None or dijo not in ESTADOS:
            continue
        DB.guardar_validacion_indice(parcela, campana, fecha, idx, lec["valor"],
                                     especie or "", fase or "",
                                     lec.get("sistema", SIN_CRITERIO), dijo,
                                     ambito, clave, regimen, densidad)
        n += 1
    _invalidar()
    return n


# ---------------------------------------------------------------------------
# El ajuste
# ---------------------------------------------------------------------------
def _candidato(valores_bajos, valores_normales, biblio):
    """Donde poner el liston para separar lo que el usuario llama bajo de lo que
    llama normal. Devuelve None si no hay con que decidir."""
    techo_bajo = max(valores_bajos) if valores_bajos else None
    suelo_normal = min(valores_normales) if valores_normales else None
    if techo_bajo is not None and suelo_normal is not None:
        if techo_bajo < suelo_normal:
            return (techo_bajo + suelo_normal) / 2.0      # hueco limpio: en medio
        # se solapan: el usuario no es consistente en esa franja. Se queda donde
        # deja fuera lo que llamo normal, que es el error que mas molesta.
        return suelo_normal - MARGEN
    if suelo_normal is not None:
        return min(biblio, suelo_normal - MARGEN)         # solo "normales": bajar
    if techo_bajo is not None:
        return max(biblio, techo_bajo + MARGEN)           # solo "bajos": subir
    return None


def _acotar(indice, valor, biblio):
    """Ni se aleja de la bibliografia mas de DESVIACION_MAX ni se sale del rango
    fisico del indice. Una racha de validaciones raras no puede desmadrarlo."""
    valor = max(biblio - DESVIACION_MAX, min(biblio + DESVIACION_MAX, valor))
    lo, hi = LIMITES.get(indice, (-1.0, 10.0))
    return round(max(lo, min(hi, valor)), 3)


def umbral_calibrado(indice, clave_umbral, biblio, especie, fase, ambitos,
                     regimen="", densidad=""):
    """Umbral ajustado para (indice, especie, fase), o None si no hay evidencia.

    Gana el ambito MAS CONCRETO que reuna evidencia suficiente: MIN_OBSERVACIONES
    validaciones Y de MIN_FECHAS pasadas distintas. Si tu parcela llega al minimo
    y el municipio tiene 40, mandan las de tu parcela: es tu tierra.

    Un ambito que no reune las dos condiciones no bloquea a los de mas arriba: se
    salta y se prueba el siguiente. Asi, mientras tu parcela junta observaciones,
    lo que ya sepa el municipio sigue valiendo."""
    if biblio is None:
        return None                     # la bibliografia dice que aqui no se juzga
    llave = (indice, clave_umbral, especie, fase, tuple(ambitos), regimen, densidad)
    with _LOCK:
        if llave in _CACHE:
            return _CACHE[llave]
    resultado = None
    for ambito, clave in ambitos:
        filas = DB.validaciones_indice(indice=indice, especie=especie, fase=fase,
                                       ambitos=[(ambito, clave)],
                                       regimen=regimen, densidad=densidad)
        if len(filas) < MIN_OBSERVACIONES:
            continue
        # ...y que NO sean todas del mismo dia. Diez validaciones de una sola
        # pasada son diez lecturas de la misma escena, la misma correccion
        # atmosferica y la misma visita: no son diez observaciones, son una.
        fechas = {f["fecha"] for f in filas if f.get("fecha")}
        if len(fechas) < MIN_FECHAS:
            continue
        bajos = [f["valor"] for f in filas if f["dijo_usuario"] == "bajo"
                 and f["valor"] is not None]
        normales = [f["valor"] for f in filas if f["dijo_usuario"] in ("normal", "alto")
                    and f["valor"] is not None]
        cand = _candidato(bajos, normales, biblio)
        if cand is None:
            continue
        resultado = {"valor": _acotar(indice, cand, biblio), "ambito": ambito,
                     "n": len(filas), "fechas": len(fechas), "biblio": biblio}
        break
    with _LOCK:
        _CACHE[llave] = resultado
    return resultado


def ajustar_umbrales(umbrales, especie, fase, parcela, ficha=None):
    """Devuelve los umbrales de la fase con lo aprendido aplicado encima.

    No modifica el dict recibido. Anade la clave `calibrado` con lo que se ha
    movido y por que, para poder explicarlo en la ficha."""
    if not umbrales or not especie or not fase:
        return umbrales
    ambitos = ambitos_de(parcela, ficha)
    regimen, densidad = sistema_de(umbrales)
    fuera = dict(umbrales)
    detalle = {}
    for indice, (clave_min, clave_max) in CALIBRABLES.items():
        for clave in (clave_min, clave_max):
            if clave is None:
                continue
            aj = umbral_calibrado(indice, clave, umbrales.get(clave), especie, fase,
                                  ambitos, regimen, densidad)
            if aj and aj["valor"] != umbrales.get(clave):
                fuera[clave] = aj["valor"]
                detalle[f"{indice}.{clave}"] = aj
    if detalle:
        fuera["calibrado"] = detalle
    return fuera


def texto_calibracion(umbrales):
    """Una linea explicando que umbrales vienen de tus validaciones y no de la
    tabla. Sin esto el usuario no sabria por que el sistema ha cambiado de idea."""
    det = (umbrales or {}).get("calibrado")
    if not det:
        return ""
    trozos = []
    for k, aj in sorted(det.items()):
        indice = k.split(".")[0]
        # se dice tambien de cuantas pasadas vienen: dos numeros distintos, y el
        # de fechas es el que dice si la evidencia esta repartida en el tiempo
        trozos.append(f"{indice} {aj['biblio']:.2f}->{aj['valor']:.2f} "
                      f"({ETIQUETA_AMBITO[aj['ambito']].lower()}, {aj['n']} validaciones "
                      f"en {aj.get('fechas', 1)} pasadas)")
    return "Umbrales ajustados con tus validaciones: " + "; ".join(trozos) + "."


# ---------------------------------------------------------------------------
# Informe: que cambiaria en TU historico
# ---------------------------------------------------------------------------
def comparar_con_historico(campana=None):
    """Relee las pasadas ya guardadas y cuenta que diagnosticos cambiarian.

    Sirve para ver el efecto ANTES de fiarse, sin esperar una campana entera:
    la base ya tiene el historico. Se ejecuta con `python calibracion_umbrales.py`.
    """
    from interpretacion_fenologica import evaluar_parcela
    from cultivo import spec_de
    resumen = {"parcelas": 0, "pasadas": 0, "cambian": 0, "detalle": []}
    for nombre in DB.nombres():
        ficha = DB.ficha(nombre) or {}
        for camp, cult in (ficha.get("cultivos_por_campana") or {}).items():
            if campana and camp != campana:
                continue
            serie = sorted(DB.pasadas(nombre, camp), key=lambda r: r.get("fecha", ""))
            if not serie:
                continue
            resumen["parcelas"] += 1
            for i in range(len(serie)):
                sub = serie[:i + 1]
                resumen["pasadas"] += 1
                base = evaluar_parcela(cult.get("tipo", ""), cult.get("subtipo", ""), sub,
                                       spec=spec_de(cult))
                cal = evaluar_parcela(cult.get("tipo", ""), cult.get("subtipo", ""), sub,
                                      spec=spec_de(cult), parcela=nombre)
                if base["estado"] != cal["estado"]:
                    resumen["cambian"] += 1
                    resumen["detalle"].append(
                        (nombre, camp, sub[-1].get("fecha", ""), base["estado"], cal["estado"]))
    return resumen


if __name__ == "__main__":       # pragma: no cover - utilidad de linea de comandos
    DB.conectar()
    r = comparar_con_historico()
    print(f"parcelas revisadas: {r['parcelas']}   pasadas: {r['pasadas']}")
    print(f"diagnosticos que cambiarian con tus validaciones: {r['cambian']}")
    for nombre, camp, fecha, a, b in r["detalle"][:40]:
        print(f"  {nombre:<20} {camp}  {fecha}   {a:>8} -> {b}")
    if not r["detalle"]:
        print("  Ninguno: todavia no hay validaciones suficientes, o no mueven nada.")
    log.info("comparacion de umbrales: %s de %s pasadas cambiarian",
             r["cambian"], r["pasadas"])
