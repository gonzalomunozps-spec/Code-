# Registro de cambios

Se sigue [Keep a Changelog](https://keepachangelog.com/es/) y
[SemVer](https://semver.org/lang/es/).

## [1.21.1] — 2026-08

Auditoría final de la revisión 1.16: no se añade ninguna funcionalidad, se repasa
todo lo hecho y se arregla lo que la revisión destapó.

### Corregido
- **El botón «Copias» reventaba si se borraba el módulo opcional `copias`.** El
  manejador importaba `ui_copias` al pulsar, no al arrancar, así que quedaba un botón
  visible que lanzaba `ModuleNotFoundError`. Ahora la comprobación se hace una vez al
  importar: sin el módulo, el botón ni se crea. Con **todos** los módulos opcionales
  borrados a la vez, la suite (777) y la de interfaz pasan enteras.
- **«Revisar datos» salía en tinta normal en el PDF anual**, mientras el panel lo
  pinta en ámbar. Ahora coinciden: es el papel que se archiva y no debía disimularlo.
- **`medir_ruido` no viajaba en `pip install .`**: faltaba en `py-modules`.

### Añadido (sólo pruebas)
- **Trinquete de empaquetado**: cada `.py` del árbol está en `py-modules` o en una
  lista explícita de scripts de instalación. Verificado que falla al quitar un módulo.
- **Prueba de interfaz** de que el manejador de copias no lanza sin el módulo.

### Cambiado
- La guarda de fecha duplicada en `contraste_indices` (7 líneas y su comentario, dos
  veces) pasa a `_mes_de`. Salida del motor **idéntica**: 3.499 casos sin diferencias.
- `ARQUITECTURA.md` al día donde el código la había dejado atrás: la tubería ya tiene
  **9** reglas (no 7), `evaluar_parcela` está en **CC 12** (no 4: encima se le montó el
  pliegue de la persistencia), 49 ficheros y ~18.000 líneas, y se documenta la única
  arista hacia atrás del grafo (`calibracion_umbrales` → motor, diferida a propósito).
- Se documenta como **deuda deliberada** por qué no se marcó uno a uno el origen de los
  ~599 números de `fenologia_especies` (§8.2), con las medidas que llevaron a esa
  decisión.

## [1.21.0] — 2026-08

### Añadido
- **El diagnóstico dice cuándo se ha decidido por poco.** Medido: uno de cada cuatro
  veredictos cambia si el NDVI se mueve ±0,03, y todos se presentaban con la misma
  rotundidad. Ahora, cuando el valor está pegado a un corte —o cuando la fase pudo
  cambiar entre esta pasada y la anterior— el motivo lo dice y da la distancia exacta.
  - **No cambia ningún veredicto**: verificado sobre las 3.499 entradas del barrido,
    cambia el motivo y nada más.
  - En la lista de parcelas el estado lleva un `*` cuando está ajustado, para poder
    distinguir de un vistazo los avisos sólidos de los que están en el filo.
  - No repite lo que ya se decía (separación copa/calle, umbral calibrado).

## [1.20.0] — 2026-08

### Añadido
- **El sistema detecta ahora datos que no cuadran con lo declarado.** Antes sólo sabía
  ver «hay menos verde del que debería»; medido, el techo de la fase no se comparaba
  **ni una vez**, así que un NDVI de 1,00 quince días después de sembrar daba «OK».
  - **Estado nuevo «Revisar datos»** cuando el verdor supera lo que la especie declarada
    alcanza en su mejor momento de todo el ciclo. El mensaje dice qué mirar: fecha de
    siembra, especie, geometría, o una cubierta de malas hierbas más verde que el cultivo.
  - **Nota, sin tocar el semáforo**, cuando el verdor corresponde a una fase distinta de
    la declarada y de sus contiguas. Un cultivo puede ir adelantado: eso se dice, no se
    marca en rojo.
  - Ninguno de los dos listones lleva un factor inventado: salen de las tablas de fases.
  - «Revisar datos» **no entra en el aprendizaje ni en la calibración** y no se ofrece
    para validar: no es un juicio agronómico. En la lista va con color de aviso —el
    cultivo puede estar perfectamente— y justo detrás de «Revisar».

## [1.19.0] — 2026-08

### Cambiado
- **El semáforo ya no cambia con una sola pasada** (persistencia de dos pasadas). Un
  estado nuevo se enseña cuando el juicio del motor lo repite en dos pasadas seguidas.
  - **Por qué**: medido sobre 6.880 combinaciones, con ruido cero el semáforo no cambia
    nunca; con ruido realista de ±0,03 oscila en el 45 % de los casos, y siempre pegado
    a un umbral (a +0,03 por encima, cero oscilación).
  - **Cuánto arregla y qué cuesta**: 623 → 140 cambios de estado sobre 282 series
    (**78 % menos**, 483 falsos cambios evitados); un deterioro real se avisa **una
    pasada más tarde**.
  - **Lo que NO espera**: «Sin dato», «Segado», el barbecho y cualquier pasada ya
    explicada (caída propia de la fase o evento del cuaderno). No son ruido, son hechos.
  - El motivo sigue contando lo observado en la pasada, con una nota que explica por qué
    el semáforo aún no se ha movido.
- **`estado_crudo` en el diagnóstico**: el juicio sin filtrar. Es lo que aprende la
  calibración y lo que se compara al medir el efecto del calibrado — retener un estado
  es presentación, no agronomía.

### Añadido
- **`medir_ruido.py`**: herramienta para estimar, sobre tu base real, cuánto ruido tiene
  el NDVI de tus parcelas y cuántos cambios del semáforo ocurrieron pegados a un umbral.

## [1.18.0] — 2026-08

### Añadido
- **Fichero de oro del motor** (`pruebas_oro.py` + `oro_evaluar_parcela.json`): congela
  la salida completa de `evaluar_parcela` —incluido el `motivo` que lee el agricultor—
  sobre **3.499 entradas** generadas a partir de las propias tablas de fases. Cubre
  fronteras exactas de fase, NDVI pegado a cada corte (±0,005), NDMI a los dos lados de
  su mínimo, leñosos con y sin marco, series de 1/2/4 pasadas, eventos, zonas y 25
  entradas degeneradas. Determinista: sin red, sin base, sin azar y sin depender de la
  fecha de hoy. **No se regenera solo, nunca**: si falla, dice qué caso y qué cambió.
- **46 pruebas nuevas de las reglas del motor**, una tabla de casos por regla.

### Cambiado
- **`evaluar_parcela` pasa a ser una tubería de reglas explícita** (ver ARQUITECTURA §4b).
  De **346 líneas, complejidad 108 y 57 locales** a **47 líneas, complejidad 4 y 13
  locales**. El orden de las reglas es ahora una lista con nombre, no la posición de las
  líneas en el fichero, y el contexto es de sólo lectura para que ninguna regla le
  cambie el suelo a la siguiente.
  - **Ni un veredicto, ni un umbral, ni un texto cambian.** El fichero de oro pasa
    idéntico: es la prueba, no la intención.

## [1.17.0] — 2026-08

### Añadido
- **El informe enseña datos que el sistema ya tenía y no llegaban al papel.** Nada de
  esto se calcula nuevo: se pinta lo que ya producen la base y los módulos existentes.
  - **Identificación completa**: variedad, **recinto SIGPAC** (en el orden oficial
    prov/mun/agr/zona/pol/par/rec) y aviso de **arbolado disperso**. Este último no es
    un adorno: con la casilla marcada los índices del diagnóstico se calculan sobre los
    píxeles de cultivo, apartando las copas, y sin decirlo los números no se pueden
    reproducir.
  - **Clima de la campaña** (ERA5-Land), agregado **mes a mes** —el diario son ~365
    filas— con lluvia y ET0 sumadas y las extremas del mes. En el Excel, además, una
    hoja con el detalle **día a día** y su gráfica.
  - **Balance hídrico de la comarca** (lluvia − ET0) dentro de la sección de estado
    hídrico: distingue un NDMI bajo por sequía general de uno bajo por un problema de
    esta parcela.
  - **Grados-día**: acumulado desde la siembra, fase por GDD, cuánto falta para la
    siguiente y la tabla de integrales con su referencia y de dónde sale (tuya o de
    bibliografía).
  - **Producción registrada** (báscula) de **todas** las campañas, no solo la que se
    está viendo: kg/ha, humedad de grano, superficie y origen del dato.
- Las tres secciones nuevas (`clima`, `gdd`, `rendimiento`) entran en el selector de
  «qué incluir» como las demás, y **`secciones_con_datos`** las marca «(sin datos)»
  cuando no hay nada que enseñar, para no pedir una sección que saldría en blanco.

### Corregido
- **El informe reventaba si un índice faltaba en toda la campaña.** Una parcela puede
  tener NDVI en todas las pasadas y NDMI o LAI en ninguna; esa línea vacía hacía saltar
  a reportlab («Polyline must have 2 or more points») y se caía el documento entero.
  Ahora se descarta la línea que no tiene al menos dos puntos, y si no queda ninguna
  simplemente no hay gráfica.

### Cambiado
- Las secciones del informe técnico **se numeran solas**. Iban numeradas a mano, así que
  insertar una obligaba a renumerar las siguientes —y alguna se quedaba atrás—.

## [1.16.0] — 2026-08

### Cambiado
- **El cuaderno de campo separa «abono» de «bioestimulante»**. Antes iban en una
  sola opción («abono / nutrición») y al releer el cuaderno no se sabía cuál de los
  dos se había aplicado. Son productos distintos: el abono aporta unidades
  fertilizantes y como tal se declara; el bioestimulante no aporta nutrientes,
  actúa sobre la fisiología de la planta y en la normativa europea de productos
  fertilizantes es otra categoría.
  - **La medida del efecto no cambia**: ninguno de los dos es herbicida, así que los
    dos pasan por la misma rama de `efecto_producto`. Es una separación de
    **registro**, no de cálculo: no se toca ningún umbral.
  - Las intervenciones ya anotadas conservan su texto («abono / nutrición») y se
    siguen leyendo y midiendo igual; esa opción sencillamente ya no se ofrece para
    las nuevas.

## [1.15.0] — 2026-08

### Corregido
- **La interpretación de los índices ya no sale cortada.** Compartía una fila de
  altura fija con la gráfica, y heredaba el recorte. Ahora la gráfica va sola y a
  todo lo ancho, y debajo van interpretación y análisis de zonas **uno al lado del
  otro**, repartidos a medias, en una fila que crece con su contenido.

## [1.14.0] — 2026-08

### Añadido
- **Variedad por parcela**: catálogo propio por especie (empieza vacío, con «+ Nueva»),
  gobernado por las reglas de la especie. Las validaciones ajustan índices y umbrales
  **por variedad**.
- **PRADERA** como cultivo de extensivo de siega en verde, tratado como asociación de
  especies y reutilizando el calendario de cortes existente.

### Corregido
- Menos falsos positivos del antivirus en el instalador (sin compresión UPX y con
  metadatos de versión y fabricante en el ejecutable).

## [1.13.0] — 2026-08

### Corregido
- **Carrera al restaurar una copia de seguridad**: un hilo podía quedarse con una
  conexión que otro acababa de cerrar (`Cannot operate on a closed database`). La
  conexión se lee dentro del cerrojo y la restauración vuelca sobre la base viva
  sin cerrarla.

### Añadido
- **Sincronización cancelable**, con progreso parcela a parcela y cierre limpio a
  media sincronización.

## [1.12.0] — 2026-08

### Añadido
- **Copias de seguridad automáticas** con rotación, exportación y restauración.
- **Manual de usuario** accesible desde el panel.
- **Ejecutable sin Python** (PyInstaller) e **instalador de Windows** de un clic
  (Inno Setup), construido y publicado desde GitHub Actions.
- **Mensajes de error claros** de Earth Engine (red, credenciales, cuota, tiempo de espera).

## [1.9.0] — 2026-08

### Añadido
- **Observaciones de campo**: verdad-terreno anotable desde cada ficha (fase, rendimiento,
  humedad de sonda, dato de dron), **en cualquier momento y también de campañas
  anteriores**, archivada por la fecha del dato.
- **`validacion.py`**: matriz de fases con kappa, RMSE, MAE, sesgo y regresión, para
  **medir** cuánto acierta el sistema en vez de suponerlo.

## [1.8.0] — 2026-08

### Añadido
- **Instalador y desinstalador automáticos** (multiplataforma: Windows, Linux, macOS),
  como scripts aparte que no tocan el programa:
  - `python instalar.py` prepara un entorno aislado con las dependencias y crea un
    **acceso directo en el escritorio** (y en el menú, en Linux). Con `--sin-venv`
    usa el Python actual.
  - `python desinstalar.py` lo quita todo (acceso directo y entorno). **Nunca borra
    los datos** (`parcelas.db`): dice dónde están para que decidas tú.
  - El programa **se sigue pudiendo usar sin instalar**: `python iniciar.py` (o
    `python panel_gestion_parcelas.py`).

### Corregido
- **`pip install .` empaqueta ahora todos los módulos**: faltaban `grados_dia`,
  `balance_hidrico`, `heterogeneidad_espacial` y `vista_ficha` en la lista, así que
  una instalación por paquete se quedaba sin esas funciones. Añadidos.

## [1.7.0] — 2026-08

### Cambiado
- **El enmascarado de encinas llega al diagnóstico** (antes solo a la lectura): en
  un **extensivo marcado como «arbolado disperso»**, el semáforo se calcula con la
  **media de NDVI del cultivo** (píxeles no arbolados de la rejilla de esa fecha),
  no con la media bruta inflada por las encinas. El diagnóstico dice cuándo lo hace
  y con qué valor.
  - **Triple candado**: hace falta el flag de la parcela, el módulo
    `heterogeneidad_espacial` y una rejilla de esa fecha; si falta alguno, se juzga
    con la media de siempre. Sin marcar, o sin el módulo, el comportamiento es
    **idéntico** al anterior.
  - Se toca **solo el valor que se juzga** (el NDVI del nivel): los deltas y el NDMI
    se dejan igual (el árbol es estable, apenas mueve el delta; el NDMI no se guarda
    por píxel).

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
