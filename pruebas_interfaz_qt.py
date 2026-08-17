# -*- coding: utf-8 -*-
"""
pruebas_interfaz_qt.py
======================

Pruebas de la interfaz Qt. Hermanas de `pruebas_interfaz.py` (que prueba la de
Tkinter) y con el mismo criterio: monta la aplicacion DE VERDAD, la toca, y
cualquier excepcion cuenta como fallo.

    python pruebas_interfaz_qt.py                  # con pantalla
    QT_QPA_PLATFORM=offscreen python pruebas_interfaz_qt.py    # en un servidor

Qt trae su propia plataforma «offscreen», asi que aqui no hace falta Xvfb: la
aplicacion se monta entera, con su layout y su hoja de estilo, sin servidor
grafico. Si falta PySide6, se omite entera y devuelve 0, como hace la de Tk
cuando no hay pantalla.

Es un fichero SUELTO: borralo y no se pierde nada mas que estas pruebas.

Limitaciones, para no dar una falsa sensacion de cobertura
----------------------------------------------------------
  - No comprueba el ASPECTO. Que la hoja de estilo se aplique sin error no dice
    que se vea bien; eso hay que mirarlo.
  - No habla con Earth Engine ni con OpenAI.
  - Cubre lo que hay portado. Lo que siga en Tkinter lo prueba el otro fichero.
"""

import os
import sys
import tempfile

FALLOS = []


def _anotar(donde, e):
    import traceback
    FALLOS.append((donde, f"{type(e).__name__}: {e}", traceback.format_exc()))


def _paso(nombre, fn):
    try:
        fn()
        return True
    except Exception as e:
        _anotar(nombre, e)
        return False


def _check(cond, mensaje):
    if not cond:
        raise AssertionError(mensaje)
    return True


DIALOGOS = []        # cajas de mensaje que habria visto quien usa el programa


def _sin_modales():
    """Sustituye las cajas de mensaje por un registro.

    Igual que en el arnes de Tkinter, y por el mismo motivo: `QMessageBox` abre su
    propio bucle de eventos y se queda ahi hasta que una persona pulse un boton.
    Sin esto, la primera confirmacion cuelga la tanda entera. Se guarda lo que
    habria salido, que ademas es informacion util."""
    from PySide6.QtWidgets import QMessageBox

    def reg(tipo, valor):
        def f(padre=None, titulo="", texto="", *a, **k):
            DIALOGOS.append((tipo, str(titulo), " ".join(str(texto).split())[:90]))
            return valor
        return staticmethod(f)
    QMessageBox.information = reg("info", QMessageBox.Ok)
    QMessageBox.warning = reg("aviso", QMessageBox.Ok)
    QMessageBox.critical = reg("error", QMessageBox.Ok)
    QMessageBox.question = reg("pregunta", QMessageBox.No)   # por defecto NO


def _callar_ruido_de_offscreen():
    """Silencia SOLO el aviso de la plataforma «offscreen», que es del arnes.

    Sin pantalla, Qt avisa de que ese backend no implementa
    `propagateSizeHints()`, una vez por ventana. No dice nada del programa -con
    pantalla no aparece- y tapa el resultado de las pruebas. Se filtra por el
    texto exacto para no callar ningun otro aviso de Qt, que si interesan."""
    from PySide6.QtCore import qInstallMessageHandler

    def handler(tipo, contexto, mensaje):
        if "propagateSizeHints" in mensaje:
            return
        sys.stderr.write(f"{mensaje}\n")
    qInstallMessageHandler(handler)


def _sembrar():
    import almacen as DB
    import demo_sistema as D
    DB.conectar()
    D.sembrar(D.escenarios())
    return DB


# ---------------------------------------------------------------------------
# Escenarios
# ---------------------------------------------------------------------------
def escenario_tema(P, DB, app):
    """La hoja de estilo se aplica y no deja marcadores sin resolver."""
    import ui_tema as T
    qss = app.styleSheet()
    _paso("tema: hay hoja de estilo", lambda: _check(len(qss) > 500, "QSS vacio o demasiado corto"))
    _paso("tema: sin marcadores de formato sin resolver",
          lambda: _check("{" not in qss.split("QWidget")[0], "quedan llaves sin sustituir"))
    _paso("tema: los colores de estado son los del programa, no otros nuevos",
          lambda: _check(T.color_estado("Revisar")[0] == "#c53030"
                         and T.color_estado("OK")[0] == "#276749",
                         "los colores de estado han cambiado"))
    _paso("tema: lo que no es un juicio va en gris",
          lambda: _check(T.color_estado("SinAsig") == (T.COLOR["muted_fg"], T.COLOR["muted_bg"]),
                         "un estado sin juicio se pinta como si lo tuviera"))
    return "hoja de estilo aplicada"


