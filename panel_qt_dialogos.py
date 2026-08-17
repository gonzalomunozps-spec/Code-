# -*- coding: utf-8 -*-
"""
panel_qt_dialogos.py
====================

Los dialogos de la interfaz Qt: corregir un diagnostico, validar indice a indice
y el cuaderno de campo.

Ninguno decide nada del dominio. El ambito de una correccion, el descarte de la
interpretacion cacheada y la normalizacion de los datos de cosecha viven en
`vista_ficha` y en `registro_parcela`, que son los mismos modulos que usa la
interfaz de Tkinter.
"""

from datetime import datetime

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QLineEdit, QComboBox, QPushButton, QTextEdit,
                               QRadioButton, QButtonGroup, QDialogButtonBox, QDateEdit,
                               QMessageBox, QStackedWidget)

import ui_tema as T
import almacen as DB
import vista_ficha as VF
import registro_parcela as REG

try:
    import calibracion_umbrales as _CALIB
except Exception:
    _CALIB = None

_FMT_FECHA = "dd-MM-yyyy"       # como se teclea; en la base se guarda ISO


def _campo_fecha(iso=None):
    """Campo de fecha con calendario. Mismo formato visible que en la version Tk."""
    w = QDateEdit()
    w.setDisplayFormat(_FMT_FECHA)
    w.setCalendarPopup(True)
    if iso:
        w.setDate(QDate.fromString(iso, "yyyy-MM-dd"))
    else:
        w.setDate(QDate.currentDate())
    return w


def _iso(campo):
    return campo.date().toString("yyyy-MM-dd")


def _etiqueta(texto):
    lb = QLabel(texto)
    lb.setObjectName("Silencioso")
    return lb


# =====================================================================
# Corregir el diagnostico
# =====================================================================
class DialogoCorreccion(QDialog):
    """Pide el estado real y una nota. Lo que se aprende sale de aqui.

    El AMBITO es la pregunta importante y por eso esta en el dialogo y no en un
    ajuste escondido: corregir «todas mis parcelas de olivo» y corregir «solo esta
    finca, que es especial» son dos cosas distintas, y el programa no puede
    adivinar cual quiso decir el usuario."""

    def __init__(self, padre, nombre, val_ctx):
        super().__init__(padre)
        self.nombre, self.ctx = nombre, val_ctx
        self.setWindowTitle("Corregir diagnostico")
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.ESP["l"], T.ESP["l"], T.ESP["l"], T.ESP["l"])
        lay.setSpacing(T.ESP["s"])

        lay.addWidget(_etiqueta("El sistema diagnostico:"))
        lay.addWidget(QLabel(f"[{val_ctx.get('estado', '?')}]  ·  "
                             f"Fase: {val_ctx.get('fase', '?')}"))

        lay.addSpacing(T.ESP["s"])
        lay.addWidget(_etiqueta("¿Cual era el estado correcto?"))
        self.cb = QComboBox()
        self.cb.addItems(VF.ESTADOS_VALIDABLES)
        self.cb.setCurrentText(val_ctx.get("estado", "OK"))
        lay.addWidget(self.cb)

        lay.addSpacing(T.ESP["s"])
        lay.addWidget(_etiqueta("¿A que debe aplicarse esta correccion?"))
        cultivo = (val_ctx.get("cultivo", "") or "").split("/")[-1] or "este cultivo"
        self.rb_cultivo = QRadioButton(f"A todas mis parcelas de {cultivo}")
        self.rb_parcela = QRadioButton(f"Solo a «{nombre.replace('_', ' ')}» "
                                       f"(esta finca es especial)")
        self.rb_cultivo.setChecked(True)
        grupo = QButtonGroup(self)
        grupo.addButton(self.rb_cultivo)
        grupo.addButton(self.rb_parcela)
        lay.addWidget(self.rb_cultivo)
        lay.addWidget(self.rb_parcela)

        lay.addSpacing(T.ESP["s"])
        lay.addWidget(_etiqueta("Observacion (opcional):"))
        self.nota = QTextEdit()
        self.nota.setFixedHeight(80)
        lay.addWidget(self.nota)

        botones = QDialogButtonBox()
        guardar = botones.addButton("Guardar correccion", QDialogButtonBox.AcceptRole)
        guardar.setObjectName("Primario")
        botones.addButton("Cancelar", QDialogButtonBox.RejectRole)
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

    def _guardar(self):
        VF.guardar_validacion(self.nombre, self.ctx.get("campana", ""), self.ctx,
                              "incorrecto", estado_real=self.cb.currentText(),
                              nota=self.nota.toPlainText().strip(),
                              solo_parcela=self.rb_parcela.isChecked())
        self.accept()


