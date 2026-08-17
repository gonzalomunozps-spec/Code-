# -*- coding: utf-8 -*-
"""
panel_qt_mapa.py
================

El mapa de indices y el de radar en la interfaz Qt: elegir dia e indice, ver el
PNG con zoom y desplazamiento, y la leyenda de color.

QUE ES ESTE MAPA Y QUE NO
-------------------------
No es un mapa interactivo de teselas: es la IMAGEN que Earth Engine devuelve
recortada a la parcela, con el indice pintado encima del color natural. Por eso
un visor de imagen con zoom es exactamente lo que hace falta, y por eso esta
parte no depende de `tkintermapview` (que es de Tk y no tiene equivalente
directo en Qt). Lo que si dependia de esa libreria era DIBUJAR una parcela a mano
en el alta, que es otra pantalla.

DEGRADACION
-----------
Sin `earthengine-api` no hay de donde bajar la imagen, y sin `Pillow` no se puede
componer. En los dos casos el widget se monta igual y lo dice, en vez de dejar un
hueco gris sin explicacion: es el mismo criterio que ya usaba la version Tk.

AVISO HONESTO: la descarga real contra Earth Engine no se ha podido ejercitar en
el entorno donde se escribio esto (no hay credenciales). Lo que si esta probado
es el camino sin credenciales y el visor con una imagen local.
"""

import os

from PySide6.QtCore import Qt, QObject, Signal, QRectF
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                               QPushButton, QGraphicsView, QGraphicsScene, QFrame,
                               QSizePolicy)

import ui_tema as T
import almacen as DB
import mapas_cache
from bitacora import log

try:
    import gee_cliente as GEE
    _HAY_GEE = GEE.hay_ee()
except Exception:                       # sin earthengine-api instalado
    GEE = None
    _HAY_GEE = False

INDICES = getattr(GEE, "INDICES", {}) if GEE else {}
INDICES_ORDEN = getattr(GEE, "INDICES_ORDEN",
                        ["NDVI", "EVI", "SAVI", "GNDVI", "LAI", "MSAVI", "NDMI"]) if GEE \
    else ["NDVI", "EVI", "SAVI", "GNDVI", "LAI", "MSAVI", "NDMI"]
RADAR_VIS = getattr(GEE, "RADAR_VIS", {}) if GEE else {}

RESOLUCION_M = 10           # metros por pixel que se piden a Earth Engine
ZOOM_MIN, ZOOM_MAX = 0.2, 8.0


class Visor(QGraphicsView):
    """Imagen con zoom a la rueda y arrastre con el raton.

    `QGraphicsView` y no un QLabel con la imagen escalada: asi el zoom no
    reescala el PNG en cada paso -que emborrona y va lento- sino que transforma
    la vista, y el arrastre sale gratis."""

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(Qt.transparent)
        self.setStyleSheet(f"background:{T.COLOR['surface_alt']};"
                           f"border-radius:{T.RADIO}px;")
        self.setMinimumHeight(240)
        self._item = None
        self._zoom = 1.0

    def poner(self, ruta):
        """Carga un PNG. Devuelve False si no se pudo (fichero roto o ausente)."""
        self.scene().clear()
        self._item = None
        pix = QPixmap(ruta) if ruta and os.path.exists(ruta) else QPixmap()
        if pix.isNull():
            return False
        self._item = self.scene().addPixmap(pix)
        self.setSceneRect(QRectF(pix.rect()))
        self.ajustar()
        return True

    def limpiar(self):
        self.scene().clear()
        self._item = None

    def ajustar(self):
        """Encaja la imagen entera. Es el estado al que se vuelve con «Ajustar»."""
        if self._item is not None:
            self.resetTransform()
            self.fitInView(self._item, Qt.KeepAspectRatio)
            self._zoom = 1.0

    def zoom(self, factor):
        nuevo = self._zoom * factor
        if not (ZOOM_MIN <= nuevo <= ZOOM_MAX):
            return                       # topes: ni un punto gigante ni una mota
        self._zoom = nuevo
        self.scale(factor, factor)

    def wheelEvent(self, ev):
        if self._item is None:
            return super().wheelEvent(ev)
        self.zoom(1.15 if ev.angleDelta().y() > 0 else 1 / 1.15)


class Leyenda(QLabel):
    """Barra de color del indice, con sus extremos. Sale de `gee_cliente.INDICES`,
    que es la misma tabla que usa la descarga: leyenda y mapa no pueden discrepar."""

    def poner(self, idx):
        vis = INDICES.get(idx) or RADAR_VIS.get(idx)
        if not vis:
            self.setText("")
            return
        lo, hi = vis["rango"]
        paleta = ", ".join(f"#{c}" for c in vis["paleta"])
        self.setText(f"{lo:g}   ⟶   {hi:g}")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(22)
        self.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {paleta.split(', ')[0]}, stop:1 {paleta.split(', ')[-1]});"
            f"color:{T.COLOR['text_invert']}; border-radius:{T.RADIO}px;"
            f"font-size:{T.TAMANO['small']}pt;")


