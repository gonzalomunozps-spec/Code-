# -*- coding: utf-8 -*-
"""
ui_dialogos.py
==============

Los dialogos modales que se abren DESDE la ficha de parcela:

  DialogoCorreccion          corregir un diagnostico y elegir su ambito
  DialogoValidacionIndices   validar la pasada indice a indice
  DialogoSincronizarCampanas bajar varias campanas anteriores de una vez
  DialogoEfectoProducto      la respuesta del cultivo tras una aplicacion

Reciben la ficha como ARGUMENTO, no la importan: por eso este modulo no depende
de `ui_ficha` y el grafo se queda sin ciclos. Lo que necesitaban de ella y no era
suyo -la lista de estados validables y la etiqueta de campana- vive ahora en
`interpretacion_fenologica` y en `campanas`, que es de donde salen.
"""

import threading
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox

from ui_tema import TEMA, FUENTES, centrar_sobre, marco_scroll
from ui_widgets import CampoFecha

import almacen as DB
import registro_parcela as REG
import gee_cliente
from gee_cliente import INDICES_ORDEN, sincronizar_parcela
from campanas import campanas_de_parcela, etiqueta_campana, PRIMERA_CAMPANA_S2
from interpretacion_fenologica import ESTADOS_VALIDABLES
import sincronizacion
from sincronizacion import ULTIMO_SYNC
from campanas import PRIMERA_CAMPANA_S2_GLOBAL

try:
    import calibracion_umbrales as _CALIB
except Exception:
    _CALIB = None

_EE = gee_cliente.hay_ee()


def _fases_para(ctx):
    """Las fases que ofrecer en el desplegable, a partir del cultivo del contexto.

    `ctx['cultivo']` es "TIPO/SUBTIPO/ESPECIE". Se leen las fases de la especie;
    si no se reconoce, lista vacia y el usuario teclea la fase libremente."""
    partes = (ctx.get("cultivo") or "").split("/")
    tipo = partes[0] if partes else ""
    especie = partes[-1] if len(partes) >= 3 else ""
    try:
        import fenologia_especies as FEN
        return FEN.fases_posibles(tipo, especie)
    except Exception:
        return []


class DialogoCorreccion(tk.Toplevel):
    """Pide el estado real y una nota para corregir un diagnostico (aprendizaje)."""
    def __init__(self, master, ficha, ctx):
        super().__init__(master)
        self.ficha = ficha
        self._ctx = ctx
        self.title("Corregir diagnostico")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(60, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))
        self.grab_set()

        tk.Label(self, text="El sistema diagnostico:", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(14, 0))
        tk.Label(self, text=f"[{ctx.get('estado','?')}]  ·  Fase: {ctx.get('fase','?')}",
                 bg=TEMA["surface"], fg=TEMA["text"], font=FUENTES["body"]).pack(anchor="w", padx=16)
        tk.Label(self, text="¿Cual era el estado correcto?", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(10, 0))
        self.cb = ttk.Combobox(self, state="readonly", values=ESTADOS_VALIDABLES, width=18)
        self.cb.set(ctx.get("estado", "OK"))
        self.cb.pack(anchor="w", padx=16, pady=(2, 0))

        # --- FASE: se puede corregir a mano (la fenologia por calendario se
        #     equivoca en anos frios/calidos). Editable: elige de la lista o teclea.
        tk.Label(self, text="¿Y la fase? (corrigela si el calendario se equivoca)",
                 bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(10, 0))
        self.cb_fase = ttk.Combobox(self, state="normal", width=30,
                                    values=_fases_para(ctx))
        self.cb_fase.set(ctx.get("fase", "") or "")
        self.cb_fase.pack(anchor="w", padx=16, pady=(2, 0))
        # --- AMBITO de la correccion: solo esta finca o todo el cultivo ---
        tk.Label(self, text="¿A que debe aplicarse esta correccion?", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(12, 0))
        self.ambito = tk.StringVar(value="cultivo")
        _cult = (ctx.get("cultivo", "") or "").split("/")[-1] or "este cultivo"
        _parc = ficha.nombre.replace("_", " ")
        ttk.Radiobutton(self, variable=self.ambito, value="cultivo",
                        text=f"A todas mis parcelas de {_cult}").pack(anchor="w", padx=24)
        ttk.Radiobutton(self, variable=self.ambito, value="parcela",
                        text=f"Solo a «{_parc}» (esta finca es especial)").pack(anchor="w", padx=24)

        tk.Label(self, text="Observacion (opcional):", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(10, 0))
        self.txt = tk.Text(self, width=44, height=4, bd=1, relief="solid",
                           font=FUENTES["body"], highlightthickness=0)
        self.txt.pack(padx=16, pady=(2, 0))
        bar = tk.Frame(self, bg=TEMA["surface"])
        bar.pack(fill="x", padx=16, pady=14)
        ttk.Button(bar, text="Cancelar", style="Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Guardar correccion", style="Accent.TButton",
                   command=self._guardar).pack(side="right", padx=(0, 8))

    def _guardar(self):
        estado_real = self.cb.get()
        nota = self.txt.get("1.0", tk.END).strip()
        # fase corregida: solo si el usuario la ha cambiado respecto a la del sistema
        fase_tecleada = self.cb_fase.get().strip()
        fase_sistema = (self._ctx.get("fase") or "").strip()
        fase_real = fase_tecleada if fase_tecleada and fase_tecleada != fase_sistema else None
        self.ficha._validar("incorrecto", estado_real=estado_real, nota=nota,
                            solo_parcela=(self.ambito.get() == "parcela"),
                            fase_real=fase_real)
        self.destroy()

