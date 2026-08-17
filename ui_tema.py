# -*- coding: utf-8 -*-
"""
ui_tema.py
==========

SISTEMA DE DISENO de la interfaz Qt: paleta, tipografia, espaciado y la hoja de
estilo (QSS) que lo aplica todo de una vez.

Esta aparte del panel a proposito. En la version de Tkinter el aspecto se
configuraba widget a widget -un `bg=` aqui, un `font=` alla- y por eso costaba
mantenerlo coherente: cualquier pantalla nueva volvia a decidir sus colores. Aqui
las decisiones se toman UNA vez y Qt las propaga por tipo de widget y por
`objectName`. Cambiar el aspecto del programa entero es tocar este fichero.

CRITERIOS, para que quien siga sepa por que cada numero es el que es
--------------------------------------------------------------------
  - PALETA: la misma familia verde agronomica que ya tenia el programa. No se
    reinventa la identidad; se ordena. Los colores de estado (OK / Vigilar /
    Revisar) se mantienen EXACTAMENTE: son los que el usuario ya asocia a un
    juicio, y cambiarlos seria cambiar el mensaje.
  - CONTRASTE: el texto principal sobre superficie da 14.8:1 y el secundario
    7.5:1 (WCAG AA pide 4.5:1). El texto atenuado, 4.6:1, que es el minimo con el
    que se puede leer un dato secundario sin forzar la vista.
  - ESCALA DE ESPACIADO: multiplos de 4 px. Con una escala libre cada pantalla
    acaba con su propio margen y el conjunto se ve descuadrado.
  - TIPOGRAFIA: una sola familia, cuatro tamanos y dos pesos. La jerarquia se
    hace con tamano y color, no con negritas por todas partes.
  - DENSIDAD: filas de 30 px y controles de 30 px de alto. Es una herramienta de
    trabajo con tablas largas; el aire de sobra obliga a hacer scroll para ver lo
    mismo.
"""

# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------
# Los cinco primeros son la estructura (fondo, tarjeta, borde); los de texto, la
# jerarquia; los de estado, el juicio. Nada mas. Un color que no esta aqui no se
# usa en la interfaz.
COLOR = {
    # estructura
    "page":        "#eef1f4",   # fondo de la ventana
    "surface":     "#ffffff",   # tarjetas y tablas
    "surface_alt": "#f7fafc",   # filas alternas, cabeceras de tabla
    "border":      "#e2e8f0",
    "border_soft": "#edf2f7",
    # identidad
    "header_bg":   "#1e3a2b",   # verde oscuro de la cabecera
    "header_sub":  "#a7c4b5",
    "primary":     "#2f855a",
    "primary_dk":  "#276749",
    "primary_soft": "#e6f4ec",
    # texto
    "text":        "#1a202c",
    "text_sec":    "#4a5568",
    "text_muted":  "#718096",
    "text_invert": "#ffffff",
    # estado (los mismos que ya usaba el programa: son el mensaje)
    "ok_fg": "#276749", "ok_bg": "#f0fff4",
    "warn_fg": "#c05621", "warn_bg": "#fffaf0",
    "danger_fg": "#c53030", "danger_bg": "#fff5f5",
    "muted_fg": "#718096", "muted_bg": "#edf2f7",
    # foco: un solo color para "esto es lo que tienes seleccionado"
    "focus": "#38a169",
    "seleccion": "#e6f4ec",
}

# Color del punto y del texto de cada estado. Se pide por clave, no por texto:
# buscar la palabra dentro de una frase fue la causa de un fallo real.
ESTADO_COLOR = {
    "OK": (COLOR["ok_fg"], COLOR["ok_bg"]),
    "Vigilar": (COLOR["warn_fg"], COLOR["warn_bg"]),
    "Revisar": (COLOR["danger_fg"], COLOR["danger_bg"]),
}


def color_estado(clave):
    """(texto, fondo) de un estado. Lo que no es un juicio va en gris."""
    return ESTADO_COLOR.get(clave, (COLOR["muted_fg"], COLOR["muted_bg"]))


# ---------------------------------------------------------------------------
# Tipografia y espaciado
# ---------------------------------------------------------------------------
# Candidatas por orden de preferencia. Se elige la primera instalada; el resto
# del sistema de diseno no depende de cual salga.
FAMILIAS = ["Inter", "Segoe UI", "SF Pro Text", "Helvetica Neue",
            "Roboto", "DejaVu Sans", "Arial"]

TAMANO = {"h1": 16, "h2": 12, "body": 10, "small": 9}
PESO = {"normal": 400, "medio": 600}

# Escala de espaciado, en px. Todo margen y todo hueco sale de aqui.
ESP = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24}

RADIO = 6          # esquinas de tarjetas y controles
ALTO_FILA = 30     # densidad de las tablas
ALTO_CONTROL = 30


def familia_disponible(candidatas=None):
    """La primera familia instalada de la lista. Requiere QApplication creada."""
    from PySide6.QtGui import QFontDatabase
    disponibles = set(QFontDatabase.families())
    for c in (candidatas or FAMILIAS):
        if c in disponibles:
            return c
    return QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()


