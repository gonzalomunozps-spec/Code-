# -*- coding: utf-8 -*-
"""
ui_credenciales.py
==================

La pestana de Credenciales: Google Earth Engine, la clave de OpenAI y el tema
claro/oscuro. Prueba cada conexion en segundo plano y ensena el resultado con una
insignia de color.
"""

import threading

import tkinter as tk
from tkinter import ttk, messagebox

from ui_tema import TEMA, FUENTES, esc, tarjeta
from tkinter import filedialog

import credenciales as CRED
from ui_tema import MODO
from sincronizacion import ULTIMO_SYNC
from bitacora import log


# PANEL DE CREDENCIALES / CONEXIONES
# =====================================================================
# Insignia de estado por servicio: color de fondo/texto segun el resultado.
_EST_COLOR = {"ok": ("ok_fg", "ok_bg"), "aviso": ("warn_fg", "warn_bg"),
              "fallo": ("danger_fg", "danger_bg"), "prueba": ("text_muted", "muted_bg")}
_EST_TEXTO = {"ok": "CONECTADO", "aviso": "SIN CONFIGURAR", "fallo": "FALLA",
              "prueba": "Probando…"}


class PanelCredenciales(ttk.Frame):
    """Pestana para ver/cambiar las credenciales (Google Earth Engine y OpenAI)
    y probar la conexion de cada una, mostrando en rojo el error si alguna falla."""

    def __init__(self, master, al_cambiar=None, *a, **k):
        super().__init__(master, *a, **k)
        self.al_cambiar = al_cambiar          # callback tras guardar (refrescar panel)
        self.cfg = CRED.cargar()
        self.badges, self.msgs = {}, {}
        self._build()
        self.after(400, self.probar_todo)     # estado inicial en segundo plano

    # ---- construccion ----
    def _build(self):
        cab = tk.Frame(self, bg=TEMA["header_bg"])
        cab.pack(fill="x")
        tk.Label(cab, text="Credenciales y conexiones", bg=TEMA["header_bg"], fg=TEMA["text_inv"],
                 font=FUENTES["h1"]).pack(anchor="w", padx=18, pady=(12, 0))
        tk.Label(cab, text="Configura los servicios externos y comprueba que responden",
                 bg=TEMA["header_bg"], fg=TEMA["header_sub"],
                 font=FUENTES["small"]).pack(anchor="w", padx=18, pady=(0, 12))

        cuerpo = tk.Frame(self, bg=TEMA["page"])
        cuerpo.pack(fill="both", expand=True, padx=18, pady=16)

        # --- Google Earth Engine ---
        g = self._tarjeta(cuerpo, "gee", "Google Earth Engine",
                          "Necesario para descargar imagenes Sentinel-2 y sincronizar las parcelas.")
        tk.Label(g, text="Inicia sesion con tu cuenta de Google: se abre el navegador y escribes tu "
                         "correo y contrasena EN LA PAGINA DE GOOGLE (no aqui). No vemos ni guardamos "
                         "tu contrasena; Google nos da solo un permiso de acceso.",
                 bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"],
                 wraplength=760, justify="left").pack(anchor="w", pady=(2, 8))
        login = tk.Frame(g, bg=TEMA["surface"])
        login.pack(fill="x")
        ttk.Button(login, text="  Iniciar sesion con Google  ", style="Accent.TButton",
                   command=self._login_google).pack(side="left")
        ttk.Button(login, text="Probar conexion", command=lambda: self._probar("gee")).pack(side="left", padx=(8, 0))

        # avanzado: cuenta de servicio (para servidores sin navegador)
        tk.Label(g, text="Avanzado · cuenta de servicio (opcional, solo para servidores sin navegador)",
                 bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"]).pack(anchor="w", pady=(12, 4))
        self.e_gee_project = self._campo(g, "Project ID de Google Cloud", self.cfg.get("gee_project", ""))
        self.e_gee_sa = self._campo(g, "Cuenta de servicio · email", self.cfg.get("gee_service_account", ""))
        tk.Label(g, text="Fichero de clave (.json)", bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", pady=(6, 2))
        fila = tk.Frame(g, bg=TEMA["surface"])
        fila.pack(fill="x")
        self.e_gee_key = ttk.Entry(fila)
        if self.cfg.get("gee_key_file"):
            self.e_gee_key.insert(0, self.cfg["gee_key_file"])
        self.e_gee_key.pack(side="left", fill="x", expand=True)
        ttk.Button(fila, text="Examinar", command=self._elegir_key).pack(side="left", padx=(6, 0))

        # --- OpenAI ---
        o = self._tarjeta(cuerpo, "openai", "OpenAI · ChatGPT",
                          "Opcional: genera la interpretacion con IA. Sin clave se usa el texto por reglas.")
        tk.Label(o, text="OpenAI no usa correo/contrasena para programar: usa una API key. Tu correo y "
                         "contrasena solo sirven para entrar en su web y crear la clave; pegala aqui.",
                 bg=TEMA["surface"], fg=TEMA["text_sec"], font=FUENTES["small"],
                 wraplength=760, justify="left").pack(anchor="w", pady=(2, 8))
        self.e_openai = self._campo(o, "API key (sk-...)", self.cfg.get("openai_api_key", ""),
                                    secreto=True)
        acc2 = tk.Frame(o, bg=TEMA["surface"])
        acc2.pack(fill="x", pady=(10, 0))
        ttk.Button(acc2, text="Probar conexion", command=lambda: self._probar("openai")).pack(side="left")
        ttk.Button(acc2, text="Conseguir clave (web)", command=self._abrir_openai).pack(side="left", padx=(8, 0))
        self.var_ver = tk.IntVar(value=0)
        tk.Checkbutton(acc2, text="Mostrar clave", variable=self.var_ver, command=self._toggle_ver,
                       bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"],
                       activebackground=TEMA["surface"], selectcolor=TEMA["surface"], bd=0).pack(side="left", padx=10)
        # recordar o no la clave en disco
        self.var_recordar = tk.IntVar(value=1 if self.cfg.get("openai_api_key") else 0)
        tk.Checkbutton(o, text="Recordar la clave en este equipo (ofuscada; si no, usa la variable OPENAI_API_KEY)",
                       variable=self.var_recordar, bg=TEMA["surface"], fg=TEMA["text_muted"],
                       font=FUENTES["small"], activebackground=TEMA["surface"],
                       selectcolor=TEMA["surface"], bd=0).pack(anchor="w", pady=(8, 0))

        # --- Aspecto ---
        asp = tarjeta(cuerpo)
        asp.pack(fill="x", pady=(0, 14))
        tk.Label(asp, text="Aspecto", bg=TEMA["surface"], fg=TEMA["text"],
                 font=FUENTES["h2"]).pack(anchor="w", padx=16, pady=(14, 0))
        tk.Label(asp, text="El tema se aplica al volver a abrir el programa: Tk no puede repintar "
                           "en caliente las ventanas ya creadas.",
                 bg=TEMA["surface"], fg=TEMA["text_muted"], font=FUENTES["small"],
                 wraplength=esc(760), justify="left").pack(anchor="w", padx=16, pady=(2, 8))
        fila_tema = tk.Frame(asp, bg=TEMA["surface"])
        fila_tema.pack(anchor="w", padx=16, pady=(0, 14))
        self.var_tema = tk.StringVar(value=MODO["m"])
        for valor, etiqueta in (("claro", "Claro"), ("oscuro", "Oscuro")):
            ttk.Radiobutton(fila_tema, text=etiqueta, value=valor,
                            variable=self.var_tema).pack(side="left", padx=(0, 16))

        barra = tk.Frame(cuerpo, bg=TEMA["page"])
        barra.pack(fill="x", pady=(4, 0))
        tk.Label(barra, text="La clave de OpenAI se guarda ofuscada (base64), no en texto plano. "
                             "La variable de entorno OPENAI_API_KEY tiene prioridad.",
                 bg=TEMA["page"], fg=TEMA["text_muted"], font=FUENTES["small"]).pack(side="left")
        ttk.Button(barra, text="  Guardar y probar todo  ", style="Accent.TButton",
                   command=self.guardar).pack(side="right")

    def _tarjeta(self, parent, clave, titulo, subtitulo):
        card = tarjeta(parent)
        card.pack(fill="x", pady=(0, 14))
        top = tk.Frame(card, bg=TEMA["surface"])
        top.pack(fill="x", padx=16, pady=(14, 4))
        izq = tk.Frame(top, bg=TEMA["surface"])
        izq.pack(side="left")
        tk.Label(izq, text=titulo, bg=TEMA["surface"], fg=TEMA["text"], font=FUENTES["h2"]).pack(anchor="w")
        tk.Label(izq, text=subtitulo, bg=TEMA["surface"], fg=TEMA["text_muted"],
                 font=FUENTES["small"]).pack(anchor="w")
        self.badges[clave] = tk.Label(top, text="Probando…", font=FUENTES["small"], padx=10, pady=3, bd=0)
        self.badges[clave].pack(side="right")
        cuerpo = tk.Frame(card, bg=TEMA["surface"])
        cuerpo.pack(fill="x", padx=16, pady=(4, 8))
        self.msgs[clave] = tk.Label(card, text="", bg=TEMA["surface"], fg=TEMA["text_sec"],
                                    font=FUENTES["small"], wraplength=780, justify="left", anchor="w")
        self.msgs[clave].pack(fill="x", padx=16, pady=(0, 12))
        return cuerpo

    def _campo(self, parent, etiqueta, valor="", secreto=False):
        tk.Label(parent, text=etiqueta, bg=TEMA["surface"], fg=TEMA["text_sec"],
                 font=FUENTES["small"]).pack(anchor="w", pady=(6, 2))
        e = ttk.Entry(parent, show="•" if secreto else "")
        if valor:
            e.insert(0, valor)
        e.pack(fill="x")
        return e

    def _set_badge(self, clave, estado, msg):
        fg, bg = _EST_COLOR.get(estado, _EST_COLOR["prueba"])
        self.badges[clave].config(text=_EST_TEXTO.get(estado, "?"), fg=TEMA[fg], bg=TEMA[bg])
        self.msgs[clave].config(text=msg, fg=TEMA["danger_fg"] if estado == "fallo" else TEMA["text_sec"])

    def _toggle_ver(self):
        self.e_openai.config(show="" if self.var_ver.get() else "•")

    def _login_google(self):
        """Abre el flujo OAuth de Google (el usuario mete correo/contrasena en la
        pagina de Google) y verifica la conexion, en segundo plano."""
        self._set_badge("gee", "prueba", "Abriendo el navegador para iniciar sesion con Google…")
        project = self.e_gee_project.get().strip()

        def run():
            est, msg = CRED.autenticar_google(project)
            self.after(0, lambda: self._set_badge("gee", est, msg))
        threading.Thread(target=run, daemon=True).start()

    def _abrir_openai(self):
        """Abre la web de OpenAI donde el usuario crea su API key."""
        import webbrowser
        try:
            webbrowser.open(CRED.URL_OPENAI_KEYS)
        except Exception:
            log.warning("no se pudo abrir el navegador en %s", CRED.URL_OPENAI_KEYS, exc_info=True)

    def _elegir_key(self):
        ruta = filedialog.askopenfilename(title="Clave de cuenta de servicio",
                                          filetypes=[("JSON", "*.json"), ("Todos", "*.*")])
        if ruta:
            self.e_gee_key.delete(0, tk.END)
            self.e_gee_key.insert(0, ruta)

    def _cfg_actual(self):
        return {"gee_project": self.e_gee_project.get().strip(),
                "gee_service_account": self.e_gee_sa.get().strip(),
                "gee_key_file": self.e_gee_key.get().strip(),
                "openai_api_key": self.e_openai.get().strip(),
                "tema": self.var_tema.get()}

    def _probar(self, servicio):
        self._set_badge(servicio, "prueba", "Probando conexion…")
        cfg = self._cfg_actual()
        CRED.aplicar_entorno(cfg)

        def run():
            if servicio == "gee":
                est, msg = CRED.probar_gee(cfg["gee_project"], cfg["gee_key_file"],
                                           cfg["gee_service_account"])
                if ULTIMO_SYNC.get("estado") == "fallo" and est == "ok":
                    est, msg = "aviso", msg + f"  ·  Aviso: el ultimo sync automatico fallo ({ULTIMO_SYNC['msg']})."
            else:
                est, msg = CRED.probar_openai(cfg["openai_api_key"])
            self.after(0, lambda: self._set_badge(servicio, est, msg))
        threading.Thread(target=run, daemon=True).start()

    def probar_todo(self):
        for s in ("gee", "openai"):
            self._probar(s)

    def guardar(self):
        cfg = self._cfg_actual()
        try:
            CRED.guardar(cfg, recordar_openai=bool(self.var_recordar.get()))
        except Exception as e:
            return messagebox.showerror("Credenciales", f"No se pudieron guardar: {e}")
        self.cfg = cfg
        CRED.aplicar_entorno(cfg, forzar=True)   # aplica la clave recien tecleada
        self.probar_todo()
        if callable(self.al_cambiar):
            try:
                self.al_cambiar()
            except Exception:
                # si falla, el resto de la app no se entera del cambio de credenciales
                log.warning("fallo el aviso de cambio de credenciales", exc_info=True)
        messagebox.showinfo("Credenciales", "Credenciales guardadas. Probando conexiones…")
