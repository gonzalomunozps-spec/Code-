# -*- coding: utf-8 -*-
"""
ui_ficha.py
===========

La ficha de una parcela y las ventanas que salen de ella:

  FichaParcela        tabla de pasadas, mapa, graficas, interpretacion, cuaderno,
                      clima y estadistica espacial
  PanelMapaComparado  un mapa con su leyenda, para poner dos al lado
  VentanaComparaMapas dos mapas de la misma parcela, lado a lado
  VentanaRadar        Sentinel-1: graficas de VV/VH/CR/RVI y mapa de radar

Es la pantalla mas grande del programa y por eso tiene modulo propio. Abre los
dialogos de `ui_dialogos` pasandose a si misma; ellos no la importan.

OJO: `FichaParcela`, `LienzoMapa` y `PanelMapaComparado` NO son widgets: son
clases normales que pintan sobre un `master`. Pasarles `self` como padre de un
widget lanza AttributeError, y dentro de un callback de Tk no se ve: el widget
simplemente no aparece. Usa `self.master`.
"""

import os
import threading
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import ui_tema
from ui_tema import (TEMA, FUENTES, esc, geom, tarjeta, centrar_sobre,
                     marco_scroll, enlazar_rueda, color_serie)
from ui_widgets import LienzoMapa
from ui_dialogos import (DialogoCorreccion, DialogoValidacionIndices, DialogoBorrarCampana,
                         DialogoSincronizarCampanas, DialogoEfectoProducto)

import almacen as DB
import registro_parcela as REG
import sentinel1 as S1
import contraste_indices as CI
import gee_cliente
from gee_cliente import (INDICES, INDICES_ORDEN, RADAR_VIS,
                         descargar_mapa_indice, descargar_mapa_radar,
                         sincronizar_parcela)
from mapas_cache import ruta_cache_mapa, ruta_cache_radar
from interpretacion_fenologica import (evaluar_parcela, texto_interpretacion,
                                       ambito_parcela)
from campanas import campanas_de_parcela, etiqueta_campana, PRIMERA_CAMPANA_S2
from cultivo import spec_de
from vista_ficha import preparar_interpretacion
from bitacora import log
import sincronizacion
from sincronizacion import ULTIMO_SYNC
from ui_widgets import CampoFecha

import importlib.util
# Aqui solo hace falta SABER si Pillow esta; quien pinta imagenes es `ui_widgets`.
_PIL = importlib.util.find_spec("PIL") is not None
try:
    import informe_anual as _INFORME
except Exception:
    _INFORME = None
try:
    import calibracion_umbrales as _CALIB
except Exception:
    _CALIB = None
try:
    import clima_era5 as _CLIMA
except Exception:
    _CLIMA = None
try:
    import grados_dia as _GDD
except Exception:
    _GDD = None
try:
    import balance_hidrico as _BH
except Exception:
    _BH = None

_EE = gee_cliente.hay_ee()




def _abrir_archivo(ruta):
    """Abre un fichero con la aplicacion por defecto del sistema (multiplataforma)."""
    import platform
    import subprocess
    try:
        sistema = platform.system()
        if sistema == "Windows":
            os.startfile(ruta)                                   # noqa: solo en Windows
        elif sistema == "Darwin":
            subprocess.Popen(["open", ruta])
        else:
            subprocess.Popen(["xdg-open", ruta])
    except Exception:
        log.warning("no se pudo abrir %s con la aplicacion del sistema", ruta, exc_info=True)


# Constantes de presentacion (se definen UNA vez, no en cada llamada/redibujado).
_FMT_DIAS = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")
_FMT_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
# color y etiqueta de cada tipo de evento del cuaderno para las lineas de la grafica
# Los eventos del cuaderno se marcan sobre la grafica como lineas verticales de
# apoyo. NO llevan color propio: siete colores mas, encima de hasta ocho series de
# datos, se comen el canal que sirve para saber que curva es cual. Van en tinta
# apagada y se distinguen por su ETIQUETA, que es lo que se lee de todas formas.
_NOMBRE_EVENTO = {"PRODUCTO": "Producto", "SIEGA": "Siega", "COSECHA": "Cosecha",
                  "RIEGO": "Riego", "LABOREO": "Laboreo", "SIEMBRA": "Siembra",
                  "OTRO": "Evento"}


# --- texto emergente de la grafica: valores de los indices y fiabilidad del dia ---
def tooltip_pasada(reg):
    """Texto multilinea con los indices de una pasada y su fiabilidad (cobertura
    valida de pixeles tras enmascarar nubes/sombra)."""
    if not reg:
        return ""
    lineas = [reg.get("fecha", "")]
    for K in INDICES_ORDEN:
        v = reg.get(K.lower())
        if v is not None:
            lineas.append(f"{K}: {v:.3f}")
    cob = reg.get("cobertura_valida")
    if cob is not None:
        pct = cob * 100 if cob <= 1 else cob
        etiqueta = "alta" if pct >= 95 else "media" if pct >= 85 else "baja"
        lineas.append(f"Fiabilidad: {pct:.0f}% ({etiqueta})")
    return "\n".join(lineas)

# (los colores de serie viven en PALETA_DATOS; se piden con `color_serie`)
# indices que se muestran por defecto en la grafica (los demas, a eleccion)
INDICES_GRAFICA_DEF = ["NDVI", "EVI", "SAVI", "NDMI"]

# Resoluciones de descarga del mapa: (etiqueta, metros por pixel)
# 10 m = nativo de Sentinel-2 en B2/B3/B4/B8. NDMI y MSAVI usan B11 (20 m nativos),
# asi que por debajo de 20 m esos dos indices se remuestrean, no ganan detalle real.
RESOLUCIONES = [
    ("5 m (sobremuestreo)", 5),
    ("10 m (nativo S2)", 10),
    ("20 m (rapido)", 20),
    ("60 m (vista rapida)", 60),
]
# MAX_PIXELES y dimensiones_para viven en gee_cliente.