class _Aviso(QObject):
    listo = Signal(str, bool)          # (mensaje, hubo_imagen)


class Mapa(QWidget):
    """Mapa de un indice (o de un parametro de radar) para un dia."""

    def __init__(self, nombre, campana, radar=False):
        super().__init__()
        self.nombre, self.campana, self.radar = nombre, campana, radar
        self._fechas = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.ESP["s"])

        barra = QHBoxLayout()
        barra.setSpacing(T.ESP["s"])
        lb = QLabel("Dia")
        lb.setObjectName("Silencioso")
        barra.addWidget(lb)
        self.cb_dia = QComboBox()
        self.cb_dia.currentIndexChanged.connect(lambda _i: self.pintar())
        barra.addWidget(self.cb_dia, 1)
        lb2 = QLabel("Parametro" if radar else "Indice")
        lb2.setObjectName("Silencioso")
        barra.addWidget(lb2)
        self.cb_idx = QComboBox()
        self.cb_idx.addItems(list(RADAR_VIS) if radar else INDICES_ORDEN)
        self.cb_idx.currentTextChanged.connect(lambda _t: self.pintar())
        barra.addWidget(self.cb_idx)
        for txt, fn in (("＋", lambda: self.visor.zoom(1.25)),
                        ("－", lambda: self.visor.zoom(1 / 1.25)),
                        ("Ajustar", lambda: self.visor.ajustar())):
            b = QPushButton(txt)
            b.setMaximumWidth(90 if txt == "Ajustar" else 40)
            b.clicked.connect(fn)
            barra.addWidget(b)
        lay.addLayout(barra)

        self.visor = Visor()
        self.visor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.visor, 1)
        self.leyenda = Leyenda()
        lay.addWidget(self.leyenda)
        self.estado = QLabel("")
        self.estado.setObjectName("Silencioso")
        self.estado.setWordWrap(True)
        lay.addWidget(self.estado)
        self._aviso = _Aviso()
        self._aviso.listo.connect(self._llegó)

    # ---- datos ----
    def poner_fechas(self, fechas):
        """Las fechas que se pueden pedir. La ultima queda elegida, como en Tk."""
        self._fechas = list(fechas or [])
        self.cb_dia.blockSignals(True)
        self.cb_dia.clear()
        self.cb_dia.addItems(self._fechas)
        if self._fechas:
            self.cb_dia.setCurrentIndex(len(self._fechas) - 1)
        self.cb_dia.blockSignals(False)
        self.pintar()

    def _ruta(self, iso, idx):
        return (mapas_cache.ruta_cache_radar(self.nombre, idx, iso, RESOLUCION_M)
                if self.radar else
                mapas_cache.ruta_cache_mapa(self.nombre, idx, iso, RESOLUCION_M))

    def pintar(self):
        """Ensena el mapa del dia y el indice elegidos.

        Si esta en la cache, se ve al momento. Si no, se pide a Earth Engine en un
        hilo; y si no hay Earth Engine, se dice y no se deja un hueco mudo."""
        idx = self.cb_idx.currentText()
        self.leyenda.poner(idx)
        iso = self.cb_dia.currentText()
        if not iso:
            self.visor.limpiar()
            self.estado.setText("Esta parcela todavia no tiene pasadas con imagen.")
            return
        ruta = self._ruta(iso, idx)
        if self.visor.poner(ruta):
            self.estado.setText(f"{idx} · {iso}")
            return
        if not _HAY_GEE:
            self.visor.limpiar()
            self.estado.setText(
                "Ese mapa no esta descargado y no hay conexion con Earth Engine "
                "(falta earthengine-api o las credenciales). Los datos e indices de "
                "la ficha si son validos: el mapa es un extra.")
            return
        self.estado.setText(f"Descargando {idx} del {iso}…")
        self._descargar(iso, idx, ruta)

    def _descargar(self, iso, idx, ruta):
        import threading
        ficha = DB.ficha(self.nombre) or {}
        coords = ficha.get("coordenadas")
        if not coords:
            self.estado.setText("Esta parcela no tiene geometria guardada.")
            return

        def worker():
            try:
                if self.radar:
                    GEE.descargar_mapa_radar(coords, iso, idx, RESOLUCION_M, ruta)
                else:
                    GEE.descargar_mapa_indice(coords, iso, idx, RESOLUCION_M, ruta)
                self._aviso.listo.emit(f"{idx} · {iso}", True)
            except Exception as e:
                log.warning("mapa %s %s no disponible", idx, iso, exc_info=True)
                self._aviso.listo.emit(f"No se pudo descargar ese mapa: {e}", False)
        threading.Thread(target=worker, daemon=True).start()

    def _llegó(self, mensaje, hubo):
        """Vuelta del hilo. Si el usuario ya cambio de dia, no se pisa lo que ve."""
        self.estado.setText(mensaje)
        if hubo:
            self.visor.poner(self._ruta(self.cb_dia.currentText(),
                                        self.cb_idx.currentText()))
