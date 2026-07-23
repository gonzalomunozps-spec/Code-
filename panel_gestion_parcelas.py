# -*- coding: utf-8 -*-
"""
panel_gestion_parcelas.py  (edicion con tema profesional)
=========================================================

Misma funcionalidad que la version anterior, con una CAPA DE ESTILO nueva:
paleta coherente (verdes + gris pizarra), tipografia cuidada, tablas y botones
planos, tarjetas con borde fino, insignias de estado con color y graficas
matplotlib a juego.

INTEGRACION
    from panel_gestion_parcelas import PanelGestionParcelas, aplicar_tema
    root = tk.Tk()
    aplicar_tema(root)                 # <- aplica el tema a toda la app
    nb = ttk.Notebook(root); nb.pack(fill="both", expand=True)
    nb.add(PanelGestionParcelas(nb), text="  Gestion de Parcelas  ")
    root.mainloop()

DEPENDENCIAS
    pip install earthengine-api tkintermapview pillow matplotlib requests
    (opcional)  pip install openai   +   export OPENAI_API_KEY=...
    earthengine authenticate
"""

import os
import io
import re
import json
import math
import tempfile
import threading
from datetime import datetime, timedelta

import requests
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import tkinter.font as tkfont

try:
    from PIL import Image, ImageTk
    _PIL = True
except Exception:
    _PIL = False
try:
    import tkintermapview
    _MAPVIEW = True
except Exception:
    _MAPVIEW = False
try:
    import ee
    _EE = True
except Exception:
    _EE = False

import matplotlib
matplotlib.use("TkAgg")
import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.colors as mcolors

# La interpretacion (y la llamada opcional a ChatGPT) viven en
# interpretacion_fenologica; el panel no habla con OpenAI directamente.

# Modulo de interpretacion fenologica + deteccion de cubierta vegetal (IA)
from interpretacion_fenologica import evaluar_parcela, texto_interpretacion
import registro_parcela as REG
import fenologia_especies as FEN
import credenciales as CRED


# =====================================================================
# TEMA / SISTEMA DE DISENO
# =====================================================================
TEMA = {
    "page":        "#eef1f4",
    "surface":     "#ffffff",
    "surface_alt": "#f7fafc",
    "border":      "#e2e8f0",
    "border_soft": "#edf2f7",
    "header_bg":   "#1e3a2b",
    "header_sub":  "#a7c4b5",
    "primary":     "#2f855a",
    "primary_dk":  "#276749",
    "text":        "#1a202c",
    "text_sec":    "#4a5568",
    "text_muted":  "#718096",
    "ok_fg": "#276749", "ok_bg": "#f0fff4",
    "warn_fg": "#c05621", "warn_bg": "#fffaf0",
    "danger_fg": "#c53030", "danger_bg": "#fff5f5",
    "muted_fg": "#718096", "muted_bg": "#edf2f7",
}

FUENTES = {}


def _familia_disponible(root, candidatas):
    disp = set(tkfont.families(root))
    for c in candidatas:
        if c in disp:
            return c
    return "TkDefaultFont"


def aplicar_tema(root):
    """Configura ttk.Style, fuentes y matplotlib. Llamar una vez tras crear la ventana."""
    fam = _familia_disponible(root, ["Segoe UI", "Helvetica Neue", "Inter",
                                     "Roboto", "DejaVu Sans", "Arial"])
    FUENTES["fam"] = fam
    FUENTES["h1"] = tkfont.Font(family=fam, size=15, weight="bold")
    FUENTES["h2"] = tkfont.Font(family=fam, size=12, weight="bold")
    FUENTES["body"] = tkfont.Font(family=fam, size=10)
    FUENTES["small"] = tkfont.Font(family=fam, size=9)

    root.configure(bg=TEMA["page"])
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except Exception:
        pass

    st.configure(".", background=TEMA["page"], foreground=TEMA["text"],
                 font=FUENTES["body"], borderwidth=0)
    st.configure("TFrame", background=TEMA["page"])
    st.configure("Card.TFrame", background=TEMA["surface"])
    st.configure("TLabel", background=TEMA["page"], foreground=TEMA["text"])

    st.configure("TButton", background=TEMA["surface"], foreground=TEMA["text"],
                 bordercolor=TEMA["border"], relief="flat", padding=(12, 7),
                 font=FUENTES["body"])
    st.map("TButton", background=[("active", TEMA["surface_alt"])],
           bordercolor=[("focus", TEMA["primary"])])
    st.configure("Accent.TButton", background=TEMA["primary"], foreground="#ffffff",
                 relief="flat", padding=(14, 8), font=FUENTES["body"])
    st.map("Accent.TButton", background=[("active", TEMA["primary_dk"]),
                                         ("pressed", TEMA["primary_dk"])])
    st.configure("Ghost.TButton", background=TEMA["header_bg"], foreground="#ffffff",
                 relief="flat", padding=(10, 6))
    st.map("Ghost.TButton", background=[("active", "#2a5540")])

    for cls in ("TEntry", "TCombobox"):
        st.configure(cls, fieldbackground=TEMA["surface"], background=TEMA["surface"],
                     bordercolor=TEMA["border"], foreground=TEMA["text"],
                     arrowcolor=TEMA["text_muted"], padding=6, relief="flat")
        st.map(cls, bordercolor=[("focus", TEMA["primary"])],
               fieldbackground=[("readonly", TEMA["surface"])])

    st.configure("Treeview", background=TEMA["surface"], fieldbackground=TEMA["surface"],
                 foreground=TEMA["text"], rowheight=30, borderwidth=0, font=FUENTES["body"])
    st.configure("Treeview.Heading", background=TEMA["surface_alt"],
                 foreground=TEMA["text_muted"], relief="flat", padding=(10, 8),
                 font=tkfont.Font(family=fam, size=10, weight="bold"))
    st.map("Treeview.Heading", background=[("active", TEMA["border_soft"])])
    st.map("Treeview", background=[("selected", "#d7ecdf")],
           foreground=[("selected", TEMA["text"])])

    st.configure("TNotebook", background=TEMA["page"], borderwidth=0)
    st.configure("TNotebook.Tab", background=TEMA["page"], foreground=TEMA["text_muted"],
                 padding=(16, 9), font=FUENTES["body"])
    st.map("TNotebook.Tab", background=[("selected", TEMA["surface"])],
           foreground=[("selected", TEMA["primary_dk"])])

    st.configure("Vertical.TScrollbar", background=TEMA["border"], troughcolor=TEMA["page"],
                 bordercolor=TEMA["page"], arrowcolor=TEMA["text_muted"])

    mpl.rcParams.update({
        "font.size": 9,
        "figure.facecolor": TEMA["surface"], "axes.facecolor": TEMA["surface"],
        "axes.edgecolor": "#cbd5e0", "axes.linewidth": 0.8,
        "axes.grid": True, "grid.color": TEMA["border_soft"], "grid.linewidth": 0.9,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.titlesize": 10, "axes.titleweight": "bold",
        "text.color": TEMA["text"], "axes.labelcolor": TEMA["text_sec"],
        "xtick.color": TEMA["text_muted"], "ytick.color": TEMA["text_muted"],
        "legend.frameon": False,
    })
    return st


def tarjeta(parent, **kw):
    return tk.Frame(parent, bg=TEMA["surface"], highlightbackground=TEMA["border"],
                    highlightcolor=TEMA["border"], highlightthickness=1, bd=0, **kw)


def _colores_estado(clave):
    return {"OK": (TEMA["ok_fg"], TEMA["ok_bg"]),
            "Vigilar": (TEMA["warn_fg"], TEMA["warn_bg"]),
            "Revisar": (TEMA["danger_fg"], TEMA["danger_bg"])}.get(
        clave, (TEMA["muted_fg"], TEMA["muted_bg"]))


# =====================================================================
# PERSISTENCIA
# =====================================================================
ARCHIVO_PARCELAS  = "parcelas.json"
ARCHIVO_HISTORICO = "historico_reportes.json"
ARCHIVO_MEMORIA   = "registro_multi_parcelas.json"
ARCHIVO_ESTADO    = "estado_sync.json"        # marca del ultimo sync (para el arranque)
DIR_MAPAS         = "cache_mapas"

for _f in (ARCHIVO_PARCELAS, ARCHIVO_HISTORICO, ARCHIVO_MEMORIA):
    if not os.path.exists(_f):
        with open(_f, "w") as fh:
            json.dump({}, fh, indent=4)
os.makedirs(DIR_MAPAS, exist_ok=True)


# =====================================================================
# INDICES (definicion, rangos y paletas)
# =====================================================================
PAL_VEG = ['a50026', 'd73027', 'f46d43', 'fdae61', 'fee08b',
           'ffffbf', 'd9ef8b', 'a6d96a', '66bd63', '1a9850', '006837']
PAL_HUM = ['8c510a', 'bf812d', 'dfc27d', 'f6e8c3', 'f7f7f7',
           'c7eae5', '80cdc1', '35978f', '01665e']
INDICES = {
    "NDVI":  {"rango": (0.0, 0.9),  "paleta": PAL_VEG},
    "EVI":   {"rango": (0.0, 1.0),  "paleta": PAL_VEG},
    "SAVI":  {"rango": (0.0, 1.0),  "paleta": PAL_VEG},
    "GNDVI": {"rango": (0.0, 0.9),  "paleta": PAL_VEG},
    "LAI":   {"rango": (0.0, 6.0),  "paleta": PAL_VEG},
    "MSAVI": {"rango": (0.0, 0.9),  "paleta": PAL_VEG},
    "NDMI":  {"rango": (-0.5, 0.5), "paleta": PAL_HUM},
}
INDICES_ORDEN = ["NDVI", "EVI", "SAVI", "GNDVI", "LAI", "MSAVI", "NDMI"]

# Resoluciones de descarga del mapa: (etiqueta, metros por pixel)
# 10 m = nativo de Sentinel-2 en B2/B3/B4/B8. NDMI y MSAVI usan B11 (20 m nativos),
# asi que por debajo de 20 m esos dos indices se remuestrean, no ganan detalle real.
RESOLUCIONES = [
    ("5 m (sobremuestreo)", 5),
    ("10 m (nativo S2)", 10),
    ("20 m (rapido)", 20),
    ("60 m (vista rapida)", 60),
]
MAX_PIXELES = 2048          # tope por lado, para no pedir imagenes gigantes a GEE


def dimensiones_para(coords, metros_px):
    """Tamano en pixeles del lado mayor para servir la parcela a `metros_px` m/pixel."""
    lons = [p[0] for p in coords]
    lats = [p[1] for p in coords]
    lat0 = math.radians(sum(lats) / len(lats))
    ancho_m = (max(lons) - min(lons)) * 111320.0 * math.cos(lat0)
    alto_m = (max(lats) - min(lats)) * 110540.0
    lado_m = max(ancho_m, alto_m, 1.0)
    return int(max(64, min(MAX_PIXELES, round(lado_m / max(1, metros_px)))))

# Los umbrales de vigor ya no son fijos por cultivo: se calculan por FASE
# fenologica en interpretacion_fenologica / fenologia_especies (rango esperado
# de NDVI segun especie, fecha y marco). Aqui solo quedan los nombres visibles.
SUBTIPOS = {"EXTENSIVO": ["SIEGA_VERDE", "COSECHA_GRANO"],
            "LENOSO": ["TRADICIONAL", "INTENSIVO", "SUPERINTENSIVO"], "BARBECHO": []}
NOMBRE_CULTIVO = {
    "LENOSO_TRADICIONAL": "Olivar tradicional", "LENOSO_INTENSIVO": "Olivar intensivo",
    "LENOSO_SUPERINTENSIVO": "Olivar superintensivo",
    "EXTENSIVO_SIEGA_VERDE": "Extensivo (siega verde)",
    "EXTENSIVO_COSECHA_GRANO": "Extensivo (grano)", "BARBECHO": "Barbecho",
}


# =====================================================================
# HELPERS CAMPANA / GEOMETRIA / GEE
# =====================================================================
def campana_actual(fecha=None):
    d = fecha or datetime.now()
    return f"{d.year}-{d.year + 1}" if d.month >= 9 else f"{d.year - 1}-{d.year}"


def rango_campana(campana):
    a0, a1 = [int(x) for x in campana.split("-")]
    return f"{a0}-09-01", f"{a1}-08-31"


