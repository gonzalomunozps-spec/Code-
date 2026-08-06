# -*- coding: utf-8 -*-
"""
demo_sistema.py
===============

DEMO AUTONOMA del sistema de gestion de parcelas, SIN satelite ni GUI.

Que hace:
  1. Genera series de indices SINTETICAS pero realistas para 6 parcelas, cada
     una pensada para ilustrar una capacidad distinta del motor de diagnostico.
  2. Ejecuta el motor REAL (interpretacion_fenologica.evaluar_parcela y
     texto_interpretacion, con respaldo por reglas si no hay OPENAI_API_KEY).
  3. Siembra los ficheros JSON que usa el panel (parcelas.json,
     historico_reportes.json, eventos_parcela.json), de modo que si luego
     ejecutas `python panel_gestion_parcelas.py` las parcelas ya salen cargadas.

Uso:
    python demo_sistema.py            # informe por consola + siembra los JSON
    python demo_sistema.py --no-seed  # solo informe, no escribe JSON

No necesita earthengine-api, tkinter ni matplotlib.
"""

import os
import sys
import json
from datetime import datetime

from interpretacion_fenologica import evaluar_parcela, texto_interpretacion
import registro_parcela as REG
import fenologia_especies as FEN
import almacen as DB       # los datos van ahora a SQLite (parcelas.db)


# ---------------------------------------------------------------------------
# Helpers puros (replicados del panel para no depender de tkinter)
# ---------------------------------------------------------------------------
def campana_actual(fecha=None):
    d = fecha or datetime.now()
    return f"{d.year}-{d.year + 1}" if d.month >= 9 else f"{d.year - 1}-{d.year}"


def superficie_ha(coords):
    # geometria compartida en geo.py; aqui solo se redondea (contrato de la demo)
    import geo
    return round(geo.superficie_ha(coords), 2)


def _reg(fecha, ndvi, evi, savi, gndvi, lai, msavi, ndmi, extra=None):
    """Construye un registro de pasada con el esquema que espera el motor."""
    r = {"fecha": fecha, "ndvi": ndvi, "evi": evi, "savi": savi, "gndvi": gndvi,
         "lai": lai, "msavi": msavi, "ndmi": ndmi, "cobertura_valida": 0.98}
    if extra:
        r.update(extra)
    return r


# ---------------------------------------------------------------------------
# ESCENARIOS (cada uno ilustra una capacidad del motor)
# ---------------------------------------------------------------------------
CAMPANA = campana_actual()
A0 = int(CAMPANA.split("-")[0])          # anio de inicio de campana (sep)
A1 = A0 + 1

# poligonos pequenos y verosimiles (lon, lat) en distintas zonas de Espana
POLIS = {
    "olivar":   [[-4.780, 37.880], [-4.776, 37.880], [-4.776, 37.883], [-4.780, 37.883]],
    "cereal":   [[-4.100, 41.650], [-4.093, 41.650], [-4.093, 41.654], [-4.100, 41.654]],
    "secano":   [[-2.520, 39.010], [-2.514, 39.010], [-2.514, 39.014], [-2.520, 39.014]],
    "almendra": [[-1.900, 38.400], [-1.895, 38.400], [-1.895, 38.404], [-1.900, 38.404]],
    "barbecho": [[-5.600, 38.900], [-5.596, 38.900], [-5.596, 38.903], [-5.600, 38.903]],
    "pradera":  [[-6.100, 43.100], [-6.096, 43.100], [-6.096, 43.103], [-6.100, 43.103]],
}


