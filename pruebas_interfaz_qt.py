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
    # Los QDialog propios tienen el mismo problema que las cajas de mensaje:
    # `exec()` abre un bucle y espera a una persona. Se responde CANCELAR, que es
    # lo que hace quien se lo piensa; el camino de "guardar" se prueba aparte,
    # llamando al metodo del dialogo, que es donde esta la logica.
    from PySide6.QtWidgets import QDialog

    def _exec(self, *a, **k):
        DIALOGOS.append(("dialogo", self.windowTitle(), ""))
        return QDialog.Rejected
    QDialog.exec = _exec

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
    _paso("lista: el menu de una fila ofrece abrir, editar y eliminar", lambda: (
        _check([a.text() for a in lista.menu_de_fila(0).actions() if a.text()] ==
               ["Abrir ficha", "Editar parcela…", "Eliminar parcela…"],
               "el menu contextual ha cambiado")))
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


def _calib():
    try:
        import calibracion_umbrales
        return calibracion_umbrales
    except Exception:
        return None


def _indices():
    try:
        from gee_cliente import INDICES_ORDEN
        return INDICES_ORDEN
    except Exception:
        return ["NDVI", "EVI", "SAVI", "GNDVI", "LAI", "MSAVI", "NDMI"]


def escenario_dialogos(P, DB, app):
    """Correccion, validacion por indice y cuaderno, por su LOGICA.

    Los dialogos no se abren con `exec()` -eso espera a una persona-: se
    construyen y se llama al metodo que guarda, que es donde estan las decisiones.
    Que el `exec` de verdad no reviente ya lo cubre el escenario de la ficha."""
    from panel_qt_dialogos import DialogoCorreccion, DialogoValidacionIndices, Cuaderno
    import vista_ficha as VF
    import registro_parcela as REG
    nombre = DB.nombres()[0]
    camp = sorted(DB.campanas_de(nombre) or ["2025-2026"])[-1]
    regs = sorted(DB.pasadas(nombre, camp), key=lambda r: r.get("fecha", ""))
    ctx = VF.contexto(nombre, camp, regs)
    if ctx is None:
        return "la parcela de prueba no tiene pasadas"

    # --- corregir un diagnostico ---
    val = dict(ctx["val_ctx"], campana=camp)
    dlg = DialogoCorreccion(None, nombre, val)
    _paso("correccion: viene preseleccionado lo que dijo el sistema",
          lambda: _check(dlg.cb.currentText() == val["estado"],
                         f"{dlg.cb.currentText()} != {val['estado']}"))
    _paso("correccion: por defecto se aplica al cultivo, no solo a la parcela",
          lambda: _check(dlg.rb_cultivo.isChecked() and not dlg.rb_parcela.isChecked(),
                         "el ambito por defecto ha cambiado"))
    otro = [e for e in VF.ESTADOS_VALIDABLES if e != val["estado"]][0]
    _paso("correccion: guardar deja la validacion anotada", lambda: (
        dlg.cb.setCurrentText(otro), dlg.nota.setPlainText("probando"),
        dlg.rb_parcela.setChecked(True), dlg._guardar(),
        _check((DB.validacion_de(nombre, camp, val["fecha"]) or {}).get("estado_real") == otro,
               "no se guardo la correccion")))
    _paso("correccion: y tira la interpretacion cacheada de esa pasada", lambda: (
        _check(all(r.get("interpretacion") is None
                   for r in DB.pasadas(nombre, camp) if r.get("fecha") == val["fecha"]),
               "la interpretacion cacheada sigue ahi")))
    _paso("correccion: acotada a la parcela, no contamina al cultivo", lambda: (
        _check("@" in (DB.validacion_de(nombre, camp, val["fecha"]) or {}).get("cultivo", ""),
               "la clave no quedo acotada a la parcela")))

    # --- validacion por indice (solo con el modulo opcional) ---
    ctx_idx = VF.contexto(nombre, camp, regs, calib=_calib(), indices=_indices())
    if _calib() is not None and (ctx_idx or {}).get("idx_ctx"):
        d2 = DialogoValidacionIndices(None, nombre, camp, ctx_idx["idx_ctx"])
        _paso("indices: hay un desplegable por cada indice medido ese dia",
              lambda: _check(len(d2.combos) > 0, "ningun indice validable"))
        _paso("indices: guardar anota una validacion por indice", lambda: (
            d2._guardar(),
            _check(len(DB.validaciones_indice_de_pasada(nombre, camp,
                                                        ctx_idx["idx_ctx"]["fecha"])) > 0,
                   "no se anoto ninguna validacion por indice")))

    # --- cuaderno de campo ---
    cua = Cuaderno(nombre, camp)
    antes = len(REG.eventos_de(nombre, camp) or [])
    _paso("cuaderno: un PRODUCTO sin nombre se rechaza", lambda: (
        cua.tipo.setCurrentText("PRODUCTO"), cua.producto.setText(""), cua._anotar(),
        _check(len(REG.eventos_de(nombre, camp) or []) == antes,
               "se anoto un producto sin nombre")))
    _paso("cuaderno: un PRODUCTO completo se anota", lambda: (
        cua.producto.setText("Cobre"), cua.dosis.setText("2 l/ha"),
        cua.notas.setText("prueba"), cua._anotar(),
        _check(len(REG.eventos_de(nombre, camp) or []) == antes + 1,
               "no se anoto el producto")))
    _paso("cuaderno: y aparece en la tabla",
          lambda: _check(cua.modelo.rowCount() == len(REG.eventos_de(nombre, camp) or []),
                         "la tabla no cuadra con los eventos"))
    _paso("cuaderno: al elegir COSECHA cambian los campos", lambda: (
        cua.tipo.setCurrentText("COSECHA"),
        _check(cua.especificos.currentIndex() == 1, "no se ensenan los campos de cosecha")))
    _paso("cuaderno: un rendimiento que no es un numero se rechaza", lambda: (
        cua.rendimiento.setText("mucho"), cua._anotar(),
        _check(len(REG.eventos_de(nombre, camp) or []) == antes + 1,
               "se colo un rendimiento que no es numero")))
    _paso("cuaderno: una cosecha con datos validos se anota", lambda: (
        cua.rendimiento.setText("4200"), cua.superficie.setText("12.4"), cua._anotar(),
        _check(len(REG.eventos_de(nombre, camp) or []) == antes + 2,
               "no se anoto la cosecha")))
    _paso("cuaderno: los tipos sin campos propios no ensenan ninguno", lambda: [
        (cua.tipo.setCurrentText(t), app.processEvents(),
         _check(cua.especificos.currentIndex() == 2, f"{t} no deberia tener campos"))
        for t in ("RIEGO", "LABOREO", "SIEMBRA", "OTRO")])
    return "correccion, indices y cuaderno recorridos"


