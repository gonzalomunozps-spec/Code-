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
import re
import calendar as _cal
import threading
from datetime import datetime

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

import matplotlib
matplotlib.use("TkAgg")
import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.colors as mcolors
import matplotlib.dates as mdates

# La interpretacion (y la llamada opcional a ChatGPT) viven en
# interpretacion_fenologica; el panel no habla con OpenAI directamente.

# Modulo de interpretacion fenologica + deteccion de cubierta vegetal (IA)
from interpretacion_fenologica import (evaluar_parcela, texto_interpretacion,
                                       ajuste_por_validaciones, observaciones_del_agricultor,
                                       ambito_parcela)
import registro_parcela as REG
import fenologia_especies as FEN
import credenciales as CRED
import almacen as DB          # capa de datos (SQLite): parcelas, historico y eventos
import sentinel1 as S1        # radar (Sentinel-1): complemento bajo demanda al optico
import contraste_indices as CI  # estadistica espacial por pasada (solo lectura)
import rutas                    # directorio de datos del usuario (no el de trabajo)
# Descarga de satelite, cache de imagenes y ritmo de sincronizacion: fuera del panel
import gee_cliente
_EE = gee_cliente.hay_ee()      # el panel ya no importa `ee`: se lo pregunta al cliente
from gee_cliente import (INDICES, INDICES_ORDEN, RADAR_VIS,
                         descargar_mapa_indice, descargar_mapa_radar,
                         sincronizar_parcela)
from mapas_cache import DIR_MAPAS, nombre_seguro, ruta_cache_mapa, ruta_cache_radar
import mapas_cache
import sincronizacion
from sincronizacion import INTERVALO_AUTOSYNC_MS, ULTIMO_SYNC
from bitacora import log      # registro de incidencias (nunca escribe en consola)
# utilidades puras de fecha (dd-mm-aaaa <-> ISO, mascara y validacion al vuelo)
from fechas import (iso_a_ddmmaaaa, ddmmaaaa_a_iso, enmascarar_fecha,
                    filtrar_fecha_digitos)
from geo import superficie_ha    # area de la parcela (shoelace), logica compartida
from campanas import (campana_actual, campanas_de_parcela, PRIMERA_CAMPANA_S2,
                      PRIMERA_CAMPANA_S2_GLOBAL)      # logica de campana
from sigpac import sigpac_consultar, _sigpac_get, SigpacError         # consulta de recintos SIGPAC
from cultivo import spec_de, clave_cultivo                            # modelo de cultivo (puro)

# Modulo OPCIONAL y desacoplado: informe anual en PDF. Si se borra el fichero
# informe_anual.py, esto queda en None y el boton no aparece (ver su cabecera).
try:
    import informe_anual as _INFORME
except Exception:
    _INFORME = None

# Modulo OPCIONAL: calibracion de umbrales con las validaciones del usuario. Si se
# borra calibracion_umbrales.py desaparecen el selector de pasada y la validacion
# por indice, y el diagnostico vuelve a los valores de la tabla. Nada mas.
try:
    import calibracion_umbrales as _CALIB
except Exception:
    _CALIB = None

# Margen interior por defecto de la rejilla de pixeles. Mismo valor que
# gee_cliente.BUFFER_INTERIOR_M; se repite aqui para no importar ese modulo (que
# arrastra `ee`) solo por un numero que hay que ensenar en un formulario.
BUFFER_POR_DEFECTO = 15.0


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
        pass    # silencio deliberado: si no hay tema "clam", vale el que traiga el sistema

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


