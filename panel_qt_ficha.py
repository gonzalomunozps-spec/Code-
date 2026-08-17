# -*- coding: utf-8 -*-
"""
panel_qt_ficha.py
=================

La FICHA de una parcela en la interfaz Qt: historico de indices, interpretacion,
graficas de evolucion y estadistica espacial.

Esta en su propio fichero a proposito. La ficha de Tkinter son 1.187 lineas
dentro de un modulo de 3.770, y ese tamano es la razon por la que cuesta tocarla.
Aqui cada pieza es un widget con su responsabilidad, y la ventana solo las coloca.

QUE DECIDE Y QUE NO
-------------------
Nada del dominio. Lo que la ficha DICE -diagnostico, encabezado, aprendizaje por
validaciones, tablas- lo da `vista_ficha`, que es el mismo modulo que usa la
interfaz de Tkinter. Aqui se pinta y se navega.

El mapa de indices y el de radar viven en `panel_qt_mapa`. La descarga real
contra Earth Engine NO se ha podido ejercitar donde se escribio esto (no hay
credenciales): lo probado es el camino sin credenciales y el visor con una
imagen local.
"""

import threading

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, QObject
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                               QPushButton, QTableView, QHeaderView, QFrame,
                               QPlainTextEdit, QCheckBox, QAbstractItemView,
                               QMessageBox, QSplitter, QSizePolicy)

import ui_tema as T
import almacen as DB
import vista_ficha as VF
from interpretacion_fenologica import texto_interpretacion
from bitacora import log

try:
    from gee_cliente import INDICES_ORDEN
except Exception:                       # sin earthengine-api instalado
    INDICES_ORDEN = ["NDVI", "EVI", "SAVI", "GNDVI", "LAI", "MSAVI", "NDMI"]

try:
    import calibracion_umbrales as _CALIB
except Exception:
    _CALIB = None

