# -*- coding: utf-8 -*-
"""
ficha_export.py
===============

`ExportMixin`: los botones de EXPORTAR de la ficha (informe de balance, informe
tecnico, hoja Excel), que delegan en el modulo OPCIONAL `informe_anual`. Mixin de
`FichaParcela` (en `ui_ficha`): comparte su `self`.

Si `informe_anual` se borra, el boton de exportar ni siquiera aparece (la ficha
lo comprueba). No cambia ningun comportamiento respecto a cuando esto vivia dentro
de `ui_ficha`.
"""

import threading

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ui_tema import TEMA, FUENTES, centrar_sobre
from ficha_comun import _abrir_archivo
import almacen as DB
import registro_parcela as REG

try:
    import informe_anual as _INFORME
except Exception:
    _INFORME = None


class ExportMixin:
    def _menu_exportar(self):
        """Menu emergente con los formatos que ofrece el modulo opcional informe_anual.
        Si ese fichero se borra, este boton ni siquiera existe."""
        if _INFORME is None:
            return
        m = tk.Menu(self.master, tearoff=0)
        m.add_command(label="Informe de balance (PDF)",
                      command=lambda: self._exportar("balance"))
        m.add_command(label="Informe tecnico (PDF)",
                      command=lambda: self._exportar("tecnico"))
        m.add_separator()
        excel_ok = getattr(_INFORME, "EXCEL_DISPONIBLE", False)
        m.add_command(label="Hoja de calculo Excel (indices por mes + graficas)"
                            + ("" if excel_ok else "  —  requiere openpyxl"),
                      command=lambda: self._exportar("excel"),
                      state=("normal" if excel_ok else "disabled"))
        try:
            m.tk_popup(self.master.winfo_pointerx(), self.master.winfo_pointery())
        finally:
            m.grab_release()

    def _elegir_secciones_balance(self, radar, eventos):
        """Modal para elegir que secciones incluye el informe de BALANCE.

        Devuelve la lista de claves elegidas, o None si se cancela. Radar y cuaderno
        solo se ofrecen marcados si de verdad hay datos ("los datos que se tienen")."""
        cat = getattr(_INFORME, "SECCIONES_BALANCE", None)
        if not cat:
            return []          # sin catalogo: el informe sale completo
        dlg = tk.Toplevel(self.master)
        dlg.title("Informe de balance · qué incluir")
        dlg.configure(bg=TEMA["page"])
        dlg.transient(self.master)
        dlg.grab_set()
        tk.Label(dlg, text="Elige qué secciones incluir en el informe:", bg=TEMA["page"],
                 fg=TEMA["text"], font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 8))
        # Que secciones tienen datos lo decide el propio modulo de informes, no esta
        # ventana: asi anadir una seccion nueva no obliga a tocar la interfaz.
        try:
            hay = _INFORME.secciones_con_datos(
                self.nombre, self.campana,
                self._cultivo_de(self.campana) if hasattr(self, "_cultivo_de") else None,
                radar, eventos)
        except Exception:
            hay = {"radar": bool(radar), "cuaderno": bool(eventos)}
        cont = tk.Frame(dlg, bg=TEMA["page"])
        cont.pack(fill="x", padx=16)
        vars_ = {}
        for clave, etiqueta in cat:
            disponible = hay.get(clave, True)
            v = tk.BooleanVar(value=disponible)
            vars_[clave] = v
            ttk.Checkbutton(cont, variable=v,
                            text=etiqueta + ("" if disponible else "  (sin datos)")).pack(anchor="w", pady=1)
        res = {"claves": None}
        barra = tk.Frame(dlg, bg=TEMA["page"])
        barra.pack(fill="x", padx=16, pady=14)

        def _generar():
            res["claves"] = [k for k, v in vars_.items() if v.get()]
            dlg.destroy()
        ttk.Button(barra, text="Generar", style="Accent.TButton", command=_generar).pack(side="right")
        ttk.Button(barra, text="Cancelar", command=dlg.destroy).pack(side="right", padx=(0, 8))
        centrar_sobre(dlg, self.master)
        dlg.wait_window()
        return res["claves"]

    def _exportar(self, formato):
        """Genera balance/tecnico (PDF) o Excel. Delegado al modulo opcional informe_anual."""
        if _INFORME is None:
            return
        pdf_ok = getattr(_INFORME, "DISPONIBLE", False)
        excel_ok = getattr(_INFORME, "EXCEL_DISPONIBLE", False)
        if formato in ("balance", "tecnico") and not pdf_ok:
            return messagebox.showwarning(
                "Exportar", getattr(_INFORME, "MOTIVO_NO_DISPONIBLE",
                                    "Falta reportlab."), parent=self.master)
        if formato == "excel" and not excel_ok:
            return messagebox.showwarning(
                "Exportar", getattr(_INFORME, "MOTIVO_EXCEL", "Falta openpyxl."),
                parent=self.master)
        serie = sorted(self.panel._historico(self.nombre), key=lambda r: r.get("fecha", ""))
        if not serie:
            return messagebox.showinfo(
                "Exportar", "Esta parcela aun no tiene pasadas de satelite que resumir.",
                parent=self.master)
        ficha = DB.ficha(self.nombre) or {}
        cultivo = (ficha.get("cultivos_por_campana", {}) or {}).get(self.campana, {})
        radar = sorted(DB.radar(self.nombre, self.campana), key=lambda r: r.get("fecha", ""))
        eventos = REG.eventos_de(self.nombre, self.campana)

        # el informe de balance deja ELEGIR que secciones incluir; el resto va completo
        secciones = None
        if formato == "balance":
            secciones = self._elegir_secciones_balance(radar, eventos)
            if secciones is None:      # cancelado
                return

        cfg = {"balance": ("Informe de balance", _INFORME.generar_informe_anual, ".pdf", "PDF", "pdf"),
               "tecnico": ("Informe tecnico", _INFORME.generar_informe_tecnico, ".pdf", "PDF", "pdf"),
               "excel":   ("Hoja de calculo", _INFORME.generar_excel, ".xlsx", "Excel", "xlsx")}
        titulo, generar, ext, etiq, sufijo = cfg[formato]
        base = "Informe" if formato != "excel" else "Indices"
        destino = filedialog.asksaveasfilename(
            parent=self.master, title=f"Guardar {titulo.lower()}", defaultextension=ext,
            filetypes=[(etiq, f"*{ext}")],
            initialfile=f"{base}_{sufijo}_{self.nombre}_{self.campana}{ext}")
        if not destino:
            return

        def worker():
            try:
                kw = {"secciones": secciones} if formato == "balance" else {}
                ruta = generar(self.nombre, self.campana, ficha, cultivo, serie,
                               radar=radar, eventos=eventos, ruta_salida=destino, **kw)
            except Exception as e:
                self.master.after(0, lambda err=e: messagebox.showerror(
                    titulo, f"No se pudo generar:\n\n{err}", parent=self.master))
                return

            def ok():
                if messagebox.askyesno(titulo, f"Generado:\n{ruta}\n\n¿Abrirlo ahora?",
                                       parent=self.master):
                    _abrir_archivo(ruta)
            self.master.after(0, ok)
        threading.Thread(target=worker, daemon=True).start()
