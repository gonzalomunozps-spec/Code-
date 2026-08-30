# -*- coding: utf-8 -*-
"""
ui_tema.py
==========

SISTEMA DE DISENO de la aplicacion: los colores, las fuentes, la escala por DPI,
el icono, la carga perezosa de matplotlib y los cuatro ayudantes de maquetacion
que usa todo lo demas (tarjeta, centrar, marco con scroll, rueda del raton).

Es la BASE de la interfaz: no importa ninguna otra pieza de la aplicacion, asi
que se puede leer y probar sola. Todo lo que pinta algo importa de aqui.

Salio de `panel_gestion_parcelas.py`, que habia llegado a 4.300 lineas.

OJO con matplotlib: se carga tarde (ver `cargar_matplotlib`) y los nombres `Figure`,
`FigureCanvasTkAgg`, `mcolors`, `mdates` y `mpl` se RELLENAN entonces. Quien los
use desde otro modulo tiene que pedirlos como atributo -`ui_tema.Figure(...)`- y
no importarlos por nombre: una copia hecha al importar se queda en None para
siempre.
"""

import os
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont

from bitacora import log


# matplotlib se carga TARDE, la primera vez que hace falta una grafica.
# Importarla cuesta ~1,6 s y era, con diferencia, lo que mas retrasaba la
# aparicion de la ventana -para algo que no se usa hasta abrir una ficha, y que
# no se usa NUNCA si solo se consulta la lista-. Aqui solo quedan reservados los
# nombres; los rellena `cargar_matplotlib()`, que llama todo metodo que dibuja.
matplotlib = Figure = FigureCanvasTkAgg = mcolors = mdates = mpl = None


# =====================================================================
# ALTA RESOLUCION (DPI) Y ESCALA DE LA INTERFAZ
# =====================================================================
# Windows entrega a los programas que NO se declaran «conscientes del DPI» una
# ventana de 96 ppp y luego la AMPLIA como si fuera un mapa de bits: en un monitor
# 4K al 150 % la aplicacion entera sale borrosa, el texto el primero. Declararlo
# hay que hacerlo ANTES de crear la ventana -despues Windows ya ha decidido-, y
# por eso esto no vive dentro de `aplicar_tema`. En Linux y macOS el sistema de
# ventanas ya entrega pixeles reales: la funcion no hace nada y no estorba.
def activar_dpi():
    """Declara el proceso consciente del DPI. Llamar ANTES de crear `tk.Tk()`."""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)     # 2 = por monitor
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()          # anterior a Windows 8.1
        return True
    except Exception:
        return False       # no es Windows: aqui no hay nada que declarar


# Cuanto hay que ampliar lo que esta medido en pixeles. Lo rellena `aplicar_tema`
# leyendo el DPI real de la pantalla.
#
# OJO, no es cosmetico: al declarar el DPI las FUENTES pasan a medir sus puntos de
# verdad y crecen, pero una caja de 380 px sigue midiendo 380 px. Si no crecen las
# dos a la vez el contenido deja de caber, y `pack` -dentro del marco con scroll
# de la ficha- no avisa: sencillamente no dibuja lo ultimo que hay dentro (esta
# contado en `FichaParcela`). Por eso TODA medida en pixeles pensada para un
# monitor de 96 ppp pasa por `esc()`.
_ESCALA = {"f": 1.0}


def esc(px):
    """Una medida pensada a 96 ppp, en pixeles de esta pantalla."""
    return int(round(px * _ESCALA["f"]))


def geom(ancho, alto):
    """La cadena de `geometry()` para un tamano pensado a 96 ppp."""
    return f"{esc(ancho)}x{esc(alto)}"