# =====================================================================
# Validar indice a indice
# =====================================================================
class DialogoValidacionIndices(QDialog):
    """Validacion INDICE A INDICE de una pasada, con el alcance de la correccion.

    Cada indice llega con lo que midio el satelite y con lo que el sistema opina,
    ya preseleccionado: confirmar es no tocar nada. Vive detras del modulo
    opcional `calibracion_umbrales`; sin el, ni este dialogo ni su boton existen.
    """

    def __init__(self, padre, nombre, campana, ctx):
        super().__init__(padre)
        self.nombre, self.campana, self.ctx = nombre, campana, ctx
        self.setWindowTitle("Validar indices de la pasada")
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.ESP["l"], T.ESP["l"], T.ESP["l"], T.ESP["l"])
        lay.setSpacing(T.ESP["s"])

        cab = QLabel(f"{nombre.replace('_', ' ')}  ·  {ctx.get('fecha', '?')}")
        cab.setObjectName("TarjetaTitulo")
        lay.addWidget(cab)
        sub = f"Fase: {ctx.get('fase', '?')}"
        if ctx.get("especie"):
            sub = f"{ctx['especie']}  ·  " + sub
        lay.addWidget(_etiqueta(sub))
        ayuda = QLabel("Confirma o corrige lo que el sistema ve en cada indice. Ya viene "
                       "marcado lo que opina: si estas de acuerdo, no toques nada.")
        ayuda.setObjectName("Secundario")
        ayuda.setWordWrap(True)
        lay.addWidget(ayuda)

        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(T.ESP["m"])
        for col, txt in enumerate(("Indice", "Valor", "El sistema ve", "Tu dices")):
            rejilla.addWidget(_etiqueta(txt), 0, col)
        previas = DB.validaciones_indice_de_pasada(nombre, campana, ctx.get("fecha", ""))
        self.combos = {}
        fila = 1
        for idx, lec in (ctx.get("lecturas") or {}).items():
            if not lec or lec.get("valor") is None:
                continue          # ese dia no se midio: no hay nada que validar
            rejilla.addWidget(QLabel(idx), fila, 0)
            rejilla.addWidget(QLabel(f"{lec['valor']:.3f}"), fila, 1)
            visto = lec.get("sistema", _CALIB.SIN_CRITERIO if _CALIB else "")
            lb_visto = QLabel(visto)
            if visto == "bajo":
                lb_visto.setStyleSheet(f"color:{T.COLOR['danger_fg']}; background:transparent;")
            rejilla.addWidget(lb_visto, fila, 2)
            cb = QComboBox()
            estados = _CALIB.ESTADOS if _CALIB else ["bajo", "normal", "alto"]
            cb.addItems(estados)
            # preseleccionado con lo que ya dijiste antes; si no, con lo que ve el
            # sistema; y si en esta fase el sistema no tiene criterio, "normal"
            anterior = (previas.get(idx) or {}).get("dijo_usuario")
            cb.setCurrentText(anterior or (visto if visto in estados else "normal"))
            rejilla.addWidget(cb, fila, 3)
            self.combos[idx] = cb
            if not lec.get("calibrable"):
                rejilla.addWidget(_etiqueta("(se anota, hoy no mueve umbral)"), fila, 4)
            fila += 1
        lay.addLayout(rejilla)

        lay.addSpacing(T.ESP["s"])
        lay.addWidget(_etiqueta("¿A que debe aplicarse lo que digas?"))
        self.ambitos = _CALIB.ambitos_disponibles(nombre) if _CALIB else [("parcela", "Esta parcela")]
        self.cb_ambito = QComboBox()
        self.cb_ambito.addItems([t for _a, t in self.ambitos])
        lay.addWidget(self.cb_ambito)
        if len(self.ambitos) < 4:
            aviso = QLabel("Esta parcela no tiene municipio ni provincia guardados: "
                           "capturala por SIGPAC o editala para poder corregir a ese nivel.")
            aviso.setObjectName("Silencioso")
            aviso.setWordWrap(True)
            lay.addWidget(aviso)

        botones = QDialogButtonBox()
        guardar = botones.addButton("Guardar", QDialogButtonBox.AcceptRole)
        guardar.setObjectName("Primario")
        botones.addButton("Cancelar", QDialogButtonBox.RejectRole)
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

    def _guardar(self):
        if _CALIB is None:
            return self.reject()
        ambito = self.ambitos[self.cb_ambito.currentIndex()][0]
        respuestas = {i: cb.currentText() for i, cb in self.combos.items()}
        n = _CALIB.registrar(self.nombre, self.campana, self.ctx.get("fecha"),
                             self.ctx.get("especie"), self.ctx.get("fase"),
                             self.ctx.get("lecturas"), respuestas, ambito,
                             umbrales=self.ctx.get("umbrales"))
        self.accept()
        QMessageBox.information(
            self.parent(), "Validacion",
            f"Anotados {n} indice(s) para «{dict(self.ambitos)[ambito]}».\n\n"
            f"Hacen falta {_CALIB.MIN_OBSERVACIONES} validaciones coherentes de la "
            f"misma especie y fase, y de al menos {_CALIB.MIN_FECHAS} pasadas de dias "
            f"distintos, para que un umbral se mueva. Varias validaciones del mismo "
            f"dia cuentan como una sola observacion.")


