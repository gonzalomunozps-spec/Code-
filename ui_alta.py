# -*- coding: utf-8 -*-
"""
ui_alta.py
==========

Alta y edicion de una parcela, y el relevo de campana:

  VentanaAltaParcela   dibujar el recinto a mano o traerlo de SIGPAC, y el cultivo
  DialogoRelevoCampana el 1 de septiembre, que hacer con cada parcela

Recibe el panel como ARGUMENTO (`panel.guardar_parcela`), no lo importa.
"""


import tkinter as tk
from tkinter import ttk, messagebox

from ui_tema import TEMA, FUENTES, geom, tarjeta, centrar_sobre, marco_scroll

import almacen as DB
import fenologia_especies as FEN
from ui_widgets import CampoFecha
from sigpac import sigpac_consultar, SigpacError
from sigpac import _sigpac_get
from mapas_cache import nombre_seguro

try:
    import tkintermapview
    _MAPVIEW = True
except Exception:
    _MAPVIEW = False

# Integrales termicas (grados-dia): modulo OPCIONAL. Si no esta, el formulario no
# ensena la seccion y la parcela se guarda sin integrales, exactamente como antes.
try:
    import grados_dia as _GDD
    _HAY_GDD = True
except Exception:
    _HAY_GDD = False

# Margen interior por defecto de la rejilla. Mismo valor que
# gee_cliente.BUFFER_INTERIOR_M; se repite para no importar ese modulo (que
# arrastra `ee`) solo por un numero que hay que ensenar en un formulario.
BUFFER_POR_DEFECTO = 15.0


def _copa_de(entry):
    """Diametro de copa tecleado, en metros, o None si esta vacio o no vale.

    Es OPCIONAL a proposito: sin el, la fraccion de copa se estima del marco y todo
    se comporta como antes de que existiera el campo. Un 0 o un negativo cuentan
    como "no lo se", no como "copa de cero metros"."""
    try:
        v = float((entry.get() or "").strip().replace(",", "."))
    except (ValueError, AttributeError, TypeError):
        return None
    return v if v > 0 else None

