# -*- coding: utf-8 -*-
"""
pruebas_interfaz.py
===================

Pruebas de la INTERFAZ. Complementan a `pruebas.py`, que corre a proposito sin
pantalla y por eso no ve nada de lo que pasa dentro de Tk.

Que hace: monta la aplicacion de verdad (ventana principal, ficha, dialogos),
pulsa botones, teclea en los campos, lanza los eventos de raton y espera a los
hilos. Cualquier excepcion cuenta como fallo, INCLUIDAS las que Tk se traga
dentro de un callback: ahi es donde se escondian los fallos que no se veian.

Como se ejecuta
---------------
    python pruebas_interfaz.py                 # con pantalla (Windows/macOS/Linux)
    xvfb-run -a python pruebas_interfaz.py     # en un servidor sin pantalla

Necesita tkinter y matplotlib. Si falta tkinter o no hay pantalla, se omite
entera y devuelve 0: no rompe una tuberia de integracion continua.

Es un fichero SUELTO: borralo y no se pierde nada mas que estas pruebas.

Limitaciones (para no dar una falsa sensacion de cobertura)
----------------------------------------------------------
  - No comprueba el ASPECTO: que no reviente no significa que se vea bien.
  - No habla con Earth Engine ni con OpenAI: esas llamadas se sustituyen.
  - Tk no deja generar <Double-1> ni un <KeyRelease> sin `keysym`; donde hace
    falta se invoca el manejador enlazado.
  - Casi todos los escenarios avanzan con update() en vez de mainloop(), asi que
    un hilo que llame a after() suelta por consola un
        RuntimeError: main thread is not in main loop
    Eso es del arnes, no del programa: con la ventana abierta de verdad hay
    mainloop y after() desde un hilo es correcto. Ya se comprobo que los tres
    sitios que lo hacen (la interpretacion, el radar y la sincronizacion) miran
    winfo_exists antes de pintar. El escenario de cierre SI usa mainloop, que es
    donde esa comprobacion importa.
"""

import os
import sys
import tempfile
import threading
import time
import traceback

FALLOS = []          # (escenario, tipo, mensaje, traza)
DIALOGOS = []        # cajas de mensaje que habria visto quien usa el programa


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
def _anotar(donde, e):
    FALLOS.append((donde, type(e).__name__, str(e), traceback.format_exc()))


def _paso(nombre, fn):
    """Ejecuta un paso y anota el fallo en vez de abortar la tanda."""
    try:
        fn()
        return True
    except Exception as e:
        _anotar(nombre, e)
        return False


def _check(condicion, mensaje):
    """Afirmacion dentro de un `_paso`: si no se cumple, se anota como fallo.

    El arnes mide sobre todo que la interfaz no reviente. Esto permite ademas
    comprobar lo que se ve, sin salirse del mismo mecanismo de anotacion."""
    if not condicion:
        raise AssertionError(mensaje)
    return True


class Evento:
    """Evento sintetico para invocar manejadores que Tk no deja generar."""

    def __init__(self, **kw):
        self.x = self.y = 5
        self.x_root = self.y_root = 50
        self.delta = 0
        self.num = 1
        self.widget = None
        self.__dict__.update(kw)


def _sin_modales():
    """Las cajas de mensaje bloquean el bucle: se sustituyen por un registro."""
    from tkinter import messagebox, filedialog

    def reg(tipo, valor=None):
        def f(titulo="", mensaje="", **kw):
            DIALOGOS.append((tipo, titulo, " ".join(str(mensaje).split())[:90]))
            return valor
        return f
    messagebox.showinfo = reg("info")
    messagebox.showwarning = reg("aviso")
    messagebox.showerror = reg("error")
    messagebox.askyesno = reg("si/no", False)
    messagebox.askokcancel = reg("ok/cancel", False)
    messagebox.askquestion = reg("pregunta", "no")
    filedialog.askopenfilename = lambda **kw: ""
    filedialog.askdirectory = lambda **kw: ""


def _botones(w, out=None):
    out = [] if out is None else out
    try:
        if w.winfo_class() in ("TButton", "Button"):
            out.append((str(w.cget("text")).strip(), w))
    except Exception:
        pass
    for ch in getattr(w, "winfo_children", lambda: [])():
        _botones(ch, out)
    return out


def _teclear(widget, texto, root):
    """Escribe como una persona. OJO: un evento de teclado SIN keysym no se
    despacha, asi que hay que darselo o la busqueda parece que no filtra."""
    import tkinter as tk
    widget.delete(0, tk.END)
    widget.insert(0, texto)
    try:
        widget.focus_force()
    except Exception:
        pass
    widget.event_generate("<KeyRelease>", keysym="a")
    root.update()


def _sembrar():
    """Las parcelas de la demo, mas cosechas de campanas anteriores."""
    import almacen as DB
    import demo_sistema as D
    DB.conectar()
    D.sembrar(D.escenarios())
    for i, kg in enumerate((3900, 4210, 3550)):
        DB.registrar_evento("Cerealista_Vega", f"{2021 + i}-{2022 + i}",
                            {"fecha": f"{2022 + i}-07-05", "tipo": "COSECHA",
                             "rendimiento_kg_ha": float(kg), "humedad_grano_pct": 12.0,
                             "superficie_cosechada_ha": 12.4, "fuente_dato": "bascula"})
    return DB