# Graficas: matplotlib con el lienzo de Qt. Es opcional, como el resto de piezas
# que solo sirven para pintar: sin matplotlib la ficha se abre igual, sin grafica.
try:
    import matplotlib
    matplotlib.use("QtAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    _MPL = True
except Exception:
    _MPL = False


# =====================================================================
# Tabla generica
# =====================================================================
class ModeloTabla(QAbstractTableModel):
    """Una tabla de texto ya formateado: cabeceras fijas y filas de cadenas.

    Las dos tablas de la ficha -indices y estadistica- reciben sus filas de
    `vista_ficha` ya con el formato decidido, asi que el modelo es el mismo para
    las dos y no repite ninguna regla de presentacion."""

    def __init__(self, cabeceras, alinear_derecha_desde=1):
        super().__init__()
        self._cab = list(cabeceras)
        self._filas = []
        self._desde = alinear_derecha_desde

    def poner(self, filas):
        self.beginResetModel()
        self._filas = list(filas or [])
        self.endResetModel()

    def rowCount(self, padre=QModelIndex()):
        return 0 if padre.isValid() else len(self._filas)

    def columnCount(self, padre=QModelIndex()):
        return 0 if padre.isValid() else len(self._cab)

    def headerData(self, seccion, orientacion, papel=Qt.DisplayRole):
        if orientacion == Qt.Horizontal and papel == Qt.DisplayRole:
            return self._cab[seccion]
        return None

    def data(self, ix, papel=Qt.DisplayRole):
        if not ix.isValid():
            return None
        fila = self._filas[ix.row()]
        if papel == Qt.DisplayRole:
            return fila[ix.column()] if ix.column() < len(fila) else ""
        if papel == Qt.TextAlignmentRole:
            derecha = ix.column() >= self._desde
            return int((Qt.AlignRight if derecha else Qt.AlignLeft) | Qt.AlignVCenter)
        return None


def tabla_de(modelo, alto_min=0):
    """Una QTableView con el aspecto y el comportamiento que usa toda la ficha."""
    t = QTableView()
    t.setModel(modelo)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(T.ALTO_FILA)
    t.horizontalHeader().setHighlightSections(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    if alto_min:
        t.setMinimumHeight(alto_min)
    return t


def _tarjeta(titulo):
    """Tarjeta con titulo. Devuelve (widget, layout) para meterle contenido."""
    w = QFrame()
    w.setObjectName("Tarjeta")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(T.ESP["m"], T.ESP["m"], T.ESP["m"], T.ESP["m"])
    lay.setSpacing(T.ESP["s"])
    lb = QLabel(titulo)
    lb.setObjectName("TarjetaTitulo")
    lay.addWidget(lb)
    return w, lay


# =====================================================================
# Grafica de evolucion
# =====================================================================
class Graficas(QWidget):
    """Evolucion de los indices elegidos. Sin matplotlib, lo dice y no estorba."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.ESP["s"])
        self.casillas = {}
        if not _MPL:
            aviso = QLabel("Las graficas necesitan matplotlib (pip install matplotlib).")
            aviso.setObjectName("Silencioso")
            aviso.setWordWrap(True)
            lay.addWidget(aviso)
            self.lienzo = None
            return
        fila = QHBoxLayout()
        fila.setSpacing(T.ESP["m"])
        # NDVI marcado y el resto no: es el indice de referencia, y con los siete
        # encendidos la grafica no se lee
        for k in INDICES_ORDEN:
            c = QCheckBox(k)
            c.setChecked(k == "NDVI")
            c.stateChanged.connect(self._replot)
            self.casillas[k] = c
            fila.addWidget(c)
        fila.addStretch(1)
        lay.addLayout(fila)
        # layout="constrained" y no tight_layout(): con la tarjeta estrecha, el
        # segundo no encuentra sitio para los ejes y avisa por consola en cada
        # redibujado. El constrained reparte el hueco sin quejarse.
        self.figura = Figure(figsize=(6, 2.6), dpi=100, facecolor=T.COLOR["surface"],
                             layout="constrained")
        self.lienzo = FigureCanvasQTAgg(self.figura)
        self.lienzo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Alto minimo real: por debajo de esto los ejes se quedan sin sitio, la
        # grafica no se lee y matplotlib avisa en cada redibujado. Es una medida
        # de diseno, no un parche para el arnes.
        self.lienzo.setMinimumHeight(180)
        lay.addWidget(self.lienzo, 1)
        self._regs = []

    def poner(self, regs):
        self._regs = list(regs or [])
        self._replot()

    def _replot(self, *_a):
        if not _MPL or self.lienzo is None:
            return
        self.figura.clear()
        ax = self.figura.add_subplot(111)
        ax.set_facecolor(T.COLOR["surface"])
        for lado in ("top", "right"):
            ax.spines[lado].set_visible(False)
        for lado in ("left", "bottom"):
            ax.spines[lado].set_color(T.COLOR["border"])
        ax.tick_params(colors=T.COLOR["text_muted"], labelsize=8)
        ax.grid(True, axis="y", color=T.COLOR["border_soft"], linewidth=0.8)
        ax.set_axisbelow(True)

        fechas = [r.get("fecha", "") for r in self._regs]
        pintado = False
        for k, casilla in self.casillas.items():
            if not casilla.isChecked():
                continue
            ys = [r.get(k.lower()) for r in self._regs]
            if all(v is None for v in ys):
                continue
            ax.plot(fechas, ys, marker="o", markersize=3.5, linewidth=1.6, label=k)
            pintado = True
        if pintado:
            ax.legend(frameon=False, fontsize=8, ncol=4,
                      labelcolor=T.COLOR["text_sec"])
            if len(fechas) > 8:      # con muchas fechas, una de cada N para que quepan
                paso = max(1, len(fechas) // 8)
                ax.set_xticks(fechas[::paso])
            for etiqueta in ax.get_xticklabels():
                etiqueta.set_rotation(30)
                etiqueta.set_horizontalalignment("right")
        else:
            ax.text(0.5, 0.5, "Sin datos que dibujar", ha="center", va="center",
                    color=T.COLOR["text_muted"], transform=ax.transAxes, fontsize=9)
            ax.set_xticks([])
            ax.set_yticks([])
        self.lienzo.draw_idle()


# =====================================================================
# Interpretacion
# =====================================================================
class _SenalTexto(QObject):
    listo = Signal(str)


class Interpretacion(QWidget):
    """El panel de interpretacion: selector de pasada, texto y validacion."""

    validar = Signal(str)          # veredicto: "correcto" | "corregir"
    validar_indices = Signal()
    cambio_pasada = Signal(int)
    cambio_zonas = Signal(bool)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.ESP["s"])

        # Selector de pasada: solo con el modulo de calibracion, igual que en Tk
        self.cb_pasada = None
        if _CALIB is not None:
            fila = QHBoxLayout()
            lb = QLabel("Pasada")
            lb.setObjectName("Silencioso")
            fila.addWidget(lb)
            self.cb_pasada = QComboBox()
            self.cb_pasada.currentIndexChanged.connect(self._elegir_pasada)
            fila.addWidget(self.cb_pasada, 1)
            lay.addLayout(fila)

        self.chk_zonas = QCheckBox("Analizar zonas dentro de la parcela (heterogeneidad)")
        self.chk_zonas.setChecked(True)
        self.chk_zonas.toggled.connect(self.cambio_zonas.emit)
        lay.addWidget(self.chk_zonas)

        self.texto = QPlainTextEdit()
        self.texto.setReadOnly(True)
        self.texto.setFrameShape(QFrame.NoFrame)
        self.texto.setStyleSheet(
            f"background:{T.COLOR['primary_soft']}; border-radius:{T.RADIO}px;"
            f"padding:{T.ESP['m']}px;")
        lay.addWidget(self.texto, 1)

        self.lbl_val = QLabel("¿El diagnostico es correcto?")
        self.lbl_val.setObjectName("Secundario")
        lay.addWidget(self.lbl_val)

        botones = QHBoxLayout()
        botones.setSpacing(T.ESP["s"])
        self.btn_ok = QPushButton("✓ Correcto")
        self.btn_ok.clicked.connect(lambda: self.validar.emit("correcto"))
        botones.addWidget(self.btn_ok)
        self.btn_no = QPushButton("✗ Corregir…")
        self.btn_no.clicked.connect(lambda: self.validar.emit("corregir"))
        botones.addWidget(self.btn_no)
        if _CALIB is not None:
            self.btn_idx = QPushButton("Indices…")
            self.btn_idx.clicked.connect(self.validar_indices.emit)
            botones.addWidget(self.btn_idx)
        botones.addStretch(1)
        lay.addLayout(botones)
        self._silencio = False

    def _elegir_pasada(self, i):
        if not self._silencio and i >= 0:
            self.cambio_pasada.emit(i)

    def poner_pasadas(self, etiquetas, actual):
        """Rellena el desplegable sin disparar el cambio (lo estamos pintando)."""
        if self.cb_pasada is None:
            return
        self._silencio = True
        try:
            self.cb_pasada.clear()
            self.cb_pasada.addItems(etiquetas)
            if 0 <= actual < len(etiquetas):
                self.cb_pasada.setCurrentIndex(actual)
        finally:
            self._silencio = False

    def poner_zonas(self, activo):
        self.chk_zonas.blockSignals(True)
        self.chk_zonas.setChecked(bool(activo))
        self.chk_zonas.blockSignals(False)

    def poner_texto(self, texto):
        self.texto.setPlainText(texto)

    def poner_validacion(self, estado):
        """`estado` es lo que devuelve `vista_ficha.texto_validacion`."""
        papeles = {"ok": T.COLOR["ok_fg"], "mal": T.COLOR["danger_fg"],
                   "neutro": T.COLOR["text_sec"]}
        self.lbl_val.setText(estado["texto"])
        self.lbl_val.setStyleSheet(
            f"color:{papeles.get(estado['papel'], T.COLOR['text_sec'])};"
            f"font-size:{T.TAMANO['small']}pt; background:transparent;")


# =====================================================================
# La ficha
# =====================================================================
class Ficha(QWidget):
    """Ficha completa de una parcela y campana."""

    volver = Signal()
    cambiar_campana = Signal(str)

    def __init__(self, nombre, campana, campanas=None):
        super().__init__()
        self.nombre, self.campana = nombre, campana
        self._pasada_sel = None
        self._val_ctx = None
        self._idx_ctx = None
        self._construir(campanas or [campana])
        self.refrescar()

    # ---- construccion ----
    def _construir(self, campanas):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        raiz.addWidget(self._cabecera(campanas))

        cuerpo = QWidget()
        lay = QVBoxLayout(cuerpo)
        lay.setContentsMargins(T.ESP["l"], T.ESP["m"], T.ESP["l"], T.ESP["l"])
        lay.setSpacing(T.ESP["m"])

        # Arriba: historico e interpretacion, con divisor movible. En la version Tk
        # las alturas eran fijas y si el contenido crecia se quedaba sin dibujar;
        # con un splitter el usuario reparte el sitio como le convenga.
        arriba = QSplitter(Qt.Horizontal)
        c_hist, l_hist = _tarjeta("Historico de indices (medias Copernicus)")
        self.modelo_idx = ModeloTabla(["FECHA"] + INDICES_ORDEN)
        l_hist.addWidget(tabla_de(self.modelo_idx, alto_min=200))
        arriba.addWidget(c_hist)

        c_int, l_int = _tarjeta("Interpretacion automatica")
        self.interp = Interpretacion()
        self.interp.cambio_pasada.connect(self._elegir_pasada)
        self.interp.cambio_zonas.connect(self._cambiar_zonas)
        self.interp.validar.connect(self._validar)
        self.interp.validar_indices.connect(self._validar_indices)
        l_int.addWidget(self.interp, 1)
        arriba.addWidget(c_int)
        arriba.setSizes([620, 520])
        lay.addWidget(arriba, 3)

        c_map, l_map = _tarjeta("Mapa de la parcela")
        from panel_qt_mapa import Mapa
        self.mapa = Mapa(self.nombre, self.campana)
        l_map.addWidget(self.mapa, 1)
        arriba2 = QSplitter(Qt.Horizontal)
        arriba2.addWidget(c_map)
        c_rad, l_rad = _tarjeta("Radar (Sentinel-1)")
        self.radar = Mapa(self.nombre, self.campana, radar=True)
        l_rad.addWidget(self.radar, 1)
        arriba2.addWidget(c_rad)
        arriba2.setSizes([620, 520])
        lay.addWidget(arriba2, 3)

        c_graf, l_graf = _tarjeta("Evolucion de los indices")
        self.graficas = Graficas()
        l_graf.addWidget(self.graficas, 1)
        lay.addWidget(c_graf, 2)

        c_cua, l_cua = _tarjeta("Cuaderno de campo (intervenciones)")
        from panel_qt_dialogos import Cuaderno
        self.cuaderno = Cuaderno(self.nombre, self.campana)
        # una intervencion nueva puede cambiar el diagnostico (el motor mira los
        # eventos cercanos a la pasada), asi que se vuelve a interpretar
        self.cuaderno.cambiado.connect(self.refrescar)
        l_cua.addWidget(self.cuaderno, 1)
        lay.addWidget(c_cua, 2)

        c_est, l_est = _tarjeta("Estadistica dentro de la parcela (distribucion del NDVI)")
        self.lbl_est = QLabel("")
        self.lbl_est.setObjectName("Silencioso")
        self.lbl_est.setWordWrap(True)
        l_est.addWidget(self.lbl_est)
        self.modelo_est = ModeloTabla([c[1] for c in VF.COLS_ESTADISTICA])
        l_est.addWidget(tabla_de(self.modelo_est, alto_min=160))
        lay.addWidget(c_est, 2)

        raiz.addWidget(cuerpo, 1)

    def _cabecera(self, campanas):
        w = QFrame()
        w.setObjectName("Cabecera")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(T.ESP["m"], T.ESP["m"], T.ESP["l"], T.ESP["m"])
        lay.setSpacing(T.ESP["s"])

        atras = QPushButton("←  Volver")
        atras.setObjectName("Fantasma")
        atras.clicked.connect(self.volver.emit)
        lay.addWidget(atras)

        titulo = QLabel(self.nombre.replace("_", " "))
        titulo.setObjectName("CabeceraTitulo")
        lay.addWidget(titulo)

        lb = QLabel("Campana")
        lb.setObjectName("CabeceraSub")
        lay.addWidget(lb)
        self.cb_campana = QComboBox()
        self.cb_campana.addItems(campanas)
        self.cb_campana.setCurrentText(self.campana)
        self.cb_campana.currentTextChanged.connect(self._cambiar_campana)
        lay.addWidget(self.cb_campana)
        lay.addStretch(1)
        return w

    # ---- datos ----
    def _serie(self):
        return sorted(DB.pasadas(self.nombre, self.campana),
                      key=lambda r: r.get("fecha", ""))

    def refrescar(self):
        regs = self._serie()
        self.modelo_idx.poner(VF.filas_indices(regs, INDICES_ORDEN))
        self.graficas.poner(regs)
        filas_est = VF.filas_estadistica(regs)
        self.modelo_est.poner(filas_est)
        self.lbl_est.setText(VF.PIE_ESTADISTICA if filas_est else VF.PIE_SIN_ESTADISTICA)
        if hasattr(self, "cuaderno"):
            self.cuaderno.refrescar()
        if hasattr(self, "mapa"):
            self.mapa.poner_fechas([r.get("fecha", "") for r in regs if r.get("fecha")])
            self.radar.poner_fechas([r.get("fecha", "") for r in
                                     sorted(DB.radar(self.nombre, self.campana),
                                            key=lambda x: x.get("fecha", ""))
                                     if r.get("fecha")])
        self._pintar_interp(regs)

    def _pintar_interp(self, regs):
        if not regs:
            self.interp.poner_texto("Sin datos. Pulsa «Sincronizar Copernicus» en la "
                                    "interfaz anterior.")
            self.interp.poner_validacion({"texto": "Sin pasada que validar.",
                                          "papel": "neutro"})
            self.interp.poner_pasadas([], -1)
            return
        ctx = VF.contexto(self.nombre, self.campana, regs, elegido=self._pasada_sel,
                          calib=_CALIB, indices=INDICES_ORDEN)
        if ctx is None:
            return
        self._val_ctx, self._idx_ctx = ctx["val_ctx"], ctx["idx_ctx"]
        validadas = DB.pasadas_validadas(self.nombre, self.campana)
        self.interp.poner_pasadas(
            [("✓ " if r.get("fecha") in validadas else "     ") + r.get("fecha", "")
             for r in regs], ctx["idx"])
        self.interp.poner_zonas(ctx["hetero_on"])
        self.interp.poner_validacion(
            VF.texto_validacion(self.nombre, self.campana, ctx["val_ctx"].get("fecha")))

        if ctx["tipo"] == "BARBECHO":
            return self.interp.poner_texto(ctx["encabezado"] + ctx["diag"]["motivo"])
        if ctx["cacheado"]:
            return self.interp.poner_texto(ctx["encabezado"] + ctx["cacheado"])
        self.interp.poner_texto(ctx["encabezado"] + "Generando interpretacion…")
        self._pedir_interpretacion(ctx)

    def _pedir_interpretacion(self, ctx):
        """La interpretacion larga puede tardar (va a ChatGPT si hay clave).

        Se pide en un hilo y vuelve por senal. La senal se conecta a un metodo de
        ESTE widget: si el usuario navega y el widget muere, Qt desconecta y el
        resultado se descarta solo, sin el «invalid command name» que habia que
        vigilar a mano en Tk."""
        senal = _SenalTexto()
        senal.listo.connect(lambda texto, e=ctx["encabezado"]:
                            self.interp.poner_texto(e + texto))
        fecha = ctx["actual"].get("fecha")

        def worker():
            try:
                texto, _d = texto_interpretacion(
                    ctx["tipo"], ctx["sub"], ctx["serie_hasta"], fecha,
                    eventos_cerca=ctx["eventos_cerca"], spec=ctx["spec"],
                    aprendizaje=ctx["aprendizaje"])
                DB.set_interpretacion(self.nombre, self.campana, fecha, texto)
                senal.listo.emit(texto)
            except Exception:
                log.warning("interpretacion no disponible para %s %s",
                            self.nombre, fecha, exc_info=True)
                senal.listo.emit("No se pudo generar la interpretacion larga; "
                                 "el diagnostico de arriba si es valido.")
        self._hilo = threading.Thread(target=worker, daemon=True)
        self._senal_interp = senal          # se guarda: si muere, se pierde la senal
        self._hilo.start()

    # ---- interaccion ----
    def _elegir_pasada(self, i):
        self._pasada_sel = i
        self._pintar_interp(self._serie())

    def _cambiar_campana(self, camp):
        if camp != self.campana:
            self.cambiar_campana.emit(camp)

    def _cambiar_zonas(self, activo):
        """Guarda la eleccion con la parcela y vuelve a interpretar al momento."""
        ficha = DB.ficha(self.nombre) or {}
        ficha["heterogeneidad"] = bool(activo)
        DB.guardar_ficha(self.nombre, ficha)
        self.refrescar()

    def _validar(self, veredicto):
        ctx = self._val_ctx
        if not ctx or not ctx.get("fecha"):
            return QMessageBox.information(self, "Validar",
                                           "No hay ninguna pasada que validar.")
        if veredicto == "correcto":
            VF.guardar_validacion(self.nombre, self.campana, ctx, "correcto")
            self.refrescar()
            return
        from panel_qt_dialogos import DialogoCorreccion
        dlg = DialogoCorreccion(self, self.nombre, dict(ctx, campana=self.campana))
        if dlg.exec():
            self.refrescar()

    def _validar_indices(self):
        if _CALIB is None or not self._idx_ctx:
            return QMessageBox.information(
                self, "Validar indices",
                "No hay lecturas que validar en esta pasada.")
        from panel_qt_dialogos import DialogoValidacionIndices
        dlg = DialogoValidacionIndices(self, self.nombre, self.campana, self._idx_ctx)
        if dlg.exec():
            self.refrescar()