class VentanaAltaParcela(tk.Toplevel):
    def __init__(self, panel, editar=None, campana=None):
        super().__init__(panel)
        self.panel = panel
        self.editar = editar                       # nombre de la parcela a editar (o None = alta)
        self.campana_edit = campana or panel.campana
        self.title("Editar parcela" if editar else "Nueva parcela")
        self.geometry(geom(1000, 600))
        self.configure(bg=TEMA["page"])
        self.coords = []
        self.poligono = None
        # integrales termicas (grados-dia) que el usuario anade a mano. Vacia = el
        # programa sigue con el calendario de siempre; con alguna, manda el GDD.
        self.integrales = []
        # de donde salio la geometria actual: "dibujo" (a mano), "sigpac" o
        # "editar". El dibujo a mano MANDA (ver `_clic` y `_sigpac`).
        self._origen_coords = "editar" if editar else None
        # que la ventana se mantenga SIEMPRE por encima de la principal (no se
        # cuele detras al aparecer un aviso de error).
        self.transient(panel.winfo_toplevel())
        self.lift()
        self.after(80, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))

        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        _tit = f"Editar parcela · {editar.replace('_', ' ')}" if editar else "Nueva parcela"
        tk.Label(cab, text=_tit, bg=TEMA["header_bg"], fg=TEMA["text_inv"],
                 font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=10)

        cuerpo = tk.Frame(self, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=14, pady=14)

        form_card = tarjeta(cuerpo, width=360)
        form_card.pack(side="left", fill="y")
        form_card.pack_propagate(False)
        cont_form, form = marco_scroll(form_card, bg=TEMA["surface"], rueda_global=True)
        cont_form.pack(fill="both", expand=True)
        pad = {"padx": 16}

        def etiqueta(t):
            tk.Label(form, text=t, bg=TEMA["surface"], fg=TEMA["text_sec"],
                     font=FUENTES["small"]).pack(anchor="w", **pad)

        tk.Label(form, text="Datos de la parcela", bg=TEMA["surface"], fg=TEMA["text"],
                 font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 8))
        etiqueta("Nombre")
        self.e_nombre = ttk.Entry(form)
        self.e_nombre.pack(fill="x", **pad)
        etiqueta("Propietario")
        self.e_prop = ttk.Entry(form)
        self.e_prop.pack(fill="x", pady=(0, 6), **pad)

        # BUFFER INTERIOR de la rejilla de pixeles. 15 m por defecto: un pixel de
        # Sentinel-2 mas margen de geolocalizacion, que es lo que hace falta para
        # que un pixel este fiablemente dentro Y siga estandolo en la pasada
        # siguiente. Se puede subir (camino ancho, lindero con arbolado) o bajar
        # (parcela pequena y limpia), incluso a 0.
        etiqueta(f"Margen interior de la parcela (m) — por defecto {BUFFER_POR_DEFECTO:.0f}")
        self.e_buffer = ttk.Entry(form, width=10)
        self.e_buffer.pack(anchor="w", **pad)
        tk.Label(form, text="Descarta los pixeles del borde, mezclados con lindero o camino.\n"
                            "Subirlo limpia mas; bajarlo conserva mas superficie. 0 = sin margen.",
                 bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"],
                 justify="left").pack(anchor="w", pady=(0, 6), **pad)

        fila = tk.Frame(form, bg=TEMA["surface"])
        fila.pack(fill="x", **pad)
        colt = tk.Frame(fila, bg=TEMA["surface"])
        colt.pack(side="left", fill="x", expand=True)
        tk.Label(colt, text="Tipo", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w")
        self.cb_tipo = ttk.Combobox(colt, state="readonly",
                                    values=["EXTENSIVO", "LENOSO", "BARBECHO"])
        self.cb_tipo.pack(fill="x")
        self.cb_tipo.bind("<<ComboboxSelected>>", self._sub)
        cols = tk.Frame(fila, bg=TEMA["surface"])
        cols.pack(side="left", fill="x", expand=True, padx=(8, 0))
        tk.Label(cols, text="Especie", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w")
        self.cb_sub = ttk.Combobox(cols, state="readonly", values=[])
        self.cb_sub.pack(fill="x")
        # al cambiar la especie, refrescar las fases que ofrece la seccion de integrales
        self.cb_sub.bind("<<ComboboxSelected>>", lambda e: self._refrescar_fases_integral())

        # campos especificos de la especie: siembra (cereal) o marco (leñoso)
        self.frame_spec = tk.Frame(form, bg=TEMA["surface"])
        self.frame_spec.pack(fill="x", **pad)
        # finalidad (solo extensivos): grano vs siega en verde
        self.lbl_finalidad = tk.Label(self.frame_spec, text="Finalidad del cultivo",
                                      bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.cb_finalidad = ttk.Combobox(self.frame_spec, state="readonly",
                                         values=["Cosecha de grano", "Siega en verde (forraje)"])
        self.cb_finalidad.set("Cosecha de grano")
        # siembra
        self.lbl_siembra = tk.Label(self.frame_spec, text="Fecha de siembra",
                                    bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.e_siembra = CampoFecha(self.frame_spec)
        # marco
        self.lbl_marco = tk.Label(self.frame_spec, text="Marco de plantacion (calle x pie, m)",
                                  bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.marco_wrap = tk.Frame(self.frame_spec, bg=TEMA["surface"])
        self.e_calle = ttk.Entry(self.marco_wrap, width=7)
        self.e_pie = ttk.Entry(self.marco_wrap, width=7)
        tk.Label(self.marco_wrap, text="calle", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left")
        self.e_calle.pack(side="left", padx=(4, 4))
        tk.Label(self.marco_wrap, text="x pie", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left")
        self.e_pie.pack(side="left", padx=(4, 0))
        # DIAMETRO DE COPA: opcional, pero es el dato que de verdad fija cuanto
        # suelo tapa el arbol, y de ahi salen los umbrales en escala de parcela.
        # Sin el se estima del marco, que no distingue un olivar viejo de uno joven
        # plantado igual. Vacio = como hasta ahora.
        tk.Label(self.marco_wrap, text="  copa", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left")
        self.e_copa = ttk.Entry(self.marco_wrap, width=5)
        self.e_copa.pack(side="left", padx=(4, 0))
        tk.Label(self.marco_wrap, text="m", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left", padx=(2, 0))
        # etiqueta que muestra el tipo deducido del marco
        # REGIMEN HIDRICO: en lenosos pesa mas que la especie. Un olivar de secano
        # en julio esta en deficit por diseno; el mismo dato en un seto regado
        # significa que ha fallado el riego.
        self.lbl_regimen = tk.Label(self.frame_spec, text="Regimen hidrico",
                                    bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.cb_regimen = ttk.Combobox(self.frame_spec, state="readonly", width=14,
                                       values=["Secano", "Regadio"])
        self.cb_regimen.set("Secano")
        self.lbl_tipo_calc = tk.Label(self.frame_spec, text="", bg=TEMA["surface"],
                                      fg=TEMA["ok_fg"], font=FUENTES["small"])
        self.e_calle.bind("<KeyRelease>", lambda e: self._calc_marco())
        self.e_pie.bind("<KeyRelease>", lambda e: self._calc_marco())
        self.e_copa.bind("<KeyRelease>", lambda e: self._calc_marco())

        box = tarjeta(form)
        box.pack(fill="x", padx=16, pady=12)
        tk.Label(box, text="Geometria por SIGPAC  (Agr y Zona: 0 si no aplica)",
                 bg=TEMA["surface"], fg=TEMA["text"],
                 font=FUENTES["small"]).grid(row=0, column=0, columnspan=6, sticky="w",
                                             padx=8, pady=(8, 4))
        self.sig = {}
        campos = ["Prov", "Mun", "Agr", "Zona", "Pol", "Par", "Rec"]
        for i, kk in enumerate(campos):
            tk.Label(box, text=kk, bg=TEMA["surface"], fg=TEMA["text_muted"],
                     font=FUENTES["small"]).grid(row=1 + i // 3, column=(i % 3) * 2,
                                                 sticky="w", padx=(8, 2))
            e = ttk.Entry(box, width=6)
            e.grid(row=1 + i // 3, column=(i % 3) * 2 + 1, padx=2, pady=2)
            if kk in ("Agr", "Zona"):
                e.insert(0, "0")
            self.sig[kk] = e
        fila_btn = 1 + (len(campos) + 2) // 3
        ttk.Button(box, text="Capturar recinto SIGPAC", command=self._sigpac).grid(
            row=fila_btn, column=0, columnspan=6, sticky="ew", padx=8, pady=(6, 8))

        # --- INTEGRALES TERMICAS (grados-dia): seccion OPCIONAL, debajo de SIGPAC ---
        # Solo aparece si el modulo grados_dia esta presente. Si el usuario no anade
        # ninguna, la parcela se guarda igual que antes y manda el calendario; en
        # cuanto anade una, esa integral pasa a fijar la fase del extensivo.
        if _HAY_GDD:
            self._construir_integrales(form, pad)

        tk.Label(form, text="...o dibuja los bordes en el mapa (clic izquierdo).",
                 bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"]).pack(anchor="w", **pad)
        botones = tk.Frame(form, bg=TEMA["surface"])
        botones.pack(fill="x", padx=16, pady=(4, 0))
        ttk.Button(botones, text="Deshacer punto", command=self._deshacer).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(botones, text="Limpiar", command=self._limpiar).pack(side="left", expand=True, fill="x")
        ttk.Button(form, text="Guardar cambios" if editar else "Guardar parcela",
                   style="Accent.TButton",
                   command=self._guardar).pack(fill="x", padx=16, pady=14)

        mapwrap = tarjeta(cuerpo)
        mapwrap.pack(side="right", fill="both", expand=True, padx=(14, 0))
        if _MAPVIEW:
            # --- barra superior del mapa: buscador de localidades + capa ---
            barra_mapa = tk.Frame(mapwrap, bg=TEMA["surface"])
            barra_mapa.pack(fill="x", padx=8, pady=6)
            tk.Label(barra_mapa, text="Localidad", bg=TEMA["surface"], fg=TEMA["text_sec"],
                     font=FUENTES["small"]).pack(side="left")
            self.e_localidad = ttk.Entry(barra_mapa)
            self.e_localidad.pack(side="left", fill="x", expand=True, padx=6)
            self.e_localidad.bind("<Return>", lambda e: self._buscar_localidad())
            ttk.Button(barra_mapa, text="Buscar", command=self._buscar_localidad).pack(side="left")
            self.cb_capa = ttk.Combobox(barra_mapa, state="readonly", width=10,
                                        values=["Satelite", "Hibrido", "Calles"])
            self.cb_capa.set("Satelite")
            self.cb_capa.pack(side="left", padx=(6, 0))
            self.cb_capa.bind("<<ComboboxSelected>>", lambda e: self._cambiar_capa())

            self.mapa = tkintermapview.TkinterMapView(mapwrap, corner_radius=0)
            self.mapa.pack(fill="both", expand=True, padx=1, pady=1)
            self._cambiar_capa()                         # arranca en satelite
            self.mapa.set_position(40.4167, -3.7037, zoom=6)
            self.mapa.add_left_click_map_command(self._clic)
        else:
            tk.Label(mapwrap, text="tkintermapview no disponible.\nUsa la geometria por SIGPAC.",
                     bg=TEMA["surface"], fg=TEMA["danger_fg"]).pack(expand=True)

        if editar:
            self.after(120, self._prellenar)

    def _prellenar(self):
        """Carga en el formulario los datos de la parcela a editar."""
        ficha = DB.ficha(self.editar) or {}
        self.e_nombre.insert(0, self.editar.replace("_", " "))
        self.e_nombre.config(state="readonly")     # el nombre identifica la parcela: no se cambia aqui
        self.e_prop.insert(0, ficha.get("propietario", ""))
        # codigos SIGPAC guardados: se reponen para no tener que teclearlos otra vez
        # (y para que editar sin tocarlos no borre la provincia y el municipio)
        for k, v in (ficha.get("sigpac") or {}).items():
            if k in self.sig and not self.sig[k].get():
                self.sig[k].insert(0, str(v))
        if ficha.get("buffer_m") is not None:
            self.e_buffer.insert(0, f"{float(ficha['buffer_m']):g}")
        cult = (ficha.get("cultivos_por_campana", {}) or {}).get(self.campana_edit, {})
        tipo = cult.get("tipo", "")
        if tipo:
            self.cb_tipo.set(tipo)
            self._sub()                            # rellena especies y muestra los campos del tipo
            if cult.get("especie"):
                self.cb_sub.set(cult["especie"])
            if tipo == "EXTENSIVO":
                self.cb_finalidad.set("Siega en verde (forraje)"
                                      if cult.get("subtipo") == "SIEGA_VERDE" or cult.get("finalidad") == "SIEGA_VERDE"
                                      else "Cosecha de grano")
                if cult.get("fecha_siembra"):
                    self.e_siembra.set_iso(cult["fecha_siembra"])
            elif tipo == "LENOSO":
                if cult.get("marco_calle") is not None:
                    self.e_calle.insert(0, str(cult["marco_calle"]))
                if cult.get("marco_pie") is not None:
                    self.e_pie.insert(0, str(cult["marco_pie"]))
                if cult.get("diametro_copa"):
                    self.e_copa.insert(0, str(cult["diametro_copa"]))
                # regimen guardado; los cultivos anteriores a este campo son SECANO,
                # que es el supuesto que no avisa donde el deficit es normal
                self.cb_regimen.set("Regadio" if cult.get("regimen") == "REGADIO" else "Secano")
                self._calc_marco()
        # integrales termicas ya guardadas: reponerlas para poder verlas/editarlas
        guardadas = cult.get("integrales_termicas")
        if guardadas:
            self.integrales = [dict(it) for it in guardadas]
            self._refrescar_fases_integral()
            self._pintar_lista_integrales()
        # geometria: cargar los vertices y dibujarlos (sin el punto de cierre duplicado)
        coords = ficha.get("coordenadas") or []
        if len(coords) >= 2 and coords[0] == coords[-1]:
            coords = coords[:-1]
        self.coords = [list(c) for c in coords]
        if _MAPVIEW and self.coords:
            self._redibujar()
            self.mapa.set_position(self.coords[0][1], self.coords[0][0], zoom=15)

    def _cambiar_capa(self):
        capa = self.cb_capa.get() if hasattr(self, "cb_capa") else "Satelite"
        servidores = {
            "Satelite": "https://mt0.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
            "Hibrido":  "https://mt0.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
            "Calles":   "https://mt0.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        }
        self.mapa.set_tile_server(servidores.get(capa, servidores["Satelite"]), max_zoom=22)

    def _buscar_localidad(self):
        texto = self.e_localidad.get().strip()
        if not texto:
            return
        try:
            if not self.mapa.set_address(texto):     # geocodifica y centra el mapa
                messagebox.showinfo("Localidad", "No se encontro la localidad.", parent=self)
        except Exception as e:
            messagebox.showerror("Localidad", f"Error en la busqueda: {e}", parent=self)

    def _sub(self, _=None):
        grupo = self.cb_tipo.get()
        esp = FEN.ESPECIES.get(grupo, [])
        self.cb_sub["values"] = esp
        self.cb_sub.set(esp[0] if esp else "")
        for w in (self.lbl_finalidad, self.cb_finalidad, self.lbl_siembra, self.e_siembra,
                  self.lbl_marco, self.marco_wrap, self.lbl_regimen, self.cb_regimen,
                  self.lbl_tipo_calc):
            w.pack_forget()
        if grupo == "EXTENSIVO":
            self.lbl_finalidad.pack(anchor="w")
            self.cb_finalidad.pack(fill="x", pady=(0, 4))
            self.lbl_siembra.pack(anchor="w")
            self.e_siembra.pack(fill="x")
        elif grupo == "LENOSO":
            self.lbl_marco.pack(anchor="w")
            self.marco_wrap.pack(anchor="w", pady=(0, 2))
            self.lbl_regimen.pack(anchor="w")
            self.cb_regimen.pack(anchor="w", pady=(0, 2))
            self.lbl_tipo_calc.pack(anchor="w")
            self._calc_marco()
        # las fases posibles cambian con el tipo/especie: repoblar desde/hasta
        self._refrescar_fases_integral()

    def _calc_marco(self):
        """Al teclear el marco (o la copa), enseña lo que implica.

        El texto lo redacta `fenologia_especies.texto_marco`, que es donde vive el
        calculo: densidad, tipo de plantacion y que fraccion de suelo tapa la copa,
        que es la que traduce los umbrales a escala de parcela."""
        try:
            c = float(self.e_calle.get().replace(",", "."))
            p = float(self.e_pie.get().replace(",", "."))
            self.lbl_tipo_calc.config(text=FEN.texto_marco(
                self.cb_sub.get() or "OLIVO", c, p, _copa_de(self.e_copa)))
        except Exception:
            self.lbl_tipo_calc.config(text="")

    # ------------------------------------------------------------------
    # Integrales termicas (grados-dia). Todo lo de esta seccion solo se
    # construye si el modulo grados_dia esta disponible (_HAY_GDD).
    # ------------------------------------------------------------------
    def _construir_integrales(self, parent, pad):
        caja = tarjeta(parent)
        caja.pack(fill="x", padx=16, pady=(0, 12))
        tk.Label(caja, text="Integrales térmicas (grados-día) — opcional",
                 bg=TEMA["surface"], fg=TEMA["text"], font=FUENTES["small"]).pack(
            anchor="w", padx=8, pady=(8, 0))
        tk.Label(caja, text="Si añades alguna, la fase del cultivo la marca el GDD y no el "
                            "calendario.\nElige el MÉTODO de cálculo y desde/hasta qué fase "
                            "cuenta. El CERO VEGETATIVO es propio de cada especie: se rellena "
                            "solo al elegir el cultivo, y puedes cambiarlo. Si no añades ninguna, "
                            "todo sigue igual.",
                 bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"],
                 justify="left").pack(anchor="w", padx=8, pady=(0, 4))

        # METODO de calculo (la formula): tiempo termico, directo, exponencial,
        # heliotermico. Se guarda la CLAVE, se ensena la etiqueta.
        self._int_metodo = {et: cl for cl, et in _GDD.METODOS_CALCULO}
        tk.Label(caja, text="Método de cálculo (tipo de integral térmica)", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).pack(anchor="w", padx=8)
        self.cb_int_metodo = ttk.Combobox(caja, state="readonly",
                                           values=[et for _cl, et in _GDD.METODOS_CALCULO])
        self.cb_int_metodo.set(_GDD.etiqueta_calculo(_GDD.METODO_CALC_DEF))
        self.cb_int_metodo.pack(fill="x", padx=8, pady=(0, 4))

        # CERO VEGETATIVO (Tbase) y TOPE, en su propia fila. El cero vegetativo se
        # autorrellena por especie (editable); solo lo usa el tiempo termico.
        fila_cv = tk.Frame(caja, bg=TEMA["surface"])
        fila_cv.pack(fill="x", padx=8, pady=(0, 4))
        ccv = tk.Frame(fila_cv, bg=TEMA["surface"])
        ccv.pack(side="left", fill="x", expand=True)
        tk.Label(ccv, text="Cero vegetativo (°C)", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w")
        self.e_int_cv = ttk.Entry(ccv)
        self.e_int_cv.pack(fill="x")
        ctope = tk.Frame(fila_cv, bg=TEMA["surface"])
        ctope.pack(side="left", fill="x", expand=True, padx=(6, 0))
        tk.Label(ctope, text="Tope Tmáx (°C, opcional)", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w")
        self.e_int_tope = ttk.Entry(ctope)
        self.e_int_tope.pack(fill="x")

        fila = tk.Frame(caja, bg=TEMA["surface"])
        fila.pack(fill="x", padx=8)
        cdesde = tk.Frame(fila, bg=TEMA["surface"])
        cdesde.pack(side="left", fill="x", expand=True)
        tk.Label(cdesde, text="Desde", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w")
        self.cb_int_desde = ttk.Combobox(cdesde, values=[])
        self.cb_int_desde.pack(fill="x")
        chasta = tk.Frame(fila, bg=TEMA["surface"])
        chasta.pack(side="left", fill="x", expand=True, padx=(6, 0))
        tk.Label(chasta, text="Hasta", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w")
        self.cb_int_hasta = ttk.Combobox(chasta, values=[])
        self.cb_int_hasta.pack(fill="x")

        ttk.Button(caja, text="Añadir integral", command=self._anadir_integral).pack(
            fill="x", padx=8, pady=(6, 4))
        self.lst_integrales = tk.Listbox(caja, height=3, font=FUENTES["small"])
        self.lst_integrales.pack(fill="x", padx=8)
        ttk.Button(caja, text="Quitar seleccionada", command=self._quitar_integral).pack(
            fill="x", padx=8, pady=(4, 8))
        self._refrescar_fases_integral()
        self._pintar_lista_integrales()

    def _opciones_fases(self):
        """Endpoints para desde/hasta: siembra, las fases del cultivo y cosecha.

        El usuario puede teclear otro nombre (combobox editable); la referencia de
        bibliografia solo la sabe calcular si coincide con una fase conocida."""
        fases = []
        try:
            fases = FEN.fases_posibles(self.cb_tipo.get(), self.cb_sub.get())
        except Exception:
            fases = []
        return ["siembra"] + list(fases) + ["cosecha"]

    def _refrescar_fases_integral(self):
        """Repuebla desde/hasta con las fases del cultivo elegido (si la seccion existe)."""
        if not hasattr(self, "cb_int_desde"):
            return
        ops = self._opciones_fases()
        self.cb_int_desde["values"] = ops
        self.cb_int_hasta["values"] = ops
        # autorrellenar el CERO VEGETATIVO propio de la especie (editable). Solo si
        # el campo esta vacio: no se pisa lo que el usuario haya tecleado.
        if hasattr(self, "e_int_cv") and not self.e_int_cv.get().strip():
            self.e_int_cv.insert(0, f"{_GDD.cero_vegetativo(self.cb_sub.get()):.0f}")
        if hasattr(self, "e_int_tope") and not self.e_int_tope.get().strip():
            tope = _GDD.tope_sugerido(self.cb_sub.get())
            if tope is not None:
                self.e_int_tope.insert(0, f"{tope:.0f}")

    def _anadir_integral(self):
        et = self.cb_int_metodo.get().strip()
        clave = self._int_metodo.get(et)
        if not clave:
            return messagebox.showwarning("Integral térmica", "Elige un método.", parent=self)
        desde = (self.cb_int_desde.get() or "").strip() or "siembra"
        hasta = (self.cb_int_hasta.get() or "").strip() or "cosecha"
        it = {"metodo": clave, "desde": desde, "hasta": hasta}
        # cero vegetativo y tope: solo tienen sentido con el tiempo termico
        if clave == "tiempo_termico":
            try:
                it["cero_vegetativo"] = self._num_opc(self.e_int_cv.get(), "cero vegetativo",
                                                      por_defecto=_GDD.cero_vegetativo(self.cb_sub.get()))
                tope = self._num_opc(self.e_int_tope.get(), "tope")
                if tope is not None:
                    it["tope"] = tope
            except ValueError as e:
                return messagebox.showwarning("Integral térmica",
                                              f"Revisa «{e}»: escribe un número (o déjalo vacío).",
                                              parent=self)
        self.integrales.append(it)
        self._pintar_lista_integrales()

    @staticmethod
    def _num_opc(txt, campo, por_defecto=None):
        """Convierte un campo opcional a float. Vacio -> por_defecto. Lanza
        ValueError(campo) si no es un numero."""
        t = (txt or "").strip().replace(",", ".")
        if not t:
            return por_defecto
        try:
            return float(t)
        except ValueError:
            raise ValueError(campo)

    def _quitar_integral(self):
        sel = self.lst_integrales.curselection()
        if not sel:
            return
        del self.integrales[sel[0]]
        self._pintar_lista_integrales()

    def _pintar_lista_integrales(self):
        if not hasattr(self, "lst_integrales"):
            return
        self.lst_integrales.delete(0, tk.END)
        for it in self.integrales:
            et = _GDD.etiqueta_integral(it)
            self.lst_integrales.insert(
                tk.END, f"{it.get('desde')} → {it.get('hasta')}  ·  {et}")

    def _clic(self, coords):
        # El dibujo a mano tiene PRIORIDAD: si el recinto actual venia de SIGPAC
        # (o de editar), el primer clic empieza uno NUEVO en vez de anadir vertices
        # sueltos a un poligono que no es del usuario. Asi dibujar siempre gana.
        if self._origen_coords not in (None, "dibujo"):
            self.coords = []
        self._origen_coords = "dibujo"
        self.coords.append([coords[1], coords[0]])
        self._redibujar()

    def _redibujar(self):
        if not _MAPVIEW:
            return
        if self.poligono:
            self.poligono.delete()
            self.poligono = None
        if len(self.coords) >= 3:
            self.poligono = self.mapa.set_polygon([(c[1], c[0]) for c in self.coords],
                                                  fill_color=TEMA["primary"], outline_color=TEMA["parcela_borde"],
                                                  border_width=2)

    def _deshacer(self):
        if self.coords:
            self.coords.pop()
            self._redibujar()

    def _limpiar(self):
        self.coords = []
        self._redibujar()

    def _sigpac(self):
        v = {k: e.get().strip() for k, e in self.sig.items()}
        # obligatorios; Agr/Zona valen 0 si se dejan vacios (recintos sin agregado/zona)
        if not all(v.get(k) for k in ("Prov", "Mun", "Pol", "Par", "Rec")):
            return messagebox.showwarning("SIGPAC", "Rellena al menos Prov, Mun, Pol, Par y Rec.", parent=self)
        # El dibujo a mano manda: si ya hay un recinto DIBUJADO, no se pisa sin
        # permiso. Traer SIGPAC encima de un dibujo tiene que ser una decision.
        if self._origen_coords == "dibujo" and len(self.coords) >= 3:
            if not messagebox.askyesno(
                    "SIGPAC",
                    "Ya has dibujado un recinto a mano en el mapa.\n\n"
                    "El dibujo tiene prioridad. ¿Seguro que quieres reemplazarlo "
                    "por el recinto de SIGPAC?", parent=self):
                return
        # Un recinto SIGPAC se identifica por 7 codigos: prov/mun/agregado/zona/pol/par/rec.
        try:
            coords = sigpac_consultar(v, _sigpac_get)
        except SigpacError as e:
            return messagebox.showerror("SIGPAC", str(e), parent=self)
        except ValueError as e:            # recinto en UTM y sin pyproj para convertir
            return messagebox.showerror("SIGPAC", str(e), parent=self)
        except Exception as e:
            return messagebox.showerror("SIGPAC", f"No se pudo capturar el recinto: {e}", parent=self)
        self.coords = coords
        self._origen_coords = "sigpac"
        if _MAPVIEW:
            self._redibujar()
            self.mapa.set_position(coords[0][1], coords[0][0], zoom=16)
        messagebox.showinfo("SIGPAC", f"Recinto capturado ({len(coords)} vertices).", parent=self)

    def _guardar(self):
        # en edicion el nombre identifica la parcela y no se cambia (campo readonly)
        nombre = self.editar or nombre_seguro(self.e_nombre.get())
        prop = self.e_prop.get().strip()
        tipo, esp = self.cb_tipo.get(), self.cb_sub.get()
        if not nombre or not prop or not tipo:
            return messagebox.showwarning("Datos", "Nombre, propietario y tipo son obligatorios.", parent=self)
        # En ALTA (no en edicion), el nombre no puede chocar con una parcela que ya
        # existe: guardar la pisaria en silencio -mismo nombre = misma clave-, y con
        # ella su historico, su cuaderno y sus validaciones.
        if not self.editar and DB.existe(nombre):
            return messagebox.showwarning(
                "Nombre repetido",
                f"Ya existe una parcela llamada «{nombre.replace('_', ' ')}».\n\n"
                "Elige otro nombre, o abre esa parcela y edítala.", parent=self)
        if tipo != "BARBECHO" and not esp:
            return messagebox.showwarning("Datos", "Selecciona la especie.", parent=self)
        if len(self.coords) < 3:
            return messagebox.showwarning("Geometria", "Define al menos 3 vertices (SIGPAC o mapa).", parent=self)

        spec = {"especie": esp}
        if tipo == "EXTENSIVO":
            spec["finalidad"] = ("SIEGA_VERDE" if self.cb_finalidad.get().startswith("Siega")
                                 else "COSECHA_GRANO")
            if not self.e_siembra.esta_vacio():
                siembra = self.e_siembra.get_iso()
                if not siembra:
                    return messagebox.showwarning("Siembra", "Fecha de siembra: dd-mm-aaaa (o dejala vacia).",
                                                  parent=self)
                spec["fecha_siembra"] = siembra
        elif tipo == "LENOSO":
            try:
                spec["marco_calle"] = float(self.e_calle.get().replace(",", "."))
                spec["marco_pie"] = float(self.e_pie.get().replace(",", "."))
            except ValueError:
                return messagebox.showwarning("Marco", "Indica el marco de plantacion (calle y pie en metros).", parent=self)
            # Un marco no positivo no es un marco. Se avisa aqui en vez de dejarlo
            # pasar: aguas abajo daba una fraccion de copa negativa y un umbral de
            # casi cero, o sea una parcela que dejaba de avisar sin decir nada.
            if spec["marco_calle"] <= 0 or spec["marco_pie"] <= 0:
                return messagebox.showwarning(
                    "Marco", "El marco de plantacion son metros: tienen que ser "
                             "numeros mayores que cero.", parent=self)
            # opcional: sin diametro de copa se estima del marco, como siempre
            spec["diametro_copa"] = _copa_de(self.e_copa)
            spec["regimen"] = "REGADIO" if self.cb_regimen.get().startswith("Rega") else "SECANO"

        # integrales termicas: si el usuario anadio alguna, se guardan y a partir de
        # ahi mandan sobre el calendario. Sin ninguna, no se guarda la clave y la
        # parcela se comporta exactamente como antes de que existiera esta seccion.
        if self.integrales:
            spec["integrales_termicas"] = [dict(it) for it in self.integrales]

        # los codigos SIGPAC tecleados se guardan con la parcela (provincia y
        # municipio), aunque el recinto se haya dibujado a mano despues
        codigos = {k: e.get().strip() for k, e in self.sig.items()} if hasattr(self, "sig") else None
        # margen interior: vacio = usar el de por defecto (se guarda como None)
        buf = (self.e_buffer.get() or "").strip().replace(",", ".")
        if buf:
            try:
                buf = float(buf)
                if buf < 0:
                    raise ValueError
            except ValueError:
                return messagebox.showwarning(
                    "Margen interior", "El margen interior son metros: un numero de 0 en "
                    "adelante (o dejalo vacio para usar el de por defecto).", parent=self)
        else:
            buf = None
        # Cambiar el margen mueve el rectangulo de la rejilla, asi que las que ya
        # estan guardadas dejan de ser comparables con las nuevas: el pixel (i,j)
        # pasa a ser otro trozo de terreno. No se pierden -se pueden volver a
        # descargar- pero conviene decirlo ANTES, no descubrirlo al comparar.
        if self.editar and buf is not None:
            antes = (DB.ficha(self.editar) or {}).get("buffer_m")
            n_rej = DB.tamano_rejillas(self.editar)[0]
            if n_rej and (antes is None or abs(float(antes) - buf) > 1e-9):
                if not messagebox.askyesno(
                        "Margen interior",
                        f"Esta parcela tiene {n_rej} rejilla(s) de pixeles guardadas con el "
                        f"margen anterior.\n\nAl cambiarlo dejan de ser comparables con las "
                        f"nuevas y habra que volver a descargarlas (Sincronizar).\n\n"
                        f"¿Cambiar el margen de todas formas?", parent=self):
                    return
        self.panel.guardar_parcela(nombre, prop, tipo, spec, self.coords,
                                   campana=self.campana_edit, sigpac=codigos, buffer_m=buf)
        if self.editar:
            messagebox.showinfo("OK", f"Cambios guardados en '{nombre.replace('_', ' ')}'.", parent=self)
            self.destroy()
            self.panel.mostrar_ficha(nombre)       # recarga la ficha con los datos nuevos
        else:
            messagebox.showinfo("OK", f"Parcela '{nombre}' guardada.", parent=self)
            self.destroy()

class DialogoRelevoCampana(tk.Toplevel):
    """Al iniciar una campana nueva, recorre las parcelas existentes y pide el cultivo
    de cada una para la nueva campana. Al terminar, ofrece anadir mas parcelas."""

    def __init__(self, panel, pendientes):
        super().__init__(panel)
        self.panel = panel
        self.pendientes = list(pendientes)
        self.idx = 0
        self.title("Nueva campana - Asignacion de cultivos")
        self.geometry(geom(440, 300))
        self.configure(bg=TEMA["page"])
        self.transient(panel.winfo_toplevel())   # siempre por encima de la principal
        self.grab_set()          # modal
        self.lift()
        self.after(80, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))

        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        tk.Label(cab, text=f"Campana {panel.campana}", bg=TEMA["header_bg"], fg=TEMA["text_inv"],
                 font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=8)
        tk.Label(cab, text="Indica el cultivo de cada parcela para la nueva campana.",
                 bg=TEMA["header_bg"], fg=TEMA["header_sub"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(0, 8))

        self.card = tarjeta(self)
        self.card.pack(fill="both", expand=True, padx=14, pady=14)

        self.lbl_parc = tk.Label(self.card, text="", bg=TEMA["surface"], fg=TEMA["text"],
                                 font=FUENTES["h2"])
        self.lbl_parc.pack(anchor="w", padx=16, pady=(14, 4))
        self.lbl_prog = tk.Label(self.card, text="", bg=TEMA["surface"], fg=TEMA["text_muted"],
                                 font=FUENTES["small"])
        self.lbl_prog.pack(anchor="w", padx=16)

        fila = tk.Frame(self.card, bg=TEMA["surface"])
        fila.pack(fill="x", padx=16, pady=14)
        tk.Label(fila, text="Tipo", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=0, sticky="w")
        tk.Label(fila, text="Especie", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.cb_tipo = ttk.Combobox(fila, state="readonly", width=14,
                                    values=["EXTENSIVO", "LENOSO", "BARBECHO"])
        self.cb_tipo.grid(row=1, column=0, sticky="ew")
        self.cb_tipo.bind("<<ComboboxSelected>>", self._sub)
        self.cb_sub = ttk.Combobox(fila, state="readonly", width=16, values=[])
        self.cb_sub.grid(row=1, column=1, sticky="ew", padx=(10, 0))
        self.cb_sub.bind("<<ComboboxSelected>>", lambda e: self._calc_marco())

        # campos por especie: siembra (cereal) o marco (leñoso)
        self.spec_wrap = tk.Frame(self.card, bg=TEMA["surface"])
        self.spec_wrap.pack(fill="x", padx=16)
        self.lbl_finalidad = tk.Label(self.spec_wrap, text="Finalidad del cultivo",
                                      bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.cb_finalidad = ttk.Combobox(self.spec_wrap, state="readonly",
                                         values=["Cosecha de grano", "Siega en verde (forraje)"])
        self.cb_finalidad.set("Cosecha de grano")
        self.lbl_siembra = tk.Label(self.spec_wrap, text="Fecha de siembra",
                                    bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.e_siembra = CampoFecha(self.spec_wrap)
        self.lbl_marco = tk.Label(self.spec_wrap, text="Marco (calle x pie, m)",
                                  bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.marco_wrap = tk.Frame(self.spec_wrap, bg=TEMA["surface"])
        self.e_calle = ttk.Entry(self.marco_wrap, width=7)
        self.e_pie = ttk.Entry(self.marco_wrap, width=7)
        self.e_calle.pack(side="left")
        tk.Label(self.marco_wrap, text="x", bg=TEMA["surface"], fg=TEMA["text_muted"]).pack(side="left", padx=4)
        self.e_pie.pack(side="left")
        # diametro de copa (opcional): ver el campo equivalente en VentanaAltaParcela
        tk.Label(self.marco_wrap, text="  copa", bg=TEMA["surface"],
                 fg=TEMA["text_muted"], font=FUENTES["small"]).pack(side="left")
        self.e_copa = ttk.Entry(self.marco_wrap, width=5)
        self.e_copa.pack(side="left", padx=(4, 0))
        tk.Label(self.marco_wrap, text="m", bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(side="left", padx=(2, 0))
        self.lbl_regimen = tk.Label(self.spec_wrap, text="Regimen hidrico",
                                    bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"])
        self.cb_regimen = ttk.Combobox(self.spec_wrap, state="readonly", width=14,
                                       values=["Secano", "Regadio"])
        self.cb_regimen.set("Secano")
        self.lbl_tipo_calc = tk.Label(self.spec_wrap, text="", bg=TEMA["surface"],
                                      fg=TEMA["ok_fg"], font=FUENTES["small"])
        self.e_calle.bind("<KeyRelease>", lambda e: self._calc_marco())
        self.e_pie.bind("<KeyRelease>", lambda e: self._calc_marco())
        self.e_copa.bind("<KeyRelease>", lambda e: self._calc_marco())

        tk.Label(self.card, text="Si la parcela no se va a sembrar, elige BARBECHO (estado N.A.).",
                 bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"]).pack(
            anchor="w", padx=16)

        ttk.Button(self.card, text="Guardar y siguiente", style="Accent.TButton",
                   command=self._siguiente).pack(fill="x", padx=16, pady=14)
        self._mostrar()

    def _sub(self, _=None):
        grupo = self.cb_tipo.get()
        esp = FEN.ESPECIES.get(grupo, [])
        self.cb_sub["values"] = esp
        self.cb_sub.set(esp[0] if esp else "")
        for w in (self.lbl_finalidad, self.cb_finalidad, self.lbl_siembra, self.e_siembra,
                  self.lbl_marco, self.marco_wrap, self.lbl_regimen, self.cb_regimen,
                  self.lbl_tipo_calc):
            w.pack_forget()
        if grupo == "EXTENSIVO":
            self.lbl_finalidad.pack(anchor="w")
            self.cb_finalidad.pack(fill="x", pady=(0, 4))
            self.lbl_siembra.pack(anchor="w")
            self.e_siembra.pack(fill="x")
        elif grupo == "LENOSO":
            self.lbl_marco.pack(anchor="w")
            self.marco_wrap.pack(anchor="w", pady=(0, 2))
            self.lbl_regimen.pack(anchor="w")
            self.cb_regimen.pack(anchor="w", pady=(0, 2))
            self.lbl_tipo_calc.pack(anchor="w")
            self._calc_marco()

    def _calc_marco(self):
        """Al teclear el marco (o la copa), enseña lo que implica.

        El texto lo redacta `fenologia_especies.texto_marco`, que es donde vive el
        calculo: densidad, tipo de plantacion y que fraccion de suelo tapa la copa,
        que es la que traduce los umbrales a escala de parcela."""
        try:
            c = float(self.e_calle.get().replace(",", "."))
            p = float(self.e_pie.get().replace(",", "."))
            self.lbl_tipo_calc.config(text=FEN.texto_marco(
                self.cb_sub.get() or "OLIVO", c, p, _copa_de(self.e_copa)))
        except Exception:
            self.lbl_tipo_calc.config(text="")

    def _mostrar(self):
        nombre = self.pendientes[self.idx]
        self.lbl_parc.config(text=nombre.replace("_", " "))
        self.lbl_prog.config(text=f"Parcela {self.idx + 1} de {len(self.pendientes)}")
        ficha = DB.ficha(nombre) or {}
        campos = ficha.get("cultivos_por_campana", {})
        prev = campos.get(sorted(campos)[-1]) if campos else None
        self.cb_tipo.set(prev.get("tipo") if prev else "LENOSO")
        self._sub()
        # rellenar con lo de la campana anterior si existe
        if prev:
            if prev.get("especie"):
                self.cb_sub.set(prev["especie"])
                self._sub()
            if prev.get("finalidad") == "SIEGA_VERDE" or prev.get("subtipo") == "SIEGA_VERDE":
                self.cb_finalidad.set("Siega en verde (forraje)")
            if prev.get("fecha_siembra"):
                self.e_siembra.set_iso(prev["fecha_siembra"])
            if prev.get("marco_calle"):
                self.e_calle.delete(0, tk.END); self.e_calle.insert(0, str(prev["marco_calle"]))
                self.e_pie.delete(0, tk.END); self.e_pie.insert(0, str(prev["marco_pie"]))
                self.e_copa.delete(0, tk.END)
                if prev.get("diametro_copa"):
                    self.e_copa.insert(0, str(prev["diametro_copa"]))
                self._calc_marco()

    def _siguiente(self):
        tipo = self.cb_tipo.get()
        esp = self.cb_sub.get()
        if not tipo:
            return messagebox.showwarning("Cultivo", "Selecciona el tipo de cultivo.", parent=self)
        if tipo != "BARBECHO" and not esp:
            return messagebox.showwarning("Cultivo", "Selecciona la especie.", parent=self)
        spec = {"especie": esp} if tipo != "BARBECHO" else {}
        if tipo == "EXTENSIVO":
            spec["finalidad"] = ("SIEGA_VERDE" if self.cb_finalidad.get().startswith("Siega")
                                 else "COSECHA_GRANO")
            if not self.e_siembra.esta_vacio():
                siembra = self.e_siembra.get_iso()
                if not siembra:
                    return messagebox.showwarning("Siembra", "Fecha de siembra: dd-mm-aaaa (o dejala vacia).",
                                                  parent=self)
                spec["fecha_siembra"] = siembra
        if tipo == "LENOSO":
            try:
                spec["marco_calle"] = float(self.e_calle.get().replace(",", "."))
                spec["marco_pie"] = float(self.e_pie.get().replace(",", "."))
            except ValueError:
                return messagebox.showwarning("Marco", "Indica el marco (calle y pie en metros).", parent=self)
            if spec["marco_calle"] <= 0 or spec["marco_pie"] <= 0:
                return messagebox.showwarning(
                    "Marco", "El marco de plantacion son metros: tienen que ser "
                             "numeros mayores que cero.", parent=self)
            # opcional: sin diametro de copa se estima del marco, como siempre
            spec["diametro_copa"] = _copa_de(self.e_copa)
            spec["regimen"] = "REGADIO" if self.cb_regimen.get().startswith("Rega") else "SECANO"
        self.panel.asignar_cultivo(self.pendientes[self.idx], tipo, spec)
        self.idx += 1
        if self.idx < len(self.pendientes):
            self._mostrar()
        else:
            self.destroy()
            if messagebox.askyesno("Nueva campana",
                                   "Cultivos asignados. Deseas anadir alguna parcela mas?",
                                   parent=self.panel.winfo_toplevel()):
                self.panel.abrir_alta_parcela()