def _callar_ruido_de_cierre():
    """Silencia SOLO el ruido de derribo del propio arnes.

    Al crear y destruir varias raices de Tk en un mismo proceso, las imagenes de
    matplotlib se recolectan cuando su interprete ya no existe y su __del__
    escupe 'main thread is not in main loop'. No es del programa: es de montar y
    desmontar ventanas seguidas, algo que no pasa en uso normal. Se filtra por
    tipo Y por procedencia (__del__), para no tapar nada real.
    """
    def hook(args):
        nombre = getattr(getattr(args, "object", None), "__name__", "")
        if args.exc_type is RuntimeError and nombre == "__del__":
            return
        sys.__unraisablehook__(args)
    sys.unraisablehook = hook


def _derribar(root):
    """Cancela los temporizadores pendientes ANTES de destruir la ventana.

    Si no, Tcl escupe un 'invalid command name ..._auto_sync' por cada after()
    que quedaba en vuelo (el panel programa el relevo de campana y el autosync
    al arrancar). Es ruido del arnes, que monta y desmonta ventanas seguidas.
    """
    try:
        for tarea in root.tk.call("after", "info"):
            try:
                root.after_cancel(tarea)
            except Exception:
                pass
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


def _raiz():
    """Tk con el cazador de excepciones de callbacks puesto: sin esto, un fallo
    dentro de un callback se va a stderr y la prueba pasaria en falso."""
    import tkinter as tk
    r = tk.Tk()
    r.geometry("1440x900")
    r.report_callback_exception = lambda exc, val, tb: FALLOS.append(
        ("callback de Tk", exc.__name__, str(val),
         "".join(traceback.format_exception(exc, val, tb))))
    return r


# ---------------------------------------------------------------------------
# Escenarios
# ---------------------------------------------------------------------------
def escenario_arranque(P, DB):
    """La ventana principal, tal cual la monta __main__."""
    from tkinter import ttk
    root = _raiz()
    _paso("tema", lambda: P.aplicar_tema(root, escala=1.0))
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    panel = P.PanelGestionParcelas(nb)
    nb.add(panel, text="parcelas")
    _paso("panel de credenciales",
          lambda: nb.add(P.PanelCredenciales(nb, al_cambiar=panel._refrescar), text="cred"))
    _paso("primer dibujado", root.update)
    n = len(panel.tree.get_children())
    _paso("arranque: la lista trae parcelas",
          lambda: (_ for _ in ()).throw(AssertionError("lista vacia")) if n == 0 else None)
    _derribar(root)
    return f"{n} parcelas en la lista"


def escenario_lista(P, DB):
    """Busqueda, orden, cambio de campana, menu contextual y botones."""
    from tkinter import ttk
    root = _raiz()
    P.aplicar_tema(root, escala=1.0)
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    panel = P.PanelGestionParcelas(nb)
    nb.add(panel, text="x")
    root.update()
    total = len(panel.tree.get_children())

    def filas(txt):
        _teclear(panel.entry_buscar, txt, root)
        return len(panel.tree.get_children())

    for txt, condicion, desc in (
            ("ZZZ_no_existe", lambda n: n == 0, "sin resultados"),
            ("'; DROP TABLE parcelas;--", lambda n: n == 0, "comilla y punto y coma"),
            ("%", lambda n: n == 0, "comodin de SQL como texto"),
            ("", lambda n: n == total, "vacio devuelve todo")):
        def _f(txt=txt, condicion=condicion, desc=desc):
            n = filas(txt)
            if not condicion(n):
                raise AssertionError(f"{desc}: {n} filas con {txt!r}")
        _paso(f"busqueda ({desc})", _f)
    filas("")

    for o in panel.cb_orden["values"]:
        _paso(f"orden por {o}", lambda o=o: (
            panel.cb_orden.set(o), panel.cb_orden.event_generate("<<ComboboxSelected>>"),
            root.update()))
    _paso("cambio de campana", lambda: (
        panel.cb_campana.set(panel.cb_campana["values"][0]),
        panel.cb_campana.event_generate("<<ComboboxSelected>>"), root.update()))

    hijos = panel.tree.get_children()
    if hijos:
        panel.tree.selection_set(hijos[0])
        root.update()
        caja = panel.tree.bbox(hijos[0]) or [0, 20]
        _paso("clic derecho en la lista", lambda: (
            panel.tree.event_generate("<Button-3>", x=5, y=caja[1] + 3), root.update()))
        _paso("doble clic abre la ficha", lambda: (
            panel._abrir_ficha_sel(Evento(y=caja[1] + 3)), root.update()))
        _paso("volver a la lista", lambda: (panel.mostrar_lista(), root.update()))

    for texto, b in _botones(panel):
        if "eliminar" in texto.lower():
            continue
        _paso(f"boton '{texto}'", lambda b=b: (b.invoke(), root.update()))
    _paso("relevo de campana", panel._comprobar_relevo_campana)
    _paso("autosincronizacion", panel._auto_sync)
    root.update()
    _derribar(root)
    return f"{total} parcelas, busqueda y orden comprobados"


