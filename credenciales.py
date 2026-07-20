# -*- coding: utf-8 -*-
"""
credenciales.py
===============

Gestion de credenciales/conexiones del sistema, SIN dependencias de Tkinter
(para poder probarla de forma aislada). El panel (PanelCredenciales) es solo la
capa visual sobre estas funciones.

Servicios:
  - Google Earth Engine (earthengine-api): necesario para descargar Sentinel-2.
  - OpenAI (ChatGPT): opcional; mejora la interpretacion. Sin clave, el sistema
    usa el respaldo por reglas.

Estados que devuelven las pruebas:
  "ok"     -> conexion correcta (verde)
  "aviso"  -> no configurado pero no es un error (ambar); p. ej. sin clave de
              OpenAI se sigue funcionando por reglas
  "fallo"  -> configurado pero falla (rojo): paquete ausente, clave invalida,
              sin red, credenciales caducadas...

La configuracion se guarda en config_credenciales.json (texto plano, en este
equipo). Contiene: openai_api_key, gee_project, gee_service_account, gee_key_file.
"""

import os
import json
import tempfile

ARCHIVO_CRED = "config_credenciales.json"


# ---------------------------------------------------------------------------
# Persistencia (atomica y tolerante, igual criterio que el resto del sistema)
# ---------------------------------------------------------------------------
def cargar():
    try:
        with open(ARCHIVO_CRED, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def guardar(cfg):
    carpeta = os.path.dirname(os.path.abspath(ARCHIVO_CRED)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=carpeta)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        os.replace(tmp, ARCHIVO_CRED)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def aplicar_entorno(cfg):
    """Vuelca al entorno del proceso lo que otros modulos leen de os.environ.
    En la practica: OPENAI_API_KEY, que usa interpretacion_fenologica."""
    cfg = cfg or {}
    key = (cfg.get("openai_api_key") or "").strip()
    if key:
        os.environ["OPENAI_API_KEY"] = key
    return cfg


# ---------------------------------------------------------------------------
# Pruebas de conexion (cada una devuelve (estado, mensaje))
# ---------------------------------------------------------------------------
def probar_openai(api_key=None):
    key = (api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")) or ""
    key = key.strip()
    if not key:
        return ("aviso", "Sin clave: la interpretacion usara el respaldo por reglas.")
    try:
        from openai import OpenAI
    except Exception:
        return ("fallo", "El paquete 'openai' no esta instalado (pip install openai).")
    try:
        OpenAI(api_key=key).models.list()      # llamada minima de validacion
        return ("ok", "Conexion con OpenAI correcta.")
    except Exception as e:
        return ("fallo", f"No se pudo validar la clave: {_breve(e)}")


def probar_gee(project=None, key_file=None, service_account=None):
    try:
        import ee
    except Exception:
        return ("fallo", "El paquete 'earthengine-api' no esta instalado.")
    try:
        if key_file and service_account:
            if not os.path.exists(key_file):
                return ("fallo", f"No existe el fichero de clave: {key_file}")
            creds = ee.ServiceAccountCredentials(service_account, key_file)
            ee.Initialize(creds, project=project or None)
        else:
            ee.Initialize(project=project or None)
        # llamada trivial que fuerza la conexion real con el servidor
        ee.Number(1).getInfo()
        return ("ok", "Google Earth Engine inicializado correctamente.")
    except Exception as e:
        return ("fallo", f"No se pudo inicializar GEE: {_breve(e)}. "
                         f"Prueba 'earthengine authenticate' o revisa la cuenta de servicio.")


def autenticar_google(project=None):
    """Inicio de sesion SENCILLO en Google Earth Engine mediante el flujo OAuth
    oficial: abre el navegador para que el usuario escriba su correo y contrasena
    EN LA PAGINA SEGURA DE GOOGLE (no en esta app). Google devuelve un token que
    earthengine-api guarda en el equipo; la contrasena no pasa por aqui ni se
    almacena. Devuelve (estado, mensaje)."""
    try:
        import ee
    except Exception:
        return ("fallo", "El paquete 'earthengine-api' no esta instalado.")
    try:
        ee.Authenticate()                        # abre el navegador (login de Google)
        ee.Initialize(project=project or None)
        ee.Number(1).getInfo()                   # verifica la conexion real
        return ("ok", "Sesion de Google iniciada y verificada correctamente.")
    except Exception as e:
        return ("fallo", f"No se pudo iniciar sesion con Google: {_breve(e)}")


URL_OPENAI_KEYS = "https://platform.openai.com/api-keys"


def estado_credenciales(cfg):
    """Aplica el entorno y prueba ambos servicios. Devuelve un dict pintable."""
    cfg = aplicar_entorno(cfg or {})
    eo, mo = probar_openai(cfg.get("openai_api_key"))
    eg, mg = probar_gee(cfg.get("gee_project"), cfg.get("gee_key_file"),
                        cfg.get("gee_service_account"))
    return {"gee": {"estado": eg, "msg": mg},
            "openai": {"estado": eo, "msg": mo}}


def _breve(e, n=180):
    s = str(e).strip().replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"