class PanelMapaComparado:
    """Visor de mapa autonomo (dia + indice + resolucion + leyenda) para la
    ventana de comparacion. Cada panel usa/gener a su propio PNG cacheado, asi
    que comparte cache con la ficha."""
    def __init__(self, parent, nombre, coords, fechas_map, idx_ini, res_ini, dia_ini=None):
        self.nombre, self.coords = nombre, coords
        self.fechas_map = fechas_map          # {etiqueta: iso}
        self.png = None
        self.img_tk = None

        card = tarjeta(parent)
        card.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        top = tk.Frame(card, bg=TEMA["surface"])
        top.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(top, text="Dia", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left")
        self.cb_dia = ttk.Combobox(top, state="readonly", width=20, values=list(fechas_map.keys()))
        self.cb_dia.pack(side="left", padx=4)
        self.cb_dia.bind("<<ComboboxSelected>>", lambda e: self.cargar())
        tk.Label(top, text="Indice", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left", padx=(6, 0))
        self.cb_idx = ttk.Combobox(top, state="readonly", width=7, values=INDICES_ORDEN)
        self.cb_idx.set(idx_ini if idx_ini in INDICES_ORDEN else "NDVI")
        self.cb_idx.pack(side="left", padx=4)
        self.cb_idx.bind("<<ComboboxSelected>>", lambda e: self.cargar())

        top2 = tk.Frame(card, bg=TEMA["surface"])
        top2.pack(fill="x", padx=8, pady=(0, 4))
        tk.Label(top2, text="Resolucion", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left")
        self.cb_res = ttk.Combobox(top2, state="readonly", width=18,
                                   values=[e[0] for e in RESOLUCIONES])
        self.cb_res.set(res_ini if res_ini in [e[0] for e in RESOLUCIONES] else RESOLUCIONES[1][0])
        self.cb_res.pack(side="left", padx=4)
        self.cb_res.bind("<<ComboboxSelected>>", lambda e: self.cargar())
        ttk.Button(top2, text="−", width=3, command=lambda: self.lienzo.zoom_rel(1 / 1.25)).pack(side="left", padx=(6, 1))
        ttk.Button(top2, text="+", width=3, command=lambda: self.lienzo.zoom_rel(1.25)).pack(side="left", padx=1)
        ttk.Button(top2, text="Ajustar", command=lambda: self.lienzo.ajustar()).pack(side="left", padx=2)

        self.lbl_info = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text_muted"],
                                 font=FUENTES["small"])
        self.lbl_info.pack(anchor="w", padx=10)

        cont = tk.Frame(card, bg=TEMA["surface"])
        cont.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.lienzo = LienzoMapa(cont, on_info=lambda t: self.lbl_info.winfo_exists() and
                                 self.lbl_info.config(text=t))
        self.lienzo.pack(side="left", fill="both", expand=True)
        self.canvas = self.lienzo.canvas          # alias para mensajes de estado
        ui_tema.cargar_matplotlib()   # se carga aqui, no al abrir el programa
        self.fig_ley = ui_tema.Figure(figsize=(0.9, 3.0), dpi=90)
        self.cv_ley = ui_tema.FigureCanvasTkAgg(self.fig_ley, master=cont)
        self.cv_ley.get_tk_widget().pack(side="right", fill="y")

        claves = list(fechas_map.keys())
        if claves:
            self.cb_dia.current(dia_ini if dia_ini is not None and 0 <= dia_ini < len(claves)
                                else len(claves) - 1)
        self.cargar()

    def cargar(self):
        self._leyenda()
        iso = self.fechas_map.get(self.cb_dia.get())
        if not iso:
            return
        idx = self.cb_idx.get()
        metros = dict(RESOLUCIONES).get(self.cb_res.get(), 10)
        png = ruta_cache_mapa(self.nombre, idx, iso, metros)
        if os.path.exists(png):
            self.lienzo.set_png(png, f"{metros} m/pixel")
        elif _EE and _PIL:
            self.lienzo.mensaje(f"Descargando a {metros} m/pixel...")
            threading.Thread(target=self._descargar, args=(iso, idx, png, metros), daemon=True).start()
        else:
            self.lienzo.mensaje("(mapa no disponible sin GEE/PIL)")

    def _descargar(self, iso, idx, png, metros):
        try:
            dim = descargar_mapa_indice(self.coords, iso, idx, metros, png)
            self.canvas.after(0, lambda: self.lienzo.set_png(png, f"{dim}x{dim} px  ·  {metros} m/pixel"))
        except Exception as e:
            # `e` se borra al salir del except: hay que fijarlo como argumento por
            # defecto o la lambda (que corre despues, via after) lanzaria NameError
            # y el usuario nunca veria el motivo del fallo.
            self.canvas.after(0, lambda err=e: self.lienzo.mensaje(f"Error mapa: {err}",
                                                                   TEMA["danger_fg"]))

    def _leyenda(self):
        ui_tema.cargar_matplotlib()   # se carga aqui, no al abrir el programa
        self.fig_ley.clear()
        idx = self.cb_idx.get()
        ax = self.fig_ley.add_axes([0.1, 0.05, 0.32, 0.9])
        cmap = ui_tema.mcolors.LinearSegmentedColormap.from_list("x", ["#" + c for c in INDICES[idx]["paleta"]])
        cb = ui_tema.matplotlib.colorbar.ColorbarBase(ax, cmap=cmap,
                                              norm=ui_tema.mcolors.Normalize(*INDICES[idx]["rango"]),
                                              orientation="vertical")
        cb.ax.tick_params(labelsize=7)
        cb.set_label(idx, fontsize=8)
        self.cv_ley.draw_idle()   # agrupado por Tk, no bloquea


class VentanaComparaMapas(tk.Toplevel):
    """Ventana con dos visores de mapa lado a lado: dos dias distintos, o el
    mismo dia con distinto indice."""
    def __init__(self, master, nombre, campana, fechas_map, idx_ini, res_ini):
        super().__init__(master)
        self.title(f"Comparar mapas · {nombre.replace('_', ' ')} · {campana}")
        self.geometry(geom(1150, 620))
        self.configure(bg=TEMA["page"])
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(80, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))

        coords = (DB.ficha(nombre) or {}).get("coordenadas") or []
        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        tk.Label(cab, text="Comparar mapas de indices", bg=TEMA["header_bg"], fg=TEMA["text_inv"],
                 font=FUENTES["h2"]).pack(side="left", padx=16, pady=10)
        tk.Label(cab, text="Elige dia e indice en cada panel: dos dias distintos, "
                           "o el mismo dia con distinto indice.",
                 bg=TEMA["header_bg"], fg=TEMA["text_inv_sec"], font=FUENTES["small"]).pack(side="left", padx=6)

        cuerpo = tk.Frame(self, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=8, pady=8)
        n = len(fechas_map)
        # por defecto: izquierda el ultimo dia, derecha el penultimo (comparativa temporal)
        self.izq = PanelMapaComparado(cuerpo, nombre, coords, fechas_map, idx_ini, res_ini,
                                      dia_ini=n - 1 if n else None)
        self.der = PanelMapaComparado(cuerpo, nombre, coords, fechas_map, idx_ini, res_ini,
                                      dia_ini=(n - 2 if n >= 2 else n - 1) if n else None)


class VentanaRadar(tk.Toplevel):
    """Ventana propia de Sentinel-1: grafica de parametros de radar (VV/VH/RVI/CR)
    con su interpretacion relacionada con el optico, y un MAPA de radar con
    selector de parametro, dia y resolucion."""
    RADAR_FECHAS = None

    def __init__(self, master, nombre, campana, radar, info, n, msg):
        super().__init__(master)
        self.nombre, self.campana = nombre, campana
        self.radar = radar or []
        self.coords = (DB.ficha(nombre) or {}).get("coordenadas") or []
        self.title(f"Sentinel-1 (radar) · {nombre.replace('_', ' ')} · {campana}")
        self.geometry(geom(1160, 650))
        self.configure(bg=TEMA["page"])
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(80, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))

        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        tk.Label(cab, text="Radar Sentinel-1  ·  parametros, interpretacion y mapa",
                 bg=TEMA["header_bg"], fg=TEMA["text_inv"], font=FUENTES["h2"]).pack(side="left", padx=16, pady=10)
        est = (f"{msg}" if n == 0 else f"descargadas {n} pasadas de radar nuevas")
        tk.Label(cab, text=f"({est})", bg=TEMA["header_bg"], fg=TEMA["text_inv_sec"],
                 font=FUENTES["small"]).pack(side="left", padx=6)

        cuerpo = tk.Frame(self, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- IZQUIERDA: grafica de parametros de radar + interpretacion ----
        izq = tarjeta(cuerpo, width=560)
        izq.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(izq, text="Evolucion de los parametros de radar", bg=TEMA["surface"],
                 fg=TEMA["text"], font=FUENTES["h2"]).pack(anchor="w", padx=12, pady=(10, 4))
        ui_tema.cargar_matplotlib()   # se carga aqui, no al abrir el programa
        self.fig = ui_tema.Figure(figsize=(6, 2.7), dpi=90)
        self.cv = ui_tema.FigureCanvasTkAgg(self.fig, master=izq)
        self.cv.get_tk_widget().pack(fill="x", padx=12, pady=(0, 6))
        self._pintar_grafica_radar()
        txt = tk.Text(izq, wrap="word", height=8, bd=0, relief="flat", bg=TEMA["nota_radar"],
                      fg=TEMA["text"], font=FUENTES["body"], padx=12, pady=10, highlightthickness=0)
        txt.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        txt.insert(tk.END, (info or {}).get("texto", ""))
        txt.config(state="disabled")

        # ---- DERECHA: mapa de radar con selectores ----
        der = tarjeta(cuerpo)
        der.pack(side="right", fill="both", expand=True, padx=(6, 0))
        barra = tk.Frame(der, bg=TEMA["surface"])
        barra.pack(fill="x", padx=10, pady=10)
        tk.Label(barra, text="Parametro", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left")
        self.cb_par = ttk.Combobox(barra, state="readonly", width=6, values=["RVI", "VV", "VH"])
        self.cb_par.set("RVI")
        self.cb_par.pack(side="left", padx=4)
        self.cb_par.bind("<<ComboboxSelected>>", lambda e: self._cargar_mapa())
        tk.Label(barra, text="Dia", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left", padx=(8, 0))
        fechas = [r["fecha"] for r in self.radar if r.get("fecha")]
        self.cb_dia = ttk.Combobox(barra, state="readonly", width=12, values=fechas)
        if fechas:
            self.cb_dia.set(fechas[-1])
        self.cb_dia.pack(side="left", padx=4)
        self.cb_dia.bind("<<ComboboxSelected>>", lambda e: self._cargar_mapa())
        tk.Label(barra, text="Resol.", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left", padx=(8, 0))
        self.cb_res = ttk.Combobox(barra, state="readonly", width=16,
                                   values=[e[0] for e in RESOLUCIONES])
        self.cb_res.set(RESOLUCIONES[1][0])
        self.cb_res.pack(side="left", padx=4)
        self.cb_res.bind("<<ComboboxSelected>>", lambda e: self._cargar_mapa())
        self.lbl_info = tk.Label(der, text="", bg=TEMA["surface"], fg=TEMA["text_muted"],
                                 font=FUENTES["small"])
        self.lbl_info.pack(anchor="w", padx=12)
        cont = tk.Frame(der, bg=TEMA["surface"])
        cont.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.lienzo = LienzoMapa(cont, on_info=lambda t: self.lbl_info.winfo_exists() and
                                 self.lbl_info.config(text=t))
        self.lienzo.pack(side="left", fill="both", expand=True)
        ui_tema.cargar_matplotlib()   # se carga aqui, no al abrir el programa
        self.fig_ley = ui_tema.Figure(figsize=(0.95, 3.0), dpi=90)
        self.cv_ley = ui_tema.FigureCanvasTkAgg(self.fig_ley, master=cont)
        self.cv_ley.get_tk_widget().pack(side="right", fill="y")
        self._cargar_mapa()

    def _pintar_grafica_radar(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        pts = []
        for r in self.radar:
            try:
                pts.append((datetime.strptime(r.get("fecha", ""), "%Y-%m-%d"), r))
            except (TypeError, ValueError):
                continue
        if pts:
            fechas = [p[0] for p in pts]
            for k, color, lbl in [("vv", color_serie("VV"), "VV (dB)"),
                                  ("vh", color_serie("VH"), "VH (dB)"),
                                  ("cr", color_serie("CR"), "CR=VH-VV (dB)")]:
                ys = [p[1].get(k) for p in pts]
                if any(v is not None for v in ys):
                    ax.plot(fechas, [v if v is not None else float("nan") for v in ys],
                            marker="o", ms=3, lw=1.6, label=lbl, color=color)
            ax.set_ylabel("dB", fontsize=8)
            ax2 = ax.twinx()          # RVI en eje 0-1 aparte
            rvis = [p[1].get("rvi") for p in pts]
            if any(v is not None for v in rvis):
                ax2.plot(fechas, [v if v is not None else float("nan") for v in rvis],
                         marker="s", ms=3, lw=1.8, ls="--", label="RVI", color=color_serie("RVI"))
                los = [p[1].get("rvi_lo") for p in pts]
                his = [p[1].get("rvi_hi") for p in pts]
                if all(x is not None for x in los) and all(x is not None for x in his):
                    ax2.fill_between(fechas, los, his, color=color_serie("RVI"), alpha=0.15)
                ax2.set_ylabel("RVI", fontsize=8)
                ax2.set_ylim(0, 1)
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels()
            ax.legend(h1 + h2, l1 + l2, fontsize=7, ncol=4, loc="upper center",
                      bbox_to_anchor=(0.5, 1.18))
            self.fig.autofmt_xdate()
        self.fig.tight_layout()
        self.cv.draw_idle()       # agrupado por Tk, no bloquea

    def _leyenda_radar(self, param):
        ui_tema.cargar_matplotlib()   # se carga aqui, no al abrir el programa
        self.fig_ley.clear()
        vis = RADAR_VIS.get(param, RADAR_VIS["RVI"])
        ax = self.fig_ley.add_axes([0.1, 0.05, 0.32, 0.9])
        cmap = ui_tema.mcolors.LinearSegmentedColormap.from_list("x", ["#" + c for c in vis["paleta"]])
        cb = ui_tema.matplotlib.colorbar.ColorbarBase(ax, cmap=cmap,
                                              norm=ui_tema.mcolors.Normalize(*vis["rango"]),
                                              orientation="vertical")
        cb.ax.tick_params(labelsize=7)
        cb.set_label(param + (" (dB)" if param in ("VV", "VH") else ""), fontsize=8)
        self.cv_ley.draw_idle()   # agrupado por Tk, no bloquea

    def _cargar_mapa(self):
        param = self.cb_par.get()
        iso = self.cb_dia.get()
        self._leyenda_radar(param)
        if not iso:
            return self.lienzo.mensaje("No hay dias de radar. Descarga con el boton de la ficha.")
        metros = dict(RESOLUCIONES).get(self.cb_res.get(), 10)
        png = ruta_cache_radar(self.nombre, param, iso, metros)
        if os.path.exists(png):
            self.lienzo.set_png(png, f"S1 {param} · {metros} m/pixel")
        elif _EE and _PIL:
            self.lienzo.mensaje(f"Descargando mapa S1 {param} a {metros} m/pixel...")
            threading.Thread(target=self._descargar_mapa, args=(iso, param, png, metros),
                             daemon=True).start()
        else:
            self.lienzo.mensaje("(mapa no disponible sin GEE/PIL)")

    def _descargar_mapa(self, iso, param, png, metros):
        try:
            dim = descargar_mapa_radar(self.coords, iso, param, metros, png)
            self.after(0, lambda: self.lienzo.set_png(png, f"S1 {param} · {dim}x{dim} px · {metros} m/pixel"))
        except Exception as e:
            # ver nota en PanelMapaComparado._descargar: `e` debe fijarse por defecto
            self.after(0, lambda err=e: self.lienzo.mensaje(f"Error mapa radar: {err}",
                                                            TEMA["danger_fg"]))


class FichaParcela:
    def __init__(self, master, panel, nombre, campana):
        self.master, self.panel = master, panel
        self.nombre, self.campana = nombre, campana
        self.img_tk = None
        self._map_fechas = {}
        self._radar = []          # serie Sentinel-1 (solo si se pulsa el boton de radar)

        cab = tk.Frame(master, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        ttk.Button(cab, text="  \u2190 Volver  ", style="Ghost.TButton",
                   command=panel.mostrar_lista).pack(side="left", padx=12, pady=10)
        tk.Label(cab, text=nombre.replace("_", " "),
                 bg=TEMA["header_bg"], fg=TEMA["text_inv"], font=FUENTES["h2"]).pack(side="left")
        ttk.Button(cab, text="  \u21BB Sincronizar Copernicus  ", style="Ghost.TButton",
                   command=self.sincronizar).pack(side="right", padx=(0, 12), pady=10)
        ttk.Button(cab, text="  \U0001F4E1 Sentinel-1 (radar)  ", style="Ghost.TButton",
                   command=self._sincronizar_radar).pack(side="right", padx=(0, 4), pady=10)
        if _INFORME is not None:      # boton solo si el modulo opcional esta presente
            ttk.Button(cab, text="  \U0001F4C4 Informe / Exportar  ", style="Ghost.TButton",
                       command=self._menu_exportar).pack(side="right", padx=(0, 4), pady=10)
        ttk.Button(cab, text="  \u23F2 Campanas anteriores  ", style="Ghost.TButton",
                   command=self._sincronizar_anteriores).pack(side="right", padx=(0, 4), pady=10)
        ttk.Button(cab, text="  \u270E Editar parcela  ", style="Ghost.TButton",
                   command=self._editar).pack(side="right", padx=(0, 4), pady=10)
        ttk.Button(cab, text="  \U0001F5D1 Borrar campana  ", style="Ghost.TButton",
                   command=self._borrar_campana).pack(side="right", padx=(0, 4), pady=10)

        cont, scroll = marco_scroll(master, bg=TEMA["page"])
        cont.pack(fill="both", expand=True)
        cuerpo = tk.Frame(scroll, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=14, pady=14)

        # Alturas fijas por fila: dentro de un marco con scroll el contenido debe
        # tener una altura REAL (si se deja expand=True, el mapa y la grafica se
        # estiran hasta la ventana y no queda nada que desplazar -> no se ve abajo).
        sup = tk.Frame(cuerpo, bg=TEMA["page"], height=esc(380))
        sup.pack(fill="x")
        sup.pack_propagate(False)
        self._build_tabla(sup)
        self._build_mapa(sup)

        inf = tk.Frame(cuerpo, bg=TEMA["page"], height=esc(320))
        inf.pack(fill="x", pady=(14, 0))
        inf.pack_propagate(False)
        self._build_graficas(inf)
        self._build_interp(inf)

        # 410 px = lo que MIDE el cuaderno completo (402) mas un margen. Es fijo a
        # proposito, como el resto de filas: dentro del marco con scroll el contenido
        # necesita altura real. Si se le queda corto, pack deja sin dibujar lo ultimo
        # que hay dentro -que es la lista de rendimientos-, sin avisar de nada.
        inf2 = tk.Frame(cuerpo, bg=TEMA["page"], height=esc(410))
        inf2.pack(fill="x", pady=(14, 0))
        inf2.pack_propagate(False)
        self._build_cuaderno(inf2)

        # CLIMA (ERA5-Land), antes de la estadistica. Solo con el modulo opcional.
        if _CLIMA is not None:
            inf_cl = tk.Frame(cuerpo, bg=TEMA["page"], height=esc(240))
            inf_cl.pack(fill="x", pady=(14, 0))
            inf_cl.pack_propagate(False)
            self._build_clima(inf_cl)

        # estadistica espacial por pasada, bajo el cuaderno de campo
        inf3 = tk.Frame(cuerpo, bg=TEMA["page"], height=esc(240))
        inf3.pack(fill="x", pady=(14, 0))
        inf3.pack_propagate(False)
        self._build_estadisticas(inf3)

        # la rueda del raton desplaza la ficha sobre marcos, etiquetas y botones
        # (el mapa conserva su zoom y las tablas su propio scroll)
        enlazar_rueda(cuerpo, scroll.rueda)

        self.refrescar()

    # =================================================================
    # SELECTOR DE CAMPANA DE LA FICHA
    # =================================================================
    # En la cabecera, al lado del nombre. Ofrece TODAS las campanas de la parcela,
    # no solo la actual:
    #   - las que Copernicus puede servir (de la 2017-2018 a la de hoy), tengan
    #     datos o no: elegir una sin descargar ofrece descargarla ahi mismo;
    #   - y las que estan guardadas pero el satelite ya no alcanza, marcadas
    #     "solo archivo". Esas no se pueden actualizar, pero son lo unico que
    #     queda de esos anos y hay que poder consultarlas.
    # Cambiar de campana aqui cambia tambien la del panel: la ficha lee la serie a
    # traves de `panel._historico`, asi que las dos tienen que ir a la vez o la
    # ficha ensenaria una campana y la lista otra.
    def _campanas_ficha(self):
        return campanas_de_parcela(DB.campanas_de(self.nombre))

    def campanas_para_barra(self):
        """Lo que el selector de la barra necesita para servir a esta ficha.

        Devuelve (etiquetas, campanas, indice de la abierta). Las campanas son las
        de ESTA parcela, no las que tengan datos en general: una parcela puede
        guardar campanas mas antiguas que el satelite y esas no se ocultan nunca
        (ver `campanas_de_parcela`)."""
        self._campanas_disp = self._campanas_ficha()
        # el numero de pasadas solo de la campana abierta: contarlas todas seria
        # una consulta por campana cada vez que se refresca la ficha
        etiquetas = [etiqueta_campana(
            c, len(DB.pasadas(self.nombre, c["campana"])) if c["campana"] == self.campana else None)
            for c in self._campanas_disp]
        actual = next((i for i, c in enumerate(self._campanas_disp)
                       if c["campana"] == self.campana), -1)
        return etiquetas, self._campanas_disp, actual

    def _refrescar_campanas(self):
        """Vuelve a rellenar el selector de la barra, que es el unico que hay."""
        if self.panel is not None:
            self.panel._sincronizar_barra()

    def cambiar_a(self, i):
        """Abre la campana numero `i` de las que ofrece la barra para esta ficha."""
        if not (0 <= i < len(getattr(self, "_campanas_disp", []))):
            return
        elegida = self._campanas_disp[i]
        camp = elegida["campana"]
        if camp == self.campana:
            return
        # Sin datos y descargable: se ofrece bajarla, que es a lo que se venia.
        # Si se dice que no, se abre igual (vacia): elegir una campana no puede
        # quedarse a medias porque no haya red.
        if not elegida["tiene_datos"] and elegida["sincronizable"] and _EE:
            aviso = (f"La campana {camp} no esta descargada.\n\n¿La descargo ahora "
                     f"de Copernicus?")
            if elegida["parcial"]:
                aviso += (f"\n\nAviso: en {PRIMERA_CAMPANA_S2} la cobertura de "
                          f"Sentinel-2 aun no era global y puede no haber imagenes "
                          f"de esta zona.")
            if messagebox.askyesno("Campanas", aviso, parent=self.master):
                self._abrir_campana(camp)
                return self._sincronizar_campana(camp)
        self._abrir_campana(camp)

    def _abrir_campana(self, camp):
        """Cambia la campana del panel y vuelve a montar la ficha en ella.

        No hay que remendar el desplegable: `mostrar_ficha` deja la barra
        sincronizada con las campanas de la parcela recien montada."""
        self.panel.campana = camp
        self.panel.mostrar_ficha(self.nombre)

    def _sincronizar_campana(self, camp):
        """Descarga UNA campana desde la ficha ya abierta en ella."""
        if not _EE:
            return messagebox.showwarning("GEE", "earthengine-api no disponible.")
        ficha = self.panel.vista_ficha
        def worker():
            n, msg = sincronizar_parcela(self.nombre, camp, silencioso=True)
            if ULTIMO_SYNC.get("estado") != "fallo":
                sincronizacion.marca_guardar()
            def fin():
                if not ficha.winfo_exists():
                    return          # se cerro la ficha mientras descargaba
                self.panel._refrescar()
                self.panel._actualizar_estado_sync()
                if self.panel.campana == camp:
                    self.panel.mostrar_ficha(self.nombre)
                if n:
                    messagebox.showinfo("Campanas", f"{camp}: {msg}.")
                else:
                    messagebox.showinfo(
                        "Campanas",
                        f"{camp}: no hay pasadas de Copernicus utilizables para esta "
                        f"parcela en esa campana.\n\n({msg})")
            ficha.after(0, fin)
        threading.Thread(target=worker, daemon=True).start()

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
            self.tv.column(c, width=esc(88) if c == "fecha" else esc(56),
                           anchor="w" if c == "fecha" else "center")
        self.tv.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.tv.tag_configure("ult", background=TEMA["warn_bg"])

    # Columnas de la tabla de estadistica espacial: (clave, titulo, ancho, decimales)
    COLS_ESTAD = [("fecha", "FECHA", 88, None), ("media", "MEDIA", 62, 3),
                  ("std", "DESV.", 62, 3), ("cv", "CV", 56, 2),
                  ("p10", "P10", 56, 2), ("p25", "P25", 56, 2), ("p50", "MEDIANA", 66, 2),
                  ("p75", "P75", 56, 2), ("p90", "P90", 56, 2),
                  ("amplitud", "P90-P10", 66, 2), ("n_pixeles", "PIXELES", 62, 0),
                  ("cobertura_valida", "COB.%", 56, "pct")]

    def _build_clima(self, parent):
        """Tabla de clima diario de ERA5-Land. SOLO ENSENA DATOS: de momento no
        mueve ningun diagnostico, ni un umbral, ni una fase."""
        card = tarjeta(parent)
        card.pack(fill="both", expand=True)
        self._titulo(card, "Clima de la comarca (ERA5-Land)")
        self.lbl_clima = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                  font=FUENTES["small"], justify="left", anchor="w",
                                  wraplength=1180)
        self.lbl_clima.pack(fill="x", padx=12, pady=(0, 4))
        # CONTEXTO HIDRICO (balance rodante lluvia-ET0): una linea, solo si el modulo
        # opcional balance_hidrico esta. Es lectura; el mismo dato es el que en el
        # diagnostico decide si un NDMI bajo se explica por la sequia comarcal.
        self.lbl_balance = None
        if _BH is not None:
            self.lbl_balance = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                        font=FUENTES["small"], justify="left", anchor="w",
                                        wraplength=1180)
            self.lbl_balance.pack(fill="x", padx=12, pady=(0, 4))
        cols = [c[0] for c in _CLIMA.COLUMNAS]
        self.tv_clima = ttk.Treeview(card, columns=cols, show="headings", height=6)
        for clave, titulo, ancho, _dec in _CLIMA.COLUMNAS:
            self.tv_clima.heading(clave, text=titulo)
            self.tv_clima.column(clave, width=esc(ancho),
                                 anchor="w" if clave == "fecha" else "center")
        sb = ttk.Scrollbar(card, orient="vertical", command=self.tv_clima.yview)
        self.tv_clima.configure(yscrollcommand=sb.set)
        self.tv_clima.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(0, 12))
        sb.pack(side="right", fill="y", padx=(0, 12), pady=(0, 12))
        ttk.Button(card, text="  Descargar clima  ",
                   command=self._sincronizar_clima).pack(side="bottom", anchor="w",
                                                         padx=12, pady=(0, 8))
        # GRADOS-DIA (integral termica): seccion OPCIONAL, dentro del clima. Solo
        # aparece si el modulo grados_dia esta y la parcela tiene integrales.
        self.gdd_card = None
        if _GDD is not None:
            self._build_gdd(parent)

    def _build_gdd(self, parent):
        """Grados-dia acumulados y las integrales termicas definidas en la parcela.

        Es lectura: ensena el GDD y la fase que sale de el, y deja ELEGIR cual de las
        integrales definidas se mira, con su referencia de bibliografia. Que la fase
        del diagnostico la mande el GDD ya lo decide el motor si hay integral; aqui
        solo se muestra."""
        card = tarjeta(parent)
        self.gdd_card = card
        self._titulo(card, "Grados-día (integral térmica)")
        self.lbl_gdd = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                font=FUENTES["small"], justify="left", anchor="w",
                                wraplength=1180)
        self.lbl_gdd.pack(fill="x", padx=12, pady=(0, 4))
        fila = tk.Frame(card, bg=TEMA["surface"])
        fila.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(fila, text="Integral que se mira:", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left")
        self.cb_gdd = ttk.Combobox(fila, state="readonly", width=48, values=[])
        self.cb_gdd.pack(side="left", padx=(6, 0))
        self.cb_gdd.bind("<<ComboboxSelected>>", lambda e: self._pintar_gdd_sel())
        self.lbl_gdd_ref = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text"],
                                    font=FUENTES["small"], justify="left", anchor="w",
                                    wraplength=1180)
        self.lbl_gdd_ref.pack(fill="x", padx=12, pady=(0, 10))

    def _pintar_clima(self):
        """Vuelca los dias de clima del punto de rejilla de esta parcela."""
        if _CLIMA is None or not hasattr(self, "tv_clima") or not self.tv_clima.winfo_exists():
            return
        dias = _CLIMA.clima_de_parcela(self.nombre, self.campana)
        self.tv_clima.delete(*self.tv_clima.get_children())
        for fila in _CLIMA.filas_tabla(dias):
            self.tv_clima.insert("", tk.END, values=fila)
        if dias:
            self.lbl_clima.config(
                text=_CLIMA.texto_resumen(_CLIMA.resumen(dias)) +
                "\n⚠ El pixel de ERA5-Land son 11 km de lado (12.392 ha): TODAS tus "
                "parcelas de la comarca reciben el mismo dato. Sirve de contexto, no "
                "para comparar una finca con su vecina. Va con unos 8 dias de retraso.")
        else:
            self.lbl_clima.config(
                text="Sin datos de clima para esta campana. Pulsa «Descargar clima» "
                     "(hace falta Earth Engine). El dato es de comarca, no de parcela: "
                     "el pixel de ERA5-Land son 11 km de lado.")
        self._pintar_balance(dias)
        self._pintar_gdd(dias)

    def _pintar_balance(self, dias):
        """Una linea con el balance hidrico rodante de la comarca (lluvia-ET0) y su
        severidad. Reutiliza los dias ya cargados; no vuelve a la base. Solo si el
        modulo balance_hidrico esta y hay dias."""
        if _BH is None or not getattr(self, "lbl_balance", None) or not self.lbl_balance.winfo_exists():
            return
        fecha = dias[-1]["fecha"] if dias else None
        ctx = _BH.contexto(dias, fecha) if fecha else None
        if not ctx:
            self.lbl_balance.pack_forget()
            return
        self.lbl_balance.pack(fill="x", padx=12, pady=(0, 4))
        aviso = ("  El déficit prolongado explica un NDMI bajo sin que sea, por sí solo, "
                 "un problema de esta parcela." if ctx["sequia"] else "")
        self.lbl_balance.config(text=_BH.texto_contexto(ctx) + aviso)

    def _pintar_gdd(self, dias):
        """Recalcula y ensena los grados-dia. Solo actua si el modulo esta, la
        parcela tiene integrales y hay una fecha a la que acumular."""
        self._gdd_resumen = None
        if _GDD is None or not getattr(self, "gdd_card", None) or not self.gdd_card.winfo_exists():
            return
        cult = self._cultivo_de(self.campana)
        spec = spec_de(cult)
        # Sin integrales definidas, esta seccion no aporta nada: se esconde y el
        # programa sigue con el calendario, como si no existiera.
        if not spec or not spec.get("integrales_termicas"):
            self.gdd_card.pack_forget()
            return
        self.gdd_card.pack(fill="both", expand=True)
        fecha = dias[-1]["fecha"] if dias else None
        res = _GDD.resumen_parcela(cult.get("tipo"), spec.get("especie"), spec, fecha, self.nombre)
        self._gdd_resumen = res
        if not res:
            self.lbl_gdd.config(text="Integrales térmicas definidas, pero aún no hay clima "
                                     "descargado para acumular grados-día. Pulsa «Descargar clima».")
            self.cb_gdd["values"] = []
            self.cb_gdd.set("")
            self.lbl_gdd_ref.config(text="")
            return
        ac = res.get("gdd_acumulado")
        partes = []
        if ac is not None:
            partes.append(f"GDD acumulado desde la siembra: {ac:.0f} °C·día "
                          f"({res.get('dias', 0)} días" +
                          (f", {res['huecos']} sin dato" if res.get("huecos") else "") + ").")
        if res.get("fase_gdd"):
            partes.append(f"Fase por grados-día: {res['fase_gdd']}.")
        if res.get("faltan_siguiente") is not None:
            partes.append(f"Faltan ~{res['faltan_siguiente']:.0f} °C·día para la siguiente fase.")
        if not res.get("hay_referencia"):
            partes.append("(Este cultivo no tiene tabla de referencia de GDD: la fase la sigue "
                          "marcando el calendario.)")
        elif spec.get("integrales_termicas"):
            partes.append("Con integral definida, la fase del diagnóstico la marca el GDD.")
        self.lbl_gdd.config(text="  ".join(partes) if partes else
                            "Sin fecha de siembra o sin clima: no se puede acumular todavía.")
        etiquetas = [f"{it['desde']} → {it['hasta']}  ·  {it['metodo']}" for it in res.get("integrales", [])]
        self.cb_gdd["values"] = etiquetas
        if etiquetas:
            self.cb_gdd.current(0)
            self._pintar_gdd_sel()
        else:
            self.cb_gdd.set("")
            self.lbl_gdd_ref.config(text="")

    def _pintar_gdd_sel(self):
        """Ensena la referencia de bibliografia de la integral elegida en el combo."""
        res = getattr(self, "_gdd_resumen", None)
        if not res:
            return
        i = self.cb_gdd.current()
        filas = res.get("integrales", [])
        if i < 0 or i >= len(filas):
            self.lbl_gdd_ref.config(text="")
            return
        it = filas[i]
        ref = it.get("referencia_gdd")
        if ref is not None:
            txt = (f"De «{it['desde']}» a «{it['hasta']}» ({it['metodo']}): "
                   f"referencia de bibliografía ≈ {ref:.0f} °C·día. "
                   "Compárala con el acumulado real para ver si el cultivo va adelantado o atrasado.")
        else:
            txt = (f"De «{it['desde']}» a «{it['hasta']}» ({it['metodo']}): "
                   "sin referencia de bibliografía para ese tramo (los extremos deben ser "
                   "fases conocidas del cultivo).")
        self.lbl_gdd_ref.config(text=txt)

    def _sincronizar_clima(self):
        if _CLIMA is None:
            return
        if not _EE:
            return messagebox.showwarning("Clima", "earthengine-api no disponible.")
        ficha = self.panel.vista_ficha

        def worker():
            n, msg = _CLIMA.sincronizar_clima(self.nombre, self.campana, silencioso=True)

            def fin():
                if not ficha.winfo_exists():
                    return
                self._pintar_clima()
                messagebox.showinfo("Clima", f"{msg}.")
            ficha.after(0, fin)
        threading.Thread(target=worker, daemon=True).start()

    def _build_estadisticas(self, parent):
        card = tarjeta(parent)
        card.pack(fill="both", expand=True)
        self._titulo(card, "Estadistica dentro de la parcela (distribucion del NDVI)")
        self.lbl_estad = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                  font=FUENTES["small"], justify="left", anchor="w")
        self.lbl_estad.pack(fill="x", padx=12, pady=(0, 4))
        cols = [c[0] for c in self.COLS_ESTAD]
        self.tv_est = ttk.Treeview(card, columns=cols, show="headings", height=7)
        for clave, titulo, ancho, _dec in self.COLS_ESTAD:
            self.tv_est.heading(clave, text=titulo)
            self.tv_est.column(clave, width=esc(ancho),
                               anchor="w" if clave == "fecha" else "center")
        self.tv_est.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.tv_est.tag_configure("ult", background=TEMA["warn_bg"])

    def _pintar_estadisticas(self, regs):
        """Vuelca los estadisticos espaciales de cada pasada. Los valores ya venian
        del satelite; aqui solo se muestran (no se calcula ningun diagnostico)."""
        if not hasattr(self, "tv_est") or not self.tv_est.winfo_exists():
            return
        self.tv_est.delete(*self.tv_est.get_children())
        filas = [e for e in (CI.estadisticas_pasada(r) for r in regs) if e]
        for k, e in enumerate(filas):
            valores = []
            for clave, _t, _a, dec in self.COLS_ESTAD:
                v = e.get(clave)
                if v is None:
                    valores.append("-")
                elif dec == "pct":
                    valores.append(f"{v * 100:.0f}" if v <= 1 else f"{v:.0f}")
                elif dec is None:
                    valores.append(str(v))
                else:
                    valores.append(f"{v:.{dec}f}")
            tag = ("ult",) if k == len(filas) - 1 else ()
            self.tv_est.insert("", tk.END, tags=tag, values=valores)
        if filas:
            self.lbl_estad.config(
                text="MEDIA/DESV. del NDVI entre los pixeles de la parcela · CV = desv./media "
                     "(dispersion relativa) · P90-P10 = distancia entre el mejor y el peor 10 % · "
                     "COB.% = pixeles validos tras descartar nubes.")
        else:
            self.lbl_estad.config(
                text="Las pasadas de esta parcela no traen estadistica espacial (son anteriores "
                     "al enmascarado por SCL). Al sincronizar pasadas nuevas apareceran aqui.")

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
        ttk.Button(top2, text="⧉ Comparar", command=self._comparar_mapas).pack(side="left", padx=(6, 4))
        self.lbl_res = tk.Label(top2, text="", bg=TEMA["surface"], fg=TEMA["text_muted"],
                                font=FUENTES["small"])
        self.lbl_res.pack(side="left", padx=8)

        cont = tk.Frame(card, bg=TEMA["surface"])
        cont.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.lienzo = LienzoMapa(cont, on_info=lambda t: self.lbl_res.winfo_exists() and
                                 self.lbl_res.config(text=t))
        self.lienzo.pack(side="left", fill="both", expand=True)
        self.canvas_mapa = self.lienzo.canvas   # alias para mensajes de estado
        ui_tema.cargar_matplotlib()   # se carga aqui, no al abrir el programa
        self.fig_ley = ui_tema.Figure(figsize=(1.0, 3.2), dpi=90)
        self.cv_ley = ui_tema.FigureCanvasTkAgg(self.fig_ley, master=cont)
        self.cv_ley.get_tk_widget().pack(side="right", fill="y")

    def _zoom(self, factor):
        """factor None = ajustar al lienzo; si no, multiplica el zoom actual."""
        if factor is None:
            self.lienzo.ajustar()
        else:
            self.lienzo.zoom_rel(factor)

    def _redibujar_png(self):
        self.lienzo.redibujar()

    def _build_graficas(self, parent):
        card = tarjeta(parent, width=560)
        card.pack(side="left", fill="both", expand=True, padx=(0, 7))
        self._titulo(card, "Evolucion en la campana")
        # selector de indices a mostrar en la grafica
        ctrl = tk.Frame(card, bg=TEMA["surface"])
        ctrl.pack(fill="x", padx=12, pady=(0, 2))
        tk.Label(ctrl, text="Indices:", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left")
        self.idx_vars = {}
        for K in INDICES_ORDEN:
            v = tk.BooleanVar(value=(K in INDICES_GRAFICA_DEF))
            self.idx_vars[K] = v
            ttk.Checkbutton(ctrl, text=K, variable=v, command=self._replot).pack(side="left", padx=1)
        # RVI (radar Sentinel-1): solo se dibuja si se han descargado pasadas de radar
        self.idx_vars["RVI"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="RVI·S1", variable=self.idx_vars["RVI"],
                        command=self._replot).pack(side="left", padx=(6, 1))
        ui_tema.cargar_matplotlib()   # se carga aqui, no al abrir el programa
        self.fig = ui_tema.Figure(figsize=(6, 2.7), dpi=90)
        self.cv = ui_tema.FigureCanvasTkAgg(self.fig, master=card)
        self.cv.get_tk_widget().pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _replot(self):
        self._pintar_graficas(getattr(self, "_regs_actual", []))

    def _build_interp(self, parent):
        card = tarjeta(parent, width=420)
        card.pack(side="right", fill="both", padx=(7, 0))
        card.pack_propagate(False)
        self._titulo(card, "Interpretacion automatica")

        # --- selector de pasada ---------------------------------------------
        # Por defecto se ve la ultima, como siempre. El desplegable permite mirar
        # -y validar- cualquier dia anterior: la marca ✓ dice cual ya revisaste.
        # Solo aparece con el modulo opcional de calibracion.
        if _CALIB is not None:
            sel = tk.Frame(card, bg=TEMA["surface"])
            sel.pack(fill="x", padx=12, pady=(0, 4))
            tk.Label(sel, text="Pasada", bg=TEMA["surface"], fg=TEMA["text_sec"],
                     font=FUENTES["small"]).pack(side="left")
            self.cb_interp = ttk.Combobox(sel, state="readonly", width=30)
            self.cb_interp.pack(side="left", padx=(6, 0), fill="x", expand=True)
            self.cb_interp.bind("<<ComboboxSelected>>", self._cambiar_pasada_interp)

        # Incluir o no el analisis de ZONAS (heterogeneidad) en la interpretacion.
        # Hay parcelas donde no aporta -muy pequenas, muy uniformes, o donde ya se
        # sabe de donde viene la mancha- y el aviso solo estorba. Se guarda con la
        # parcela: por defecto SI, que es como se ha comportado siempre.
        self.var_hetero = tk.BooleanVar(value=True)
        fila_h = tk.Frame(card, bg=TEMA["surface"])
        fila_h.pack(fill="x", padx=12, pady=(0, 4))
        self.chk_hetero = ttk.Checkbutton(
            fila_h, text="Analizar zonas dentro de la parcela (heterogeneidad)",
            variable=self.var_hetero, command=self._cambiar_heterogeneidad)
        self.chk_hetero.pack(anchor="w")

        self.txt = tk.Text(card, wrap="word", height=8, bd=0, relief="flat",
                           bg=TEMA["nota_bg"], fg=TEMA["text"], font=FUENTES["body"],
                           padx=12, pady=10, highlightthickness=0)
        self.txt.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        # --- validacion del diagnostico (aprendizaje para futuras pasadas) ---
        val = tk.Frame(card, bg=TEMA["surface"])
        val.pack(fill="x", padx=12, pady=(0, 10))
        self.lbl_val = tk.Label(val, text="¿El diagnostico es correcto?", bg=TEMA["surface"],
                                fg=TEMA["text_sec"], font=FUENTES["small"])
        self.lbl_val.pack(anchor="w")
        # La observacion escrita se pide en el dialogo de "Corregir", no aqui: tener
        # ademas una caja de texto en la ficha era redundante.
        botones = tk.Frame(val, bg=TEMA["surface"])
        botones.pack(fill="x", pady=(4, 0))
        self.btn_val_ok = ttk.Button(botones, text="  ✓ Correcto  ", style="Ghost.TButton",
                                     command=lambda: self._validar("correcto"))
        self.btn_val_ok.pack(side="left")
        self.btn_val_no = ttk.Button(botones, text="  ✗ Corregir…  ", style="Ghost.TButton",
                                     command=self._abrir_correccion)
        self.btn_val_no.pack(side="left", padx=(6, 0))
        if _CALIB is not None:
            self.btn_val_idx = ttk.Button(botones, text="  Indices…  ", style="Ghost.TButton",
                                          command=self._abrir_validacion_indices)
            self.btn_val_idx.pack(side="left", padx=(6, 0))

    def _cambiar_heterogeneidad(self):
        """Guarda la eleccion con la parcela y vuelve a interpretar al momento."""
        ficha = DB.ficha(self.nombre) or {}
        ficha["heterogeneidad"] = bool(self.var_hetero.get())
        DB.guardar_ficha(self.nombre, ficha)
        # la interpretacion cacheada de las pasadas se hizo con el ajuste anterior
        for r in (getattr(self, "_regs_actual", None) or []):
            r["interpretacion"] = None
        self.refrescar()

    # ---- seleccion de la pasada que se interpreta ----
    def _cambiar_pasada_interp(self, _=None):
        """El usuario elige otro dia en el desplegable: se reinterpreta ESE dia."""
        self._pasada_sel = self.cb_interp.current()
        self._pintar_interp(getattr(self, "_regs_actual", []) or [])

    def _indice_pasada(self, regs):
        """Posicion de la pasada que hay que interpretar. Por defecto, la ultima.

        Si el usuario habia elegido otra, se respeta mientras siga existiendo (al
        sincronizar entran pasadas nuevas y la lista crece)."""
        if not regs:
            return -1
        i = getattr(self, "_pasada_sel", None)
        if i is None or not (0 <= i < len(regs)):
            return len(regs) - 1
        return i

    def _refrescar_selector_pasadas(self, regs, idx):
        if _CALIB is None or not hasattr(self, "cb_interp") or not self.cb_interp.winfo_exists():
            return
        validadas = DB.pasadas_validadas(self.nombre, self.campana)
        etiquetas = [("✓ " if r.get("fecha") in validadas else "    ") + self._fmt(r["fecha"])
                     for r in regs if r.get("fecha")]
        if list(self.cb_interp["values"]) != etiquetas:
            self.cb_interp["values"] = etiquetas
        if etiquetas and 0 <= idx < len(etiquetas):
            self.cb_interp.current(idx)

    def refrescar(self):
        # La ficha se destruye al abrir OTRA parcela. Si mientras tanto seguia
        # sincronizando, el hilo vuelve por after() y se encuentra los widgets ya
        # muertos: sin esta comprobacion salta TclError (invalid command name).
        if not hasattr(self, "tv") or not self.tv.winfo_exists():
            return
        regs = sorted(self.panel._historico(self.nombre), key=lambda r: r.get("fecha", ""))
        self._radar = sorted(DB.radar(self.nombre, self.campana), key=lambda r: r.get("fecha", ""))
        self.tv.delete(*self.tv.get_children())       # vaciado en UNA llamada a Tk
        for k, r in enumerate(regs):
            tag = ("ult",) if k == len(regs) - 1 else ()
            self.tv.insert("", tk.END, tags=tag, values=[r.get("fecha", "")] +
                           [f"{r.get(x.lower()):.3f}" if r.get(x.lower()) is not None else "-"
                            for x in INDICES_ORDEN])
        self._map_fechas = {self._fmt(r["fecha"]): r["fecha"] for r in regs if r.get("fecha")}
        self.cb_dia["values"] = list(self._map_fechas.keys())
        if self._map_fechas:
            self.cb_dia.current(len(self._map_fechas) - 1)
        self._refrescar_campanas()
        self._pintar_leyenda()
        self._pintar_graficas(regs)
        self._pintar_interp(regs)
        self._pintar_clima()
        self._pintar_estadisticas(regs)
        self._pintar_mapa()

    @staticmethod
    def _fmt(iso):
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{_FMT_DIAS[d.weekday()]}, {d.day} {_FMT_MESES[d.month-1]} {d.year}"

    def _pintar_graficas(self, regs):
        ui_tema.cargar_matplotlib()   # se carga aqui, no al abrir el programa
        self._regs_actual = regs         # para volver a pintar al cambiar de indices
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        self._hover_ax = ax
        self._hover_datos = []          # [(x_num, registro, texto_tooltip), ...] para el puntero
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
            # el texto del tooltip se calcula UNA vez por pasada (no en cada movimiento del raton)
            self._hover_datos = [(ui_tema.mdates.date2num(f), r, tooltip_pasada(r))
                                 for f, r in zip(fechas, validos)]
            idx_vars = getattr(self, "idx_vars", None)   # una sola lectura, coherente abajo
            if idx_vars:
                seleccion = [K for K in INDICES_ORDEN if idx_vars[K].get()]
            else:
                seleccion = INDICES_GRAFICA_DEF
            for K in seleccion:
                ys = [r.get(K.lower()) for r in validos]
                if any(v is not None for v in ys):
                    ax.plot(fechas, [v if v is not None else float("nan") for v in ys],
                            marker="o", ms=3, lw=1.8, label=K, color=color_serie(K))
            # RVI de Sentinel-1 (radar): serie propia, con sus fechas, si existe y esta marcada
            if (idx_vars and idx_vars.get("RVI") and idx_vars["RVI"].get()
                    and getattr(self, "_radar", None)):
                # se parsea CADA fecha de radar una sola vez (antes se hacia hasta 3 veces)
                rad = []
                for r in self._radar:
                    try:
                        fx = datetime.strptime(r.get("fecha", ""), "%Y-%m-%d")
                    except (TypeError, ValueError):
                        continue
                    rad.append((fx, r.get("rvi"), r.get("rvi_lo"), r.get("rvi_hi")))
                rp = [(f, y) for f, y, _lo, _hi in rad if y is not None]
                if rp:
                    ax.plot([p[0] for p in rp], [p[1] for p in rp], marker="s", ms=3, lw=1.6,
                            ls="--", label="RVI·S1", color=color_serie("RVI"))
                    # banda de incertidumbre del RVI (rango por speckle/dispersion)
                    banda = [(f, lo, hi) for f, _y, lo, hi in rad if lo is not None and hi is not None]
                    if len(banda) >= 2:
                        ax.fill_between([b[0] for b in banda], [b[1] for b in banda],
                                        [b[2] for b in banda], color=color_serie("RVI"), alpha=0.15)
            # --- marcadores de eventos del cuaderno de campo ---
            vistos = set()
            for e in REG.eventos_de(self.nombre, self.campana):
                try:
                    fx = datetime.strptime(e["fecha"], "%Y-%m-%d")
                except Exception:
                    continue
                et = _NOMBRE_EVENTO.get(e.get("tipo"), _NOMBRE_EVENTO["OTRO"])
                lbl = et if et not in vistos else None
                vistos.add(et)
                ax.axvline(fx, color=TEMA["traza"], ls=":", lw=1.0, alpha=0.8, label=lbl)
            ax.legend(fontsize=7, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.18))
            self.fig.autofmt_xdate()
            # --- puntero interactivo: linea vertical + caja con los valores del dia ---
            self._hover_linea = ax.axvline(fechas[0], color=TEMA["traza"], lw=0.8,
                                           alpha=0.0, zorder=1)
            self._hover_caja = ax.annotate(
                "", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
                fontsize=7.5, ha="left", va="bottom", visible=False, zorder=6,
                bbox=dict(boxstyle="round,pad=0.4", fc=TEMA["tooltip_bg"],
                                          ec=TEMA["tooltip_bg"], alpha=0.92),
                color=TEMA["tooltip_fg"])
            if getattr(self, "_hover_cid", None) is not None:
                try:
                    self.cv.mpl_disconnect(self._hover_cid)
                except Exception:
                    pass    # silencio deliberado: el callback ya no existe tras redibujar
            self._hover_cid = self.cv.mpl_connect("motion_notify_event", self._on_hover)
        self.fig.tight_layout()
        self.cv.draw_idle()       # agrupado por Tk, no bloquea

    def _on_hover(self, event):
        """Muestra los valores de los indices y la fiabilidad del dia mas cercano."""
        caja = getattr(self, "_hover_caja", None)
        if caja is None or not self._hover_datos or event.inaxes is not getattr(self, "_hover_ax", None):
            if caja is not None and caja.get_visible():
                caja.set_visible(False)
                self._hover_linea.set_alpha(0.0)
                self.cv.draw_idle()
            return
        x = event.xdata
        xn, reg, texto = min(self._hover_datos, key=lambda t: abs(t[0] - x))
        self._hover_linea.set_xdata([xn, xn])
        self._hover_linea.set_alpha(0.6)
        caja.xy = (xn, event.ydata)
        caja.set_text(texto)
        # coloca la caja hacia el interior para que NO se salga por los bordes
        ax = self._hover_ax
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        fx = (xn - x0) / (x1 - x0) if x1 != x0 else 0.0
        fy = (event.ydata - y0) / (y1 - y0) if y1 != y0 else 0.0
        dx, ha = (-12, "right") if fx > 0.55 else (12, "left")
        dy, va = (-12, "top") if fy > 0.6 else (12, "bottom")
        caja.set_position((dx, dy))
        caja.set_ha(ha)
        caja.set_va(va)
        caja.set_visible(True)
        self.cv.draw_idle()

    def _pintar_leyenda(self):
        ui_tema.cargar_matplotlib()   # se carga aqui, no al abrir el programa
        self.fig_ley.clear()
        idx = self.cb_idx.get()
        ax = self.fig_ley.add_axes([0.1, 0.05, 0.32, 0.9])
        cmap = ui_tema.mcolors.LinearSegmentedColormap.from_list("x", ["#" + c for c in INDICES[idx]["paleta"]])
        cb = ui_tema.matplotlib.colorbar.ColorbarBase(ax, cmap=cmap,
                                              norm=ui_tema.mcolors.Normalize(*INDICES[idx]["rango"]),
                                              orientation="vertical")
        cb.ax.tick_params(labelsize=7)
        cb.set_label(idx, fontsize=8)
        self.cv_ley.draw_idle()   # agrupado por Tk, no bloquea

    def _pintar_interp(self, regs):
        self.txt.delete("1.0", tk.END)
        if not regs:
            self.txt.insert(tk.END, "Sin datos. Pulsa \'Sincronizar Copernicus\'.")
            return
        # La pasada elegida sale del desplegable (Tk); a partir de ahi, DECIDIR que
        # mostrar es puro y vive en `vista_ficha.preparar_interpretacion`, probado
        # sin pantalla. Aqui solo se pinta.
        idx = self._indice_pasada(regs)
        self._refrescar_selector_pasadas(
            sorted(self.panel._historico(self.nombre), key=lambda r: r.get("fecha", "")), idx)

        r = preparar_interpretacion(self.nombre, self.campana, regs, idx)

        # la casilla de zonas refleja lo que hay guardado para la parcela
        if hasattr(self, "var_hetero") and self.var_hetero.get() != bool(r["hetero_on"]):
            self.var_hetero.set(bool(r["hetero_on"]))

        self._estado_actual = r["estado"]
        self._val_ctx = r["val_ctx"]           # contexto para corregir el diagnostico
        if r["idx_ctx"] is not None:           # contexto de validacion POR INDICE
            self._idx_ctx = r["idx_ctx"]

        encabezado = r["encabezado"]
        self.txt.insert(tk.END, encabezado)
        self._refrescar_validacion()

        if r["es_barbecho"]:
            self.txt.insert(tk.END, r["motivo"])
            return
        # validaciones pasadas del agricultor -> aprendizaje para la IA (con tus notas)
        aprendizaje = DB.validaciones_recientes(limite=8, cultivo=r["cultivo_id"])
        if r["interpretacion_cache"]:          # cacheado (se invalida al corregir)
            self.txt.insert(tk.END, r["interpretacion_cache"])
            return
        self.txt.insert(tk.END, "Generando interpretacion...")

        tipo, sub, spec = r["tipo"], r["sub"], r["spec"]
        regs_hasta, actual = r["regs"], r["actual"]
        eventos_cerca, hetero_on = r["eventos_cerca"], r["hetero_on"]

        def worker():
            # Los MISMOS argumentos con que se resolvio la cabecera:
            # `texto_interpretacion` vuelve a evaluar por dentro, y con otros
            # argumentos el semaforo y el texto de abajo saldrian de dos
            # diagnosticos distintos -y el texto ademas se guarda en la base-.
            texto, _d = texto_interpretacion(tipo, sub, regs_hasta, actual.get("fecha"),
                                             eventos_cerca=eventos_cerca, spec=spec,
                                             aprendizaje=aprendizaje,
                                             parcela=self.nombre,
                                             heterogeneidad_activa=hetero_on)
            DB.set_interpretacion(self.nombre, self.campana, actual.get("fecha"), texto)

            def pintar():
                if not self.txt.winfo_exists():   # el usuario ya navego a otra vista
                    return
                self.txt.delete("1.0", tk.END)
                self.txt.insert(tk.END, encabezado + texto)
            self.master.after(0, pintar)
        threading.Thread(target=worker, daemon=True).start()

    # ---- validacion del diagnostico ----
    def _refrescar_validacion(self):
        """Muestra si la pasada actual ya fue validada y con que veredicto."""
        if not hasattr(self, "lbl_val") or not self.lbl_val.winfo_exists():
            return
        ctx = getattr(self, "_val_ctx", None)
        if not ctx or not ctx.get("fecha"):
            self.lbl_val.config(text="Sin pasada que validar.")
            return
        v = DB.validacion_de(self.nombre, self.campana, ctx["fecha"])
        if not v:
            self.lbl_val.config(text="¿El diagnostico es correcto?", fg=TEMA["text_sec"])
        elif v.get("veredicto") == "correcto":
            self.lbl_val.config(text="✓ Validado como correcto.", fg=TEMA["ok_fg"])
        else:
            self.lbl_val.config(text=f"✗ Corregido a: {v.get('estado_real','?')}.", fg=TEMA["danger_fg"])

    def _validar(self, veredicto, estado_real=None, nota="", solo_parcela=False,
                 fase_real=None):
        ctx = getattr(self, "_val_ctx", None)
        if not ctx or not ctx.get("fecha"):
            return messagebox.showinfo("Validacion", "No hay ninguna pasada que validar.", parent=self.master)
        # AMBITO: si el usuario marca "solo esta parcela", la correccion se guarda con
        # la clave acotada y no afectara al resto de sus parcelas del mismo cultivo.
        clave = ctx.get("cultivo")
        if solo_parcela:
            clave = ambito_parcela(clave, self.nombre)
        DB.guardar_validacion(self.nombre, self.campana, ctx["fecha"], ctx.get("fase"),
                              clave, ctx.get("estado"), veredicto,
                              estado_real=estado_real, nota=nota, fase_real=fase_real)
        # APRENDER AL MOMENTO: si corriges o escribes una observacion, se descarta la
        # interpretacion cacheada de esta pasada para que se regenere teniendo en cuenta
        # lo que acabas de decir; ademas se vuelve a pintar la interpretacion ya mismo.
        regs = getattr(self, "_regs_actual", None)
        if veredicto == "incorrecto" or (nota or "").strip():
            DB.set_interpretacion(self.nombre, self.campana, ctx["fecha"], None)
            if regs:
                for r in regs:
                    if r.get("fecha") == ctx["fecha"]:
                        r["interpretacion"] = None
        if regs:
            self._pintar_interp(regs)
        else:
            self._refrescar_validacion()

    def _abrir_correccion(self):
        ctx = getattr(self, "_val_ctx", None)
        if not ctx or not ctx.get("fecha"):
            return messagebox.showinfo("Validacion", "No hay ninguna pasada que validar.", parent=self.master)
        DialogoCorreccion(self.master, self, ctx)

    def _abrir_validacion_indices(self):
        ctx = getattr(self, "_idx_ctx", None)
        if _CALIB is None or not ctx or not ctx.get("fecha"):
            return messagebox.showinfo("Validacion", "No hay ninguna pasada que validar.",
                                       parent=self.master)
        if not any(l.get("valor") is not None for l in (ctx.get("lecturas") or {}).values()):
            return messagebox.showinfo("Validacion", "Esa pasada no trae ningun indice medido.",
                                       parent=self.master)
        DialogoValidacionIndices(self.master, self, ctx)

    # ================= CUADERNO DE CAMPO =================
    # Filas visibles del historico de rendimientos. El resto se alcanza con la
    # barra: lo que NO puede es empujar el resto de la ficha.
    ALTO_RENDIMIENTOS = 3

    def _build_cuaderno(self, parent):
        card = tarjeta(parent)
        card.pack(fill="both", expand=True)
        self._titulo(card, "Cuaderno de campo (intervenciones)")

        form = tk.Frame(card, bg=TEMA["surface"])
        form.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(form, text="Fecha de la intervencion", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=0, sticky="w")
        self.ev_fecha = CampoFecha(form, iso=datetime.now().strftime("%Y-%m-%d"))  # hoy por defecto
        self.ev_fecha.grid(row=1, column=0, padx=(0, 8), sticky="w")
        tk.Label(form, text="Tipo", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=1, sticky="w")
        self.ev_tipo = ttk.Combobox(form, state="readonly", width=12, values=REG.TIPOS_EVENTO)
        self.ev_tipo.set("PRODUCTO")
        self.ev_tipo.grid(row=1, column=1, padx=(0, 8))
        self.ev_tipo.bind("<<ComboboxSelected>>", lambda e: self._toggle_campos_evento())
        # al cambiar la fecha puede cambiar la campana (y con ella el cultivo), asi
        # que se revisa si toca ensenar la humedad. add="+" para no pisar el manejador
        # propio de CampoFecha.
        self.ev_fecha.entry.bind("<FocusOut>", lambda e: self._toggle_campos_evento(), add="+")

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
        tk.Label(self.frame_prod, text="Dia informe (opc.)", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=6, sticky="w", padx=(8, 4))
        self.ev_informe = CampoFecha(self.frame_prod, width=11)
        self.ev_informe.grid(row=0, column=7, columnspan=2, sticky="w")

        # campos especificos de COSECHA. Todos OPCIONALES: son el dato de bascula,
        # no una estimacion. Comparten celda con frame_prod (nunca se ven a la vez).
        self.frame_cosecha = tk.Frame(form, bg=TEMA["surface"])
        self.frame_cosecha.grid(row=1, column=2, columnspan=3, sticky="w")
        tk.Label(self.frame_cosecha, text="Rendimiento (kg/ha)", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.ev_rend = ttk.Entry(self.frame_cosecha, width=9)
        self.ev_rend.grid(row=0, column=1, padx=(0, 8))
        # la humedad solo tiene sentido en grano de extensivo: en el resto no hay dato
        self.frame_humedad = tk.Frame(self.frame_cosecha, bg=TEMA["surface"])
        self.frame_humedad.grid(row=0, column=2, sticky="w")
        tk.Label(self.frame_humedad, text="Humedad grano (%)", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.ev_humedad = ttk.Entry(self.frame_humedad, width=7)
        self.ev_humedad.grid(row=0, column=1, padx=(0, 8))
        tk.Label(self.frame_cosecha, text="Superficie (ha)", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).grid(row=0, column=3, sticky="w", padx=(0, 4))
        self.ev_sup = ttk.Entry(self.frame_cosecha, width=8)
        self.ev_sup.grid(row=0, column=4, padx=(0, 8))
        tk.Label(self.frame_cosecha, text="Origen del dato", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).grid(row=0, column=5, sticky="w", padx=(0, 4))
        self.ev_fuente = ttk.Combobox(self.frame_cosecha, state="readonly", width=15,
                                      values=[""] + list(REG.FUENTES_DATO))
        self.ev_fuente.set("")
        self.ev_fuente.grid(row=0, column=6)

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
            self.tv_ev.column(c, width=esc(w), anchor="w")
        self.tv_ev.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.tv_ev.bind("<Double-1>", lambda e: self._ver_efecto_evento())
        self.tv_ev.bind("<Button-3>", self._menu_evento)
        tk.Label(card, text="Doble clic en un producto: ver su efecto sobre el cultivo. "
                            "Clic derecho: eliminar.", bg=TEMA["surface"],
                 fg=TEMA["text_muted"], font=FUENTES["small"]).pack(anchor="w", padx=12, pady=(0, 4))

        # Historico de cosecha: lo unico medido en bascula, no interpretado.
        # Se listan TODAS las campanas, no solo la que se esta viendo.
        tk.Label(card, text="Rendimientos registrados  ·  se anotan con un evento COSECHA (grano) "
                           "o SIEGA (forraje), que admite fechas de campanas anteriores",
                 bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=12)
        # Lista ACOTADA (ALTO_RENDIMIENTOS filas) con su propia barra: el historico
        # crece una linea por campana y esta ficha vive en un marco de altura fija,
        # asi que una etiqueta multilinea acabaria comiendose la tabla de eventos o
        # recortandose sola. Con la lista, ocupe lo que ocupe el historico, el alto
        # del cuaderno no se mueve.
        wrap_rend = tk.Frame(card, bg=TEMA["surface"])
        wrap_rend.pack(fill="x", padx=12, pady=(2, 10))
        self.lst_rend = tk.Listbox(wrap_rend, height=self.ALTO_RENDIMIENTOS,
                                   font=FUENTES["small"], bd=1, relief="solid",
                                   bg=TEMA["campo_bg"], fg=TEMA["text"],
                                   highlightthickness=0, activestyle="none",
                                   exportselection=False)
        sb_rend = ttk.Scrollbar(wrap_rend, orient="vertical", command=self.lst_rend.yview)
        self.lst_rend.configure(yscrollcommand=sb_rend.set)
        self.lst_rend.pack(side="left", fill="x", expand=True)
        sb_rend.pack(side="right", fill="y")
        self._toggle_campos_evento()
        self._refrescar_eventos()

    def _cultivo_de(self, campana):
        return ((DB.ficha(self.nombre) or {}).get("cultivos_por_campana", {}) or {}).get(campana, {})

    def _campana_evento(self, iso):
        return REG.campana_de_evento(self.ev_tipo.get(), iso, self.campana)

    def _toggle_campos_evento(self):
        tipo = self.ev_tipo.get()
        es_produccion = tipo in ("COSECHA", "SIEGA")   # ambos anotan kg/ha de bascula
        (self.frame_prod.grid if tipo == "PRODUCTO" else self.frame_prod.grid_remove)()
        (self.frame_cosecha.grid if es_produccion else self.frame_cosecha.grid_remove)()
        # la humedad de grano solo tiene sentido en la cosecha de grano, no en la siega
        if tipo == "COSECHA" and self._admite_humedad(self._campana_evento(self.ev_fecha.get_iso())):
            self.frame_humedad.grid()
        else:
            self.frame_humedad.grid_remove()

    def _admite_humedad(self, campana):
        """Si toca pedir la humedad del grano para una cosecha de esa campana. Las
        campanas viejas no suelen tener cultivo registrado: se hereda el de la que
        se esta viendo (ver REG.admite_humedad_en_campana)."""
        return REG.admite_humedad_en_campana(self._cultivo_de(campana),
                                             self._cultivo_de(self.campana))

    def _add_evento(self):
        fecha = self.ev_fecha.get_iso()
        if not fecha:
            return messagebox.showwarning("Fecha", "Elige la fecha de la intervencion (dd-mm-aaaa).")
        ev = {"fecha": fecha, "tipo": self.ev_tipo.get(), "notas": self.ev_notas.get().strip()}
        campana = self._campana_evento(fecha)
        if ev["tipo"] == "PRODUCTO":
            if not self.ev_prod.get().strip():
                return messagebox.showwarning("Producto", "Indica el nombre del producto.")
            ev.update({"producto": self.ev_prod.get().strip(),
                       "objetivo": self.ev_obj.get(), "dosis": self.ev_dosis.get().strip()})
            # dia del informe opcional: fecha en la que se quiere medir el efecto
            if not self.ev_informe.esta_vacio():
                informe = self.ev_informe.get_iso()
                if not informe:
                    return messagebox.showwarning("Dia informe", "Dia del informe: dd-mm-aaaa "
                                                  "(o dejalo vacio para el automatico).")
                ev["fecha_informe"] = informe
        elif ev["tipo"] in ("COSECHA", "SIEGA"):
            es_cosecha = ev["tipo"] == "COSECHA"
            titulo = "Cosecha" if es_cosecha else "Siega"
            # la humedad de grano solo se anota en la cosecha de grano de extensivo;
            # la siega (forraje) guarda kg/ha y superficie, pero no humedad de grano
            admite = es_cosecha and self._admite_humedad(campana)
            if es_cosecha and not admite and self.ev_humedad.get().strip():
                self._toggle_campos_evento()
                return messagebox.showwarning(
                    "Cosecha", "Este cultivo no es grano de extensivo: ahi no se anota "
                    "humedad de grano. Borra ese campo para continuar.")
            try:
                ev.update(REG.datos_cosecha(
                    self.ev_rend.get(), self.ev_humedad.get(), self.ev_sup.get(),
                    self.ev_fuente.get(), admite_humedad=admite))
            except ValueError as e:
                return messagebox.showwarning(titulo, f"Revisa el campo {e}: "
                                              "escribe un numero (o dejalo vacio).")
        REG.registrar_evento(self.nombre, campana, ev)
        self.ev_notas.delete(0, tk.END)
        if hasattr(self, "ev_prod"):
            self.ev_prod.delete(0, tk.END)
            self.ev_dosis.delete(0, tk.END)
            self.ev_informe.set_iso("")
        for w in (getattr(self, "ev_rend", None), getattr(self, "ev_humedad", None),
                  getattr(self, "ev_sup", None)):
            if w is not None:
                w.delete(0, tk.END)
        if hasattr(self, "ev_fuente"):
            self.ev_fuente.set("")
        if campana != self.campana:
            messagebox.showinfo("Cosecha", f"Anotada en la campana {campana}. Queda en el "
                                "historico de rendimientos; para ver el evento, cambia a esa "
                                "campana.", parent=self.master)
        self._refrescar_eventos()
        self._pintar_graficas(sorted(self.panel._historico(self.nombre),
                                     key=lambda r: r.get("fecha", "")))
        self.refrescar()   # el evento puede cambiar el diagnostico (siega/cosecha)

    def _refrescar_eventos(self):
        self.tv_ev.delete(*self.tv_ev.get_children())  # vaciado en UNA llamada a Tk
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
        self._refrescar_rendimientos()

    def _refrescar_rendimientos(self):
        if not hasattr(self, "lst_rend") or not self.lst_rend.winfo_exists():
            return
        filas = DB.rendimientos(self.nombre)
        self.lst_rend.delete(0, tk.END)          # vaciado en UNA llamada a Tk
        for r in filas:
            self.lst_rend.insert(tk.END, REG.linea_rendimiento(r))
        if filas:
            self.lst_rend.see(tk.END)            # la campana mas reciente, a la vista
        else:
            self.lst_rend.insert(tk.END, "  (todavia no hay ninguno)")
            self.lst_rend.itemconfig(0, foreground=TEMA["text_muted"])

    def _menu_evento(self, event):
        fila = self.tv_ev.identify_row(event.y)
        if not fila:
            return
        self.tv_ev.selection_set(fila)
        # OJO: el padre es self.master, no self. FichaParcela NO es un widget (es
        # una clase normal que pinta sobre master), asi que tk.Menu(self, ...)
        # reventaba con AttributeError: 'FichaParcela' object has no attribute 'tk'.
        m = tk.Menu(self.master, tearoff=0, bg=TEMA["surface"], fg=TEMA["text"], bd=0)
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
        DialogoEfectoProducto(self.master, self, ev, regs)

    def _pintar_mapa(self):
        self._pintar_leyenda()
        etq = self.cb_dia.get()
        if not etq:
            return
        iso = self._map_fechas.get(etq)
        idx = self.cb_idx.get()
        metros = dict(RESOLUCIONES).get(self.cb_res.get(), 10)
        # la cache distingue la resolucion: cada m/pixel es un PNG distinto
        png = ruta_cache_mapa(self.nombre, idx, iso, metros)
        if os.path.exists(png):
            self.lienzo.set_png(png, f"{metros} m/pixel")
        elif _EE and _PIL:
            self.lienzo.mensaje(f"Descargando a {metros} m/pixel...")
            threading.Thread(target=self._descargar, args=(iso, idx, png, metros),
                             daemon=True).start()
        else:
            self.lienzo.mensaje("(mapa no disponible sin GEE/PIL)")

    def _descargar(self, iso, idx, png, metros):
        try:
            coords = DB.ficha(self.nombre)["coordenadas"]
            dim = descargar_mapa_indice(coords, iso, idx, metros, png)
            self.master.after(0, lambda: self.lienzo.set_png(png, f"{dim}x{dim} px  ·  {metros} m/pixel"))
        except Exception as e:
            # ver nota en PanelMapaComparado._descargar: `e` debe fijarse por defecto
            self.master.after(0, lambda err=e: self.lienzo.mensaje(f"Error mapa: {err}",
                                                                   TEMA["danger_fg"]))

    def _comparar_mapas(self):
        if not self._map_fechas:
            return messagebox.showinfo("Comparar", "No hay dias disponibles todavia. "
                                       "Sincroniza primero.", parent=self.master)
        VentanaComparaMapas(self.master, self.nombre, self.campana,
                            dict(self._map_fechas), self.cb_idx.get(), self.cb_res.get())

    def _editar(self):
        self.panel.editar_parcela(self.nombre, self.campana)

    def _sincronizar_anteriores(self):
        DialogoSincronizarCampanas(self.master, self.panel, self.nombre, self.campana)

    def _borrar_campana(self):
        """Borra TODO lo de la campana abierta, con doble confirmacion. Al terminar
        vuelve a la lista, porque la campana que se estaba mirando ya no existe."""
        def hecho():
            self.panel.mostrar_lista()
        DialogoBorrarCampana(self.master, self.nombre, self.campana, hecho)

    # ---- Sentinel-1 (radar): SOLO bajo demanda desde el boton ----
    def _sincronizar_radar(self):
        if not _EE:
            return messagebox.showwarning("Sentinel-1", "earthengine-api no disponible.", parent=self.master)
        threading.Thread(target=self._sync_radar, daemon=True).start()

    def _sync_radar(self):
        n, msg = gee_cliente.sincronizar_radar(self.nombre, self.campana, silencioso=True)

        def fin():
            try:
                if not self.cv.get_tk_widget().winfo_exists():
                    return                                 # ficha cerrada mientras descargaba
            except Exception:
                return
            self._radar = sorted(DB.radar(self.nombre, self.campana), key=lambda r: r.get("fecha", ""))
            self._pintar_graficas(getattr(self, "_regs_actual", []))   # dibuja la linea RVI·S1
            optica = sorted(self.panel._historico(self.nombre), key=lambda r: r.get("fecha", ""))
            cult = (DB.ficha(self.nombre) or {}).get("cultivos_por_campana", {}).get(self.campana, {})
            diag = None
            if optica:
                diag = evaluar_parcela(cult.get("tipo", "BARBECHO"), cult.get("subtipo", ""),
                                       optica, spec=spec_de(cult))
            info = S1.interpretar_radar(optica, self._radar, diag)
            VentanaRadar(self.master, self.nombre, self.campana, self._radar, info, n, msg)
        self.master.after(0, fin)

    def _menu_exportar(self):
        """Menu emergente con los formatos que ofrece el modulo opcional informe_anual.
        Si ese fichero se borra, este boton ni siquiera existe."""
        if _INFORME is None:
            return
        m = tk.Menu(self.master, tearoff=0)
        m.add_command(label="Informe de balance (PDF)",
                      command=lambda: self._exportar("balance"))
        m.add_command(label="Informe tecnico (PDF)",
                      command=lambda: self._exportar("tecnico"))
        m.add_separator()
        excel_ok = getattr(_INFORME, "EXCEL_DISPONIBLE", False)
        m.add_command(label="Hoja de calculo Excel (indices por mes + graficas)"
                            + ("" if excel_ok else "  —  requiere openpyxl"),
                      command=lambda: self._exportar("excel"),
                      state=("normal" if excel_ok else "disabled"))
        try:
            m.tk_popup(self.master.winfo_pointerx(), self.master.winfo_pointery())
        finally:
            m.grab_release()

    def _exportar(self, formato):
        """Genera balance/tecnico (PDF) o Excel. Delegado al modulo opcional informe_anual."""
        if _INFORME is None:
            return
        pdf_ok = getattr(_INFORME, "DISPONIBLE", False)
        excel_ok = getattr(_INFORME, "EXCEL_DISPONIBLE", False)
        if formato in ("balance", "tecnico") and not pdf_ok:
            return messagebox.showwarning(
                "Exportar", getattr(_INFORME, "MOTIVO_NO_DISPONIBLE",
                                    "Falta reportlab."), parent=self.master)
        if formato == "excel" and not excel_ok:
            return messagebox.showwarning(
                "Exportar", getattr(_INFORME, "MOTIVO_EXCEL", "Falta openpyxl."),
                parent=self.master)
        serie = sorted(self.panel._historico(self.nombre), key=lambda r: r.get("fecha", ""))
        if not serie:
            return messagebox.showinfo(
                "Exportar", "Esta parcela aun no tiene pasadas de satelite que resumir.",
                parent=self.master)
        ficha = DB.ficha(self.nombre) or {}
        cultivo = (ficha.get("cultivos_por_campana", {}) or {}).get(self.campana, {})
        radar = sorted(DB.radar(self.nombre, self.campana), key=lambda r: r.get("fecha", ""))
        eventos = REG.eventos_de(self.nombre, self.campana)

        cfg = {"balance": ("Informe de balance", _INFORME.generar_informe_anual, ".pdf", "PDF", "pdf"),
               "tecnico": ("Informe tecnico", _INFORME.generar_informe_tecnico, ".pdf", "PDF", "pdf"),
               "excel":   ("Hoja de calculo", _INFORME.generar_excel, ".xlsx", "Excel", "xlsx")}
        titulo, generar, ext, etiq, sufijo = cfg[formato]
        base = "Informe" if formato != "excel" else "Indices"
        destino = filedialog.asksaveasfilename(
            parent=self.master, title=f"Guardar {titulo.lower()}", defaultextension=ext,
            filetypes=[(etiq, f"*{ext}")],
            initialfile=f"{base}_{sufijo}_{self.nombre}_{self.campana}{ext}")
        if not destino:
            return

        def worker():
            try:
                ruta = generar(self.nombre, self.campana, ficha, cultivo, serie,
                               radar=radar, eventos=eventos, ruta_salida=destino)
            except Exception as e:
                self.master.after(0, lambda err=e: messagebox.showerror(
                    titulo, f"No se pudo generar:\n\n{err}", parent=self.master))
                return

            def ok():
                if messagebox.askyesno(titulo, f"Generado:\n{ruta}\n\n¿Abrirlo ahora?",
                                       parent=self.master):
                    _abrir_archivo(ruta)
            self.master.after(0, ok)
        threading.Thread(target=worker, daemon=True).start()

    def sincronizar(self):
        if not _EE:
            return messagebox.showwarning("GEE", "earthengine-api no disponible.")
        threading.Thread(target=self._sync, daemon=True).start()

    def _sync(self):
        n, msg = sincronizar_parcela(self.nombre, self.campana, silencioso=True)
        if ULTIMO_SYNC.get("estado") != "fallo":
            sincronizacion.marca_guardar()
        self.master.after(0, self.refrescar)
        self.master.after(0, self.panel._refrescar)
        self.master.after(0, self.panel._actualizar_estado_sync)
        self.master.after(0, lambda: messagebox.showinfo(
            "Sincronizacion", f"{self.nombre}: {msg}." if n == 0 else
            f"{self.nombre}: {msg} (incremental, sin sobrescribir)."))