def _factor_escala(root):
    """El factor de ampliacion de esta pantalla. 1.0 en un monitor de 96 ppp."""
    try:
        ppp = float(root.winfo_fpixels("1i"))
    except Exception:
        return 1.0
    if ppp <= 0:
        return 1.0
    # Se redondea a cuartos porque es lo que ofrecen los sistemas de verdad
    # (100 %, 125 %, 150 %...) y porque el DPI que informa la pantalla trae ruido:
    # a 96 ppp salia 1,0007 y una ventana de 1440 px acababa midiendo 1441.
    # Acotado ademas: por debajo de 1 encogeria una interfaz ya ajustada, y por
    # encima de 3 no hay pantalla que lo pida -seria un DPI mal informado-.
    return min(max(round(ppp / 96.0 * 4) / 4, 1.0), 3.0)


# =====================================================================
# ICONO DE LA APLICACION
# =====================================================================
# Sin esto, la ventana y la barra de tareas ensenan la pluma de Tk, que es lo
# primero que delata a un programa a medio terminar. Los ficheros viven junto al
# fuente (el proyecto es plano) y son OPCIONALES: si faltan, no pasa nada.
DIR_APP = os.path.dirname(os.path.abspath(__file__))
ICONO_PNG = os.path.join(DIR_APP, "icono.png")
ICONO_ICO = os.path.join(DIR_APP, "icono.ico")

_ICONOS = []          # hay que guardar la referencia: Tk no se queda con la imagen


def poner_icono(root):
    """Pone el icono en la ventana y en la barra de tareas. Silencioso si falta."""
    puesto = False
    # En Windows el icono de la BARRA DE TAREAS sale del .ico, no del PNG.
    if os.path.exists(ICONO_ICO):
        try:
            root.iconbitmap(default=ICONO_ICO)
            puesto = True
        except Exception:
            pass       # fuera de Windows, `iconbitmap` con .ico no siempre existe
    if os.path.exists(ICONO_PNG):
        try:
            img = tk.PhotoImage(file=ICONO_PNG, master=root)
            _ICONOS.append(img)                # si se recolecta, el icono se va
            root.iconphoto(True, img)          # True = tambien las ventanas hijas
            puesto = True
        except Exception:
            log.warning("no se pudo poner el icono de la aplicacion", exc_info=True)
    return puesto


# =====================================================================
# TEMA / SISTEMA DE DISENO
# =====================================================================
# `TEMA` es el diccionario VIVO: lo lee todo el programa como `TEMA["surface"]`.
# Se rellena con el modo elegido y se muta EN EL SITIO -nunca se reasigna-, para
# que siga valiendo cualquier referencia que alguien tenga ya cogida.
MODO = {"m": "claro"}

TEMAS = {}
TEMAS["claro"] = {
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
    "warn_fg": "#bc5420", "warn_bg": "#fffaf0",
    "danger_fg": "#c53030", "danger_bg": "#fff5f5",
    "muted_fg": "#616e83", "muted_bg": "#edf2f7",

    # --- sobre la cabecera verde oscura -------------------------------------
    "tab_sel_fg":   "#276749",   # texto de la pestana activa (NO es primary_dk:
                                 # ese es un FONDO y ha de ser oscuro; este se lee)
    "text_inv":     "#ffffff",   # titulos y botones de la cabecera
    "text_inv_sec": "#cbd5e1",   # lo secundario de la cabecera
    "header_hover": "#2a5540",   # boton de cabecera con el raton encima
    "sync_ok":      "#86efac",   # insignia de conexion, legible sobre el verde
    "sync_fallo":   "#fca5a5",

    # --- superficies concretas ----------------------------------------------
    "campo_bg":     "#ffffff",   # fondo de un campo que se puede escribir
    "fila_alt":     "#fcfdfe",   # franja alterna de las tablas
    "sel_bg":       "#d7ecdf",   # fila seleccionada
    "nota_bg":      "#f2f8ff",   # panel de texto de la interpretacion
    "nota_radar":   "#eef7f5",   # el mismo panel, en la ventana de radar
    "lienzo_bg":    "#d7ddd9",   # fondo del mapa cuando no hay imagen

    # --- graficas (cromo, NO series: eso va en PALETA_DATOS) -----------------
    "eje":          "#cbd5e0",   # borde de los ejes
    "traza":        "#94a3b8",   # linea vertical que sigue al raton
    "tooltip_bg":   "#111827",
    "tooltip_fg":   "#f8fafc",
    "parcela_borde": "#22d3ee",  # contorno al dibujar una parcela sobre el mapa
}

