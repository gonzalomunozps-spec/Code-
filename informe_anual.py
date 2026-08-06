# -*- coding: utf-8 -*-
"""
informe_anual.py
================

Modulo OPCIONAL y DESACOPLADO: genera un INFORME ANUAL de una parcela en PDF, en
clave de BALANCE de toda la campana (la parcela contada a lo largo del ano), no un
estado puntual "de ahora".

Que incluye (todo se calcula con el motor real del programa):
  - Resumen narrativo de la campana.
  - Grafica de evolucion (NDVI, LAI, NDMI y, si hay, RVI de Sentinel-1).
  - Recorrido fenologico (fase estimada en cada pasada).
  - Hitos: maximo verdor, maxima biomasa, momento de menos agua, cierre.
  - Estado hidrico durante el ano.
  - Uniformidad de la parcela.
  - Intervenciones del cuaderno de campo y su efecto.
  - Corroboracion con radar (si se ha descargado Sentinel-1).
  - Valoracion general de la campana.

COMO QUITAR ESTA PARTE:
  Basta con BORRAR este fichero. El panel lo importa de forma tolerante
  (try/except): si no existe, el boton "Informe anual (PDF)" simplemente no
  aparece y el resto del programa sigue igual. No hay interruptor ni
  configuracion que tocar.

Dependencia: reportlab  (pip install reportlab). Si no esta instalado, el modulo
se carga igual pero DISPONIBLE = False, y el panel avisa de como instalarlo.
"""

import os
import math
from datetime import datetime

# --- motor real del programa (nucleo; estos modulos siempre estan) ---
from interpretacion_fenologica import evaluar_parcela
from contraste_indices import heterogeneidad
import registro_parcela as REG
try:
    import sentinel1 as S1
except Exception:
    S1 = None

# --- reportlab: dependencia propia de este modulo (tolerante) ---
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
                                    Table, TableStyle)
    from reportlab.graphics.shapes import Drawing, String, Rect
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.widgets.markers import makeMarker
    _RL = True
except Exception:
    _RL = False

DISPONIBLE = _RL
MOTIVO_NO_DISPONIBLE = ("" if _RL else
                        "Falta la libreria 'reportlab'. Instalala con:  pip install reportlab")

MESES = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
         7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre",
         12: "diciembre"}


