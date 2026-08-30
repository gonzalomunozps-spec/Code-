# Cómo arrancar

## 1. Requisitos

Python **3.10 o superior**. Tkinter **no se instala con pip**: viene con Python en
Windows y macOS; en Linux es un paquete del sistema.

```bash
# Linux (Debian/Ubuntu) — solo si te falta Tkinter
sudo apt install python3-tk
```

## 2. Dependencias

```bash
pip install -r requirements.txt
```

## 3. Arrancar el programa

```bash
python panel_gestion_parcelas.py
```

En Linux/macOS puede que tengas que escribir `python3` en vez de `python`.

## 4. Primera vez: credenciales

El programa abre sin credenciales, pero **no podrá descargar imágenes**. Para eso:

1. Ve a la pestaña **Credenciales**.
2. Pulsa **Iniciar sesión con Google** (se abre el navegador; la contraseña se
   escribe en la página de Google, no aquí).
3. La clave de OpenAI es **opcional**: sin ella la interpretación se genera por
   reglas en vez de con ChatGPT.

También puedes autenticarte desde la terminal:

```bash
earthengine authenticate
```

## 5. Probar sin satélite

Para ver el programa funcionando con datos de ejemplo, sin credenciales ni red:

```bash
python demo_sistema.py             # siembra 6 parcelas de ejemplo
python panel_gestion_parcelas.py   # y ábrelas
```

## 6. Dónde se guardan los datos

En la carpeta de datos del usuario, **no** en la del programa:

| Sistema | Ruta |
|---|---|
| Windows | `%LOCALAPPDATA%\gestor_parcelas\` |
| macOS | `~/Library/Application Support/gestor_parcelas/` |
| Linux | `~/.local/share/gestor_parcelas/` (o `~/.gestor_parcelas`) |

Se puede cambiar con la variable de entorno `GESTOR_PARCELAS_DIR`:

```bash
GESTOR_PARCELAS_DIR=/ruta/que/quieras python panel_gestion_parcelas.py
```

Dentro está `parcelas.db` (SQLite, todos los datos), `parcelas.log` y la caché de
mapas. **Para hacer copia de seguridad basta con copiar esa carpeta.**

## 7. Pruebas

```bash
python pruebas.py            # 956 pruebas, sin pantalla ni red
python pruebas_interfaz.py   # monta la aplicación de verdad y la recorre
```

En un servidor sin pantalla: `xvfb-run -a python pruebas_interfaz.py`.

## 8. Tema claro / oscuro

Se elige en la pestaña **Credenciales**, apartado *Aspecto*. Se aplica al volver a
abrir el programa: Tk no puede repintar en caliente las ventanas ya creadas.