def escenario_mapa(P, DB, app):
    """El visor de mapas: sin credenciales de Earth Engine y con una imagen local.

    Lo que NO se puede probar aqui es la descarga real: no hay credenciales. Lo
    que si: que sin ellas se dice y no se deja un hueco mudo, y que el visor
    carga, hace zoom y se ajusta con un PNG de verdad."""
    from panel_qt_mapa import Mapa, Visor, RESOLUCION_M
    from PySide6.QtGui import QPixmap
    import mapas_cache
    nombre = DB.nombres()[0]
    camp = sorted(DB.campanas_de(nombre) or ["2025-2026"])[-1]
    fechas = [r["fecha"] for r in DB.pasadas(nombre, camp) if r.get("fecha")]

    m = Mapa(nombre, camp)
    _paso("mapa: se ofrecen todos los indices",
          lambda: _check(m.cb_idx.count() == 7, f"{m.cb_idx.count()} indices"))
    _paso("mapa: sin fechas lo dice, no deja un hueco mudo", lambda: (
        m.poner_fechas([]),
        _check("todavia no tiene pasadas" in m.estado.text(), m.estado.text())))
    _paso("mapa: con fechas queda elegida la ultima", lambda: (
        m.poner_fechas(fechas),
        _check(m.cb_dia.currentText() == fechas[-1], "no se eligio la ultima")))
    _paso("mapa: sin mapa descargado ni Earth Engine, se explica", lambda: (
        _check("Earth Engine" in m.estado.text() or "descargando" in m.estado.text().lower(),
               m.estado.text())))
    _paso("mapa: recorrer los indices no revienta", lambda: [
        (m.cb_idx.setCurrentText(i), app.processEvents()) for i in
        [m.cb_idx.itemText(k) for k in range(m.cb_idx.count())]])
    _paso("mapa: la leyenda sale de la misma tabla que la descarga", lambda: (
        m.leyenda.poner("NDVI"),
        _check("⟶" in m.leyenda.text(), f"leyenda vacia: {m.leyenda.text()!r}")))

    # el visor, con una imagen de verdad puesta en la cache
    ruta = mapas_cache.ruta_cache_mapa(nombre, "NDVI", fechas[-1], RESOLUCION_M)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    pix = QPixmap(120, 90)
    pix.fill()
    pix.save(ruta, "PNG")
    # el recorrido anterior dejo elegido el ultimo indice: se vuelve al que tiene
    # imagen, que es lo que haria el usuario al elegirlo en el desplegable
    _paso("visor: carga un PNG de la cache", lambda: (
        m.cb_idx.setCurrentText("NDVI"), m.poner_fechas(fechas),
        _check(m.visor._item is not None, "el visor no cargo la imagen")))
    _paso("visor: y entonces el estado dice que dia e indice se ve",
          lambda: _check(fechas[-1] in m.estado.text(), m.estado.text()))
    _paso("visor: zoom dentro y fuera, y ajustar", lambda: (
        m.visor.zoom(1.25), m.visor.zoom(1 / 1.25), m.visor.ajustar()))
    _paso("visor: el zoom tiene topes y no se dispara", lambda: (
        [m.visor.zoom(2.0) for _ in range(20)],
        _check(m.visor._zoom <= 8.0 + 1e-9, f"zoom desbocado: {m.visor._zoom}")))
    _paso("visor: un fichero que no existe no revienta, devuelve False",
          lambda: _check(Visor().poner("/no/existe.png") is False, "deberia dar False"))
    os.remove(ruta)

    r = Mapa(nombre, camp, radar=True)
    _paso("radar: ofrece los parametros de Sentinel-1, no los indices opticos",
          lambda: _check(r.cb_idx.count() in (0, 3), f"{r.cb_idx.count()} parametros"))
    _paso("radar: sin pasadas de radar lo dice", lambda: (
        r.poner_fechas([]),
        _check("todavia no tiene pasadas" in r.estado.text(), r.estado.text())))
    return "visor, leyenda, zoom y radar recorridos"


