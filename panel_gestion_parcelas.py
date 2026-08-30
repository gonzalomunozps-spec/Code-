# -*- coding: utf-8 -*-
"""
panel_gestion_parcelas.py
=========================

La VENTANA PRINCIPAL: la lista de parcelas, la barra de abajo (campana, busqueda,
orden, sincronizar, nueva parcela) y el arranque del programa.

Este fichero era un monolito de 4.300 lineas -la deuda tecnica numero uno del
proyecto- y ahora es el ENSAMBLADOR: monta las piezas y se queda con la lista.

    ui_tema.py          colores, fuentes, escala por DPI, icono, matplotlib
    ui_widgets.py       LienzoMapa, CampoFecha, PopupCalendario
    ui_dialogos.py      los modales que abre la ficha
    ui_ficha.py         la ficha de parcela, el radar y la comparacion de mapas
    ui_alta.py          alta/edicion de parcela y relevo de campana
    ui_credenciales.py  la pestana de credenciales y aspecto

El grafo NO tiene ciclos:

    panel -> ficha, alta, credenciales, tema
    ficha -> dialogos, widgets, tema
    alta  -> widgets, tema
    dialogos, credenciales, widgets -> tema
    tema  -> (nada del programa)

Los dialogos reciben la ficha como ARGUMENTO en vez de importarla; para que eso
fuera posible se movieron a la capa 0 las dos cosas que les hacian falta y no eran
suyas: `interpretacion_fenologica.ESTADOS_VALIDABLES` y `campanas.etiqueta_campana`.

INTEGRACION
    from panel_gestion_parcelas import PanelGestionParcelas, aplicar_tema
    root = tk.Tk()
    aplicar_tema(root)
    nb = ttk.Notebook(root); nb.pack(fill="both", expand=True)
    nb.add(PanelGestionParcelas(nb), text="  Gestion de Parcelas  ")
    root.mainloop()

DEPENDENCIAS
    pip install -r requirements.txt
    earthengine authenticate
"""

import threading

import tkinter as tk
from tkinter import ttk, messagebox

# --- las piezas de la interfaz -------------------------------------------
# Se reexportan A PROPOSITO aunque este fichero no las use: el panel es la puerta
# de entrada de la interfaz (`from panel_gestion_parcelas import ...`) y romper
# eso obligaria a que todo el que monte la aplicacion supiera en que modulo cayo
# cada clase. De ahi los `noqa`.
import ui_tema
from ui_tema import (TEMA, TEMAS, MODO, FUENTES, PALETA_DATOS, RANURA_SERIE,
                     color_serie, activar_dpi, esc, geom, poner_icono,
                     aplicar_tema, tarjeta, centrar_sobre, marco_scroll,
                     enlazar_rueda, ui_seguro)
from ui_widgets import LienzoMapa, CampoFecha, PopupCalendario
from ui_ficha import (FichaParcela, VentanaRadar, VentanaComparaMapas,
                      PanelMapaComparado, tooltip_pasada)
from ui_dialogos import (DialogoCorreccion, DialogoValidacionIndices,
                         DialogoSincronizarCampanas, DialogoEfectoProducto,
                         DialogoBorrarCampana)
from ui_alta import VentanaAltaParcela, DialogoRelevoCampana, BUFFER_POR_DEFECTO
from ui_credenciales import PanelCredenciales

# Reexportados para quien monte la aplicacion desde fuera y para el arnes de
# pruebas, que mira el panel como puerta de entrada de toda la interfaz.
from ui_tema import _ESCALA
from ui_dialogos import _CALIB

# --- el resto del programa -----------------------------------------------
import almacen as DB
import credenciales as CRED
import gee_cliente
import mapas_cache
import rutas
import sincronizacion
from gee_cliente import sincronizar_parcela
from interpretacion_fenologica import evaluar_parcela
from campanas import campana_actual
from cultivo import spec_de, clave_cultivo
from sincronizacion import INTERVALO_AUTOSYNC_MS, ULTIMO_SYNC
from bitacora import log
import fenologia_especies as FEN
from geo import superficie_ha
from mapas_cache import DIR_MAPAS

_EE = gee_cliente.hay_ee()

# La superficie PUBLICA del modulo. El panel es la puerta de entrada de toda la
# interfaz (`from panel_gestion_parcelas import ...`), asi que reexporta las
# piezas aunque este fichero no las use: si no, quien monte la aplicacion tendria
# que saber en que modulo cayo cada clase. Declararlo aqui ademas se lo dice a las
# herramientas, que si no lo toman por imports olvidados.
__all__ = [
    "PanelGestionParcelas", "PanelCredenciales", "FichaParcela",
    "VentanaAltaParcela", "DialogoRelevoCampana", "VentanaRadar",
    "VentanaComparaMapas", "PanelMapaComparado", "LienzoMapa", "CampoFecha",
    "PopupCalendario", "DialogoCorreccion", "DialogoValidacionIndices",
    "DialogoSincronizarCampanas", "DialogoEfectoProducto", "DialogoBorrarCampana",
    "main",
    "aplicar_tema", "activar_dpi", "poner_icono", "esc", "geom",
    "TEMA", "TEMAS", "MODO", "FUENTES", "PALETA_DATOS", "RANURA_SERIE",
    "color_serie", "tarjeta", "centrar_sobre", "marco_scroll", "enlazar_rueda",
    "tooltip_pasada", "BUFFER_POR_DEFECTO", "RETARDO_BUSQUEDA_MS",
    "_ESCALA", "_CALIB",
]