# =====================================================================
# Cuaderno de campo
# =====================================================================
class Cuaderno(QWidget):
    """Alta de intervenciones y lista de lo ya anotado.

    Los campos cambian segun el tipo: un PRODUCTO pide nombre, objetivo y dosis;
    una COSECHA pide rendimiento, humedad y superficie. Se ensena solo lo que
    aplica, en vez de un formulario con la mitad de los campos en gris."""

    cambiado = Signal()

    def __init__(self, nombre, campana):
        super().__init__()
        self.nombre, self.campana = nombre, campana
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.ESP["s"])

        alta = QHBoxLayout()
        alta.setSpacing(T.ESP["s"])
        alta.addWidget(_etiqueta("Fecha"))
        self.fecha = _campo_fecha(datetime.now().strftime("%Y-%m-%d"))
        alta.addWidget(self.fecha)
        alta.addWidget(_etiqueta("Tipo"))
        self.tipo = QComboBox()
        self.tipo.addItems(REG.TIPOS_EVENTO)
        self.tipo.setCurrentText("PRODUCTO")
        self.tipo.currentTextChanged.connect(self._cambiar_tipo)
        alta.addWidget(self.tipo)
        lay.addLayout(alta)

        # Los campos propios de cada tipo, apilados: nunca se ven dos a la vez.
        self.especificos = QStackedWidget()
        self.especificos.addWidget(self._campos_producto())
        self.especificos.addWidget(self._campos_cosecha())
        self.especificos.addWidget(QWidget())          # el resto de tipos: nada
        lay.addWidget(self.especificos)

        notas = QHBoxLayout()
        notas.addWidget(_etiqueta("Notas"))
        self.notas = QLineEdit()
        notas.addWidget(self.notas, 1)
        self.btn = QPushButton("Anotar")
        self.btn.setObjectName("Primario")
        self.btn.clicked.connect(self._anotar)
        notas.addWidget(self.btn)
        lay.addLayout(notas)

        from panel_qt_ficha import ModeloTabla, tabla_de
        self.modelo = ModeloTabla(["FECHA", "TIPO", "DETALLE", "NOTAS"])
        self.tabla = tabla_de(self.modelo, alto_min=140)
        lay.addWidget(self.tabla, 1)
        self._cambiar_tipo(self.tipo.currentText())
        self.refrescar()

    def _campos_producto(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.ESP["s"])
        lay.addWidget(_etiqueta("Producto"))
        self.producto = QLineEdit()
        lay.addWidget(self.producto, 1)
        lay.addWidget(_etiqueta("Objetivo"))
        self.objetivo = QComboBox()
        self.objetivo.addItems(REG.OBJETIVOS_PRODUCTO)
        lay.addWidget(self.objetivo)
        lay.addWidget(_etiqueta("Dosis"))
        self.dosis = QLineEdit()
        self.dosis.setMaximumWidth(90)
        lay.addWidget(self.dosis)
        return w

    def _campos_cosecha(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.ESP["s"])
        lay.addWidget(_etiqueta("Rendimiento (kg/ha)"))
        self.rendimiento = QLineEdit()
        self.rendimiento.setMaximumWidth(90)
        lay.addWidget(self.rendimiento)
        self.lb_humedad = _etiqueta("Humedad grano (%)")
        lay.addWidget(self.lb_humedad)
        self.humedad = QLineEdit()
        self.humedad.setMaximumWidth(70)
        lay.addWidget(self.humedad)
        lay.addWidget(_etiqueta("Superficie (ha)"))
        self.superficie = QLineEdit()
        self.superficie.setMaximumWidth(80)
        lay.addWidget(self.superficie)
        lay.addWidget(_etiqueta("Origen"))
        self.fuente = QComboBox()
        self.fuente.addItems([""] + list(REG.FUENTES_DATO))
        lay.addWidget(self.fuente)
        lay.addStretch(1)
        return w

    # ---- reglas ----
    def _campana_evento(self, iso):
        return REG.campana_de_evento(self.tipo.currentText(), iso, self.campana)

    def _cultivo_de(self, campana):
        ficha = DB.ficha(self.nombre) or {}
        return (ficha.get("cultivos_por_campana") or {}).get(campana, {}) or {}

    def _admite_humedad(self, campana):
        """La humedad de grano solo se pide donde significa algo.

        Las campanas viejas no suelen tener cultivo registrado: se hereda el de la
        que se esta viendo (misma regla que en la version Tk)."""
        return REG.admite_humedad_en_campana(self._cultivo_de(campana),
                                             self._cultivo_de(self.campana))

    def _cambiar_tipo(self, tipo):
        self.especificos.setCurrentIndex(
            0 if tipo == "PRODUCTO" else 1 if tipo == "COSECHA" else 2)
        if tipo == "COSECHA":
            admite = self._admite_humedad(self._campana_evento(_iso(self.fecha)))
            self.lb_humedad.setVisible(admite)
            self.humedad.setVisible(admite)

    def _anotar(self):
        fecha = _iso(self.fecha)
        tipo = self.tipo.currentText()
        ev = {"fecha": fecha, "tipo": tipo, "notas": self.notas.text().strip()}
        campana = self._campana_evento(fecha)
        if tipo == "PRODUCTO":
            if not self.producto.text().strip():
                return QMessageBox.warning(self, "Producto",
                                           "Indica el nombre del producto.")
            ev.update({"producto": self.producto.text().strip(),
                       "objetivo": self.objetivo.currentText(),
                       "dosis": self.dosis.text().strip()})
        elif tipo == "COSECHA":
            admite = self._admite_humedad(campana)
            if not admite and self.humedad.text().strip():
                return QMessageBox.warning(
                    self, "Cosecha",
                    "Este cultivo no es grano de extensivo: ahi no se anota humedad "
                    "de grano. Borra ese campo para continuar.")
            try:
                ev.update(REG.datos_cosecha(self.rendimiento.text(), self.humedad.text(),
                                            self.superficie.text(), self.fuente.currentText(),
                                            admite_humedad=admite))
            except ValueError as e:
                return QMessageBox.warning(self, "Cosecha", f"Revisa el campo {e}: "
                                           "escribe un numero (o dejalo vacio).")
        REG.registrar_evento(self.nombre, campana, ev)
        for campo in (self.notas, self.producto, self.dosis, self.rendimiento,
                      self.humedad, self.superficie):
            campo.clear()
        self.refrescar()
        self.cambiado.emit()

    def refrescar(self):
        filas = []
        for ev in REG.eventos_de(self.nombre, self.campana) or []:
            detalle = ev.get("producto", "")
            if ev.get("dosis"):
                detalle += f"  ({ev['dosis']})"
            if ev.get("rendimiento_kg_ha") is not None:
                detalle = f"{ev['rendimiento_kg_ha']:.0f} kg/ha"
                if ev.get("humedad_grano_pct") is not None:
                    detalle += f"  ·  {ev['humedad_grano_pct']:.1f} % hum."
            filas.append([ev.get("fecha", ""), ev.get("tipo", ""), detalle or "-",
                          ev.get("notas", "")])
        self.modelo.poner(filas)