def centrar_sobre(win, parent):
    """Fija la ventana `win` centrada sobre la ventana principal (parent)."""
    try:
        win.update_idletasks()
        top = parent.winfo_toplevel()
        pw, ph = top.winfo_width(), top.winfo_height()
        w, h = win.winfo_width(), win.winfo_height()
        x = top.winfo_rootx() + max(0, (pw - w) // 2)
        y = top.winfo_rooty() + max(0, (ph - h) // 2)
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass    # silencio deliberado: centrar es cosmetico; si falla, el gestor la coloca


def marco_scroll(parent, bg=None, rueda_global=False):
    """Crea un contenedor con scroll vertical y devuelve (contenedor, interior).

    El contenido se mete en `interior`. La barra lateral siempre funciona.
    `rueda_global=True` captura la rueda sobre TODO el marco mientras el puntero
    esta dentro (ideal para formularios de solo campos). Con `False` la rueda se
    enlaza solo al lienzo, para no chocar con hijos que ya usan la rueda (el mapa
    de la ficha hace zoom con la rueda)."""
    bg = bg or TEMA["page"]
    cont = tk.Frame(parent, bg=bg)
    canvas = tk.Canvas(cont, bg=bg, highlightthickness=0, bd=0)
    sb = ttk.Scrollbar(cont, orient="vertical", command=canvas.yview)
    interior = tk.Frame(canvas, bg=bg)
    ventana = canvas.create_window((0, 0), window=interior, anchor="nw")
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    def _region(_=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
    interior.bind("<Configure>", _region)
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(ventana, width=e.width))

    def _rueda(e):
        caja = canvas.bbox("all")
        if caja and canvas.winfo_height() >= caja[3]:
            return                                   # todo cabe: no hace falta scroll
        paso = -1 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else 1
        canvas.yview_scroll(paso, "units")

    interior.rueda = _rueda          # se expone para enlazar la rueda a mas hijos
    if rueda_global:
        # bind_all mientras el puntero esta dentro; se retira al salir para no
        # interferir con otras zonas scrolleables de la aplicacion.
        def _entrar(_=None):
            canvas.bind_all("<MouseWheel>", _rueda)
            canvas.bind_all("<Button-4>", _rueda)
            canvas.bind_all("<Button-5>", _rueda)
        def _salir(_=None):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")
        cont.bind("<Enter>", _entrar)
        cont.bind("<Leave>", _salir)
        cont.bind("<Destroy>", _salir)
    else:
        for w in (canvas, interior):
            w.bind("<MouseWheel>", _rueda)           # Windows / macOS
            w.bind("<Button-4>", _rueda)             # Linux
            w.bind("<Button-5>", _rueda)
    return cont, interior


# Widgets que gestionan la rueda por su cuenta (no se les enlaza el scroll del
# marco para no pisar su comportamiento): mapa/grafica (Canvas), tablas (Treeview),
# texto e desplegables.
_RUEDA_SALTAR = {"Canvas", "Treeview", "Text", "TCombobox", "Combobox",
                 "Listbox", "Scrollbar", "TScrollbar"}


def enlazar_rueda(widget, handler):
    """Enlaza la rueda del raton a `widget` y a sus hijos 'seguros', para que el
    scroll del marco funcione sobre casi toda la superficie (marcos, etiquetas,
    botones) sin interferir con el zoom del mapa ni el scroll de las tablas."""
    try:
        if widget.winfo_class() not in _RUEDA_SALTAR:
            widget.bind("<MouseWheel>", handler, add="+")
            widget.bind("<Button-4>", handler, add="+")
            widget.bind("<Button-5>", handler, add="+")
    except Exception:
        pass    # silencio deliberado: hay widgets que no aceptan estos eventos de rueda
    try:
        hijos = widget.winfo_children()
    except Exception:
        hijos = []
    for ch in hijos:
        enlazar_rueda(ch, handler)


class LienzoMapa:
    """Canvas que muestra un PNG con ZOOM (rueda / botones) y DESPLAZAMIENTO
    (arrastrar con el raton) para recorrer las distintas zonas de la parcela.
    Lo usan tanto la ficha como la ventana de comparacion."""
    def __init__(self, parent, bg="#d7ddd9", on_info=None):
        self.canvas = tk.Canvas(parent, bg=bg, highlightthickness=0)
        self.on_info = on_info                 # callback(texto) para el estado (zoom/resolucion)
        self.png = None
        self.info = ""
        self.img_tk = None
        self.zoom = None                       # None = ajustar al lienzo
        self.offset = [0, 0]                   # desplazamiento (px) respecto al centro
        self._drag = None
        self._im = None                        # imagen PIL cacheada (no reabrir en cada arrastre)
        self._im_path = None
        self._escalada = None                  # (png, ancho, alto) de la imagen YA escalada
        self._item = None                      # id del item del canvas, para moverlo al arrastrar
        c = self.canvas
        c.bind("<Configure>", lambda e: self.redibujar())
        c.bind("<MouseWheel>", lambda e: self.zoom_rel(1.25 if e.delta > 0 else 1 / 1.25))
        c.bind("<Button-4>", lambda e: self.zoom_rel(1.25))
        c.bind("<Button-5>", lambda e: self.zoom_rel(1 / 1.25))
        c.bind("<ButtonPress-1>", self._pan_ini)
        c.bind("<B1-Motion>", self._pan_mov)
        c.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        c.bind("<Double-Button-1>", lambda e: self.ajustar())

    def pack(self, **kw):
        self.canvas.pack(**kw)

    def set_png(self, png, info=""):
        """Cambia la imagen conservando el zoom/desplazamiento (util para comparar
        la MISMA zona entre dias o indices)."""
        self.png = png
        self.info = info
        self.redibujar()

    def mensaje(self, texto, color=None):
        # Puede llegar desde un after() cuando el usuario ya cerro la ventana (las
        # descargas de GEE tardan segundos): si el canvas ya no existe, no hay nada
        # que pintar. Sin esta guarda, Tk lanzaria 'invalid command name'.
        # (redibujar() ya hace esta misma comprobacion, por eso set_png esta cubierto.)
        if not self.canvas.winfo_exists():
            return
        self.canvas.delete("all")          # esto destruye tambien la imagen cacheada...
        self._item = None                  # ...asi que se invalida su id y su escala
        self._escalada = None
        self.canvas.create_text(20, 20, anchor="nw", fill=color or TEMA["text_muted"], text=texto)

    def ajustar(self):
        self.zoom = None
        self.offset = [0, 0]
        self.redibujar()

    def zoom_rel(self, factor):
        base = self.zoom if self.zoom else 1.0
        self.zoom = max(0.2, min(8.0, base * factor))
        self.redibujar()

    def _pan_ini(self, e):
        self._drag = (e.x, e.y, self.offset[0], self.offset[1])

    def _pan_mov(self, e):
        if not self._drag:
            return
        x0, y0, ox, oy = self._drag
        self.offset = [ox + (e.x - x0), oy + (e.y - y0)]
        self.redibujar()

    def redibujar(self):
        c = self.canvas
        if not (c.winfo_exists() and self.png and os.path.exists(self.png) and _PIL):
            return
        if self._im_path != self.png:          # abrir del disco solo al cambiar de imagen
            try:
                self._im = Image.open(self.png).convert("RGBA")
            except Exception:
                return
            self._im_path = self.png
            self._escalada = None              # imagen distinta: hay que reescalar
        base = self._im
        ow, oh = base.size
        cw = max(c.winfo_width(), 50)
        ch = max(c.winfo_height(), 50)
        escala = min(cw / ow, ch / oh)         # ajuste base al lienzo
        if self.zoom is None:
            self.offset = [0, 0]
        else:
            escala *= self.zoom
        nw, nh = max(1, int(ow * escala)), max(1, int(oh * escala))
        x, y = cw // 2 + self.offset[0], ch // 2 + self.offset[1]

        # AL ARRASTRAR solo cambia la POSICION: si la imagen escalada es la misma
        # (mismo PNG, mismo zoom y mismo tamano de lienzo), basta con mover el item.
        # Reescalar en cada movimiento del raton costaba decenas de ms por evento y
        # era lo que hacia que el arrastre fuera a tirones.
        if self._escalada == (self._im_path, nw, nh) and self._item is not None:
            c.coords(self._item, x, y)
        else:
            im = base.resize((nw, nh), Image.NEAREST if escala > 1 else Image.LANCZOS)
            self.img_tk = ImageTk.PhotoImage(im)
            c.delete("all")
            self._item = c.create_image(x, y, image=self.img_tk)
            self._escalada = (self._im_path, nw, nh)
        c.config(scrollregion=c.bbox("all"))
        if self.on_info:
            z = "ajuste" if self.zoom is None else f"{self.zoom:.2f}x"
            self.on_info((f"{self.info}  ·  " if self.info else "") + f"zoom {z}  ·  arrastra para mover")


# Las utilidades de fecha (iso_a_ddmmaaaa, ddmmaaaa_a_iso, enmascarar_fecha,
# filtrar_fecha_digitos) viven ahora en fechas.py y se importan arriba.


class PopupCalendario(tk.Toplevel):
    """Mini calendario. Al elegir un dia llama on_pick(iso) con la fecha ISO."""
    MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

    def __init__(self, parent, on_pick, iso_ini=None, anchor=None):
        super().__init__(parent)
        self.on_pick = on_pick
        self.title("Elegir fecha")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.lift()
        self.after(40, self.focus_force)
        try:
            base = datetime.strptime(iso_ini, "%Y-%m-%d")
        except (ValueError, TypeError):
            base = datetime.now()
        self.anio, self.mes = base.year, base.month
        self._grid = None
        self._build()
        anchor = anchor or parent
        try:
            self.update_idletasks()
            self.geometry(f"+{anchor.winfo_rootx()}+{anchor.winfo_rooty() + anchor.winfo_height() + 2}")
        except Exception:
            pass    # silencio deliberado: posicionar el calendario es cosmetico
        self.after(60, self._grab)

    def _grab(self):
        try:
            self.grab_set()
        except Exception:
            pass    # silencio deliberado: otro modal puede tener el grab; no es un error

    def _build(self):
        cab = tk.Frame(self, bg=TEMA["surface"])
        cab.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Button(cab, text="◀", width=3, command=lambda: self._mover(-1)).pack(side="left")
        tk.Label(cab, text=f"{self.MESES[self.mes - 1]} {self.anio}", bg=TEMA["surface"],
                 fg=TEMA["text"], font=FUENTES["small"], width=16).pack(side="left", expand=True)
        ttk.Button(cab, text="▶", width=3, command=lambda: self._mover(1)).pack(side="left")

        if self._grid:
            self._grid.destroy()
        self._grid = tk.Frame(self, bg=TEMA["surface"])
        self._grid.pack(padx=6, pady=(2, 6))
        for i, d in enumerate(["L", "M", "X", "J", "V", "S", "D"]):
            tk.Label(self._grid, text=d, bg=TEMA["surface"], fg=TEMA["text_muted"], width=3,
                     font=FUENTES["small"]).grid(row=0, column=i)
        cal = _cal.Calendar(firstweekday=0)     # lunes primero
        for r, semana in enumerate(cal.monthdayscalendar(self.anio, self.mes), start=1):
            for cix, dia in enumerate(semana):
                if dia == 0:
                    continue
                ttk.Button(self._grid, text=str(dia), width=3,
                           command=lambda d=dia: self._elegir(d)).grid(row=r, column=cix, padx=1, pady=1)

    def _mover(self, delta):
        self.mes += delta
        if self.mes < 1:
            self.mes, self.anio = 12, self.anio - 1
        elif self.mes > 12:
            self.mes, self.anio = 1, self.anio + 1
        for w in self.winfo_children():
            w.destroy()
        self._grid = None
        self._build()

    def _elegir(self, dia):
        self.on_pick(f"{self.anio:04d}-{self.mes:02d}-{dia:02d}")
        self.destroy()


class CampoFecha(tk.Frame):
    """Campo de fecha reutilizable: entrada con mascara dd-mm-aaaa (los guiones
    salen solos al teclear) + boton de calendario. El programa trabaja en ISO:
    usa get_iso() / set_iso()."""
    PH = "dd-mm-aaaa"

    def __init__(self, parent, iso=None, width=11, **kw):
        super().__init__(parent, bg=TEMA["surface"], **kw)
        self.var = tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self.var, width=width, justify="center",
                              bd=1, relief="solid", bg="#ffffff", fg=TEMA["text"],
                              insertbackground=TEMA["text"], highlightthickness=0)
        self.entry.pack(side="left", ipady=1)
        ttk.Button(self, text="📅", width=3, command=self._abrir_cal).pack(side="left", padx=(2, 0))
        self.entry.bind("<KeyRelease>", self._al_teclear)
        self.entry.bind("<FocusIn>", self._foco_in)
        self.entry.bind("<FocusOut>", self._foco_out)
        if iso:
            self.set_iso(iso)
        else:
            self._poner_ph()

    def _poner_ph(self):
        self.var.set(self.PH)
        self.entry.config(fg=TEMA["text_muted"])

    def _es_ph(self):
        return self.var.get() == self.PH

    def _foco_in(self, _=None):
        if self._es_ph():
            self.var.set("")
            self.entry.config(fg=TEMA["text"])

    def _foco_out(self, _=None):
        if not re.sub(r"\D", "", self.var.get()):
            self._poner_ph()

    def _al_teclear(self, event=None):
        if event and event.keysym in ("Tab", "Left", "Right", "Up", "Down"):
            return
        self.entry.config(fg=TEMA["text"])
        digs = filtrar_fecha_digitos(self.var.get())   # rechaza dia>31 / mes>12 al vuelo
        self.var.set(enmascarar_fecha(digs))
        self.entry.icursor(tk.END)

    def _abrir_cal(self):
        PopupCalendario(self, self._desde_cal, iso_ini=self.get_iso(), anchor=self.entry)

    def _desde_cal(self, iso):
        self.set_iso(iso)

    def get_iso(self):
        """Fecha en ISO (aaaa-mm-dd) o '' si esta vacia/incompleta/invalida."""
        return "" if self._es_ph() else ddmmaaaa_a_iso(self.var.get())

    def set_iso(self, iso):
        txt = iso_a_ddmmaaaa(iso)
        if txt:
            self.var.set(txt)
            self.entry.config(fg=TEMA["text"])
        else:
            self._poner_ph()

    def esta_vacio(self):
        return self._es_ph() or not re.sub(r"\D", "", self.var.get())


# Constantes de presentacion (se definen UNA vez, no en cada llamada/redibujado).
_FMT_DIAS = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")
_FMT_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
# color y etiqueta de cada tipo de evento del cuaderno para las lineas de la grafica
_ICONOS_EVENTO = {"PRODUCTO": ("#c05621", "Producto"), "SIEGA": ("#2b6cb0", "Siega"),
                  "COSECHA": ("#b7791f", "Cosecha"), "RIEGO": ("#3182ce", "Riego"),
                  "LABOREO": ("#718096", "Laboreo"), "SIEMBRA": ("#276749", "Siembra"),
                  "OTRO": ("#718096", "Evento")}


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


def _copa_de(entry):
    """Diametro de copa tecleado, en metros, o None si esta vacio o no vale.

    Es OPCIONAL a proposito: sin el, la fraccion de copa se estima del marco y todo
    se comporta como antes de que existiera el campo. Un 0 o un negativo cuentan
    como "no lo se", no como "copa de cero metros"."""
    try:
        v = float((entry.get() or "").strip().replace(",", "."))
    except (ValueError, AttributeError, TypeError):
        return None
    return v if v > 0 else None


def _colores_estado(clave):
    return {"OK": (TEMA["ok_fg"], TEMA["ok_bg"]),
            "Vigilar": (TEMA["warn_fg"], TEMA["warn_bg"]),
            "Revisar": (TEMA["danger_fg"], TEMA["danger_bg"])}.get(
        clave, (TEMA["muted_fg"], TEMA["muted_bg"]))


# =====================================================================
# PERSISTENCIA
# =====================================================================
# Los DATOS (parcelas, historico y eventos) viven en SQLite via el modulo
# `almacen` (DB). Aqui solo queda como JSON la marca del ultimo sync, que es
# estado, no datos.
# ARCHIVO_ESTADO vive en sincronizacion; DIR_MAPAS en mapas_cache.


# =====================================================================
# INDICES (definicion, rangos y paletas)
# =====================================================================
# Las paletas, INDICES e INDICES_ORDEN viven en gee_cliente (los usa la descarga
# y los reutiliza la leyenda de la interfaz).

COLOR_INDICE = {"NDVI": "#2f855a", "EVI": "#805ad5", "SAVI": "#dd6b20", "GNDVI": "#0ea5e9",
                "LAI": "#d69e2e", "MSAVI": "#e53e3e", "NDMI": "#3182ce", "RVI": "#0d9488"}
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
# HELPERS GEOMETRIA / GEE
# =====================================================================
# campana_actual, rango_campana y campanas_entre viven ahora en campanas.py
# (se importan arriba). superficie_ha vive en geo.py.


# clave_cultivo vive ahora en cultivo.py (se importa arriba).


# nombre_seguro vive en mapas_cache.


# ---------------------------------------------------------------------------
# SIGPAC: parseo robusto de la respuesta GeoJSON
# ---------------------------------------------------------------------------
# El bloque SIGPAC (parseo de geometria + consulta con endpoints de reserva)
# vive ahora en sigpac.py; el panel importa sigpac_consultar, _sigpac_get y
# SigpacError arriba.


# spec_de vive ahora en cultivo.py (se importa arriba).


# construir_indice vive ahora en gee_cliente.


# La sesion HTTP, construir_indice, los mapas (indice y radar), RADAR_VIS y
# ruta_cache_* viven ahora en gee_cliente y mapas_cache.


# La persistencia atomica, la marca de sync, toca_sincronizar, ULTIMO_SYNC y
# sincronizar_parcela viven ahora en sincronizacion y gee_cliente.


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

        # limpieza de PNG viejos de la cache, en un hilo aparte para NO retrasar
        # la apertura de la ventana (borra imagenes, nunca datos)
        threading.Thread(target=self._purgar_cache, daemon=True).start()

        # Relevo de campana (1 de septiembre) + import automatico periodico
        self.after(400, self._comprobar_relevo_campana)
        self.after(1500, self._auto_sync)

    # ---------------------------------------------------------- relevo de campana
    def _comprobar_relevo_campana(self):
        """Al entrar en una campana nueva, pide el cultivo de las parcelas ya existentes
        que aun no lo tengan asignado para la campana activa."""
        parcelas = DB.parcelas_dict()
        pendientes = [n for n, f in parcelas.items()
                      if self.campana not in f.get("cultivos_por_campana", {})]
        if parcelas and pendientes:
            DialogoRelevoCampana(self, pendientes)

    def asignar_cultivo(self, nombre, tipo, spec):
        if DB.existe(nombre):
            spec = dict(spec or {})
            subtipo = ""
            if tipo == "LENOSO" and spec.get("marco_calle"):
                dens = FEN.densidad_arboles(spec["marco_calle"], spec["marco_pie"])
                subtipo = FEN.subtipo_canonico(spec.get("especie", "OLIVO"), dens)
            elif tipo == "EXTENSIVO":
                subtipo = spec.get("finalidad") if spec.get("finalidad") in ("SIEGA_VERDE", "COSECHA_GRANO") else "COSECHA_GRANO"
            cultivo = {"tipo": tipo, "subtipo": subtipo}
            cultivo.update(spec)
            DB.set_cultivo(nombre, self.campana, cultivo)
        self._refrescar()

    # ---------------------------------------------------------- import automatico
    def _purgar_cache(self):
        """Borra los PNG de mapas mas viejos que mapas_cache.DIAS_CACHE.

        Corre en un hilo aparte para no retrasar la apertura de la ventana, y no
        toca la interfaz. Solo borra imagenes, que se vuelven a descargar solas
        cuando se piden; los datos no se tocan (ver rutas.purgar_png_antiguos).
        """
        try:
            n = rutas.purgar_png_antiguos(DIR_MAPAS, mapas_cache.DIAS_CACHE)
            if n:
                log.warning("cache de mapas: %s PNG con mas de %s dias borrados",
                            n, mapas_cache.DIAS_CACHE)
        except Exception:
            log.warning("no se pudo purgar la cache de mapas", exc_info=True)

    def _auto_sync(self):
        """Se ejecuta al ARRANCAR y luego de forma periodica. Solo sincroniza si
        toca (nunca se sincronizo o ya paso el intervalo desde el ultimo sync);
        asi, abrir la app varias veces el mismo dia no repite, pero si han pasado
        los dias configurados, al iniciarse se pone al dia sola."""
        if _EE and sincronizacion.toca_sincronizar(sincronizacion.marca_leer(), INTERVALO_AUTOSYNC_MS):
            threading.Thread(target=self._sync_todas, daemon=True).start()
        self.after(INTERVALO_AUTOSYNC_MS, self._auto_sync)

    def _sync_todas(self):
        total = 0
        for nombre in DB.nombres():
            n, _ = sincronizar_parcela(nombre, self.campana, silencioso=True)
            total += n
        if ULTIMO_SYNC.get("estado") != "fallo":     # solo marca la hora si conecto
            sincronizacion.marca_guardar()
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
        if not hasattr(self, "lbl_sync") or not self.lbl_sync.winfo_exists():
            return          # la ventana se cerro mientras el hilo sincronizaba
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
        for nombre in DB.nombres():
            n, _ = sincronizar_parcela(nombre, self.campana, silencioso=True)
            total += n
            n_par += 1
        if ULTIMO_SYNC.get("estado") != "fallo":
            sincronizacion.marca_guardar()

        def fin():
            if not self.btn_sync.winfo_exists():
                return      # se cerro el programa mientras sincronizaba todo
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
        # solo la actual + las campanas con datos de satelite (las vacias no se muestran)
        c = {campana_actual()}
        c |= DB.campanas_con_datos()
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
        if not hasattr(self, "tree") or not self.tree.winfo_exists():
            return          # la ventana se cerro mientras el hilo sincronizaba
        self.tree.delete(*self.tree.get_children())   # vaciado en UNA llamada a Tk
        texto = self.entry_buscar.get().lower() if hasattr(self, "entry_buscar") else ""
        orden = self.cb_orden.get() if hasattr(self, "cb_orden") else "nombre"
        parcelas = DB.parcelas_dict()
        historico = DB.pasadas_de_campana(self.campana)   # {nombre: [pasadas]} en una consulta

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
                serie = sorted(historico.get(nombre, []),
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

        sev = {"Revisar": 0, "Vigilar": 1, "OK": 2, "Segado": 2, "Sin dato": 3, "N.A.": 4, "Sin asignar": 5}
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
        DB.eliminar_parcela(nombre)   # borra en cascada: parcela + cultivos + pasadas + eventos
        self._refrescar()

    def abrir_alta_parcela(self):
        VentanaAltaParcela(self)

    def guardar_parcela(self, nombre, propietario, tipo, spec, coords, campana=None,
                        sigpac=None, buffer_m=None):
        camp = campana or self.campana
        cerrado = coords + [coords[0]] if coords and coords[0] != coords[-1] else coords
        ficha = DB.ficha(nombre) or {}
        ficha.update({"propietario": propietario, "coordenadas": cerrado,
                      "superficie_ha": superficie_ha(cerrado),
                      "anio_inicio_monitoreo": ficha.get("anio_inicio_monitoreo", camp)})
        # DONDE esta la parcela. Antes los 7 codigos SIGPAC se tecleaban, servian
        # para bajar el recinto y se tiraban. Se guardan porque provincia y
        # municipio son la unidad en la que se corrige un umbral para una comarca.
        if sigpac and sigpac.get("Prov") and sigpac.get("Mun"):
            ficha["provincia"] = str(sigpac["Prov"]).strip()
            ficha["municipio"] = f"{str(sigpac['Prov']).strip()}/{str(sigpac['Mun']).strip()}"
            ficha["sigpac"] = {k: str(v).strip() for k, v in sigpac.items() if str(v).strip()}
        if buffer_m is not None:
            ficha["buffer_m"] = float(buffer_m)
        # subtipo derivado (compatibilidad y visualizacion):
        #   leñoso -> tipo de plantacion segun el marco; cereal -> COSECHA_GRANO
        spec = dict(spec or {})
        subtipo = ""
        if tipo == "LENOSO" and spec.get("marco_calle"):
            dens = FEN.densidad_arboles(spec["marco_calle"], spec["marco_pie"])
            subtipo = FEN.subtipo_canonico(spec.get("especie", "OLIVO"), dens)
        elif tipo == "EXTENSIVO":
            subtipo = spec.get("finalidad") if spec.get("finalidad") in ("SIEGA_VERDE", "COSECHA_GRANO") else "COSECHA_GRANO"
        cultivo = {"tipo": tipo, "subtipo": subtipo}
        cultivo.update(spec)          # especie, fecha_siembra, marco_calle, marco_pie, finalidad
        ficha.setdefault("cultivos_por_campana", {})[camp] = cultivo
        DB.guardar_ficha(nombre, ficha)
        self.cb_campana["values"] = self._campanas()
        self._refrescar()

    def editar_parcela(self, nombre, campana):
        """Abre la ventana de alta en modo edicion (prellena la parcela)."""
        VentanaAltaParcela(self, editar=nombre, campana=campana)

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
        return DB.pasadas(nombre, self.campana)

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
    def __init__(self, panel, editar=None, campana=None):
        super().__init__(panel)
        self.panel = panel
        self.editar = editar                       # nombre de la parcela a editar (o None = alta)
        self.campana_edit = campana or panel.campana
        self.title("Editar parcela" if editar else "Nueva parcela")
        self.geometry("1000x600")
        self.configure(bg=TEMA["page"])
        self.coords = []
        self.poligono = None
        # que la ventana se mantenga SIEMPRE por encima de la principal (no se
        # cuele detras al aparecer un aviso de error).
        self.transient(panel.winfo_toplevel())
        self.lift()
        self.after(80, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))

        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        _tit = f"Editar parcela · {editar.replace('_', ' ')}" if editar else "Nueva parcela"
        tk.Label(cab, text=_tit, bg=TEMA["header_bg"], fg="#fff",
                 font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=10)

        cuerpo = tk.Frame(self, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=14, pady=14)

        form_card = tarjeta(cuerpo, width=360)
        form_card.pack(side="left", fill="y")
        form_card.pack_propagate(False)
        cont_form, form = marco_scroll(form_card, bg=TEMA["surface"], rueda_global=True)
        cont_form.pack(fill="both", expand=True)
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

        # BUFFER INTERIOR de la rejilla de pixeles. 15 m por defecto: un pixel de
        # Sentinel-2 mas margen de geolocalizacion, que es lo que hace falta para
        # que un pixel este fiablemente dentro Y siga estandolo en la pasada
        # siguiente. Se puede subir (camino ancho, lindero con arbolado) o bajar
        # (parcela pequena y limpia), incluso a 0.
        etiqueta(f"Margen interior de la parcela (m) — por defecto {BUFFER_POR_DEFECTO:.0f}")
        self.e_buffer = ttk.Entry(form, width=10)
        self.e_buffer.pack(anchor="w", **pad)
        tk.Label(form, text="Descarta los pixeles del borde, mezclados con lindero o camino.\n"
                            "Subirlo limpia mas; bajarlo conserva mas superficie. 0 = sin margen.",
                 bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"],
                 justify="left").pack(anchor="w", pady=(0, 6), **pad)

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
        # finalidad (solo extensivos): grano vs siega en verde
        self.lbl_finalidad = tk.Label(self.frame_spec, text="Finalidad del cultivo",
                                      bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.cb_finalidad = ttk.Combobox(self.frame_spec, state="readonly",
                                         values=["Cosecha de grano", "Siega en verde (forraje)"])
        self.cb_finalidad.set("Cosecha de grano")
        # siembra
        self.lbl_siembra = tk.Label(self.frame_spec, text="Fecha de siembra",
                                    bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.e_siembra = CampoFecha(self.frame_spec)
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
        # DIAMETRO DE COPA: opcional, pero es el dato que de verdad fija cuanto
        # suelo tapa el arbol, y de ahi salen los umbrales en escala de parcela.
        # Sin el se estima del marco, que no distingue un olivar viejo de uno joven
        # plantado igual. Vacio = como hasta ahora.
        tk.Label(self.marco_wrap, text="  copa", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left")
        self.e_copa = ttk.Entry(self.marco_wrap, width=5)
        self.e_copa.pack(side="left", padx=(4, 0))
        tk.Label(self.marco_wrap, text="m", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left", padx=(2, 0))
        # etiqueta que muestra el tipo deducido del marco
        # REGIMEN HIDRICO: en lenosos pesa mas que la especie. Un olivar de secano
        # en julio esta en deficit por diseno; el mismo dato en un seto regado
        # significa que ha fallado el riego.
        self.lbl_regimen = tk.Label(self.frame_spec, text="Regimen hidrico",
                                    bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.cb_regimen = ttk.Combobox(self.frame_spec, state="readonly", width=14,
                                       values=["Secano", "Regadio"])
        self.cb_regimen.set("Secano")
        self.lbl_tipo_calc = tk.Label(self.frame_spec, text="", bg=TEMA["surface"],
                                      fg=TEMA["ok_fg"], font=FUENTES["small"])
        self.e_calle.bind("<KeyRelease>", lambda e: self._calc_marco())
        self.e_pie.bind("<KeyRelease>", lambda e: self._calc_marco())
        self.e_copa.bind("<KeyRelease>", lambda e: self._calc_marco())

        box = tarjeta(form)
        box.pack(fill="x", padx=16, pady=12)
        tk.Label(box, text="Geometria por SIGPAC  (Agr y Zona: 0 si no aplica)",
                 bg=TEMA["surface"], fg=TEMA["text"],
                 font=FUENTES["small"]).grid(row=0, column=0, columnspan=6, sticky="w",
                                             padx=8, pady=(8, 4))
        self.sig = {}
        campos = ["Prov", "Mun", "Agr", "Zona", "Pol", "Par", "Rec"]
        for i, kk in enumerate(campos):
            tk.Label(box, text=kk, bg=TEMA["surface"], fg=TEMA["text_muted"],
                     font=FUENTES["small"]).grid(row=1 + i // 3, column=(i % 3) * 2,
                                                 sticky="w", padx=(8, 2))
            e = ttk.Entry(box, width=6)
            e.grid(row=1 + i // 3, column=(i % 3) * 2 + 1, padx=2, pady=2)
            if kk in ("Agr", "Zona"):
                e.insert(0, "0")
            self.sig[kk] = e
        fila_btn = 1 + (len(campos) + 2) // 3
        ttk.Button(box, text="Capturar recinto SIGPAC", command=self._sigpac).grid(
            row=fila_btn, column=0, columnspan=6, sticky="ew", padx=8, pady=(6, 8))

        tk.Label(form, text="...o dibuja los bordes en el mapa (clic izquierdo).",
                 bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"]).pack(anchor="w", **pad)
        botones = tk.Frame(form, bg=TEMA["surface"])
        botones.pack(fill="x", padx=16, pady=(4, 0))
        ttk.Button(botones, text="Deshacer punto", command=self._deshacer).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(botones, text="Limpiar", command=self._limpiar).pack(side="left", expand=True, fill="x")
        ttk.Button(form, text="Guardar cambios" if editar else "Guardar parcela",
                   style="Accent.TButton",
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

        if editar:
            self.after(120, self._prellenar)

    def _prellenar(self):
        """Carga en el formulario los datos de la parcela a editar."""
        ficha = DB.ficha(self.editar) or {}
        self.e_nombre.insert(0, self.editar.replace("_", " "))
        self.e_nombre.config(state="readonly")     # el nombre identifica la parcela: no se cambia aqui
        self.e_prop.insert(0, ficha.get("propietario", ""))
        # codigos SIGPAC guardados: se reponen para no tener que teclearlos otra vez
        # (y para que editar sin tocarlos no borre la provincia y el municipio)
        for k, v in (ficha.get("sigpac") or {}).items():
            if k in self.sig and not self.sig[k].get():
                self.sig[k].insert(0, str(v))
        if ficha.get("buffer_m") is not None:
            self.e_buffer.insert(0, f"{float(ficha['buffer_m']):g}")
        cult = (ficha.get("cultivos_por_campana", {}) or {}).get(self.campana_edit, {})
        tipo = cult.get("tipo", "")
        if tipo:
            self.cb_tipo.set(tipo)
            self._sub()                            # rellena especies y muestra los campos del tipo
            if cult.get("especie"):
                self.cb_sub.set(cult["especie"])
            if tipo == "EXTENSIVO":
                self.cb_finalidad.set("Siega en verde (forraje)"
                                      if cult.get("subtipo") == "SIEGA_VERDE" or cult.get("finalidad") == "SIEGA_VERDE"
                                      else "Cosecha de grano")
                if cult.get("fecha_siembra"):
                    self.e_siembra.set_iso(cult["fecha_siembra"])
            elif tipo == "LENOSO":
                if cult.get("marco_calle") is not None:
                    self.e_calle.insert(0, str(cult["marco_calle"]))
                if cult.get("marco_pie") is not None:
                    self.e_pie.insert(0, str(cult["marco_pie"]))
                if cult.get("diametro_copa"):
                    self.e_copa.insert(0, str(cult["diametro_copa"]))
                # regimen guardado; los cultivos anteriores a este campo son SECANO,
                # que es el supuesto que no avisa donde el deficit es normal
                self.cb_regimen.set("Regadio" if cult.get("regimen") == "REGADIO" else "Secano")
                self._calc_marco()
        # geometria: cargar los vertices y dibujarlos (sin el punto de cierre duplicado)
        coords = ficha.get("coordenadas") or []
        if len(coords) >= 2 and coords[0] == coords[-1]:
            coords = coords[:-1]
        self.coords = [list(c) for c in coords]
        if _MAPVIEW and self.coords:
            self._redibujar()
            self.mapa.set_position(self.coords[0][1], self.coords[0][0], zoom=15)

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
                messagebox.showinfo("Localidad", "No se encontro la localidad.", parent=self)
        except Exception as e:
            messagebox.showerror("Localidad", f"Error en la busqueda: {e}", parent=self)

    def _sub(self, _=None):
        grupo = self.cb_tipo.get()
        esp = FEN.ESPECIES.get(grupo, [])
        self.cb_sub["values"] = esp
        self.cb_sub.set(esp[0] if esp else "")
        for w in (self.lbl_finalidad, self.cb_finalidad, self.lbl_siembra, self.e_siembra,
                  self.lbl_marco, self.marco_wrap, self.lbl_regimen, self.cb_regimen,
                  self.lbl_tipo_calc):
            w.pack_forget()
        if grupo == "EXTENSIVO":
            self.lbl_finalidad.pack(anchor="w")
            self.cb_finalidad.pack(fill="x", pady=(0, 4))
            self.lbl_siembra.pack(anchor="w")
            self.e_siembra.pack(fill="x")
        elif grupo == "LENOSO":
            self.lbl_marco.pack(anchor="w")
            self.marco_wrap.pack(anchor="w", pady=(0, 2))
            self.lbl_regimen.pack(anchor="w")
            self.cb_regimen.pack(anchor="w", pady=(0, 2))
            self.lbl_tipo_calc.pack(anchor="w")
            self._calc_marco()

    def _calc_marco(self):
        """Al teclear el marco (o la copa), enseña lo que implica.

        El texto lo redacta `fenologia_especies.texto_marco`, que es donde vive el
        calculo: densidad, tipo de plantacion y que fraccion de suelo tapa la copa,
        que es la que traduce los umbrales a escala de parcela."""
        try:
            c = float(self.e_calle.get().replace(",", "."))
            p = float(self.e_pie.get().replace(",", "."))
            self.lbl_tipo_calc.config(text=FEN.texto_marco(
                self.cb_sub.get() or "OLIVO", c, p, _copa_de(self.e_copa)))
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
        v = {k: e.get().strip() for k, e in self.sig.items()}
        # obligatorios; Agr/Zona valen 0 si se dejan vacios (recintos sin agregado/zona)
        if not all(v.get(k) for k in ("Prov", "Mun", "Pol", "Par", "Rec")):
            return messagebox.showwarning("SIGPAC", "Rellena al menos Prov, Mun, Pol, Par y Rec.", parent=self)
        # Un recinto SIGPAC se identifica por 7 codigos: prov/mun/agregado/zona/pol/par/rec.
        try:
            coords = sigpac_consultar(v, _sigpac_get)
        except SigpacError as e:
            return messagebox.showerror("SIGPAC", str(e), parent=self)
        except ValueError as e:            # recinto en UTM y sin pyproj para convertir
            return messagebox.showerror("SIGPAC", str(e), parent=self)
        except Exception as e:
            return messagebox.showerror("SIGPAC", f"No se pudo capturar el recinto: {e}", parent=self)
        self.coords = coords
        if _MAPVIEW:
            self._redibujar()
            self.mapa.set_position(coords[0][1], coords[0][0], zoom=16)
        messagebox.showinfo("SIGPAC", f"Recinto capturado ({len(coords)} vertices).", parent=self)

    def _guardar(self):
        # en edicion el nombre identifica la parcela y no se cambia (campo readonly)
        nombre = self.editar or nombre_seguro(self.e_nombre.get())
        prop = self.e_prop.get().strip()
        tipo, esp = self.cb_tipo.get(), self.cb_sub.get()
        if not nombre or not prop or not tipo:
            return messagebox.showwarning("Datos", "Nombre, propietario y tipo son obligatorios.", parent=self)
        if tipo != "BARBECHO" and not esp:
            return messagebox.showwarning("Datos", "Selecciona la especie.", parent=self)
        if len(self.coords) < 3:
            return messagebox.showwarning("Geometria", "Define al menos 3 vertices (SIGPAC o mapa).", parent=self)

        spec = {"especie": esp}
        if tipo == "EXTENSIVO":
            spec["finalidad"] = ("SIEGA_VERDE" if self.cb_finalidad.get().startswith("Siega")
                                 else "COSECHA_GRANO")
            if not self.e_siembra.esta_vacio():
                siembra = self.e_siembra.get_iso()
                if not siembra:
                    return messagebox.showwarning("Siembra", "Fecha de siembra: dd-mm-aaaa (o dejala vacia).",
                                                  parent=self)
                spec["fecha_siembra"] = siembra
        elif tipo == "LENOSO":
            try:
                spec["marco_calle"] = float(self.e_calle.get().replace(",", "."))
                spec["marco_pie"] = float(self.e_pie.get().replace(",", "."))
            except ValueError:
                return messagebox.showwarning("Marco", "Indica el marco de plantacion (calle y pie en metros).", parent=self)
            # opcional: sin diametro de copa se estima del marco, como siempre
            spec["diametro_copa"] = _copa_de(self.e_copa)
            spec["regimen"] = "REGADIO" if self.cb_regimen.get().startswith("Rega") else "SECANO"

        # los codigos SIGPAC tecleados se guardan con la parcela (provincia y
        # municipio), aunque el recinto se haya dibujado a mano despues
        codigos = {k: e.get().strip() for k, e in self.sig.items()} if hasattr(self, "sig") else None
        # margen interior: vacio = usar el de por defecto (se guarda como None)
        buf = (self.e_buffer.get() or "").strip().replace(",", ".")
        if buf:
            try:
                buf = float(buf)
                if buf < 0:
                    raise ValueError
            except ValueError:
                return messagebox.showwarning(
                    "Margen interior", "El margen interior son metros: un numero de 0 en "
                    "adelante (o dejalo vacio para usar el de por defecto).", parent=self)
        else:
            buf = None
        # Cambiar el margen mueve el rectangulo de la rejilla, asi que las que ya
        # estan guardadas dejan de ser comparables con las nuevas: el pixel (i,j)
        # pasa a ser otro trozo de terreno. No se pierden -se pueden volver a
        # descargar- pero conviene decirlo ANTES, no descubrirlo al comparar.
        if self.editar and buf is not None:
            antes = (DB.ficha(self.editar) or {}).get("buffer_m")
            n_rej = DB.tamano_rejillas(self.editar)[0]
            if n_rej and (antes is None or abs(float(antes) - buf) > 1e-9):
                if not messagebox.askyesno(
                        "Margen interior",
                        f"Esta parcela tiene {n_rej} rejilla(s) de pixeles guardadas con el "
                        f"margen anterior.\n\nAl cambiarlo dejan de ser comparables con las "
                        f"nuevas y habra que volver a descargarlas (Sincronizar).\n\n"
                        f"¿Cambiar el margen de todas formas?", parent=self):
                    return
        self.panel.guardar_parcela(nombre, prop, tipo, spec, self.coords,
                                   campana=self.campana_edit, sigpac=codigos, buffer_m=buf)
        if self.editar:
            messagebox.showinfo("OK", f"Cambios guardados en '{nombre.replace('_', ' ')}'.", parent=self)
            self.destroy()
            self.panel.mostrar_ficha(nombre)       # recarga la ficha con los datos nuevos
        else:
            messagebox.showinfo("OK", f"Parcela '{nombre}' guardada.", parent=self)
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
        self.transient(panel.winfo_toplevel())   # siempre por encima de la principal
        self.grab_set()          # modal
        self.lift()
        self.after(80, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))

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
        self.lbl_finalidad = tk.Label(self.spec_wrap, text="Finalidad del cultivo",
                                      bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.cb_finalidad = ttk.Combobox(self.spec_wrap, state="readonly",
                                         values=["Cosecha de grano", "Siega en verde (forraje)"])
        self.cb_finalidad.set("Cosecha de grano")
        self.lbl_siembra = tk.Label(self.spec_wrap, text="Fecha de siembra",
                                    bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.e_siembra = CampoFecha(self.spec_wrap)
        self.lbl_marco = tk.Label(self.spec_wrap, text="Marco (calle x pie, m)",
                                  bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.marco_wrap = tk.Frame(self.spec_wrap, bg=TEMA["surface"])
        self.e_calle = ttk.Entry(self.marco_wrap, width=7)
        self.e_pie = ttk.Entry(self.marco_wrap, width=7)
        self.e_calle.pack(side="left")
        tk.Label(self.marco_wrap, text="x", bg=TEMA["surface"], fg=TEMA["text_muted"]).pack(side="left", padx=4)
        self.e_pie.pack(side="left")
        # diametro de copa (opcional): ver el campo equivalente en VentanaAltaParcela
        tk.Label(self.marco_wrap, text="  copa", bg=TEMA["surface"],
                 fg=TEMA["text_muted"], font=FUENTES["small"]).pack(side="left")
        self.e_copa = ttk.Entry(self.marco_wrap, width=5)
        self.e_copa.pack(side="left", padx=(4, 0))
        tk.Label(self.marco_wrap, text="m", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left", padx=(2, 0))
        self.lbl_regimen = tk.Label(self.spec_wrap, text="Regimen hidrico",
                                    bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.cb_regimen = ttk.Combobox(self.spec_wrap, state="readonly", width=14,
                                       values=["Secano", "Regadio"])
        self.cb_regimen.set("Secano")
        self.lbl_tipo_calc = tk.Label(self.spec_wrap, text="", bg=TEMA["surface"],
                                      fg=TEMA["ok_fg"], font=FUENTES["small"])
        self.e_calle.bind("<KeyRelease>", lambda e: self._calc_marco())
        self.e_pie.bind("<KeyRelease>", lambda e: self._calc_marco())
        self.e_copa.bind("<KeyRelease>", lambda e: self._calc_marco())

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
        for w in (self.lbl_finalidad, self.cb_finalidad, self.lbl_siembra, self.e_siembra,
                  self.lbl_marco, self.marco_wrap, self.lbl_regimen, self.cb_regimen,
                  self.lbl_tipo_calc):
            w.pack_forget()
        if grupo == "EXTENSIVO":
            self.lbl_finalidad.pack(anchor="w")
            self.cb_finalidad.pack(fill="x", pady=(0, 4))
            self.lbl_siembra.pack(anchor="w")
            self.e_siembra.pack(fill="x")
        elif grupo == "LENOSO":
            self.lbl_marco.pack(anchor="w")
            self.marco_wrap.pack(anchor="w", pady=(0, 2))
            self.lbl_regimen.pack(anchor="w")
            self.cb_regimen.pack(anchor="w", pady=(0, 2))
            self.lbl_tipo_calc.pack(anchor="w")
            self._calc_marco()

    def _calc_marco(self):
        """Al teclear el marco (o la copa), enseña lo que implica.

        El texto lo redacta `fenologia_especies.texto_marco`, que es donde vive el
        calculo: densidad, tipo de plantacion y que fraccion de suelo tapa la copa,
        que es la que traduce los umbrales a escala de parcela."""
        try:
            c = float(self.e_calle.get().replace(",", "."))
            p = float(self.e_pie.get().replace(",", "."))
            self.lbl_tipo_calc.config(text=FEN.texto_marco(
                self.cb_sub.get() or "OLIVO", c, p, _copa_de(self.e_copa)))
        except Exception:
            self.lbl_tipo_calc.config(text="")

    def _mostrar(self):
        nombre = self.pendientes[self.idx]
        self.lbl_parc.config(text=nombre.replace("_", " "))
        self.lbl_prog.config(text=f"Parcela {self.idx + 1} de {len(self.pendientes)}")
        ficha = DB.ficha(nombre) or {}
        campos = ficha.get("cultivos_por_campana", {})
        prev = campos.get(sorted(campos)[-1]) if campos else None
        self.cb_tipo.set(prev.get("tipo") if prev else "LENOSO")
        self._sub()
        # rellenar con lo de la campana anterior si existe
        if prev:
            if prev.get("especie"):
                self.cb_sub.set(prev["especie"])
                self._sub()
            if prev.get("finalidad") == "SIEGA_VERDE" or prev.get("subtipo") == "SIEGA_VERDE":
                self.cb_finalidad.set("Siega en verde (forraje)")
            if prev.get("fecha_siembra"):
                self.e_siembra.set_iso(prev["fecha_siembra"])
            if prev.get("marco_calle"):
                self.e_calle.delete(0, tk.END); self.e_calle.insert(0, str(prev["marco_calle"]))
                self.e_pie.delete(0, tk.END); self.e_pie.insert(0, str(prev["marco_pie"]))
                self.e_copa.delete(0, tk.END)
                if prev.get("diametro_copa"):
                    self.e_copa.insert(0, str(prev["diametro_copa"]))
                self._calc_marco()

    def _siguiente(self):
        tipo = self.cb_tipo.get()
        esp = self.cb_sub.get()
        if not tipo:
            return messagebox.showwarning("Cultivo", "Selecciona el tipo de cultivo.", parent=self)
        if tipo != "BARBECHO" and not esp:
            return messagebox.showwarning("Cultivo", "Selecciona la especie.", parent=self)
        spec = {"especie": esp} if tipo != "BARBECHO" else {}
        if tipo == "EXTENSIVO":
            spec["finalidad"] = ("SIEGA_VERDE" if self.cb_finalidad.get().startswith("Siega")
                                 else "COSECHA_GRANO")
            if not self.e_siembra.esta_vacio():
                siembra = self.e_siembra.get_iso()
                if not siembra:
                    return messagebox.showwarning("Siembra", "Fecha de siembra: dd-mm-aaaa (o dejala vacia).",
                                                  parent=self)
                spec["fecha_siembra"] = siembra
        if tipo == "LENOSO":
            try:
                spec["marco_calle"] = float(self.e_calle.get().replace(",", "."))
                spec["marco_pie"] = float(self.e_pie.get().replace(",", "."))
            except ValueError:
                return messagebox.showwarning("Marco", "Indica el marco (calle y pie en metros).", parent=self)
            # opcional: sin diametro de copa se estima del marco, como siempre
            spec["diametro_copa"] = _copa_de(self.e_copa)
            spec["regimen"] = "REGADIO" if self.cb_regimen.get().startswith("Rega") else "SECANO"
        self.panel.asignar_cultivo(self.pendientes[self.idx], tipo, spec)
        self.idx += 1
        if self.idx < len(self.pendientes):
            self._mostrar()
        else:
            self.destroy()
            if messagebox.askyesno("Nueva campana",
                                   "Cultivos asignados. Deseas anadir alguna parcela mas?",
                                   parent=self.panel.winfo_toplevel()):
                self.panel.abrir_alta_parcela()


class DialogoCorreccion(tk.Toplevel):
    """Pide el estado real y una nota para corregir un diagnostico (aprendizaje)."""
    def __init__(self, master, ficha, ctx):
        super().__init__(master)
        self.ficha = ficha
        self.title("Corregir diagnostico")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(60, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))
        self.grab_set()

        tk.Label(self, text="El sistema diagnostico:", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(14, 0))
        tk.Label(self, text=f"[{ctx.get('estado','?')}]  ·  Fase: {ctx.get('fase','?')}",
                 bg=TEMA["surface"], fg=TEMA["text"], font=FUENTES["body"]).pack(anchor="w", padx=16)
        tk.Label(self, text="¿Cual era el estado correcto?", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(10, 0))
        self.cb = ttk.Combobox(self, state="readonly", values=FichaParcela.ESTADOS_VALIDABLES, width=18)
        self.cb.set(ctx.get("estado", "OK"))
        self.cb.pack(anchor="w", padx=16, pady=(2, 0))
        # --- AMBITO de la correccion: solo esta finca o todo el cultivo ---
        tk.Label(self, text="¿A que debe aplicarse esta correccion?", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(12, 0))
        self.ambito = tk.StringVar(value="cultivo")
        _cult = (ctx.get("cultivo", "") or "").split("/")[-1] or "este cultivo"
        _parc = ficha.nombre.replace("_", " ")
        ttk.Radiobutton(self, variable=self.ambito, value="cultivo",
                        text=f"A todas mis parcelas de {_cult}").pack(anchor="w", padx=24)
        ttk.Radiobutton(self, variable=self.ambito, value="parcela",
                        text=f"Solo a «{_parc}» (esta finca es especial)").pack(anchor="w", padx=24)

        tk.Label(self, text="Observacion (opcional):", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(10, 0))
        self.txt = tk.Text(self, width=44, height=4, bd=1, relief="solid",
                           font=FUENTES["body"], highlightthickness=0)
        self.txt.pack(padx=16, pady=(2, 0))
        bar = tk.Frame(self, bg=TEMA["surface"])
        bar.pack(fill="x", padx=16, pady=14)
        ttk.Button(bar, text="Cancelar", style="Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Guardar correccion", style="Accent.TButton",
                   command=self._guardar).pack(side="right", padx=(0, 8))

    def _guardar(self):
        estado_real = self.cb.get()
        nota = self.txt.get("1.0", tk.END).strip()
        self.ficha._validar("incorrecto", estado_real=estado_real, nota=nota,
                            solo_parcela=(self.ambito.get() == "parcela"))
        self.destroy()


class DialogoValidacionIndices(tk.Toplevel):
    """Validacion INDICE A INDICE de una pasada, con el alcance de la correccion.

    Cada indice llega con lo que midio el satelite y con lo que el sistema opina
    (bajo / normal / alto), ya preseleccionado en su desplegable: confirmar es no
    tocar nada. Lo que se cambie mueve el umbral de ESE indice, en el alcance
    elegido, sin tocar los valores de la bibliografia.

    Vive detras del modulo opcional `calibracion_umbrales`: si se borra, ni este
    dialogo ni su boton existen.
    """

    def __init__(self, master, ficha, ctx):
        super().__init__(master)
        self.ficha, self.ctx = ficha, ctx
        self.title("Validar indices de la pasada")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(60, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))
        self.grab_set()

        cab = f"{ficha.nombre.replace('_', ' ')}  ·  {ctx.get('fecha', '?')}"
        tk.Label(self, text=cab, bg=TEMA["surface"], fg=TEMA["text"],
                 font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 0))
        sub = f"Fase: {ctx.get('fase', '?')}"
        if ctx.get("especie"):
            sub = f"{ctx['especie']}  ·  " + sub
        tk.Label(self, text=sub, bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16)
        tk.Label(self, text="Confirma o corrige lo que el sistema ve en cada indice. "
                            "Ya viene marcado lo que opina: si estas de acuerdo, no toques nada.",
                 bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"],
                 wraplength=470, justify="left").pack(anchor="w", padx=16, pady=(8, 4))

        tabla = tk.Frame(self, bg=TEMA["surface"])
        tabla.pack(fill="x", padx=16, pady=(0, 4))
        for col, txt in enumerate(("Indice", "Valor", "El sistema ve", "Tu dices")):
            tk.Label(tabla, text=txt, bg=TEMA["surface"], fg=TEMA["text_muted"],
                     font=FUENTES["small"]).grid(row=0, column=col, sticky="w", padx=(0, 12))

        previas = DB.validaciones_indice_de_pasada(ficha.nombre, ficha.campana,
                                                   ctx.get("fecha", ""))
        self.combos = {}
        fila = 1
        for idx in INDICES_ORDEN:
            lec = (ctx.get("lecturas") or {}).get(idx) or {}
            if lec.get("valor") is None:
                continue                      # ese dia no se midio: no hay nada que validar
            tk.Label(tabla, text=idx, bg=TEMA["surface"], fg=TEMA["text"],
                     font=FUENTES["small"]).grid(row=fila, column=0, sticky="w", pady=1)
            tk.Label(tabla, text=f"{lec['valor']:.3f}", bg=TEMA["surface"], fg=TEMA["text"],
                     font=FUENTES["small"]).grid(row=fila, column=1, sticky="w", padx=(0, 12))
            visto = lec.get("sistema", _CALIB.SIN_CRITERIO)
            tk.Label(tabla, text=visto, bg=TEMA["surface"],
                     fg=TEMA["danger_fg"] if visto == "bajo" else TEMA["text_sec"],
                     font=FUENTES["small"]).grid(row=fila, column=2, sticky="w", padx=(0, 12))
            cb = ttk.Combobox(tabla, state="readonly", width=10, values=_CALIB.ESTADOS)
            # preseleccionado con lo que ya dijiste antes; si no, con lo que ve el
            # sistema; y si el sistema no tiene criterio en esta fase, "normal"
            anterior = (previas.get(idx) or {}).get("dijo_usuario")
            cb.set(anterior or (visto if visto in _CALIB.ESTADOS else "normal"))
            cb.grid(row=fila, column=3, sticky="w", pady=1)
            self.combos[idx] = cb
            if not lec.get("calibrable"):
                tk.Label(tabla, text="(se anota, hoy no mueve umbral)", bg=TEMA["surface"],
                         fg=TEMA["text_muted"], font=FUENTES["small"]).grid(
                             row=fila, column=4, sticky="w", padx=(8, 0))
            fila += 1

        tk.Label(self, text="¿A que debe aplicarse lo que digas?", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(10, 0))
        self.ambitos = _CALIB.ambitos_disponibles(ficha.nombre)
        self.cb_ambito = ttk.Combobox(self, state="readonly", width=34,
                                      values=[t for _, t in self.ambitos])
        self.cb_ambito.current(0)
        self.cb_ambito.pack(anchor="w", padx=16, pady=(2, 0))
        if len(self.ambitos) < 4:
            tk.Label(self, text="Esta parcela no tiene municipio ni provincia guardados: "
                                "capturala por SIGPAC o editala para poder corregir a ese nivel.",
                     bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"],
                     wraplength=470, justify="left").pack(anchor="w", padx=16, pady=(4, 0))

        botones = tk.Frame(self, bg=TEMA["surface"])
        botones.pack(fill="x", padx=16, pady=14)
        ttk.Button(botones, text="  Guardar  ", style="Accent.TButton",
                   command=self._guardar).pack(side="right")
        ttk.Button(botones, text="  Cancelar  ", style="Ghost.TButton",
                   command=self.destroy).pack(side="right", padx=(0, 8))

    def _guardar(self):
        ambito = self.ambitos[self.cb_ambito.current()][0]
        respuestas = {idx: cb.get() for idx, cb in self.combos.items()}
        # los umbrales llevan el regimen y la densidad: sin eso, lo validado en un
        # olivar de secano contaminaria a un seto de regadio
        n = _CALIB.registrar(self.ficha.nombre, self.ficha.campana, self.ctx.get("fecha"),
                             self.ctx.get("especie"), self.ctx.get("fase"),
                             self.ctx.get("lecturas"), respuestas, ambito,
                             umbrales=self.ctx.get("umbrales"))
        self.destroy()
        self.ficha.refrescar()          # el umbral puede haber cambiado ya
        messagebox.showinfo("Validacion",
                            f"Anotados {n} indice(s) para «{dict(self.ambitos)[ambito]}».\n\n"
                            f"Hacen falta {_CALIB.MIN_OBSERVACIONES} validaciones coherentes "
                            f"de la misma especie y fase para que un umbral se mueva.",
                            parent=self.ficha.master)


class DialogoSincronizarCampanas(tk.Toplevel):
    """Descarga Copernicus para una o varias campanas (anos anteriores) de la parcela."""
    def __init__(self, master, panel, nombre, campana_ficha):
        super().__init__(master)
        self.panel, self.nombre = panel, nombre
        self.title("Sincronizar campanas anteriores")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(60, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))
        self.grab_set()

        # El limite lo pone el satelite, no el programa: Sentinel-2 L2A empieza en
        # la campana 2017-2018 (ver campanas.PRIMERA_CAMPANA_S2). Las campanas mas
        # antiguas que eso, si las hay guardadas, salen listadas pero sin casilla:
        # no se pueden descargar, solo consultarlas desde la ficha.
        camps = campanas_de_parcela(DB.campanas_de(nombre))

        tk.Label(self, text=f"Parcela: {nombre.replace('_', ' ')}", bg=TEMA["surface"],
                 fg=TEMA["text"], font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(self, text=f"Copernicus llega hasta la campana {PRIMERA_CAMPANA_S2} "
                            f"(cobertura completa desde {PRIMERA_CAMPANA_S2_GLOBAL}).\n"
                            "Marca las que quieras descargar (incremental, no repite). Si una campana\n"
                            "no tiene datos de satelite, se avisara al sincronizar. Para VER una,\n"
                            "seleccionala en el desplegable de campana de la ficha.",
                 bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"],
                 justify="left").pack(anchor="w", padx=16)

        cont, interior = marco_scroll(self, bg=TEMA["surface"], rueda_global=True)
        cont.configure(height=180, width=320)
        cont.pack(fill="x", padx=16, pady=8)
        cont.pack_propagate(False)
        self.vars = {}
        for c in camps:
            etiqueta = FichaParcela._etiqueta_campana(c)
            if not c["sincronizable"]:
                # guardada pero fuera del alcance del satelite: se ensena para que
                # se sepa que esta ahi, sin casilla porque no hay nada que pedir
                tk.Label(interior, text="      " + etiqueta, bg=TEMA["surface"],
                         fg=TEMA["text_muted"], font=FUENTES["small"]).pack(anchor="w", pady=1)
                continue
            v = tk.BooleanVar(value=(c["campana"] == campana_ficha))
            self.vars[c["campana"]] = v
            ttk.Checkbutton(interior, text=etiqueta, variable=v).pack(anchor="w", pady=1)

        self.lbl_prog = tk.Label(self, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                 font=FUENTES["small"])
        self.lbl_prog.pack(anchor="w", padx=16)
        bar = tk.Frame(self, bg=TEMA["surface"])
        bar.pack(fill="x", padx=16, pady=14)
        ttk.Button(bar, text="Cerrar", style="Ghost.TButton", command=self.destroy).pack(side="right")
        self.btn = ttk.Button(bar, text="Sincronizar seleccionadas", style="Accent.TButton",
                              command=self._sync)
        self.btn.pack(side="right", padx=(0, 8))

    def _sync(self):
        if not _EE:
            return messagebox.showwarning("GEE", "earthengine-api no disponible.", parent=self)
        sel = [c for c, v in self.vars.items() if v.get()]
        if not sel:
            return messagebox.showinfo("Sincronizar", "No has marcado ninguna campana.", parent=self)
        self.btn.config(state="disabled")
        threading.Thread(target=self._worker, args=(sel,), daemon=True).start()

    def _worker(self, sel):
        total, lineas = 0, []
        orden = sorted(sel)
        for i, camp in enumerate(orden, 1):
            self.after(0, lambda c=camp, k=i: self._prog(f"Sincronizando {c}  ({k}/{len(orden)})…"))
            tenia = DB.ultima_fecha(self.nombre, camp) is not None
            try:
                n, msg = sincronizar_parcela(self.nombre, camp, silencioso=True)
            except Exception as e:
                n, msg = 0, f"error: {e}"
            total += n
            if n == 0 and not tenia and DB.ultima_fecha(self.nombre, camp) is None:
                lineas.append(f"{camp}: NO hay datos de Copernicus para esa campana")
            else:
                lineas.append(f"{camp}: {msg}")
        if ULTIMO_SYNC.get("estado") != "fallo":
            sincronizacion.marca_guardar()

        def fin():
            if not self.btn.winfo_exists():
                return
            self._prog(f"Hecho. {total} pasada(s) nueva(s) en total.")
            self.btn.config(state="normal")
            self.panel.cb_campana["values"] = self.panel._campanas()
            self.panel._actualizar_estado_sync()
            self.panel._refrescar()
            messagebox.showinfo("Sincronizacion de campanas", "\n".join(lineas), parent=self)
        self.after(0, fin)

    def _prog(self, texto):
        if self.lbl_prog.winfo_exists():
            self.lbl_prog.config(text=texto)


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
        self.fig_ley = Figure(figsize=(0.9, 3.0), dpi=90)
        self.cv_ley = FigureCanvasTkAgg(self.fig_ley, master=cont)
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


class VentanaComparaMapas(tk.Toplevel):
    """Ventana con dos visores de mapa lado a lado: dos dias distintos, o el
    mismo dia con distinto indice."""
    def __init__(self, master, nombre, campana, fechas_map, idx_ini, res_ini):
        super().__init__(master)
        self.title(f"Comparar mapas · {nombre.replace('_', ' ')} · {campana}")
        self.geometry("1150x620")
        self.configure(bg=TEMA["page"])
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(80, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))

        coords = (DB.ficha(nombre) or {}).get("coordenadas") or []
        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        tk.Label(cab, text="Comparar mapas de indices", bg=TEMA["header_bg"], fg="#fff",
                 font=FUENTES["h2"]).pack(side="left", padx=16, pady=10)
        tk.Label(cab, text="Elige dia e indice en cada panel: dos dias distintos, "
                           "o el mismo dia con distinto indice.",
                 bg=TEMA["header_bg"], fg="#cbd5e1", font=FUENTES["small"]).pack(side="left", padx=6)

        cuerpo = tk.Frame(self, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=8, pady=8)
        n = len(fechas_map)
        # por defecto: izquierda el ultimo dia, derecha el penultimo (comparativa temporal)
        self.izq = PanelMapaComparado(cuerpo, nombre, coords, fechas_map, idx_ini, res_ini,
                                      dia_ini=n - 1 if n else None)
        self.der = PanelMapaComparado(cuerpo, nombre, coords, fechas_map, idx_ini, res_ini,
                                      dia_ini=(n - 2 if n >= 2 else n - 1) if n else None)


class DialogoEfectoProducto(tk.Toplevel):
    """Muestra el efecto de un producto y deja ELEGIR el dia del informe (la pasada
    posterior a la aplicacion contra la que se mide). Se puede guardar como dia
    del informe de esa intervencion."""
    def __init__(self, master, ficha, evento, serie):
        super().__init__(master)
        self.ficha, self.evento = ficha, evento
        self.serie = sorted(serie or [], key=lambda r: r.get("fecha", ""))
        self.title("Efecto del producto")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(60, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))
        self.grab_set()

        f_ap = evento.get("fecha")
        tk.Label(self, text=f"{evento.get('producto', '')}   ·   {evento.get('objetivo', '')}",
                 bg=TEMA["surface"], fg=TEMA["text"], font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(self, text=f"Aplicado: {f_ap}", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16)

        # pasadas validas posteriores a la aplicacion -> opciones de dia del informe
        self.post = [r for r in self.serie
                     if r.get("fecha") and r["fecha"] > f_ap and r.get("ndvi") is not None]
        self.lbl2fecha = {self._etq(r): r["fecha"] for r in self.post}

        fila = tk.Frame(self, bg=TEMA["surface"])
        fila.pack(fill="x", padx=16, pady=(10, 2))
        tk.Label(fila, text="Dia del informe", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left")
        self.cb = ttk.Combobox(fila, state="readonly", width=22,
                               values=["(automatico)"] + list(self.lbl2fecha.keys()))
        self.cb.pack(side="left", padx=6)
        self.cb.bind("<<ComboboxSelected>>", lambda e: self._actualizar())
        # seleccion inicial: el dia guardado (el mas cercano), o automatico
        sel = "(automatico)"
        obj = evento.get("fecha_informe")
        if obj and self.post:
            cercana = min(self.post, key=lambda r: abs(self._dias(obj, r["fecha"])))
            sel = self._etq(cercana)
        self.cb.set(sel)

        self.txt = tk.Text(self, width=52, height=9, bd=0, relief="flat", bg="#f2f8ff",
                           fg=TEMA["text"], font=FUENTES["body"], padx=12, pady=10, highlightthickness=0)
        self.txt.pack(fill="both", expand=True, padx=16, pady=(8, 0))

        bar = tk.Frame(self, bg=TEMA["surface"])
        bar.pack(fill="x", padx=16, pady=12)
        ttk.Button(bar, text="Cerrar", style="Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Guardar como dia del informe", style="Accent.TButton",
                   command=self._guardar).pack(side="right", padx=(0, 8))
        self._actualizar()

    @staticmethod
    def _dias(a, b):
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days

    def _etq(self, r):
        return f"{r['fecha']}   (+{self._dias(self.evento.get('fecha'), r['fecha'])} d)"

    def _fecha_sel(self):
        return self.lbl2fecha.get(self.cb.get())     # None si es "(automatico)"

    def _actualizar(self):
        # se calcula sobre una copia SIN fecha_informe: asi "(automatico)" es de
        # verdad automatico aunque la intervencion ya tenga un dia guardado.
        ev = {k: v for k, v in self.evento.items() if k != "fecha_informe"}
        ef = REG.efecto_producto(self.serie, ev, fecha_objetivo=self._fecha_sel())
        self.txt.config(state="normal")
        self.txt.delete("1.0", tk.END)
        if not ef or not ef.get("disponible"):
            self.txt.insert(tk.END, ef["nota"] if ef else "Sin datos suficientes.")
        else:
            msg = (f"Dia del informe: {ef['dia_informe']}  ({ef['dias_despues']} dias despues)\n\n"
                   f"NDVI: {ef['ndvi_antes']} -> {ef['ndvi_despues']}   ({ef['d_ndvi']:+.3f})\n")
            if ef.get("d_ndmi") is not None:
                msg += f"NDMI: {ef['ndmi_antes']} -> {ef['ndmi_despues']}   ({ef['d_ndmi']:+.3f})\n"
            if ef.get("d_lai") is not None:
                msg += f"LAI:  {ef['lai_antes']} -> {ef['lai_despues']}   ({ef['d_lai']:+.2f})"
                msg += "   (clave en herbicidas)\n" if ef.get("es_herbicida") else "\n"
            if ef.get("es_herbicida") and ef.get("d_std") is not None:
                msg += f"Dispersion NDVI: {ef['d_std']:+.3f}   (baja = parcela mas homogenea)\n"
            msg += f"\nLectura: {ef['verdicto']}.\n\n{ef['aviso']}"
            self.txt.insert(tk.END, msg)
        self.txt.config(state="disabled")

    def _guardar(self):
        fecha = self._fecha_sel()
        if fecha:
            self.evento["fecha_informe"] = fecha
        else:
            self.evento.pop("fecha_informe", None)   # volver al automatico
        REG.registrar_evento(self.ficha.nombre, self.ficha.campana, self.evento)
        self.ficha._refrescar_eventos()
        messagebox.showinfo("Dia del informe",
                            f"Guardado: el efecto se medira en {fecha}." if fecha else
                            "Guardado: dia del informe automatico.", parent=self)
        self.destroy()


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
        self.geometry("1160x650")
        self.configure(bg=TEMA["page"])
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(80, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))

        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        tk.Label(cab, text="Radar Sentinel-1  ·  parametros, interpretacion y mapa",
                 bg=TEMA["header_bg"], fg="#fff", font=FUENTES["h2"]).pack(side="left", padx=16, pady=10)
        est = (f"{msg}" if n == 0 else f"descargadas {n} pasadas de radar nuevas")
        tk.Label(cab, text=f"({est})", bg=TEMA["header_bg"], fg="#cbd5e1",
                 font=FUENTES["small"]).pack(side="left", padx=6)

        cuerpo = tk.Frame(self, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- IZQUIERDA: grafica de parametros de radar + interpretacion ----
        izq = tarjeta(cuerpo, width=560)
        izq.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(izq, text="Evolucion de los parametros de radar", bg=TEMA["surface"],
                 fg=TEMA["text"], font=FUENTES["h2"]).pack(anchor="w", padx=12, pady=(10, 4))
        self.fig = Figure(figsize=(6, 2.7), dpi=90)
        self.cv = FigureCanvasTkAgg(self.fig, master=izq)
        self.cv.get_tk_widget().pack(fill="x", padx=12, pady=(0, 6))
        self._pintar_grafica_radar()
        txt = tk.Text(izq, wrap="word", height=8, bd=0, relief="flat", bg="#eef7f5",
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
        self.fig_ley = Figure(figsize=(0.95, 3.0), dpi=90)
        self.cv_ley = FigureCanvasTkAgg(self.fig_ley, master=cont)
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
            for k, color, lbl in [("vv", "#64748b", "VV (dB)"), ("vh", "#0ea5e9", "VH (dB)"),
                                  ("cr", "#d97706", "CR=VH-VV (dB)")]:
                ys = [p[1].get(k) for p in pts]
                if any(v is not None for v in ys):
                    ax.plot(fechas, [v if v is not None else float("nan") for v in ys],
                            marker="o", ms=3, lw=1.6, label=lbl, color=color)
            ax.set_ylabel("dB", fontsize=8)
            ax2 = ax.twinx()          # RVI en eje 0-1 aparte
            rvis = [p[1].get("rvi") for p in pts]
            if any(v is not None for v in rvis):
                ax2.plot(fechas, [v if v is not None else float("nan") for v in rvis],
                         marker="s", ms=3, lw=1.8, ls="--", label="RVI", color="#0d9488")
                los = [p[1].get("rvi_lo") for p in pts]
                his = [p[1].get("rvi_hi") for p in pts]
                if all(x is not None for x in los) and all(x is not None for x in his):
                    ax2.fill_between(fechas, los, his, color="#0d9488", alpha=0.15)
                ax2.set_ylabel("RVI", fontsize=8)
                ax2.set_ylim(0, 1)
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels()
            ax.legend(h1 + h2, l1 + l2, fontsize=7, ncol=4, loc="upper center",
                      bbox_to_anchor=(0.5, 1.18))
            self.fig.autofmt_xdate()
        self.fig.tight_layout()
        self.cv.draw()

    def _leyenda_radar(self, param):
        self.fig_ley.clear()
        vis = RADAR_VIS.get(param, RADAR_VIS["RVI"])
        ax = self.fig_ley.add_axes([0.1, 0.05, 0.32, 0.9])
        cmap = mcolors.LinearSegmentedColormap.from_list("x", ["#" + c for c in vis["paleta"]])
        cb = matplotlib.colorbar.ColorbarBase(ax, cmap=cmap,
                                              norm=mcolors.Normalize(*vis["rango"]),
                                              orientation="vertical")
        cb.ax.tick_params(labelsize=7)
        cb.set_label(param + (" (dB)" if param in ("VV", "VH") else ""), fontsize=8)
        self.cv_ley.draw()

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


# =====================================================================
# FICHA DE PARCELA
# =====================================================================
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
                 bg=TEMA["header_bg"], fg="#fff", font=FUENTES["h2"]).pack(side="left")
        self._build_selector_campana(cab)
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

        cont, scroll = marco_scroll(master, bg=TEMA["page"])
        cont.pack(fill="both", expand=True)
        cuerpo = tk.Frame(scroll, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=14, pady=14)

        # Alturas fijas por fila: dentro de un marco con scroll el contenido debe
        # tener una altura REAL (si se deja expand=True, el mapa y la grafica se
        # estiran hasta la ventana y no queda nada que desplazar -> no se ve abajo).
        sup = tk.Frame(cuerpo, bg=TEMA["page"], height=380)
        sup.pack(fill="x")
        sup.pack_propagate(False)
        self._build_tabla(sup)
        self._build_mapa(sup)

        inf = tk.Frame(cuerpo, bg=TEMA["page"], height=320)
        inf.pack(fill="x", pady=(14, 0))
        inf.pack_propagate(False)
        self._build_graficas(inf)
        self._build_interp(inf)

        # 410 px = lo que MIDE el cuaderno completo (402) mas un margen. Es fijo a
        # proposito, como el resto de filas: dentro del marco con scroll el contenido
        # necesita altura real. Si se le queda corto, pack deja sin dibujar lo ultimo
        # que hay dentro -que es la lista de rendimientos-, sin avisar de nada.
        inf2 = tk.Frame(cuerpo, bg=TEMA["page"], height=410)
        inf2.pack(fill="x", pady=(14, 0))
        inf2.pack_propagate(False)
        self._build_cuaderno(inf2)

        # estadistica espacial por pasada, bajo el cuaderno de campo
        inf3 = tk.Frame(cuerpo, bg=TEMA["page"], height=240)
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
    def _build_selector_campana(self, cab):
        marco = tk.Frame(cab, bg=TEMA["header_bg"])
        marco.pack(side="left", padx=(14, 0))
        tk.Label(marco, text="Campana", bg=TEMA["header_bg"], fg=TEMA["header_sub"],
                 font=FUENTES["small"]).pack(side="left", padx=(0, 6))
        self.cb_campana_ficha = ttk.Combobox(marco, state="readonly", width=26)
        self.cb_campana_ficha.pack(side="left")
        self.cb_campana_ficha.bind("<<ComboboxSelected>>", self._cambiar_campana)
        self._refrescar_campanas()

    def _campanas_ficha(self):
        return campanas_de_parcela(DB.campanas_de(self.nombre))

    @staticmethod
    def _etiqueta_campana(c, n_pasadas=None):
        """Una linea que dice de un vistazo que se puede hacer con esa campana."""
        marca = c["campana"]
        if c["actual"]:
            marca += "  ·  en curso"
        if c["solo_archivo"]:
            return marca + "  ·  solo archivo"
        if c["tiene_datos"]:
            return marca + (f"  ✓ {n_pasadas} pasadas" if n_pasadas else "  ✓ con datos")
        return marca + ("  ·  sin descargar (parcial)" if c["parcial"]
                        else "  ·  sin descargar")

    def _refrescar_campanas(self):
        if not hasattr(self, "cb_campana_ficha") or not self.cb_campana_ficha.winfo_exists():
            return
        self._campanas_disp = self._campanas_ficha()
        # el numero de pasadas solo de la campana abierta: contarlas todas seria
        # una consulta por campana cada vez que se refresca la ficha
        etiquetas = [self._etiqueta_campana(
            c, len(DB.pasadas(self.nombre, c["campana"])) if c["campana"] == self.campana else None)
            for c in self._campanas_disp]
        self.cb_campana_ficha["values"] = etiquetas
        for i, c in enumerate(self._campanas_disp):
            if c["campana"] == self.campana:
                self.cb_campana_ficha.current(i)
                break

    def _cambiar_campana(self, _=None):
        i = self.cb_campana_ficha.current()
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
        """Cambia la campana del panel y vuelve a montar la ficha en ella."""
        self.panel.campana = camp
        if hasattr(self.panel, "cb_campana") and self.panel.cb_campana.winfo_exists():
            # el selector del panel solo lista campanas CON datos; si se abre una
            # vacia hay que meterla o quedaria puesta una campana que no esta en la
            # lista y el desplegable ensenaria otra cosa
            self.panel.cb_campana["values"] = sorted(
                set(self.panel._campanas()) | {camp}, reverse=True)
            self.panel.cb_campana.set(camp)
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
            self.tv.column(c, width=88 if c == "fecha" else 56,
                           anchor="w" if c == "fecha" else "center")
        self.tv.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.tv.tag_configure("ult", background="#fffaf0")

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
            self.tv_est.column(clave, width=ancho,
                               anchor="w" if clave == "fecha" else "center")
        self.tv_est.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.tv_est.tag_configure("ult", background="#fffaf0")

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
        self.fig_ley = Figure(figsize=(1.0, 3.2), dpi=90)
        self.cv_ley = FigureCanvasTkAgg(self.fig_ley, master=cont)
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
        self.fig = Figure(figsize=(6, 2.7), dpi=90)
        self.cv = FigureCanvasTkAgg(self.fig, master=card)
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
                           bg="#f2f8ff", fg=TEMA["text"], font=FUENTES["body"],
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
        self._pintar_estadisticas(regs)
        self._pintar_mapa()

    @staticmethod
    def _fmt(iso):
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{_FMT_DIAS[d.weekday()]}, {d.day} {_FMT_MESES[d.month-1]} {d.year}"

    def _pintar_graficas(self, regs):
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
            self._hover_datos = [(mdates.date2num(f), r, tooltip_pasada(r))
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
                            marker="o", ms=3, lw=1.8, label=K, color=COLOR_INDICE.get(K, "#666"))
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
                            ls="--", label="RVI·S1", color=COLOR_INDICE["RVI"])
                    # banda de incertidumbre del RVI (rango por speckle/dispersion)
                    banda = [(f, lo, hi) for f, _y, lo, hi in rad if lo is not None and hi is not None]
                    if len(banda) >= 2:
                        ax.fill_between([b[0] for b in banda], [b[1] for b in banda],
                                        [b[2] for b in banda], color=COLOR_INDICE["RVI"], alpha=0.15)
            # --- marcadores de eventos del cuaderno de campo ---
            vistos = set()
            for e in REG.eventos_de(self.nombre, self.campana):
                try:
                    fx = datetime.strptime(e["fecha"], "%Y-%m-%d")
                except Exception:
                    continue
                col, et = _ICONOS_EVENTO.get(e.get("tipo"), _ICONOS_EVENTO["OTRO"])
                lbl = et if et not in vistos else None
                vistos.add(et)
                ax.axvline(fx, color=col, ls="--", lw=1.0, alpha=0.7, label=lbl)
            ax.legend(fontsize=7, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.18))
            self.fig.autofmt_xdate()
            # --- puntero interactivo: linea vertical + caja con los valores del dia ---
            self._hover_linea = ax.axvline(fechas[0], color="#94a3b8", lw=0.8,
                                           alpha=0.0, zorder=1)
            self._hover_caja = ax.annotate(
                "", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
                fontsize=7.5, ha="left", va="bottom", visible=False, zorder=6,
                bbox=dict(boxstyle="round,pad=0.4", fc="#111827", ec="#111827", alpha=0.92),
                color="#f8fafc")
            if getattr(self, "_hover_cid", None) is not None:
                try:
                    self.cv.mpl_disconnect(self._hover_cid)
                except Exception:
                    pass    # silencio deliberado: el callback ya no existe tras redibujar
            self._hover_cid = self.cv.mpl_connect("motion_notify_event", self._on_hover)
        self.fig.tight_layout()
        self.cv.draw()

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
        # Se interpreta la pasada ELEGIDA (por defecto la ultima). Para juzgar un dia
        # anterior hay que darle al motor la serie HASTA ese dia: si se le pasara
        # entera, las variaciones se calcularian contra pasadas del futuro.
        idx = self._indice_pasada(regs)
        regs = regs[:idx + 1]
        actual = regs[-1]
        self._refrescar_selector_pasadas(
            sorted(self.panel._historico(self.nombre), key=lambda r: r.get("fecha", "")), idx)
        _ficha = DB.ficha(self.nombre) or {}
        cult = (_ficha.get("cultivos_por_campana", {}) or {}).get(self.campana, {})
        tipo, sub = cult.get("tipo", "BARBECHO"), cult.get("subtipo", "")
        spec = spec_de(cult)
        # el analisis de zonas se puede apagar por parcela (casilla de arriba)
        hetero_on = _ficha.get("heterogeneidad", True)
        if hasattr(self, "var_hetero") and self.var_hetero.get() != bool(hetero_on):
            self.var_hetero.set(bool(hetero_on))

        # eventos del cuaderno cercanos a esa pasada (para el diagnostico)
        eventos_cerca = REG.eventos_cercanos(self.nombre, self.campana,
                                             actual.get("fecha", ""), ventana_dias=20)

        # diagnostico fenologico (rapido, local): fase, estado, cubierta y eventos.
        # `parcela` solo sirve para aplicar los umbrales que tu hayas calibrado.
        diag = evaluar_parcela(tipo, sub, regs, eventos_cerca=eventos_cerca, spec=spec,
                               parcela=self.nombre, heterogeneidad_activa=hetero_on)
        estado_bruto = diag["estado"]          # el que produce el motor (base del aprendizaje)
        cultivo_id = f"{tipo}/{sub}" + (f"/{spec['especie']}" if spec and spec.get("especie") else "")

        historial = DB.validaciones_recientes(limite=300)
        # --- APRENDIZAJE de campanas anteriores (ajuste del estado por historial) ---
        # lo aprendido en ESTA parcela manda; si no hay, se usa lo del cultivo
        aj = ajuste_por_validaciones(cultivo_id, diag.get("fase"), estado_bruto, historial,
                                     parcela=self.nombre)
        if aj.get("corregido"):
            diag["estado"] = aj["corregido"]   # la prediccion se afina con el historial

        # --- VALIDACION PROPIA DE ESTA PASADA: lo que TU dijiste manda sobre lo mostrado ---
        # Aprende al momento: si corregiste esta pasada, se muestra tu estado; si la
        # confirmaste, se marca; y tu observacion escrita se refleja siempre.
        val_actual = DB.validacion_de(self.nombre, self.campana, actual.get("fecha"))
        nota_usuario = None
        if val_actual:
            if val_actual.get("veredicto") == "incorrecto" and val_actual.get("estado_real"):
                diag["estado"] = val_actual["estado_real"]
                nota_usuario = (f"Corregido por ti a '{val_actual['estado_real']}' "
                                f"(el sistema decia '{estado_bruto}'). El programa lo recuerda.")
            elif val_actual.get("veredicto") == "correcto":
                nota_usuario = f"Confirmado por ti como '{estado_bruto}'."
            obs_txt = (val_actual.get("nota") or "").strip()
            if obs_txt:
                nota_usuario = (nota_usuario or "") + f"  Tu observacion: “{obs_txt}”."

        self._estado_actual = diag["estado"]
        # contexto que se guarda al validar (se guarda el estado BRUTO, para aprender coherente)
        self._val_ctx = {"fecha": actual.get("fecha"), "fase": diag.get("fase"),
                         "estado": estado_bruto, "cultivo": cultivo_id}
        # contexto del dialogo de validacion POR INDICE: que midio el satelite ese
        # dia y que dice el sistema de cada indice con los umbrales de esa fase
        if _CALIB is not None:
            self._idx_ctx = {
                "fecha": actual.get("fecha"), "fase": diag.get("fase"),
                "especie": (spec or {}).get("especie", ""),
                "lecturas": _CALIB.lectura_de_pasada(actual, diag.get("umbrales") or {},
                                                     INDICES_ORDEN),
                "umbrales": diag.get("umbrales") or {}}

        # ---- ENCABEZADO compartido por el render inmediato y el de la IA ----
        cab = f"[{diag['estado']}]  Fase: {diag['fase']}"
        c = diag.get("cubierta")
        if c and c["señales"] >= 2:
            cab += f"  ·  Cubierta: {c['hipotesis_preliminar']} ({c['señales']}/4)"
        lineas = [cab]
        # estadistica espacial de la pasada (ya venia del satelite; aqui se muestra)
        txt_est = CI.texto_estadisticas(actual, diag.get("heterogeneidad"))
        if txt_est:
            lineas.append("📊 " + txt_est)
        if aj.get("nota"):
            lineas.append("🧠 " + aj["nota"])
        if nota_usuario:
            lineas.append("🧠 " + nota_usuario)
        # lo que la PERSONA dijo antes en este cultivo/fase (se muestra haya o no ChatGPT)
        obs_prev = [o for o in observaciones_del_agricultor(cultivo_id, diag.get("fase"), historial,
                                                            parcela=self.nombre)
                    if o.get("fecha") != actual.get("fecha")]
        if obs_prev:
            lineas.append("🗣️ Segun tus validaciones anteriores:")
            for o in obs_prev:
                lineas.append(f"   • [{o.get('estado', '?')}] {o['nota']}")
        encabezado = "\n".join(lineas) + "\n\n"

        self.txt.insert(tk.END, encabezado)
        self._refrescar_validacion()

        if tipo == "BARBECHO":
            self.txt.insert(tk.END, diag["motivo"])
            return
        # validaciones pasadas del agricultor -> aprendizaje para la IA (incluye tus notas)
        aprendizaje = DB.validaciones_recientes(limite=8, cultivo=cultivo_id)
        if actual.get("interpretacion"):          # cacheado (se invalida al corregir)
            self.txt.insert(tk.END, actual["interpretacion"])
            return
        self.txt.insert(tk.END, "Generando interpretacion...")

        def worker():
            texto, _d = texto_interpretacion(tipo, sub, regs, actual.get("fecha"),
                                             eventos_cerca=eventos_cerca, spec=spec,
                                             aprendizaje=aprendizaje)
            DB.set_interpretacion(self.nombre, self.campana, actual.get("fecha"), texto)

            def pintar():
                if not self.txt.winfo_exists():   # el usuario ya navego a otra vista
                    return
                self.txt.delete("1.0", tk.END)
                self.txt.insert(tk.END, encabezado + texto)
            self.master.after(0, pintar)
        threading.Thread(target=worker, daemon=True).start()

    # ---- validacion del diagnostico ----
    ESTADOS_VALIDABLES = ["OK", "Vigilar", "Revisar", "Segado", "N.A."]

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

    def _validar(self, veredicto, estado_real=None, nota="", solo_parcela=False):
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
                              estado_real=estado_real, nota=nota)
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
            self.tv_ev.column(c, width=w, anchor="w")
        self.tv_ev.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.tv_ev.bind("<Double-1>", lambda e: self._ver_efecto_evento())
        self.tv_ev.bind("<Button-3>", self._menu_evento)
        tk.Label(card, text="Doble clic en un producto: ver su efecto sobre el cultivo. "
                            "Clic derecho: eliminar.", bg=TEMA["surface"],
                 fg=TEMA["text_muted"], font=FUENTES["small"]).pack(anchor="w", padx=12, pady=(0, 4))

        # Historico de cosecha: lo unico medido en bascula, no interpretado.
        # Se listan TODAS las campanas, no solo la que se esta viendo.
        tk.Label(card, text="Rendimientos registrados  ·  se anotan con un evento COSECHA, "
                           "que admite fechas de campanas anteriores",
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
                                   bg="#ffffff", fg=TEMA["text"],
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
        (self.frame_prod.grid if tipo == "PRODUCTO" else self.frame_prod.grid_remove)()
        (self.frame_cosecha.grid if tipo == "COSECHA" else self.frame_cosecha.grid_remove)()
        if tipo == "COSECHA":
            (self.frame_humedad.grid if self._admite_humedad(self._campana_evento(
                self.ev_fecha.get_iso())) else self.frame_humedad.grid_remove)()

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
        elif ev["tipo"] == "COSECHA":
            admite = self._admite_humedad(campana)
            # si el cultivo no es grano, se avisa en vez de tirar el dato en silencio
            if not admite and self.ev_humedad.get().strip():
                self._toggle_campos_evento()
                return messagebox.showwarning(
                    "Cosecha", "Este cultivo no es grano de extensivo: ahi no se anota "
                    "humedad de grano. Borra ese campo para continuar.")
            try:
                ev.update(REG.datos_cosecha(
                    self.ev_rend.get(), self.ev_humedad.get(), self.ev_sup.get(),
                    self.ev_fuente.get(), admite_humedad=admite))
            except ValueError as e:
                return messagebox.showwarning("Cosecha", f"Revisa el campo {e}: "
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
            log.warning("no se pudo abrir el navegador en %s", CRED.URL_OPENAI_KEYS, exc_info=True)

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
                # si falla, el resto de la app no se entera del cambio de credenciales
                log.warning("fallo el aviso de cambio de credenciales", exc_info=True)
        messagebox.showinfo("Credenciales", "Credenciales guardadas. Probando conexiones…")


# =====================================================================
# DEMO
# =====================================================================
if __name__ == "__main__":
    DB.conectar()                    # abre SQLite y migra los JSON antiguos si existen
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