def escenario_fichas(P, DB):
    """Abre la ficha de CADA parcela y toca todos sus controles."""
    import tkinter as tk
    from tkinter import ttk
    root = _raiz()
    P.aplicar_tema(root, escala=1.0)
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    panel = P.PanelGestionParcelas(nb)
    nb.add(panel, text="x")
    ultima = {}
    original = P.FichaParcela.__init__

    def capturar(self, *a, **k):        # mostrar_ficha no guarda la instancia
        ultima["f"] = self
        return original(self, *a, **k)
    P.FichaParcela.__init__ = capturar
    root.update()

    abiertas = 0
    for nombre in DB.nombres():
        if not _paso(f"ficha '{nombre}'", lambda n=nombre: (panel.mostrar_ficha(n), root.update())):
            continue
        abiertas += 1
        f = ultima.get("f")
        if f is None:
            continue
        _paso(f"{nombre}: refrescar", lambda f=f: (f.refrescar(), root.update()))
        _paso(f"{nombre}: cambiar de dia", lambda f=f: (
            f.cb_dia.current(0) if f.cb_dia["values"] else None,
            f.cb_dia.event_generate("<<ComboboxSelected>>"), root.update()))
        _paso(f"{nombre}: cada indice del mapa", lambda f=f: [
            (f.cb_idx.set(v), f.cb_idx.event_generate("<<ComboboxSelected>>"), root.update())
            for v in f.cb_idx["values"]])
        _paso(f"{nombre}: marcar indices de la grafica", lambda f=f: [
            (v.set(not v.get()), f._replot(), root.update())
            for v in getattr(f, "idx_vars", {}).values()])
        _paso(f"{nombre}: menu del cuaderno", lambda f=f: (
            f._menu_evento(Evento(y=(f.tv_ev.bbox(f.tv_ev.get_children()[0]) or [0, 20])[1] + 2))
            if f.tv_ev.get_children() else None, root.update()))
        _paso(f"{nombre}: ver efecto", lambda f=f: (f._ver_efecto_evento(), root.update()))
        _paso(f"{nombre}: correccion", lambda f=f: (f._abrir_correccion(), root.update()))
        _paso(f"{nombre}: validar", lambda f=f: (f._validar("correcto"), root.update()))
        _paso(f"{nombre}: comparar mapas", lambda f=f: (f._comparar_mapas(), root.update()))
        _paso(f"{nombre}: menu exportar", lambda f=f: (f._menu_exportar(), root.update()))
        _paso(f"{nombre}: campanas anteriores",
              lambda f=f: (f._sincronizar_anteriores(), root.update()))
        lz = getattr(f, "lienzo", None)
        if lz is not None:
            cv = lz.canvas
            for ev, kw in (("<MouseWheel>", {"delta": 120}), ("<MouseWheel>", {"delta": -120}),
                           ("<Button-4>", {}), ("<Button-5>", {}),
                           ("<ButtonPress-1>", {"x": 40, "y": 40}),
                           ("<B1-Motion>", {"x": 90, "y": 70}),
                           ("<ButtonRelease-1>", {"x": 90, "y": 70})):
                _paso(f"{nombre}: mapa {ev}",
                      lambda e=ev, k=kw: (cv.event_generate(e, **k), root.update()))
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel):
                w.destroy()
        root.update()
    P.FichaParcela.__init__ = original
    _derribar(root)
    return f"{abiertas} fichas abiertas y recorridas"


def escenario_cuaderno(P, DB):
    """Cosecha por la interfaz: campana en curso, campana anterior y dato invalido."""
    import tkinter as tk
    from tkinter import ttk
    root = _raiz()
    P.aplicar_tema(root, escala=1.0)
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    panel = P.PanelGestionParcelas(nb)
    nb.add(panel, text="x")
    ultima = {}
    original = P.FichaParcela.__init__
    P.FichaParcela.__init__ = lambda s, *a, **k: (ultima.__setitem__("f", s),
                                                  original(s, *a, **k))[1]
    root.update()
    NOM = "Cerealista_Vega"                     # extensivo de grano
    panel.mostrar_ficha(NOM)
    root.update()
    f = ultima["f"]

    def anotar_cosecha(fecha, kg, humedad):
        f.ev_tipo.set("COSECHA")
        f.ev_tipo.event_generate("<<ComboboxSelected>>")
        root.update()
        f.ev_fecha.set_iso(fecha)
        f._toggle_campos_evento()
        root.update()
        visible = bool(f.frame_humedad.winfo_ismapped())
        f.ev_rend.delete(0, tk.END); f.ev_rend.insert(0, kg)
        f.ev_humedad.delete(0, tk.END); f.ev_humedad.insert(0, humedad)
        f.ev_fuente.set("bascula")
        f._add_evento()
        root.update()
        return visible

    antes = len(DB.rendimientos(NOM))

    def _actual():
        if not anotar_cosecha("2026-07-05", "4500", "12,5"):
            raise AssertionError("en trigo la humedad del grano deberia pedirse")
    _paso("cosecha de la campana en curso", _actual)

    def _vieja():
        # campana sin cultivo declarado: la humedad se hereda de la campana vista
        if not anotar_cosecha("2019-07-01", "3800", "11,5"):
            raise AssertionError("al cargar historico la humedad debe seguir pidiendose")
    _paso("cosecha de una campana anterior", _vieja)

    def _invalida():
        anotar_cosecha("2026-07-06", "cuatro mil", "12")
        if len(DB.rendimientos(NOM)) != antes + 2:
            raise AssertionError("un rendimiento no numerico no debe guardarse")
    _paso("cosecha con texto no numerico", _invalida)

    _paso("la lista de rendimientos se rellena",
          lambda: (_ for _ in ()).throw(AssertionError("lista vacia"))
          if f.lst_rend.size() == 0 else None)

    # el alto del cuaderno NO puede depender de cuantas campanas haya
    alto1 = f.lst_rend.master.winfo_reqheight()
    for i in range(12):
        DB.registrar_evento(NOM, f"{2000 + i}-{2001 + i}",
                            {"fecha": f"{2001 + i}-07-01", "tipo": "COSECHA",
                             "rendimiento_kg_ha": 4000.0 + i})
    f._refrescar_rendimientos()
    root.update()
    alto2 = f.lst_rend.master.winfo_reqheight()
    _paso("el historico largo no estira el cuaderno",
          lambda: (_ for _ in ()).throw(
              AssertionError(f"el bloque crecio de {alto1} a {alto2} px"))
          if alto2 != alto1 else None)
    P.FichaParcela.__init__ = original
    _derribar(root)
    return f"{len(DB.rendimientos(NOM))} rendimientos, alto estable ({alto1} px)"