# El oscuro NO es el claro invertido: es la misma identidad -verde de campo sobre
# gris pizarra- elegida contra un fondo oscuro. Los pares de texto sobre fondo se
# comprueban con un script, no a ojo (ver `pruebas_interfaz.escenario_tema`).
TEMAS["oscuro"] = {
    "page":        "#121714",
    "surface":     "#1b211d",
    "surface_alt": "#232a25",
    "border":      "#323b35",
    "border_soft": "#28302a",
    "header_bg":   "#16261c",
    "header_sub":  "#8fae9e",
    "primary":     "#34855c",
    "primary_dk":  "#2b6f4c",
    "text":        "#e7ece9",
    "text_sec":    "#b6c2ba",
    "text_muted":  "#8d9a92",
    "ok_fg": "#7fe0a6", "ok_bg": "#16301f",
    "warn_fg": "#f0ac6e", "warn_bg": "#33261a",
    "danger_fg": "#f39191", "danger_bg": "#351e1e",
    "muted_fg": "#8d9a92", "muted_bg": "#28302a",

    "tab_sel_fg":   "#5cc08c",
    "text_inv":     "#ffffff",
    "text_inv_sec": "#a9b6ad",
    "header_hover": "#223b2b",
    "sync_ok":      "#86efac",
    "sync_fallo":   "#fca5a5",

    "campo_bg":     "#232a25",
    "fila_alt":     "#1f2621",
    "sel_bg":       "#2d4938",
    "nota_bg":      "#1a2430",
    "nota_radar":   "#172a26",
    "lienzo_bg":    "#232925",

    "eje":          "#3d4842",
    "traza":        "#6d7c74",
    "tooltip_bg":   "#e7ece9",
    "tooltip_fg":   "#121714",
    "parcela_borde": "#22d3ee",
}

TEMA = dict(TEMAS["claro"])


# =====================================================================
# PALETA DE DATOS  (esto NO es cromo: no va dentro de TEMA)
# =====================================================================
# El color de una serie identifica un INDICE; no decora la ventana. Tiene que
# sobrevivir al cambio de tema, no seguirlo, y por eso vive aparte. El paso
# oscuro no es el claro «aclarado»: son los mismos ocho tonos re-escalonados
# contra el fondo oscuro.
#
# La paleta anterior no pasaba la validacion: RVI (#0d9488) y NDMI (#3182ce)
# quedaban a ΔE 13,6 con vision NORMAL -por debajo de 15, o sea confundibles
# incluso viendo todos los colores- y GNDVI y LAI no llegaban a 3:1 de contraste
# contra el blanco. Con ocho curvas sobre la misma grafica eso no es un detalle
# estetico: es no poder decir cual es cual.
PALETA_DATOS = {
    "claro":  ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
               "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "oscuro": ["#3987e5", "#d95926", "#199e70", "#c98500",
               "#d55181", "#008300", "#9085e9", "#e66767"],
}

# Cada serie tiene su RANURA fija: el color va con la serie, no con su posicion
# en pantalla, asi que encender o apagar indices no repinta los que quedan.
# VV/VH/CR solo aparecen en la ventana de radar y por eso reaprovechan ranuras
# del grafico de la ficha, con el que nunca comparten imagen; RVI conserva la
# suya para ser del mismo color en los dos sitios.
RANURA_SERIE = {"NDVI": 0, "EVI": 1, "SAVI": 2, "GNDVI": 3,
                "LAI": 4, "MSAVI": 5, "NDMI": 6, "RVI": 7,
                "VV": 0, "VH": 1, "CR": 2}


