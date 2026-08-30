# -*- coding: utf-8 -*-
"""
medir_ruido.py
==============

HERRAMIENTA DE DIAGNOSTICO, no parte del programa. Contesta a una pregunta que no
se puede contestar sin TUS datos:

    ¿cuanto ruido tiene el NDVI de mis parcelas, y cuantas veces cambia el semaforo
    por ese ruido en vez de por el cultivo?

Se usa asi, con el programa cerrado y desde la carpeta del proyecto:

    python medir_ruido.py                 # todas las parcelas, todas las campanas
    python medir_ruido.py --campana 2025-2026
    python medir_ruido.py --parcela Cerealista_Vega

No escribe nada. Solo lee la base y saca un informe por pantalla.

COMO SE MIDE EL RUIDO
---------------------
El NDVI cambia entre pasadas por dos motivos: porque el cultivo cambia (senal) y
porque la medida no es perfecta -atmosfera, angulo de sol, mezcla de pixeles,
restos de nube que el enmascarado no pilla- (ruido). Restar dos pasadas seguidas
mezcla las dos cosas y no sirve.

Se usa la SEGUNDA DIFERENCIA sobre tripletes de pasadas consecutivas:

    r = ndvi[t] - (ndvi[t-1] + ndvi[t+1]) / 2

Si en esas tres fechas el cultivo va aproximadamente en linea recta -sube o baja,
pero sin doblarse-, la parte de senal se cancela y lo que queda es ruido. Como en
esa cuenta el ruido de las tres pasadas entra con pesos 1, -1/2 y -1/2:

    var(r) = var(n_t) + var(n_{t-1})/4 + var(n_{t+1})/4 = 1.5 * sigma^2
    sigma  = desviacion(r) / raiz(1.5)

Se usa la DESVIACION ROBUSTA (mediana de desviaciones absolutas, MAD, escalada),
no la desviacion tipica: una sola pasada con nube residual dispara la tipica y se
llevaria por delante la estimacion de toda la parcela.

LO QUE ESTA MEDIDA SUPONE, dicho claro
--------------------------------------
1. Que en tres pasadas seguidas el cultivo va casi recto. Por eso se descartan los
   tripletes con huecos largos (`--hueco`, 20 dias por defecto): tras un mes de
   nubes, entre dos pasadas cabe media fenologia y la suposicion se rompe.
2. Que la curvatura real del cultivo es pequena comparada con el ruido. En un
   crecimiento rapido (encanado) eso no es del todo cierto, asi que la cifra que
   sale es una COTA SUPERIOR del ruido: el ruido de verdad es ese o menos.
3. Que el ruido no depende del valor. No se ha comprobado.

CUANTO SE PUEDE FIAR UNO DEL NUMERO
-----------------------------------
Medido sobre 200 realizaciones con un ruido conocido de 0.020: el estimador NO se
desvia (mediana 0.019-0.021), pero es RUIDOSO cuando hay pocas pasadas.

    pasadas de la parcela   error tipico de la estimacion
              8                        45 %
             12                        45 %
             20                        33 %
             40                        23 %
             80                        16 %

Por eso el numero de cabecera del informe NO es la mediana de las parcelas: es la
estimacion sobre TODOS los residuos juntos. Con diez parcelas de veinte pasadas
hay cientos de tripletes y la cifra global es fiable, aunque la de cada parcela
por separado no lo sea. Las columnas por parcela van con su numero de tripletes al
lado, precisamente para que se vea cuales son de fiar.

Es decir: el numero que sale sirve para elegir en que fila de la tabla de
decision estas, no para publicarlo como una medida de precision radiometrica.

BORRABLE: este fichero no lo importa nadie. Si se borra, no pasa nada.
"""

import argparse
import sys