def escenario_validacion_indices(P, DB):
    """Desplegable de pasadas anteriores y validacion indice a indice.

    Todo esto cuelga del modulo OPCIONAL calibracion_umbrales: si no esta, el
    escenario se salta y la suite sigue verde."""
    if getattr(P, "_CALIB", None) is None:
        return "se omite (sin calibracion_umbrales)"
    from tkinter import ttk
    CAL = P._CALIB
    root = _raiz()
    P.aplicar_tema(root, escala=1.0)
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    panel = P.PanelGestionParcelas(nb)
    nb.add(panel, text="x")
    ultima = {}
    original = P.FichaParcela.__init__
    P.FichaParcela.__init__ = lambda s, *a, **k: (ultima.__setitem__("f", s),
                                                  original(s, *a, **k))[1]
    root.update()

    NOM = "Cerealista_Vega"
    # se le pone ubicacion para que existan los cuatro ambitos
    ficha = DB.ficha(NOM) or {}
    ficha.update({"provincia": "47", "municipio": "47/186",
                  "sigpac": {"Prov": "47", "Mun": "186", "Pol": "3", "Par": "12", "Rec": "1"}})
    DB.guardar_ficha(NOM, ficha)
    panel.mostrar_ficha(NOM)
    root.update()
    f = ultima["f"]

    n_pasadas = len(DB.pasadas(NOM, panel.campana))
    _paso("el desplegable lista todas las pasadas",
          lambda: (_ for _ in ()).throw(AssertionError(
              f"{len(f.cb_interp['values'])} opciones para {n_pasadas} pasadas"))
          if len(f.cb_interp["values"]) != n_pasadas else None)
    _paso("por defecto se muestra la ultima",
          lambda: (_ for _ in ()).throw(AssertionError("no arranca en la ultima"))
          if f.cb_interp.current() != n_pasadas - 1 else None)

    # recorrer TODAS las pasadas anteriores: cada una se reinterpreta
    def _recorrer():
        for i in range(n_pasadas):
            f.cb_interp.current(i)
            f._cambiar_pasada_interp()
            root.update()
            if f._val_ctx["fecha"] != sorted(
                    r["fecha"] for r in DB.pasadas(NOM, panel.campana))[i]:
                raise AssertionError(f"la pasada {i} no interpreta su propio dia")
    _paso("cada pasada del desplegable interpreta SU dia", _recorrer)

    # validar la primera pasada indice a indice
    f.cb_interp.current(0)
    f._cambiar_pasada_interp()
    root.update()
    fecha0 = f._val_ctx["fecha"]
    dlg = {}
    _paso("abre el dialogo de validacion por indice",
          lambda: dlg.__setitem__("v", P.DialogoValidacionIndices(root, f, f._idx_ctx)))
    v = dlg.get("v")
    if v is not None:
        root.update()
        _paso("hay un desplegable por cada indice medido",
              lambda: (_ for _ in ()).throw(AssertionError("ningun indice en el dialogo"))
              if not v.combos else None)
        _paso("viene preseleccionado con lo que ve el sistema",
              lambda: (_ for _ in ()).throw(AssertionError("desplegable vacio"))
              if any(c.get() not in CAL.ESTADOS for c in v.combos.values()) else None)
        _paso("ofrece los cuatro ambitos",
              lambda: (_ for _ in ()).throw(AssertionError(f"{v.ambitos}"))
              if len(v.ambitos) != 4 else None)
        _paso("guardar anota las validaciones", lambda: (v._guardar(), root.update()))
        guardadas = DB.validaciones_indice_de_pasada(NOM, panel.campana, fecha0)
        _paso("quedan guardadas en la base",
              lambda: (_ for _ in ()).throw(AssertionError("no se guardo nada"))
              if not guardadas else None)
        _paso("la pasada validada sale marcada en el desplegable",
              lambda: (f.refrescar(), root.update(),
                       (_ for _ in ()).throw(AssertionError("sin marca ✓"))
                       if not str(f.cb_interp["values"][0]).startswith("✓") else None))
    # --- casilla de analisis de zonas: apaga el aviso, no el dato, y persiste
    _paso("la casilla de zonas viene encendida",
          lambda: (_ for _ in ()).throw(AssertionError("deberia venir marcada"))
          if not f.var_hetero.get() else None)

    def _apagar_zonas():
        f.var_hetero.set(False)
        f._cambiar_heterogeneidad()
        root.update()
        if DB.ficha(NOM).get("heterogeneidad") is not False:
            raise AssertionError("no se guardo el apagado")
    _paso("apagarla se guarda con la parcela", _apagar_zonas)

    def _sobrevive():
        panel.mostrar_ficha(NOM)
        root.update()
        if ultima["f"].var_hetero.get():
            raise AssertionError("al reabrir la ficha vuelve a salir encendida")
    _paso("sigue apagada al reabrir la ficha", _sobrevive)

    def _encender():
        g = ultima["f"]
        g.var_hetero.set(True)
        g._cambiar_heterogeneidad()
        root.update()
        if DB.ficha(NOM).get("heterogeneidad") is not True:
            raise AssertionError("no se guardo el encendido")
    _paso("y se puede volver a encender", _encender)

    P.FichaParcela.__init__ = original
    _derribar(root)
    return f"{n_pasadas} pasadas recorridas y validadas"