def escenarios():
    """Devuelve lista de dicts: parcela, ficha, cultivo, serie, eventos, nota."""
    S = []

    # --- A) OLIVAR con CUBIERTA VEGETAL entre calles (invierno-primavera) -----
    # El NDVI sube por la hierba entre calles, pero el MSAVI (robusto al suelo)
    # y el LAI no acompanan -> el motor detecta cubierta y juzga con MSAVI.
    serie_olivo = [
        _reg(f"{A0}-10-08", 0.44, 0.26, 0.34, 0.44, 1.10, 0.40, 0.14),
        _reg(f"{A0}-11-12", 0.46, 0.27, 0.35, 0.45, 1.05, 0.39, 0.16),
        _reg(f"{A0}-12-15", 0.50, 0.28, 0.37, 0.48, 1.00, 0.36, 0.20),
        _reg(f"{A1}-01-14", 0.56, 0.30, 0.40, 0.52, 0.98, 0.34, 0.22),
        _reg(f"{A1}-02-11", 0.62, 0.31, 0.44, 0.56, 0.96, 0.33, 0.24),
        _reg(f"{A1}-03-10", 0.68, 0.32, 0.47, 0.60, 0.98, 0.33, 0.23),
    ]
    S.append({
        "parcela": "Olivar_La_Serna",
        "ficha": {"propietario": "Coop. San Isidro",
                  "coordenadas": POLIS["olivar"] + [POLIS["olivar"][0]]},
        "cultivo": {"tipo": "LENOSO", "especie": "OLIVO",
                    "marco_calle": 5.0, "marco_pie": 4.0},
        "serie": serie_olivo, "eventos": [],
        "nota": "Cubierta vegetal: el NDVI se dispara pero MSAVI/LAI no; se juzga la copa con MSAVI.",
    })

    # --- B) TRIGO: ciclo completo hasta SENESCENCIA (caida NORMAL) ------------
    # La fuerte bajada de junio es maduracion, no un problema: el motor debe
    # reconocer la fase y NO dar alarma.
    serie_trigo = [
        _reg(f"{A0}-12-05", 0.22, 0.16, 0.20, 0.25, 0.6, 0.24, 0.18),
        _reg(f"{A1}-01-10", 0.38, 0.24, 0.32, 0.38, 1.2, 0.35, 0.24),
        _reg(f"{A1}-02-12", 0.55, 0.34, 0.46, 0.52, 2.1, 0.50, 0.30),
        _reg(f"{A1}-03-16", 0.72, 0.45, 0.60, 0.64, 3.2, 0.62, 0.34),
        _reg(f"{A1}-04-15", 0.80, 0.52, 0.68, 0.70, 3.8, 0.66, 0.30),
        _reg(f"{A1}-05-14", 0.66, 0.44, 0.58, 0.62, 3.0, 0.55, 0.18),
        _reg(f"{A1}-06-12", 0.34, 0.22, 0.30, 0.40, 1.3, 0.30, 0.06),
    ]
    S.append({
        "parcela": "Cerealista_Vega",
        "ficha": {"propietario": "Hnos. Vega",
                  "coordenadas": POLIS["cereal"] + [POLIS["cereal"][0]]},
        "cultivo": {"tipo": "EXTENSIVO", "especie": "TRIGO",
                    "fecha_siembra": f"{A0}-11-10"},
        "serie": serie_trigo, "eventos": [],
        "nota": "Senescencia: caida fuerte de NDVI en junio, coherente con la fase -> sin alarma.",
    })

    # --- C) SECANO (cebada): ESTRES HIDRICO temprano -------------------------
    # El NDMI cae ANTES y mas rapido que el NDVI: firma temprana de estres.
    serie_secano = [
        _reg(f"{A0}-12-06", 0.24, 0.17, 0.21, 0.26, 0.7, 0.25, 0.16),
        _reg(f"{A1}-01-11", 0.42, 0.26, 0.34, 0.40, 1.4, 0.39, 0.20),
        _reg(f"{A1}-02-13", 0.58, 0.36, 0.49, 0.55, 2.3, 0.53, 0.24),
        _reg(f"{A1}-03-17", 0.68, 0.44, 0.58, 0.63, 3.0, 0.60, 0.10),
        _reg(f"{A1}-04-16", 0.70, 0.45, 0.60, 0.64, 3.1, 0.61, -0.05),
    ]
    S.append({
        "parcela": "Secano_El_Alto",
        "ficha": {"propietario": "Finca El Alto",
                  "coordenadas": POLIS["secano"] + [POLIS["secano"][0]]},
        "cultivo": {"tipo": "EXTENSIVO", "especie": "CEBADA",
                    "fecha_siembra": f"{A0}-11-18"},
        "serie": serie_secano, "eventos": [],
        "nota": "Estres hidrico: el NDMI se hunde mientras el NDVI aun aguanta.",
    })

    # --- D) ALMENDRO: deterioro LOCALIZADO (posible foco) --------------------
    # La media cae y la dispersion interna (std) SUBE: firma de foco (rodal,
    # hongo o plaga). Se aportan std y percentiles del NDVI.
    serie_almendro = [
        _reg(f"{A1}-03-12", 0.40, 0.26, 0.34, 0.44, 1.4, 0.38, 0.18,
             {"ndvi_std": 0.05, "ndvi_p10": 0.35, "ndvi_p50": 0.40,
              "ndvi_p90": 0.46, "n_pixeles": 820}),
        _reg(f"{A1}-04-10", 0.52, 0.34, 0.44, 0.52, 2.0, 0.48, 0.20,
             {"ndvi_std": 0.06, "ndvi_p10": 0.45, "ndvi_p50": 0.52,
              "ndvi_p90": 0.60, "n_pixeles": 820}),
        _reg(f"{A1}-04-27", 0.44, 0.28, 0.37, 0.47, 1.6, 0.41, 0.14,
             {"ndvi_std": 0.16, "ndvi_p10": 0.22, "ndvi_p50": 0.47,
              "ndvi_p90": 0.62, "n_pixeles": 820}),
    ]
    S.append({
        "parcela": "Almendral_Norte",
        "ficha": {"propietario": "Agro Levante S.L.",
                  "coordenadas": POLIS["almendra"] + [POLIS["almendra"][0]]},
        "cultivo": {"tipo": "LENOSO", "especie": "ALMENDRO",
                    "marco_calle": 6.0, "marco_pie": 5.0},
        "serie": serie_almendro, "eventos": [],
        "nota": "Deterioro LOCALIZADO: la media baja y la dispersion sube -> posible foco puntual.",
    })

    # --- E) BARBECHO: no se evalua vigor (estado N.A.) -----------------------
    serie_barbecho = [
        _reg(f"{A1}-02-10", 0.14, 0.09, 0.12, 0.16, 0.3, 0.15, 0.05),
        _reg(f"{A1}-03-14", 0.18, 0.11, 0.15, 0.19, 0.4, 0.18, 0.08),
    ]
    S.append({
        "parcela": "Barbecho_Sur",
        "ficha": {"propietario": "Dehesa del Sur",
                  "coordenadas": POLIS["barbecho"] + [POLIS["barbecho"][0]]},
        "cultivo": {"tipo": "BARBECHO"},
        "serie": serie_barbecho, "eventos": [],
        "nota": "Barbecho: el motor devuelve N.A. y no interpreta el vigor.",
    })

    # --- F) PRADERA de siega: una SIEGA registrada explica la caida ----------
    # Sin el evento seria una falsa alarma; con el cuaderno pasa a ser normal.
    serie_pradera = [
        _reg(f"{A1}-02-12", 0.55, 0.36, 0.47, 0.54, 2.4, 0.50, 0.22),
        _reg(f"{A1}-03-16", 0.70, 0.46, 0.60, 0.64, 3.1, 0.60, 0.26),
        _reg(f"{A1}-04-14", 0.36, 0.24, 0.31, 0.42, 1.3, 0.33, 0.16),
    ]
    S.append({
        "parcela": "Pradera_Rio",
        "ficha": {"propietario": "Ganaderia Ribera",
                  "coordenadas": POLIS["pradera"] + [POLIS["pradera"][0]]},
        "cultivo": {"tipo": "EXTENSIVO", "subtipo": "SIEGA_VERDE", "especie": "AVENA",
                    "fecha_siembra": f"{A0}-10-05"},
        "serie": serie_pradera,
        "eventos": [{"fecha": f"{A1}-04-08", "tipo": "SIEGA",
                     "notas": "Primer corte de la temporada"}],
        "nota": "Siega registrada en el cuaderno: explica la caida de NDVI -> deja de ser alarma.",
    })

    return S


