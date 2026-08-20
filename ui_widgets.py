# -*- coding: utf-8 -*-
"""
ui_widgets.py
=============

Los tres widgets REUTILIZABLES de la aplicacion, los que usa mas de una pantalla:

  LienzoMapa       un PNG con zoom y arrastre (la ficha y la comparacion de mapas)
  PopupCalendario  el calendario emergente
  CampoFecha       entrada de fecha con mascara dd-mm-aaaa y su calendario

No saben nada de parcelas ni de campanas: reciben lo que tienen que pintar. Solo
dependen de `ui_tema`.
"""

import calendar as _cal
import os
import re
from datetime import datetime

import tkinter as tk
from tkinter import ttk

try:
    from PIL import Image, ImageTk
    _PIL = True
except Exception:
    _PIL = False

from ui_tema import TEMA, FUENTES
from fechas import (iso_a_ddmmaaaa, ddmmaaaa_a_iso, enmascarar_fecha,
                    filtrar_fecha_digitos)


class LienzoMapa:
    """Canvas que muestra un PNG con ZOOM (rueda / botones) y DESPLAZAMIENTO
    (arrastrar con el raton) para recorrer las distintas zonas de la parcela.
    Lo usan tanto la ficha como la ventana de comparacion."""
    def __init__(self, parent, bg=None, on_info=None):
        bg = bg or TEMA["lienzo_bg"]
        self.canvas = tk.Canvas(parent, bg=bg, highlightthickness=0)
        self.on_info = on_info                 # callback(texto) para el estado (zoom/resolucion)
        self.png = None
        self.info = ""
        self.img_tk = None
        self.zoom = None                       # None = ajustar al lienzo
        self.offset = [0, 0]                   # desplazamiento (px) respecto al centro
        self._drag = None
        self._im = None                        # imagen PIL cacheada (no reabrir en cada arrastre)
        self._im_path = None
        self._escalada = None                  # (png, ancho, alto) de la imagen YA escalada
        self._item = None                      # id del item del canvas, para moverlo al arrastrar
        c = self.canvas
        c.bind("<Configure>", lambda e: self.redibujar())
        c.bind("<MouseWheel>", lambda e: self.zoom_rel(1.25 if e.delta > 0 else 1 / 1.25))
        c.bind("<Button-4>", lambda e: self.zoom_rel(1.25))
        c.bind("<Button-5>", lambda e: self.zoom_rel(1 / 1.25))
        c.bind("<ButtonPress-1>", self._pan_ini)
        c.bind("<B1-Motion>", self._pan_mov)
        c.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        c.bind("<Double-Button-1>", lambda e: self.ajustar())

    def pack(self, **kw):
        self.canvas.pack(**kw)

    def set_png(self, png, info=""):
        """Cambia la imagen conservando el zoom/desplazamiento (util para comparar
        la MISMA zona entre dias o indices)."""
        self.png = png
        self.info = info
        self.redibujar()

    def mensaje(self, texto, color=None):
        # Puede llegar desde un after() cuando el usuario ya cerro la ventana (las
        # descargas de GEE tardan segundos): si el canvas ya no existe, no hay nada
        # que pintar. Sin esta guarda, Tk lanzaria 'invalid command name'.
        # (redibujar() ya hace esta misma comprobacion, por eso set_png esta cubierto.)
        if not self.canvas.winfo_exists():
            return
        self.canvas.delete("all")          # esto destruye tambien la imagen cacheada...
        self._item = None                  # ...asi que se invalida su id y su escala
        self._escalada = None
        self.canvas.create_text(20, 20, anchor="nw", fill=color or TEMA["text_muted"], text=texto)

    def ajustar(self):
        self.zoom = None
        self.offset = [0, 0]
        self.redibujar()

    def zoom_rel(self, factor):
        base = self.zoom if self.zoom else 1.0
        self.zoom = max(0.2, min(8.0, base * factor))
        self.redibujar()

    def _pan_ini(self, e):
        self._drag = (e.x, e.y, self.offset[0], self.offset[1])

    def _pan_mov(self, e):
        if not self._drag:
            return
        x0, y0, ox, oy = self._drag
        self.offset = [ox + (e.x - x0), oy + (e.y - y0)]
        self.redibujar()

    def redibujar(self):
        c = self.canvas
        if not (c.winfo_exists() and self.png and os.path.exists(self.png) and _PIL):
            return
        if self._im_path != self.png:          # abrir del disco solo al cambiar de imagen
            try:
                self._im = Image.open(self.png).convert("RGBA")
            except Exception:
                return
            self._im_path = self.png
            self._escalada = None              # imagen distinta: hay que reescalar
        base = self._im
        ow, oh = base.size
        cw = max(c.winfo_width(), 50)
        ch = max(c.winfo_height(), 50)
        escala = min(cw / ow, ch / oh)         # ajuste base al lienzo
        if self.zoom is None:
            self.offset = [0, 0]
        else:
            escala *= self.zoom
        nw, nh = max(1, int(ow * escala)), max(1, int(oh * escala))
        x, y = cw // 2 + self.offset[0], ch // 2 + self.offset[1]

        # AL ARRASTRAR solo cambia la POSICION: si la imagen escalada es la misma
        # (mismo PNG, mismo zoom y mismo tamano de lienzo), basta con mover el item.
        # Reescalar en cada movimiento del raton costaba decenas de ms por evento y
        # era lo que hacia que el arrastre fuera a tirones.
        if self._escalada == (self._im_path, nw, nh) and self._item is not None:
            c.coords(self._item, x, y)
        else:
            im = base.resize((nw, nh), Image.NEAREST if escala > 1 else Image.LANCZOS)
            self.img_tk = ImageTk.PhotoImage(im)
            c.delete("all")
            self._item = c.create_image(x, y, image=self.img_tk)
            self._escalada = (self._im_path, nw, nh)
        c.config(scrollregion=c.bbox("all"))
        if self.on_info:
            z = "ajuste" if self.zoom is None else f"{self.zoom:.2f}x"
            self.on_info((f"{self.info}  ·  " if self.info else "") + f"zoom {z}  ·  arrastra para mover")


