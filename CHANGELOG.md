# Registro de cambios

Se sigue [Keep a Changelog](https://keepachangelog.com/es/) y
[SemVer](https://semver.org/lang/es/).

## [1.2.0] — 2026-08

### Añadido
- **Integrales térmicas (grados-día)**, en un módulo **opcional y extraíble**
  (`grados_dia.py`): si el archivo no está, el programa funciona igual que antes.
  - Al **crear o editar** una parcela, debajo de SIGPAC, se pueden **añadir varias
    integrales**, eligiendo el **método** (base 0/5/6/10 °C, con o sin tope) y
    **desde/hasta qué fase** cuenta cada una (p. ej. «de siembra a cosecha»,
    «de nascencia a floración»).
  - Si **no se añade ninguna**, todo sigue con el calendario de siempre. Si se
    **añade alguna**, en los extensivos con tabla de referencia **la fase la marca
    el GDD** en vez del calendario (prima la integral).
  - En la **ficha**, dentro de «Clima de la comarca», una sección de **grados-día**
    muestra el GDD acumulado, la fase por GDD y deja **elegir cada integral
    definida** para ver su referencia de bibliografía y comparar adelanto/atraso.

### Corregido
- **Cobertura de copa/cubierta (evidencias)**: el LAI se deriva del EVI, así que
  contar «NDVI/EVI» y «LAI/NDVI» a la vez contaba dos veces la misma señal física.
  Ahora esa evidencia se cuenta **una sola vez**, sin cambiar ningún umbral.

## [1.1.0] — 2026-08

### Añadido
- **No se permiten dos parcelas con el mismo nombre**: el alta avisa en vez de
  pisar en silencio la parcela existente (y con ella su histórico).
- **El recinto dibujado a mano tiene prioridad sobre SIGPAC**: dibujar sobre un
  recinto de SIGPAC empieza uno nuevo, y traer SIGPAC sobre un dibujo pide permiso.
- **Corrección manual de la fase** al validar: si el calendario se equivoca (año
  frío/cálido), se corrige la fase a mano; se muestra en su lugar y el aprendizaje
  sigue usando la fase del sistema, con la misma lógica que la corrección de estado.
- **Borrar una campaña entera** de una parcela, con doble confirmación (casilla +
  botón) para evitar borrados accidentales. No toca la parcela ni sus otras campañas.

### Cambiado
- **Informe de balance (PDF)**: sustituye la lista de avisos por una **narrativa
  de la progresión del estado** (de qué estado partió, cuándo y en qué fase saltaron
  los avisos, cómo cerró). El detalle pasada a pasada —estado y fase— pasa al
  **Excel**, en la hoja «Índices por pasada».

## [1.0.0] — 2026-08

Primera versión con forma de producto: instalable, documentada y con arranque
limpio. Reúne el trabajo de las semanas anteriores.

### Añadido
- **Empaquetado**: `pyproject.toml`, `README.md`, `LICENSE` (MIT), `CHANGELOG.md`
  y `COMO_ARRANCAR.md`. Comando `gestor-parcelas` con `--version` y `--help`.
- **Tema claro / oscuro**, elegible en Credenciales, con una paleta de datos
  validada para daltonismo y contraste.
- **Alta resolución (DPI)**: la ventana deja de salir borrosa en monitores 4K, y
  todas las medidas escalan con la pantalla.
- **Icono propio** de la aplicación.
- **Contexto climático de ERA5-Land** (módulo opcional y extraíble).

### Cambiado
- La interfaz, que era un monolito de 4.300 líneas, está partida en siete módulos
  con un grafo de dependencias sin ciclos.
- El arranque ya no espera a matplotlib ni a la comprobación de red de Earth
  Engine: la ventana aparece en ~0,15 s en vez de ~0,5 s.
- La búsqueda de la lista ya no reevalúa el motor agronómico en cada tecla.
- Un solo selector de campaña, en la barra inferior, sirviendo a las dos vistas.

### Corregido
Doce fallos localizados en el repaso completo del código, cada uno con su prueba.
Los de mayor impacto:
- El **último día de cada campaña no se descargaba nunca** (`filterDate` excluye
  el límite derecho, pero el rango era inclusivo).
- Una pasada con **NDVI exactamente 0.0** (suelo desnudo) se descartaba como si
  fuera un hueco.
- `3.500` se leía como 3,5 al reescribir un rendimiento: el dato de báscula
  quedaba **dividido por mil**.
- El **margen interior** no se podía devolver a su valor por defecto.
- La cabecera de la ficha y su texto podían mostrar **diagnósticos distintos**.
- Cuatro sitios que **reventaban con datos malformados** ahora degradan.

---

Nota: `1.0.0` versiona el PROGRAMA. La versión del ESQUEMA de la base de datos se
lleva aparte en `almacen.ESQUEMA_VERSION` y sube cuando cambia una tabla.
