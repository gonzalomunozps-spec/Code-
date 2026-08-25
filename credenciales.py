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

Seguridad de la clave de OpenAI (en orden de preferencia):
  1. Variable de entorno OPENAI_API_KEY: TIENE PRIORIDAD y la clave NUNCA se
     guarda en disco (lo mejor para equipos compartidos).
  2. Almacen de secretos del sistema (`keyring`): si el paquete esta disponible y
     con un backend usable -Llavero de macOS, Credential Locker de Windows, Secret
     Service en Linux-, la clave se CIFRA ahi y en el fichero solo queda una marca
     (openai_en_keyring). Es cifrado real gestionado por el SO, no ofuscacion.
  3. Respaldo: si no hay keyring usable y el usuario decide recordarla, se guarda
     OFUSCADA (base64) en config_credenciales.json. base64 NO es cifrado; evita el
     texto plano a simple vista pero no protege frente a alguien con acceso al
     equipo (`clave_en_claro_en_disco` lo delata para poder avisar).
Para no guardarla, basta con desmarcar "recordar" y usar la variable de entorno.
El resto (gee_project, gee_service_account, gee_key_file) se guarda en claro.

`keyring` es OPCIONAL y extraible: si no esta instalado (o no hay backend), todo
funciona igual con el respaldo base64, exactamente como antes de que existiera.
"""

import os
import json
import base64
import tempfile
import rutas
from bitacora import log   # registro de incidencias

ARCHIVO_CRED = rutas.ruta("config_credenciales.json")

# --- Almacen de secretos del sistema (cifrado real, OPCIONAL) --------------
# La clave se guarda bajo este servicio/usuario en el llavero del SO. Si el
# paquete no esta o no hay backend usable, `_KEYRING` queda a None y se usa el
# respaldo base64. Se deja como variable de modulo para poder inyectar un doble
# en las pruebas.
SERVICIO_KEYRING = "gestor-parcelas"
USUARIO_KEYRING = "openai_api_key"
try:
    import keyring as _KEYRING
except Exception:
    _KEYRING = None


def _kr_guardar(key):
    """Guarda la clave en el llavero del SO y CONFIRMA que se puede releer.

    La confirmacion no es paranoia: hay backends «nulos» que aceptan el guardado
    y luego devuelven None (descartan en silencio). Si no se puede releer igual,
    se considera que el llavero no sirve y quien llama cae al respaldo base64.
    Devuelve True solo si la clave quedo guardada y verificada."""
    if _KEYRING is None:
        return False
    try:
        _KEYRING.set_password(SERVICIO_KEYRING, USUARIO_KEYRING, key)
        return _KEYRING.get_password(SERVICIO_KEYRING, USUARIO_KEYRING) == key
    except Exception:
        log.warning("no se pudo usar el llavero del sistema; se usara el respaldo",
                    exc_info=True)
        return False


def _kr_cargar():
    """La clave guardada en el llavero, o None si no hay o no se puede leer."""
    if _KEYRING is None:
        return None
    try:
        return _KEYRING.get_password(SERVICIO_KEYRING, USUARIO_KEYRING)
    except Exception:
        log.warning("no se pudo leer el llavero del sistema", exc_info=True)
        return None


def _kr_borrar():
    """Retira la clave del llavero (al olvidarla o al pasar al respaldo). No falla
    si no habia ninguna."""
    if _KEYRING is None:
        return
    try:
        _KEYRING.delete_password(SERVICIO_KEYRING, USUARIO_KEYRING)
    except Exception:
        pass          # no estaba, o el backend no soporta borrar: da igual


# ---------------------------------------------------------------------------
# Persistencia (atomica y tolerante, igual criterio que el resto del sistema)
# ---------------------------------------------------------------------------
def cargar():
    try:
        with open(ARCHIVO_CRED, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, ValueError):
        return {}
    # 1) si la clave esta en el llavero del SO (cifrada), se trae de ahi
    if cfg.get("openai_en_keyring") and not cfg.get("openai_api_key"):
        key = _kr_cargar()
        if key:
            cfg["openai_api_key"] = key
    # 2) respaldo: la clave ofuscada (base64) del propio fichero
    if cfg.get("openai_api_key_b64") and not cfg.get("openai_api_key"):
        try:
            cfg["openai_api_key"] = base64.b64decode(cfg["openai_api_key_b64"].encode()).decode()
        except Exception:
            log.warning("no se pudo descifrar la clave de OpenAI guardada; se ignora",
                        exc_info=True)
    return cfg


def guardar(cfg, recordar_openai=True):
    """Guarda la configuracion de forma atomica. La clave de OpenAI, si se recuerda,
    va CIFRADA en el llavero del SO cuando se puede; si no, al respaldo OFUSCADO
    (base64). Nunca en claro. Con recordar_openai=False no toca el disco NI el
    llavero (se retira lo que hubiera y se usa solo en memoria)."""
    cfg = cfg or {}
    # las tres formas de la clave se recomponen aqui: no se arrastran del cfg
    almacen = {k: v for k, v in cfg.items()
               if k not in ("openai_api_key", "openai_api_key_b64", "openai_en_keyring",
                            "clave_en_claro_en_disco")}
    key = (cfg.get("openai_api_key") or "").strip()
    if recordar_openai and key:
        if _kr_guardar(key):
            # cifrada en el llavero: en el fichero solo queda la marca, sin clave
            almacen["openai_en_keyring"] = True
        else:
            # respaldo: ofuscada en el fichero, y se retira cualquier resto del llavero
            almacen["openai_api_key_b64"] = base64.b64encode(key.encode()).decode()
            almacen["clave_en_claro_en_disco"] = True     # para poder avisar de que es debil
            _kr_borrar()
    else:
        _kr_borrar()          # "olvidar": que no quede en el llavero de antes

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


def modo_almacen_clave(cfg):
    """Como esta guardada la clave de OpenAI, para poder decirlo en la interfaz:
      'keyring' -> cifrada en el llavero del SO (seguro)
      'base64'  -> ofuscada en el fichero, cifrado NO real (debil: conviene avisar)
      'ninguno' -> no guardada en disco (solo memoria o variable de entorno)"""
    cfg = cfg or {}
    if cfg.get("openai_en_keyring"):
        return "keyring"
    if cfg.get("openai_api_key_b64") or cfg.get("clave_en_claro_en_disco"):
        return "base64"
    return "ninguno"


def _breve(e, n=180):
    s = str(e).strip().replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"