# Las utilidades de fecha (iso_a_ddmmaaaa, ddmmaaaa_a_iso, enmascarar_fecha,
# filtrar_fecha_digitos) viven ahora en fechas.py y se importan arriba.


class PopupCalendario(tk.Toplevel):
    """Mini calendario. Al elegir un dia llama on_pick(iso) con la fecha ISO."""
    MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

    def __init__(self, parent, on_pick, iso_ini=None, anchor=None):
        super().__init__(parent)
        self.on_pick = on_pick
        self.title("Elegir fecha")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.lift()
        self.after(40, self.focus_force)
        try:
            base = datetime.strptime(iso_ini, "%Y-%m-%d")
        except (ValueError, TypeError):
            base = datetime.now()
        self.anio, self.mes = base.year, base.month
        self._grid = None
        self._build()
        anchor = anchor or parent
        try:
            self.update_idletasks()
            self.geometry(f"+{anchor.winfo_rootx()}+{anchor.winfo_rooty() + anchor.winfo_height() + 2}")
        except Exception:
            pass    # silencio deliberado: posicionar el calendario es cosmetico
        self.after(60, self._grab)

    def _grab(self):
        try:
            self.grab_set()
        except Exception:
            pass    # silencio deliberado: otro modal puede tener el grab; no es un error

    def _build(self):
        cab = tk.Frame(self, bg=TEMA["surface"])
        cab.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Button(cab, text="◀", width=3, command=lambda: self._mover(-1)).pack(side="left")
        tk.Label(cab, text=f"{self.MESES[self.mes - 1]} {self.anio}", bg=TEMA["surface"],
                 fg=TEMA["text"], font=FUENTES["small"], width=16).pack(side="left", expand=True)
        ttk.Button(cab, text="▶", width=3, command=lambda: self._mover(1)).pack(side="left")

        if self._grid:
            self._grid.destroy()
        self._grid = tk.Frame(self, bg=TEMA["surface"])
        self._grid.pack(padx=6, pady=(2, 6))
        for i, d in enumerate(["L", "M", "X", "J", "V", "S", "D"]):
            tk.Label(self._grid, text=d, bg=TEMA["surface"], fg=TEMA["text_muted"], width=3,
                     font=FUENTES["small"]).grid(row=0, column=i)
        cal = _cal.Calendar(firstweekday=0)     # lunes primero
        for r, semana in enumerate(cal.monthdayscalendar(self.anio, self.mes), start=1):
            for cix, dia in enumerate(semana):
                if dia == 0:
                    continue
                ttk.Button(self._grid, text=str(dia), width=3,
                           command=lambda d=dia: self._elegir(d)).grid(row=r, column=cix, padx=1, pady=1)

    def _mover(self, delta):
        self.mes += delta
        if self.mes < 1:
            self.mes, self.anio = 12, self.anio - 1
        elif self.mes > 12:
            self.mes, self.anio = 1, self.anio + 1
        for w in self.winfo_children():
            w.destroy()
        self._grid = None
        self._build()

    def _elegir(self, dia):
        self.on_pick(f"{self.anio:04d}-{self.mes:02d}-{dia:02d}")
        self.destroy()