# ---------------------------------------------------------------------------
# SIEMBRA DE LOS JSON DEL PANEL
# ---------------------------------------------------------------------------
def sembrar(escen):
    """Siembra las parcelas de la demo en la base de datos SQLite (parcelas.db)."""
    DB.conectar()
    for e in escen:
        nombre, cultivo = e["parcela"], dict(e["cultivo"])
        # subtipo canonico (igual que hace el panel al dar de alta)
        if cultivo["tipo"] == "LENOSO" and cultivo.get("marco_calle"):
            dens = FEN.densidad_arboles(cultivo["marco_calle"], cultivo["marco_pie"])
            cultivo.setdefault("subtipo", FEN.subtipo_canonico(cultivo.get("especie", "OLIVO"), dens))
        elif cultivo["tipo"] == "EXTENSIVO":
            cultivo.setdefault("subtipo", "COSECHA_GRANO")
        else:
            cultivo.setdefault("subtipo", "")

        ficha = dict(e["ficha"])
        ficha["superficie_ha"] = superficie_ha(ficha["coordenadas"])
        ficha["anio_inicio_monitoreo"] = CAMPANA
        ficha["cultivos_por_campana"] = {CAMPANA: cultivo}

        DB.eliminar_parcela(nombre)          # limpio, para que reejecutar no duplique
        DB.guardar_ficha(nombre, ficha)
        DB.anadir_pasadas(nombre, CAMPANA, e["serie"])
        for ev in e["eventos"]:
            REG.registrar_evento(nombre, CAMPANA, ev)


