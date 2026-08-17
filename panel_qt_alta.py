# -*- coding: utf-8 -*-
"""
panel_qt_alta.py
================

Alta y edicion de una parcela en la interfaz Qt: quien es, que se cultiva y donde
esta.

LA GEOMETRIA, Y UNA LIMITACION QUE CONVIENE SABER
-------------------------------------------------
La parcela se captura por SIGPAC: siete codigos y el recinto llega ya dibujado.
Es la via buena, porque el poligono es el oficial y de paso quedan guardados la
provincia y el municipio, que son la unidad en la que luego se corrige un umbral
para una comarca.

Lo que aqui NO hay es el mapa para DIBUJAR la parcela a mano. En la version de
Tkinter eso lo daba `tkintermapview`, que es una libreria solo de Tk y no tiene
equivalente directo en Qt: habria que reimplementarlo sobre QGraphicsView con
descarga de teselas, y es un trabajo aparte. Ya era una pieza OPCIONAL -sin ella
instalada, la version Tk tambien se queda solo con SIGPAC-, asi que esta pantalla
se comporta como esa, y lo dice en vez de dejar un hueco.

Las REGLAS de guardado (cerrar el poligono, calcular la superficie, guardar los
codigos SIGPAC, derivar el subtipo del marco) viven en `vista_parcelas`, que es
el mismo modulo que usa la interfaz de Tkinter.
"""

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QLineEdit, QComboBox, QPushButton, QDateEdit,
                               QDialogButtonBox, QMessageBox, QStackedWidget, QFrame)

import ui_tema as T
import almacen as DB
import vista_parcelas as VP
import fenologia_especies as FEN
from geo import superficie_ha
from sigpac import sigpac_consultar, _sigpac_get, SigpacError

CAMPOS_SIGPAC = ["Prov", "Mun", "Agr", "Zona", "Pol", "Par", "Rec"]
OBLIGATORIOS_SIGPAC = ("Prov", "Mun", "Pol", "Par", "Rec")
BUFFER_POR_DEFECTO = 15.0       # mismo valor que gee_cliente.BUFFER_INTERIOR_M


def _silencioso(texto):
    lb = QLabel(texto)
    lb.setObjectName("Silencioso")
    return lb