class CampoFecha(tk.Frame):
    """Campo de fecha reutilizable: entrada con mascara dd-mm-aaaa (los guiones
    salen solos al teclear) + boton de calendario. El programa trabaja en ISO:
    usa get_iso() / set_iso()."""
    PH = "dd-mm-aaaa"

    def __init__(self, parent, iso=None, width=11, **kw):
        super().__init__(parent, bg=TEMA["surface"], **kw)
        self.var = tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self.var, width=width, justify="center",
                              bd=1, relief="solid", bg=TEMA["campo_bg"], fg=TEMA["text"],
                              insertbackground=TEMA["text"], highlightthickness=0)
        self.entry.pack(side="left", ipady=1)
        ttk.Button(self, text="📅", width=3, command=self._abrir_cal).pack(side="left", padx=(2, 0))
        self.entry.bind("<KeyRelease>", self._al_teclear)
        self.entry.bind("<FocusIn>", self._foco_in)
        self.entry.bind("<FocusOut>", self._foco_out)
        if iso:
            self.set_iso(iso)
        else:
            self._poner_ph()

    def _poner_ph(self):
        self.var.set(self.PH)
        self.entry.config(fg=TEMA["text_muted"])

    def _es_ph(self):
        return self.var.get() == self.PH

    def _foco_in(self, _=None):
        if self._es_ph():
            self.var.set("")
            self.entry.config(fg=TEMA["text"])

    def _foco_out(self, _=None):
        if not re.sub(r"\D", "", self.var.get()):
            self._poner_ph()

    def _al_teclear(self, event=None):
        if event and event.keysym in ("Tab", "Left", "Right", "Up", "Down"):
            return
        self.entry.config(fg=TEMA["text"])
        digs = filtrar_fecha_digitos(self.var.get())   # rechaza dia>31 / mes>12 al vuelo
        self.var.set(enmascarar_fecha(digs))
        self.entry.icursor(tk.END)

    def _abrir_cal(self):
        PopupCalendario(self, self._desde_cal, iso_ini=self.get_iso(), anchor=self.entry)

    def _desde_cal(self, iso):
        self.set_iso(iso)

    def get_iso(self):
        """Fecha en ISO (aaaa-mm-dd) o '' si esta vacia/incompleta/invalida."""
        return "" if self._es_ph() else ddmmaaaa_a_iso(self.var.get())

    def set_iso(self, iso):
        txt = iso_a_ddmmaaaa(iso)
        if txt:
            self.var.set(txt)
            self.entry.config(fg=TEMA["text"])
        else:
            self._poner_ph()

    def esta_vacio(self):
        return self._es_ph() or not re.sub(r"\D", "", self.var.get())