def escenario_campanas(P, DB):
    """El selector de campana de la ficha: cambiar de ano y llegar al archivo.

    Sin Earth Engine no se descarga nada, que es justo lo que interesa comprobar:
    elegir una campana sin datos tiene que abrir la ficha vacia igualmente, no
    quedarse a medias porque no haya red."""
    import tkinter as tk
    from tkinter import ttk
    from campanas import campana_actual, PRIMERA_CAMPANA_S2
    root = _raiz()
    P.aplicar_tema(root, escala=1.0)
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    panel = P.PanelGestionParcelas(nb)
    nb.add(panel, text="x")
    ultima = {}
    original = P.FichaParcela.__init__

    def capturar(self, *a, **k):
        ultima["f"] = self
        return original(self, *a, **k)
    P.FichaParcela.__init__ = capturar
    root.update()

    nombre = DB.nombres()[0]
    # una campana MAS ANTIGUA que Sentinel-2: es el caso de "tengo datos que el
    # programa ya no puede volver a pedir"
    DB.anadir_pasadas(nombre, "2013-2014", [{"fecha": "2014-04-10", "ndvi": 0.44}])
    panel.mostrar_ficha(nombre)
    root.update()
    f = ultima["f"]

    cambios = 0
    _paso("campanas: el desplegable existe y lista mas de una",
          lambda: (_check(len(f.cb_campana_ficha["values"]) > 1,
                          "el selector de campana no ofrece campanas anteriores")))
    _paso("campanas: la campana en curso viene seleccionada",
          lambda: _check(campana_actual() in f.cb_campana_ficha.get(),
                         f"la ficha no abre en la campana en curso: {f.cb_campana_ficha.get()!r}"))
    _paso("campanas: el archivo anterior al satelite esta en la lista",
          lambda: _check(any("2013-2014" in v for v in f.cb_campana_ficha["values"]),
                         "una campana guardada fuera del alcance del satelite no se ofrece"))
    _paso("campanas: y se marca como solo archivo",
          lambda: _check(any("2013-2014" in v and "archivo" in v
                             for v in f.cb_campana_ficha["values"]),
                         "la campana de archivo no se distingue de una descargable"))

    def ir_a(texto):
        f2 = ultima["f"]
        vals = list(f2.cb_campana_ficha["values"])
        i = next(k for k, v in enumerate(vals) if texto in v)
        f2.cb_campana_ficha.current(i)
        f2.cb_campana_ficha.event_generate("<<ComboboxSelected>>")
        root.update()

    for destino in ("2013-2014", PRIMERA_CAMPANA_S2, campana_actual()):
        if _paso(f"campanas: cambiar a {destino}", lambda d=destino: ir_a(d)):
            cambios += 1
            _paso(f"campanas: la ficha queda en {destino}",
                  lambda d=destino: _check(panel.campana == d,
                                           f"se pidio {d} y el panel esta en {panel.campana}"))
    _paso("campanas: el dialogo de descarga se abre con la lista nueva",
          lambda: (ultima["f"]._sincronizar_anteriores(), root.update()))
    for w in root.winfo_children():
        if isinstance(w, tk.Toplevel):
            w.destroy()
    P.FichaParcela.__init__ = original
    _derribar(root)
    return f"{cambios} cambios de campana, archivo incluido"