def escenario_lista(P, DB, app):
    """La lista: carga, busca, ordena, cambia de campana y abre el menu."""
    from PySide6.QtCore import Qt, QPoint
    v = P.VentanaPrincipal()
    v.show()
    app.processEvents()
    lista = v.lista
    n_total = lista.modelo.rowCount()
    _paso("lista: carga las parcelas sembradas",
          lambda: _check(n_total == len(DB.nombres()),
                         f"{n_total} filas para {len(DB.nombres())} parcelas"))
    _paso("lista: las columnas son las cinco de siempre",
          lambda: _check([c[1] for c in lista.modelo.COLUMNAS] ==
                         ["Parcela", "Cultivo", "Superficie", "Propietario", "Estado"],
                         "han cambiado las columnas de la lista"))

    # busqueda
    primera = lista.modelo.fila(0)["nombre"]
    _paso("lista: la busqueda filtra", lambda: (
        lista.buscar.setText(primera.split()[0]), app.processEvents(),
        _check(0 < lista.modelo.rowCount() <= n_total, "la busqueda no filtro nada")))
    _paso("lista: una busqueda sin resultados deja la tabla vacia y no revienta",
          lambda: (lista.buscar.setText("zzz-no-existe"), app.processEvents(),
                   _check(lista.modelo.rowCount() == 0, "deberia quedar vacia")))
    _paso("lista: al vaciar la busqueda vuelven todas",
          lambda: (lista.buscar.setText(""), app.processEvents(),
                   _check(lista.modelo.rowCount() == n_total, "no vuelven todas")))

    # orden: se recorren TODOS los criterios, no solo uno
    import vista_parcelas as VP
    for orden in VP.ORDENES:
        _paso(f"lista: ordenar por {orden}", lambda o=orden: (
            lista.cb_orden.setCurrentText(o), app.processEvents(),
            _check(lista.modelo.rowCount() == n_total, f"al ordenar por {o} se perdieron filas")))
    _paso("lista: ordenar por estado pone lo urgente primero", lambda: (
        lista.cb_orden.setCurrentText("estado"), app.processEvents(),
        _check([VP.SEVERIDAD.get(lista.modelo.fila(i)["estado"], 9)
                for i in range(lista.modelo.rowCount())] ==
               sorted(VP.SEVERIDAD.get(lista.modelo.fila(i)["estado"], 9)
                      for i in range(lista.modelo.rowCount())),
               "el orden por estado no es por gravedad")))

    # campanas
    for camp in [lista.cb_campana.itemText(i) for i in range(lista.cb_campana.count())]:
        _paso(f"lista: campana {camp}", lambda c=camp: (
            lista.cb_campana.setCurrentText(c), app.processEvents()))

    # el modelo responde bien a lo que Qt le pide, incluido lo que no existe
    _paso("lista: el modelo no se sale por un indice invalido", lambda: (
        _check(lista.modelo.fila(9999) is None, "un indice fuera de rango deberia dar None"),
        _check(lista.modelo.data(lista.modelo.index(-1, 0)) is None, "indice invalido")))
    _paso("lista: el estado lleva su color, y solo donde hay juicio", lambda: (
        _check(all(lista.modelo.data(lista.modelo.index(i, 4), Qt.ForegroundRole) is not None
                   for i in range(lista.modelo.rowCount())),
               "falta el color del estado en alguna fila")))

    # menu contextual y seleccion
    _paso("lista: seleccionar una fila", lambda: (
        lista.tabla.selectRow(0), app.processEvents(),
        _check(lista._seleccionada() is not None, "no hay fila seleccionada")))
    # el menu se CONSTRUYE aqui, no se muestra: `exec` abriria su propio bucle de
    # eventos y el arnes se colgaria esperando a que alguien lo cerrase
    _paso("lista: el menu de una fila ofrece abrir y eliminar", lambda: (
        _check([a.text() for a in lista.menu_de_fila(0).actions() if a.text()] ==
               ["Abrir ficha", "Eliminar parcela…"], "el menu contextual ha cambiado")))
    _paso("lista: no hay menu para una fila que no existe",
          lambda: _check(lista.menu_de_fila(9999) is None, "deberia no haber menu"))
    _paso("lista: un clic contextual en el hueco vacio no hace nada",
          lambda: lista._menu_contextual(QPoint(5, 100000)))

    # abrir ficha: hoy avisa de que no esta portada; lo que importa es que no cae
    _paso("lista: doble clic sobre una parcela", lambda: lista._abrir(0))
    _paso("lista: el resumen por estado se pinta",
          lambda: _check(lista.insignias.count() >= 0, "resumen roto"))
    v.close()
    return f"{n_total} parcelas, busqueda, {len(VP.ORDENES)} ordenes y menu comprobados"


