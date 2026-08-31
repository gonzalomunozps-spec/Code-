# -*- coding: utf-8 -*-
"""
contraste_rendimiento.py
========================

HERRAMIENTA DE DIAGNOSTICO, no parte del programa. Contesta a la unica pregunta
que valida de verdad los umbrales del sistema:

    ¿las parcelas que el semaforo marco en la FASE CRITICA rindieron menos?

Se usa asi, con el programa cerrado y desde la carpeta del proyecto:

    python contraste_rendimiento.py                    # todo lo que haya
    python contraste_rendimiento.py --campana 2025-2026
    python contraste_rendimiento.py --humedad-ref 9    # girasol, por ejemplo

No escribe nada. Solo lee la base y saca un informe por pantalla.


POR QUE ESTO Y NO LAS VALIDACIONES
----------------------------------
Cuando el usuario valida un diagnostico como «correcto» o «incorrecto» esta
contrastando el criterio del sistema contra SU criterio. Si los umbrales de
`fenologia_especies` salieron de ese mismo criterio, el bucle se cierra sobre si
mismo: se confirma una opinion con la misma opinion.

Los kg/ha de la bascula no opinan. Si las parcelas que el sistema marco rindieron
igual que las que no marco, el umbral no separa nada, por convencido que se este.
Esa es la prueba, y es la unica que no se puede discutir.


TRES COSAS QUE HAY QUE HACER BIEN O EL RESULTADO NO VALE
--------------------------------------------------------
1. HUMEDAD. 6.000 kg/ha al 18 % de humedad NO son mas que 5.800 al 14 %: en los
   primeros hay mas agua. Sin llevar todo a una humedad de referencia se estan
   comparando pesos de agua distintos. `almacen.rendimientos` guarda el dato
   crudo de bascula a proposito (ahi no se corrige nada); la correccion se hace
   aqui. Ver `normaliza`.

2. NO MEZCLAR. Un trigo y una cebada no se comparan en kg/ha, ni dos campanas
   distintas: el ano manda mas que cualquier umbral. Todo contraste se hace
   DENTRO de un grupo (especie, campana). Es lo que hace que hagan falta varias
   parcelas del mismo cultivo el mismo ano, y no vale juntarlo todo.

3. LA FASE CRITICA, no el pico. Lo que hoy empareja `vista_ficha` es el NDVI
   MAXIMO de la campana contra el rendimiento. El maximo cae en el momento de
   maxima cobertura, que en un cereal es ANTES de que se decida la cosecha. La
   bibliografia de coeficientes de respuesta (FAO-56, Ky) dice que lo que
   determina la produccion es lo que pasa en la fase critica -espigado/floracion
   y llenado de grano-, y esas fases ya vienen marcadas en las tablas con
   `"critica": True`. Aqui se mira ahi.


LO QUE ESTA HERRAMIENTA NO HACE
-------------------------------
No cambia ningun umbral, ni propone cambiarlo. Dice si el que hay separa o no
separa. Mover un umbral con cuatro parcelas seria cambiar la agronomia de todas
las parcelas de esa especie a partir de una muestra que no da para eso.

Tampoco convierte «rindieron menos» en «el sistema acerto»: puede que el sistema
avisara de algo real que se corrigio a tiempo, y entonces la parcela avisada
rinde igual y el aviso fue util. Por eso el informe separa los avisos que
quedaron VIGENTES al cierre de los que se resolvieron: solo los vigentes deberian
verse en la bascula.
"""

import argparse
import itertools
import math
import sys

# Humedad comercial de referencia. El 14 % es la habitual del grano de cereal;
# el girasol se paga al 9 %, y cada contrato tiene la suya. Se deja como
# parametro (`--humedad-ref`) porque NO es una constante agronomica universal.
#
# Importante: para el CONTRASTE da igual cual se elija. La correccion es un factor
# comun dentro de un grupo (misma referencia para todas las parcelas), asi que no
# altera el orden ni la conclusion; solo cambia los kg/ha que se leen en pantalla.
# Solo importa si se van a comparar estas cifras con las de un albaran.
HUMEDAD_REFERENCIA = 14.0

# Minimos para que el contraste signifique algo. Con menos, el informe NO concluye:
# dice cuantas parcelas faltan. Ver `evidencia_maxima` para el porque del 4+4.
MIN_POR_GRUPO = 4           # parcelas en cada lado (avisadas / limpias)


