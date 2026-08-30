# -*- coding: utf-8 -*-
"""
ficha_clima_gdd.py
==================

`ClimaGddMixin`: la parte de la ficha que muestra el CLIMA de la comarca
(ERA5-Land), el contexto hidrico (balance rodante) y los GRADOS-DIA (integral
termica). Es un mixin de `FichaParcela` (en `ui_ficha`): comparte su `self`.

Todo lo de aqui es LECTURA: ensena datos y deja elegir que integral mirar; no
mueve ningun umbral ni fase (eso lo decide el motor). Los modulos `clima_era5`,
`balance_hidrico` y `grados_dia` son OPCIONALES: si faltan, las secciones
correspondientes sencillamente no aparecen. No cambia ningun comportamiento
respecto a cuando estas funciones vivian dentro de `ui_ficha`.
"""

import threading

import tkinter as tk
from tkinter import ttk, messagebox

from ui_tema import TEMA, FUENTES, esc, tarjeta
from cultivo import spec_de
from ficha_comun import _EE

try:
    import clima_era5 as _CLIMA
except Exception:
    _CLIMA = None
try:
    import balance_hidrico as _BH
except Exception:
    _BH = None
try:
    import grados_dia as _GDD
except Exception:
    _GDD = None


class ClimaGddMixin:
    def _build_clima(self, parent):
        """Tabla de clima diario de ERA5-Land. SOLO ENSENA DATOS: de momento no
        mueve ningun diagnostico, ni un umbral, ni una fase."""
        card = tarjeta(parent)
        card.pack(fill="both", expand=True)
        self._titulo(card, "Clima de la comarca (ERA5-Land)")
        self.lbl_clima = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                  font=FUENTES["small"], justify="left", anchor="w",
                                  wraplength=1180)
        self.lbl_clima.pack(fill="x", padx=12, pady=(0, 4))
        # CONTEXTO HIDRICO (balance rodante lluvia-ET0): una linea, solo si el modulo
        # opcional balance_hidrico esta. Es lectura; el mismo dato es el que en el
        # diagnostico decide si un NDMI bajo se explica por la sequia comarcal.
        self.lbl_balance = None
        if _BH is not None:
            self.lbl_balance = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                        font=FUENTES["small"], justify="left", anchor="w",
                                        wraplength=1180)
            self.lbl_balance.pack(fill="x", padx=12, pady=(0, 4))
        cols = [c[0] for c in _CLIMA.COLUMNAS]
        self.tv_clima = ttk.Treeview(card, columns=cols, show="headings", height=6)
        for clave, titulo, ancho, _dec in _CLIMA.COLUMNAS:
            self.tv_clima.heading(clave, text=titulo)
            self.tv_clima.column(clave, width=esc(ancho),
                                 anchor="w" if clave == "fecha" else "center")
        sb = ttk.Scrollbar(card, orient="vertical", command=self.tv_clima.yview)
        self.tv_clima.configure(yscrollcommand=sb.set)
        self.tv_clima.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(0, 12))
        sb.pack(side="right", fill="y", padx=(0, 12), pady=(0, 12))
        ttk.Button(card, text="  Descargar clima  ",
                   command=self._sincronizar_clima).pack(side="bottom", anchor="w",
                                                         padx=12, pady=(0, 8))
        # GRADOS-DIA (integral termica): seccion OPCIONAL, dentro del clima. Solo
        # aparece si el modulo grados_dia esta y la parcela tiene integrales.
        self.gdd_card = None
        if _GDD is not None:
            self._build_gdd(parent)

    def _build_gdd(self, parent):
        """Grados-dia acumulados y las integrales termicas definidas en la parcela.

        Es lectura: ensena el GDD y la fase que sale de el, y deja ELEGIR cual de las
        integrales definidas se mira, con su referencia de bibliografia. Que la fase
        del diagnostico la mande el GDD ya lo decide el motor si hay integral; aqui
        solo se muestra."""
        card = tarjeta(parent)
        self.gdd_card = card
        self._titulo(card, "Grados-día (integral térmica)")
        self.lbl_gdd = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                font=FUENTES["small"], justify="left", anchor="w",
                                wraplength=1180)
        self.lbl_gdd.pack(fill="x", padx=12, pady=(0, 4))
        fila = tk.Frame(card, bg=TEMA["surface"])
        fila.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(fila, text="Integral que se mira:", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left")
        self.cb_gdd = ttk.Combobox(fila, state="readonly", width=48, values=[])
        self.cb_gdd.pack(side="left", padx=(6, 0))
        self.cb_gdd.bind("<<ComboboxSelected>>", lambda e: self._pintar_gdd_sel())
        self.lbl_gdd_ref = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text"],
                                    font=FUENTES["small"], justify="left", anchor="w",
                                    wraplength=1180)
        self.lbl_gdd_ref.pack(fill="x", padx=12, pady=(0, 10))

    def _pintar_clima(self):
        """Vuelca los dias de clima del punto de rejilla de esta parcela."""
        if _CLIMA is None or not hasattr(self, "tv_clima") or not self.tv_clima.winfo_exists():
            return
        dias = _CLIMA.clima_de_parcela(self.nombre, self.campana)
        self.tv_clima.delete(*self.tv_clima.get_children())
        for fila in _CLIMA.filas_tabla(dias):
            self.tv_clima.insert("", tk.END, values=fila)
        if dias:
            self.lbl_clima.config(
                text=_CLIMA.texto_resumen(_CLIMA.resumen(dias)) +
                "\n⚠ El pixel de ERA5-Land son 11 km de lado (12.392 ha): TODAS tus "
                "parcelas de la comarca reciben el mismo dato. Sirve de contexto, no "
                "para comparar una finca con su vecina. Va con unos 8 dias de retraso.")
        else:
            self.lbl_clima.config(
                text="Sin datos de clima para esta campaña. Pulsa «Descargar clima» "
                     "(hace falta Earth Engine). El dato es de comarca, no de parcela: "
                     "el pixel de ERA5-Land son 11 km de lado.")
        self._pintar_balance(dias)
        self._pintar_gdd(dias)

    def _pintar_balance(self, dias):
        """Una linea con el balance hidrico rodante de la comarca (lluvia-ET0) y su
        severidad. Reutiliza los dias ya cargados; no vuelve a la base. Solo si el
        modulo balance_hidrico esta y hay dias."""
        if _BH is None or not getattr(self, "lbl_balance", None) or not self.lbl_balance.winfo_exists():
            return
        fecha = dias[-1]["fecha"] if dias else None
        ctx = _BH.contexto(dias, fecha) if fecha else None
        if not ctx:
            self.lbl_balance.pack_forget()
            return
        self.lbl_balance.pack(fill="x", padx=12, pady=(0, 4))
        aviso = ("  El déficit prolongado explica un NDMI bajo sin que sea, por sí solo, "
                 "un problema de esta parcela." if ctx["sequia"] else "")
        self.lbl_balance.config(text=_BH.texto_contexto(ctx) + aviso)

    def _pintar_gdd(self, dias):
        """Recalcula y ensena los grados-dia. Solo actua si el modulo esta, la
        parcela tiene integrales y hay una fecha a la que acumular."""
        self._gdd_resumen = None
        if _GDD is None or not getattr(self, "gdd_card", None) or not self.gdd_card.winfo_exists():
            return
        cult = self._cultivo_de(self.campana)
        spec = spec_de(cult)
        # Sin integrales definidas, esta seccion no aporta nada: se esconde y el
        # programa sigue con el calendario, como si no existiera.
        if not spec or not spec.get("integrales_termicas"):
            self.gdd_card.pack_forget()
            return
        self.gdd_card.pack(fill="both", expand=True)
        fecha = dias[-1]["fecha"] if dias else None
        res = _GDD.resumen_parcela(cult.get("tipo"), spec.get("especie"), spec, fecha, self.nombre)
        self._gdd_resumen = res
        if not res:
            self.lbl_gdd.config(text="Integrales térmicas definidas, pero aún no hay clima "
                                     "descargado para acumular grados-día. Pulsa «Descargar clima».")
            self.cb_gdd["values"] = []
            self.cb_gdd.set("")
            self.lbl_gdd_ref.config(text="")
            return
        ac = res.get("gdd_acumulado")
        partes = []
        if ac is not None:
            partes.append(f"GDD acumulado desde la siembra: {ac:.0f} °C·día "
                          f"({res.get('dias', 0)} días" +
                          (f", {res['huecos']} sin dato" if res.get("huecos") else "") + ").")
        if res.get("fase_gdd"):
            partes.append(f"Fase por grados-día: {res['fase_gdd']}.")
        if res.get("faltan_siguiente") is not None:
            partes.append(f"Faltan ~{res['faltan_siguiente']:.0f} °C·día para la siguiente fase.")
        if not res.get("hay_referencia"):
            partes.append("(Este cultivo no tiene tabla de referencia de GDD: la fase la sigue "
                          "marcando el calendario.)")
        elif spec.get("integrales_termicas"):
            partes.append("Con integral definida, la fase del diagnóstico la marca el GDD.")
            if res.get("hitos_propios"):
                partes.append("Afinado con tus valores de GDD entre estados (mandan sobre la "
                              "tabla de bibliografía).")
            if res.get("aviso_metodo"):
                partes.append("⚠ El método elegido no es «tiempo térmico»: sus unidades no "
                              "coinciden con los hitos de fase (en °C·día), así que la fase por "
                              "GDD es solo orientativa.")
        self.lbl_gdd.config(text="  ".join(partes) if partes else
                            "Sin fecha de siembra o sin clima: no se puede acumular todavía.")
        etiquetas = [f"{it['desde']} → {it['hasta']}  ·  {it['metodo']}" for it in res.get("integrales", [])]
        self.cb_gdd["values"] = etiquetas
        if etiquetas:
            self.cb_gdd.current(0)
            self._pintar_gdd_sel()
        else:
            self.cb_gdd.set("")
            self.lbl_gdd_ref.config(text="")

    def _pintar_gdd_sel(self):
        """Ensena la referencia de bibliografia de la integral elegida en el combo."""
        res = getattr(self, "_gdd_resumen", None)
        if not res:
            return
        i = self.cb_gdd.current()
        filas = res.get("integrales", [])
        if i < 0 or i >= len(filas):
            self.lbl_gdd_ref.config(text="")
            return
        it = filas[i]
        ref = it.get("referencia_gdd")
        if ref is not None:
            fuente = it.get("referencia_fuente")
            de_quien = ("tu valor" if fuente == "tuyo" else "referencia de bibliografía")
            txt = (f"De «{it['desde']}» a «{it['hasta']}» ({it['metodo']}): "
                   f"{de_quien} ≈ {ref:.0f} °C·día. "
                   "Compárala con el acumulado real para ver si el cultivo va adelantado o atrasado.")
        else:
            txt = (f"De «{it['desde']}» a «{it['hasta']}» ({it['metodo']}): "
                   "sin referencia para ese tramo (dale un valor °C·día, o pon como extremos "
                   "fases conocidas del cultivo).")
        self.lbl_gdd_ref.config(text=txt)

    def _sincronizar_clima(self):
        if _CLIMA is None:
            return
        if not _EE:
            return messagebox.showwarning("Clima", "earthengine-api no disponible.")
        ficha = self.panel.vista_ficha

        def worker():
            n, msg = _CLIMA.sincronizar_clima(self.nombre, self.campana, silencioso=True)

            def fin():
                if not ficha.winfo_exists():
                    return
                self._pintar_clima()
                messagebox.showinfo("Clima", f"{msg}.")
            ficha.after(0, fin)
        threading.Thread(target=worker, daemon=True).start()