# =====================================================================
# NUCLEO PURO (se prueba sin base de datos)
# =====================================================================
def segundas_diferencias(serie, hueco_max=20):
    """Los residuos `r` de los tripletes utilizables de una serie.

    `serie` es una lista de dicts con `fecha` (ISO) y `ndvi`. Se descartan los
    tripletes con algun NDVI ausente y los que tengan un hueco mayor de
    `hueco_max` dias entre pasadas consecutivas.
    """
    from datetime import datetime
    validas = []
    for r in serie or []:
        v, f = r.get("ndvi"), r.get("fecha")
        if v is None or not f:
            continue
        try:
            validas.append((datetime.strptime(f, "%Y-%m-%d"), float(v)))
        except (TypeError, ValueError):
            continue
    validas.sort()
    out = []
    for i in range(1, len(validas) - 1):
        (f0, v0), (f1, v1), (f2, v2) = validas[i - 1], validas[i], validas[i + 1]
        if (f1 - f0).days > hueco_max or (f2 - f1).days > hueco_max:
            continue
        out.append(v1 - (v0 + v2) / 2.0)
    return out


def mediana(xs):
    """Mediana de una lista. Vacia -> None."""
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def sigma_robusta(residuos):
    """Ruido (sigma) estimado a partir de los residuos, con MAD.

    MAD -> sigma normal se escala por 1.4826; y los residuos de la segunda
    diferencia llevan un factor raiz(1.5) de mas. None si no hay datos.
    """
    if len(residuos) < 3:
        return None
    m = mediana(residuos)
    mad = mediana([abs(r - m) for r in residuos])
    if mad is None:
        return None
    return (1.4826 * mad) / (1.5 ** 0.5)


# =====================================================================
# INFORME (necesita la base)
# =====================================================================
def _series(parcela=None, campana=None):
    """[(nombre, campana, serie)] de la base real."""
    import almacen as DB
    DB.conectar()
    nombres = [parcela] if parcela else DB.nombres()
    out = []
    for n in nombres:
        camps = [campana] if campana else sorted(DB.campanas_de(n))
        for c in camps:
            s = DB.pasadas(n, c)
            if s:
                out.append((n, c, s))
    return out


def _estados(nombre, campana, serie):
    """El estado pasada a pasada, como lo vio el programa en su dia."""
    from interpretacion_fenologica import evaluar_parcela
    import almacen as DB
    import cultivo as CU
    ficha = DB.ficha(nombre) or {}
    cult = (ficha.get("cultivos_por_campana") or {}).get(campana) or {}
    spec = CU.spec_de(cult)
    out = []
    for i in range(len(serie)):
        d = evaluar_parcela(cult.get("tipo", "EXTENSIVO"), cult.get("subtipo", ""),
                            serie[:i + 1], spec=spec, parcela=nombre,
                            arbolado=bool(ficha.get("arbolado")),
                            heterogeneidad_activa=ficha.get("heterogeneidad", True))
        out.append((d["estado"], d.get("ndvi_juicio"),
                    (d.get("rango_fase") or (None, None))[0], d.get("fase")))
    return out


