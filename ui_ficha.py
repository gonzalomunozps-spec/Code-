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

Es la pantalla mas grande del programa y por eso tiene modulo propio. Para que no
sea un unico fichero gigante, `FichaParcela` se compone de MIXINS por seccion, en
ficheros aparte (mismo `self`, mismos nombres de metodo; solo cambia donde vive el
codigo, no que hace):

  CuadernoMixin   (ficha_cuaderno)    cuaderno de campo y rendimientos
  ClimaGddMixin   (ficha_clima_gdd)   clima ERA5, balance hidrico y grados-dia
  ValidacionMixin (ficha_validacion)  observaciones de campo y su nota
  ExportMixin     (ficha_export)      informes de balance/tecnico y Excel

Las constantes y ayudantes de presentacion compartidos viven en `ficha_comun`
(para que los mixins los importen sin crear un ciclo con `ui_ficha`). Lo que queda
aqui es el armazon: `__init__`/`refrescar`, la tabla, el mapa, la grafica, la
interpretacion y las estadisticas, mas las ventanas auxiliares.

Abre los dialogos de `ui_dialogos` pasandose a si misma; ellos no la importan.

OJO: `FichaParcela`, `LienzoMapa` y `PanelMapaComparado` NO son widgets: son
clases normales que pintan sobre un `master`. Pasarles `self` como padre de un
widget lanza AttributeError, y dentro de un callback de Tk no se ve: el widget
simplemente no aparece. Usa `self.master`.
"""

import os
import threading
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox

import ui_tema
from ui_tema import (TEMA, FUENTES, esc, geom, tarjeta, centrar_sobre,
                     marco_scroll, enlazar_rueda, color_serie)
from ui_widgets import LienzoMapa
from ui_dialogos import (DialogoCorreccion, DialogoValidacionIndices, DialogoBorrarCampana,
                         DialogoSincronizarCampanas)
from ficha_cuaderno import CuadernoMixin
from ficha_clima_gdd import ClimaGddMixin
from ficha_validacion import ValidacionMixin
from ficha_export import ExportMixin

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
try:
    import heterogeneidad_espacial as _HE
except Exception:
    _HE = None
try:
    import validacion as _VAL
except Exception:
    _VAL = None

# Constantes de presentacion y ayudantes sueltos: viven en `ficha_comun` para que
# los mixins de la ficha los compartan sin crear un ciclo de imports.
from ficha_comun import (_PIL, _EE, _FMT_DIAS, _FMT_MESES, _NOMBRE_EVENTO,
                         tooltip_pasada, INDICES_GRAFICA_DEF, RESOLUCIONES)


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


class FichaParcela(CuadernoMixin, ClimaGddMixin, ValidacionMixin, ExportMixin):
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
        ttk.Button(cab, text="  \U0001F52C Observacion de campo  ", style="Ghost.TButton",
                   command=self._observacion_campo).pack(side="right", padx=(0, 4), pady=10)
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

        # cuadro aparte con la interpretacion de la heterogeneidad (zonas), debajo
        # de la grafica de evolucion de los indices
        het = tk.Frame(cuerpo, bg=TEMA["page"])
        het.pack(fill="x", pady=(14, 0))
        self._build_hetero(het)

        # validacion contra las observaciones de campo (verdad-terreno). Sin altura
        # fija: crece con lo que haya. Solo con el modulo opcional `validacion`.
        if _VAL is not None:
            val = tk.Frame(cuerpo, bg=TEMA["page"])
            val.pack(fill="x", pady=(14, 0))
            self._build_validacion(val)

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

    def _build_hetero(self, parent):
        """Cuadro de interpretacion de la HETEROGENEIDAD (zonas dentro de la parcela):
        la lectura clasica (media/dispersion) y, si esta el modulo espacial, el
        analisis por pixel (foco, tamano, persistencia, arbolado). Solo lectura."""
        card = tarjeta(parent)
        card.pack(fill="x")
        self._titulo(card, "Heterogeneidad de la parcela · zonas")
        self.lbl_hetero = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                   font=FUENTES["small"], justify="left", anchor="w",
                                   wraplength=1180)
        self.lbl_hetero.pack(fill="x", padx=12, pady=(0, 12))

    def _pintar_hetero(self, regs):
        """Rellena el cuadro de zonas: lectura agregada + analisis espacial opcional."""
        if not getattr(self, "lbl_hetero", None) or not self.lbl_hetero.winfo_exists():
            return
        partes = []
        # lectura clasica de la heterogeneidad (media, dispersion, evolucion)
        try:
            h = CI.heterogeneidad(regs or [])
            if h and h.get("lectura"):
                partes.append(h["lectura"])
            elif h and h.get("uniformidad"):
                partes.append(f"Uniformidad de la parcela: {h['uniformidad']}.")
        except Exception:
            log.debug("no se pudo calcular la heterogeneidad clasica", exc_info=True)
        # analisis ESPACIAL por pixel (opcional): foco/persistencia/arbolado
        if _HE is not None:
            try:
                arb = bool(getattr(self, "var_arbolado", None) and self.var_arbolado.get())
                res = _HE.analizar_parcela(self.nombre, self.campana, arbolado=arb)
                t = _HE.texto(res)
                if t:
                    partes.append(t)
            except Exception:
                log.debug("no se pudo calcular la heterogeneidad espacial", exc_info=True)
        self.lbl_hetero.config(text="  ".join(partes) if partes else
                               "Sin datos suficientes para el análisis de zonas "
                               "(hacen falta varias pasadas con rejilla de píxeles).")

    def _build_interp(self, parent):
        # `expand=True`: comparte el ancho con la grafica en vez de quedarse en un
        # ancho fijo. Sin esto, en una ventana estrecha la grafica (que si se
        # expandia) empujaba esta tarjeta FUERA de la pantalla y la interpretacion
        # "desaparecia". `pack_propagate(False)` mantiene la ALTURA fija (la del
        # marco con scroll), no el ancho. `width=360` es solo el minimo de arranque.
        card = tarjeta(parent, width=360)
        card.pack(side="right", fill="both", expand=True, padx=(7, 0))
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
        # Arbolado disperso (dehesa/encinas): solo si el modulo espacial esta. Con la
        # casilla marcada, los pixeles de arbol permanente se excluyen del analisis.
        if _HE is not None:
            self.var_arbolado = tk.BooleanVar(value=bool((DB.ficha(self.nombre) or {}).get("arbolado")))
            self.chk_arbolado = ttk.Checkbutton(
                fila_h, text="Arbolado disperso (dehesa/encinas): excluirlo del análisis de zonas",
                variable=self.var_arbolado, command=self._cambiar_arbolado)
            self.chk_arbolado.pack(anchor="w")

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

    def _cambiar_arbolado(self):
        """Guarda si la parcela tiene arbolado disperso y repinta el cuadro de zonas."""
        ficha = DB.ficha(self.nombre) or {}
        ficha["arbolado"] = bool(self.var_arbolado.get())
        DB.guardar_ficha(self.nombre, ficha)
        self._pintar_hetero(getattr(self, "_regs_actual", None) or [])

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
        self._pintar_hetero(regs)
        if _VAL is not None and getattr(self, "lst_val", None):
            self._pintar_validacion()
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
        arbolado = r.get("arbolado", False)
        motivo_reglas = r.get("motivo", "")     # RED DE SEGURIDAD: el diagnóstico por reglas

        def worker():
            # Los MISMOS argumentos con que se resolvio la cabecera:
            # `texto_interpretacion` vuelve a evaluar por dentro, y con otros
            # argumentos el semaforo y el texto de abajo saldrian de dos
            # diagnosticos distintos -y el texto ademas se guarda en la base-.
            exito = False
            try:
                texto, _d = texto_interpretacion(tipo, sub, regs_hasta, actual.get("fecha"),
                                                 eventos_cerca=eventos_cerca, spec=spec,
                                                 aprendizaje=aprendizaje,
                                                 parcela=self.nombre,
                                                 heterogeneidad_activa=hetero_on,
                                                 arbolado=arbolado)
                exito = True
            except Exception:
                # NUNCA dejar al usuario colgado en "Generando…": si la generación
                # falla (red, IA, dato raro), se muestra el diagnóstico por reglas
                # que ya se calculó. No se cachea, para reintentar la próxima vez.
                log.warning("no se pudo generar la interpretacion; se muestra el diagnostico "
                            "por reglas", exc_info=True)
                texto = motivo_reglas or ("No se pudo generar la interpretación en este momento; "
                                          "vuelve a abrir la parcela para reintentarlo.")
            if exito:
                DB.set_interpretacion(self.nombre, self.campana, actual.get("fecha"), texto)

            def pintar():
                if not self.txt.winfo_exists():   # el usuario ya navego a otra vista
                    return
                self.txt.delete("1.0", tk.END)
                self.txt.insert(tk.END, encabezado + texto)
            try:
                self.master.after(0, pintar)
            except Exception:
                pass          # la ventana ya no existe: nada que pintar
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