# =====================================================================
# Helpers puros
# =====================================================================
def _fnat(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{d.day} de {MESES[d.month]}"
    except (TypeError, ValueError):
        return iso or "-"


def _superficie_ha(coords):
    if not coords or len(coords) < 3:
        return None
    pts = coords[:-1] if coords[0] == coords[-1] else coords
    lat0 = math.radians(sum(p[1] for p in pts) / len(pts))
    R = 6371000.0
    xy = [(math.radians(p[0]) * R * math.cos(lat0), math.radians(p[1]) * R) for p in pts]
    area = 0.0
    n = len(xy)
    for i in range(n):
        x1, y1 = xy[i]
        x2, y2 = xy[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return round(abs(area) / 2.0 / 10000.0, 2)


def _spec_de(cultivo):
    if not cultivo or not cultivo.get("especie"):
        return None
    return {"especie": cultivo.get("especie"), "fecha_siembra": cultivo.get("fecha_siembra"),
            "marco_calle": cultivo.get("marco_calle"), "marco_pie": cultivo.get("marco_pie")}


def _eventos_cerca(eventos, fecha_iso, ventana=20):
    """Replica local (sin BD) de eventos en los `ventana` dias previos a fecha_iso."""
    out = []
    if not fecha_iso:
        return out
    for e in eventos or []:
        f = e.get("fecha")
        if not f:
            continue
        try:
            d = (datetime.strptime(fecha_iso, "%Y-%m-%d")
                 - datetime.strptime(f, "%Y-%m-%d")).days
        except (TypeError, ValueError):
            continue
        if 0 <= d <= ventana:
            out.append((d, e))
    return sorted(out, key=lambda x: x[0])


def _num(serie, clave):
    return [r for r in serie if r.get(clave) is not None]


# =====================================================================
# API PUBLICA
# =====================================================================
def generar_informe_anual(nombre, campana, ficha, cultivo, serie,
                          radar=None, eventos=None, ruta_salida=None):
    """Genera el PDF y devuelve la ruta. Lanza RuntimeError si no se puede."""
    if not _RL:
        raise RuntimeError(MOTIVO_NO_DISPONIBLE)
    serie = sorted([r for r in (serie or []) if r.get("fecha")], key=lambda r: r["fecha"])
    if not serie:
        raise RuntimeError("La parcela no tiene pasadas de satelite: no hay campana que resumir.")
    radar = sorted([r for r in (radar or []) if r.get("fecha")], key=lambda r: r["fecha"])
    eventos = eventos or []
    if not ruta_salida:
        ruta_salida = os.path.abspath(f"Informe_{nombre}_{campana}.pdf")

    tipo = (cultivo or {}).get("tipo", "BARBECHO")
    sub = (cultivo or {}).get("subtipo", "")
    especie = (cultivo or {}).get("especie") or tipo.capitalize()
    spec = _spec_de(cultivo)
    coords = (ficha or {}).get("coordenadas")
    superficie = _superficie_ha(coords)
    propietario = (ficha or {}).get("propietario", "-")

    ndvi_serie = _num(serie, "ndvi")
    lai_serie = _num(serie, "lai")
    ndmi_serie = _num(serie, "ndmi")
    inicio, fin = serie[0], serie[-1]
    pico_ndvi = max(ndvi_serie, key=lambda r: r["ndvi"]) if ndvi_serie else None
    pico_lai = max(lai_serie, key=lambda r: r["lai"]) if lai_serie else None
    min_ndmi = min(ndmi_serie, key=lambda r: r["ndmi"]) if ndmi_serie else None

    # --- recorrido fenologico y alertas (motor real, pasada a pasada) ---
    recorrido = []
    avisos = []                      # [(indice, fecha, estado, fase)]
    for i in range(len(serie)):
        parcial = serie[:i + 1]
        evc = _eventos_cerca(eventos, serie[i].get("fecha"))
        d = evaluar_parcela(tipo, sub, parcial, eventos_cerca=evc or None, spec=spec)
        recorrido.append({"fecha": serie[i]["fecha"], "fase": d.get("fase", "-"),
                          "estado": d.get("estado", "-"), "esperado": d.get("esperado", False),
                          "ndvi": serie[i].get("ndvi"), "lai": serie[i].get("lai")})
        if d.get("estado") in ("Revisar", "Vigilar") and not d.get("esperado"):
            avisos.append((i, serie[i]["fecha"], d.get("estado"), d.get("fase")))

    # BALANCE RETROSPECTIVO: un aviso puntual queda "resuelto" si una pasada
    # POSTERIOR lo reencuadra en la fenologia (OK o caida esperada). Solo los que
    # siguen vigentes al cierre pesan en la valoracion general.
    alertas = []                     # [(fecha, estado, fase, resuelto)]
    for (i, fecha, estado, fase) in avisos:
        resuelto = any(recorrido[j]["esperado"] or recorrido[j]["estado"] == "OK"
                       for j in range(i + 1, len(recorrido)))
        alertas.append((fecha, estado, fase, resuelto))
    alertas_vigentes = [a for a in alertas if not a[3]]

    fases_orden = []
    for r in recorrido:
        if r["fase"] and (not fases_orden or fases_orden[-1][0] != r["fase"]):
            fases_orden.append((r["fase"], r["fecha"], r["ndvi"], r["lai"]))

    diag_final = evaluar_parcela(tipo, sub, serie, spec=spec)
    hetero = heterogeneidad(serie)

    # efecto de productos del cuaderno (herbicidas y demas)
    efectos = []
    for e in eventos:
        if e.get("tipo") == "PRODUCTO":
            ef = REG.efecto_producto(serie, e)
            if ef and ef.get("disponible"):
                efectos.append((e, ef))

    # radar
    radar_info = None
    if radar and S1 is not None:
        try:
            radar_info = S1.interpretar_radar(serie, radar, diag_final)
        except Exception:
            radar_info = None

    _construir_pdf(ruta_salida, locals())
    return ruta_salida


# =====================================================================
# Construccion del PDF
# =====================================================================
def _construir_pdf(ruta, ctx):
    HEADER = colors.HexColor("#1e3a2b"); PRIMARY = colors.HexColor("#2f855a")
    PRIMARY_DK = colors.HexColor("#276749"); INK = colors.HexColor("#1a202c")
    INK2 = colors.HexColor("#4a5568"); INK3 = colors.HexColor("#718096")
    BORDER = colors.HexColor("#e2e8f0"); PANEL = colors.HexColor("#f4f8f5")
    COL_NDVI = colors.HexColor("#2f855a"); COL_LAI = colors.HexColor("#dd6b20")
    COL_NDMI = colors.HexColor("#3182ce"); COL_RVI = colors.HexColor("#805ad5")

    serie = ctx["serie"]; radar = ctx["radar"]
    nombre = ctx["nombre"]; campana = ctx["campana"]; especie = ctx["especie"]
    propietario = ctx["propietario"]; superficie = ctx["superficie"]
    cultivo = ctx["cultivo"]; inicio = ctx["inicio"]; fin = ctx["fin"]
    pico_ndvi = ctx["pico_ndvi"]; pico_lai = ctx["pico_lai"]; min_ndmi = ctx["min_ndmi"]
    fases_orden = ctx["fases_orden"]; hetero = ctx["hetero"]; alertas = ctx["alertas"]
    alertas_vigentes = ctx["alertas_vigentes"]
    efectos = ctx["efectos"]; radar_info = ctx["radar_info"]; tipo = ctx["tipo"]

    def esc(s): return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    H1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=13, textColor=PRIMARY_DK,
                        spaceBefore=13, spaceAfter=5, leading=16)
    BODY = ParagraphStyle("BODY", fontName="Helvetica", fontSize=9.5, textColor=INK2,
                          leading=14.5, spaceAfter=5)
    SMALL = ParagraphStyle("SMALL", parent=BODY, fontSize=8.4, textColor=INK3, leading=11.5)
    CELL = ParagraphStyle("CELL", fontName="Helvetica", fontSize=8.6, textColor=INK, leading=11)
    LEAD = ParagraphStyle("LEAD", parent=BODY, fontSize=10.5, leading=15.5)
    WCELL = ParagraphStyle("WCELL", parent=CELL, textColor=colors.white, fontName="Helvetica-Bold")

    def H(t): return Paragraph(t, H1)
    def P(t): return Paragraph(t, BODY)

    def panel(flow, fill=PANEL, bd=BORDER, pad=9):
        t = Table([[flow]], colWidths=[168 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fill),
                               ("BOX", (0, 0), (-1, -1), 0.7, bd),
                               ("TOPPADDING", (0, 0), (-1, -1), pad),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
                               ("LEFTPADDING", (0, 0), (-1, -1), 11),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 11)]))
        return t

    def grafica():
        n = len(serie); xs = list(range(n)); fechas = [r["fecha"] for r in serie]

        def col(clave, factor=1.0):
            return [(i, serie[i][clave] * factor) for i in range(n) if serie[i].get(clave) is not None]

        data = [col("ndvi"), col("lai", 0.2), col("ndmi")]
        cols = [COL_NDVI, COL_LAI, COL_NDMI]
        rvi_pts = []
        if radar:
            for rr in radar:
                if rr.get("rvi") is None:
                    continue
                k = min(range(n), key=lambda i: abs(
                    (datetime.strptime(serie[i]["fecha"], "%Y-%m-%d")
                     - datetime.strptime(rr["fecha"], "%Y-%m-%d")).days))
                rvi_pts.append((k, rr["rvi"]))
            if rvi_pts:
                data.append(rvi_pts); cols.append(COL_RVI)

        d = Drawing(170 * mm, 76 * mm)
        lp = LinePlot(); lp.x = 14 * mm; lp.y = 15 * mm; lp.width = 150 * mm; lp.height = 52 * mm
        lp.data = data
        for i, c in enumerate(cols):
            lp.lines[i].strokeColor = c; lp.lines[i].strokeWidth = 2 if i == 0 else 1.6
            lp.lines[i].symbol = makeMarker("FilledCircle"); lp.lines[i].symbol.size = 3.2
            lp.lines[i].symbol.fillColor = c
        if len(cols) == 4:
            lp.lines[3].strokeDashArray = (3, 2)
        lp.xValueAxis.valueMin = -0.3; lp.xValueAxis.valueMax = n - 0.7; lp.xValueAxis.valueSteps = xs
        lp.xValueAxis.labelTextFormat = lambda v: (fechas[int(round(v))][5:] if 0 <= int(round(v)) < n else "")
        lp.xValueAxis.labels.fontSize = 6.5
        lp.yValueAxis.valueMin = -0.1; lp.yValueAxis.valueMax = 1.0; lp.yValueAxis.valueStep = 0.2
        lp.yValueAxis.labels.fontSize = 6.5
        d.add(lp)
        leg = [("NDVI (verdor)", COL_NDVI), ("LAI /5 (biomasa)", COL_LAI), ("NDMI (agua)", COL_NDMI)]
        if len(cols) == 4:
            leg.append(("RVI radar (estructura)", COL_RVI))
        x = 15 * mm
        for texto, c in leg:
            d.add(Rect(x, 70 * mm, 4 * mm, 2.2 * mm, fillColor=c, strokeColor=None))
            d.add(String(x + 5 * mm, 69.6 * mm, esc(texto), fontName="Helvetica", fontSize=7, fillColor=INK2))
            x += 41 * mm
        return d

    story = []
    story.append(Paragraph("Balance de la campa&ntilde;a",
                 ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=20, textColor=HEADER, leading=23)))
    story.append(Paragraph(f"{esc(nombre.replace('_', ' '))} &mdash; {esc(especie)} &middot; Campa&ntilde;a {esc(campana)}",
                 ParagraphStyle("s", fontName="Helvetica", fontSize=12, textColor=PRIMARY, leading=15)))
    story.append(HRFlowable(width="46%", thickness=2, color=PRIMARY, spaceBefore=6, spaceAfter=9, hAlign="LEFT"))

    siembra = (cultivo or {}).get("fecha_siembra")
    cab = [[Paragraph("<b>Propietario</b>", SMALL), Paragraph(esc(propietario), CELL),
            Paragraph("<b>Superficie</b>", SMALL),
            Paragraph(f"{superficie} ha" if superficie else "-", CELL)],
           [Paragraph("<b>Cultivo</b>", SMALL),
            Paragraph(esc(especie) + (f" (siembra {esc(siembra)})" if siembra else ""), CELL),
            Paragraph("<b>Periodo</b>", SMALL),
            Paragraph(f"{_fnat(inicio['fecha'])} &ndash; {_fnat(fin['fecha'])}", CELL)]]
    tc = Table(cab, colWidths=[26 * mm, 62 * mm, 24 * mm, 56 * mm])
    tc.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
                            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(tc)
    story.append(Spacer(1, 6))

    # ---- resumen narrativo (data-driven) ----
    frases = [f"A lo largo de la campana {esc(campana)}, la parcela {esc(nombre.replace('_', ' '))} "
              f"({esc(especie)}) fue seguida en {len(serie)} pasadas de satelite entre el "
              f"{_fnat(inicio['fecha'])} y el {_fnat(fin['fecha'])}."]
    if pico_ndvi and inicio.get("ndvi") is not None:
        f = (f"El verdor (NDVI) parti&oacute; de {inicio['ndvi']:.2f}, alcanz&oacute; su m&aacute;ximo de "
             f"{pico_ndvi['ndvi']:.2f} el {_fnat(pico_ndvi['fecha'])}")
        if pico_lai:
            f += f" (con un LAI de {pico_lai['lai']:.1f})"
        if fin.get("ndvi") is not None:
            f += f" y cerr&oacute; la campa&ntilde;a en {fin['ndvi']:.2f}."
        else:
            f += "."
        frases.append(f)
    if min_ndmi:
        frases.append(f"El &iacute;ndice de humedad (NDMI) tuvo su valor m&aacute;s bajo ({min_ndmi['ndmi']:+.2f}) el "
                      f"{_fnat(min_ndmi['fecha'])}.")
    if alertas_vigentes:
        frases.append(f"Al cierre de la campa&ntilde;a quedan {len(alertas_vigentes)} aviso(s) sin reencuadrar "
                      f"por la fenolog&iacute;a (ver m&aacute;s abajo), que conviene revisar.")
    elif alertas:
        frases.append(f"Hubo {len(alertas)} aviso(s) puntual(es) durante el a&ntilde;o, pero las pasadas "
                      f"posteriores los reencuadraron en la fenolog&iacute;a: la campa&ntilde;a cerr&oacute; sin incidencias vigentes.")
    else:
        frases.append("No se detectaron ca&iacute;das fuera de fase, focos localizados ni estr&eacute;s adelantado: "
                      "una evoluci&oacute;n coherente con la fenolog&iacute;a del cultivo de principio a fin.")
    story.append(panel(Paragraph(" ".join(frases), LEAD)))
    story.append(Spacer(1, 4))

    # ---- grafica ----
    story.append(H("La campa&ntilde;a de un vistazo"))
    story.append(grafica())
    story.append(Paragraph("Cada punto es una pasada de sat&eacute;lite. El LAI se muestra dividido por 5 para "
                           "compartir escala. En la aplicaci&oacute;n la gr&aacute;fica es interactiva, con tooltip.", SMALL))

    # ---- recorrido fenologico ----
    if fases_orden:
        story.append(H("Recorrido fenol&oacute;gico"))
        fil = [[Paragraph("Fase", WCELL), Paragraph("Desde", WCELL),
                Paragraph("NDVI", WCELL), Paragraph("LAI", WCELL)]]
        for fase, fecha, ndvi, lai in fases_orden:
            fil.append([Paragraph(esc(fase), CELL), Paragraph(_fnat(fecha), CELL),
                        Paragraph(f"{ndvi:.2f}" if ndvi is not None else "-", CELL),
                        Paragraph(f"{lai:.1f}" if lai is not None else "-", CELL)])
        tf = Table(fil, colWidths=[70 * mm, 44 * mm, 27 * mm, 27 * mm])
        tf.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), PRIMARY_DK),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PANEL]),
                                ("GRID", (0, 0), (-1, -1), 0.4, BORDER), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("ALIGN", (2, 0), (-1, -1), "CENTER"),
                                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(tf)
        story.append(Paragraph("El sistema estima la fase por especie y d&iacute;as desde la siembra; as&iacute; distingue "
                               "una ca&iacute;da propia de la fase (senescencia, corte) de un problema real.", SMALL))

    # ---- hitos ----
    hitos = []
    if pico_ndvi: hitos.append(("M&aacute;ximo verdor (NDVI)", f"{pico_ndvi['ndvi']:.2f}", _fnat(pico_ndvi["fecha"])))
    if pico_lai: hitos.append(("M&aacute;xima biomasa (LAI)", f"{pico_lai['lai']:.1f}", _fnat(pico_lai["fecha"])))
    if min_ndmi: hitos.append(("Momento de menos agua (NDMI)", f"{min_ndmi['ndmi']:+.2f}", _fnat(min_ndmi["fecha"])))
    if fin.get("ndvi") is not None:
        hitos.append(("Cierre de campa&ntilde;a (NDVI)", f"{fin['ndvi']:.2f}", _fnat(fin["fecha"])))
    if hitos:
        story.append(H("Hitos de la campa&ntilde;a"))
        hh = [[Paragraph(f"<b>{a}</b>", CELL),
               Paragraph(b, ParagraphStyle("v", parent=CELL, fontName="Helvetica-Bold", textColor=PRIMARY_DK)),
               Paragraph(esc(c), CELL)] for a, b, c in hitos]
        th = Table(hh, colWidths=[78 * mm, 40 * mm, 50 * mm])
        th.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(th)

    # ---- estado hidrico ----
    if min_ndmi and pico_ndvi:
        story.append(H("Estado h&iacute;drico durante el a&ntilde;o"))
        story.append(P(f"El &iacute;ndice de humedad (NDMI) acompa&ntilde;&oacute; al desarrollo del cultivo y toc&oacute; su valor "
                       f"m&aacute;s bajo ({min_ndmi['ndmi']:+.2f}) el {_fnat(min_ndmi['fecha'])}. La firma temprana de un "
                       f"estr&eacute;s h&iacute;drico ser&iacute;a un NDMI que cae ANTES y m&aacute;s r&aacute;pido que el NDVI; el motor la "
                       f"vigila pasada a pasada para poder avisar a tiempo."))

    # ---- uniformidad ----
    story.append(H("Uniformidad de la parcela"))
    if hetero and hetero.get("disponible"):
        story.append(P(f"Uniformidad: <b>{esc(hetero.get('uniformidad', '-'))}</b>. {esc(hetero.get('lectura', ''))}"))
    else:
        story.append(P("En las pasadas de esta campa&ntilde;a no se dispuso de estad&iacute;stica espacial interna, por lo "
                       "que el balance se hace sobre los valores medios. Cuando esa estad&iacute;stica est&aacute; disponible, "
                       "el sistema vigila si alg&uacute;n rodal se separa del conjunto (posible foco)."))

    # ---- intervenciones ----
    if efectos:
        story.append(H("Intervenciones del cuaderno de campo"))
        for e, ef in efectos:
            story.append(P(f"&bull;&nbsp; {esc(_fnat(e.get('fecha')))}: {esc(e.get('producto', '') or e.get('objetivo', ''))} "
                           f"&mdash; {esc(ef.get('verdicto', ''))}."))

    # ---- alertas del ano ----
    if alertas:
        story.append(H("Avisos registrados durante la campa&ntilde;a"))
        for fecha, estado, fase, resuelto in alertas:
            marca = (" <font color='#2f855a'>(reencuadrado por la fenolog&iacute;a en pasadas posteriores)</font>"
                     if resuelto else " <font color='#dd6b20'>(vigente al cierre)</font>")
            story.append(P(f"&bull;&nbsp; {esc(_fnat(fecha))}: <b>{esc(estado)}</b> en fase de {esc(fase)}.{marca}"))

    # ---- radar ----
    if radar_info and radar_info.get("disponible"):
        story.append(H("Corroboraci&oacute;n con radar (Sentinel-1)"))
        story.append(P(esc(radar_info.get("texto", ""))))

    # ---- valoracion general ----
    story.append(H("Valoraci&oacute;n general de la campa&ntilde;a"))
    if tipo == "BARBECHO":
        val = (f"Parcela en barbecho durante la campa&ntilde;a {esc(campana)}: no se eval&uacute;a el vigor de un cultivo. "
               "El seguimiento queda como registro del estado del suelo.")
    elif alertas_vigentes:
        val = (f"Campa&ntilde;a con {len(alertas_vigentes)} aviso(s) sin reencuadrar al cierre (ver secci&oacute;n de avisos). "
               f"El cultivo alcanz&oacute; un pico de NDVI de {pico_ndvi['ndvi']:.2f}"
               + (f" y un LAI de {pico_lai['lai']:.1f}" if pico_lai else "")
               + ". Revisa las fechas marcadas y contrasta con lo observado en campo.")
    else:
        val = (f"Campa&ntilde;a <b>favorable y sin incidencias vigentes</b> para {esc(especie)} en "
               f"{esc(nombre.replace('_', ' '))}. La parcela complet&oacute; el ciclo con un pico de vigor "
               f"de NDVI {pico_ndvi['ndvi']:.2f}"
               + (f" y LAI {pico_lai['lai']:.1f}" if pico_lai else "")
               + ". "
               + ("Los avisos puntuales del a&ntilde;o se reencuadraron en la fenolog&iacute;a en pasadas posteriores. "
                  if alertas else "")
               + "Evoluci&oacute;n coherente de principio a fin.")
    story.append(panel(Paragraph(val, LEAD), fill=colors.HexColor("#eef6ef")))

    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER, spaceBefore=2, spaceAfter=6))
    story.append(Paragraph(f"Informe generado por el Sistema de Gesti&oacute;n y Monitoreo de Parcelas el "
                           f"{datetime.now():%d-%m-%Y %H:%M}. Los &iacute;ndices proceden de Copernicus/Sentinel-2 "
                           f"(y Sentinel-1 si se ha descargado el radar). La interpretaci&oacute;n es orientativa: "
                           f"conviene contrastarla con la observaci&oacute;n en campo.", SMALL))

    def encpie(c, doc):
        c.saveState(); w, h = A4
        c.setStrokeColor(BORDER); c.setLineWidth(0.5); c.line(20 * mm, 14 * mm, w - 20 * mm, 14 * mm)
        c.setFont("Helvetica", 7.5); c.setFillColor(INK3)
        c.drawString(20 * mm, 9.5 * mm, f"Balance de campaña - {nombre.replace('_', ' ')} - {campana}")
        c.drawRightString(w - 20 * mm, 9.5 * mm, f"Pag. {doc.page}")
        c.restoreState()

    doc = SimpleDocTemplate(ruta, pagesize=A4, topMargin=16 * mm, bottomMargin=18 * mm,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            title=f"Balance de campana - {nombre}")
    doc.build(story, onFirstPage=encpie, onLaterPages=encpie)