def superficie_ha(coords):
    if not coords or len(coords) < 3:
        return 0.0
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
    return abs(area) / 2.0 / 10000.0


def clave_cultivo(tipo, subtipo):
    return tipo if tipo == "BARBECHO" else f"{tipo}_{subtipo}"


def nombre_seguro(nombre):
    """Nombre de parcela seguro para usar como clave y en rutas de fichero:
    espacios a '_' y se descartan caracteres problematicos (/, \\, :, etc.)."""
    n = (nombre or "").strip().replace(" ", "_")
    n = re.sub(r"[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ_\-]", "", n)
    return n or "parcela"


def spec_de(cultivo):
    """Extrae el modelo por especie del registro de cultivo (o None si es antiguo)."""
    if not cultivo or not cultivo.get("especie"):
        return None
    return {"especie": cultivo.get("especie"),
            "fecha_siembra": cultivo.get("fecha_siembra"),
            "marco_calle": cultivo.get("marco_calle"),
            "marco_pie": cultivo.get("marco_pie")}


def construir_indice(img, indice):
    nir, red, green, blue = img.select("B8"), img.select("B4"), img.select("B3"), img.select("B2")
    if indice == "NDVI":
        return img.normalizedDifference(["B8", "B4"]).rename("IDX")
    if indice == "GNDVI":
        return img.normalizedDifference(["B8", "B3"]).rename("IDX")
    if indice == "NDMI":
        return img.normalizedDifference(["B8", "B11"]).rename("IDX")
    if indice == "SAVI":
        return img.expression("((NIR-RED)/(NIR+RED+0.5))*1.5", {"NIR": nir, "RED": red}).rename("IDX")
    if indice == "EVI":
        return img.expression("2.5*((NIR-RED)/(NIR+6.0*RED-7.5*BLUE+1.0))",
                              {"NIR": nir, "RED": red, "BLUE": blue}).rename("IDX")
    if indice == "MSAVI":
        return img.expression("(2*NIR+1-sqrt((2*NIR+1)**2-8*(NIR-RED)))/2",
                              {"NIR": nir, "RED": red}).rename("IDX")
    if indice == "LAI":
        evi = img.expression("2.5*((NIR-RED)/(NIR+6.0*RED-7.5*BLUE+1.0))",
                             {"NIR": nir, "RED": red, "BLUE": blue})
        return evi.expression("3.618*EVI-0.118", {"EVI": evi}).rename("IDX")
    return img.normalizedDifference(["B8", "B4"]).rename("IDX")


# =====================================================================
# PERSISTENCIA JSON (atomica y tolerante)
# =====================================================================
# El estado y la interpretacion se calculan en interpretacion_fenologica
# (evaluar_parcela / texto_interpretacion). Aqui solo se persiste y se pinta.

# Un unico cerrojo para todas las lecturas/escrituras de los JSON: el auto-sync
# y el worker de interpretacion corren en hilos aparte y tocan los mismos
# ficheros; sin esto podrian pisarse y perder datos.
_IO_LOCK = threading.RLock()


def _load(path):
    """Lectura tolerante: si el fichero falta o esta corrupto, devuelve {} en vez
    de reventar (p. ej. un JSON a medio escribir por un corte anterior)."""
    with _IO_LOCK:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {}


def _save(path, data):
    """Escritura ATOMICA: se vuelca a un temporal y se reemplaza de golpe con
    os.replace. Asi un corte a mitad nunca deja el JSON corrupto (o esta el
    fichero viejo intacto, o el nuevo completo)."""
    with _IO_LOCK:
        carpeta = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=carpeta)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise


def _actualizar(path, mutador):
    """Read-modify-write serializado: relee el fichero MAS RECIENTE bajo cerrojo,
    aplica el cambio y lo guarda. Evita que dos hilos que cargaron el JSON en
    momentos distintos se pisen al guardar (auto-sync vs. worker de IA)."""
    with _IO_LOCK:
        data = _load(path)
        mutador(data)
        _save(path, data)


# --- marca de tiempo del ultimo sync (persistente, para decidir en el arranque) ---
def _marca_sync_leer():
    """Devuelve el ISO del ultimo sync realizado, o None si no hay."""
    return _load(ARCHIVO_ESTADO).get("ultima_comprobacion")


def _marca_sync_guardar():
    _save(ARCHIVO_ESTADO, {"ultima_comprobacion": datetime.now().isoformat(timespec="seconds")})


def _toca_sincronizar(ultima_iso, intervalo_ms, ahora=None):
    """True si nunca se sincronizo o si ya ha pasado el intervalo desde entonces.
    Funcion pura (sin ficheros): asi el arranque solo sincroniza cuando toca."""
    if not ultima_iso:
        return True
    try:
        ult = datetime.fromisoformat(ultima_iso)
    except (TypeError, ValueError):
        return True
    ahora = ahora or datetime.now()
    return (ahora - ult).total_seconds() * 1000.0 >= intervalo_ms


# Cada cuanto se comprueba AUTOMATICAMENTE si hay pasadas nuevas del satelite.
# Sentinel-2 repite orbita cada ~5 dias (menos aun con nubes), asi que no hace
# falta mirar a menudo. Ademas se sincroniza al abrir la app y se puede forzar a
# mano en cualquier momento (boton "Sincronizar ahora" o desde cada ficha).
DIAS_AUTOSYNC = 1                            # pon 2 para comprobar cada dos dias
INTERVALO_AUTOSYNC_MS = DIAS_AUTOSYNC * 24 * 60 * 60 * 1000

# Resultado de la ultima sincronizacion (la automatica es silenciosa; esto deja
# constancia de si fallo, para poder mostrarlo en la pestana de Credenciales).
ULTIMO_SYNC = {"estado": None, "msg": "aun no se ha sincronizado"}


def sincronizar_parcela(nombre, campana, silencioso=True):
    """
    Sincronizacion INCREMENTAL: mira hasta que fecha hay datos guardados y solo
    descarga las pasadas nuevas del satelite con nubosidad < 20 %, sin sobrescribir.
    Devuelve (n_nuevos, mensaje).
    """
    if not _EE:
        ULTIMO_SYNC.update(estado="fallo", msg="earthengine-api no disponible")
        return (0, "earthengine-api no disponible")
    try:
        ficha = _load(ARCHIVO_PARCELAS).get(nombre)
        if not ficha or not ficha.get("coordenadas"):
            return (0, "parcela sin geometria")

        geom = ee.Geometry.Polygon(ficha["coordenadas"])
        ini_camp, fin_camp = rango_campana(campana)

        hist = _load(ARCHIVO_HISTORICO)
        existentes = hist.get(nombre, {}).get(campana, [])
        # solo fechas presentes: un registro sin fecha metia None en el set y
        # max() reventaba (str vs None), dejando el sync roto para siempre.
        fechas_existentes = {r.get("fecha") for r in existentes if r.get("fecha")}
        ultima = max(fechas_existentes) if fechas_existentes else None

        # ventana incremental: desde el dia siguiente a la ultima fecha guardada
        try:
            inicio = ((datetime.strptime(ultima, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                      if ultima else ini_camp)
        except ValueError:                    # fecha guardada mal formada: re-escanea la campana
            inicio = ini_camp
        hoy = datetime.now().strftime("%Y-%m-%d")
        fin = min(fin_camp, hoy)
        if inicio > fin:
            return (0, "ya esta al dia")

        col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
               .filterBounds(geom).filterDate(inicio, fin)
               .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))   # prefiltro amplio;
               .sort("system:time_start", True))                       # el SCL decide de verdad

        def feat(img):
            # --- 1. ENMASCARADO DE NUBES CON SCL (por pixel, no por escena) ---
            # La banda SCL clasifica cada pixel. Nos quedamos solo con lo utilizable:
            #   4 = vegetacion, 5 = suelo desnudo, 6 = agua, 7 = nube baja probabilidad,
            #   11 = nieve/hielo.  Se DESCARTAN:
            #   0 = sin dato, 1 = saturado/defectuoso, 2 = sombra oscura, 3 = sombra de nube,
            #   8 = nube media prob., 9 = nube alta prob., 10 = cirros.
            scl = img.select("SCL")
            valido = (scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7)))
            img_m = img.updateMask(valido)

            comp = img_m
            for k in INDICES_ORDEN:
                comp = comp.addBands(construir_indice(img_m, k).rename(k))

            # --- 2. COBERTURA VALIDA DENTRO DE LA PARCELA ---
            # Fraccion de pixeles de la parcela que sobreviven al enmascarado.
            # Es la nubosidad REAL sobre la finca, no la de la escena entera.
            cobertura = (valido.rename("OK").unmask(0)
                         .reduceRegion(ee.Reducer.mean(), geom, scale=10, bestEffort=True)
                         .get("OK"))

            # --- 3. ESTADISTICA INTRAPARCELA: media + desviacion + percentiles ---
            # La media sola oculta la heterogeneidad. Con la desviacion y los percentiles
            # se detecta si una PARTE de la parcela va mucho peor que el resto.
            reductor = (ee.Reducer.mean()
                        .combine(ee.Reducer.stdDev(), sharedInputs=True)
                        .combine(ee.Reducer.percentile([10, 25, 50, 75, 90]), sharedInputs=True)
                        .combine(ee.Reducer.count(), sharedInputs=True))
            m = comp.reduceRegion(reductor, geom, scale=10, bestEffort=True)

            props = {"fecha": img.date().format("yyyy-MM-dd"),
                     "cobertura_valida": cobertura}
            for k in INDICES_ORDEN:
                props[k.lower()] = m.get(k + "_mean")
            # estadistica espacial completa solo del NDVI (es el indice de referencia)
            props["ndvi_std"] = m.get("NDVI_stdDev")
            props["ndvi_p10"] = m.get("NDVI_p10")
            props["ndvi_p25"] = m.get("NDVI_p25")
            props["ndvi_p50"] = m.get("NDVI_p50")
            props["ndvi_p75"] = m.get("NDVI_p75")
            props["ndvi_p90"] = m.get("NDVI_p90")
            props["n_pixeles"] = m.get("NDVI_count")
            return ee.Feature(None, props)

        data = col.map(feat).getInfo()["features"]
        # el getInfo ha ido bien -> la conexion con GEE funciona
        ULTIMO_SYNC.update(estado="ok", msg="conexion con GEE correcta")

        # --- 4. FILTRO DE VALIDEZ POR PARCELA (no por escena) ---
        # Se acepta la pasada solo si al menos el 80 % de los pixeles de la parcela
        # son validos tras el SCL (es decir, <20 % de nube/sombra SOBRE LA FINCA).
        nuevos, descartadas = [], 0
        for f in data:
            p = f["properties"]
            fecha = p.get("fecha")
            cob = p.get("cobertura_valida")
            if not fecha or fecha in fechas_existentes:
                continue
            if cob is None or cob < 0.80 or not p.get("ndvi"):
                descartadas += 1
                continue
            p["cobertura_valida"] = round(cob, 3)
            nuevos.append(p)

        if not nuevos:
            msg = "sin pasadas nuevas fiables"
            if descartadas:
                msg += f" ({descartadas} descartadas por nube/sombra sobre la parcela)"
            return (0, msg)

        # anadir sin sobrescribir. Se relee el historico MAS RECIENTE bajo cerrojo
        # (no el que se cargo antes de la descarga de GEE) para no pisar cambios
        # que otro hilo haya guardado entretanto (p. ej. una interpretacion).
        def _merge(hist_actual):
            previos = hist_actual.get(nombre, {}).get(campana, [])
            combinado = {r["fecha"]: r for r in previos}      # conserva lo ya guardado
            for r in nuevos:
                combinado.setdefault(r["fecha"], r)
            hist_actual.setdefault(nombre, {})[campana] = [combinado[f] for f in sorted(combinado)]

        _actualizar(ARCHIVO_HISTORICO, _merge)
        return (len(nuevos), f"anadidas {len(nuevos)} fechas nuevas")
    except Exception as e:
        ULTIMO_SYNC.update(estado="fallo", msg=f"{e}")
        if not silencioso:
            raise
        return (0, f"error: {e}")