# ---------------------------------------------------------------------------
# Nucleo puro: aritmetica y estadistica, sin base de datos
# ---------------------------------------------------------------------------
def normaliza(kg_ha, humedad_pct, referencia=HUMEDAD_REFERENCIA):
    """Kg/ha llevados a una humedad de referencia. None si no se puede.

    Balance de materia seca, que es lo que de verdad se cosecha:

        kg_ref = kg_medidos * (100 - H_medida) / (100 - H_referencia)

    Si no se anoto la humedad se devuelve el valor TAL CUAL, porque mas vale un
    rendimiento sin corregir que ninguno -pero el informe lo marca, porque mezclar
    corregidos y sin corregir mete un error que puede ser mayor que la diferencia
    que se busca-.
    """
    if kg_ha is None:
        return None
    try:
        kg = float(kg_ha)
    except (TypeError, ValueError):
        return None
    if kg < 0:
        return None
    if humedad_pct is None:
        return kg                        # sin dato: se pasa crudo (y se avisa)
    try:
        h = float(humedad_pct)
    except (TypeError, ValueError):
        return kg
    if not (0.0 <= h < 100.0) or not (0.0 <= referencia < 100.0):
        return kg                        # humedad imposible: no se corrige nada
    return kg * (100.0 - h) / (100.0 - referencia)


def mediana(xs):
    """La mediana, o None si no hay datos. Se usa mediana y no media porque con
    cuatro parcelas una helada en una se lleva la media por delante."""
    ys = sorted(x for x in xs if x is not None)
    if not ys:
        return None
    n = len(ys)
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2.0


def _u(a, b):
    """Estadistico U de Mann-Whitney: cuantos pares (x de a, y de b) tienen x<y.
    Los empates cuentan medio, que es lo estandar."""
    u = 0.0
    for x in a:
        for y in b:
            if x < y:
                u += 1.0
            elif x == y:
                u += 0.5
    return u


def p_una_cola(avisados, limpios):
    """Probabilidad EXACTA de ver una separacion asi de buena por puro azar, si
    en realidad el aviso no dijera nada.

    Es la prueba de Mann-Whitney con enumeracion completa: se recolocan las
    etiquetas de todas las formas posibles y se cuenta en cuantas sale un
    resultado al menos tan favorable. Exacta, sin suponer normalidad -que con
    cinco parcelas no se puede suponer- y sin depender de scipy.

    Hipotesis: los avisados rinden MENOS. Devuelve None si falta algun lado.
    """
    a = [x for x in avisados if x is not None]
    b = [x for x in limpios if x is not None]
    if not a or not b:
        return None
    n, m = len(a), len(b)
    if math.comb(n + m, n) > 200000:     # muestras grandes: la exacta no hace falta
        return _p_aproximada(a, b)
    observado = _u(a, b)                 # pares en que el avisado rinde menos
    todos = a + b
    favorables = total = 0
    for idx in itertools.combinations(range(n + m), n):
        sel = set(idx)
        ga = [todos[i] for i in idx]
        gb = [todos[i] for i in range(n + m) if i not in sel]
        total += 1
        if _u(ga, gb) >= observado:
            favorables += 1
    return favorables / total if total else None


def _p_aproximada(a, b):
    """Aproximacion normal de Mann-Whitney, para cuando enumerar es absurdo."""
    n, m = len(a), len(b)
    u = _u(a, b)
    mu = n * m / 2.0
    sigma = math.sqrt(n * m * (n + m + 1) / 12.0)
    if sigma == 0:
        return None
    z = (u - mu - 0.5) / sigma
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def evidencia_maxima(n_avisados, n_limpios):
    """La p MAS PEQUENA que se puede sacar con esos tamanos, aunque la separacion
    sea perfecta.

    Esto es lo que hace honesto al informe. Con 3 avisadas y 3 limpias hay 20
    repartos posibles, asi que aunque las tres peores sean las tres avisadas la p
    no baja de 1/20 = 0,05. Con 2 y 2 no baja de 1/6 = 0,17: NINGUN resultado con
    esa muestra puede ser concluyente, y decirlo antes de mirar los datos evita
    contarse una historia con lo que salga.
    """
    if n_avisados < 1 or n_limpios < 1:
        return None
    return 1.0 / math.comb(n_avisados + n_limpios, n_avisados)