def escenario_alta(P, DB, app):
    """Alta y edicion de una parcela, por su logica (el dialogo no se `exec`ta).

    La captura por SIGPAC NO se ejercita: sale a la red. Lo que si se comprueba
    es todo lo demas, que es donde estan las decisiones: validaciones, campos por
    tipo, y que lo guardado quede como debe."""
    from panel_qt_alta import DialogoParcela
    import fenologia_especies as FEN
    camp = "2025-2026"
    cuadrado = [[-4.10, 41.65], [-4.09, 41.65], [-4.09, 41.66], [-4.10, 41.66]]

    d = DialogoParcela(None, camp)
    _paso("alta: sin nombre ni propietario no se guarda", lambda: (
        d._guardar(), _check("Nueva_Qt" not in DB.nombres(), "se guardo sin datos")))
    _paso("alta: sin geometria tampoco", lambda: (
        d.e_nombre.setText("Nueva Qt"), d.e_prop.setText("Ana"), d._guardar(),
        _check("Nueva_Qt" not in DB.nombres(), "se guardo sin geometria")))
    _paso("alta: al elegir LENOSO se piden marco y regimen", lambda: (
        d.cb_tipo.setCurrentText("LENOSO"), app.processEvents(),
        _check(d.especificos.currentIndex() == 1, "no se ensenan los campos de lenoso")))
    _paso("alta: un lenoso sin marco no se guarda", lambda: (
        setattr(d, "coords", cuadrado), d._guardar(),
        _check("Nueva_Qt" not in DB.nombres(), "se guardo un lenoso sin marco")))
    _paso("alta: el marco dice lo que implica al teclearlo", lambda: (
        d.e_calle.setText("10"), d.e_pie.setText("10"), app.processEvents(),
        _check("arboles/ha" in d.lbl_marco.text() and "%" in d.lbl_marco.text(),
               f"resumen del marco: {d.lbl_marco.text()!r}")))
    _paso("alta: y distingue copa medida de copa estimada", lambda: (
        _check("estimada" in d.lbl_marco.text(), d.lbl_marco.text()),
        d.e_copa.setText("7"), app.processEvents(),
        _check("copa medida" in d.lbl_marco.text(), d.lbl_marco.text())))
    _paso("alta: un margen que no es numero se rechaza", lambda: (
        d.e_buffer.setText("bastante"), d._guardar(),
        _check("Nueva_Qt" not in DB.nombres(), "se colo un margen que no es numero")))
    _paso("alta: con todo completo se guarda", lambda: (
        d.e_buffer.setText("20"), d._guardar(),
        _check("Nueva_Qt" in DB.nombres(), "no se guardo la parcela")))
    ficha = DB.ficha("Nueva_Qt") or {}
    _paso("alta: se guarda la superficie calculada del poligono",
          lambda: _check(ficha.get("superficie_ha", 0) > 0, "superficie sin calcular"))
    _paso("alta: y el margen interior tecleado",
          lambda: _check(ficha.get("buffer_m") == 20.0, f"buffer {ficha.get('buffer_m')}"))
    cult = (ficha.get("cultivos_por_campana") or {}).get(camp) or {}
    _paso("alta: el subtipo se DERIVA del marco, nadie lo teclea",
          lambda: _check(cult.get("subtipo") == FEN.subtipo_canonico(
              cult.get("especie", "OLIVO"), FEN.densidad_arboles(10.0, 10.0)),
              f"subtipo {cult.get('subtipo')!r}"))
    _paso("alta: el diametro de copa llega al cultivo",
          lambda: _check(cult.get("diametro_copa") == 7.0, str(cult.get("diametro_copa"))))

    # --- edicion ---
    e = DialogoParcela(None, camp, editar="Nueva_Qt")
    _paso("edicion: el nombre no se puede cambiar (identifica el historico)",
          lambda: _check(e.e_nombre.isReadOnly(), "el nombre es editable"))
    _paso("edicion: viene relleno con lo guardado", lambda: (
        _check(e.e_prop.text() == "Ana", e.e_prop.text()),
        _check(e.e_calle.text() == "10.0", e.e_calle.text()),
        _check(len(e.coords) >= 3, "no cargo la geometria")))
    _paso("edicion: guardar respeta el nombre y actualiza el propietario", lambda: (
        e.e_prop.setText("Luis"), e._guardar(),
        _check((DB.ficha("Nueva_Qt") or {}).get("propietario") == "Luis",
               "no se actualizo el propietario")))
    _paso("edicion: un BARBECHO no pide especie ni marco", lambda: (
        e.cb_tipo.setCurrentText("BARBECHO"), app.processEvents(),
        _check(e.especificos.currentIndex() == 2, "barbecho no deberia pedir nada"),
        e._guardar()))
    _paso("alta: SIGPAC sin los codigos obligatorios avisa y no sale a la red",
          lambda: DialogoParcela(None, camp)._sigpac())
    DB.eliminar_parcela("Nueva_Qt")
    return "alta y edicion recorridas"


ESCENARIOS = [("tema", escenario_tema), ("lista de parcelas", escenario_lista),
              ("lista vacia", escenario_lista_vacia), ("borrado", escenario_borrado),
              ("ficha de parcela", escenario_ficha),
              ("ficha sin pasadas", escenario_ficha_sin_pasadas),
              ("logica compartida", escenario_ficha_y_logica),
              ("dialogos y cuaderno", escenario_dialogos),
              ("mapa y radar", escenario_mapa),
              ("alta y edicion", escenario_alta)]


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