# =====================================================================
# PANEL PRINCIPAL
# =====================================================================
class PanelGestionParcelas(ttk.Frame):
    def __init__(self, master, *a, **k):
        super().__init__(master, *a, **k)
        self.campana = campana_actual()

        self.contenedor = tk.Frame(self, bg=TEMA["page"])
        self.contenedor.pack(fill="both", expand=True)
        self.vista_lista = tk.Frame(self.contenedor, bg=TEMA["page"])
        self.vista_ficha = tk.Frame(self.contenedor, bg=TEMA["page"])

        self._build_cabecera()
        self._build_barra()
        self._build_lista()
        self.mostrar_lista()

        # Relevo de campana (1 de septiembre) + import automatico periodico
        self.after(400, self._comprobar_relevo_campana)
        self.after(1500, self._auto_sync)

    # ---------------------------------------------------------- relevo de campana
    def _comprobar_relevo_campana(self):
        """Al entrar en una campana nueva, pide el cultivo de las parcelas ya existentes
        que aun no lo tengan asignado para la campana activa."""
        parcelas = _load(ARCHIVO_PARCELAS)
        pendientes = [n for n, f in parcelas.items()
                      if self.campana not in f.get("cultivos_por_campana", {})]
        if parcelas and pendientes:
            DialogoRelevoCampana(self, pendientes)

    def asignar_cultivo(self, nombre, tipo, spec):
        parcelas = _load(ARCHIVO_PARCELAS)
        if nombre in parcelas:
            spec = dict(spec or {})
            subtipo = ""
            if tipo == "LENOSO" and spec.get("marco_calle"):
                dens = FEN.densidad_arboles(spec["marco_calle"], spec["marco_pie"])
                subtipo = FEN.subtipo_canonico(spec.get("especie", "OLIVO"), dens)
            elif tipo == "EXTENSIVO":
                subtipo = "COSECHA_GRANO"
            cultivo = {"tipo": tipo, "subtipo": subtipo}
            cultivo.update(spec)
            parcelas[nombre].setdefault("cultivos_por_campana", {})[self.campana] = cultivo
            _save(ARCHIVO_PARCELAS, parcelas)
        self._refrescar()

    # ---------------------------------------------------------- import automatico
    def _auto_sync(self):
        """Se ejecuta al ARRANCAR y luego de forma periodica. Solo sincroniza si
        toca (nunca se sincronizo o ya paso el intervalo desde el ultimo sync);
        asi, abrir la app varias veces el mismo dia no repite, pero si han pasado
        los dias configurados, al iniciarse se pone al dia sola."""
        if _EE and _toca_sincronizar(_marca_sync_leer(), INTERVALO_AUTOSYNC_MS):
            threading.Thread(target=self._sync_todas, daemon=True).start()
        self.after(INTERVALO_AUTOSYNC_MS, self._auto_sync)

    def _sync_todas(self):
        total = 0
        for nombre in _load(ARCHIVO_PARCELAS):
            n, _ = sincronizar_parcela(nombre, self.campana, silencioso=True)
            total += n
        if ULTIMO_SYNC.get("estado") != "fallo":     # solo marca la hora si conecto
            _marca_sync_guardar()
        self.after(0, self._actualizar_estado_sync)   # refleja exito/fallo del auto-sync
        if total:
            self.after(0, self._refrescar)

    def _build_cabecera(self):
        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x", side="top")
        # indicador de estado de la sincronizacion (siempre visible, a la derecha)
        der = tk.Frame(cab, bg=TEMA["header_bg"])
        der.pack(side="right", padx=18)
        self.lbl_sync = tk.Label(der, text="○ GEE: sin sincronizar", bg=TEMA["header_bg"],
                                 fg=TEMA["header_sub"], font=FUENTES["small"], cursor="hand2")
        self.lbl_sync.pack(side="right", pady=14)
        self.lbl_sync.bind("<Button-1>", lambda e: self._detalle_sync())
        izq = tk.Frame(cab, bg=TEMA["header_bg"])
        izq.pack(side="left", fill="x")
        tk.Label(izq, text="Gestion y Monitoreo de Parcelas", bg=TEMA["header_bg"],
                 fg="#ffffff", font=FUENTES["h1"]).pack(anchor="w", padx=18, pady=(12, 0))
        tk.Label(izq, text="Ecosistema Copernicus  -  Sentinel-2", bg=TEMA["header_bg"],
                 fg=TEMA["header_sub"], font=FUENTES["small"]).pack(anchor="w", padx=18, pady=(0, 12))

    # colores legibles sobre la cabecera verde oscura
    _SYNC_COLOR = {"ok": "#86efac", "fallo": "#fca5a5", None: TEMA["header_sub"]}
    _SYNC_TEXTO = {"ok": "● GEE: conectado", "fallo": "● GEE: fallo",
                   None: "○ GEE: sin sincronizar"}

    def _actualizar_estado_sync(self):
        """Refresca el indicador de la cabecera a partir de ULTIMO_SYNC."""
        if not hasattr(self, "lbl_sync"):
            return
        est = ULTIMO_SYNC.get("estado")
        self.lbl_sync.config(text=self._SYNC_TEXTO.get(est, self._SYNC_TEXTO[None]),
                             fg=self._SYNC_COLOR.get(est, self._SYNC_COLOR[None]))

    def _detalle_sync(self):
        est = ULTIMO_SYNC.get("estado")
        msg = ULTIMO_SYNC.get("msg", "")
        if est == "fallo":
            messagebox.showerror("Sincronizacion Copernicus", f"La ultima sincronizacion fallo:\n\n{msg}")
        elif est == "ok":
            messagebox.showinfo("Sincronizacion Copernicus", f"Conexion con Google Earth Engine correcta.\n{msg}")
        else:
            messagebox.showinfo("Sincronizacion Copernicus",
                                "Aun no se ha sincronizado en esta sesion.")

    def _build_barra(self):
        barra = tk.Frame(self, bg=TEMA["page"])
        barra.pack(fill="x", padx=18, pady=12)

        camp = tarjeta(barra)
        camp.pack(side="left")
        tk.Label(camp, text=" Campana ", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left", padx=(6, 0), pady=4)
        self.cb_campana = ttk.Combobox(camp, state="readonly", width=11, values=self._campanas())
        self.cb_campana.set(self.campana)
        self.cb_campana.pack(side="left", padx=6, pady=4)
        self.cb_campana.bind("<<ComboboxSelected>>",
                             lambda e: (setattr(self, "campana", self.cb_campana.get()),
                                        self._refrescar()))

        centro = tarjeta(barra)
        centro.pack(side="left", fill="x", expand=True, padx=10)
        tk.Label(centro, text="  \U0001F50D  ", bg=TEMA["surface"],
                 fg=TEMA["text_muted"]).pack(side="left")
        self.entry_buscar = tk.Entry(centro, bd=0, bg=TEMA["surface"], fg=TEMA["text"],
                                     font=FUENTES["body"], insertbackground=TEMA["text"])
        self.entry_buscar.pack(side="left", fill="x", expand=True, padx=4, pady=6, ipady=2)
        self.entry_buscar.bind("<KeyRelease>", lambda e: self._refrescar())
        tk.Label(centro, text="Ordenar", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left", padx=(6, 2))
        self.cb_orden = ttk.Combobox(centro, state="readonly", width=13,
                                     values=["nombre", "superficie", "propietario",
                                             "anio_inicio", "estado"])
        self.cb_orden.set("estado")
        self.cb_orden.pack(side="left", padx=6, pady=4)
        self.cb_orden.bind("<<ComboboxSelected>>", lambda e: self._refrescar())

        ttk.Button(barra, text="  + Nueva parcela  ", style="Accent.TButton",
                   command=self.abrir_alta_parcela).pack(side="right")
        self.btn_sync = ttk.Button(barra, text="  ↻ Sincronizar ahora  ",
                                   command=self._sincronizar_ahora)
        self.btn_sync.pack(side="right", padx=(0, 8))

    def _sincronizar_ahora(self):
        """Sincronizacion manual de TODAS las parcelas, por si hay alguna pasada
        nueva antes de la comprobacion automatica."""
        if not _EE:
            return messagebox.showwarning(
                "Sincronizacion", "earthengine-api no disponible. Configura la conexion "
                "en la pestana 'Credenciales'.")
        self.btn_sync.config(text="  ↻ Sincronizando…  ", state="disabled")
        self.lbl_sync.config(text="↻ GEE: sincronizando…", fg=TEMA["header_sub"])
        threading.Thread(target=self._sync_todas_notificando, daemon=True).start()

    def _sync_todas_notificando(self):
        total, n_par = 0, 0
        for nombre in _load(ARCHIVO_PARCELAS):
            n, _ = sincronizar_parcela(nombre, self.campana, silencioso=True)
            total += n
            n_par += 1
        if ULTIMO_SYNC.get("estado") != "fallo":
            _marca_sync_guardar()

        def fin():
            self.btn_sync.config(text="  ↻ Sincronizar ahora  ", state="normal")
            self._actualizar_estado_sync()
            self._refrescar()
            if ULTIMO_SYNC.get("estado") == "fallo":
                messagebox.showerror("Sincronizacion",
                                     f"No se pudo sincronizar con Copernicus:\n\n{ULTIMO_SYNC.get('msg','')}")
            elif total:
                messagebox.showinfo("Sincronizacion",
                                    f"{n_par} parcela(s) revisadas. {total} pasada(s) nueva(s) anadida(s).")
            else:
                messagebox.showinfo("Sincronizacion",
                                    f"{n_par} parcela(s) revisadas. Sin pasadas nuevas por ahora.")
        self.after(0, fin)

    def _campanas(self):
        c = {campana_actual()}
        for _, camps in _load(ARCHIVO_HISTORICO).items():
            c.update(camps.keys())
        for _, ficha in _load(ARCHIVO_PARCELAS).items():
            c.update(ficha.get("cultivos_por_campana", {}).keys())
        return sorted(c, reverse=True)

    def _build_lista(self):
        wrap = tarjeta(self.vista_lista)
        wrap.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        cols = ("nombre", "cultivo", "superficie", "propietario", "estado")
        titulos = {"nombre": "Nombre", "cultivo": "Cultivo", "superficie": "Superficie",
                   "propietario": "Propietario", "estado": "Estado"}
        anchos = {"nombre": 220, "cultivo": 200, "superficie": 120,
                  "propietario": 200, "estado": 130}
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=titulos[c])
            self.tree.column(c, width=anchos[c], anchor="e" if c == "superficie" else "w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        sb.pack(side="right", fill="y", pady=1)

        self.tree.tag_configure("par", background=TEMA["surface"])
        self.tree.tag_configure("impar", background="#fcfdfe")
        for clave in ("OK", "Vigilar", "Revisar"):
            self.tree.tag_configure(f"est_{clave}", foreground=_colores_estado(clave)[0])
        self.tree.tag_configure("est_NA", foreground=TEMA["text_muted"])
        self.tree.tag_configure("est_SinAsig", foreground=TEMA["text_muted"])
        self.tree.bind("<Double-1>", self._abrir_ficha_sel)
        self.tree.bind("<Button-3>", self._menu_ctx)

    def mostrar_lista(self):
        self.vista_ficha.pack_forget()
        self.vista_lista.pack(fill="both", expand=True)
        self._refrescar()

    def _refrescar(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        texto = self.entry_buscar.get().lower() if hasattr(self, "entry_buscar") else ""
        orden = self.cb_orden.get() if hasattr(self, "cb_orden") else "nombre"
        parcelas = _load(ARCHIVO_PARCELAS)
        historico = _load(ARCHIVO_HISTORICO)   # una sola lectura (antes: una por parcela)

        filas = []
        for nombre, ficha in parcelas.items():
            if texto and texto not in nombre.lower() and texto not in ficha.get("propietario", "").lower():
                continue
            cult = ficha.get("cultivos_por_campana", {}).get(self.campana)
            if cult is None:                              # sin cultivo asignado en esta campana
                cc, clave, txt = "SIN_ASIGNAR", "SinAsig", "Sin asignar"
            elif cult.get("tipo") == "BARBECHO":          # barbecho -> no aplica vigor
                cc, clave, txt = "BARBECHO", "NA", "N.A."
            else:
                cc = clave_cultivo(cult.get("tipo"), cult.get("subtipo", ""))
                serie = sorted(historico.get(nombre, {}).get(self.campana, []),
                               key=lambda r: r.get("fecha", ""))
                diag = evaluar_parcela(cult.get("tipo"), cult.get("subtipo", ""), serie,
                                       spec=spec_de(cult))
                clave, txt = diag["clave"], diag["estado"]
            filas.append({"nombre": nombre.replace("_", " "),
                          "cultivo": NOMBRE_CULTIVO.get(cc, "Sin asignar" if cc == "SIN_ASIGNAR"
                                                        else cc.replace("_", " ").title()),
                          "superficie": f"{ficha.get('superficie_ha', 0.0):.2f} ha",
                          "_sup": ficha.get("superficie_ha", 0.0),
                          "propietario": ficha.get("propietario", ""),
                          "estado": txt, "_clave": clave})

        sev = {"Revisar": 0, "Vigilar": 1, "OK": 2, "Sin dato": 3, "N.A.": 4, "Sin asignar": 5}
        keys = {"superficie": lambda r: -r["_sup"],
                "propietario": lambda r: r["propietario"].lower(),
                "estado": lambda r: sev.get(r["estado"], 9),
                "nombre": lambda r: r["nombre"].lower()}
        filas.sort(key=keys.get(orden, keys["nombre"]))

        for k, r in enumerate(filas):
            tags = ("par" if k % 2 == 0 else "impar", f"est_{r['_clave']}")
            dot = "\u25CF " if r["_clave"] in ("OK", "Vigilar", "Revisar") else ""
            self.tree.insert("", tk.END, tags=tags,
                             values=(r["nombre"], r["cultivo"], r["superficie"],
                                     r["propietario"], dot + r["estado"]))

    def _menu_ctx(self, event):
        fila = self.tree.identify_row(event.y)
        if not fila:
            return
        self.tree.selection_set(fila)
        m = tk.Menu(self, tearoff=0, bg=TEMA["surface"], fg=TEMA["text"],
                    activebackground=TEMA["surface_alt"], bd=0)
        m.add_command(label="  Abrir ficha", command=lambda: self._abrir_ficha_sel(None))
        m.add_separator()
        m.add_command(label="  Eliminar parcela", command=self._eliminar_sel)
        m.tk_popup(event.x_root, event.y_root)

    def _eliminar_sel(self):
        sel = self.tree.selection()
        if not sel:
            return
        nombre = self.tree.item(sel[0], "values")[0].replace(" ", "_")
        if not messagebox.askyesno("Eliminar", f"Eliminar la parcela '{nombre}' y su historico?"):
            return
        for path in (ARCHIVO_PARCELAS, ARCHIVO_HISTORICO):
            d = _load(path)
            d.pop(nombre, None)
            _save(path, d)
        self._refrescar()

    def abrir_alta_parcela(self):
        VentanaAltaParcela(self)

    def guardar_parcela(self, nombre, propietario, tipo, spec, coords):
        parcelas = _load(ARCHIVO_PARCELAS)
        cerrado = coords + [coords[0]] if coords and coords[0] != coords[-1] else coords
        ficha = parcelas.get(nombre, {})
        ficha.update({"propietario": propietario, "coordenadas": cerrado,
                      "superficie_ha": superficie_ha(cerrado),
                      "anio_inicio_monitoreo": ficha.get("anio_inicio_monitoreo", self.campana)})
        # subtipo derivado (compatibilidad y visualizacion):
        #   leñoso -> tipo de plantacion segun el marco; cereal -> COSECHA_GRANO
        spec = dict(spec or {})
        subtipo = ""
        if tipo == "LENOSO" and spec.get("marco_calle"):
            dens = FEN.densidad_arboles(spec["marco_calle"], spec["marco_pie"])
            subtipo = FEN.subtipo_canonico(spec.get("especie", "OLIVO"), dens)
        elif tipo == "EXTENSIVO":
            subtipo = "COSECHA_GRANO"
        cultivo = {"tipo": tipo, "subtipo": subtipo}
        cultivo.update(spec)          # especie, fecha_siembra, marco_calle, marco_pie
        ficha.setdefault("cultivos_por_campana", {})[self.campana] = cultivo
        parcelas[nombre] = ficha
        _save(ARCHIVO_PARCELAS, parcelas)
        self.cb_campana["values"] = self._campanas()
        self._refrescar()

    def _abrir_ficha_sel(self, _):
        sel = self.tree.selection()
        if sel:
            self.mostrar_ficha(self.tree.item(sel[0], "values")[0].replace(" ", "_"))

    def mostrar_ficha(self, nombre):
        self.vista_lista.pack_forget()
        for w in self.vista_ficha.winfo_children():
            w.destroy()
        self.vista_ficha.pack(fill="both", expand=True)
        FichaParcela(self.vista_ficha, self, nombre, self.campana)

    def _historico(self, nombre):
        return _load(ARCHIVO_HISTORICO).get(nombre, {}).get(self.campana, [])

    def _ultimo_valido(self, nombre, clave):
        regs = sorted(self._historico(nombre), key=lambda r: r.get("fecha", ""))
        for r in reversed(regs):
            if r.get(clave) is not None:
                return r[clave]
        return None


# =====================================================================
# VENTANA DE ALTA
# =====================================================================
class VentanaAltaParcela(tk.Toplevel):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.title("Nueva parcela")
        self.geometry("1000x600")
        self.configure(bg=TEMA["page"])
        self.coords = []
        self.poligono = None

        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        tk.Label(cab, text="Nueva parcela", bg=TEMA["header_bg"], fg="#fff",
                 font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=10)

        cuerpo = tk.Frame(self, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=14, pady=14)

        form = tarjeta(cuerpo, width=360)
        form.pack(side="left", fill="y")
        form.pack_propagate(False)
        pad = {"padx": 16}

        def etiqueta(t):
            tk.Label(form, text=t, bg=TEMA["surface"], fg=TEMA["text_sec"],
                     font=FUENTES["small"]).pack(anchor="w", **pad)

        tk.Label(form, text="Datos de la parcela", bg=TEMA["surface"], fg=TEMA["text"],
                 font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 8))
        etiqueta("Nombre")
        self.e_nombre = ttk.Entry(form)
        self.e_nombre.pack(fill="x", **pad)
        etiqueta("Propietario")
        self.e_prop = ttk.Entry(form)
        self.e_prop.pack(fill="x", pady=(0, 6), **pad)

        fila = tk.Frame(form, bg=TEMA["surface"])
        fila.pack(fill="x", **pad)
        colt = tk.Frame(fila, bg=TEMA["surface"])
        colt.pack(side="left", fill="x", expand=True)
        tk.Label(colt, text="Tipo", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w")
        self.cb_tipo = ttk.Combobox(colt, state="readonly",
                                    values=["EXTENSIVO", "LENOSO", "BARBECHO"])
        self.cb_tipo.pack(fill="x")
        self.cb_tipo.bind("<<ComboboxSelected>>", self._sub)
        cols = tk.Frame(fila, bg=TEMA["surface"])
        cols.pack(side="left", fill="x", expand=True, padx=(8, 0))
        tk.Label(cols, text="Especie", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w")
        self.cb_sub = ttk.Combobox(cols, state="readonly", values=[])
        self.cb_sub.pack(fill="x")

        # campos especificos de la especie: siembra (cereal) o marco (leñoso)
        self.frame_spec = tk.Frame(form, bg=TEMA["surface"])
        self.frame_spec.pack(fill="x", **pad)
        # siembra
        self.lbl_siembra = tk.Label(self.frame_spec, text="Fecha de siembra (AAAA-MM-DD)",
                                    bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.e_siembra = ttk.Entry(self.frame_spec)
        # marco
        self.lbl_marco = tk.Label(self.frame_spec, text="Marco de plantacion (calle x pie, m)",
                                  bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.marco_wrap = tk.Frame(self.frame_spec, bg=TEMA["surface"])
        self.e_calle = ttk.Entry(self.marco_wrap, width=7)
        self.e_pie = ttk.Entry(self.marco_wrap, width=7)
        tk.Label(self.marco_wrap, text="calle", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left")
        self.e_calle.pack(side="left", padx=(4, 4))
        tk.Label(self.marco_wrap, text="x pie", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left")
        self.e_pie.pack(side="left", padx=(4, 0))
        # etiqueta que muestra el tipo deducido del marco
        self.lbl_tipo_calc = tk.Label(self.frame_spec, text="", bg=TEMA["surface"],
                                      fg=TEMA["ok_fg"], font=FUENTES["small"])
        self.e_calle.bind("<KeyRelease>", lambda e: self._calc_marco())
        self.e_pie.bind("<KeyRelease>", lambda e: self._calc_marco())

        box = tarjeta(form)
        box.pack(fill="x", padx=16, pady=12)
        tk.Label(box, text="Geometria por SIGPAC", bg=TEMA["surface"], fg=TEMA["text"],
                 font=FUENTES["small"]).grid(row=0, column=0, columnspan=6, sticky="w",
                                             padx=8, pady=(8, 4))
        self.sig = {}
        for i, kk in enumerate(["Prov", "Mun", "Pol", "Par", "Rec"]):
            tk.Label(box, text=kk, bg=TEMA["surface"], fg=TEMA["text_muted"],
                     font=FUENTES["small"]).grid(row=1 + i // 3, column=(i % 3) * 2,
                                                 sticky="w", padx=(8, 2))
            e = ttk.Entry(box, width=6)
            e.grid(row=1 + i // 3, column=(i % 3) * 2 + 1, padx=2, pady=2)
            self.sig[kk] = e
        ttk.Button(box, text="Capturar recinto SIGPAC", command=self._sigpac).grid(
            row=3, column=0, columnspan=6, sticky="ew", padx=8, pady=(6, 8))

        tk.Label(form, text="...o dibuja los bordes en el mapa (clic izquierdo).",
                 bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"]).pack(anchor="w", **pad)
        botones = tk.Frame(form, bg=TEMA["surface"])
        botones.pack(fill="x", padx=16, pady=(4, 0))
        ttk.Button(botones, text="Deshacer punto", command=self._deshacer).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(botones, text="Limpiar", command=self._limpiar).pack(side="left", expand=True, fill="x")
        ttk.Button(form, text="Guardar parcela", style="Accent.TButton",
                   command=self._guardar).pack(fill="x", padx=16, pady=14)

        mapwrap = tarjeta(cuerpo)
        mapwrap.pack(side="right", fill="both", expand=True, padx=(14, 0))
        if _MAPVIEW:
            # --- barra superior del mapa: buscador de localidades + capa ---
            barra_mapa = tk.Frame(mapwrap, bg=TEMA["surface"])
            barra_mapa.pack(fill="x", padx=8, pady=6)
            tk.Label(barra_mapa, text="Localidad", bg=TEMA["surface"], fg=TEMA["text_sec"],
                     font=FUENTES["small"]).pack(side="left")
            self.e_localidad = ttk.Entry(barra_mapa)
            self.e_localidad.pack(side="left", fill="x", expand=True, padx=6)
            self.e_localidad.bind("<Return>", lambda e: self._buscar_localidad())
            ttk.Button(barra_mapa, text="Buscar", command=self._buscar_localidad).pack(side="left")
            self.cb_capa = ttk.Combobox(barra_mapa, state="readonly", width=10,
                                        values=["Satelite", "Hibrido", "Calles"])
            self.cb_capa.set("Satelite")
            self.cb_capa.pack(side="left", padx=(6, 0))
            self.cb_capa.bind("<<ComboboxSelected>>", lambda e: self._cambiar_capa())

            self.mapa = tkintermapview.TkinterMapView(mapwrap, corner_radius=0)
            self.mapa.pack(fill="both", expand=True, padx=1, pady=1)
            self._cambiar_capa()                         # arranca en satelite
            self.mapa.set_position(40.4167, -3.7037, zoom=6)
            self.mapa.add_left_click_map_command(self._clic)
        else:
            tk.Label(mapwrap, text="tkintermapview no disponible.\nUsa la geometria por SIGPAC.",
                     bg=TEMA["surface"], fg=TEMA["danger_fg"]).pack(expand=True)

    def _cambiar_capa(self):
        capa = self.cb_capa.get() if hasattr(self, "cb_capa") else "Satelite"
        servidores = {
            "Satelite": "https://mt0.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
            "Hibrido":  "https://mt0.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
            "Calles":   "https://mt0.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        }
        self.mapa.set_tile_server(servidores.get(capa, servidores["Satelite"]), max_zoom=22)

    def _buscar_localidad(self):
        texto = self.e_localidad.get().strip()
        if not texto:
            return
        try:
            if not self.mapa.set_address(texto):     # geocodifica y centra el mapa
                messagebox.showinfo("Localidad", "No se encontro la localidad.")
        except Exception as e:
            messagebox.showerror("Localidad", f"Error en la busqueda: {e}")

    def _sub(self, _=None):
        grupo = self.cb_tipo.get()
        esp = FEN.ESPECIES.get(grupo, [])
        self.cb_sub["values"] = esp
        self.cb_sub.set(esp[0] if esp else "")
        for w in (self.lbl_siembra, self.e_siembra, self.lbl_marco,
                  self.marco_wrap, self.lbl_tipo_calc):
            w.pack_forget()
        if grupo == "EXTENSIVO":
            self.lbl_siembra.pack(anchor="w")
            self.e_siembra.pack(fill="x")
        elif grupo == "LENOSO":
            self.lbl_marco.pack(anchor="w")
            self.marco_wrap.pack(anchor="w", pady=(0, 2))
            self.lbl_tipo_calc.pack(anchor="w")
            self._calc_marco()

    def _calc_marco(self):
        try:
            c = float(self.e_calle.get().replace(",", "."))
            p = float(self.e_pie.get().replace(",", "."))
            dens = FEN.densidad_arboles(c, p)
            esp = self.cb_sub.get() or "OLIVO"
            tipo, _ = FEN.tipo_plantacion(esp, dens)
            self.lbl_tipo_calc.config(text=f"= {dens} arboles/ha  ->  {tipo}")
        except Exception:
            self.lbl_tipo_calc.config(text="")

    def _clic(self, coords):
        self.coords.append([coords[1], coords[0]])
        self._redibujar()

    def _redibujar(self):
        if not _MAPVIEW:
            return
        if self.poligono:
            self.poligono.delete()
            self.poligono = None
        if len(self.coords) >= 3:
            self.poligono = self.mapa.set_polygon([(c[1], c[0]) for c in self.coords],
                                                  fill_color="#2f855a", outline_color="#22d3ee",
                                                  border_width=2)

    def _deshacer(self):
        if self.coords:
            self.coords.pop()
            self._redibujar()

    def _limpiar(self):
        self.coords = []
        self._redibujar()

    def _sigpac(self):
        v = {k: e.get() for k, e in self.sig.items()}
        if not all(v.values()):
            return messagebox.showwarning("SIGPAC", "Rellena Prov/Mun/Pol/Par/Rec.")
        url = ("https://sigpac.mapa.gob.es/fega/serviciosrest/v1/recintos/geojson/"
               f"{v['Prov']}/{v['Mun']}/{v['Pol']}/{v['Par']}/{v['Rec']}")
        try:
            geo = requests.get(url, timeout=10).json()["geometry"]
            c = geo["coordinates"][0] if geo["type"] == "Polygon" else geo["coordinates"][0][0]
            self.coords = [[p[0], p[1]] for p in c]
            if _MAPVIEW:
                self._redibujar()
                self.mapa.set_position(self.coords[0][1], self.coords[0][0], zoom=16)
            messagebox.showinfo("SIGPAC", "Recinto capturado.")
        except Exception as e:
            messagebox.showerror("SIGPAC", f"Error: {e}")

    def _guardar(self):
        nombre = nombre_seguro(self.e_nombre.get())
        prop = self.e_prop.get().strip()
        tipo, esp = self.cb_tipo.get(), self.cb_sub.get()
        if not nombre or not prop or not tipo:
            return messagebox.showwarning("Datos", "Nombre, propietario y tipo son obligatorios.")
        if tipo != "BARBECHO" and not esp:
            return messagebox.showwarning("Datos", "Selecciona la especie.")
        if len(self.coords) < 3:
            return messagebox.showwarning("Geometria", "Define al menos 3 vertices (SIGPAC o mapa).")

        spec = {"especie": esp}
        if tipo == "EXTENSIVO":
            siembra = self.e_siembra.get().strip()
            if siembra:
                try:
                    datetime.strptime(siembra, "%Y-%m-%d")
                    spec["fecha_siembra"] = siembra
                except ValueError:
                    return messagebox.showwarning("Siembra", "Fecha de siembra: formato AAAA-MM-DD.")
        elif tipo == "LENOSO":
            try:
                spec["marco_calle"] = float(self.e_calle.get().replace(",", "."))
                spec["marco_pie"] = float(self.e_pie.get().replace(",", "."))
            except ValueError:
                return messagebox.showwarning("Marco", "Indica el marco de plantacion (calle y pie en metros).")

        self.panel.guardar_parcela(nombre, prop, tipo, spec, self.coords)
        messagebox.showinfo("OK", f"Parcela '{nombre}' guardada.")
        self.destroy()


# =====================================================================
# RELEVO DE CAMPANA (1 de septiembre)
# =====================================================================
class DialogoRelevoCampana(tk.Toplevel):
    """Al iniciar una campana nueva, recorre las parcelas existentes y pide el cultivo
    de cada una para la nueva campana. Al terminar, ofrece anadir mas parcelas."""

    def __init__(self, panel, pendientes):
        super().__init__(panel)
        self.panel = panel
        self.pendientes = list(pendientes)
        self.idx = 0
        self.title("Nueva campana - Asignacion de cultivos")
        self.geometry("440x300")
        self.configure(bg=TEMA["page"])
        self.grab_set()          # modal

        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        tk.Label(cab, text=f"Campana {panel.campana}", bg=TEMA["header_bg"], fg="#fff",
                 font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=8)
        tk.Label(cab, text="Indica el cultivo de cada parcela para la nueva campana.",
                 bg=TEMA["header_bg"], fg=TEMA["header_sub"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(0, 8))

        self.card = tarjeta(self)
        self.card.pack(fill="both", expand=True, padx=14, pady=14)

        self.lbl_parc = tk.Label(self.card, text="", bg=TEMA["surface"], fg=TEMA["text"],
                                 font=FUENTES["h2"])
        self.lbl_parc.pack(anchor="w", padx=16, pady=(14, 4))
        self.lbl_prog = tk.Label(self.card, text="", bg=TEMA["surface"], fg=TEMA["text_muted"],
                                 font=FUENTES["small"])
        self.lbl_prog.pack(anchor="w", padx=16)

        fila = tk.Frame(self.card, bg=TEMA["surface"])
        fila.pack(fill="x", padx=16, pady=14)
        tk.Label(fila, text="Tipo", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=0, sticky="w")
        tk.Label(fila, text="Especie", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.cb_tipo = ttk.Combobox(fila, state="readonly", width=14,
                                    values=["EXTENSIVO", "LENOSO", "BARBECHO"])
        self.cb_tipo.grid(row=1, column=0, sticky="ew")
        self.cb_tipo.bind("<<ComboboxSelected>>", self._sub)
        self.cb_sub = ttk.Combobox(fila, state="readonly", width=16, values=[])
        self.cb_sub.grid(row=1, column=1, sticky="ew", padx=(10, 0))
        self.cb_sub.bind("<<ComboboxSelected>>", lambda e: self._calc_marco())

        # campos por especie: siembra (cereal) o marco (leñoso)
        self.spec_wrap = tk.Frame(self.card, bg=TEMA["surface"])
        self.spec_wrap.pack(fill="x", padx=16)
        self.lbl_siembra = tk.Label(self.spec_wrap, text="Fecha de siembra (AAAA-MM-DD)",
                                    bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.e_siembra = ttk.Entry(self.spec_wrap)
        self.lbl_marco = tk.Label(self.spec_wrap, text="Marco (calle x pie, m)",
                                  bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.marco_wrap = tk.Frame(self.spec_wrap, bg=TEMA["surface"])
        self.e_calle = ttk.Entry(self.marco_wrap, width=7)
        self.e_pie = ttk.Entry(self.marco_wrap, width=7)
        self.e_calle.pack(side="left")
        tk.Label(self.marco_wrap, text="x", bg=TEMA["surface"], fg=TEMA["text_muted"]).pack(side="left", padx=4)
        self.e_pie.pack(side="left")
        self.lbl_tipo_calc = tk.Label(self.spec_wrap, text="", bg=TEMA["surface"],
                                      fg=TEMA["ok_fg"], font=FUENTES["small"])
        self.e_calle.bind("<KeyRelease>", lambda e: self._calc_marco())
        self.e_pie.bind("<KeyRelease>", lambda e: self._calc_marco())

        tk.Label(self.card, text="Si la parcela no se va a sembrar, elige BARBECHO (estado N.A.).",
                 bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"]).pack(
            anchor="w", padx=16)

        ttk.Button(self.card, text="Guardar y siguiente", style="Accent.TButton",
                   command=self._siguiente).pack(fill="x", padx=16, pady=14)
        self._mostrar()

    def _sub(self, _=None):
        grupo = self.cb_tipo.get()
        esp = FEN.ESPECIES.get(grupo, [])
        self.cb_sub["values"] = esp
        self.cb_sub.set(esp[0] if esp else "")
        for w in (self.lbl_siembra, self.e_siembra, self.lbl_marco,
                  self.marco_wrap, self.lbl_tipo_calc):
            w.pack_forget()
        if grupo == "EXTENSIVO":
            self.lbl_siembra.pack(anchor="w")
            self.e_siembra.pack(fill="x")
        elif grupo == "LENOSO":
            self.lbl_marco.pack(anchor="w")
            self.marco_wrap.pack(anchor="w", pady=(0, 2))
            self.lbl_tipo_calc.pack(anchor="w")
            self._calc_marco()

    def _calc_marco(self):
        try:
            c = float(self.e_calle.get().replace(",", "."))
            p = float(self.e_pie.get().replace(",", "."))
            dens = FEN.densidad_arboles(c, p)
            tipo, _ = FEN.tipo_plantacion(self.cb_sub.get() or "OLIVO", dens)
            self.lbl_tipo_calc.config(text=f"= {dens} arboles/ha  ->  {tipo}")
        except Exception:
            self.lbl_tipo_calc.config(text="")

    def _mostrar(self):
        nombre = self.pendientes[self.idx]
        self.lbl_parc.config(text=nombre.replace("_", " "))
        self.lbl_prog.config(text=f"Parcela {self.idx + 1} de {len(self.pendientes)}")
        ficha = _load(ARCHIVO_PARCELAS).get(nombre, {})
        campos = ficha.get("cultivos_por_campana", {})
        prev = campos.get(sorted(campos)[-1]) if campos else None
        self.cb_tipo.set(prev.get("tipo") if prev else "LENOSO")
        self._sub()
        # rellenar con lo de la campana anterior si existe
        if prev:
            if prev.get("especie"):
                self.cb_sub.set(prev["especie"])
                self._sub()
            if prev.get("fecha_siembra"):
                self.e_siembra.delete(0, tk.END)
                self.e_siembra.insert(0, prev["fecha_siembra"])
            if prev.get("marco_calle"):
                self.e_calle.delete(0, tk.END); self.e_calle.insert(0, str(prev["marco_calle"]))
                self.e_pie.delete(0, tk.END); self.e_pie.insert(0, str(prev["marco_pie"]))
                self._calc_marco()

    def _siguiente(self):
        tipo = self.cb_tipo.get()
        esp = self.cb_sub.get()
        if not tipo:
            return messagebox.showwarning("Cultivo", "Selecciona el tipo de cultivo.")
        if tipo != "BARBECHO" and not esp:
            return messagebox.showwarning("Cultivo", "Selecciona la especie.")
        spec = {"especie": esp} if tipo != "BARBECHO" else {}
        if tipo == "EXTENSIVO" and self.e_siembra.get().strip():
            spec["fecha_siembra"] = self.e_siembra.get().strip()
        if tipo == "LENOSO":
            try:
                spec["marco_calle"] = float(self.e_calle.get().replace(",", "."))
                spec["marco_pie"] = float(self.e_pie.get().replace(",", "."))
            except ValueError:
                return messagebox.showwarning("Marco", "Indica el marco (calle y pie en metros).")
        self.panel.asignar_cultivo(self.pendientes[self.idx], tipo, spec)
        self.idx += 1
        if self.idx < len(self.pendientes):
            self._mostrar()
        else:
            self.destroy()
            if messagebox.askyesno("Nueva campana",
                                   "Cultivos asignados. Deseas anadir alguna parcela mas?"):
                self.panel.abrir_alta_parcela()


# =====================================================================
# FICHA DE PARCELA
# =====================================================================
class FichaParcela:
    def __init__(self, master, panel, nombre, campana):
        self.master, self.panel = master, panel
        self.nombre, self.campana = nombre, campana
        self.img_tk = None
        self._map_fechas = {}

        cab = tk.Frame(master, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        ttk.Button(cab, text="  \u2190 Volver  ", style="Ghost.TButton",
                   command=panel.mostrar_lista).pack(side="left", padx=12, pady=10)
        tk.Label(cab, text=f"{nombre.replace('_',' ')}   ·   Campana {campana}",
                 bg=TEMA["header_bg"], fg="#fff", font=FUENTES["h2"]).pack(side="left")
        ttk.Button(cab, text="  \u21BB Sincronizar Copernicus  ", style="Ghost.TButton",
                   command=self.sincronizar).pack(side="right", padx=12, pady=10)

        cuerpo = tk.Frame(master, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=14, pady=14)

        sup = tk.Frame(cuerpo, bg=TEMA["page"])
        sup.pack(fill="both", expand=True)
        self._build_tabla(sup)
        self._build_mapa(sup)

        inf = tk.Frame(cuerpo, bg=TEMA["page"])
        inf.pack(fill="both", expand=True, pady=(14, 0))
        self._build_graficas(inf)
        self._build_interp(inf)

        inf2 = tk.Frame(cuerpo, bg=TEMA["page"])
        inf2.pack(fill="both", expand=True, pady=(14, 0))
        self._build_cuaderno(inf2)

        self.refrescar()

    def _titulo(self, parent, texto):
        tk.Label(parent, text=texto, bg=TEMA["surface"], fg=TEMA["text"],
                 font=FUENTES["h2"]).pack(anchor="w", padx=12, pady=(10, 6))

    def _build_tabla(self, parent):
        card = tarjeta(parent, width=560)
        card.pack(side="left", fill="both", expand=True, padx=(0, 7))
        self._titulo(card, "Historico de indices (medias Copernicus)")
        cols = ["fecha"] + INDICES_ORDEN
        self.tv = ttk.Treeview(card, columns=cols, show="headings", height=10)
        for c in cols:
            self.tv.heading(c, text=c.upper())
            self.tv.column(c, width=88 if c == "fecha" else 56,
                           anchor="w" if c == "fecha" else "center")
        self.tv.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.tv.tag_configure("ult", background="#fffaf0")

    def _build_mapa(self, parent):
        card = tarjeta(parent)
        card.pack(side="right", fill="both", expand=True, padx=(7, 0))
        top = tk.Frame(card, bg=TEMA["surface"])
        top.pack(fill="x", padx=12, pady=10)
        tk.Label(top, text="Dia", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left")
        self.cb_dia = ttk.Combobox(top, state="readonly", width=24)
        self.cb_dia.pack(side="left", padx=6)
        self.cb_dia.bind("<<ComboboxSelected>>", lambda e: self._pintar_mapa())
        tk.Label(top, text="Indice", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left", padx=(8, 0))
        self.cb_idx = ttk.Combobox(top, state="readonly", width=8, values=INDICES_ORDEN)
        self.cb_idx.set("NDVI")
        self.cb_idx.pack(side="left", padx=6)
        self.cb_idx.bind("<<ComboboxSelected>>", lambda e: self._pintar_mapa())

        # --- barra de resolucion y zoom ---
        top2 = tk.Frame(card, bg=TEMA["surface"])
        top2.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(top2, text="Resolucion", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left")
        self.cb_res = ttk.Combobox(top2, state="readonly", width=22,
                                   values=[e[0] for e in RESOLUCIONES])
        self.cb_res.set(RESOLUCIONES[1][0])          # 10 m = nativo Sentinel-2
        self.cb_res.pack(side="left", padx=6)
        self.cb_res.bind("<<ComboboxSelected>>", lambda e: self._pintar_mapa())

        tk.Label(top2, text="Zoom", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left", padx=(10, 2))
        ttk.Button(top2, text="\u2212", width=3,
                   command=lambda: self._zoom(1 / 1.25)).pack(side="left", padx=1)
        ttk.Button(top2, text="+", width=3,
                   command=lambda: self._zoom(1.25)).pack(side="left", padx=1)
        ttk.Button(top2, text="Ajustar", command=lambda: self._zoom(None)).pack(side="left", padx=4)
        self.lbl_res = tk.Label(top2, text="", bg=TEMA["surface"], fg=TEMA["text_muted"],
                                font=FUENTES["small"])
        self.lbl_res.pack(side="left", padx=8)

        cont = tk.Frame(card, bg=TEMA["surface"])
        cont.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.canvas_mapa = tk.Canvas(cont, bg="#d7ddd9", highlightthickness=0)
        self.canvas_mapa.pack(side="left", fill="both", expand=True)
        self.canvas_mapa.bind("<Configure>", lambda e: self._redibujar_png())
        self.canvas_mapa.bind("<MouseWheel>",                       # Windows / macOS
                              lambda e: self._zoom(1.25 if e.delta > 0 else 1 / 1.25))
        self.canvas_mapa.bind("<Button-4>", lambda e: self._zoom(1.25))       # Linux
        self.canvas_mapa.bind("<Button-5>", lambda e: self._zoom(1 / 1.25))   # Linux
        self.zoom = None                        # None = ajustar al lienzo
        self.fig_ley = Figure(figsize=(1.0, 3.2), dpi=90)
        self.cv_ley = FigureCanvasTkAgg(self.fig_ley, master=cont)
        self.cv_ley.get_tk_widget().pack(side="right", fill="y")

    def _zoom(self, factor):
        """factor None = ajustar al lienzo; si no, multiplica el zoom actual."""
        if factor is None:
            self.zoom = None
        else:
            base = self.zoom if self.zoom else 1.0
            self.zoom = max(0.2, min(8.0, base * factor))
        self._redibujar_png()

    def _build_graficas(self, parent):
        card = tarjeta(parent, width=560)
        card.pack(side="left", fill="both", expand=True, padx=(0, 7))
        self._titulo(card, "Evolucion en la campana")
        self.fig = Figure(figsize=(6, 2.9), dpi=90)
        self.cv = FigureCanvasTkAgg(self.fig, master=card)
        self.cv.get_tk_widget().pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _build_interp(self, parent):
        card = tarjeta(parent, width=420)
        card.pack(side="right", fill="both", padx=(7, 0))
        card.pack_propagate(False)
        self._titulo(card, "Interpretacion automatica")
        self.txt = tk.Text(card, wrap="word", height=8, bd=0, relief="flat",
                           bg="#f2f8ff", fg=TEMA["text"], font=FUENTES["body"],
                           padx=12, pady=10, highlightthickness=0)
        self.txt.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def refrescar(self):
        regs = sorted(self.panel._historico(self.nombre), key=lambda r: r.get("fecha", ""))
        for i in self.tv.get_children():
            self.tv.delete(i)
        for k, r in enumerate(regs):
            tag = ("ult",) if k == len(regs) - 1 else ()
            self.tv.insert("", tk.END, tags=tag, values=[r.get("fecha", "")] +
                           [f"{r.get(x.lower()):.3f}" if r.get(x.lower()) is not None else "-"
                            for x in INDICES_ORDEN])
        self._map_fechas = {self._fmt(r["fecha"]): r["fecha"] for r in regs if r.get("fecha")}
        self.cb_dia["values"] = list(self._map_fechas.keys())
        if self._map_fechas:
            self.cb_dia.current(len(self._map_fechas) - 1)
        self._pintar_leyenda()
        self._pintar_graficas(regs)
        self._pintar_interp(regs)
        self._pintar_mapa()

    @staticmethod
    def _fmt(iso):
        dias = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
        meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{dias[d.weekday()]}, {d.day} {meses[d.month-1]} {d.year}"

    def _pintar_graficas(self, regs):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        # solo registros con fecha valida (uno mal formado no debe tumbar la grafica)
        puntos = []
        for r in regs:
            try:
                puntos.append((datetime.strptime(r.get("fecha", ""), "%Y-%m-%d"), r))
            except (TypeError, ValueError):
                continue
        if puntos:
            fechas = [p[0] for p in puntos]
            validos = [p[1] for p in puntos]
            for idx, color in [("ndvi", "#2f855a"), ("evi", "#805ad5"),
                               ("savi", "#dd6b20"), ("ndmi", "#3182ce")]:
                ys = [r.get(idx) for r in validos]
                if any(v is not None for v in ys):
                    ax.plot(fechas, [v if v is not None else float("nan") for v in ys],
                            marker="o", ms=3, lw=1.8, label=idx.upper(), color=color)
            # --- marcadores de eventos del cuaderno de campo ---
            iconos = {"PRODUCTO": ("#c05621", "Producto"), "SIEGA": ("#2b6cb0", "Siega"),
                      "COSECHA": ("#b7791f", "Cosecha"), "RIEGO": ("#3182ce", "Riego"),
                      "LABOREO": ("#718096", "Laboreo"), "SIEMBRA": ("#276749", "Siembra"),
                      "OTRO": ("#718096", "Evento")}
            vistos = set()
            for e in REG.eventos_de(self.nombre, self.campana):
                try:
                    fx = datetime.strptime(e["fecha"], "%Y-%m-%d")
                except Exception:
                    continue
                col, et = iconos.get(e.get("tipo"), iconos["OTRO"])
                lbl = et if et not in vistos else None
                vistos.add(et)
                ax.axvline(fx, color=col, ls="--", lw=1.0, alpha=0.7, label=lbl)
            ax.legend(fontsize=7, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.16))
            self.fig.autofmt_xdate()
        self.fig.tight_layout()
        self.cv.draw()

    def _pintar_leyenda(self):
        self.fig_ley.clear()
        idx = self.cb_idx.get()
        ax = self.fig_ley.add_axes([0.1, 0.05, 0.32, 0.9])
        cmap = mcolors.LinearSegmentedColormap.from_list("x", ["#" + c for c in INDICES[idx]["paleta"]])
        cb = matplotlib.colorbar.ColorbarBase(ax, cmap=cmap,
                                              norm=mcolors.Normalize(*INDICES[idx]["rango"]),
                                              orientation="vertical")
        cb.ax.tick_params(labelsize=7)
        cb.set_label(idx, fontsize=8)
        self.cv_ley.draw()

    def _pintar_interp(self, regs):
        self.txt.delete("1.0", tk.END)
        if not regs:
            self.txt.insert(tk.END, "Sin datos. Pulsa 'Sincronizar Copernicus'.")
            return
        actual = regs[-1]
        cult = _load(ARCHIVO_PARCELAS).get(self.nombre, {}) \
            .get("cultivos_por_campana", {}).get(self.campana, {})
        tipo, sub = cult.get("tipo", "BARBECHO"), cult.get("subtipo", "")
        spec = spec_de(cult)

        # eventos del cuaderno cercanos a la ultima pasada (para el diagnostico)
        eventos_cerca = REG.eventos_cercanos(self.nombre, self.campana,
                                             actual.get("fecha", ""), ventana_dias=20)

        # diagnostico fenologico (rapido, local): fase, estado, cubierta y eventos
        diag = evaluar_parcela(tipo, sub, regs, eventos_cerca=eventos_cerca, spec=spec)
        self._estado_actual = diag["estado"]
        cab = f"[{diag['estado']}]  Fase: {diag['fase']}"
        c = diag.get("cubierta")
        if c and c["señales"] >= 2:
            cab += f"  ·  Cubierta: {c['hipotesis_preliminar']} ({c['señales']}/4)"
        self.txt.insert(tk.END, cab + "\n\n")

        if tipo == "BARBECHO":
            self.txt.insert(tk.END, diag["motivo"])
            return
        if actual.get("interpretacion"):          # cacheado
            self.txt.insert(tk.END, actual["interpretacion"])
            return
        self.txt.insert(tk.END, "Generando interpretacion...")

        def worker():
            texto, _d = texto_interpretacion(tipo, sub, regs, actual.get("fecha"),
                                             eventos_cerca=eventos_cerca, spec=spec)

            def _set(hist):
                for r in hist.get(self.nombre, {}).get(self.campana, []):
                    if r.get("fecha") == actual.get("fecha"):
                        r["interpretacion"] = texto
            _actualizar(ARCHIVO_HISTORICO, _set)

            def pintar():
                if not self.txt.winfo_exists():   # el usuario ya navego a otra vista
                    return
                self.txt.delete("1.0", tk.END)
                self.txt.insert(tk.END, cab + "\n\n" + texto)
            self.master.after(0, pintar)
        threading.Thread(target=worker, daemon=True).start()

    # ================= CUADERNO DE CAMPO =================
    def _build_cuaderno(self, parent):
        card = tarjeta(parent)
        card.pack(fill="both", expand=True)
        self._titulo(card, "Cuaderno de campo (intervenciones)")

        form = tk.Frame(card, bg=TEMA["surface"])
        form.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(form, text="Fecha", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=0, sticky="w")
        self.ev_fecha = ttk.Entry(form, width=12)
        self.ev_fecha.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.ev_fecha.grid(row=1, column=0, padx=(0, 8))
        tk.Label(form, text="Tipo", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=1, sticky="w")
        self.ev_tipo = ttk.Combobox(form, state="readonly", width=12, values=REG.TIPOS_EVENTO)
        self.ev_tipo.set("PRODUCTO")
        self.ev_tipo.grid(row=1, column=1, padx=(0, 8))
        self.ev_tipo.bind("<<ComboboxSelected>>", lambda e: self._toggle_producto())

        # campos especificos de PRODUCTO
        self.frame_prod = tk.Frame(form, bg=TEMA["surface"])
        self.frame_prod.grid(row=1, column=2, columnspan=3, sticky="w")
        tk.Label(self.frame_prod, text="Producto", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.ev_prod = ttk.Entry(self.frame_prod, width=16)
        self.ev_prod.grid(row=0, column=1, padx=(0, 8))
        tk.Label(self.frame_prod, text="Objetivo", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.ev_obj = ttk.Combobox(self.frame_prod, state="readonly", width=22,
                                   values=REG.OBJETIVOS_PRODUCTO)
        self.ev_obj.set(REG.OBJETIVOS_PRODUCTO[0])
        self.ev_obj.grid(row=0, column=3, padx=(0, 8))
        tk.Label(self.frame_prod, text="Dosis", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=4, sticky="w", padx=(0, 4))
        self.ev_dosis = ttk.Entry(self.frame_prod, width=10)
        self.ev_dosis.grid(row=0, column=5)

        tk.Label(form, text="Notas", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=5, sticky="w")
        self.ev_notas = ttk.Entry(form, width=26)
        self.ev_notas.grid(row=1, column=5, padx=(8, 8))
        ttk.Button(form, text="Anadir", style="Accent.TButton",
                   command=self._add_evento).grid(row=1, column=6, padx=4)

        cols = ("fecha", "tipo", "detalle", "efecto")
        self.tv_ev = ttk.Treeview(card, columns=cols, show="headings", height=5)
        for c, w in [("fecha", 90), ("tipo", 90), ("detalle", 300), ("efecto", 260)]:
            self.tv_ev.heading(c, text=c.capitalize())
            self.tv_ev.column(c, width=w, anchor="w")
        self.tv_ev.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.tv_ev.bind("<Double-1>", lambda e: self._ver_efecto_evento())
        self.tv_ev.bind("<Button-3>", self._menu_evento)
        tk.Label(card, text="Doble clic en un producto: ver su efecto sobre el cultivo. "
                            "Clic derecho: eliminar.", bg=TEMA["surface"],
                 fg=TEMA["text_muted"], font=FUENTES["small"]).pack(anchor="w", padx=12, pady=(0, 10))
        self._toggle_producto()
        self._refrescar_eventos()

    def _toggle_producto(self):
        if self.ev_tipo.get() == "PRODUCTO":
            self.frame_prod.grid()
        else:
            self.frame_prod.grid_remove()

    def _add_evento(self):
        fecha = self.ev_fecha.get().strip()
        try:
            datetime.strptime(fecha, "%Y-%m-%d")
        except Exception:
            return messagebox.showwarning("Fecha", "Formato de fecha: AAAA-MM-DD.")
        ev = {"fecha": fecha, "tipo": self.ev_tipo.get(), "notas": self.ev_notas.get().strip()}
        if ev["tipo"] == "PRODUCTO":
            if not self.ev_prod.get().strip():
                return messagebox.showwarning("Producto", "Indica el nombre del producto.")
            ev.update({"producto": self.ev_prod.get().strip(),
                       "objetivo": self.ev_obj.get(), "dosis": self.ev_dosis.get().strip()})
        REG.registrar_evento(self.nombre, self.campana, ev)
        self.ev_notas.delete(0, tk.END)
        if hasattr(self, "ev_prod"):
            self.ev_prod.delete(0, tk.END)
            self.ev_dosis.delete(0, tk.END)
        self._refrescar_eventos()
        self._pintar_graficas(sorted(self.panel._historico(self.nombre),
                                     key=lambda r: r.get("fecha", "")))
        self.refrescar()   # el evento puede cambiar el diagnostico (siega/cosecha)

    def _refrescar_eventos(self):
        for i in self.tv_ev.get_children():
            self.tv_ev.delete(i)
        regs = sorted(self.panel._historico(self.nombre), key=lambda r: r.get("fecha", ""))
        for e in REG.eventos_de(self.nombre, self.campana):
            if e.get("tipo") == "PRODUCTO":
                det = f"{e.get('producto','')} · {e.get('objetivo','')}"
                if e.get("dosis"):
                    det += f" · {e['dosis']}"
                ef = REG.efecto_producto(regs, e)
                efec = (ef["verdicto"] if ef and ef.get("disponible") else
                        (ef["nota"] if ef else "-"))
            else:
                det = e.get("notas", "") or "-"
                efec = "-"
            self.tv_ev.insert("", tk.END, values=(e.get("fecha", ""), e.get("tipo", ""),
                                                  det, efec), tags=(e.get("id", ""),))

    def _menu_evento(self, event):
        fila = self.tv_ev.identify_row(event.y)
        if not fila:
            return
        self.tv_ev.selection_set(fila)
        m = tk.Menu(self, tearoff=0, bg=TEMA["surface"], fg=TEMA["text"], bd=0)
        m.add_command(label="  Ver efecto", command=self._ver_efecto_evento)
        m.add_separator()
        m.add_command(label="  Eliminar evento", command=self._eliminar_evento)
        m.tk_popup(event.x_root, event.y_root)

    def _eliminar_evento(self):
        sel = self.tv_ev.selection()
        if not sel:
            return
        eid = self.tv_ev.item(sel[0], "tags")[0]
        REG.eliminar_evento(self.nombre, self.campana, eid)
        self._refrescar_eventos()
        self.refrescar()

    def _ver_efecto_evento(self):
        sel = self.tv_ev.selection()
        if not sel:
            return
        eid = self.tv_ev.item(sel[0], "tags")[0]
        ev = next((e for e in REG.eventos_de(self.nombre, self.campana)
                   if e.get("id") == eid), None)
        if not ev or ev.get("tipo") != "PRODUCTO":
            return messagebox.showinfo("Efecto", "Solo los productos tienen efecto medible.")
        regs = sorted(self.panel._historico(self.nombre), key=lambda r: r.get("fecha", ""))
        ef = REG.efecto_producto(regs, ev)
        if not ef or not ef.get("disponible"):
            return messagebox.showinfo("Efecto", ef["nota"] if ef else "Sin datos.")
        msg = (f"Producto: {ef['producto']} ({ef['objetivo']})\n"
               f"Aplicado: {ef['fecha_aplicacion']}\n\n"
               f"NDVI: {ef['ndvi_antes']} -> {ef['ndvi_despues']}  ({ef['d_ndvi']:+.3f})\n")
        if ef.get("d_ndmi") is not None:
            msg += f"NDMI: {ef['ndmi_antes']} -> {ef['ndmi_despues']}  ({ef['d_ndmi']:+.3f})\n"
        msg += (f"Medido {ef['dias_despues']} dias despues.\n\n"
                f"Lectura: {ef['verdicto']}.\n\n{ef['aviso']}")
        messagebox.showinfo("Efecto del producto", msg)

    def _pintar_mapa(self):
        self._pintar_leyenda()
        etq = self.cb_dia.get()
        if not etq:
            return
        iso = self._map_fechas.get(etq)
        idx = self.cb_idx.get()
        metros = dict(RESOLUCIONES).get(self.cb_res.get(), 10)
        # la cache distingue la resolucion: cada m/pixel es un PNG distinto
        # (nombre_seguro por si una parcela antigua tuviera caracteres raros)
        png = os.path.join(DIR_MAPAS, f"{nombre_seguro(self.nombre)}_{idx}_{iso}_{metros}m.png")
        if os.path.exists(png):
            self._png = png
            self._redibujar_png()
        elif _EE and _PIL:
            self.canvas_mapa.delete("all")
            self.canvas_mapa.create_text(20, 20, anchor="nw", fill=TEMA["text_muted"],
                                         text=f"Descargando a {metros} m/pixel...")
            threading.Thread(target=self._descargar, args=(iso, idx, png, metros),
                             daemon=True).start()
        else:
            self.canvas_mapa.delete("all")
            self.canvas_mapa.create_text(20, 20, anchor="nw", fill=TEMA["text_muted"],
                                         text="(mapa no disponible sin GEE/PIL)")

    def _descargar(self, iso, idx, png, metros):
        try:
            ficha = _load(ARCHIVO_PARCELAS)[self.nombre]
            coords = ficha["coordenadas"]
            geom = ee.Geometry.Polygon(coords)
            region = geom.bounds()
            dim = dimensiones_para(coords, metros)     # pixeles del lado mayor

            d1 = (datetime.strptime(iso, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            img = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                   .filterBounds(geom).filterDate(iso, d1).first())

            fondo = img.visualize(bands=["B4", "B3", "B2"], min=0, max=3000).getThumbURL(
                {"region": region, "dimensions": dim, "format": "png"})
            fondo = Image.open(io.BytesIO(requests.get(fondo, timeout=90).content)).convert("RGBA")

            rng = INDICES[idx]["rango"]
            ov = construir_indice(img, idx).clip(geom).visualize(
                min=rng[0], max=rng[1], palette=INDICES[idx]["paleta"]).getThumbURL(
                {"region": region, "dimensions": dim, "format": "png"})
            ov = Image.open(io.BytesIO(requests.get(ov, timeout=90).content)).convert("RGBA")

            Image.alpha_composite(fondo, ov).save(png)
            self._png = png
            self._info_res = f"{dim}x{dim} px  ·  {metros} m/pixel"
            self.master.after(0, self._redibujar_png)
        except Exception as e:
            self.master.after(0, lambda: self.canvas_mapa.winfo_exists() and self.canvas_mapa.create_text(
                20, 20, anchor="nw", fill=TEMA["danger_fg"], text=f"Error mapa: {e}"))

    def _redibujar_png(self):
        if not (hasattr(self, "canvas_mapa") and self.canvas_mapa.winfo_exists()):
            return                                # ficha cerrada mientras se descargaba
        png = getattr(self, "_png", None)
        if not (png and os.path.exists(png) and _PIL):
            return
        cw = max(self.canvas_mapa.winfo_width(), 50)
        ch = max(self.canvas_mapa.winfo_height(), 50)
        im = Image.open(png)
        orig_w, orig_h = im.size

        if self.zoom is None:                       # ajustar al lienzo
            im.thumbnail((cw, ch), Image.LANCZOS)
        else:                                       # zoom manual (NEAREST conserva el pixel)
            escala_ajuste = min(cw / orig_w, ch / orig_h)
            f = escala_ajuste * self.zoom
            nw, nh = max(1, int(orig_w * f)), max(1, int(orig_h * f))
            remuestreo = Image.NEAREST if f > 1 else Image.LANCZOS
            im = im.resize((nw, nh), remuestreo)

        self.img_tk = ImageTk.PhotoImage(im)
        self.canvas_mapa.delete("all")
        self.canvas_mapa.create_image(cw // 2, ch // 2, image=self.img_tk)
        # region desplazable si la imagen es mayor que el lienzo
        self.canvas_mapa.config(scrollregion=self.canvas_mapa.bbox("all"))

        if hasattr(self, "lbl_res"):
            z = "ajuste" if self.zoom is None else f"{self.zoom:.2f}x"
            self.lbl_res.config(text=f"{getattr(self, '_info_res', f'{orig_w}x{orig_h} px')}  ·  zoom {z}")

    def sincronizar(self):
        if not _EE:
            return messagebox.showwarning("GEE", "earthengine-api no disponible.")
        threading.Thread(target=self._sync, daemon=True).start()

    def _sync(self):
        n, msg = sincronizar_parcela(self.nombre, self.campana, silencioso=True)
        if ULTIMO_SYNC.get("estado") != "fallo":
            _marca_sync_guardar()
        self.master.after(0, self.refrescar)
        self.master.after(0, self.panel._refrescar)
        self.master.after(0, self.panel._actualizar_estado_sync)
        self.master.after(0, lambda: messagebox.showinfo(
            "Sincronizacion", f"{self.nombre}: {msg}." if n == 0 else
            f"{self.nombre}: {msg} (incremental, sin sobrescribir)."))


# =====================================================================
# PANEL DE CREDENCIALES / CONEXIONES
# =====================================================================
# Insignia de estado por servicio: color de fondo/texto segun el resultado.
_EST_COLOR = {"ok": ("ok_fg", "ok_bg"), "aviso": ("warn_fg", "warn_bg"),
              "fallo": ("danger_fg", "danger_bg"), "prueba": ("text_muted", "muted_bg")}
_EST_TEXTO = {"ok": "CONECTADO", "aviso": "SIN CONFIGURAR", "fallo": "FALLA",
              "prueba": "Probando…"}


class PanelCredenciales(ttk.Frame):
    """Pestana para ver/cambiar las credenciales (Google Earth Engine y OpenAI)
    y probar la conexion de cada una, mostrando en rojo el error si alguna falla."""

    def __init__(self, master, al_cambiar=None, *a, **k):
        super().__init__(master, *a, **k)
        self.al_cambiar = al_cambiar          # callback tras guardar (refrescar panel)
        self.cfg = CRED.cargar()
        self.badges, self.msgs = {}, {}
        self._build()
        self.after(400, self.probar_todo)     # estado inicial en segundo plano

    # ---- construccion ----
    def _build(self):
        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        tk.Label(cab, text="Credenciales y conexiones", bg=TEMA["header_bg"], fg="#fff",
                 font=FUENTES["h1"]).pack(anchor="w", padx=18, pady=(12, 0))
        tk.Label(cab, text="Configura los servicios externos y comprueba que responden",
                 bg=TEMA["header_bg"], fg=TEMA["header_sub"],
                 font=FUENTES["small"]).pack(anchor="w", padx=18, pady=(0, 12))

        cuerpo = tk.Frame(self, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=18, pady=16)

        # --- Google Earth Engine ---
        g = self._tarjeta(cuerpo, "gee", "Google Earth Engine",
                          "Necesario para descargar imagenes Sentinel-2 y sincronizar las parcelas.")
        tk.Label(g, text="Inicia sesion con tu cuenta de Google: se abre el navegador y escribes tu "
                         "correo y contrasena EN LA PAGINA DE GOOGLE (no aqui). No vemos ni guardamos "
                         "tu contrasena; Google nos da solo un permiso de acceso.",
                 bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"],
                 wraplength=760, justify="left").pack(anchor="w", pady=(2, 8))
        login = tk.Frame(g, bg=TEMA["surface"])
        login.pack(fill="x")
        ttk.Button(login, text="  Iniciar sesion con Google  ", style="Accent.TButton",
                   command=self._login_google).pack(side="left")
        ttk.Button(login, text="Probar conexion", command=lambda: self._probar("gee")).pack(side="left", padx=(8, 0))

        # avanzado: cuenta de servicio (para servidores sin navegador)
        tk.Label(g, text="Avanzado · cuenta de servicio (opcional, solo para servidores sin navegador)",
                 bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"]).pack(anchor="w", pady=(12, 4))
        self.e_gee_project = self._campo(g, "Project ID de Google Cloud", self.cfg.get("gee_project", ""))
        self.e_gee_sa = self._campo(g, "Cuenta de servicio · email", self.cfg.get("gee_service_account", ""))
        tk.Label(g, text="Fichero de clave (.json)", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", pady=(6, 2))
        fila = tk.Frame(g, bg=TEMA["surface"])
        fila.pack(fill="x")
        self.e_gee_key = ttk.Entry(fila)
        if self.cfg.get("gee_key_file"):
            self.e_gee_key.insert(0, self.cfg["gee_key_file"])
        self.e_gee_key.pack(side="left", fill="x", expand=True)
        ttk.Button(fila, text="Examinar", command=self._elegir_key).pack(side="left", padx=(6, 0))

        # --- OpenAI ---
        o = self._tarjeta(cuerpo, "openai", "OpenAI · ChatGPT",
                          "Opcional: genera la interpretacion con IA. Sin clave se usa el texto por reglas.")
        tk.Label(o, text="OpenAI no usa correo/contrasena para programar: usa una API key. Tu correo y "
                         "contrasena solo sirven para entrar en su web y crear la clave; pegala aqui.",
                 bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"],
                 wraplength=760, justify="left").pack(anchor="w", pady=(2, 8))
        self.e_openai = self._campo(o, "API key (sk-...)", self.cfg.get("openai_api_key", ""),
                                    secreto=True)
        acc2 = tk.Frame(o, bg=TEMA["surface"])
        acc2.pack(fill="x", pady=(10, 0))
        ttk.Button(acc2, text="Probar conexion", command=lambda: self._probar("openai")).pack(side="left")
        ttk.Button(acc2, text="Conseguir clave (web)", command=self._abrir_openai).pack(side="left", padx=(8, 0))
        self.var_ver = tk.IntVar(value=0)
        tk.Checkbutton(acc2, text="Mostrar clave", variable=self.var_ver, command=self._toggle_ver,
                       bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"],
                       activebackground=TEMA["surface"], selectcolor=TEMA["surface"], bd=0).pack(side="left", padx=10)
        # recordar o no la clave en disco
        self.var_recordar = tk.IntVar(value=1 if self.cfg.get("openai_api_key") else 0)
        tk.Checkbutton(o, text="Recordar la clave en este equipo (ofuscada; si no, usa la variable OPENAI_API_KEY)",
                       variable=self.var_recordar, bg=TEMA["surface"], fg=TEMA["text_muted"],
                       font=FUENTES["small"], activebackground=TEMA["surface"],
                       selectcolor=TEMA["surface"], bd=0).pack(anchor="w", pady=(8, 0))

        barra = tk.Frame(cuerpo, bg=TEMA["page"])
        barra.pack(fill="x", pady=(4, 0))
        tk.Label(barra, text="La clave de OpenAI se guarda ofuscada (base64), no en texto plano. "
                             "La variable de entorno OPENAI_API_KEY tiene prioridad.",
                 bg=TEMA["page"], fg=TEMA["text_muted"], font=FUENTES["small"]).pack(side="left")
        ttk.Button(barra, text="  Guardar y probar todo  ", style="Accent.TButton",
                   command=self.guardar).pack(side="right")

    def _tarjeta(self, parent, clave, titulo, subtitulo):
        card = tarjeta(parent)
        card.pack(fill="x", pady=(0, 14))
        top = tk.Frame(card, bg=TEMA["surface"])
        top.pack(fill="x", padx=16, pady=(14, 4))
        izq = tk.Frame(top, bg=TEMA["surface"])
        izq.pack(side="left")
        tk.Label(izq, text=titulo, bg=TEMA["surface"], fg=TEMA["text"], font=FUENTES["h2"]).pack(anchor="w")
        tk.Label(izq, text=subtitulo, bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(anchor="w")
        self.badges[clave] = tk.Label(top, text="Probando…", font=FUENTES["small"], padx=10, pady=3, bd=0)
        self.badges[clave].pack(side="right")
        cuerpo = tk.Frame(card, bg=TEMA["surface"])
        cuerpo.pack(fill="x", padx=16, pady=(4, 8))
        self.msgs[clave] = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                    font=FUENTES["small"], wraplength=780, justify="left", anchor="w")
        self.msgs[clave].pack(fill="x", padx=16, pady=(0, 12))
        return cuerpo

    def _campo(self, parent, etiqueta, valor="", secreto=False):
        tk.Label(parent, text=etiqueta, bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", pady=(6, 2))
        e = ttk.Entry(parent, show="•" if secreto else "")
        if valor:
            e.insert(0, valor)
        e.pack(fill="x")
        return e

    def _set_badge(self, clave, estado, msg):
        fg, bg = _EST_COLOR.get(estado, _EST_COLOR["prueba"])
        self.badges[clave].config(text=_EST_TEXTO.get(estado, "?"), fg=TEMA[fg], bg=TEMA[bg])
        self.msgs[clave].config(text=msg, fg=TEMA["danger_fg"] if estado == "fallo" else TEMA["text_sec"])

    def _toggle_ver(self):
        self.e_openai.config(show="" if self.var_ver.get() else "•")

    def _login_google(self):
        """Abre el flujo OAuth de Google (el usuario mete correo/contrasena en la
        pagina de Google) y verifica la conexion, en segundo plano."""
        self._set_badge("gee", "prueba", "Abriendo el navegador para iniciar sesion con Google…")
        project = self.e_gee_project.get().strip()

        def run():
            est, msg = CRED.autenticar_google(project)
            self.after(0, lambda: self._set_badge("gee", est, msg))
        threading.Thread(target=run, daemon=True).start()

    def _abrir_openai(self):
        """Abre la web de OpenAI donde el usuario crea su API key."""
        import webbrowser
        try:
            webbrowser.open(CRED.URL_OPENAI_KEYS)
        except Exception:
            pass

    def _elegir_key(self):
        ruta = filedialog.askopenfilename(title="Clave de cuenta de servicio",
                                          filetypes=[("JSON", "*.json"), ("Todos", "*.*")])
        if ruta:
            self.e_gee_key.delete(0, tk.END)
            self.e_gee_key.insert(0, ruta)

    def _cfg_actual(self):
        return {"gee_project": self.e_gee_project.get().strip(),
                "gee_service_account": self.e_gee_sa.get().strip(),
                "gee_key_file": self.e_gee_key.get().strip(),
                "openai_api_key": self.e_openai.get().strip()}

    def _probar(self, servicio):
        self._set_badge(servicio, "prueba", "Probando conexion…")
        cfg = self._cfg_actual()
        CRED.aplicar_entorno(cfg)

        def run():
            if servicio == "gee":
                est, msg = CRED.probar_gee(cfg["gee_project"], cfg["gee_key_file"],
                                           cfg["gee_service_account"])
                if ULTIMO_SYNC.get("estado") == "fallo" and est == "ok":
                    est, msg = "aviso", msg + f"  ·  Aviso: el ultimo sync automatico fallo ({ULTIMO_SYNC['msg']})."
            else:
                est, msg = CRED.probar_openai(cfg["openai_api_key"])
            self.after(0, lambda: self._set_badge(servicio, est, msg))
        threading.Thread(target=run, daemon=True).start()

    def probar_todo(self):
        for s in ("gee", "openai"):
            self._probar(s)

    def guardar(self):
        cfg = self._cfg_actual()
        try:
            CRED.guardar(cfg, recordar_openai=bool(self.var_recordar.get()))
        except Exception as e:
            return messagebox.showerror("Credenciales", f"No se pudieron guardar: {e}")
        self.cfg = cfg
        CRED.aplicar_entorno(cfg, forzar=True)   # aplica la clave recien tecleada
        self.probar_todo()
        if callable(self.al_cambiar):
            try:
                self.al_cambiar()
            except Exception:
                pass
        messagebox.showinfo("Credenciales", "Credenciales guardadas. Probando conexiones…")


# =====================================================================
# DEMO
# =====================================================================
if __name__ == "__main__":
    _cfg = CRED.cargar()
    CRED.aplicar_entorno(_cfg)
    if _EE:
        _est, _msg = CRED.probar_gee(_cfg.get("gee_project"), _cfg.get("gee_key_file"),
                                     _cfg.get("gee_service_account"))
        if _est != "ok":
            print(f"Aviso GEE: {_msg}")
    root = tk.Tk()
    root.title("Gestion de Parcelas - Copernicus")
    root.geometry("1440x900")
    aplicar_tema(root)
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    panel = PanelGestionParcelas(nb)
    nb.add(panel, text="  Gestion de Parcelas  ")
    nb.add(PanelCredenciales(nb, al_cambiar=panel._refrescar), text="  Credenciales  ")
    root.mainloop()