def color_serie(nombre):
    """El color de una serie de datos, en el modo vigente."""
    return PALETA_DATOS[MODO["m"]][RANURA_SERIE.get(nombre, 0)]

FUENTES = {}


def _familia_disponible(root, candidatas):
    disp = set(tkfont.families(root))
    for c in candidatas:
        if c in disp:
            return c
    return "TkDefaultFont"


def aplicar_tema(root, escala=None, modo=None):
    """Configura ttk.Style y fuentes. Llamar una vez tras crear la ventana.

    `modo` es "claro" u "oscuro". Rellena `TEMA` mutandolo EN EL SITIO, para no
    invalidar ninguna referencia que alguien tenga ya cogida.

    `escala` fija a mano el factor de ampliacion en vez de deducirlo de la
    pantalla. Existe para las PRUEBAS: si el factor sale del DPI del monitor, la
    misma suite da resultados distintos en cada maquina. Con `escala=1.0` se
    comprueba siempre la misma interfaz, se ejecute donde se ejecute.

    matplotlib ya no se toca aqui: su tema se aplica solo, al cargarla la primera
    grafica (ver `cargar_matplotlib`)."""
    if modo in TEMAS:
        MODO["m"] = modo
    TEMA.clear()
    TEMA.update(TEMAS[MODO["m"]])
    _ESCALA["f"] = float(escala) if escala else _factor_escala(root)
    try:
        # `tk scaling` son pixeles por punto tipografico. Con el DPI real, una
        # fuente de 10 puntos mide diez puntos DE VERDAD en cualquier pantalla, en
        # vez de diez puntos «de 96 ppp» que luego el sistema estira. Los 96/72
        # son los pixeles por punto de un monitor de referencia.
        root.tk.call("tk", "scaling", _ESCALA["f"] * 96.0 / 72.0 if escala
                     else root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass       # silencio deliberado: sin escalado se ve pequena, no rota
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
    st.configure("Accent.TButton", background=TEMA["primary"], foreground=TEMA["text_inv"],
                 relief="flat", padding=(14, 8), font=FUENTES["body"])
    st.map("Accent.TButton", background=[("active", TEMA["primary_dk"]),
                                         ("pressed", TEMA["primary_dk"])])
    st.configure("Ghost.TButton", background=TEMA["header_bg"], foreground=TEMA["text_inv"],
                 relief="flat", padding=(10, 6))
    st.map("Ghost.TButton", background=[("active", TEMA["header_hover"])])

    for cls in ("TEntry", "TCombobox"):
        st.configure(cls, fieldbackground=TEMA["surface"], background=TEMA["surface"],
                     bordercolor=TEMA["border"], foreground=TEMA["text"],
                     arrowcolor=TEMA["text_muted"], padding=6, relief="flat")
        st.map(cls, bordercolor=[("focus", TEMA["primary"])],
               fieldbackground=[("readonly", TEMA["surface"])])

    st.configure("Treeview", background=TEMA["surface"], fieldbackground=TEMA["surface"],
                 foreground=TEMA["text"], rowheight=esc(30), borderwidth=0, font=FUENTES["body"])
    st.configure("Treeview.Heading", background=TEMA["surface_alt"],
                 foreground=TEMA["text_muted"], relief="flat", padding=(10, 8),
                 font=tkfont.Font(family=fam, size=10, weight="bold"))
    st.map("Treeview.Heading", background=[("active", TEMA["border_soft"])])
    st.map("Treeview", background=[("selected", TEMA["sel_bg"])],
           foreground=[("selected", TEMA["text"])])

    st.configure("TNotebook", background=TEMA["page"], borderwidth=0)
    st.configure("TNotebook.Tab", background=TEMA["page"], foreground=TEMA["text_sec"],
                 padding=(16, 9), font=FUENTES["body"])
    st.map("TNotebook.Tab", background=[("selected", TEMA["surface"])],
           foreground=[("selected", TEMA["tab_sel_fg"])])

    st.configure("Vertical.TScrollbar", background=TEMA["border"], troughcolor=TEMA["page"],
                 bordercolor=TEMA["page"], arrowcolor=TEMA["text_muted"])

    if Figure is not None:      # ya cargada: hay que volver a vestirle las graficas
        _tema_matplotlib()
    return st


def _tema_matplotlib():
    """El tema de las graficas. Lo llama `_matplotlib()` nada mas cargarla."""
    mpl.rcParams.update({
        "font.size": 9,
        "figure.facecolor": TEMA["surface"], "axes.facecolor": TEMA["surface"],
        "axes.edgecolor": TEMA["eje"], "axes.linewidth": 0.8,
        "axes.grid": True, "grid.color": TEMA["border_soft"], "grid.linewidth": 0.9,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.titlesize": 10, "axes.titleweight": "bold",
        "text.color": TEMA["text"], "axes.labelcolor": TEMA["text_sec"],
        "xtick.color": TEMA["text_muted"], "ytick.color": TEMA["text_muted"],
        "legend.frameon": False,
    })


def cargar_matplotlib():
    """Carga matplotlib y le aplica el tema. A partir de la segunda vez no cuesta.

    La llama al empezar todo metodo que dibuja. Importarla al abrir el programa
    costaba ~1,6 s de ventana en blanco por algo que puede no usarse nunca."""
    global matplotlib, Figure, FigureCanvasTkAgg, mcolors, mdates, mpl
    if Figure is not None:
        return
    import matplotlib                  # el nombre a secas: lo usan las barras de color
    matplotlib.use("TkAgg")
    # `matplotlib.colorbar` NO viene por el hecho de importar el paquete. Antes
    # llegaba de rebote, porque algun otro import lo arrastraba; se pide aparte
    # para no depender de esa casualidad.
    import matplotlib.colorbar         # noqa: F401  (se usa como matplotlib.colorbar)
    from matplotlib.figure import Figure as _Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg as _Lienzo
    import matplotlib.colors as _mcolors
    import matplotlib.dates as _mdates
    mpl, Figure, FigureCanvasTkAgg = matplotlib, _Figure, _Lienzo
    mcolors, mdates = _mcolors, _mdates
    _tema_matplotlib()


def tarjeta(parent, **kw):
    return tk.Frame(parent, bg=TEMA["surface"], highlightbackground=TEMA["border"],
                    highlightcolor=TEMA["border"], highlightthickness=1, bd=0, **kw)


def ui_seguro(widget, fn):
    """Encola `fn` en el hilo de Tk. Si la ventana ya murio, no hace nada.

    Un hilo de trabajo NO puede tocar widgets: lo que hace es pedirle al hilo
    principal que los toque, con `widget.after(0, fn)`. El problema es que `after`
    ES YA una llamada a Tcl, asi que si el usuario cierra la ventana mientras la
    descarga sigue en marcha, la propia peticion revienta con
    `RuntimeError: main thread is not in main loop`. La excepcion salta en el hilo
    de trabajo, donde nadie la recoge; no tumba el programa, pero deja un volcado
    por consola y el trabajo a medias sin avisar a nadie.

    Comprobado que la condicion exacta es esa: llamar a Tcl desde un hilo que NO es
    el suyo con el bucle de eventos parado -porque termino o porque la ventana se
    cerro-. Desde el hilo principal `after` no se queja ni con el widget destruido,
    asi que este ayudante es para los hilos. Se captura tambien `TclError` por si
    otra version de Tk prefiere lanzar eso.

    Cerrar la ventana es una respuesta legitima a «esto tarda»: que el usuario lo
    haga no debe imprimir una traza. Por eso aqui se traga, y solo aqui.

    Devuelve True si se pudo encolar y False si Tk ya no estaba, por si quien llama
    quiere dejar de trabajar en balde.
    """
    try:
        widget.after(0, fn)
        return True
    except (tk.TclError, RuntimeError):
        return False


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