def escenario_dialogos(P, DB):
    """Cada ventana secundaria: se abre, se toca y se cierra."""
    import tkinter as tk
    from tkinter import ttk
    root = _raiz()
    P.aplicar_tema(root, escala=1.0)
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    panel = P.PanelGestionParcelas(nb)
    nb.add(panel, text="x")
    root.update()
    NOM = "Cerealista_Vega"
    CAMP = panel.campana
    regs = sorted(DB.pasadas(NOM, CAMP), key=lambda r: r.get("fecha", ""))

    def cerrar():
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel):
                try:
                    w.destroy()
                except Exception:
                    pass
        root.update()

    abiertas = []

    def abrir(nombre, fabrica, luego=None):
        def _ir():
            v = fabrica()
            root.update()
            if luego:
                luego(v)
                root.update()
        # se cuenta lo que de verdad se ha abierto: el numero iba escrito a mano y
        # se quedo desfasado al anadir ventanas nuevas
        abiertas.append(nombre)
        _paso(nombre, _ir)
        cerrar()

    def _fecha():
        top = tk.Toplevel(root)
        c = P.CampoFecha(top, iso="2026-04-15")
        c.pack()
        root.update()
        for txt in ("15-04-2026", "31-02-2026", "aa-bb-cccc", "", "1-1-26"):
            _teclear(c.entry, txt, root)
            c.get_iso()
            c.esta_vacio()
        c._abrir_cal()
        return c
    abrir("CampoFecha y calendario", _fecha)

    def _alta_con_margen():
        v = P.VentanaAltaParcela(panel)
        root.update()
        # el margen interior de la rejilla se teclea aqui; vacio = el de por defecto
        v.e_buffer.insert(0, "25")
        if not v.e_buffer.get():
            raise AssertionError("no hay campo de margen interior")
        return v
    abrir("alta de parcela con margen interior", _alta_con_margen,
          lambda v: v._guardar())

    def _alta_con_copa():
        """El marco y el diametro de copa, y lo que el formulario ENSEÑA con ellos.

        El campo de copa es opcional, pero es el que quita la suposicion gruesa de
        estimarla del marco; y el texto que sale debajo es donde el usuario se
        entera de que fraccion de suelo tapa, que es lo que traduce los umbrales."""
        v = P.VentanaAltaParcela(panel)
        root.update()
        v.cb_tipo.set("LENOSO")
        v._sub()
        v.cb_sub.set("OLIVO")
        root.update()
        _teclear(v.e_calle, "10", root)
        _teclear(v.e_pie, "10", root)
        v._calc_marco()
        root.update()
        estimada = v.lbl_tipo_calc.cget("text")
        _check("arboles/ha" in estimada, f"el marco no dice la densidad: {estimada!r}")
        _check("%" in estimada, f"el marco no dice cuanto suelo tapa la copa: {estimada!r}")
        _check("estimada" in estimada, f"no avisa de que la copa es estimada: {estimada!r}")
        _teclear(v.e_copa, "7", root)
        v._calc_marco()
        root.update()
        medida = v.lbl_tipo_calc.cget("text")
        _check("copa medida" in medida, f"con copa tecleada sigue diciendo estimada: {medida!r}")
        _check(medida != estimada, "teclear la copa no cambia lo que se ensena")
        return v
    abrir("alta de parcela con diametro de copa", _alta_con_copa,
          lambda v: v._guardar())

    def _alta_marco_negativo():
        """Un guion de mas al teclear el marco NO puede colarse.

        Aguas abajo daba una fraccion de copa negativa y un umbral de casi cero:
        la parcela dejaba de avisar sin decir nada. El formulario tiene que
        rechazarlo, como ya rechaza un rendimiento negativo en la cosecha."""
        import almacen as _DB
        v = P.VentanaAltaParcela(panel)
        root.update()
        v.cb_tipo.set("LENOSO")
        v._sub()
        v.cb_sub.set("OLIVO")
        root.update()
        v.e_nombre.delete(0, "end"); v.e_nombre.insert(0, "Marco Malo")
        v.e_prop.delete(0, "end"); v.e_prop.insert(0, "x")
        v.coords = [[-4.10, 41.65], [-4.09, 41.65], [-4.09, 41.66], [-4.10, 41.66]]
        _teclear(v.e_calle, "-12", root)
        _teclear(v.e_pie, "12", root)
        v._guardar()
        _check("Marco_Malo" not in _DB.nombres(),
               "se guardo una parcela con el marco negativo")
        # y con el marco corregido si entra
        _teclear(v.e_calle, "12", root)
        v._guardar()
        _check("Marco_Malo" in _DB.nombres(), "no se guardo con el marco corregido")
        _DB.eliminar_parcela("Marco_Malo")
        return v
    abrir("alta con marco negativo", _alta_marco_negativo)

    abrir("alta de parcela", lambda: P.VentanaAltaParcela(panel),
          lambda v: [b.invoke() for t, b in _botones(v) if "guardar" not in t.lower()]
          + [v._guardar()])
    abrir("edicion de parcela",
          lambda: P.VentanaAltaParcela(panel, editar=NOM, campana=CAMP))
    abrir("relevo de campana", lambda: P.DialogoRelevoCampana(panel, [NOM]),
          lambda v: v._siguiente())

    class FichaFalsa:
        nombre, campana, master = NOM, CAMP, root

        def _validar(self, *a, **k):
            pass
    ctx = {"fecha": regs[-1]["fecha"], "fase": "espigado", "estado": "Vigilar",
           "cultivo": "EXTENSIVO/COSECHA_GRANO/TRIGO"}
    abrir("correccion del diagnostico",
          lambda: P.DialogoCorreccion(root, FichaFalsa(), ctx), lambda v: v._guardar())
    abrir("sincronizar campanas anteriores",
          lambda: P.DialogoSincronizarCampanas(root, panel, NOM, CAMP), lambda v: v._sync())
    abrir("efecto de un producto",
          lambda: P.DialogoEfectoProducto(root, FichaFalsa(),
                                          {"fecha": regs[0]["fecha"], "tipo": "PRODUCTO",
                                           "producto": "X",
                                           "objetivo": "fungicida (enfermedad)"}, regs))
    abrir("comparar mapas",
          lambda: P.VentanaComparaMapas(root, NOM, CAMP,
                                        {r["fecha"]: r["fecha"] for r in regs}, "NDVI", 10))
    abrir("ventana de radar",
          lambda: P.VentanaRadar(root, NOM, CAMP, [], {"texto": "sin datos"}, 0, "sin datos"))
    _derribar(root)
    return f"{len(abiertas)} ventanas secundarias"


