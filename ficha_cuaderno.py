# -*- coding: utf-8 -*-
"""
ficha_cuaderno.py
=================

`CuadernoMixin`: la parte de la ficha de parcela que gestiona el CUADERNO DE
CAMPO (intervenciones) y el historico de rendimientos. Es un mixin de
`FichaParcela` (en `ui_ficha`): comparte su `self` -mismos atributos y metodos-,
solo vive en otro fichero para que la ficha no sea un unico modulo gigante.

No cambia ningun comportamiento: los nombres de metodo (`_build_cuaderno`,
`_add_evento`, `_refrescar_eventos`...) y los widgets que crea (`self.tv_ev`,
`self.lst_rend`, `self.ev_*`) son exactamente los de antes.
"""

from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox

from ui_tema import TEMA, FUENTES, esc, tarjeta
from ui_widgets import CampoFecha
from ui_dialogos import DialogoEfectoProducto
import almacen as DB
import registro_parcela as REG


class CuadernoMixin:
    def _build_cuaderno(self, parent):
        card = tarjeta(parent)
        card.pack(fill="both", expand=True)
        self._titulo(card, "Cuaderno de campo (intervenciones)")

        form = tk.Frame(card, bg=TEMA["surface"])
        form.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(form, text="Fecha de la intervencion", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=0, sticky="w")
        self.ev_fecha = CampoFecha(form, iso=datetime.now().strftime("%Y-%m-%d"))  # hoy por defecto
        self.ev_fecha.grid(row=1, column=0, padx=(0, 8), sticky="w")
        tk.Label(form, text="Tipo", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=1, sticky="w")
        self.ev_tipo = ttk.Combobox(form, state="readonly", width=12, values=REG.TIPOS_EVENTO)
        self.ev_tipo.set("PRODUCTO")
        self.ev_tipo.grid(row=1, column=1, padx=(0, 8))
        self.ev_tipo.bind("<<ComboboxSelected>>", lambda e: self._toggle_campos_evento())
        # al cambiar la fecha puede cambiar la campana (y con ella el cultivo), asi
        # que se revisa si toca ensenar la humedad. add="+" para no pisar el manejador
        # propio de CampoFecha.
        self.ev_fecha.entry.bind("<FocusOut>", lambda e: self._toggle_campos_evento(), add="+")

        # campos especificos de PRODUCTO
        self.frame_prod = tk.Frame(form, bg=TEMA["surface"])
        self.frame_prod.grid(row=1, column=2, columnspan=3, sticky="w")
        tk.Label(self.frame_prod, text="Producto", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.ev_prod = ttk.Entry(self.frame_prod, width=16)
        self.ev_prod.grid(row=0, column=1, padx=(0, 8))
        tk.Label(self.frame_prod, text="Objetivo", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.ev_obj = ttk.Combobox(self.frame_prod, state="readonly", width=22,
                                   values=REG.OBJETIVOS_PRODUCTO)
        self.ev_obj.set(REG.OBJETIVOS_PRODUCTO[0])
        self.ev_obj.grid(row=0, column=3, padx=(0, 8))
        tk.Label(self.frame_prod, text="Dosis", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=4, sticky="w", padx=(0, 4))
        self.ev_dosis = ttk.Entry(self.frame_prod, width=10)
        self.ev_dosis.grid(row=0, column=5)
        tk.Label(self.frame_prod, text="Dia informe (opc.)", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=6, sticky="w", padx=(8, 4))
        self.ev_informe = CampoFecha(self.frame_prod, width=11)
        self.ev_informe.grid(row=0, column=7, columnspan=2, sticky="w")

        # campos especificos de COSECHA. Todos OPCIONALES: son el dato de bascula,
        # no una estimacion. Comparten celda con frame_prod (nunca se ven a la vez).
        self.frame_cosecha = tk.Frame(form, bg=TEMA["surface"])
        self.frame_cosecha.grid(row=1, column=2, columnspan=3, sticky="w")
        tk.Label(self.frame_cosecha, text="Rendimiento (kg/ha)", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.ev_rend = ttk.Entry(self.frame_cosecha, width=9)
        self.ev_rend.grid(row=0, column=1, padx=(0, 8))
        # la humedad solo tiene sentido en grano de extensivo: en el resto no hay dato
        self.frame_humedad = tk.Frame(self.frame_cosecha, bg=TEMA["surface"])
        self.frame_humedad.grid(row=0, column=2, sticky="w")
        tk.Label(self.frame_humedad, text="Humedad grano (%)", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.ev_humedad = ttk.Entry(self.frame_humedad, width=7)
        self.ev_humedad.grid(row=0, column=1, padx=(0, 8))
        tk.Label(self.frame_cosecha, text="Superficie (ha)", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).grid(row=0, column=3, sticky="w", padx=(0, 4))
        self.ev_sup = ttk.Entry(self.frame_cosecha, width=8)
        self.ev_sup.grid(row=0, column=4, padx=(0, 8))
        tk.Label(self.frame_cosecha, text="Origen del dato", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).grid(row=0, column=5, sticky="w", padx=(0, 4))
        self.ev_fuente = ttk.Combobox(self.frame_cosecha, state="readonly", width=15,
                                      values=[""] + list(REG.FUENTES_DATO))
        self.ev_fuente.set("")
        self.ev_fuente.grid(row=0, column=6)

        tk.Label(form, text="Notas", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).grid(row=0, column=5, sticky="w")
        self.ev_notas = ttk.Entry(form, width=26)
        self.ev_notas.grid(row=1, column=5, padx=(8, 8))
        ttk.Button(form, text="Anadir", style="Accent.TButton",
                   command=self._add_evento).grid(row=1, column=6, padx=4)

        cols = ("fecha", "tipo", "detalle", "efecto")
        self.tv_ev = ttk.Treeview(card, columns=cols, show="headings", height=5)
        for c, w in [("fecha", 90), ("tipo", 90), ("detalle", 300), ("efecto", 260)]:
            self.tv_ev.heading(c, text=c.capitalize())
            self.tv_ev.column(c, width=esc(w), anchor="w")
        self.tv_ev.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.tv_ev.bind("<Double-1>", lambda e: self._ver_efecto_evento())
        self.tv_ev.bind("<Button-3>", self._menu_evento)
        tk.Label(card, text="Doble clic en un producto: ver su efecto sobre el cultivo. "
                            "Clic derecho: eliminar.", bg=TEMA["surface"],
                 fg=TEMA["text_muted"], font=FUENTES["small"]).pack(anchor="w", padx=12, pady=(0, 4))

        # Historico de cosecha: lo unico medido en bascula, no interpretado.
        # Se listan TODAS las campanas, no solo la que se esta viendo.
        tk.Label(card, text="Rendimientos registrados  ·  se anotan con un evento COSECHA (grano) "
                           "o SIEGA (forraje), que admite fechas de campanas anteriores",
                 bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=12)
        # Lista ACOTADA (ALTO_RENDIMIENTOS filas) con su propia barra: el historico
        # crece una linea por campana y esta ficha vive en un marco de altura fija,
        # asi que una etiqueta multilinea acabaria comiendose la tabla de eventos o
        # recortandose sola. Con la lista, ocupe lo que ocupe el historico, el alto
        # del cuaderno no se mueve.
        wrap_rend = tk.Frame(card, bg=TEMA["surface"])
        wrap_rend.pack(fill="x", padx=12, pady=(2, 10))
        self.lst_rend = tk.Listbox(wrap_rend, height=self.ALTO_RENDIMIENTOS,
                                   font=FUENTES["small"], bd=1, relief="solid",
                                   bg=TEMA["campo_bg"], fg=TEMA["text"],
                                   highlightthickness=0, activestyle="none",
                                   exportselection=False)
        sb_rend = ttk.Scrollbar(wrap_rend, orient="vertical", command=self.lst_rend.yview)
        self.lst_rend.configure(yscrollcommand=sb_rend.set)
        self.lst_rend.pack(side="left", fill="x", expand=True)
        sb_rend.pack(side="right", fill="y")
        self._toggle_campos_evento()
        self._refrescar_eventos()

    def _cultivo_de(self, campana):
        return ((DB.ficha(self.nombre) or {}).get("cultivos_por_campana", {}) or {}).get(campana, {})

    def _campana_evento(self, iso):
        return REG.campana_de_evento(self.ev_tipo.get(), iso, self.campana)

    def _toggle_campos_evento(self):
        tipo = self.ev_tipo.get()
        es_produccion = tipo in ("COSECHA", "SIEGA")   # ambos anotan kg/ha de bascula
        (self.frame_prod.grid if tipo == "PRODUCTO" else self.frame_prod.grid_remove)()
        (self.frame_cosecha.grid if es_produccion else self.frame_cosecha.grid_remove)()
        # la humedad de grano solo tiene sentido en la cosecha de grano, no en la siega
        if tipo == "COSECHA" and self._admite_humedad(self._campana_evento(self.ev_fecha.get_iso())):
            self.frame_humedad.grid()
        else:
            self.frame_humedad.grid_remove()

    def _admite_humedad(self, campana):
        """Si toca pedir la humedad del grano para una cosecha de esa campana. Las
        campanas viejas no suelen tener cultivo registrado: se hereda el de la que
        se esta viendo (ver REG.admite_humedad_en_campana)."""
        return REG.admite_humedad_en_campana(self._cultivo_de(campana),
                                             self._cultivo_de(self.campana))

    def _add_evento(self):
        fecha = self.ev_fecha.get_iso()
        if not fecha:
            return messagebox.showwarning("Fecha", "Elige la fecha de la intervencion (dd-mm-aaaa).")
        ev = {"fecha": fecha, "tipo": self.ev_tipo.get(), "notas": self.ev_notas.get().strip()}
        campana = self._campana_evento(fecha)
        if ev["tipo"] == "PRODUCTO":
            if not self.ev_prod.get().strip():
                return messagebox.showwarning("Producto", "Indica el nombre del producto.")
            ev.update({"producto": self.ev_prod.get().strip(),
                       "objetivo": self.ev_obj.get(), "dosis": self.ev_dosis.get().strip()})
            # dia del informe opcional: fecha en la que se quiere medir el efecto
            if not self.ev_informe.esta_vacio():
                informe = self.ev_informe.get_iso()
                if not informe:
                    return messagebox.showwarning("Dia informe", "Dia del informe: dd-mm-aaaa "
                                                  "(o dejalo vacio para el automatico).")
                ev["fecha_informe"] = informe
        elif ev["tipo"] in ("COSECHA", "SIEGA"):
            es_cosecha = ev["tipo"] == "COSECHA"
            titulo = "Cosecha" if es_cosecha else "Siega"
            # la humedad de grano solo se anota en la cosecha de grano de extensivo;
            # la siega (forraje) guarda kg/ha y superficie, pero no humedad de grano
            admite = es_cosecha and self._admite_humedad(campana)
            if es_cosecha and not admite and self.ev_humedad.get().strip():
                self._toggle_campos_evento()
                return messagebox.showwarning(
                    "Cosecha", "Este cultivo no es grano de extensivo: ahi no se anota "
                    "humedad de grano. Borra ese campo para continuar.")
            try:
                ev.update(REG.datos_cosecha(
                    self.ev_rend.get(), self.ev_humedad.get(), self.ev_sup.get(),
                    self.ev_fuente.get(), admite_humedad=admite))
            except ValueError as e:
                return messagebox.showwarning(titulo, f"Revisa el campo {e}: "
                                              "escribe un numero (o dejalo vacio).")
        REG.registrar_evento(self.nombre, campana, ev)
        self.ev_notas.delete(0, tk.END)
        if hasattr(self, "ev_prod"):
            self.ev_prod.delete(0, tk.END)
            self.ev_dosis.delete(0, tk.END)
            self.ev_informe.set_iso("")
        for w in (getattr(self, "ev_rend", None), getattr(self, "ev_humedad", None),
                  getattr(self, "ev_sup", None)):
            if w is not None:
                w.delete(0, tk.END)
        if hasattr(self, "ev_fuente"):
            self.ev_fuente.set("")
        if campana != self.campana:
            _q = "Siega" if ev["tipo"] == "SIEGA" else "Cosecha"
            messagebox.showinfo(_q, f"Anotada en la campana {campana}. Queda en el "
                                "historico de rendimientos; para ver el evento, cambia a esa "
                                "campana.", parent=self.master)
        self._refrescar_eventos()
        self._pintar_graficas(sorted(self.panel._historico(self.nombre),
                                     key=lambda r: r.get("fecha", "")))
        self.refrescar()   # el evento puede cambiar el diagnostico (siega/cosecha)

    def _refrescar_eventos(self):
        self.tv_ev.delete(*self.tv_ev.get_children())  # vaciado en UNA llamada a Tk
        regs = sorted(self.panel._historico(self.nombre), key=lambda r: r.get("fecha", ""))
        for e in REG.eventos_de(self.nombre, self.campana):
            if e.get("tipo") == "PRODUCTO":
                det = f"{e.get('producto','')} · {e.get('objetivo','')}"
                if e.get("dosis"):
                    det += f" · {e['dosis']}"
                ef = REG.efecto_producto(regs, e)
                efec = (ef["verdicto"] if ef and ef.get("disponible") else
                        (ef["nota"] if ef else "-"))
            else:
                det = e.get("notas", "") or "-"
                efec = "-"
            self.tv_ev.insert("", tk.END, values=(e.get("fecha", ""), e.get("tipo", ""),
                                                  det, efec), tags=(e.get("id", ""),))
        self._refrescar_rendimientos()

    def _refrescar_rendimientos(self):
        if not hasattr(self, "lst_rend") or not self.lst_rend.winfo_exists():
            return
        filas = DB.rendimientos(self.nombre)
        self.lst_rend.delete(0, tk.END)          # vaciado en UNA llamada a Tk
        for r in filas:
            self.lst_rend.insert(tk.END, REG.linea_rendimiento(r))
        if filas:
            self.lst_rend.see(tk.END)            # la campana mas reciente, a la vista
        else:
            self.lst_rend.insert(tk.END, "  (todavia no hay ninguno)")
            self.lst_rend.itemconfig(0, foreground=TEMA["text_muted"])

    def _menu_evento(self, event):
        fila = self.tv_ev.identify_row(event.y)
        if not fila:
            return
        self.tv_ev.selection_set(fila)
        # OJO: el padre es self.master, no self. FichaParcela NO es un widget (es
        # una clase normal que pinta sobre master), asi que tk.Menu(self, ...)
        # reventaba con AttributeError: 'FichaParcela' object has no attribute 'tk'.
        m = tk.Menu(self.master, tearoff=0, bg=TEMA["surface"], fg=TEMA["text"], bd=0)
        m.add_command(label="  Ver efecto", command=self._ver_efecto_evento)
        m.add_separator()
        m.add_command(label="  Eliminar evento", command=self._eliminar_evento)
        m.tk_popup(event.x_root, event.y_root)

    def _eliminar_evento(self):
        sel = self.tv_ev.selection()
        if not sel:
            return
        eid = self.tv_ev.item(sel[0], "tags")[0]
        REG.eliminar_evento(self.nombre, self.campana, eid)
        self._refrescar_eventos()
        self.refrescar()

    def _ver_efecto_evento(self):
        sel = self.tv_ev.selection()
        if not sel:
            return
        eid = self.tv_ev.item(sel[0], "tags")[0]
        ev = next((e for e in REG.eventos_de(self.nombre, self.campana)
                   if e.get("id") == eid), None)
        if not ev or ev.get("tipo") != "PRODUCTO":
            return messagebox.showinfo("Efecto", "Solo los productos tienen efecto medible.")
        regs = sorted(self.panel._historico(self.nombre), key=lambda r: r.get("fecha", ""))
        DialogoEfectoProducto(self.master, self, ev, regs)