class DialogoValidacionIndices(tk.Toplevel):
    """Validacion INDICE A INDICE de una pasada, con el alcance de la correccion.

    Cada indice llega con lo que midio el satelite y con lo que el sistema opina
    (bajo / normal / alto), ya preseleccionado en su desplegable: confirmar es no
    tocar nada. Lo que se cambie mueve el umbral de ESE indice, en el alcance
    elegido, sin tocar los valores de la bibliografia.

    Vive detras del modulo opcional `calibracion_umbrales`: si se borra, ni este
    dialogo ni su boton existen.
    """

    def __init__(self, master, ficha, ctx):
        super().__init__(master)
        self.ficha, self.ctx = ficha, ctx
        self.title("Validar indices de la pasada")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(60, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))
        self.grab_set()

        cab = f"{ficha.nombre.replace('_', ' ')}  ·  {ctx.get('fecha', '?')}"
        tk.Label(self, text=cab, bg=TEMA["surface"], fg=TEMA["text"],
                 font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 0))
        sub = f"Fase: {ctx.get('fase', '?')}"
        if ctx.get("especie"):
            sub = f"{ctx['especie']}  ·  " + sub
        tk.Label(self, text=sub, bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16)
        tk.Label(self, text="Confirma o corrige lo que el sistema ve en cada indice. "
                            "Ya viene marcado lo que opina: si estas de acuerdo, no toques nada.",
                 bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"],
                 wraplength=470, justify="left").pack(anchor="w", padx=16, pady=(8, 4))

        tabla = tk.Frame(self, bg=TEMA["surface"])
        tabla.pack(fill="x", padx=16, pady=(0, 4))
        for col, txt in enumerate(("Indice", "Valor", "El sistema ve", "Tu dices")):
            tk.Label(tabla, text=txt, bg=TEMA["surface"], fg=TEMA["text_muted"],
                     font=FUENTES["small"]).grid(row=0, column=col, sticky="w", padx=(0, 12))

        previas = DB.validaciones_indice_de_pasada(ficha.nombre, ficha.campana,
                                                   ctx.get("fecha", ""))
        self.combos = {}
        fila = 1
        for idx in INDICES_ORDEN:
            lec = (ctx.get("lecturas") or {}).get(idx) or {}
            if lec.get("valor") is None:
                continue                      # ese dia no se midio: no hay nada que validar
            tk.Label(tabla, text=idx, bg=TEMA["surface"], fg=TEMA["text"],
                     font=FUENTES["small"]).grid(row=fila, column=0, sticky="w", pady=1)
            tk.Label(tabla, text=f"{lec['valor']:.3f}", bg=TEMA["surface"], fg=TEMA["text"],
                     font=FUENTES["small"]).grid(row=fila, column=1, sticky="w", padx=(0, 12))
            visto = lec.get("sistema", _CALIB.SIN_CRITERIO)
            tk.Label(tabla, text=visto, bg=TEMA["surface"],
                     fg=TEMA["danger_fg"] if visto == "bajo" else TEMA["text_sec"],
                     font=FUENTES["small"]).grid(row=fila, column=2, sticky="w", padx=(0, 12))
            cb = ttk.Combobox(tabla, state="readonly", width=10, values=_CALIB.ESTADOS)
            # preseleccionado con lo que ya dijiste antes; si no, con lo que ve el
            # sistema; y si el sistema no tiene criterio en esta fase, "normal"
            anterior = (previas.get(idx) or {}).get("dijo_usuario")
            cb.set(anterior or (visto if visto in _CALIB.ESTADOS else "normal"))
            cb.grid(row=fila, column=3, sticky="w", pady=1)
            self.combos[idx] = cb
            if not lec.get("calibrable"):
                tk.Label(tabla, text="(se anota, hoy no mueve umbral)", bg=TEMA["surface"],
                         fg=TEMA["text_muted"], font=FUENTES["small"]).grid(
                             row=fila, column=4, sticky="w", padx=(8, 0))
            fila += 1

        tk.Label(self, text="¿A que debe aplicarse lo que digas?", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).pack(anchor="w", padx=16, pady=(10, 0))
        self.ambitos = _CALIB.ambitos_disponibles(ficha.nombre)
        self.cb_ambito = ttk.Combobox(self, state="readonly", width=34,
                                      values=[t for _, t in self.ambitos])
        self.cb_ambito.current(0)
        self.cb_ambito.pack(anchor="w", padx=16, pady=(2, 0))
        if len(self.ambitos) < 4:
            tk.Label(self, text="Esta parcela no tiene municipio ni provincia guardados: "
                                "capturala por SIGPAC o editala para poder corregir a ese nivel.",
                     bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"],
                     wraplength=470, justify="left").pack(anchor="w", padx=16, pady=(4, 0))

        botones = tk.Frame(self, bg=TEMA["surface"])
        botones.pack(fill="x", padx=16, pady=14)
        ttk.Button(botones, text="  Guardar  ", style="Accent.TButton",
                   command=self._guardar).pack(side="right")
        ttk.Button(botones, text="  Cancelar  ", style="Ghost.TButton",
                   command=self.destroy).pack(side="right", padx=(0, 8))

    def _guardar(self):
        ambito = self.ambitos[self.cb_ambito.current()][0]
        respuestas = {idx: cb.get() for idx, cb in self.combos.items()}
        # los umbrales llevan el regimen y la densidad: sin eso, lo validado en un
        # olivar de secano contaminaria a un seto de regadio
        n = _CALIB.registrar(self.ficha.nombre, self.ficha.campana, self.ctx.get("fecha"),
                             self.ctx.get("especie"), self.ctx.get("fase"),
                             self.ctx.get("lecturas"), respuestas, ambito,
                             umbrales=self.ctx.get("umbrales"))
        self.destroy()
        self.ficha.refrescar()          # el umbral puede haber cambiado ya
        messagebox.showinfo("Validacion",
                            f"Anotados {n} indice(s) para «{dict(self.ambitos)[ambito]}».\n\n"
                            f"Hacen falta {_CALIB.MIN_OBSERVACIONES} validaciones coherentes "
                            f"de la misma especie y fase, y de al menos "
                            f"{_CALIB.MIN_FECHAS} pasadas de dias distintos, para que un "
                            f"umbral se mueva. Varias validaciones del mismo dia cuentan "
                            f"como una sola observacion.",
                            parent=self.ficha.master)