def escenario_cierre(P, DB):
    """Cerrar la ventana MIENTRAS un hilo sigue sincronizando. Es el caso que
    deja los callbacks diferidos apuntando a widgets ya destruidos."""
    from tkinter import ttk
    import gee_cliente

    lento = threading.Event()
    original_sync = P.sincronizar_parcela
    original_radar = gee_cliente.sincronizar_radar
    original_ee = P._EE
    P.sincronizar_parcela = lambda *a, **k: (lento.wait(30.0), (0, "sin pasadas nuevas"))[1]
    gee_cliente.sincronizar_radar = lambda *a, **k: (lento.wait(30.0), (0, "sin datos"))[1]
    P._EE = True
    fallos_hilo = []
    excepthook = threading.excepthook
    threading.excepthook = lambda a: fallos_hilo.append(f"{a.exc_type.__name__}: {a.exc_value}")

    root = _raiz()
    P.aplicar_tema(root, escala=1.0)
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    panel = P.PanelGestionParcelas(nb)
    nb.add(panel, text="x")
    ultima = {}
    original = P.FichaParcela.__init__
    P.FichaParcela.__init__ = lambda s, *a, **k: (ultima.__setitem__("f", s),
                                                  original(s, *a, **k))[1]

    hechas = []

    def escena(t0, etiqueta, arrancar, cerrar):
        root.after(int(t0 * 1000), lambda: (lento.clear(), fallos_hilo.clear(), arrancar()))
        root.after(int((t0 + 0.6) * 1000), cerrar)
        root.after(int((t0 + 0.8) * 1000), lento.set)
        root.after(int((t0 + 2.2) * 1000),
                   lambda: hechas.append((etiqueta, list(fallos_hilo))))

    root.after(100, lambda: panel.mostrar_ficha("Cerealista_Vega"))
    escena(0.5, "sincronizar y abrir otra ficha",
           lambda: ultima["f"].sincronizar(),
           lambda: panel.mostrar_ficha("Secano_El_Alto"))
    root.after(3000, lambda: panel.mostrar_ficha("Cerealista_Vega"))
    escena(3.4, "radar y abrir otra ficha",
           lambda: ultima["f"]._sincronizar_radar(),
           lambda: panel.mostrar_ficha("Secano_El_Alto"))
    escena(6.0, "sincronizar todo y cerrar el programa",
           lambda: panel._sincronizar_ahora(), lambda: panel.destroy())
    root.after(9000, root.quit)
    root.mainloop()

    for etiqueta, fallos in hechas:
        if fallos:
            FALLOS.append((f"cierre: {etiqueta}", "excepcion en el hilo", fallos[0], fallos[0]))
    P.FichaParcela.__init__ = original
    P.sincronizar_parcela = original_sync
    gee_cliente.sincronizar_radar = original_radar
    P._EE = original_ee
    threading.excepthook = excepthook
    _derribar(root)
    return f"{len(hechas)} escenas de cierre"


# Si matplotlib estaba cargada ya al importar el panel, la carga perezosa se ha
# roto: se anota en el momento del import (ver `main`) porque despues es tarde.
_MPL_AL_IMPORTAR = []