class DialogoParcela(QDialog):
    """Alta de una parcela nueva, o edicion de una existente.

    En edicion el NOMBRE no se cambia: identifica la parcela en toda la base
    (pasadas, eventos, validaciones), y renombrarla desde aqui dejaria huerfano
    todo su historico."""

    def __init__(self, padre, campana, editar=None):
        super().__init__(padre)
        self.campana = campana
        self.editar = editar
        self.coords = []
        self.setWindowTitle("Editar parcela" if editar else "Nueva parcela")
        self.setModal(True)
        self.setMinimumWidth(560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.ESP["l"], T.ESP["l"], T.ESP["l"], T.ESP["l"])
        lay.setSpacing(T.ESP["m"])
        lay.addLayout(self._identidad())
        lay.addWidget(self._cultivo())
        lay.addWidget(self._geometria())
        lay.addLayout(self._margen())

        self.estado = _silencioso("")
        self.estado.setWordWrap(True)
        lay.addWidget(self.estado)

        botones = QDialogButtonBox()
        guardar = botones.addButton("Guardar", QDialogButtonBox.AcceptRole)
        guardar.setObjectName("Primario")
        botones.addButton("Cancelar", QDialogButtonBox.RejectRole)
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

        self._cambiar_tipo(self.cb_tipo.currentText())
        if editar:
            self._cargar(editar)

    # ---- secciones ----
    def _identidad(self):
        rej = QGridLayout()
        rej.addWidget(_silencioso("Nombre"), 0, 0)
        self.e_nombre = QLineEdit()
        if self.editar:
            self.e_nombre.setText(self.editar.replace("_", " "))
            self.e_nombre.setReadOnly(True)     # identifica a la parcela: no se toca
        rej.addWidget(self.e_nombre, 1, 0)
        rej.addWidget(_silencioso("Propietario"), 0, 1)
        self.e_prop = QLineEdit()
        rej.addWidget(self.e_prop, 1, 1)
        return rej

    def _cultivo(self):
        caja = QFrame()
        caja.setObjectName("Tarjeta")
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(T.ESP["m"], T.ESP["m"], T.ESP["m"], T.ESP["m"])
        lay.setSpacing(T.ESP["s"])

        fila = QHBoxLayout()
        fila.addWidget(_silencioso("Tipo"))
        self.cb_tipo = QComboBox()
        self.cb_tipo.addItems(["EXTENSIVO", "LENOSO", "BARBECHO"])
        self.cb_tipo.currentTextChanged.connect(self._cambiar_tipo)
        fila.addWidget(self.cb_tipo)
        fila.addWidget(_silencioso("Especie"))
        self.cb_esp = QComboBox()
        self.cb_esp.currentTextChanged.connect(lambda _t: self._calc_marco())
        fila.addWidget(self.cb_esp, 1)
        lay.addLayout(fila)

        # Campos propios de cada tipo, apilados: un formulario con la mitad de los
        # campos en gris se lee peor que uno que solo ensena lo que aplica.
        self.especificos = QStackedWidget()
        self.especificos.addWidget(self._campos_extensivo())
        self.especificos.addWidget(self._campos_lenoso())
        self.especificos.addWidget(QWidget())          # barbecho: nada que pedir
        lay.addWidget(self.especificos)
        return caja

    def _campos_extensivo(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_silencioso("Finalidad"))
        self.cb_finalidad = QComboBox()
        self.cb_finalidad.addItems(["Cosecha de grano", "Siega en verde (forraje)"])
        lay.addWidget(self.cb_finalidad)
        lay.addWidget(_silencioso("Fecha de siembra"))
        self.e_siembra = QDateEdit()
        self.e_siembra.setDisplayFormat("dd-MM-yyyy")
        self.e_siembra.setCalendarPopup(True)
        self.e_siembra.setSpecialValueText(" ")        # vacio = no se sabe
        self.e_siembra.setMinimumDate(QDate(1900, 1, 1))
        self.e_siembra.setDate(self.e_siembra.minimumDate())
        lay.addWidget(self.e_siembra)
        lay.addStretch(1)
        return w

    def _campos_lenoso(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.ESP["xs"])
        fila = QHBoxLayout()
        fila.addWidget(_silencioso("Marco (m)"))
        self.e_calle = QLineEdit()
        self.e_calle.setMaximumWidth(70)
        self.e_calle.setPlaceholderText("calle")
        self.e_pie = QLineEdit()
        self.e_pie.setMaximumWidth(70)
        self.e_pie.setPlaceholderText("pie")
        self.e_copa = QLineEdit()
        self.e_copa.setMaximumWidth(70)
        self.e_copa.setPlaceholderText("copa")
        for campo in (self.e_calle, self.e_pie, self.e_copa):
            campo.textChanged.connect(self._calc_marco)
            fila.addWidget(campo)
        fila.addWidget(_silencioso("Regimen"))
        self.cb_regimen = QComboBox()
        self.cb_regimen.addItems(["Secano", "Regadio"])
        fila.addWidget(self.cb_regimen)
        fila.addStretch(1)
        lay.addLayout(fila)
        self.lbl_marco = QLabel("")
        self.lbl_marco.setStyleSheet(f"color:{T.COLOR['ok_fg']}; background:transparent;"
                                     f"font-size:{T.TAMANO['small']}pt;")
        lay.addWidget(self.lbl_marco)
        return w

    def _geometria(self):
        caja = QFrame()
        caja.setObjectName("Tarjeta")
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(T.ESP["m"], T.ESP["m"], T.ESP["m"], T.ESP["m"])
        lay.setSpacing(T.ESP["s"])
        lay.addWidget(QLabel("Geometria por SIGPAC   (Agr y Zona: 0 si no aplica)"))
        rej = QGridLayout()
        self.sig = {}
        for i, k in enumerate(CAMPOS_SIGPAC):
            rej.addWidget(_silencioso(k), (i // 4) * 2, i % 4)
            e = QLineEdit()
            e.setMaximumWidth(80)
            if k in ("Agr", "Zona"):
                e.setText("0")
            rej.addWidget(e, (i // 4) * 2 + 1, i % 4)
            self.sig[k] = e
        lay.addLayout(rej)
        btn = QPushButton("Capturar recinto SIGPAC")
        btn.clicked.connect(self._sigpac)
        lay.addWidget(btn)
        self.lbl_geo = _silencioso(
            "Aqui no se puede dibujar la parcela a mano: esa parte usaba una libreria "
            "solo de Tkinter. Captura el recinto por SIGPAC, que ademas guarda "
            "provincia y municipio.")
        self.lbl_geo.setWordWrap(True)
        lay.addWidget(self.lbl_geo)
        return caja

    def _margen(self):
        fila = QHBoxLayout()
        fila.addWidget(_silencioso("Margen interior (m)"))
        self.e_buffer = QLineEdit()
        self.e_buffer.setMaximumWidth(80)
        self.e_buffer.setPlaceholderText(str(int(BUFFER_POR_DEFECTO)))
        fila.addWidget(self.e_buffer)
        fila.addWidget(_silencioso("Vacio = el del programa (15 m). Descarta los "
                                   "pixeles de borde, mezclados con lindero o camino."))
        fila.addStretch(1)
        return fila

    # ---- reglas de pantalla ----
    def _cambiar_tipo(self, tipo):
        esp = FEN.ESPECIES.get(tipo, [])
        self.cb_esp.clear()
        self.cb_esp.addItems(esp)
        self.cb_esp.setEnabled(bool(esp))
        self.especificos.setCurrentIndex(
            0 if tipo == "EXTENSIVO" else 1 if tipo == "LENOSO" else 2)

    def _copa(self):
        try:
            v = float((self.e_copa.text() or "").replace(",", "."))
        except ValueError:
            return None
        return v if v > 0 else None

    def _calc_marco(self, *_a):
        """Al teclear el marco (o la copa), dice lo que implica: densidad, tipo de
        plantacion y que fraccion de suelo tapa la copa, que es la que traduce los
        umbrales a escala de parcela."""
        try:
            c = float(self.e_calle.text().replace(",", "."))
            p = float(self.e_pie.text().replace(",", "."))
        except ValueError:
            return self.lbl_marco.setText("")
        self.lbl_marco.setText(FEN.texto_marco(self.cb_esp.currentText() or "OLIVO",
                                               c, p, self._copa()))

    def _sigpac(self):
        v = {k: e.text().strip() for k, e in self.sig.items()}
        if not all(v.get(k) for k in OBLIGATORIOS_SIGPAC):
            return QMessageBox.warning(self, "SIGPAC",
                                       "Rellena al menos Prov, Mun, Pol, Par y Rec.")
        try:
            self.coords = sigpac_consultar(v, _sigpac_get)
        except (SigpacError, ValueError) as e:
            return QMessageBox.critical(self, "SIGPAC", str(e))
        self.estado.setText(f"Recinto capturado: {len(self.coords)} vertices, "
                            f"{superficie_ha(self.coords):.2f} ha.")

    def _cargar(self, nombre):
        ficha = DB.ficha(nombre) or {}
        self.e_prop.setText(ficha.get("propietario", ""))
        self.coords = ficha.get("coordenadas") or []
        if ficha.get("buffer_m") is not None:
            self.e_buffer.setText(str(ficha["buffer_m"]))
        for k, val in (ficha.get("sigpac") or {}).items():
            if k in self.sig:
                self.sig[k].setText(str(val))
        cult = (ficha.get("cultivos_por_campana") or {}).get(self.campana) or {}
        if cult.get("tipo"):
            self.cb_tipo.setCurrentText(cult["tipo"])
        if cult.get("especie"):
            self.cb_esp.setCurrentText(cult["especie"])
        if cult.get("fecha_siembra"):
            self.e_siembra.setDate(QDate.fromString(cult["fecha_siembra"], "yyyy-MM-dd"))
        if cult.get("finalidad") == "SIEGA_VERDE":
            self.cb_finalidad.setCurrentIndex(1)
        for campo, clave in ((self.e_calle, "marco_calle"), (self.e_pie, "marco_pie"),
                             (self.e_copa, "diametro_copa")):
            if cult.get(clave):
                campo.setText(str(cult[clave]))
        if cult.get("regimen") == "REGADIO":
            self.cb_regimen.setCurrentText("Regadio")
        if self.coords:
            self.estado.setText(f"Geometria guardada: {len(self.coords)} vertices, "
                                f"{superficie_ha(self.coords):.2f} ha.")

    # ---- guardado ----
    def _spec(self, tipo):
        """Los datos del cultivo. Devuelve None si falta algo obligatorio (y lo dice)."""
        spec = {"especie": self.cb_esp.currentText()}
        if tipo == "EXTENSIVO":
            spec["finalidad"] = ("SIEGA_VERDE" if self.cb_finalidad.currentIndex() == 1
                                 else "COSECHA_GRANO")
            if self.e_siembra.date() != self.e_siembra.minimumDate():
                spec["fecha_siembra"] = self.e_siembra.date().toString("yyyy-MM-dd")
        elif tipo == "LENOSO":
            try:
                spec["marco_calle"] = float(self.e_calle.text().replace(",", "."))
                spec["marco_pie"] = float(self.e_pie.text().replace(",", "."))
            except ValueError:
                QMessageBox.warning(self, "Marco", "Indica el marco de plantacion "
                                                   "(calle y pie, en metros).")
                return None
            spec["diametro_copa"] = self._copa()
            spec["regimen"] = ("REGADIO" if self.cb_regimen.currentText().startswith("Rega")
                               else "SECANO")
        return spec

    def _guardar(self):
        nombre = self.editar or self.e_nombre.text().strip().replace(" ", "_")
        prop = self.e_prop.text().strip()
        tipo = self.cb_tipo.currentText()
        if not nombre or not prop:
            return QMessageBox.warning(self, "Datos",
                                       "El nombre y el propietario son obligatorios.")
        if tipo != "BARBECHO" and not self.cb_esp.currentText():
            return QMessageBox.warning(self, "Datos", "Selecciona la especie.")
        if len(self.coords or []) < 3:
            return QMessageBox.warning(
                self, "Geometria",
                "Falta la geometria de la parcela. Captura el recinto por SIGPAC "
                "(Prov, Mun, Pol, Par y Rec).")
        spec = self._spec(tipo)
        if spec is None:
            return
        buf = (self.e_buffer.text() or "").strip().replace(",", ".")
        try:
            buffer_m = float(buf) if buf else None
            if buffer_m is not None and buffer_m < 0:
                raise ValueError
        except ValueError:
            return QMessageBox.warning(self, "Margen",
                                       "El margen interior es un numero de metros "
                                       "(o dejalo vacio).")
        VP.guardar_parcela(DB, FEN, superficie_ha, nombre, prop, tipo, spec,
                           self.coords, self.campana,
                           sigpac={k: e.text().strip() for k, e in self.sig.items()},
                           buffer_m=buffer_m)
        self.accept()