def contraste(avisados, limpios):
    """Compara los rendimientos de las parcelas avisadas contra las limpias.

    Devuelve n de cada lado, medianas, la diferencia (en kg/ha y en %), si los
    dos rangos se solapan, la p exacta y la mejor p alcanzable con esa muestra.
    `concluyente` solo es True si hay muestra suficiente Y la p baja de 0,05.
    """
    a = [x for x in avisados if x is not None]
    b = [x for x in limpios if x is not None]
    ma, mb = mediana(a), mediana(b)
    dif = (ma - mb) if (ma is not None and mb is not None) else None
    p = p_una_cola(a, b)
    mejor = evidencia_maxima(len(a), len(b))
    suficiente = len(a) >= MIN_POR_GRUPO and len(b) >= MIN_POR_GRUPO
    return {
        "n_avisados": len(a), "n_limpios": len(b),
        "mediana_avisados": ma, "mediana_limpios": mb,
        "diferencia": dif,
        "diferencia_pct": (100.0 * dif / mb) if (dif is not None and mb) else None,
        "solapan": bool(a and b and max(a) > min(b)),
        "p": p, "mejor_p_posible": mejor,
        "muestra_suficiente": suficiente,
        "concluyente": bool(suficiente and p is not None and p < 0.05),
    }


# ---------------------------------------------------------------------------
# Lectura de la base: un caso por (parcela, campana) con cosecha anotada
# ---------------------------------------------------------------------------
def aviso_vigente(marcas):
    """¿Hubo un aviso en fase critica que NO se recupero mientras aun importaba?

    `marcas`: lista, pasada a pasada, de (critica, estado, esperado).

    LA RECUPERACION SOLO CUENTA DENTRO DE LA VENTANA CRITICA. Esto no es un
    detalle de implementacion, es la agronomia del asunto: los coeficientes de
    respuesta del cultivo (FAO-56, Ky) dicen que lo que se pierde en floracion y
    llenado NO se recupera despues. Un trigo que se hunde en llenado y «vuelve al
    verde» en senescencia no ha recuperado nada: es que en senescencia el NDVI
    bajo es lo normal, y el motor deja de avisar por eso.

    El informe anual usa un balance parecido pero mira TODA la campana, porque
    alli se cuenta la historia del ano. Copiar aquel criterio aqui era el error
    obvio -y se cometio-: marcaba como «resuelto» absolutamente todo, porque
    despues de la fase critica siempre viene la senescencia, y el contraste salia
    con cero parcelas avisadas siempre.
    """
    ultima_critica = -1
    for i, (critica, _e, _esp) in enumerate(marcas):
        if critica:
            ultima_critica = i
    for i, (critica, estado, esperado) in enumerate(marcas):
        if not critica or esperado or estado not in ("Revisar", "Vigilar"):
            continue
        # ¿se reencuadro mientras la fase critica seguia abierta?
        recuperado = any(marcas[j][2] or marcas[j][1] == "OK"
                         for j in range(i + 1, ultima_critica + 1))
        if not recuperado:
            return True
    return False


def _rasgos(tipo, subtipo, serie, spec):
    """Recorre la campana pasada a pasada con el motor REAL y saca lo que hace
    falta para el contraste.

    Devuelve (aviso_vigente, indice_min_critica, pasadas_criticas). El minimo del
    indice de juicio se toma DENTRO de las fases criticas -no el maximo de la
    campana, que cae en maxima cobertura, antes de que se decida la cosecha-.
    """
    from interpretacion_fenologica import evaluar_parcela
    marcas, minimos, criticas = [], [], 0
    for i in range(len(serie)):
        d = evaluar_parcela(tipo, subtipo, serie[:i + 1], spec=spec)
        critica = bool((d.get("umbrales") or {}).get("critica"))
        marcas.append((critica, d.get("estado"), bool(d.get("esperado"))))
        if critica:
            criticas += 1
            v = d.get("ndvi_juicio")
            if v is not None:
                minimos.append(v)
    return (aviso_vigente(marcas), (min(minimos) if minimos else None), criticas)


