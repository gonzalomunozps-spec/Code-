# -*- coding: utf-8 -*-
"""
ui_copias.py
============

`DialogoCopias`: la ventana de COPIAS DE SEGURIDAD. Deja crear una copia al
momento, ver las que hay, restaurar una y exportar una copia a donde el usuario
quiera (pen-drive, carpeta de red). Se abre desde la barra de la ventana
principal.

La logica de copiar/rotar vive en `copias` (sin Tk, probada aparte); aqui solo
esta el dialogo. Restaurar NO cierra la base: usa `almacen.restaurar_desde`, que
vuelca la copia por dentro de la conexion viva (backup online de SQLite). Cerrar
y sustituir el fichero por debajo era una carrera con los hilos de fondo.
"""

from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ui_tema import TEMA, FUENTES, centrar_sobre
import almacen as DB
import copias


class DialogoCopias(tk.Toplevel):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.title("Copias de seguridad")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(panel.winfo_toplevel())
        self.lift()
        self.after(60, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))
        self.grab_set()

        tk.Label(self, text="Copias de seguridad de tus datos", bg=TEMA["surface"],
                 fg=TEMA["text"], font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(self, text="Toda la informacion (parcelas, pasadas, cuaderno, observaciones) "
                            "vive en una sola base de datos. Haz copias a menudo; se guarda "
                            "una automatica al abrir el programa.",
                 bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"],
                 wraplength=460, justify="left").pack(anchor="w", padx=16, pady=(0, 8))

        wrap = tk.Frame(self, bg=TEMA["surface"])
        wrap.pack(fill="both", expand=True, padx=16)
        self.lst = tk.Listbox(wrap, height=8, width=54, font=FUENTES["small"], bd=1,
                              relief="solid", bg=TEMA["campo_bg"], fg=TEMA["text"],
                              highlightthickness=0, activestyle="none", exportselection=False)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.lst.yview)
        self.lst.configure(yscrollcommand=sb.set)
        self.lst.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        bar = tk.Frame(self, bg=TEMA["surface"])
        bar.pack(fill="x", padx=16, pady=(8, 4))
        ttk.Button(bar, text="Crear copia ahora", style="Accent.TButton",
                   command=self._crear).pack(side="left")
        ttk.Button(bar, text="Restaurar seleccionada", command=self._restaurar).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Exportar a…", command=self._exportar).pack(side="left", padx=(8, 0))

        self.lbl_dir = tk.Label(self, text="", bg=TEMA["surface"], fg=TEMA["text_muted"],
                                font=FUENTES["small"], wraplength=460, justify="left")
        self.lbl_dir.pack(anchor="w", padx=16, pady=(0, 4))
        ttk.Button(self, text="Cerrar", style="Ghost.TButton",
                   command=self.destroy).pack(anchor="e", padx=16, pady=(0, 14))

        self._recargar()

    def _recargar(self):
        self._copias = copias.listar()
        self.lst.delete(0, tk.END)
        for c in self._copias:
            cuando = datetime.fromtimestamp(c["mtime"]).strftime("%d-%m-%Y %H:%M")
            self.lst.insert(tk.END, f"{cuando}   ·   {copias.texto_tamano(c['bytes'])}")
        if not self._copias:
            self.lst.insert(tk.END, "  (todavia no hay copias)")
            self.lst.itemconfig(0, foreground=TEMA["text_muted"])
        self.lbl_dir.config(text=f"Se guardan en: {copias.dir_copias()}")

    def _crear(self):
        ruta = copias.crear_copia(DB.RUTA_DB)
        if ruta:
            self._recargar()
            messagebox.showinfo("Copia creada", "Copia de seguridad guardada.", parent=self)
        else:
            messagebox.showwarning("Copia", "No se pudo crear la copia (¿hay datos guardados?).",
                                   parent=self)

    def _seleccionada(self):
        sel = self.lst.curselection()
        if not sel or not self._copias or sel[0] >= len(self._copias):
            return None
        return self._copias[sel[0]]

    def _restaurar(self):
        c = self._seleccionada()
        if not c:
            return messagebox.showinfo("Restaurar", "Elige una copia de la lista.", parent=self)
        cuando = datetime.fromtimestamp(c["mtime"]).strftime("%d-%m-%Y %H:%M")
        if not messagebox.askyesno(
                "Restaurar copia",
                f"Vas a sustituir TODOS los datos actuales por la copia del {cuando}.\n\n"
                "Se guardara antes una copia de los datos de ahora, por si acaso. "
                "El programa recargara la lista.\n\n¿Continuar?", parent=self):
            return
        # Red de seguridad: los datos de AHORA, con su propio prefijo (no entra en
        # la lista ni en la rotacion). `maximo=0` para no rotar por esto.
        copias.crear_copia(DB.RUTA_DB, maximo=0, prefijo=copias.PREFIJO_RESTAURAR)
        # La restauracion va POR DENTRO de la conexion viva (backup online de
        # SQLite). NO se cierra la base: cerrarla y sustituir el fichero por debajo
        # es una carrera con los hilos de fondo -la sincronizacion automatica
        # arranca sola- que dejaba al hilo escribiendo sobre una conexion cerrada.
        ok = DB.restaurar_desde(c["ruta"])
        if ok:
            try:
                self.panel._refrescar()
            except Exception:
                pass
            self._recargar()
            messagebox.showinfo("Restaurado", "Datos restaurados desde la copia.", parent=self)
        else:
            messagebox.showerror("Restaurar", "No se pudo restaurar la copia.", parent=self)

    def _exportar(self):
        destino = filedialog.asksaveasfilename(
            parent=self, title="Exportar copia de seguridad", defaultextension=".db",
            filetypes=[("Base de datos", "*.db")],
            initialfile=f"parcelas_{datetime.now().strftime('%Y%m%d')}.db")
        if not destino:
            return
        if copias.exportar(DB.RUTA_DB, destino):
            messagebox.showinfo("Exportar", f"Copia guardada en:\n{destino}", parent=self)
        else:
            messagebox.showwarning("Exportar", "No se pudo exportar la copia.", parent=self)
