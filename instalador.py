# -*- coding: utf-8 -*-
"""
instalador.py
=============

Lógica de INSTALACIÓN / DESINSTALACIÓN del programa, multiplataforma y SIN depender
del resto de la aplicación (se puede ejecutar aunque falten las dependencias).

Aquí vive el "cómo"; los guiones `instalar.py` y `desinstalar.py` son la cáscara
que lo llama. El programa **se puede usar sin instalar** (ver `iniciar.py` o
`python panel_gestion_parcelas.py`): la instalación solo añade un entorno aislado
con las dependencias y un ACCESO DIRECTO; no es obligatoria.

Qué hace la instalación:
  1. (Opcional) crea un entorno virtual `.venv` en la carpeta del programa, que
     hereda el Python del sistema (para tener tkinter) e instala las dependencias.
  2. Crea un acceso directo en el ESCRITORIO (y en el menú, en Linux) que arranca
     el programa con ese Python.
  3. Apunta lo creado en `.instalacion.json` para poder deshacerlo.

Qué NO hace: NUNCA toca los DATOS del usuario (parcelas.db vive en la carpeta de
datos del sistema, ver `rutas.py`). Desinstalar deja los datos intactos.
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

NOMBRE_APP = "Gestor de Parcelas"
NOMBRE_CORTO = "gestor-parcelas"
PROYECTO = Path(__file__).resolve().parent
ENTRADA = PROYECTO / "panel_gestion_parcelas.py"
REGISTRO = PROYECTO / ".instalacion.json"


# =====================================================================
# Detección de plataforma y rutas (puro: `so` inyectable para probar)
# =====================================================================
def sistema(so=None):
    """'windows' / 'darwin' / 'linux'. Se puede forzar `so` en las pruebas."""
    s = (so or platform.system()).lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "darwin"
    return "linux"


def escritorio(home=None):
    """Carpeta del escritorio del usuario (acepta 'Desktop' y 'Escritorio')."""
    h = Path(home) if home else Path.home()
    for nombre in ("Desktop", "Escritorio"):
        if (h / nombre).is_dir():
            return h / nombre
    return h / "Desktop"        # no existe todavía: se creará al poner el acceso


def icono(so=None):
    """Ruta al icono adecuado: .ico en Windows, .png en el resto."""
    return str(PROYECTO / ("icono.ico" if sistema(so) == "windows" else "icono.png"))


def python_lanzador(venv_dir=None, so=None, actual=None):
    """El Python con el que se arranca la app: el del venv si existe, si no el actual.

    En Windows se prefiere `pythonw.exe` (arranca sin ventana de consola negra)."""
    so = sistema(so)
    if venv_dir:
        vd = Path(venv_dir)
        cand = (vd / "Scripts" / "pythonw.exe") if so == "windows" else (vd / "bin" / "python")
        if cand.exists():
            return cand
        # en Windows, si no hay pythonw usa python
        alt = vd / "Scripts" / "python.exe"
        if so == "windows" and alt.exists():
            return alt
    return Path(actual or sys.executable)


# =====================================================================
# Contenido de los accesos directos (puro: se prueba sin crear nada)
# =====================================================================
def _q(s):
    """Entrecomilla una ruta con espacios para una línea Exec de .desktop / shell."""
    s = str(s)
    return f'"{s}"' if " " in s else s


def contenido_desktop(python_exe, ico):
    """Texto de un fichero .desktop (Linux) que lanza el programa."""
    exec_ = f'{_q(python_exe)} {_q(ENTRADA)}'
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={NOMBRE_APP}\n"
            "Comment=Monitoreo de parcelas agrícolas por satélite\n"
            f"Exec={exec_}\n"
            f"Icon={ico}\n"
            f"Path={PROYECTO}\n"
            "Terminal=false\n"
            "Categories=Science;Education;Utility;\n")


def contenido_command_macos(python_exe):
    """Texto de un lanzador .command (macOS): doble clic abre el programa."""
    return ("#!/bin/bash\n"
            f'cd {_q(PROYECTO)}\n'
            f'exec {_q(python_exe)} {_q(ENTRADA)}\n')


def powershell_crear_lnk(destino_lnk, python_exe, ico):
    """Comando PowerShell que crea un acceso directo .lnk en Windows (sin pywin32)."""
    args = str(ENTRADA).replace("'", "''")
    return (
        "$W = New-Object -ComObject WScript.Shell; "
        f"$S = $W.CreateShortcut('{str(destino_lnk).replace(chr(39), chr(39)*2)}'); "
        f"$S.TargetPath = '{str(python_exe).replace(chr(39), chr(39)*2)}'; "
        f"$S.Arguments = '\"{args}\"'; "
        f"$S.WorkingDirectory = '{str(PROYECTO).replace(chr(39), chr(39)*2)}'; "
        f"$S.IconLocation = '{str(ico).replace(chr(39), chr(39)*2)}'; "
        "$S.Save()"
    )


# =====================================================================
# Registro de lo instalado (para desinstalar)
# =====================================================================
def guardar_registro(datos):
    REGISTRO.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def leer_registro():
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


# =====================================================================
# Crear / quitar el acceso directo (efectos reales)
# =====================================================================
def crear_acceso_directo(python_exe, so=None, home=None):
    """Crea el acceso directo en el escritorio (y menú en Linux). Devuelve la lista
    de ficheros creados, para poder borrarlos al desinstalar."""
    so = sistema(so)
    ico = icono(so)
    creados = []
    esc = escritorio(home)
    esc.mkdir(parents=True, exist_ok=True)

    if so == "linux":
        cont = contenido_desktop(python_exe, ico)
        destinos = [esc / f"{NOMBRE_CORTO}.desktop"]
        apps = (Path(home) if home else Path.home()) / ".local" / "share" / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        destinos.append(apps / f"{NOMBRE_CORTO}.desktop")
        for d in destinos:
            d.write_text(cont, encoding="utf-8")
            try:
                d.chmod(0o755)
            except OSError:
                pass
            creados.append(str(d))
        # marcar el del escritorio como "de confianza" (GNOME), sin fallar si no se puede
        try:
            subprocess.run(["gio", "set", str(destinos[0]), "metadata::trusted", "true"],
                           check=False, capture_output=True)
        except Exception:
            pass

    elif so == "darwin":
        d = esc / f"{NOMBRE_APP}.command"
        d.write_text(contenido_command_macos(python_exe), encoding="utf-8")
        try:
            d.chmod(0o755)
        except OSError:
            pass
        creados.append(str(d))

    else:  # windows
        d = esc / f"{NOMBRE_APP}.lnk"
        ps = powershell_crear_lnk(d, python_exe, ico)
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       check=True, capture_output=True)
        creados.append(str(d))
    return creados


def quitar_accesos(registro):
    """Borra los accesos directos que apunta el registro. Devuelve cuántos quitó."""
    n = 0
    for ruta in (registro or {}).get("accesos", []):
        try:
            p = Path(ruta)
            if p.exists():
                p.unlink()
                n += 1
        except OSError:
            pass
    return n


# =====================================================================
# Entorno virtual con las dependencias (efecto real; tolerante)
# =====================================================================
def crear_venv(destino=None, con_deps=True, log=print):
    """Crea un entorno virtual que HEREDA el Python del sistema (para tener tkinter)
    e instala las dependencias. Devuelve la ruta del venv, o None si no se pudo.

    Con `con_deps=False` crea el venv vacío (útil si ya tienes las dependencias)."""
    destino = Path(destino) if destino else (PROYECTO / ".venv")
    try:
        import venv
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(str(destino))
    except Exception as e:
        log(f"  ! No se pudo crear el entorno virtual: {e}")
        return None
    py = python_lanzador(destino)
    py = Path(str(py).replace("pythonw.exe", "python.exe"))   # para pip usamos python, no pythonw
    if con_deps:
        req = PROYECTO / "requirements.txt"
        try:
            log("  · Instalando dependencias (puede tardar)…")
            subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip"],
                           check=False, capture_output=True)
            r = subprocess.run([str(py), "-m", "pip", "install", "-r", str(req)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                log("  ! Algunas dependencias no se instalaron; el programa aún puede "
                    "funcionar en modo reducido. Detalle al final.")
                log((r.stderr or "")[-800:])
        except Exception as e:
            log(f"  ! Error instalando dependencias: {e}")
    return destino


def carpeta_datos_texto():
    """Dónde viven los datos del usuario, para avisar (NO se tocan al desinstalar)."""
    try:
        import rutas
        return str(rutas.directorio_datos())
    except Exception:
        return "la carpeta de datos del usuario (ver README)"
