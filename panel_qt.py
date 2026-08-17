# -*- coding: utf-8 -*-
"""
panel_qt.py
===========

Interfaz Qt (PySide6) del gestor de parcelas. Convive con la de Tkinter mientras
dura el porte: las dos hablan con la MISMA logica (`almacen`,
`interpretacion_fenologica`, `vista_parcelas`...), asi que no pueden dar
resultados distintos.

    python panel_qt.py

POR QUE PySide6 Y NO PyQt
-------------------------
Misma API de Qt 6, pero PySide6 es LGPL y PyQt es GPL o licencia comercial. Un
programa que se va a distribuir a agricultores no deberia arrastrar una GPL sin
que sea una decision consciente; con PySide6 no hay que tomarla. Si algun dia se
prefiere PyQt6, los cambios son los `import` y poco mas: no se usa nada
especifico de PySide.

QUE HAY AQUI Y QUE NO (estado del porte)
----------------------------------------
Hecho:   ventana principal, cabecera, barra de herramientas, LISTA de parcelas
         con busqueda, orden, resumen por estado y menu contextual, y la FICHA
         de parcela (historico, interpretacion, graficas y estadistica) en
         `panel_qt_ficha.py`.
Pendiente: el mapa para DIBUJAR una parcela a mano en el alta, que en Tkinter
         venia de `tkintermapview` (ver panel_qt_alta).
Mientras tanto, `panel_gestion_parcelas.py` (Tkinter) sigue siendo la interfaz
completa y no se ha tocado.

REGLAS DE ESTA INTERFAZ
-----------------------
  - Aqui NO se decide nada del dominio. Lo que sale en la lista, en que orden y
    con que estado lo dice `vista_parcelas`, que es puro y se prueba sin pantalla.
  - El aspecto vive entero en `ui_tema`. Este fichero no escribe ni un color.
  - Nada de trabajo lento en el hilo de la interfaz: va en `QThreadPool` y vuelve
    por senal, que es el equivalente Qt del `widget.after(...)` de Tk.
"""

import sys

from PySide6.QtCore import (Qt, QAbstractTableModel, QModelIndex, Signal, QObject,
                            QRunnable)
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QLineEdit, QComboBox,
                               QPushButton, QTableView, QHeaderView, QFrame,
                               QMessageBox, QMenu, QAbstractItemView, QSizePolicy,
                               QStackedWidget)

import ui_tema as T
import almacen as DB
import vista_parcelas as VP
from interpretacion_fenologica import evaluar_parcela
from campanas import campana_actual
from panel_qt_ficha import Ficha
from bitacora import log


# =====================================================================
# Piezas de composicion
# =====================================================================
def tarjeta(margen=T.ESP["l"], espaciado=T.ESP["m"]):
    """Un contenedor con el aspecto de tarjeta y su layout vertical ya puesto.

    Devuelve (widget, layout). Todas las pantallas se componen de tarjetas: es lo
    que hace que dos pantallas distintas se parezcan sin ponerse de acuerdo."""
    w = QFrame()
    w.setObjectName("Tarjeta")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(margen, margen, margen, margen)
    lay.setSpacing(espaciado)
    return w, lay


def etiqueta(texto, papel=""):
    """Etiqueta con uno de los papeles del sistema de diseno (o el normal)."""
    lb = QLabel(texto)
    if papel:
        lb.setObjectName(papel)
    return lb


class Insignia(QLabel):
    """Contador de un estado: «3 Revisar» con el color de ese estado.

    Es la unica pieza que traduce un estado a color en esta interfaz, y lo hace
    pidiendoselo a `ui_tema.color_estado` por CLAVE, no buscando la palabra dentro
    de un texto."""

    def __init__(self, clave, n):
        super().__init__(f"{n}  {clave}")
        fg, bg = T.color_estado(clave)
        self.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:{T.RADIO}px;"
            f"padding:{T.ESP['xs']}px {T.ESP['m']}px; font-size:{T.TAMANO['small']}pt;")
        self.setAlignment(Qt.AlignCenter)


# =====================================================================
# Trabajo en segundo plano
# =====================================================================
class _Senales(QObject):
    listo = Signal(object)
    error = Signal(str)