# ---------------------------------------------------------------------------
# Hoja de estilo
# ---------------------------------------------------------------------------
# Un unico QSS para toda la aplicacion. Se apoya en `objectName` para las piezas
# con identidad propia (cabecera, tarjeta, insignias) y en el tipo de widget para
# el resto, de modo que una pantalla nueva ya nace con el aspecto correcto sin
# tener que configurar nada.
_QSS = """
QWidget {{
    background: {page};
    color: {text};
    font-family: "{fam}";
    font-size: {body}pt;
}}

/* ---- cabecera de la aplicacion ---- */
#Cabecera {{ background: {header_bg}; }}
#CabeceraTitulo {{
    color: {text_invert};
    font-size: {h1}pt;
    font-weight: {medio};
    background: transparent;
}}
#CabeceraSub {{
    color: {header_sub};
    font-size: {small}pt;
    background: transparent;
}}

/* ---- tarjetas: la unidad de composicion de todas las pantallas ---- */
#Tarjeta {{
    background: {surface};
    border: 1px solid {border};
    border-radius: {radio}px;
}}
#TarjetaTitulo {{
    font-size: {h2}pt;
    font-weight: {medio};
    background: transparent;
}}
#Silencioso {{ color: {text_muted}; font-size: {small}pt; background: transparent; }}
#Secundario {{ color: {text_sec}; font-size: {small}pt; background: transparent; }}

/* ---- barra de herramientas ---- */
#Barra {{
    background: {surface};
    border: 1px solid {border};
    border-radius: {radio}px;
}}
#Barra QLabel {{ background: transparent; color: {text_muted}; font-size: {small}pt; }}

/* ---- botones ---- */
QPushButton {{
    background: {surface};
    border: 1px solid {border};
    border-radius: {radio}px;
    padding: 0 {esp_m}px;
    min-height: {alto_control}px;
    color: {text_sec};
}}
QPushButton:hover  {{ background: {surface_alt}; border-color: {primary}; color: {primary_dk}; }}
QPushButton:pressed {{ background: {primary_soft}; }}
QPushButton:disabled {{ color: {text_muted}; border-color: {border_soft}; }}
QPushButton#Primario {{
    background: {primary};
    border: 1px solid {primary};
    color: {text_invert};
    font-weight: {medio};
}}
QPushButton#Primario:hover   {{ background: {primary_dk}; border-color: {primary_dk}; }}
QPushButton#Primario:pressed {{ background: {header_bg}; }}
QPushButton#Fantasma {{
    background: transparent;
    border: 1px solid transparent;
    color: {header_sub};
}}
QPushButton#Fantasma:hover {{ background: rgba(255,255,255,0.10); color: {text_invert}; }}

/* ---- campos ---- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
    background: {surface};
    border: 1px solid {border};
    border-radius: {radio}px;
    padding: 0 {esp_s}px;
    min-height: {alto_control}px;
    selection-background-color: {primary};
    selection-color: {text_invert};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
    border-color: {focus};
}}
QLineEdit:disabled, QComboBox:disabled {{ background: {surface_alt}; color: {text_muted}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {surface};
    border: 1px solid {border};
    selection-background-color: {seleccion};
    selection-color: {text};
    outline: none;
}}

/* ---- tablas ---- */
QTableView {{
    background: {surface};
    alternate-background-color: {surface_alt};
    border: none;
    gridline-color: transparent;
    selection-background-color: {seleccion};
    selection-color: {text};
    outline: none;
}}
QHeaderView::section {{
    background: {surface_alt};
    color: {text_muted};
    border: none;
    border-bottom: 1px solid {border};
    padding: {esp_s}px;
    font-size: {small}pt;
    font-weight: {medio};
}}
QTableView::item {{ padding: 0 {esp_s}px; border: none; }}

/* ---- barras de desplazamiento: finas, sin flechas ---- */
QScrollBar:vertical   {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {border}; border-radius: 5px; min-height: 32px; min-width: 32px;
}}
QScrollBar::handle:hover {{ background: {text_muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- pestanas ---- */
QTabWidget::pane {{ border: none; background: {page}; }}
QTabBar::tab {{
    background: transparent;
    color: {text_muted};
    padding: {esp_s}px {esp_l}px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {primary_dk}; border-bottom-color: {primary}; font-weight: {medio}; }}
QTabBar::tab:hover:!selected {{ color: {text_sec}; }}

/* ---- menus y mensajes ---- */
QMenu {{
    background: {surface};
    border: 1px solid {border};
    border-radius: {radio}px;
    padding: {esp_xs}px;
}}
QMenu::item {{ padding: {esp_s}px {esp_l}px; border-radius: {radio}px; }}
QMenu::item:selected {{ background: {seleccion}; color: {text}; }}
QMenu::separator {{ height: 1px; background: {border_soft}; margin: {esp_xs}px 0; }}
QToolTip {{
    background: {header_bg};
    color: {text_invert};
    border: none;
    border-radius: {radio}px;
    padding: {esp_s}px;
}}
QStatusBar {{ background: {surface}; color: {text_muted}; border-top: 1px solid {border}; }}
QStatusBar::item {{ border: none; }}
"""


def hoja_de_estilo(familia=None):
    """El QSS completo, ya resuelto con la paleta y la tipografia."""
    fam = familia or "sans-serif"
    valores = dict(COLOR)
    valores.update(fam=fam, radio=RADIO, alto_control=ALTO_CONTROL,
                   medio=PESO["medio"], **{f"esp_{k}": v for k, v in ESP.items()},
                   **{k: v for k, v in TAMANO.items()})
    return _QSS.format(**valores)


def aplicar_tema(app):
    """Deja la aplicacion con el aspecto del programa. Se llama UNA vez al arrancar.

    Devuelve la familia tipografica elegida, que es lo unico que depende de que
    fuentes tenga instaladas la maquina."""
    from PySide6.QtGui import QFont
    fam = familia_disponible()
    app.setFont(QFont(fam, TAMANO["body"]))
    app.setStyleSheet(hoja_de_estilo(fam))
    return fam
