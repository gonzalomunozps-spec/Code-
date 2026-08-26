# Registro de cambios

Se sigue [Keep a Changelog](https://keepachangelog.com/es/) y
[SemVer](https://semver.org/lang/es/).

## [1.6.0] — 2026-08

### Añadido
- **Heterogeneidad espacial** (módulo **opcional** `heterogeneidad_espacial.py`):
  usa la rejilla de píxeles georreferenciada para lo que la heterogeneidad clásica
  no ve.
  - Distingue un **foco compacto** (hongo/plaga/rodal) de ruido disperso, da el
    **tamaño** de la mancha mayor (píxeles y ha) y si **persiste** entre pasadas.
  - **Encinas / dehesa**: detecta los píxeles de **arbolado permanente** por su
    firma temporal (verdes todo el año, amplitud baja) y los **excluye** del juicio
    del cultivo herbáceo. Se activa con la casilla *«Arbolado disperso»* de la ficha
    (nuevo flag por parcela, esquema de base v9).
- **Cuadro de heterogeneidad (zonas)** en la ficha, debajo de la gráfica de
  evolución de índices: junta la lectura clásica (media/dispersión) y el análisis
  espacial por píxel.
- **Informe de balance a la carta**: al generarlo se elige qué secciones incluir
  (gráfica, recorrido fenológico, hitos, estado hídrico, uniformidad, cuaderno,
  progresión, radar); radar y cuaderno solo se ofrecen si hay datos.

## [1.5.0] — 2026-08

### Añadido
- **Producción de siega**, no solo de cosecha: un evento **SIEGA** (forraje) ahora
  guarda su rendimiento (kg/ha), superficie y origen del dato, igual que la cosecha
  de grano, y **puede repetirse varias veces por campaña** (cada corte). La humedad
  de grano no se pide en la siega, porque ahí no existe ese dato.
  - El **histórico de rendimientos** incluye cosechas y siegas, cada línea marcada
    con su tipo («Cosecha» / «Siega»). `almacen.rendimientos` devuelve además el
    campo `tipo`.
  - Como la cosecha, la **siega se archiva en la campaña de su propia fecha**, para
    poder cargar el histórico de años anteriores —y varios cortes— sin cambiar de
    campaña en el panel.

## [1.4.0] — 2026-08

### Seguridad
- **La clave de OpenAI se cifra de verdad** cuando el equipo tiene un almacén de
  secretos del sistema (Llavero de macOS, Credential Locker de Windows, Secret
  Service en Linux), vía el paquete opcional `keyring`. En el fichero de
  configuración solo queda una marca; la clave ya no está ahí.
  - Si no hay llavero usable, **respaldo** a la ofuscación base64 de siempre, ahora
    marcada como débil para poder avisar en la interfaz.
  - La variable de entorno `OPENAI_API_KEY` sigue teniendo prioridad y no toca disco.
  - Al «olvidar» la clave se retira también del llavero.
  - La pestaña de Credenciales dice en qué modo quedó guardada (cifrada / ofuscada /
    no guardada). `keyring` es opcional: sin él, todo funciona como antes.

## [1.3.0] — 2026-08

### Añadido
- **Contexto de sequía comarcal** (balance hídrico), en un módulo **opcional y
  extraíble** (`balance_hidrico.py`): si el archivo no está, el diagnóstico se
  comporta igual que antes.
  - Con la lluvia y la ET0 que ya descarga `clima_era5`, calcula el balance
    rodante (lluvia − ET0) de las últimas semanas de la comarca.
  - Si **toda la comarca está en déficit hídrico real**, un NDMI por debajo de lo
    esperado en **secano** se lee como coherente con la sequía general y **deja de
    subir por sí solo el nivel de alerta** (menos falsas alarmas donde el déficit
    es lo normal). El diagnóstico explica el porqué, con el balance de la comarca.
  - En **regadío no se suprime**: el riego debería haber sostenido el NDMI, así que
    un valor bajo pese al riego sigue avisando, acompañado del contexto.
  - No cambia ningún umbral del NDMI ni del NDVI: solo aporta contexto y, como
    mucho, evita que el NDMI bajo escale el semáforo cuando la sequía ya lo explica.
  - En la ficha, la tarjeta de clima muestra una línea con ese balance rodante y su
    severidad (normal / seco / muy seco), para verlo también cuando el NDMI no está bajo.

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