class DialogoSincronizarCampanas(tk.Toplevel):
    """Descarga Copernicus para una o varias campanas (anos anteriores) de la parcela."""
    def __init__(self, master, panel, nombre, campana_ficha):
        super().__init__(master)
        self.panel, self.nombre = panel, nombre
        self.title("Sincronizar campanas anteriores")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(60, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))
        self.grab_set()

        # El limite lo pone el satelite, no el programa: Sentinel-2 L2A empieza en
        # la campana 2017-2018 (ver campanas.PRIMERA_CAMPANA_S2). Las campanas mas
        # antiguas que eso, si las hay guardadas, salen listadas pero sin casilla:
        # no se pueden descargar, solo consultarlas desde la ficha.
        camps = campanas_de_parcela(DB.campanas_de(nombre))

        tk.Label(self, text=f"Parcela: {nombre.replace('_', ' ')}", bg=TEMA["surface"],
                 fg=TEMA["text"], font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(self, text=f"Copernicus llega hasta la campana {PRIMERA_CAMPANA_S2} "
                            f"(cobertura completa desde {PRIMERA_CAMPANA_S2_GLOBAL}).\n"
                            "Marca las que quieras descargar (incremental, no repite). Si una campana\n"
                            "no tiene datos de satelite, se avisara al sincronizar. Para VER una,\n"
                            "seleccionala en el desplegable de campana de la ficha.",
                 bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"],
                 justify="left").pack(anchor="w", padx=16)

        cont, interior = marco_scroll(self, bg=TEMA["surface"], rueda_global=True)
        cont.configure(height=180, width=320)
        cont.pack(fill="x", padx=16, pady=8)
        cont.pack_propagate(False)
        self.vars = {}
        for c in camps:
            etiqueta = etiqueta_campana(c)
            if not c["sincronizable"]:
                # guardada pero fuera del alcance del satelite: se ensena para que
                # se sepa que esta ahi, sin casilla porque no hay nada que pedir
                tk.Label(interior, text="      " + etiqueta, bg=TEMA["surface"],
                         fg=TEMA["text_muted"], font=FUENTES["small"]).pack(anchor="w", pady=1)
                continue
            v = tk.BooleanVar(value=(c["campana"] == campana_ficha))
            self.vars[c["campana"]] = v
            ttk.Checkbutton(interior, text=etiqueta, variable=v).pack(anchor="w", pady=1)

        self.lbl_prog = tk.Label(self, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                 font=FUENTES["small"])
        self.lbl_prog.pack(anchor="w", padx=16)
        bar = tk.Frame(self, bg=TEMA["surface"])
        bar.pack(fill="x", padx=16, pady=14)
        ttk.Button(bar, text="Cerrar", style="Ghost.TButton", command=self.destroy).pack(side="right")
        self.btn = ttk.Button(bar, text="Sincronizar seleccionadas", style="Accent.TButton",
                              command=self._sync)
        self.btn.pack(side="right", padx=(0, 8))

    def _sync(self):
        if not _EE:
            return messagebox.showwarning("GEE", "earthengine-api no disponible.", parent=self)
        sel = [c for c, v in self.vars.items() if v.get()]
        if not sel:
            return messagebox.showinfo("Sincronizar", "No has marcado ninguna campana.", parent=self)
        self.btn.config(state="disabled")
        threading.Thread(target=self._worker, args=(sel,), daemon=True).start()

    def _worker(self, sel):
        total, lineas = 0, []
        orden = sorted(sel)
        for i, camp in enumerate(orden, 1):
            self.after(0, lambda c=camp, k=i: self._prog(f"Sincronizando {c}  ({k}/{len(orden)})…"))
            tenia = DB.ultima_fecha(self.nombre, camp) is not None
            try:
                n, msg = sincronizar_parcela(self.nombre, camp, silencioso=True)
            except Exception as e:
                n, msg = 0, f"error: {e}"
            total += n
            if n == 0 and not tenia and DB.ultima_fecha(self.nombre, camp) is None:
                lineas.append(f"{camp}: NO hay datos de Copernicus para esa campana")
            else:
                lineas.append(f"{camp}: {msg}")
        if ULTIMO_SYNC.get("estado") != "fallo":
            sincronizacion.marca_guardar()

        def fin():
            if not self.btn.winfo_exists():
                return
            self._prog(f"Hecho. {total} pasada(s) nueva(s) en total.")
            self.btn.config(state="normal")
            self.panel.cb_campana["values"] = self.panel._campanas()
            self.panel._actualizar_estado_sync()
            self.panel._refrescar()
            messagebox.showinfo("Sincronizacion de campanas", "\n".join(lineas), parent=self)
        self.after(0, fin)

    def _prog(self, texto):
        if self.lbl_prog.winfo_exists():
            self.lbl_prog.config(text=texto)

class DialogoEfectoProducto(tk.Toplevel):
    """Muestra el efecto de un producto y deja ELEGIR el dia del informe (la pasada
    posterior a la aplicacion contra la que se mide). Se puede guardar como dia
    del informe de esa intervencion."""
    def __init__(self, master, ficha, evento, serie):
        super().__init__(master)
        self.ficha, self.evento = ficha, evento
        self.serie = sorted(serie or [], key=lambda r: r.get("fecha", ""))
        self.title("Efecto del producto")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(60, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))
        self.grab_set()

        f_ap = evento.get("fecha")
        tk.Label(self, text=f"{evento.get('producto', '')}   ·   {evento.get('objetivo', '')}",
                 bg=TEMA["surface"], fg=TEMA["text"], font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(self, text=f"Aplicado: {f_ap}", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", padx=16)

        # pasadas validas posteriores a la aplicacion -> opciones de dia del informe
        self.post = [r for r in self.serie
                     if r.get("fecha") and r["fecha"] > f_ap and r.get("ndvi") is not None]
        self.lbl2fecha = {self._etq(r): r["fecha"] for r in self.post}

        fila = tk.Frame(self, bg=TEMA["surface"])
        fila.pack(fill="x", padx=16, pady=(10, 2))
        tk.Label(fila, text="Dia del informe", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(side="left")
        self.cb = ttk.Combobox(fila, state="readonly", width=22,
                               values=["(automatico)"] + list(self.lbl2fecha.keys()))
        self.cb.pack(side="left", padx=6)
        self.cb.bind("<<ComboboxSelected>>", lambda e: self._actualizar())
        # seleccion inicial: el dia guardado (el mas cercano), o automatico
        sel = "(automatico)"
        obj = evento.get("fecha_informe")
        if obj and self.post:
            cercana = min(self.post, key=lambda r: abs(self._dias(obj, r["fecha"])))
            sel = self._etq(cercana)
        self.cb.set(sel)

        self.txt = tk.Text(self, width=52, height=9, bd=0, relief="flat", bg=TEMA["nota_bg"],
                           fg=TEMA["text"], font=FUENTES["body"], padx=12, pady=10, highlightthickness=0)
        self.txt.pack(fill="both", expand=True, padx=16, pady=(8, 0))

        bar = tk.Frame(self, bg=TEMA["surface"])
        bar.pack(fill="x", padx=16, pady=12)
        ttk.Button(bar, text="Cerrar", style="Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Guardar como dia del informe", style="Accent.TButton",
                   command=self._guardar).pack(side="right", padx=(0, 8))
        self._actualizar()

    @staticmethod
    def _dias(a, b):
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days

    def _etq(self, r):
        return f"{r['fecha']}   (+{self._dias(self.evento.get('fecha'), r['fecha'])} d)"

    def _fecha_sel(self):
        return self.lbl2fecha.get(self.cb.get())     # None si es "(automatico)"

    def _actualizar(self):
        # se calcula sobre una copia SIN fecha_informe: asi "(automatico)" es de
        # verdad automatico aunque la intervencion ya tenga un dia guardado.
        ev = {k: v for k, v in self.evento.items() if k != "fecha_informe"}
        ef = REG.efecto_producto(self.serie, ev, fecha_objetivo=self._fecha_sel())
        self.txt.config(state="normal")
        self.txt.delete("1.0", tk.END)
        if not ef or not ef.get("disponible"):
            self.txt.insert(tk.END, ef["nota"] if ef else "Sin datos suficientes.")
        else:
            msg = (f"Dia del informe: {ef['dia_informe']}  ({ef['dias_despues']} dias despues)\n\n"
                   f"NDVI: {ef['ndvi_antes']} -> {ef['ndvi_despues']}   ({ef['d_ndvi']:+.3f})\n")
            if ef.get("d_ndmi") is not None:
                msg += f"NDMI: {ef['ndmi_antes']} -> {ef['ndmi_despues']}   ({ef['d_ndmi']:+.3f})\n"
            if ef.get("d_lai") is not None:
                msg += f"LAI:  {ef['lai_antes']} -> {ef['lai_despues']}   ({ef['d_lai']:+.2f})"
                msg += "   (clave en herbicidas)\n" if ef.get("es_herbicida") else "\n"
            if ef.get("es_herbicida") and ef.get("d_std") is not None:
                msg += f"Dispersion NDVI: {ef['d_std']:+.3f}   (baja = parcela mas homogenea)\n"
            msg += f"\nLectura: {ef['verdicto']}.\n\n{ef['aviso']}"
            self.txt.insert(tk.END, msg)
        self.txt.config(state="disabled")

    def _guardar(self):
        fecha = self._fecha_sel()
        if fecha:
            self.evento["fecha_informe"] = fecha
        else:
            self.evento.pop("fecha_informe", None)   # volver al automatico
        REG.registrar_evento(self.ficha.nombre, self.ficha.campana, self.evento)
        self.ficha._refrescar_eventos()
        messagebox.showinfo("Dia del informe",
                            f"Guardado: el efecto se medira en {fecha}." if fecha else
                            "Guardado: dia del informe automatico.", parent=self)
        self.destroy()


class DialogoBorrarCampana(tk.Toplevel):
    """Borra TODO lo de una campana de una parcela, con DOBLE confirmacion.

    El borrado es irreversible, asi que no basta un «¿seguro?» que se pulsa sin
    leer: hay que (1) marcar la casilla de que se entiende, y solo entonces (2) se
    habilita el boton de borrar. Dos actos deliberados en vez de uno reflejo.
    """
    def __init__(self, master, nombre, campana, al_terminar=None):
        super().__init__(master)
        self.nombre, self.campana, self.al_terminar = nombre, campana, al_terminar
        self.title("Borrar campana")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(60, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))
        self.grab_set()

        n_pas = len(DB.pasadas(nombre, campana))
        n_ev = len(DB.eventos_de(nombre, campana)) if hasattr(DB, "eventos_de") else 0

        tk.Label(self, text=f"Borrar la campana {campana}", bg=TEMA["surface"],
                 fg=TEMA["danger_fg"], font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(self, text=f"Parcela: {nombre.replace('_', ' ')}", bg=TEMA["surface"],
                 fg=TEMA["text_sec"], font=FUENTES["small"]).pack(anchor="w", padx=16)
        det = (f"Se borrara TODO lo de esta campana:\n"
               f"   • {n_pas} pasada(s) de satelite y sus mapas\n"
               f"   • {n_ev} evento(s) del cuaderno de campo\n"
               f"   • el cultivo asignado y las validaciones de este ano\n\n"
               f"La parcela y sus OTRAS campanas NO se tocan.\n"
               f"Esto es IRREVERSIBLE: no hay deshacer.")
        tk.Label(self, text=det, bg=TEMA["surface"], fg=TEMA["text"], font=FUENTES["body"],
                 justify="left").pack(anchor="w", padx=16, pady=(10, 8))

        self.var_ok = tk.IntVar(value=0)
        tk.Checkbutton(self, text="Sí, entiendo que se borrara para siempre",
                       variable=self.var_ok, command=self._toggle,
                       bg=TEMA["surface"], fg=TEMA["text"], font=FUENTES["body"],
                       activebackground=TEMA["surface"], selectcolor=TEMA["surface"],
                       bd=0).pack(anchor="w", padx=16)

        bar = tk.Frame(self, bg=TEMA["surface"])
        bar.pack(fill="x", padx=16, pady=14)
        ttk.Button(bar, text="Cancelar", style="Ghost.TButton",
                   command=self.destroy).pack(side="right")
        self.btn = ttk.Button(bar, text="Borrar definitivamente", style="Accent.TButton",
                              command=self._borrar, state="disabled")
        self.btn.pack(side="right", padx=(0, 8))

    def _toggle(self):
        # el boton solo se habilita con la casilla marcada: la segunda validacion
        self.btn.config(state="normal" if self.var_ok.get() else "disabled")

    def _borrar(self):
        if not self.var_ok.get():
            return
        n = DB.eliminar_campana(self.nombre, self.campana)
        self.destroy()
        messagebox.showinfo("Campana borrada",
                            f"Borrada la campana {self.campana} de "
                            f"{self.nombre.replace('_', ' ')} ({n} pasada(s)).",
                            parent=self.master)
        if callable(self.al_terminar):
            self.al_terminar()


def _num(txt, campo, minimo=None, maximo=None):
    """Convierte un campo de texto a float o lanza ValueError con el NOMBRE del
    campo (para el aviso). Vacio -> None (el dato es opcional)."""
    t = (txt or "").strip().replace(",", ".")
    if not t:
        return None
    try:
        v = float(t)
    except ValueError:
        raise ValueError(campo)
    if (minimo is not None and v < minimo) or (maximo is not None and v > maximo):
        raise ValueError(campo)
    return v


class DialogoObservacionCampo(tk.Toplevel):
    """Anota una OBSERVACION DE CAMPO: la verdad-terreno con la que se mide el
    acierto del sistema (modulo opcional `validacion`).

    Recoge lo que se vio de verdad -a pie de finca, con una sonda de humedad o con
    un vuelo de dron multiespectral- para esta parcela y una fecha. Todos los
    campos son opcionales salvo la fecha: se anota lo que se haya medido. El dato
    se guarda como VERDAD y no toca el diagnostico del sistema; solo sirve para
    puntuarlo despues (evita la circularidad de corregir con lo mismo que mides).
    """

    FUENTES_OBS = ["campo", "sonda", "dron"]

    def __init__(self, master, ficha, al_terminar=None):
        super().__init__(master)
        self.ficha = ficha
        self.al_terminar = al_terminar
        self.title("Observacion de campo")
        self.configure(bg=TEMA["surface"])
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.lift()
        self.after(60, self.focus_force)
        self.after(0, lambda: centrar_sobre(self, self.master))
        self.grab_set()

        cab = f"{ficha.nombre.replace('_', ' ')}  ·  campana {ficha.campana}"
        tk.Label(self, text=cab, bg=TEMA["surface"], fg=TEMA["text"],
                 font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 0))
        tk.Label(self, text="Anota lo que observaste de verdad. Se guarda como dato medido "
                            "para medir el acierto del sistema; no cambia el diagnostico.",
                 bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"],
                 wraplength=440, justify="left").pack(anchor="w", padx=16, pady=(2, 8))

        form = tk.Frame(self, bg=TEMA["surface"])
        form.pack(fill="x", padx=16)

        def _fila(r, texto):
            tk.Label(form, text=texto, bg=TEMA["surface"], fg=TEMA["text_sec"],
                     font=FUENTES["small"]).grid(row=r, column=0, sticky="w", pady=(6, 0))

        _fila(0, "Fecha de la observacion")
        self.fecha = CampoFecha(form, iso=datetime.now().strftime("%Y-%m-%d"))
        self.fecha.grid(row=0, column=1, sticky="w", pady=(6, 0))
        _fila(1, "Origen del dato")
        self.cb_fuente = ttk.Combobox(form, state="readonly", width=12, values=self.FUENTES_OBS)
        self.cb_fuente.set("campo")
        self.cb_fuente.grid(row=1, column=1, sticky="w", pady=(6, 0))

        _fila(2, "Fase fenologica observada")
        ctx = {"cultivo": self._cultivo_str()}
        self.cb_fase = ttk.Combobox(form, state="normal", width=26, values=_fases_para(ctx))
        self.cb_fase.set("")
        self.cb_fase.grid(row=2, column=1, sticky="w", pady=(6, 0))

        _fila(3, "Rendimiento medido (kg/ha)")
        self.e_rend = ttk.Entry(form, width=12)
        self.e_rend.grid(row=3, column=1, sticky="w", pady=(6, 0))

        _fila(4, "Humedad de sonda (%)")
        self.e_hum = ttk.Entry(form, width=12)
        self.e_hum.grid(row=4, column=1, sticky="w", pady=(6, 0))

        _fila(5, "Dron: indice y valor")
        drf = tk.Frame(form, bg=TEMA["surface"])
        drf.grid(row=5, column=1, sticky="w", pady=(6, 0))
        self.cb_idx = ttk.Combobox(drf, state="readonly", width=7, values=["", "NDVI", "NDRE"])
        self.cb_idx.set("")
        self.cb_idx.pack(side="left")
        self.e_dron = ttk.Entry(drf, width=8)
        self.e_dron.pack(side="left", padx=(6, 0))

        _fila(6, "Nota (opcional)")
        self.txt = tk.Text(form, width=34, height=3, bd=1, relief="solid",
                           font=FUENTES["body"], highlightthickness=0)
        self.txt.grid(row=6, column=1, sticky="w", pady=(6, 0))

        bar = tk.Frame(self, bg=TEMA["surface"])
        bar.pack(fill="x", padx=16, pady=14)
        ttk.Button(bar, text="Cancelar", style="Ghost.TButton",
                   command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Guardar observacion", style="Accent.TButton",
                   command=self._guardar).pack(side="right", padx=(0, 8))

    def _cultivo_str(self):
        """"TIPO/SUBTIPO/ESPECIE" del cultivo de la campana, para las fases."""
        cul = ((DB.ficha(self.ficha.nombre) or {}).get("cultivos_por_campana", {})
               or {}).get(self.ficha.campana, {}) or {}
        partes = [cul.get("tipo", ""), cul.get("subtipo", ""), cul.get("especie", "")]
        return "/".join(partes)

    def _guardar(self):
        fecha = self.fecha.get_iso()
        if not fecha:
            return messagebox.showwarning("Fecha", "Elige la fecha de la observacion (dd-mm-aaaa).",
                                          parent=self)
        try:
            rend = _num(self.e_rend.get(), "rendimiento (kg/ha)", minimo=0)
            hum = _num(self.e_hum.get(), "humedad de sonda (%)", minimo=0, maximo=100)
            dron = _num(self.e_dron.get(), "valor del dron", minimo=-1, maximo=1)
        except ValueError as e:
            return messagebox.showwarning("Revisa el dato", f"El campo «{e}» debe ser un numero "
                                          "valido (o dejarlo vacio).", parent=self)
        fase = self.cb_fase.get().strip()
        idx = self.cb_idx.get().strip()
        nota = self.txt.get("1.0", tk.END).strip()

        obs = {"fecha": fecha, "fuente": self.cb_fuente.get()}
        if fase:
            obs["fase_obs"] = fase
        if rend is not None:
            obs["rendimiento_kg_ha"] = rend
        if hum is not None:
            obs["humedad_suelo_pct"] = hum
        if dron is not None and idx:
            obs["indice_dron"] = idx
            obs["valor_dron"] = dron
        if nota:
            obs["nota"] = nota
        # que traiga ALGO ademas de la fecha y la fuente: una fila vacia no mide nada
        if len(obs) <= 2:
            return messagebox.showwarning("Sin datos", "Anota al menos un dato: fase, rendimiento, "
                                          "humedad o lectura de dron.", parent=self)
        DB.registrar_observacion(self.ficha.nombre, self.ficha.campana, obs)
        self.destroy()
        if callable(self.al_terminar):
            self.al_terminar()