class Tarea(QRunnable):
    """Ejecuta algo lento fuera del hilo de la interfaz y vuelve por senal.

    Equivale al `threading.Thread` + `widget.after(...)` de la version Tk, pero
    sin el riesgo de tocar un widget ya destruido: si la ventana se cierra, la
    conexion muere con ella y la senal no llega a ningun sitio."""

    def __init__(self, fn, *a, **k):
        super().__init__()
        self.fn, self.a, self.k = fn, a, k
        self.senales = _Senales()

    def run(self):
        try:
            self.senales.listo.emit(self.fn(*self.a, **self.k))
        except Exception as e:                       # noqa: la interfaz no puede caerse
            log.warning("tarea en segundo plano fallida", exc_info=True)
            self.senales.error.emit(str(e))


# =====================================================================
# Modelo de la lista
# =====================================================================
class ModeloParcelas(QAbstractTableModel):
    """Las filas que da `vista_parcelas`, servidas a la tabla.

    Un modelo y no un relleno de celdas a mano: Qt pinta solo lo visible, asi que
    una explotacion con cientos de parcelas se desplaza igual de fluida. El
    contenido de cada celda ya viene decidido; aqui solo se elige alineacion y
    color."""

    COLUMNAS = [("nombre", "Parcela", Qt.AlignLeft),
                ("cultivo", "Cultivo", Qt.AlignLeft),
                ("superficie", "Superficie", Qt.AlignRight),
                ("propietario", "Propietario", Qt.AlignLeft),
                ("estado", "Estado", Qt.AlignLeft)]

    def __init__(self):
        super().__init__()
        self._filas = []

    def poner(self, filas):
        self.beginResetModel()
        self._filas = list(filas or [])
        self.endResetModel()

    def fila(self, i):
        return self._filas[i] if 0 <= i < len(self._filas) else None

    def rowCount(self, padre=QModelIndex()):
        return 0 if padre.isValid() else len(self._filas)

    def columnCount(self, padre=QModelIndex()):
        return 0 if padre.isValid() else len(self.COLUMNAS)

    def headerData(self, seccion, orientacion, papel=Qt.DisplayRole):
        if orientacion == Qt.Horizontal and papel == Qt.DisplayRole:
            return self.COLUMNAS[seccion][1]
        return None

    def data(self, indice, papel=Qt.DisplayRole):
        if not indice.isValid():
            return None
        r = self._filas[indice.row()]
        clave, _titulo, alineacion = self.COLUMNAS[indice.column()]
        if papel == Qt.DisplayRole:
            # el punto de color solo donde hay juicio; en "N.A." o "sin asignar"
            # pintarlo seria decir que el sistema opina algo, y no opina
            if clave == "estado" and r["semaforo"]:
                return f"●  {r['estado']}"
            return r[clave]
        if papel == Qt.TextAlignmentRole:
            return int(alineacion | Qt.AlignVCenter)
        if papel == Qt.ForegroundRole and clave == "estado":
            return QColor(T.color_estado(r["_clave"])[0])
        if papel == Qt.FontRole and clave == "nombre":
            f = QFont()
            f.setWeight(QFont.DemiBold)
            return f
        return None


