; instalador_windows.iss
; =======================
; Script de Inno Setup para crear UN instalador de Windows (Setup.exe) a partir
; del ejecutable que genera `empaquetar.py` (carpeta dist\MonitorParcelas\).
;
; Inno Setup es gratuito: https://jrsoftware.org/isdl.php
; No se compila a mano: lo hace `construir_windows.bat`, que ademas pasa la
; version. Si lo compilas suelto, define la version:  ISCC /DMyAppVersion=1.12.0 instalador_windows.iss
;
; El resultado (MonitorParcelas-Setup-<version>.exe) queda en la carpeta Output\.
; Ese unico fichero es el que se envia: el usuario lo abre, siguiente-siguiente,
; y tiene el programa con su acceso directo y su desinstalador.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "Monitor de Parcelas"
#define MyAppExe "MonitorParcelas.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Monitor de Parcelas
DefaultDirName={autopf}\MonitorParcelas
DefaultGroupName=Monitor de Parcelas
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExe}
OutputDir=Output
OutputBaseFilename=MonitorParcelas-Setup-{#MyAppVersion}
SetupIconFile=icono.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; el ejecutable de PyInstaller es de 64 bits: se instala en Archivos de programa (x64)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
; TODA la carpeta que genera PyInstaller (el .exe y sus ficheros de apoyo)
Source: "dist\MonitorParcelas\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Abrir {#MyAppName} ahora"; Flags: nowait postinstall skipifsilent