# ---------------------------------------------------------------------------
# INFORME POR CONSOLA
# ---------------------------------------------------------------------------
SEMAFORO = {"OK": "\U0001F7E2", "Vigilar": "\U0001F7E1", "Revisar": "\U0001F534",
            "N.A.": "⚪", "Sin dato": "⬜"}


def informe(escen):
    print("=" * 78)
    print(f"  DEMO - Gestion de Parcelas  ·  Campana {CAMPANA}  ·  {len(escen)} parcelas")
    print("=" * 78)
    for e in escen:
        nombre = e["parcela"]
        cultivo = e["cultivo"]
        tipo = cultivo["tipo"]
        subtipo = cultivo.get("subtipo", "")
        if tipo == "LENOSO" and cultivo.get("marco_calle"):
            dens = FEN.densidad_arboles(cultivo["marco_calle"], cultivo["marco_pie"])
            subtipo = FEN.subtipo_canonico(cultivo.get("especie", "OLIVO"), dens)
        elif tipo == "EXTENSIVO" and not subtipo:
            subtipo = "COSECHA_GRANO"

        spec = None
        if cultivo.get("especie"):
            spec = {"especie": cultivo.get("especie"),
                    "fecha_siembra": cultivo.get("fecha_siembra"),
                    "marco_calle": cultivo.get("marco_calle"),
                    "marco_pie": cultivo.get("marco_pie")}

        serie = e["serie"]
        fecha = serie[-1]["fecha"]
        # eventos cercanos calculados EN MEMORIA (no dependemos del JSON, asi la
        # demo da el mismo resultado con o sin --no-seed)
        eventos_cerca = []
        for ev in e["eventos"]:
            dd = (datetime.strptime(fecha, "%Y-%m-%d")
                  - datetime.strptime(ev["fecha"], "%Y-%m-%d")).days
            if 0 <= dd <= 20:
                eventos_cerca.append((dd, ev))

        diag = evaluar_parcela(tipo, subtipo, serie, fecha,
                               eventos_cerca=eventos_cerca, spec=spec)
        texto, _ = texto_interpretacion(tipo, subtipo, serie, fecha,
                                        eventos_cerca=eventos_cerca, spec=spec)

        sem = SEMAFORO.get(diag["estado"], "⬜")
        print()
        print("-" * 78)
        esp = f" · {cultivo['especie']}" if cultivo.get("especie") else ""
        print(f" {sem}  {nombre.replace('_', ' ')}   [{tipo}{esp}]   ultima pasada: {fecha}")
        print("-" * 78)
        print(f"   Estado:  {diag['estado']}        Fase: {diag['fase']}")
        rango = diag.get("rango_fase")
        if rango:
            print(f"   Rango NDVI esperado en fase: {rango[0]:.2f} - {rango[1]:.2f}"
                  f"   |   NDVI de juicio: {diag.get('ndvi_juicio')}")
        c = diag.get("cubierta")
        if c and c.get("señales", 0) >= 2:
            print(f"   Cubierta: {c['hipotesis_preliminar']} ({c['señales']}/4 senales)")
        het = diag.get("heterogeneidad")
        if het and het.get("patron"):
            print(f"   Heterogeneidad: {het['patron']}")
        print(f"   Interpretacion: {texto}")
        print(f"   → (demo) {e['nota']}")
    print()
    print("=" * 78)


def main():
    escen = escenarios()
    informe(escen)
    if "--no-seed" not in sys.argv:
        sembrar(escen)
        print("Sembradas las parcelas de la demo en la base de datos (parcelas.db).")
        print("Abre el panel con:")
        print("    python panel_gestion_parcelas.py")
        print("y las parcelas de la demo apareceran ya cargadas.")
    else:
        print("(--no-seed) No se ha tocado la base de datos.")


if __name__ == "__main__":
    main()