# =====================================================================
# Pantalla: lista de parcelas
# =====================================================================
class PantallaLista(QWidget):
    """La lista de parcelas, con su barra de busqueda, orden y campana."""

    abrir_ficha = Signal(str)

    def __init__(self, campana=None):
        super().__init__()
        self.campana = campana or campana_actual()
        self._construir()
        self.refrescar()

    # ---- construccion ----
    def _construir(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(T.ESP["l"], T.ESP["m"], T.ESP["l"], T.ESP["l"])
        raiz.setSpacing(T.ESP["m"])
        raiz.addWidget(self._barra())

        caja, lay = tarjeta(margen=0, espaciado=0)
        self.tabla = QTableView()
        self.modelo = ModeloParcelas()
        self.tabla.setModel(self.modelo)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(T.ALTO_FILA)
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self._menu_contextual)
        self.tabla.doubleClicked.connect(lambda ix: self._abrir(ix.row()))
        cab = self.tabla.horizontalHeader()
        cab.setHighlightSections(False)
        for i in range(self.modelo.columnCount()):
            # la columna del propietario se come el espacio sobrante: es la que
            # mas varia de largo y la que menos molesta si queda holgada
            cab.setSectionResizeMode(
                i, QHeaderView.Stretch if i == 3 else QHeaderView.ResizeToContents)
        lay.addWidget(self.tabla)
        raiz.addWidget(caja, 1)

        self.pie = etiqueta("", "Silencioso")
        raiz.addWidget(self.pie)

    def _barra(self):
        w = QFrame()
        w.setObjectName("Barra")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(T.ESP["m"], T.ESP["s"], T.ESP["m"], T.ESP["s"])
        lay.setSpacing(T.ESP["s"])

        lay.addWidget(etiqueta("Campana"))
        self.cb_campana = QComboBox()
        self.cb_campana.addItems(self._campanas())
        self.cb_campana.setCurrentText(self.campana)
        self.cb_campana.currentTextChanged.connect(self._cambiar_campana)
        lay.addWidget(self.cb_campana)

        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar por parcela o propietario…")
        self.buscar.setClearButtonEnabled(True)
        self.buscar.textChanged.connect(self.refrescar)
        self.buscar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay.addWidget(self.buscar, 1)

        lay.addWidget(etiqueta("Ordenar por"))
        self.cb_orden = QComboBox()
        self.cb_orden.addItems(list(VP.ORDENES))
        self.cb_orden.currentTextChanged.connect(self.refrescar)
        lay.addWidget(self.cb_orden)

        nueva = QPushButton("Nueva parcela")
        nueva.setObjectName("Primario")
        nueva.clicked.connect(self.alta_parcela)
        lay.addWidget(nueva)

        self.insignias = QHBoxLayout()
        self.insignias.setSpacing(T.ESP["xs"])
        lay.addLayout(self.insignias)
        return w

    def _campanas(self):
        c = {campana_actual()} | set(DB.campanas_con_datos())
        return sorted(c, reverse=True)

    # ---- datos ----
    def _cambiar_campana(self, texto):
        self.campana = texto
        self.refrescar()

    def refrescar(self):
        """Relee la lista. Es barato: una consulta de parcelas y otra de pasadas."""
        filas = VP.filas(DB.parcelas_dict(), DB.pasadas_de_campana(self.campana),
                         self.campana, evaluar_parcela,
                         texto=self.buscar.text(), orden=self.cb_orden.currentText())
        self.modelo.poner(filas)
        self._pintar_resumen(VP.resumen(filas))
        n = len(filas)
        self.pie.setText(f"{n} parcela{'s' if n != 1 else ''} en {self.campana}"
                         + ("  ·  doble clic para abrir la ficha" if n else ""))

    def _pintar_resumen(self, cuenta):
        """Insignias con cuantas parcelas hay en cada estado, de peor a mejor.

        Solo se ensenan los estados con juicio y que EXISTAN: una insignia con un
        cero es ruido que hay que leer para descartarlo."""
        while self.insignias.count():
            it = self.insignias.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for clave in ("Revisar", "Vigilar", "OK"):
            if cuenta.get(clave):
                self.insignias.addWidget(Insignia(clave, cuenta[clave]))

    # ---- interaccion ----
    def _seleccionada(self):
        ix = self.tabla.selectionModel().selectedRows()
        return self.modelo.fila(ix[0].row()) if ix else None

    def _abrir(self, fila):
        r = self.modelo.fila(fila)
        if r:
            self.abrir_ficha.emit(r["id"])

    def menu_de_fila(self, fila):
        """El menu contextual de esa fila, SIN mostrarlo.

        Construirlo y mostrarlo van aparte a proposito: `QMenu.exec` abre su
        propio bucle de eventos y se queda ahi hasta que alguien lo cierra, asi
        que un arnes que lo llamara se colgaria. Lo que tiene logica -que opciones
        hay y sobre que parcela actuan- se puede comprobar con esto."""
        r = self.modelo.fila(fila)
        if r is None:
            return None
        menu = QMenu(self)
        abrir = QAction("Abrir ficha", self)
        abrir.triggered.connect(lambda: self._abrir(fila))
        editar = QAction("Editar parcela…", self)
        editar.triggered.connect(self._editar)
        borrar = QAction("Eliminar parcela…", self)
        borrar.triggered.connect(self._eliminar)
        menu.addAction(abrir)
        menu.addAction(editar)
        menu.addSeparator()
        menu.addAction(borrar)
        return menu

    def alta_parcela(self, editar=None):
        """Alta de una parcela nueva, o edicion de la seleccionada."""
        from panel_qt_alta import DialogoParcela
        dlg = DialogoParcela(self, self.campana, editar=editar)
        if dlg.exec():
            self.cb_campana.blockSignals(True)
            self.cb_campana.clear()
            self.cb_campana.addItems(self._campanas())
            self.cb_campana.setCurrentText(self.campana)
            self.cb_campana.blockSignals(False)
            self.refrescar()

    def _editar(self):
        r = self._seleccionada()
        if r:
            self.alta_parcela(editar=r["id"])

    def _menu_contextual(self, punto):
        ix = self.tabla.indexAt(punto)
        if not ix.isValid():
            return                      # clic en el hueco de debajo de las filas
        self.tabla.selectRow(ix.row())
        menu = self.menu_de_fila(ix.row())
        if menu is not None:
            menu.exec(self.tabla.viewport().mapToGlobal(punto))

    def _eliminar(self):
        r = self._seleccionada()
        if not r:
            return
        resp = QMessageBox.question(
            self, "Eliminar parcela",
            f"¿Eliminar «{r['nombre']}» y todo su historico?\n\n"
            "Se borran sus pasadas, eventos y validaciones. No se puede deshacer.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resp == QMessageBox.Yes:
            DB.eliminar_parcela(r["id"])   # borrado en cascada, como en la version Tk
            self.refrescar()


# =====================================================================
# Ventana principal
# =====================================================================
class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gestor de parcelas")
        self.resize(1280, 800)

        central = QWidget()
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        raiz.addWidget(self._cabecera())

        # La lista y la ficha son dos VISTAS de la misma ventana, apiladas.
        self.vistas = QStackedWidget()
        self.lista = PantallaLista()
        self.lista.abrir_ficha.connect(self._abrir_ficha)
        self.vistas.addWidget(self.lista)
        self.ficha = None
        raiz.addWidget(self.vistas, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage(f"Datos en {DB.RUTA_DB}")

    def _cabecera(self):
        w = QFrame()
        w.setObjectName("Cabecera")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(T.ESP["l"], T.ESP["m"], T.ESP["l"], T.ESP["m"])
        lay.setSpacing(T.ESP["s"])

        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(etiqueta("Gestor de parcelas", "CabeceraTitulo"))
        col.addWidget(etiqueta("Seguimiento por satelite de cultivos extensivos y lenosos",
                               "CabeceraSub"))
        lay.addLayout(col)
        lay.addStretch(1)

        self.btn_actualizar = QPushButton("Actualizar")
        self.btn_actualizar.setObjectName("Fantasma")
        self.btn_actualizar.clicked.connect(lambda: self.lista.refrescar())
        lay.addWidget(self.btn_actualizar)
        return w

    def _abrir_ficha(self, nombre):
        """Sustituye la lista por la ficha de esa parcela.

        Se apila en un QStackedWidget en vez de abrir una ventana nueva: la ficha
        es una VISTA del mismo trabajo, no una tarea aparte, y una ventana suelta
        obliga a colocarla y a cerrarla."""
        campanas = [self.lista.cb_campana.itemText(i)
                    for i in range(self.lista.cb_campana.count())]
        ficha = Ficha(nombre, self.lista.campana, campanas)
        ficha.volver.connect(self._mostrar_lista)
        ficha.cambiar_campana.connect(
            lambda c, n=nombre: (self.lista.cb_campana.setCurrentText(c),
                                 self._cerrar_ficha(), self._abrir_ficha(n)))
        self._cerrar_ficha()
        self.ficha = ficha
        self.vistas.addWidget(ficha)
        self.vistas.setCurrentWidget(ficha)

    def _cerrar_ficha(self):
        if getattr(self, "ficha", None) is not None:
            self.vistas.removeWidget(self.ficha)
            self.ficha.deleteLater()
            self.ficha = None

    def _mostrar_lista(self):
        self.vistas.setCurrentWidget(self.lista)
        self._cerrar_ficha()
        self.lista.refrescar()


def main(argv=None):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Gestor de parcelas")
    T.aplicar_tema(app)
    DB.conectar()
    v = VentanaPrincipal()
    v.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
