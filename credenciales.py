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

Seguridad de la clave de OpenAI:
  - Si existe la variable de entorno OPENAI_API_KEY, TIENE PRIORIDAD y la clave
    nunca se guarda en disco (opcion recomendada para equipos compartidos).
  - Si el usuario decide recordarla, se guarda OFUSCADA (base64) en
    config_credenciales.json. Ojo: base64 es ofuscacion, NO cifrado; evita el
    texto plano a simple vista pero no protege frente a alguien con acceso al
    equipo. Para no guardarla, basta con desmarcar "recordar" y usar la variable
    de entorno.
El resto (gee_project, gee_service_account, gee_key_file) se guarda en claro.
"""

import os
import json
import base64
import tempfile
import rutas
from bitacora import log   # registro de incidencias

ARCHIVO_CRED = rutas.ruta("config_credenciales.json")


# ---------------------------------------------------------------------------
# Persistencia (atomica y tolerante, igual criterio que el resto del sistema)
# ---------------------------------------------------------------------------
def cargar():
    try:
        with open(ARCHIVO_CRED, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, ValueError):
        return {}
    # la clave de OpenAI se guarda ofuscada (base64): se descodifica al cargar
    if cfg.get("openai_api_key_b64") and not cfg.get("openai_api_key"):
        try:
            cfg["openai_api_key"] = base64.b64decode(cfg["openai_api_key_b64"].encode()).decode()
        except Exception:
            log.warning("no se pudo descifrar la clave de OpenAI guardada; se ignora",
                        exc_info=True)
    return cfg


def guardar(cfg, recordar_openai=True):
    """Guarda la configuracion de forma atomica. La clave de OpenAI solo se
    escribe si recordar_openai es True, y entonces OFUSCADA (base64), nunca en
    claro. Si es False, la clave no toca el disco (se usa solo en memoria)."""
    cfg = cfg or {}
    almacen = {k: v for k, v in cfg.items()
               if k not in ("openai_api_key", "openai_api_key_b64")}
    key = (cfg.get("openai_api_key") or "").strip()
    if recordar_openai and key:
        almacen["openai_api_key_b64"] = base64.b64encode(key.encode()).decode()

    carpeta = os.path.dirname(os.path.abspath(ARCHIVO_CRED)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=carpeta)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(almacen, f, indent=4, ensure_ascii=False)
        os.replace(tmp, ARCHIVO_CRED)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            log.warning("no se pudo borrar el temporal de credenciales", exc_info=True)
        raise


def aplicar_entorno(cfg, forzar=False):
    """Vuelca OPENAI_API_KEY al entorno del proceso (lo lee interpretacion_fenologica).
    Una variable de entorno externa TIENE PRIORIDAD: si ya esta definida y no se
    fuerza, no se sobrescribe con la clave guardada. `forzar=True` la aplica
    igualmente (p. ej. cuando el usuario acaba de teclear una clave nueva)."""
    cfg = cfg or {}
    if not forzar and os.environ.get("OPENAI_API_KEY"):
        return cfg
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