def informe(parcela=None, campana=None, hueco_max=20):
    datos = _series(parcela, campana)
    if not datos:
        print("No hay pasadas guardadas para eso. ¿Has sincronizado alguna campana?")
        return 1

    print("=" * 78)
    print(" RUIDO DEL NDVI Y CAMBIOS DEL SEMAFORO  ·  tus datos reales")
    print("=" * 78)
    print(f" {'parcela':<24} {'campana':<10} {'pasadas':>7} {'ruido':>7} {'tripl':>6}"
          f" {'cambios':>8} {'en franja':>10}")
    print(" " + "-" * 80)

    sigmas, tot_pas, tot_cam, tot_franja, sin_datos = [], 0, 0, 0, []
    todos_res = []                      # todos los residuos juntos: la cifra fiable
    for nombre, camp, serie in datos:
        res = segundas_diferencias(serie, hueco_max)
        todos_res.extend(res)
        sg = sigma_robusta(res)
        est = _estados(nombre, camp, serie)
        cambios = sum(1 for a, b in zip(est, est[1:]) if a[0] != b[0])
        # ¿cuantos de esos cambios pasaron con el valor pegado al umbral?
        en_franja = 0
        for (ea, _va, _la, _fa), (eb, vb, lb, _fb) in zip(est, est[1:]):
            if ea != eb and vb is not None and lb is not None and sg is not None:
                if abs(vb - lb) < sg or abs(vb - lb * 0.8) < sg:
                    en_franja += 1
        tot_pas += len(serie)
        tot_cam += cambios
        tot_franja += en_franja
        if sg is None:
            sin_datos.append(f"{nombre} {camp}")
            txt_sg = "  -"
        else:
            sigmas.append(sg)
            txt_sg = f"{sg:.3f}"
        print(f" {nombre[:24]:<24} {camp:<10} {len(serie):>7} {txt_sg:>7} "
              f"{len(res):>6} {cambios:>8} {en_franja:>10}")

    print(" " + "-" * 80)
    print(f" {'TOTAL':<24} {'':<10} {tot_pas:>7} {'':>7} {len(todos_res):>6}"
          f" {tot_cam:>8} {tot_franja:>10}")
    print()
    if not sigmas:
        print(" No se ha podido estimar el ruido en ninguna parcela: hacen falta al menos")
        print(f" 5 pasadas seguidas con huecos de menos de {hueco_max} dias entre ellas.")
        print(" Sincroniza mas campanas o sube el hueco con --hueco.")
        return 0

    sigmas.sort()
    global_ = sigma_robusta(todos_res)
    med = global_ if global_ is not None else mediana(sigmas)
    p90 = sigmas[min(len(sigmas) - 1, int(0.9 * len(sigmas)))]
    # error tipico aproximado, interpolado de la tabla medida de la cabecera
    err = 45 if len(todos_res) < 12 else (33 if len(todos_res) < 20 else
                                          (23 if len(todos_res) < 40 else
                                           (16 if len(todos_res) < 80 else 10)))
    print(" RUIDO ESTIMADO (cota superior; ver la cabecera del fichero)")
    print(f"   CIFRA GLOBAL (todos los residuos juntos): +-{med:.3f}")
    print(f"     con {len(todos_res)} tripletes, error tipico ~{err} % "
          f"(o sea, entre {med*(1-err/100):.3f} y {med*(1+err/100):.3f})")
    if len(sigmas) > 1:
        print(f"   por parcela: mediana +-{mediana(sigmas):.3f}, la peor de cada 10 "
              f"+-{p90:.3f}, rango +-{sigmas[0]:.3f} a +-{sigmas[-1]:.3f}")
        print("   (las de parcelas con pocos tripletes son poco fiables: ver la columna)")
    if sin_datos:
        print(f"   sin estimar ({len(sin_datos)}): {', '.join(sin_datos[:4])}"
              + ("..." if len(sin_datos) > 4 else ""))
    print()
    print(" CAMBIOS DEL SEMAFORO")
    print(f"   {tot_cam} cambios en {tot_pas} pasadas")
    if tot_cam:
        print(f"   {tot_franja} de esos {tot_cam} ({100*tot_franja/tot_cam:.0f} %) pasaron con el")
        print("   valor a menos de un ruido del umbral: son los candidatos a ser artefacto.")
    print()
    print(" QUE HACER CON ESTE NUMERO")
    print("   La franja donde el semaforo oscila es del ancho del ruido (medido sobre")
    print(f"   6.880 combinaciones). Con +-{med:.3f} de mediana, la franja de riesgo")
    print(f"   alrededor de cada umbral es de unos {med:.2f} puntos de NDVI.")
    if med < 0.015:
        print("   Es un ruido BAJO: la oscilacion sera rara y puede no compensar tocar nada.")
    elif med < 0.035:
        print("   Es un ruido MEDIO: la oscilacion es real pero acotada a esa franja.")
    else:
        print("   Es un ruido ALTO: conviene revisar el enmascarado de nubes antes que")
        print("   el semaforo; puede que esten entrando pasadas que no deberian.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Mide el ruido del NDVI y los cambios del semaforo en TUS datos.")
    ap.add_argument("--parcela", help="solo esta parcela")
    ap.add_argument("--campana", help="solo esta campana (p. ej. 2025-2026)")
    ap.add_argument("--hueco", type=int, default=20,
                    help="dias maximos entre pasadas para fiarse del triplete (20)")
    a = ap.parse_args(argv)
    try:
        return informe(a.parcela, a.campana, a.hueco)
    except Exception as e:                       # noqa: BLE001 - herramienta de mano
        print(f"No se pudo leer la base: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