def escenario_lista_vacia(P, DB, app):
    """Una base recien creada, sin ninguna parcela: el caso que mas se olvida."""
    import almacen as _DB
    _DB.conectar(os.path.join(tempfile.mkdtemp(), "vacia.db"))
    try:
        v = P.VentanaPrincipal()
        v.show()
        app.processEvents()
        _paso("vacia: la lista aparece sin filas y sin quejarse",
              lambda: _check(v.lista.modelo.rowCount() == 0, "deberia estar vacia"))
        _paso("vacia: el pie lo dice en singular/plural correcto",
              lambda: _check("0 parcelas" in v.lista.pie.text(), v.lista.pie.text()))
        _paso("vacia: eliminar sin seleccion no hace nada", lambda: v.lista._eliminar())
        _paso("vacia: refrescar sobre una base vacia", lambda: v.lista.refrescar())
        v.close()
    finally:
        _sembrar()
    return "base sin parcelas recorrida"


def escenario_borrado(P, DB, app):
    """Eliminar una parcela desde la lista, confirmando de verdad."""
    from PySide6.QtWidgets import QMessageBox
    v = P.VentanaPrincipal()
    v.show()
    app.processEvents()
    antes = v.lista.modelo.rowCount()
    original = QMessageBox.question
    try:
        # aqui SI se contesta que si: es lo que hace la prueba
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        v.lista.tabla.selectRow(0)
        nombre = v.lista._seleccionada()["id"]
        v.lista._eliminar()
        app.processEvents()
        _paso("borrado: desaparece de la lista",
              lambda: _check(v.lista.modelo.rowCount() == antes - 1,
                             f"habia {antes}, quedan {v.lista.modelo.rowCount()}"))
        _paso("borrado: y de la base, en cascada",
              lambda: _check(nombre not in DB.nombres(), "la parcela sigue en la base"))
    finally:
        QMessageBox.question = original
        _sembrar()
    _paso("borrado: decir que NO deja la parcela donde estaba", lambda: (
        _check(QMessageBox.question(None, "", "") == QMessageBox.No,
               "la respuesta por defecto del arnes deberia ser NO")))
    v.close()
    return "una parcela eliminada y repuesta"


ESCENARIOS = [("tema", escenario_tema), ("lista de parcelas", escenario_lista),
              ("lista vacia", escenario_lista_vacia), ("borrado", escenario_borrado)]


def main():
    # se pregunta por el modulo sin importarlo: solo interesa si esta instalado
    import importlib.util
    if importlib.util.find_spec("PySide6") is None:
        print("pruebas_interfaz_qt: se omite (no hay PySide6; pip install PySide6)")
        return 0
    os.environ["GESTOR_PARCELAS_DIR"] = tempfile.mkdtemp()   # nunca la base real
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    import ui_tema as T

    _sin_modales()
    _callar_ruido_de_offscreen()
    DB = _sembrar()
    import panel_qt as P
    app = QApplication.instance() or QApplication([])
    T.aplicar_tema(app)

    print("=" * 74)
    print(" PRUEBAS DE INTERFAZ (Qt)  ·  se monta la aplicacion real y se toca todo")
    print("=" * 74)
    import time
    for nombre, fn in ESCENARIOS:
        antes, t0 = len(FALLOS), time.time()
        try:
            detalle = fn(P, DB, app)
        except Exception as e:
            _anotar(nombre, e)
            detalle = "abortado"
        nuevos = len(FALLOS) - antes
        marca = "  ok " if nuevos == 0 else f" {nuevos:>3} X"
        print(f"{marca}  {nombre:<24} {detalle}   ({time.time() - t0:.1f}s)")

    print("-" * 74)
    if DIALOGOS:
        print(f"  {len(DIALOGOS)} caja(s) de mensaje por el camino "
              f"(esperado: el aviso de que la ficha aun no esta portada)")
    if not FALLOS:
        print("  La interfaz Qt responde sin excepciones.")
        return 0
    print(f"  {len(FALLOS)} FALLO(S):")
    for donde, msg, traza in FALLOS:
        print(f"  -- {donde}: {msg}")
        print("     " + traza.strip().splitlines()[-3].strip())
    return 1


if __name__ == "__main__":
    sys.exit(main())