# Los nombres de matplotlib los RELLENA `ui_tema._matplotlib()` cuando hace falta
# una grafica, asi que no se pueden importar por nombre: una copia hecha al
# importar se quedaria en None para siempre. Se resuelven al pedirlos (PEP 562).
_DE_TEMA = ("Figure", "FigureCanvasTkAgg", "mcolors", "mdates", "mpl", "matplotlib")


def __getattr__(nombre):
    if nombre in _DE_TEMA:
        return getattr(ui_tema, nombre)
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")




# Distingue «no me han dicho nada» de «ponlo a None». Sin esto no se puede volver
# al margen por defecto: `None` como valor por defecto del argumento y `None` como
# «borralo» son indistinguibles.
_SIN_TOCAR = object()

# Cuanto se espera desde la ultima tecla antes de repintar la lista. Lo bastante
# para no repintar a media palabra, lo bastante poco para que no parezca que la
# caja de busqueda no responde.
RETARDO_BUSQUEDA_MS = 180

# El selector de campana de la barra sirve a las dos vistas: en la lista basta con
# el nombre de la campana; con una ficha abierta lleva ademas que se puede hacer
# con ella ("en curso", "solo archivo", "✓ 3 pasadas"), y necesita mas sitio.
ANCHO_CAMPANA_LISTA = 11
ANCHO_CAMPANA_FICHA = 34

# La lista ya evaluada es un dato DERIVADO de las parcelas: si se borra una, deja
# de valer. Segun la regla de `almacen`, quien guarda algo derivado se apunta al
# aviso en vez de esperar a que quien borra se acuerde -el borrado se llama desde
# el panel, desde la demo y desde las pruebas, y basta con que uno se olvide-.
# Se lleva un contador de version, no una referencia al panel: asi no se retiene
# viva ninguna ventana ya cerrada.
_GENERACION = {"n": 0}


def _datos_cambiaron(_nombre=None):
    """Invalida la lista evaluada de todos los paneles vivos."""
    _GENERACION["n"] += 1


DB.al_eliminar_parcela(_datos_cambiaron)


def _colores_estado(clave):
    return {"OK": (TEMA["ok_fg"], TEMA["ok_bg"]),
            "Vigilar": (TEMA["warn_fg"], TEMA["warn_bg"]),
            "Revisar": (TEMA["danger_fg"], TEMA["danger_bg"]),
            # «Revisar datos» NO es rojo: el cultivo puede estar perfectamente. Lo
            # que falla es lo declarado, asi que va con el color de aviso, no con
            # el de alarma. Ningun color nuevo: se reutiliza la paleta del tema.
            "Revisar datos": (TEMA["warn_fg"], TEMA["warn_bg"])}.get(
        clave, (TEMA["muted_fg"], TEMA["muted_bg"]))


# Los umbrales de vigor ya no son fijos por cultivo: se calculan por FASE
# fenologica en interpretacion_fenologica / fenologia_especies (rango esperado
# de NDVI segun especie, fecha y marco). Aqui solo quedan los nombres visibles.
SUBTIPOS = {"EXTENSIVO": ["SIEGA_VERDE", "COSECHA_GRANO"],
            "LENOSO": ["TRADICIONAL", "INTENSIVO", "SUPERINTENSIVO"], "BARBECHO": []}
NOMBRE_CULTIVO = {
    "LENOSO_TRADICIONAL": "Olivar tradicional", "LENOSO_INTENSIVO": "Olivar intensivo",
    "LENOSO_SUPERINTENSIVO": "Olivar superintensivo",
    "EXTENSIVO_SIEGA_VERDE": "Extensivo (siega verde)",
    "EXTENSIVO_COSECHA_GRANO": "Extensivo (grano)", "BARBECHO": "Barbecho",
}


