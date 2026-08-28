# Crear un instalador de Windows (Setup.exe)

Cómo convertir el programa en **un único `Setup.exe`** que envías a alguien y se
instala con doble clic (sin Python, sin nada más). Esto lo hace **quien reparte**
el programa.

Un `.exe` de Windows **solo se puede generar desde Windows** (PyInstaller empaqueta
el intérprete de la máquina donde corre, e Inno Setup es un compilador de Windows).
Por eso hay dos vías: dejar que lo compile GitHub en una máquina Windows suya, o
compilarlo tú en un PC con Windows.

## Opción A (recomendada): que lo compile GitHub por ti

**No necesitas un PC con Windows.** El repositorio trae un flujo que construye el
instalador en una máquina Windows de GitHub:

1. Entra en el repositorio, pestaña **Actions**.
2. Elige **Instalador de Windows** en la lista de la izquierda.
3. Pulsa **Run workflow** y confirma.
4. Cuando termine (unos minutos), abre la ejecución y descarga el `Setup.exe`
   desde el apartado **Artifacts**, al pie de la página.

También se construye solo al publicar una etiqueta de versión (`v1.13.0`, por
ejemplo), y en ese caso queda adjunto a la Release.

---

## Opción B: compilarlo tú en un PC con Windows

### Una sola vez: instalar las herramientas
1. **Python** (si no lo tienes ya): https://www.python.org/downloads/  — marca
   «Add Python to PATH» al instalar.
2. **Inno Setup 6** (gratis): https://jrsoftware.org/isdl.php

### Cada vez que quieras generar el instalador
Descomprime el programa, abre su carpeta y haz **doble clic en
`construir_windows.bat`**. Hace los dos pasos solo:

1. Empaqueta el programa a un ejecutable (PyInstaller).
2. Lo envuelve en el instalador (Inno Setup).

Al terminar, el instalador queda en:

```
Output\MonitorParcelas-Setup-<version>.exe
```

**Ese único fichero es el que envías** (correo, pen-drive, carpeta compartida).

## Qué hace el instalador en el equipo de destino
- Instala el programa en `Archivos de programa\MonitorParcelas`.
- Crea acceso directo en el **menú de inicio** y, si se marca, en el
  **escritorio**.
- Añade **«Desinstalar Monitor de Parcelas»** (se quita como cualquier programa,
  desde «Aplicaciones» de Windows).

### Si prefieres hacerlo a mano
```bat
pip install pyinstaller
python empaquetar.py
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.12.0 instalador_windows.iss
```

## Notas
- La primera vez Windows SmartScreen puede avisar de que el editor es
  «desconocido» (normal en ejecutables sin firma digital). Se abre con «Más
  información → Ejecutar de todas formas». Para quitar ese aviso haría falta un
  **certificado de firma de código** (de pago), que es un paso aparte.
- Los datos del usuario (parcelas, copias) **no** van dentro del instalador: se
  guardan en su carpeta personal y sobreviven a reinstalaciones y actualizaciones.