def casos(campana=None, referencia=HUMEDAD_REFERENCIA):
    """Un caso por (parcela, campana) que TENGA cosecha anotada.

    Sin kg/ha no hay nada que contrastar, asi que esas campanas no entran -pero se
    cuentan aparte, porque «no tengo datos» y «los datos no separan» son
    conclusiones muy distintas y no deben confundirse-.
    """
    import almacen as DB
    from cultivo import spec_de
    fuera, sin_cosecha = [], 0
    for nombre in DB.nombres():
        ficha = DB.ficha(nombre) or {}
        rend_por_camp = {}
        for r in DB.rendimientos(nombre):
            if r.get("rendimiento_kg_ha") is not None:
                rend_por_camp.setdefault(r["campana"], []).append(r)
        for camp, cult in (ficha.get("cultivos_por_campana") or {}).items():
            if campana and camp != campana:
                continue
            serie = sorted(DB.pasadas(nombre, camp), key=lambda r: r.get("fecha", ""))
            if not serie:
                continue
            cosechas = rend_por_camp.get(camp) or []
            if not cosechas:
                sin_cosecha += 1
                continue
            # Varias cosechas en una campana (una siega de forraje se corta varias
            # veces): se suma la produccion del ano, que es lo que se compara.
            kgs, con_humedad = [], 0
            for r in cosechas:
                v = normaliza(r.get("rendimiento_kg_ha"),
                              r.get("humedad_grano_pct"), referencia)
                if v is not None:
                    kgs.append(v)
                    if r.get("humedad_grano_pct") is not None:
                        con_humedad += 1
            if not kgs:
                sin_cosecha += 1
                continue
            spec = spec_de(cult)
            vigente, ndvi_min, n_crit = _rasgos(cult.get("tipo", ""),
                                                cult.get("subtipo", ""), serie, spec)
            fuera.append({
                "parcela": nombre, "campana": camp,
                "especie": (spec or {}).get("especie") or cult.get("subtipo") or "?",
                "tipo": cult.get("tipo", ""),
                "rendimiento": sum(kgs),
                "humedad_anotada": con_humedad == len(cosechas),
                "avisado": vigente, "ndvi_min_critica": ndvi_min,
                "pasadas_criticas": n_crit,
            })
    return fuera, sin_cosecha


def agrupa(lista):
    """Los casos por (especie, campana). Comparar fuera de ese grupo no vale:
    dos especies no rinden lo mismo, y dos anos tampoco."""
    grupos = {}
    for c in lista:
        grupos.setdefault((c["especie"], c["campana"]), []).append(c)
    return grupos


# ---------------------------------------------------------------------------
# El informe
# ---------------------------------------------------------------------------
def _kg(v):
    return "     -" if v is None else f"{v:6.0f}"


def _bloque_grupo(especie, camp, casos_g, salida):
    avisados = [c["rendimiento"] for c in casos_g if c["avisado"]]
    limpios = [c["rendimiento"] for c in casos_g if not c["avisado"]]
    r = contraste(avisados, limpios)
    salida.append(f"  {especie}  ·  {camp}   ({len(casos_g)} parcelas con cosecha)")
    salida.append(f"     avisadas en fase critica: {r['n_avisados']:2d}   "
                  f"mediana {_kg(r['mediana_avisados'])} kg/ha")
    salida.append(f"     sin aviso vigente:        {r['n_limpios']:2d}   "
                  f"mediana {_kg(r['mediana_limpios'])} kg/ha")

    if not r["muestra_suficiente"]:
        falta_a = max(0, MIN_POR_GRUPO - r["n_avisados"])
        falta_l = max(0, MIN_POR_GRUPO - r["n_limpios"])
        mejor = r["mejor_p_posible"]
        salida.append("     NO CONCLUYE: muestra insuficiente.")
        if mejor is not None:
            salida.append(f"       con {r['n_avisados']} y {r['n_limpios']} parcelas, aunque la separacion "
                          f"fuese perfecta la p no bajaria de {mejor:.2f}.")
        piezas = []
        if falta_a:
            piezas.append(f"{falta_a} avisada(s) mas")
        if falta_l:
            piezas.append(f"{falta_l} sin aviso mas")
        if piezas:
            salida.append(f"       faltan {' y '.join(piezas)} de esta especie y campana.")
        return r

    d, dp, p = r["diferencia"], r["diferencia_pct"], r["p"]
    if d is not None:
        signo = "menos" if d < 0 else "mas"
        salida.append(f"     diferencia: {abs(d):.0f} kg/ha {signo} las avisadas"
                      + (f"  ({abs(dp):.0f} %)" if dp is not None else ""))
    if p is not None:
        salida.append(f"     p (una cola, exacta) = {p:.3f}"
                      + ("   los rangos NO se solapan" if not r["solapan"] else ""))
    if r["concluyente"] and d is not None and d < 0:
        salida.append("     -> EL UMBRAL SEPARA. Lo que el sistema marco se ve en la bascula.")
    elif d is not None and d >= 0:
        salida.append("     -> EL UMBRAL NO SEPARA: las avisadas rindieron igual o mas.")
        salida.append("        O el umbral esta mal puesto, o los avisos se corrigieron a tiempo.")
    else:
        salida.append("     -> NO CONCLUYENTE: la diferencia va en el sentido esperado pero")
        salida.append("        cabe dentro de lo que puede dar el azar con esta muestra.")
    return r