class PanelGestionParcelas(ttk.Frame):
    def __init__(self, master, *a, **k):
        super().__init__(master, *a, **k)
        self.campana = campana_actual()
        # La ficha abierta, si la hay. El selector de campana de la barra sirve a
        # las dos vistas y necesita saber a cual esta sirviendo.
        self.ficha = None
        self._campanas_barra = None      # campanas de la ficha, cuando hay ficha
        # Lista ya evaluada (ver `_refrescar`), con la campana y la version de los
        # datos con que se calculo. `None` = todavia no hay nada.
        self._filas = None
        self._filas_campana = None
        self._filas_gen = -1
        self._tarea_busqueda = None      # el repintado pendiente de la busqueda
        # SINCRONIZACION EN CURSO. Con cientos de parcelas, recorrerlas todas son
        # minutos de red: hace falta poder CANCELAR y ver por donde va. El Event lo
        # comparten los dos recorridos (manual y automatico) y se mira entre parcela
        # y parcela, nunca a mitad de una escritura.
        self._cancelar_sync = threading.Event()
        self._sync_en_curso = False

        self.contenedor = tk.Frame(self, bg=TEMA["page"])
        self.vista_lista = tk.Frame(self.contenedor, bg=TEMA["page"])
        self.vista_ficha = tk.Frame(self.contenedor, bg=TEMA["page"])

        # El ORDEN de estos tres importa, y estaba mal: `contenedor` se
        # empaquetaba el primero con expand=True, se quedaba con todo el alto y
        # empujaba la cabecera por debajo del contenido -el titulo del programa
        # salia al pie de la ventana-. Se reservan primero los bordes y el
        # contenido ocupa lo que queda.
        self._build_cabecera()          # titulo y estado, arriba
        self._build_barra()             # campana, busqueda y acciones, abajo
        self.contenedor.pack(fill="both", expand=True)
        self._build_lista()
        self.mostrar_lista()

        # limpieza de PNG viejos de la cache, en un hilo aparte para NO retrasar
        # la apertura de la ventana (borra imagenes, nunca datos)
        threading.Thread(target=self._purgar_cache, daemon=True).start()

        # Relevo de campana (1 de septiembre) + import automatico periodico
        self.after(400, self._comprobar_relevo_campana)
        self.after(1500, self._auto_sync)

    # ---------------------------------------------------------- relevo de campana
    def _comprobar_relevo_campana(self):
        """Al entrar en una campana nueva, pide el cultivo de las parcelas ya existentes
        que aun no lo tengan asignado para la campana activa."""
        parcelas = DB.parcelas_dict()
        pendientes = [n for n, f in parcelas.items()
                      if self.campana not in f.get("cultivos_por_campana", {})]
        if parcelas and pendientes:
            DialogoRelevoCampana(self, pendientes)

    def asignar_cultivo(self, nombre, tipo, spec):
        if DB.existe(nombre):
            spec = dict(spec or {})
            subtipo = ""
            if tipo == "LENOSO" and spec.get("marco_calle"):
                dens = FEN.densidad_arboles(spec["marco_calle"], spec["marco_pie"])
                subtipo = FEN.subtipo_canonico(spec.get("especie", "OLIVO"), dens)
            elif tipo == "EXTENSIVO":
                subtipo = spec.get("finalidad") if spec.get("finalidad") in ("SIEGA_VERDE", "COSECHA_GRANO") else "COSECHA_GRANO"
            cultivo = {"tipo": tipo, "subtipo": subtipo}
            cultivo.update(spec)
            DB.set_cultivo(nombre, self.campana, cultivo)
        self._refrescar()

    # ---------------------------------------------------------- import automatico
    def _purgar_cache(self):
        """Borra los PNG de mapas mas viejos que mapas_cache.DIAS_CACHE.

        Corre en un hilo aparte para no retrasar la apertura de la ventana, y no
        toca la interfaz. Solo borra imagenes, que se vuelven a descargar solas
        cuando se piden; los datos no se tocan (ver rutas.purgar_png_antiguos).
        """
        try:
            n = rutas.purgar_png_antiguos(DIR_MAPAS, mapas_cache.DIAS_CACHE)
            if n:
                log.warning("cache de mapas: %s PNG con mas de %s dias borrados",
                            n, mapas_cache.DIAS_CACHE)
        except Exception:
            log.warning("no se pudo purgar la cache de mapas", exc_info=True)

    def _auto_sync(self):
        """Se ejecuta al ARRANCAR y luego de forma periodica. Solo sincroniza si
        toca (nunca se sincronizo o ya paso el intervalo desde el ultimo sync);
        asi, abrir la app varias veces el mismo dia no repite, pero si han pasado
        los dias configurados, al iniciarse se pone al dia sola."""
        if (_EE and not self._sync_en_curso
                and sincronizacion.toca_sincronizar(sincronizacion.marca_leer(), INTERVALO_AUTOSYNC_MS)):
            self._sync_en_curso = True
            self._cancelar_sync.clear()
            threading.Thread(target=self._sync_todas, daemon=True).start()
        self.after(INTERVALO_AUTOSYNC_MS, self._auto_sync)

    def _recorrer_sincronizando(self, progreso=None):
        """Sincroniza TODAS las parcelas de la campana, una a una.

        Devuelve (pasadas_nuevas, parcelas_revisadas, cancelado). Mira el Event de
        cancelacion ENTRE parcelas: asi se corta rapido sin dejar a medias la
        descarga de ninguna. `progreso(i, total)` se llama tras cada parcela (la
        interfaz lo usa para decir «37/500»)."""
        total = revisadas = 0
        nombres = DB.nombres()
        cuantas = len(nombres)
        for i, nombre in enumerate(nombres, 1):
            if self._cancelar_sync.is_set():
                return total, revisadas, True
            n, _ = sincronizar_parcela(nombre, self.campana, silencioso=True)
            total += n
            revisadas += 1
            if progreso is not None:
                progreso(i, cuantas)
        return total, revisadas, False

    def _sync_todas(self):
        """Recorrido AUTOMATICO (al arrancar y cada intervalo). Sin dialogos: solo
        actualiza el indicador y, si trajo algo, repinta la lista."""
        try:
            total, _rev, cancelado = self._recorrer_sincronizando(self._progreso_sync)
        finally:
            self._sync_en_curso = False
        if not cancelado and ULTIMO_SYNC.get("estado") != "fallo":
            sincronizacion.marca_guardar()   # solo marca la hora si conecto y termino
        ui_seguro(self, self._actualizar_estado_sync)   # refleja exito/fallo del auto-sync
        if total:
            ui_seguro(self, self._refrescar)

    def _progreso_sync(self, i, cuantas):
        """Ensena por que parcela va la sincronizacion. Se marshalla al hilo de la
        interfaz; con una parcela por evento, ni con cientos satura nada."""
        def pintar():
            if hasattr(self, "lbl_sync") and self.lbl_sync.winfo_exists():
                self.lbl_sync.config(text=f"↻ GEE: {i}/{cuantas}", fg=TEMA["header_sub"])
        ui_seguro(self, pintar)

    def detener_sincronizacion(self):
        """Pide que el recorrido en curso pare en cuanto termine la parcela actual.
        La llama el boton de cancelar y el cierre del programa."""
        self._cancelar_sync.set()

    def _build_cabecera(self):
        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x", side="top")
        # indicador de estado de la sincronizacion (siempre visible, a la derecha)
        der = tk.Frame(cab, bg=TEMA["header_bg"])
        der.pack(side="right", padx=18)
        self.lbl_sync = tk.Label(der, text="○ GEE: sin sincronizar", bg=TEMA["header_bg"],
                                 fg=TEMA["header_sub"], font=FUENTES["small"], cursor="hand2")
        self.lbl_sync.pack(side="right", pady=14)
        self.lbl_sync.bind("<Button-1>", lambda e: self._detalle_sync())
        izq = tk.Frame(cab, bg=TEMA["header_bg"])
        izq.pack(side="left", fill="x")
        tk.Label(izq, text="Gestion y Monitoreo de Parcelas", bg=TEMA["header_bg"],
                 fg=TEMA["text_inv"], font=FUENTES["h1"]).pack(anchor="w", padx=18, pady=(12, 0))
        tk.Label(izq, text="Ecosistema Copernicus  -  Sentinel-2", bg=TEMA["header_bg"],
                 fg=TEMA["header_sub"], font=FUENTES["small"]).pack(anchor="w", padx=18, pady=(0, 12))

    # colores legibles sobre la cabecera verde oscura
    # Se resuelve al pintar, no al importar: al importar aun no se sabe con que
    # tema va a arrancar el programa.
    _SYNC_TOKEN = {"ok": "sync_ok", "fallo": "sync_fallo", None: "header_sub"}
    _SYNC_TEXTO = {"ok": "● GEE: conectado", "fallo": "● GEE: fallo",
                   None: "○ GEE: sin sincronizar"}

    def _actualizar_estado_sync(self):
        """Refresca el indicador de la cabecera a partir de ULTIMO_SYNC."""
        if not hasattr(self, "lbl_sync") or not self.lbl_sync.winfo_exists():
            return          # la ventana se cerro mientras el hilo sincronizaba
        est = ULTIMO_SYNC.get("estado")
        self.lbl_sync.config(text=self._SYNC_TEXTO.get(est, self._SYNC_TEXTO[None]),
                             fg=TEMA[self._SYNC_TOKEN.get(est, self._SYNC_TOKEN[None])])

    def _detalle_sync(self):
        est = ULTIMO_SYNC.get("estado")
        msg = ULTIMO_SYNC.get("msg", "")
        if est == "fallo":
            messagebox.showerror("Sincronizacion Copernicus", f"La ultima sincronizacion fallo:\n\n{msg}")
        elif est == "ok":
            messagebox.showinfo("Sincronizacion Copernicus", f"Conexion con Google Earth Engine correcta.\n{msg}")
        else:
            messagebox.showinfo("Sincronizacion Copernicus",
                                "Aun no se ha sincronizado en esta sesion.")

    def _build_barra(self):
        barra = tk.Frame(self, bg=TEMA["page"])
        barra.pack(fill="x", side="bottom", padx=18, pady=12)

        camp = tarjeta(barra)
        camp.pack(side="left")
        tk.Label(camp, text=" Campana ", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left", padx=(6, 0), pady=4)
        self.cb_campana = ttk.Combobox(camp, state="readonly", width=ANCHO_CAMPANA_LISTA,
                                       values=self._campanas())
        self.cb_campana.set(self.campana)
        self.cb_campana.pack(side="left", padx=6, pady=4)
        self.cb_campana.bind("<<ComboboxSelected>>", lambda e: self._elegir_campana())

        # Buscar y ordenar son de la LISTA: con una ficha abierta no hacen nada,
        # asi que se retiran en vez de quedarse ahi de adorno (ver `_sincronizar_barra`).
        self.card_buscar = centro = tarjeta(barra)
        centro.pack(side="left", fill="x", expand=True, padx=10)
        tk.Label(centro, text="  \U0001F50D  ", bg=TEMA["surface"],
                 fg=TEMA["text_muted"]).pack(side="left")
        self.entry_buscar = tk.Entry(centro, bd=0, bg=TEMA["surface"], fg=TEMA["text"],
                                     font=FUENTES["body"], insertbackground=TEMA["text"])
        self.entry_buscar.pack(side="left", fill="x", expand=True, padx=4, pady=6, ipady=2)
        self.entry_buscar.bind("<KeyRelease>", self._buscar_pronto)
        tk.Label(centro, text="Ordenar", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left", padx=(6, 2))
        self.cb_orden = ttk.Combobox(centro, state="readonly", width=13,
                                     values=["nombre", "superficie", "propietario",
                                             "anio_inicio", "estado"])
        self.cb_orden.set("estado")
        self.cb_orden.pack(side="left", padx=6, pady=4)
        self.cb_orden.bind("<<ComboboxSelected>>",
                           lambda e: self._refrescar(recargar=False))

        ttk.Button(barra, text="  + Nueva parcela  ", style="Accent.TButton",
                   command=self.abrir_alta_parcela).pack(side="right")
        self.btn_sync = ttk.Button(barra, text="  ↻ Sincronizar ahora  ",
                                   command=self._sincronizar_ahora)
        self.btn_sync.pack(side="right", padx=(0, 8))
        ttk.Button(barra, text="  🛡 Copias  ", style="Ghost.TButton",
                   command=self._abrir_copias).pack(side="right", padx=(0, 8))
        ttk.Button(barra, text="  ❔ Ayuda  ", style="Ghost.TButton",
                   command=self._abrir_manual).pack(side="right", padx=(0, 8))

    def _abrir_copias(self):
        """Abre la ventana de copias de seguridad (crear, restaurar, exportar)."""
        from ui_copias import DialogoCopias
        DialogoCopias(self)

    def _abrir_manual(self):
        """Abre el manual de usuario (MANUAL.md) con la aplicacion del sistema."""
        import os
        from ficha_comun import _abrir_archivo
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MANUAL.md")
        if os.path.exists(ruta):
            _abrir_archivo(ruta)
        else:
            messagebox.showinfo("Ayuda", "No se encontro el manual (MANUAL.md).")

    def _sincronizar_ahora(self):
        """Sincronizacion manual de TODAS las parcelas. Mientras corre, el mismo
        boton sirve para CANCELAR: con cientos de parcelas esto son minutos de red
        y dejar al usuario sin salida no es aceptable."""
        if self._sync_en_curso:                     # segunda pulsacion = cancelar
            self.detener_sincronizacion()
            self.btn_sync.config(text="  ⏹ Cancelando…  ", state="disabled")
            return
        if not _EE:
            return messagebox.showwarning(
                "Sincronizacion", "earthengine-api no disponible. Configura la conexion "
                "en la pestana 'Credenciales'.")
        self._sync_en_curso = True
        self._cancelar_sync.clear()
        self.btn_sync.config(text="  ⏹ Cancelar  ", state="normal")
        self.lbl_sync.config(text="↻ GEE: sincronizando…", fg=TEMA["header_sub"])
        threading.Thread(target=self._sync_todas_notificando, daemon=True).start()

    def _sync_todas_notificando(self):
        try:
            total, n_par, cancelado = self._recorrer_sincronizando(self._progreso_sync)
        finally:
            self._sync_en_curso = False
        if not cancelado and ULTIMO_SYNC.get("estado") != "fallo":
            sincronizacion.marca_guardar()

        def fin():
            if not self.btn_sync.winfo_exists():
                return      # se cerro el programa mientras sincronizaba todo
            self.btn_sync.config(text="  ↻ Sincronizar ahora  ", state="normal")
            self._actualizar_estado_sync()
            self._refrescar()
            if cancelado:
                messagebox.showinfo("Sincronizacion",
                                    f"Sincronizacion cancelada. Se revisaron {n_par} parcela(s) "
                                    f"y se anadieron {total} pasada(s); lo demas queda para la "
                                    "proxima vez.")
            elif ULTIMO_SYNC.get("estado") == "fallo":
                messagebox.showerror("Sincronizacion",
                                     f"No se pudo sincronizar con Copernicus:\n\n{ULTIMO_SYNC.get('msg','')}")
            elif total:
                messagebox.showinfo("Sincronizacion",
                                    f"{n_par} parcela(s) revisadas. {total} pasada(s) nueva(s) anadida(s).")
            else:
                messagebox.showinfo("Sincronizacion",
                                    f"{n_par} parcela(s) revisadas. Sin pasadas nuevas por ahora.")
        ui_seguro(self, fin)

    def _elegir_campana(self):
        """UNA sola campana para todo el programa: la de esta barra.

        En la lista elige que campana se resume. Con una ficha abierta elige que
        campana de ESA parcela se mira, con su aviso de descarga y sus campanas de
        solo archivo. Antes habia dos selectores a la vez -uno en la cabecera de la
        ficha y otro aqui- que podian acabar diciendo cosas distintas."""
        if self.ficha is not None and self._campanas_barra is not None:
            return self.ficha.cambiar_a(self.cb_campana.current())
        self.campana = self.cb_campana.get()
        self._refrescar()

    def _sincronizar_barra(self):
        """Deja la barra de abajo acorde con lo que se esta mirando.

        Es la unica barra del programa y sirve a las dos vistas, asi que tiene que
        ensenar lo que aplica en cada una: con una ficha abierta, las campanas de
        ESA parcela y sin la busqueda, que ahi no filtra nada."""
        if not hasattr(self, "cb_campana") or not self.cb_campana.winfo_exists():
            return
        if self.card_buscar.winfo_exists():
            if self.ficha is not None:
                self.card_buscar.pack_forget()
            elif not self.card_buscar.winfo_ismapped():
                self.card_buscar.pack(side="left", fill="x", expand=True, padx=10,
                                      before=self.btn_sync)
        if self.ficha is not None:
            etiquetas, disponibles, actual = self.ficha.campanas_para_barra()
            self._campanas_barra = disponibles
            self.cb_campana.configure(values=etiquetas, width=ANCHO_CAMPANA_FICHA)
            if 0 <= actual < len(etiquetas):
                self.cb_campana.current(actual)
        else:
            self._campanas_barra = None
            self.cb_campana.configure(values=self._campanas(), width=ANCHO_CAMPANA_LISTA)
            self.cb_campana.set(self.campana)

    def _campanas(self):
        # solo la actual + las campanas con datos de satelite (las vacias no se muestran)
        c = {campana_actual()}
        c |= DB.campanas_con_datos()
        return sorted(c, reverse=True)

    def _build_lista(self):
        wrap = tarjeta(self.vista_lista)
        wrap.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        cols = ("nombre", "cultivo", "superficie", "propietario", "estado")
        titulos = {"nombre": "Nombre", "cultivo": "Cultivo", "superficie": "Superficie",
                   "propietario": "Propietario", "estado": "Estado"}
        anchos = {"nombre": 220, "cultivo": 200, "superficie": 120,
                  "propietario": 200, "estado": 130}
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=titulos[c])
            self.tree.column(c, width=esc(anchos[c]), anchor="e" if c == "superficie" else "w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        sb.pack(side="right", fill="y", pady=1)

        self.tree.tag_configure("par", background=TEMA["surface"])
        self.tree.tag_configure("impar", background=TEMA["fila_alt"])
        for clave in ("OK", "Vigilar", "Revisar"):
            self.tree.tag_configure(f"est_{clave}", foreground=_colores_estado(clave)[0])
        self.tree.tag_configure("est_NA", foreground=TEMA["text_muted"])
        self.tree.tag_configure("est_SinAsig", foreground=TEMA["text_muted"])
        self.tree.bind("<Double-1>", self._abrir_ficha_sel)
        self.tree.bind("<Button-3>", self._menu_ctx)

    def mostrar_lista(self):
        self.vista_ficha.pack_forget()
        self.vista_lista.pack(fill="both", expand=True)
        self.ficha = None
        self._sincronizar_barra()
        self._refrescar()

    # Orden de gravedad para ordenar por estado: lo que hay que mirar, arriba.
    # «Revisar datos» va justo detras de «Revisar»: hay que mirarlo pronto -el
    # diagnostico de esa parcela no vale mientras el dato no cuadre-, pero no es una
    # urgencia agronomica como un cultivo que se esta perdiendo.
    SEVERIDAD = {"Revisar": 0, "Revisar datos": 1, "Vigilar": 2, "OK": 3, "Segado": 3,
                 "Sin dato": 4, "N.A.": 5, "Sin asignar": 6}

    def _refrescar(self, recargar=True):
        """Repinta la lista. Con `recargar=False` reutiliza lo ya evaluado.

        Evaluar una parcela no es gratis: hay que traer su serie de pasadas y
        pasarla entera por `evaluar_parcela`. Filtrar por texto y cambiar el orden
        NO pueden cambiar ningun diagnostico, asi que se hacen sobre lo ya
        calculado. Lo que si lo cambia -sincronizar, dar de alta, editar, borrar,
        cambiar de campana- llama a `_refrescar()` a secas y vuelve a evaluar.

        Antes cada tecla de la caja de busqueda recorria la base y evaluaba todas
        las parcelas: escribir «Olivar» eran seis pasadas completas del motor
        agronomico, en el hilo de la interfaz."""
        if not hasattr(self, "tree") or not self.tree.winfo_exists():
            return          # la ventana se cerro mientras el hilo sincronizaba
        if (recargar or self._filas is None or self._filas_campana != self.campana
                or self._filas_gen != _GENERACION["n"]):
            self._filas = self._evaluar_parcelas()
            self._filas_campana = self.campana
            self._filas_gen = _GENERACION["n"]
        self._pintar_filas()

    def _evaluar_parcelas(self):
        """Una fila por parcela de la campana, con su diagnostico ya resuelto.

        Devuelve TODAS las parcelas, sin filtrar: el filtro es cosa de
        `_pintar_filas`, que se ejecuta muchas mas veces y no debe evaluar nada."""
        parcelas = DB.parcelas_dict()
        historico = DB.pasadas_de_campana(self.campana)   # {nombre: [pasadas]} en una consulta

        filas = []
        for nombre, ficha in parcelas.items():
            cult = ficha.get("cultivos_por_campana", {}).get(self.campana)
            if cult is None:                              # sin cultivo asignado en esta campana
                cc, clave, txt = "SIN_ASIGNAR", "SinAsig", "Sin asignar"
            elif cult.get("tipo") == "BARBECHO":          # barbecho -> no aplica vigor
                cc, clave, txt = "BARBECHO", "NA", "N.A."
            else:
                cc = clave_cultivo(cult.get("tipo"), cult.get("subtipo", ""))
                serie = sorted(historico.get(nombre, []),
                               key=lambda r: r.get("fecha", ""))
                diag = evaluar_parcela(cult.get("tipo"), cult.get("subtipo", ""), serie,
                                       spec=spec_de(cult))
                clave, txt = diag["clave"], diag["estado"]
            propietario = ficha.get("propietario", "")
            filas.append({"nombre": nombre.replace("_", " "),
                          "cultivo": NOMBRE_CULTIVO.get(cc, "Sin asignar" if cc == "SIN_ASIGNAR"
                                                        else cc.replace("_", " ").title()),
                          "superficie": f"{ficha.get('superficie_ha', 0.0):.2f} ha",
                          "_sup": ficha.get("superficie_ha", 0.0),
                          "propietario": propietario,
                          "estado": txt, "_clave": clave,
                          # la clave de busqueda se deja hecha: se compara en cada
                          # tecla y no vale la pena repetir el .lower() por fila
                          "_busca": f"{nombre} {propietario}".lower()})
        return filas

    def _pintar_filas(self):
        """Filtra por el texto, ordena y vuelca en la tabla. No evalua nada."""
        texto = self.entry_buscar.get().lower() if hasattr(self, "entry_buscar") else ""
        orden = self.cb_orden.get() if hasattr(self, "cb_orden") else "nombre"
        filas = [r for r in self._filas if not texto or texto in r["_busca"]]

        keys = {"superficie": lambda r: -r["_sup"],
                "propietario": lambda r: r["propietario"].lower(),
                "estado": lambda r: self.SEVERIDAD.get(r["estado"], 9),
                "nombre": lambda r: r["nombre"].lower()}
        filas.sort(key=keys.get(orden, keys["nombre"]))

        self.tree.delete(*self.tree.get_children())   # vaciado en UNA llamada a Tk
        for k, r in enumerate(filas):
            tags = ("par" if k % 2 == 0 else "impar", f"est_{r['_clave']}")
            dot = "\u25CF " if r["_clave"] in ("OK", "Vigilar", "Revisar") else ""
            self.tree.insert("", tk.END, tags=tags,
                             values=(r["nombre"], r["cultivo"], r["superficie"],
                                     r["propietario"], dot + r["estado"]))

    def _buscar_pronto(self, _=None):
        """Repinta poco despues de la ULTIMA tecla, no en cada una.

        Sin esto, escribir «Olivar» repinta la tabla entera seis veces, y cinco de
        esas seis no las llega a leer nadie: el usuario sigue tecleando."""
        if self._tarea_busqueda is not None:
            try:
                self.after_cancel(self._tarea_busqueda)
            except Exception:
                pass       # ya habia saltado: nada que cancelar
        self._tarea_busqueda = self.after(RETARDO_BUSQUEDA_MS, self._buscar_ahora)

    def _buscar_ahora(self):
        self._tarea_busqueda = None
        self._refrescar(recargar=False)      # el texto no cambia ningun diagnostico

    def _menu_ctx(self, event):
        fila = self.tree.identify_row(event.y)
        if not fila:
            return
        self.tree.selection_set(fila)
        m = tk.Menu(self, tearoff=0, bg=TEMA["surface"], fg=TEMA["text"],
                    activebackground=TEMA["surface_alt"], bd=0)
        m.add_command(label="  Abrir ficha", command=lambda: self._abrir_ficha_sel(None))
        m.add_separator()
        m.add_command(label="  Eliminar parcela", command=self._eliminar_sel)
        m.tk_popup(event.x_root, event.y_root)

    def _eliminar_sel(self):
        sel = self.tree.selection()
        if not sel:
            return
        nombre = self.tree.item(sel[0], "values")[0].replace(" ", "_")
        if not messagebox.askyesno("Eliminar", f"Eliminar la parcela '{nombre}' y su historico?"):
            return
        DB.eliminar_parcela(nombre)   # borra en cascada: parcela + cultivos + pasadas + eventos
        self._refrescar()

    def abrir_alta_parcela(self):
        VentanaAltaParcela(self)

    def guardar_parcela(self, nombre, propietario, tipo, spec, coords, campana=None,
                        sigpac=None, buffer_m=_SIN_TOCAR):
        """Alta o edicion de una parcela.

        `buffer_m`: un numero fija el margen interior; `None` lo devuelve al del
        programa; omitirlo deja el que hubiera. Hacen falta los tres casos: la
        ficha se carga de la base ANTES de actualizarla, asi que no basta con «si
        no viene, no lo toco» -el valor viejo ya esta dentro y sobrevive-."""
        camp = campana or self.campana
        cerrado = coords + [coords[0]] if coords and coords[0] != coords[-1] else coords
        ficha = DB.ficha(nombre) or {}
        ficha.update({"propietario": propietario, "coordenadas": cerrado,
                      "superficie_ha": superficie_ha(cerrado),
                      "anio_inicio_monitoreo": ficha.get("anio_inicio_monitoreo", camp)})
        # DONDE esta la parcela. Antes los 7 codigos SIGPAC se tecleaban, servian
        # para bajar el recinto y se tiraban. Se guardan porque provincia y
        # municipio son la unidad en la que se corrige un umbral para una comarca.
        if sigpac and sigpac.get("Prov") and sigpac.get("Mun"):
            ficha["provincia"] = str(sigpac["Prov"]).strip()
            ficha["municipio"] = f"{str(sigpac['Prov']).strip()}/{str(sigpac['Mun']).strip()}"
            ficha["sigpac"] = {k: str(v).strip() for k, v in sigpac.items() if str(v).strip()}
        if buffer_m is not _SIN_TOCAR:
            ficha["buffer_m"] = None if buffer_m is None else float(buffer_m)
        # subtipo derivado (compatibilidad y visualizacion):
        #   leñoso -> tipo de plantacion segun el marco; cereal -> COSECHA_GRANO
        spec = dict(spec or {})
        subtipo = ""
        if tipo == "LENOSO" and spec.get("marco_calle"):
            dens = FEN.densidad_arboles(spec["marco_calle"], spec["marco_pie"])
            subtipo = FEN.subtipo_canonico(spec.get("especie", "OLIVO"), dens)
        elif tipo == "EXTENSIVO":
            subtipo = spec.get("finalidad") if spec.get("finalidad") in ("SIEGA_VERDE", "COSECHA_GRANO") else "COSECHA_GRANO"
        cultivo = {"tipo": tipo, "subtipo": subtipo}
        cultivo.update(spec)          # especie, fecha_siembra, marco_calle, marco_pie, finalidad
        ficha.setdefault("cultivos_por_campana", {})[camp] = cultivo
        DB.guardar_ficha(nombre, ficha)
        self.cb_campana["values"] = self._campanas()
        self._refrescar()

    def editar_parcela(self, nombre, campana):
        """Abre la ventana de alta en modo edicion (prellena la parcela)."""
        VentanaAltaParcela(self, editar=nombre, campana=campana)

    def _abrir_ficha_sel(self, _):
        sel = self.tree.selection()
        if sel:
            self.mostrar_ficha(self.tree.item(sel[0], "values")[0].replace(" ", "_"))

    def mostrar_ficha(self, nombre):
        self.vista_lista.pack_forget()
        for w in self.vista_ficha.winfo_children():
            w.destroy()
        self.vista_ficha.pack(fill="both", expand=True)
        self.ficha = FichaParcela(self.vista_ficha, self, nombre, self.campana)
        self._sincronizar_barra()

    def _historico(self, nombre):
        return DB.pasadas(nombre, self.campana)

    def _ultimo_valido(self, nombre, clave):
        regs = sorted(self._historico(nombre), key=lambda r: r.get("fecha", ""))
        for r in reversed(regs):
            if r.get(clave) is not None:
                return r[clave]
        return None


# =====================================================================
# ARRANQUE
# =====================================================================
def main(argv=None):
    """Monta la ventana principal y entra en el bucle de eventos.

    Es tambien el punto de entrada del comando `gestor-parcelas` (ver
    pyproject.toml). Acepta `--version` y `--help` para no obligar a abrir la
    ventana solo por saber que version es. Devuelve el codigo de salida."""
    import argparse
    from version import __version__

    parser = argparse.ArgumentParser(
        prog="gestor-parcelas",
        description="Gestion y monitoreo de parcelas agricolas con Sentinel-2/1.")
    parser.add_argument("--version", action="version",
                        version=f"gestor-parcelas {__version__}")
    parser.parse_args(argv)

    # ANTES de tk.Tk(): una vez creada la ventana, Windows ya ha decidido como la
    # escala y declararse consciente del DPI no sirve de nada.
    activar_dpi()

    DB.conectar()                    # abre SQLite y migra los JSON antiguos si existen
    try:                             # copia de seguridad automatica (si no hay una reciente)
        import copias
        copias.crear_copia_si_toca(DB.RUTA_DB)
    except Exception:
        pass                         # una copia fallida jamas debe impedir arrancar
    cfg = CRED.cargar()
    CRED.aplicar_entorno(cfg)

    root = tk.Tk()
    root.withdraw()                  # se monta a escondidas y se ensena ya hecha
    root.title(f"Gestion de Parcelas - Copernicus  ·  v{__version__}")
    aplicar_tema(root, modo=cfg.get("tema"))      # "claro" u "oscuro"; None = claro
    poner_icono(root)
    root.geometry(geom(1440, 900))
    # Por debajo de esto las filas de la ficha -que tienen altura fija- dejan de
    # caber, y `pack` recorta sin avisar. Mejor que el gestor de ventanas lo impida.
    root.minsize(esc(1024), esc(640))

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    panel = PanelGestionParcelas(nb)
    nb.add(panel, text="  Gestion de Parcelas  ")
    nb.add(PanelCredenciales(nb, al_cambiar=panel._refrescar), text="  Credenciales  ")

    def al_cerrar():
        """Al cerrar la ventana: pedir que pare la sincronizacion en curso antes de
        destruir nada. Los hilos son `daemon`, asi que el proceso no se quedaria
        colgado, pero cortarlos en seco a mitad de un recorrido de cientos de
        parcelas deja el trabajo a medias sin motivo: avisando, el recorrido se
        detiene limpiamente en cuanto acaba la parcela que tuviera entre manos."""
        try:
            panel.detener_sincronizacion()
        except Exception:
            log.debug("no se pudo detener la sincronizacion al cerrar", exc_info=True)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", al_cerrar)

    root.deiconify()                 # de golpe, sin verla construirse por partes

    # La comprobacion de Earth Engine es una llamada de RED, y estaba ANTES de la
    # ventana: la pantalla se quedaba vacia todo lo que tardase el servidor -y sin
    # salida a internet, hasta que venciera el plazo-. Ahora va detras y en
    # segundo plano; solo sirve para avisar por consola. El panel de Credenciales
    # la repite por su cuenta y ensena el resultado en su insignia.
    if _EE:
        def _aviso_gee():
            est, msg = CRED.probar_gee(cfg.get("gee_project"), cfg.get("gee_key_file"),
                                       cfg.get("gee_service_account"))
            if est != "ok":
                print(f"Aviso GEE: {msg}")
        threading.Thread(target=_aviso_gee, daemon=True).start()

    root.mainloop()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