def escenario_presentacion(P, DB):
    """Escalado por DPI, icono y carga perezosa de matplotlib.

    Lo que se vigila aqui no es que «se vea bonito» -eso no lo comprueba ninguna
    prueba- sino tres cosas que, al fallar, fallan CALLANDO: que en un monitor
    normal no se mueva ni un pixel, que las cajas medidas en pixeles crezcan al
    menos tanto como las fuentes (si no, `pack` recorta sin avisar), y que
    matplotlib siga sin cargarse hasta que haga falta una grafica."""
    from tkinter import ttk
    hechos = []

    # --- 1. matplotlib NO puede estar cargada solo por importar el modulo ---
    _paso("al importar el panel, matplotlib sigue sin cargarse",
          lambda: (_ for _ in ()).throw(AssertionError("matplotlib cargada de mas"))
          if not all(_MPL_AL_IMPORTAR) else None)

    root = _raiz()
    P.aplicar_tema(root, escala=1.0)

    # --- 2. el factor de escala es sensato y cuantizado ---
    f = P._ESCALA["f"]
    _paso("el factor de escala esta acotado y va en cuartos",
          lambda: (_ for _ in ()).throw(AssertionError(f"factor raro: {f}"))
          if not (1.0 <= f <= 3.0 and abs(f * 4 - round(f * 4)) < 1e-9) else None)
    hechos.append(f"factor {f}")

    # --- 3. `esc` y `geom` son coherentes con ese factor ---
    _paso("esc() y geom() aplican el factor vigente",
          lambda: (_ for _ in ()).throw(AssertionError("esc/geom no cuadran"))
          if (P.esc(100) != int(round(100 * f))
              or P.geom(800, 600) != f"{P.esc(800)}x{P.esc(600)}") else None)

    # --- 4. las cajas crecen AL MENOS tanto que el texto ---
    # Es la condicion que evita el fallo silencioso: si la fuente creciera mas que
    # su caja, el contenido dejaria de caber y `pack` no dibujaria lo ultimo.
    alto_linea = P.FUENTES["body"].metrics("linespace")
    _paso("una caja escalada crece al menos como la fuente",
          lambda: (_ for _ in ()).throw(AssertionError(
              f"caja {P.esc(380)} vs texto {alto_linea}"))
          if P.esc(380) / 380.0 < alto_linea / 17.0 - 0.01 else None)

    # --- 5. el icono se pone (o se salta sin romper si no esta el fichero) ---
    _paso("poner_icono no revienta", lambda: P.poner_icono(root))
    hechos.append("icono " + ("puesto" if P.poner_icono(root) else "ausente"))

    # --- 4bis. LA MISMA interfaz a 150 %, en una raiz aparte ---
    # Sin esto, el camino escalado no lo prueba nadie: la suite fija escala 1.0
    # para ser reproducible, y entonces `esc()` seria siempre la identidad.
    alta = _raiz()
    P.aplicar_tema(alta, escala=1.5)
    grande = alta.tk.call("tk", "scaling")
    _paso("a 150 % las medidas y el texto crecen a la vez",
          lambda: (_ for _ in ()).throw(AssertionError(
              f"esc(380)={P.esc(380)} texto={P.FUENTES['body'].metrics('linespace')} "
              f"scaling={grande}"))
          if not (P.esc(380) == 570 and P.geom(1000, 600) == "1500x900"
                  and float(grande) > 1.9) else None)
    nb2 = ttk.Notebook(alta)
    nb2.pack(fill="both", expand=True)
    panel2 = P.PanelGestionParcelas(nb2)
    nb2.add(panel2, text="x")
    alta.update()
    _paso("y la ficha entera se monta a esa escala", lambda: (
        panel2.mostrar_ficha(sorted(DB.nombres())[0]), alta.update()))
    _derribar(alta)
    P.aplicar_tema(root, escala=1.0)      # se deja como estaba para el resto
    hechos.append("150 % comprobado")

    # --- 6. abrir una ficha SI carga matplotlib, y con el tema aplicado ---
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    panel = P.PanelGestionParcelas(nb)
    nb.add(panel, text="x")
    root.update()
    panel.mostrar_ficha(sorted(DB.nombres())[0])
    root.update()
    _paso("abrir una ficha carga matplotlib",
          lambda: (_ for _ in ()).throw(AssertionError("matplotlib sin cargar"))
          if P.Figure is None else None)
    _paso("y le aplica el tema de las graficas",
          lambda: (_ for _ in ()).throw(AssertionError("rcParams sin tema"))
          if P.mpl.rcParams["axes.facecolor"] != P.TEMA["surface"] else None)

    _derribar(root)
    return ", ".join(hechos)


# ---------------------------------------------------------------------------
ESCENARIOS = [("arranque", escenario_arranque), ("lista de parcelas", escenario_lista),
              ("fichas de parcela", escenario_fichas), ("cuaderno y cosecha", escenario_cuaderno),
              ("validacion por indice", escenario_validacion_indices),
              ("campanas de la ficha", escenario_campanas),
              ("dialogos", escenario_dialogos), ("presentacion (DPI, icono, arranque)", escenario_presentacion),
              ("cierre a media sincronizacion", escenario_cierre)]


def main():
    try:
        import tkinter  # noqa: F401
    except Exception as e:
        print(f"pruebas_interfaz: se omite (no hay tkinter: {e})")
        return 0
    os.environ["GESTOR_PARCELAS_DIR"] = tempfile.mkdtemp()   # nunca la base real
    os.environ.pop("OPENAI_API_KEY", None)
    try:
        import tkinter as tk
        tk.Tk().destroy()
    except Exception as e:
        print(f"pruebas_interfaz: se omite (no hay pantalla: {e}). "
              f"En un servidor: xvfb-run -a python pruebas_interfaz.py")
        return 0

    _sin_modales()
    _callar_ruido_de_cierre()
    DB = _sembrar()
    import panel_gestion_parcelas as P
    # Se anota AQUI, recien importado: para cuando corre el escenario de
    # presentacion ya se han abierto fichas y matplotlib esta cargada con razon.
    _MPL_AL_IMPORTAR.append(P.Figure is None)

    print("=" * 74)
    print(" PRUEBAS DE INTERFAZ  ·  se monta la aplicacion real y se toca todo")
    print("=" * 74)
    for nombre, fn in ESCENARIOS:
        antes = len(FALLOS)
        t0 = time.time()
        try:
            detalle = fn(P, DB)
        except Exception as e:
            _anotar(nombre, e)
            detalle = "abortado"
        nuevos = len(FALLOS) - antes
        marca = "  ok " if nuevos == 0 else f" {nuevos:>3} X"
        print(f"{marca}  {nombre:<32} {detalle}   ({time.time() - t0:.1f}s)")

    print("-" * 74)
    if DIALOGOS:
        print(f"  {len(DIALOGOS)} caja(s) de mensaje por el camino "
              f"(esperado: avisos de validacion y de que no hay Earth Engine)")
    if not FALLOS:
        print("  La interfaz responde sin excepciones.")
        return 0
    print(f"  {len(FALLOS)} FALLO(S):")
    vistos = set()
    for donde, tipo, msg, traza in FALLOS:
        if (tipo, msg) in vistos:
            continue
        vistos.add((tipo, msg))
        print(f"\n  -- {donde}: {tipo}: {msg}")
        for linea in traza.strip().split("\n")[-5:]:
            print("     " + linea)
    return 1


if __name__ == "__main__":
    sys.exit(main())
