# -*- coding: utf-8 -*-
"""
ficha_validacion.py
===================

`ValidacionMixin`: la tarjeta de la ficha que lista las OBSERVACIONES DE CAMPO
(verdad-terreno) y muestra la nota del sistema (aciertos de fase, error del GDD,
R² indice<->rendimiento, dron<->satelite). Mixin de `FichaParcela` (en
`ui_ficha`): comparte su `self`.

Solo lectura y captura: el emparejamiento y las metricas viven en
`vista_ficha.resumen_validacion` y en el modulo opcional `validacion`; el dialogo
de anotar, en `ui_dialogos.DialogoObservacionCampo`. No cambia ningun
comportamiento respecto a cuando esto vivia dentro de `ui_ficha`.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from ui_tema import TEMA, FUENTES, tarjeta
from ui_dialogos import DialogoObservacionCampo
from vista_ficha import resumen_validacion
from bitacora import log
import almacen as DB


class ValidacionMixin:
    def _build_validacion(self, parent):
        """Tarjeta de VALIDACION: lista las observaciones de campo (verdad-terreno)
        y, si hay con que emparejar, la nota del sistema (aciertos de fase, error
        del GDD, R² indice<->rendimiento, dron<->satelite). Solo lectura; el boton
        de anotar vive en la cabecera de la ficha."""
        card = tarjeta(parent)
        card.pack(fill="x")
        self._titulo(card, "Validacion con observaciones de campo")
        self.lbl_val_met = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text"],
                                    font=FUENTES["small"], justify="left", anchor="w",
                                    wraplength=1180)
        self.lbl_val_met.pack(fill="x", padx=12, pady=(0, 4))
        wrap = tk.Frame(card, bg=TEMA["surface"])
        wrap.pack(fill="x", padx=12, pady=(0, 12))
        self.lst_val = tk.Listbox(wrap, height=4, font=FUENTES["small"], bd=1, relief="solid",
                                  bg=TEMA["campo_bg"], fg=TEMA["text"], highlightthickness=0,
                                  activestyle="none", exportselection=False)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.lst_val.yview)
        self.lst_val.configure(yscrollcommand=sb.set)
        self.lst_val.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        self.lst_val.bind("<Button-3>", self._menu_observacion)
        tk.Label(card, text="Clic derecho en una observacion: eliminar. Se anotan con el boton "
                            "«Observacion de campo» de la cabecera.",
                 bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(anchor="w", padx=12, pady=(0, 8))

    def _pintar_validacion(self):
        """Rellena la tarjeta de validacion. Robusto: nunca rompe la ficha."""
        if not getattr(self, "lst_val", None) or not self.lst_val.winfo_exists():
            return
        try:
            res = resumen_validacion(self.nombre)
        except Exception:
            log.debug("no se pudo montar el resumen de validacion", exc_info=True)
            return
        self._obs_val = res.get("observaciones", [])
        self.lst_val.delete(0, tk.END)
        for o in self._obs_val:
            partes = [o.get("fecha", "?"), o.get("fuente", "campo")]
            if o.get("fase_obs"):
                partes.append(f"fase={o['fase_obs']}")
            if o.get("rendimiento_kg_ha") is not None:
                partes.append(f"{o['rendimiento_kg_ha']:.0f} kg/ha")
            if o.get("humedad_suelo_pct") is not None:
                partes.append(f"humedad {o['humedad_suelo_pct']:.0f}%")
            if o.get("valor_dron") is not None:
                partes.append(f"{o.get('indice_dron','dron')}={o['valor_dron']:.3f}")
            if o.get("nota"):
                partes.append(f"«{o['nota']}»")
            self.lst_val.insert(tk.END, "  ·  ".join(str(p) for p in partes))
        txt = res.get("texto") or ""
        if txt:
            self.lbl_val_met.config(text=txt, fg=TEMA["text"])
        elif self._obs_val:
            self.lbl_val_met.config(
                text="Observaciones anotadas. Aun no hay con que emparejarlas "
                     "(hacen falta pasadas de satelite en las mismas fechas).",
                fg=TEMA["text_sec"])
        else:
            self.lbl_val_met.config(
                text="Sin observaciones de campo todavia. Anota lo que veas a pie de "
                     "finca, con sonda o con el dron para medir el acierto del sistema.",
                fg=TEMA["text_sec"])

    def _menu_observacion(self, event):
        obs = getattr(self, "_obs_val", [])
        sel = self.lst_val.nearest(event.y)
        if sel < 0 or sel >= len(obs):
            return
        o = obs[sel]
        # self.master, no self: FichaParcela no es un widget (ver _menu_evento)
        menu = tk.Menu(self.master, tearoff=0)
        menu.add_command(label="Eliminar observacion",
                         command=lambda: self._borrar_observacion(o))
        menu.tk_popup(event.x_root, event.y_root)

    def _borrar_observacion(self, o):
        if not messagebox.askyesno("Eliminar observacion",
                                   f"¿Eliminar la observacion del {o.get('fecha','?')}?",
                                   parent=self.master):
            return
        DB.eliminar_observacion(self.nombre, o.get("campana", self.campana), o.get("id"))
        self._pintar_validacion()

    def _observacion_campo(self):
        """Abre el dialogo para anotar una observacion de campo y refresca al cerrar."""
        DialogoObservacionCampo(self.master, self, al_terminar=self._pintar_validacion)