def _bloque_indice(casos_g, salida):
    """Regresion del indice en fase critica contra el rendimiento. Reutiliza
    `validacion.regresion`, que ya calcula R2, RMSE, pendiente y Pearson."""
    try:
        import validacion as V
    except Exception:
        return None                      # modulo opcional: sin el, este bloque no sale
    pares = [(c["ndvi_min_critica"], c["rendimiento"]) for c in casos_g
             if c["ndvi_min_critica"] is not None]
    reg = V.regresion(pares) if len(pares) >= 2 else None
    if not reg or reg.get("r2") is None:
        return None
    salida.append(f"     indice minimo en fase critica vs kg/ha:  R2={reg['r2']:.2f}  "
                  f"n={reg['n']}  error {reg['rmse']:.0f} kg/ha")
    if reg["r2"] < 0.3:
        salida.append("        (R2 bajo: el indice en fase critica no explica esta cosecha)")
    return reg


def informe(campana=None, referencia=HUMEDAD_REFERENCIA):
    """El informe entero, como lista de lineas."""
    lista, sin_cosecha = casos(campana, referencia)
    out = []
    out.append("=" * 78)
    out.append(" ¿LO QUE EL SISTEMA MARCA SE VE EN LA BASCULA?")
    out.append("=" * 78)
    out.append(f" Humedad de referencia: {referencia:.1f} %   "
               f"(no altera el contraste, solo los kg/ha que se leen)")
    out.append("")
    if not lista:
        out.append(" No hay ninguna campana con cosecha anotada Y pasadas de satelite.")
        out.append("")
        out.append(f" Campanas con pasadas pero SIN kg/ha: {sin_cosecha}.")
        out.append(" Sin kg/ha de bascula esta prueba no se puede hacer: es el unico dato")
        out.append(" del sistema que no sale de interpretar una imagen. Se anotan en el")
        out.append(" cuaderno de campo, en el evento de COSECHA o de SIEGA.")
        return out

    sin_h = [c for c in lista if not c["humedad_anotada"]]
    grupos = agrupa(lista)
    utiles = 0
    for (esp, camp), g in sorted(grupos.items()):
        r = _bloque_grupo(esp, camp, g, out)
        _bloque_indice(g, out)
        if r["muestra_suficiente"]:
            utiles += 1
        out.append("")

    out.append("-" * 78)
    out.append(f" {len(lista)} campana(s) con cosecha, en {len(grupos)} grupo(s) especie x campana.")
    out.append(f" Grupos con muestra suficiente para concluir: {utiles} de {len(grupos)}.")
    if sin_cosecha:
        out.append(f" Campanas descartadas por no tener kg/ha anotados: {sin_cosecha}.")
    if sin_h:
        out.append(f" ATENCION: {len(sin_h)} campana(s) sin humedad de grano anotada. Sus kg/ha")
        out.append(" entran SIN corregir, mezclados con los corregidos. Una diferencia de 4")
        out.append(" puntos de humedad son ~5 % de peso: puede ser mayor que lo que se busca.")
    if utiles == 0:
        out.append("")
        out.append(" NADA QUE CONCLUIR TODAVIA, y eso no es un fallo: es la respuesta correcta.")
        out.append(f" Hacen falta {MIN_POR_GRUPO} parcelas avisadas y {MIN_POR_GRUPO} sin aviso")
        out.append(" DE LA MISMA ESPECIE Y CAMPANA. Concentrar en una especie da resultado")
        out.append(" antes que repartir el esfuerzo entre todas.")
    return out


if __name__ == "__main__":       # pragma: no cover - utilidad de linea de comandos
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campana", default=None, help="solo esta campana (p.ej. 2025-2026)")
    ap.add_argument("--humedad-ref", type=float, default=HUMEDAD_REFERENCIA,
                    dest="href", help=f"humedad comercial de referencia (por defecto {HUMEDAD_REFERENCIA} %%)")
    args = ap.parse_args()
    import almacen as DB
    DB.conectar()
    for linea in informe(args.campana, args.href):
        print(linea)
    sys.exit(0)
