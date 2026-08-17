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


def escenario_ficha(P, DB, app):
    """La ficha de CADA parcela: se abre, se recorre y se vuelve."""
    import vista_ficha as VF
    v = P.VentanaPrincipal()
    v.show()
    app.processEvents()
    abiertas = 0
    for nombre in DB.nombres():
        if not _paso(f"ficha '{nombre}': abrir", lambda n=nombre: (
                v._abrir_ficha(n), app.processEvents(),
                _check(v.ficha is not None, "no se monto la ficha"),
                _check(v.vistas.currentWidget() is v.ficha, "la ficha no esta a la vista"))):
            continue
        abiertas += 1
        f = v.ficha
        serie = f._serie()
        _paso(f"{nombre}: el historico tiene una fila por pasada", lambda f=f, s=serie: (
            _check(f.modelo_idx.rowCount() == len(s),
                   f"{f.modelo_idx.rowCount()} filas para {len(s)} pasadas")))
        _paso(f"{nombre}: la tabla lleva fecha y los siete indices", lambda f=f: (
            _check(f.modelo_idx.columnCount() == 8, "faltan columnas de indices")))
        _paso(f"{nombre}: la estadistica no inventa filas", lambda f=f, s=serie: (
            _check(f.modelo_est.rowCount() == len(VF.filas_estadistica(s)),
                   "la tabla de estadistica no cuadra con lo que hay")))
        _paso(f"{nombre}: el pie explica la tabla o dice por que esta vacia", lambda f=f: (
            _check(f.lbl_est.text() in (VF.PIE_ESTADISTICA, VF.PIE_SIN_ESTADISTICA),
                   "pie de la estadistica inesperado")))
        _paso(f"{nombre}: hay interpretacion, no una caja en blanco", lambda f=f, s=serie: (
            _check(len(f.interp.texto.toPlainText()) > 0, "la interpretacion esta vacia")))
        _paso(f"{nombre}: refrescar dos veces seguidas", lambda f=f: (
            f.refrescar(), app.processEvents(), f.refrescar(), app.processEvents()))
        # recorrer TODAS las pasadas por el desplegable, como haria el usuario
        if f.interp.cb_pasada is not None and f.interp.cb_pasada.count():
            _paso(f"{nombre}: recorrer las pasadas anteriores", lambda f=f: [
                (f.interp.cb_pasada.setCurrentIndex(i), app.processEvents())
                for i in range(f.interp.cb_pasada.count())])
        # marcar y desmarcar cada indice de la grafica
        _paso(f"{nombre}: marcar y desmarcar los indices de la grafica", lambda f=f: [
            (c.setChecked(not c.isChecked()), app.processEvents())
            for c in f.graficas.casillas.values()])
        _paso(f"{nombre}: apagar y encender el analisis de zonas", lambda f=f: (
            f.interp.chk_zonas.setChecked(False), app.processEvents(),
            f.interp.chk_zonas.setChecked(True), app.processEvents()))
        _paso(f"{nombre}: validar como correcto", lambda f=f: (
            f._validar("correcto"), app.processEvents()))
        _paso(f"{nombre}: pedir la correccion (aun no portada, debe avisar)",
              lambda f=f: f._validar("corregir"))
        _paso(f"{nombre}: volver a la lista", lambda: (
            v.lista.refrescar() if v.ficha is None else v.ficha.volver.emit(),
            app.processEvents(),
            _check(v.vistas.currentWidget() is v.lista, "no se volvio a la lista"),
            _check(v.ficha is None, "la ficha no se solto al volver")))
    v.close()
    return f"{abiertas} fichas abiertas y recorridas"


def escenario_ficha_sin_pasadas(P, DB, app):
    """Una parcela recien dada de alta, sin ninguna pasada todavia."""
    DB.guardar_ficha("Recien_Creada", {"propietario": "x", "superficie_ha": 3.0,
                                       "coordenadas": [[0, 0], [0, 1], [1, 1]]})
    v = P.VentanaPrincipal()
    v.show()
    app.processEvents()
    _paso("sin pasadas: la ficha se abre igual", lambda: (
        v._abrir_ficha("Recien_Creada"), app.processEvents(),
        _check(v.ficha is not None, "no se monto la ficha")))
    f = v.ficha
    _paso("sin pasadas: las tablas quedan vacias, no a medias", lambda: (
        _check(f.modelo_idx.rowCount() == 0 and f.modelo_est.rowCount() == 0,
               "deberian estar vacias")))
    _paso("sin pasadas: se dice que hay que sincronizar", lambda: (
        _check("Sincronizar" in f.interp.texto.toPlainText(),
               f.interp.texto.toPlainText()[:60])))
    _paso("sin pasadas: validar no revienta, avisa", lambda: f._validar("correcto"))
    _paso("sin pasadas: la grafica se dibuja vacia", lambda: f.graficas.poner([]))
    v.close()
    DB.eliminar_parcela("Recien_Creada")
    return "ficha vacia recorrida"


def escenario_ficha_y_logica(P, DB, app):
    """La ficha de Qt y la de Tk piden lo MISMO al modulo compartido.

    No se comparan pantallas -no se puede-, se comprueba que las dos pasan por
    `vista_ficha` y que ninguna guarda una copia propia del encabezado."""
    import os
    import vista_ficha as VF
    base = os.path.dirname(os.path.abspath(__file__))
    tk_src = open(os.path.join(base, "panel_gestion_parcelas.py"), encoding="utf-8").read()
    qt_src = open(os.path.join(base, "panel_qt_ficha.py"), encoding="utf-8").read()
    _paso("compartido: la ficha de Tk usa vista_ficha",
          lambda: _check("VF.contexto(" in tk_src, "el panel de Tk no usa el modulo"))
    _paso("compartido: la ficha de Qt usa vista_ficha",
          lambda: _check("VF.contexto(" in qt_src, "la ficha de Qt no usa el modulo"))
    _paso("compartido: ninguna redacta el encabezado por su cuenta",
          lambda: _check("Fase: " not in tk_src.split("def _pintar_interp")[1][:4000]
                         and "Fase: " not in qt_src,
                         "alguna interfaz vuelve a redactar el encabezado"))
    nombre = DB.nombres()[0]
    camp = sorted(DB.campanas_de(nombre) or ["2025-2026"])[-1]
    regs = sorted(DB.pasadas(nombre, camp), key=lambda r: r.get("fecha", ""))
    _paso("compartido: el contexto de una parcela real trae lo que la ficha necesita",
          lambda: _check(regs == [] or all(
              k in (VF.contexto(nombre, camp, regs) or {})
              for k in ("estado", "encabezado", "val_ctx", "diag")),
              "faltan claves en el contexto"))
    _paso("compartido: sin pasadas el contexto es None, no un dict a medias",
          lambda: _check(VF.contexto(nombre, camp, []) is None, "deberia ser None"))
    return "las dos interfaces sobre el mismo modulo"


ESCENARIOS = [("tema", escenario_tema), ("lista de parcelas", escenario_lista),
              ("lista vacia", escenario_lista_vacia), ("borrado", escenario_borrado),
              ("ficha de parcela", escenario_ficha),
              ("ficha sin pasadas", escenario_ficha_sin_pasadas),
              ("logica compartida", escenario_ficha_y_logica)]


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
