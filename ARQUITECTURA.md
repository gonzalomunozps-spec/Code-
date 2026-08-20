# Arquitectura del Sistema de Gestión y Monitoreo de Parcelas

Documento para quien tenga que **mantener** este proyecto. Describe qué hace cada
módulo, cómo fluyen los datos y qué reglas conviene respetar para no romperlo.

> **Regla de oro:** la lógica agronómica (fases fenológicas, umbrales, contraste
> de índices, interpretación) es el núcleo de valor del programa y está probada.
> No se cambia sin una razón agronómica explícita. Refactorizar sí; alterar
> resultados, no.

---

## 1. Qué es el programa

Aplicación de escritorio (Tkinter) que monitoriza parcelas agrícolas con imágenes
de satélite **Copernicus/Sentinel-2** (óptico) y **Sentinel-1** (radar), obtenidas
a través de Google Earth Engine. Para cada parcela calcula índices de vegetación,
estima la **fase fenológica** según especie y fecha de siembra, y emite un
diagnóstico (`OK` / `Vigilar` / `Revisar`) coherente con esa fase.

Todo se guarda en un único fichero **SQLite** (`parcelas.db`), dentro del
**directorio de datos del usuario** (ver `rutas.py`): así el programa encuentra
siempre sus datos, se arranque desde donde se arranque.

---

## 2. Mapa de módulos (19 ficheros. ~9.200 líneas)

El grafo de dependencias **no tiene ciclos**. Las capas van de abajo arriba:

```
CAPA 3  ENTREGA        panel_gestion_parcelas.py   informe_anual.py*
           │                     │                        │
CAPA 2b SATELITE       gee_cliente.py  ──►  mapas_cache.py   sincronizacion.py
           │            (unico que PIDE datos a Earth Engine; `ee` inyectable)
CAPA 2  DOMINIO        interpretacion_fenologica.py  registro_parcela.py  sentinel1.py
           │                     │                        │
CAPA 1  DATOS                 almacen.py ──► bitacora.py ──► rutas.py
           │
CAPA 0  HOJAS PURAS    fechas  geo  campanas  cultivo  sigpac
                       contraste_indices  fenologia_especies  herbicida_contexto*
```
`*` = módulo **opcional y extraíble** (ver §6).

### Capa 0 — Lógica pura (sin Tkinter, sin BD, sin red)
Son la base testeable. Ninguno importa a otro.

| Módulo | Responsabilidad |
|---|---|
| `fenologia_especies.py` | Tablas por especie: fase según días desde siembra (extensivos) o mes + marco (leñosos). En leñosos, además, **fases fisiológicas** y umbrales por **régimen hídrico** (regadío/secano). |
| `contraste_indices.py` | Cruza índices entre sí para separar senescencia, estrés hídrico y malas hierbas; heterogeneidad intraparcela. `separacion_copa_cubierta` reparte copa/cubierta en leñosos usando los percentiles de la pasada. |
| `fechas.py` | Conversión ISO ↔ dd-mm-aaaa, máscara y validación al teclear. |
| `geo.py` | Superficie de la parcela (fórmula del polígono). |
| `rejilla.py` | Rejilla de NDVI píxel a píxel: formato compacto (1 byte/píxel + 1 bit de máscara), encaje en la retícula nativa de Sentinel-2 y reglas de comparabilidad entre fechas. |
| `campanas.py` | Campaña agrícola (sep–ago): actual, rango, listado y qué campañas ofrecer por parcela. |
| `cultivo.py` | Modelo de cultivo: `spec_de`, `clave_cultivo`. |
| `sigpac.py` | Consulta de recintos SIGPAC y parseo GeoJSON. La petición HTTP se **inyecta**, por eso se prueba sin red. |
| `clima_era5.py` | Contexto climático de ERA5-Land: conversión de unidades, punto de rejilla, resumen y descarga. **Opcional.** |
| `herbicida_contexto.py` | Interpretación del herbicida con LAI constante. **Opcional.** |
| `calibracion_umbrales.py` | Ajusta los umbrales de los índices con las validaciones del usuario, por ámbito (parcela / municipio / provincia / global). No toca la bibliografía. **Opcional.** |

### Capa 1 — Datos
| Módulo | Responsabilidad |
|---|---|
| `almacen.py` | **Único** punto de acceso a SQLite: parcelas, pasadas, radar, eventos, validaciones. WAL + `RLock`; conexión compartida con *double-checked locking*. Migra los JSON antiguos una sola vez. |
| `bitacora.py` | Registro de incidencias a `parcelas.log`. Nunca escribe en consola; si no puede escribir, degrada a `NullHandler`. |
| `rutas.py` | **Dónde viven los datos**: `GESTOR_PARCELAS_DIR` → `platformdirs` (opcional) → `~/.gestor_parcelas`. También purga los PNG viejos de la caché. |
| `credenciales.py` | Config y clave de OpenAI (ofuscada, fichero 0600, escritura atómica). |

### Capa 2 — Dominio
| Módulo | Responsabilidad |
|---|---|
| `interpretacion_fenologica.py` | **El cerebro.** `evaluar_parcela` produce el diagnóstico; `texto_interpretacion` lo redacta (ChatGPT si hay clave, si no por reglas); `ajuste_por_validaciones` aprende de las correcciones del usuario. |
| `registro_parcela.py` | Cuaderno de campo: eventos, `efecto_producto` (respuesta del cultivo tras una aplicación) y captura de **cosecha** (kg/ha, humedad, superficie, origen del dato). |
| `sentinel1.py` | Radar: VV/VH, RVI, CR, incertidumbre y fiabilidad; relación con el óptico. **Puro**: la descarga está en `gee_cliente`. |

### Capa 2b — Satélite (lo único que habla con Earth Engine)
| Módulo | Responsabilidad |
|---|---|
| `gee_cliente.py` | Índices, sincronización incremental (óptico y radar) y descarga de mapas. El único que usa Earth Engine **para obtener datos** (`credenciales.py` también importa `ee`, pero solo para probar la conexión y autenticar). El módulo `ee` es **inyectable**, por eso la descarga se prueba sin red. Tablas `INDICES`/`RADAR_VIS` y sesión HTTP compartida. |
| `mapas_cache.py` | Nombres y rutas de los PNG cacheados, y su purga. |
| `sincronizacion.py` | Cuándo toca sincronizar, marca del último sync y estado del último intento. |

### Capa 3 — Entrega
| Módulo | Responsabilidad |
|---|---|
| `panel_gestion_parcelas.py` | Solo la interfaz (~3.160 líneas). Ver §5. |
| `informe_anual.py` | Informes PDF (balance y técnico) y Excel. **Opcional.** |
| `demo_sistema.py` | Siembra datos de ejemplo y ejecuta el motor sin satélite ni GUI. |
| `pruebas.py` | 595 pruebas sin pantalla ni red. |
| `pruebas_interfaz.py` | Pruebas **con** pantalla: monta la aplicación y la toca entera. **Opcional.** |

---

## 3. Flujo de datos

```
Earth Engine ──► sincronizar_parcela()  ──► almacen (tabla pasadas)
   (S2/S1)         filtra por cobertura         │
                   válida ≥ 80 % de la          ▼
                   PARCELA (no de la      evaluar_parcela()  ◄── fenologia_especies
                   escena)                      │             ◄── contraste_indices
                                                ▼
                                        texto_interpretacion()
                                          │            │
                                     ChatGPT      respaldo por reglas
                                          └──────┬─────┘
                                                 ▼
                                    ficha  ──►  validación del usuario
                                                 │
                                                 ▼
                                    almacen (tabla validaciones) ──► aprendizaje
```

**Aprendizaje por validación** (§ importante): al corregir un diagnóstico se guarda
qué dijo el sistema, qué era correcto y la observación escrita. En pasadas futuras
del **mismo cultivo y fase**:
- 1 corrección → se anota y se muestra, pero no cambia el estado;
- ≥ 2 coherentes → **ajusta** el diagnóstico automáticamente.

El ámbito puede ser **todo el cultivo** (clave `TIPO/SUBTIPO/ESPECIE`) o **solo esa
parcela** (clave `...@Parcela`). Lo propio de la parcela tiene precedencia; si no
hay, hereda lo del cultivo. Los registros antiguos (sin `@`) siguen valiendo para
todas las parcelas.

---

## 4. Invariantes que conviene no romper

1. **Las pasadas no se pisan.** La sincronización es incremental (`INSERT OR IGNORE`):
   conserva la interpretación ya cacheada de cada fecha.
2. **Todo acceso a SQLite va por `almacen.py`** y bajo su lock. Quien guarde algo
   DERIVADO de una parcela (una caché, un índice en memoria) se apunta a
   `almacen.al_eliminar_parcela` en vez de esperar que quien borra se acuerde de
   avisarle: el borrado se llama desde el panel, desde la demo y desde las
   pruebas, y basta con que uno se olvide para que el dato derivado sobreviva a
   los datos que lo justificaban.
3. **Un número que teclea el usuario se valida en su rango, no solo en su tipo.**
   Que `float("-12")` no falle no significa que −12 sea un marco. Un marco no
   positivo daba una fracción de copa **negativa** y con ella un umbral de casi
   cero: la parcela dejaba de avisar **sin decir nada**, que es la peor forma de
   fallar que tiene este programa. Igual por el otro lado: un percentil imposible
   como fondo subía el umbral por las nubes y la parcela avisaba siempre. El
   criterio bueno ya estaba en `registro_parcela.datos_cosecha`, que rechaza un
   rendimiento negativo o una humedad del 200 %; ahora se aplica también al marco
   (`densidad_arboles`) y al fondo medido (`suelo_de_la_parcela`).
3. **La interfaz solo se toca desde el hilo principal.** El trabajo lento va en
   hilos y vuelve con `widget.after(...)`. Verificado: no hay ni un acceso directo
   a widgets desde un hilo.
4. **Los callbacks diferidos comprueban que el widget siga vivo** (`winfo_exists`)
   antes de pintar: una descarga puede terminar después de cerrar la ventana.
5. **`except ... as e` + lambda diferida:** hay que fijar la excepción como
   argumento por defecto (`lambda err=e:`). Python borra `e` al salir del `except`.
6. **Ninguna ruta de datos es relativa al directorio de trabajo.** Todo se pide a
   `rutas.ruta(...)`. Si al arrancar hay un `parcelas.db` en el directorio actual
   y no en el de datos, se traslada una vez y queda anotado en la bitácora.
7. **Una rejilla que no cuadra con el servidor no se guarda.** Al descargarla se
   pide también la media que calcula Earth Engine sobre la misma geometría, y se
   compara con la media de los píxeles recibidos. Son dos caminos independientes
   al mismo número; si difieren, la rejilla está desplazada o mal enmascarada y
   se descarta. Es la única comprobación que caza eso sin credenciales, y una
   rejilla desplazada no da error: da un mapa de manchas perfectamente creíble.
8. **El píxel (i,j) de dos fechas es el mismo trozo de terreno, o no se compara.**
   La rejilla de NDVI se guarda en la **retícula nativa** de Sentinel-2, sin
   reproyectar, con su georreferenciación (`crs`, `escala`, `i0`, `j0`, filas,
   columnas). Al leer se exige que coincidan los seis: si no —una parcela a
   caballo entre dos husos UTM llega en husos distintos según la pasada— la
   comparación se **descarta**, no se hace mal. Y se guarda la máscara de válidos:
   un píxel tapado por nube no es un píxel anómalo.
9. **En leñosos el juez es el MSAVI, no el NDVI.** El NDVI medio mezcla copa y
   calle: un olivar puede salir «normal» con la copa floja y la hierba alta. El
   vigor de copa se juzga con MSAVI, y con el percentil 90 cuando el marco da
   para separar líneas. `separacion_copa_cubierta` es la **única** fuente del
   veredicto copa/cubierta: antes había dos heurísticas que discrepaban en el
   21 % de los casos, y la cabecera podía contradecir al diagnóstico.
   Los percentiles se leen con el nombre que usa la base (`ndvi_p90`, `msavi_p90`),
   **no** con el que usa `estadisticas_pasada` para la tabla (`p90`). Se leían con
   el segundo y por eso el camino del p90 estuvo muerto: la confianza salía
   siempre «baja» y la copa se juzgaba con la media, justo lo que se quería evitar.
10. **El régimen hídrico manda sobre la especie en leñosos.** Un olivar de secano
   en julio está en déficit por diseño. Donde el déficit es normal o buscado
   (secano en verano, viña en envero) el NDMI **no se juzga**: `ndmi_min = None`.
   Un régimen sin declarar cuenta como SECANO, que es el supuesto que no alarma.
11. **Los umbrales de la bibliografía no se editan.** `fenologia_especies` es la
   referencia agronómica. Lo que el usuario valida se guarda aparte y se aplica
   como una capa encima (`calibracion_umbrales`), acotada y reversible. Donde la
   tabla dice `ndmi_min: None` («aquí este índice no significa nada») no se
   inventa un umbral por muchas validaciones que haya.
   Y para que un umbral se mueva hacen falta **dos condiciones independientes**:
   `MIN_OBSERVACIONES` validaciones coherentes (cantidad) **y** de `MIN_FECHAS`
   pasadas de días distintos (independencia). Varias validaciones del mismo día no
   son varias observaciones: son la misma escena, la misma corrección atmosférica y
   la misma visita, así que su sesgo entra entero. El riesgo real está en los
   ámbitos amplios, donde el mínimo se junta en una tarde validando varias parcelas
   del mismo municipio. `DESVIACION_MAX` es un freno distinto y sigue igual: limita
   **cuánto** se mueve, no **cuándo**.
12. **Las bandas se escalan a reflectancia antes de entrar en cualquier fórmula.**
   `COPERNICUS/S2_SR_HARMONIZED` entrega las bandas espectrales como enteros
   UINT16 con la reflectancia multiplicada por 10.000: un 0,28 llega como 2800.
   `gee_cliente.reflectancia()` deshace ese factor (`ESCALA_SR = 0.0001`) y
   **todos** los índices se calculan sobre el resultado.
   NDVI, GNDVI y NDMI son cocientes normalizados `(a-b)/(a+b)`: multiplicar las
   dos bandas por la misma constante no cambia el resultado, así que salían bien
   incluso sin escalar y siguen dando **exactamente** el mismo número que antes
   (hay pruebas que lo fijan). SAVI, EVI, MSAVI y LAI llevan **constantes
   aditivas** —el `L = 0.5` de SAVI, el `+1.0` de EVI, el `+1` de dentro de la
   raíz de MSAVI—, pensadas para reflectancia en `[0,1]`: frente a valores de
   2800 son despreciables y el índice degenera en otra magnitud, fuera del rango
   físico. Sobre un olivar típico el EVI daba 1,07 donde vale 0,33, y el MSAVI
   0,68 donde vale 0,30 —justo por encima de los `msavi_min` de bibliografía, que
   así no disparaban nunca—. Se escala también los tres normalizados, aunque no
   lo necesiten, para que el escalado no dependa de por qué rama pase el código.
   Fuera de `construir_indice` hay dos sitios que **no** escalan, a propósito: el
   fondo RGB de `descargar_mapa_indice` (pinta la imagen natural, no un índice) y
   el NDVI de la rejilla (normalizado). El radar tampoco: Sentinel-1 llega en dB.
8. **El esquema de la base se versiona** con `PRAGMA user_version`. Para
   cambiarlo hay que subir `ESQUEMA_VERSION` y añadir su migración a
   `_MIGRACIONES` (receta completa en el docstring de `almacen.py`). Va por la
   **7**: la tabla `clima`.
   Esa tabla es la **única excepción** al borrado en cascada de `eliminar_parcela`,
   y es deliberado: se indexa por **punto de rejilla de ERA5** (11 km de lado), no
   por parcela, porque todas las fincas de una comarca comparten el mismo dato y
   guardarlo por parcela serían veinte copias de una sola medida. A cambio, al
   borrar una parcela se retiran los puntos que ya no usa ninguna
   (`purgar_clima`), para no dejar huérfanos.
12. **Hasta dónde llega el histórico lo decide el satélite, no el programa.**
   Sentinel-2 L2A empieza en la campaña **2017-2018**, y el catálogo de Earth
   Engine avisa de que su cobertura no es global hasta **2018-2019**; ambas cosas
   están en `campanas.PRIMERA_CAMPANA_S2` y `PRIMERA_CAMPANA_S2_GLOBAL`, no en un
   número puesto a ojo. Antes había un tope de «5 campañas atrás» que no
   correspondía a nada y recortaba años de histórico que sí existen.
   Una parcela puede tener guardadas campañas **más antiguas que el satélite**
   (importadas, o de otra versión). Esas no se pueden sincronizar —no hay de
   dónde— pero **no se ocultan nunca**: `campanas_de_parcela` devuelve la unión de
   lo descargable y lo guardado, y marca cada campaña con lo que se puede hacer
   con ella (`sincronizable`, `tiene_datos`, `solo_archivo`, `parcial`). Es lo
   único que queda de esos años; esconderlas sería perderlas.
13. **En leñosos, los umbrales de la tabla son de COPA; lo que mide el satélite es
   la PARCELA. Nunca se comparan sin traducir.** Un olivar tradicional a 12×12
   mide NDVI 0,17 y MSAVI 0,11 con el árbol perfecto, porque cuatro quintas partes
   del píxel de 10 m son calle; el rango de `LENOSO_ESPECIES` («un olivo en julio
   está entre 0,40 y 0,78») y los `msavi_min` de `UMBRALES_LENOSO` describen el
   **dosel**. Comparándolos a pelo saltaba «Revisar» en tradicional estuviera el
   árbol como estuviera —y lo que subía ese 0,11 hacia 0,30 no era que el árbol
   mejorase, era que hubiera hierba en la calle: el umbral medía la cubierta.
   La traducción es la **mezcla del píxel**, no un porcentaje:
   `fc · umbral_copa + (1 − fc) · suelo` (`fenologia_especies.umbral_en_escala_parcela`),
   con `fc` = fracción de suelo que tapa la copa, derivada de la geometría del
   marco y del **diámetro de copa**, que se teclea en la ficha del cultivo junto al
   marco. Es opcional: sin él se estima como una proporción del marco menor
   (`PROPORCION_COPA`), que no distingue un olivar viejo de uno joven plantado
   igual —al mismo marco de 10×10, una copa de 2,5 m tapa el 5 % del suelo y una
   de 7 m el 38 %—. Al teclearlo, el formulario dice lo que implica
   (`texto_marco`) y la ficha guarda si la copa está medida o estimada.
   Antes la densidad entraba como un factor
   0,82 / 1,0 / 1,12 —un ±15 % sobre una magnitud que cambia por más del doble
   entre un tradicional y un seto, y de la forma equivocada: lo que cambia con la
   densidad no es el vigor de la copa, es **cuánto píxel es copa**—. Ese factor
   sobrevive solo en el `lai_min`.
   **El suelo se mide, no se supone.** El decil peor de la pasada (`msavi_p10`,
   `ndvi_p10`) es la calle: es el fondo de esa finca ese día, con su humedad y su
   cubierta. Entra como término de suelo de la mezcla, y si la calle está verde el
   umbral sube con ella — que es justo lo que debe pasar: con hierba entre líneas,
   un mismo MSAVI medio es menos prueba de que la copa esté bien. La cuenta sale
   sola: media y umbral suben los dos con el fondo, y lo que acaba comparándose es
   la copa contra el umbral de copa, sea cual sea el fondo. Sin percentiles se cae
   a las constantes (`MSAVI_SUELO`, `NDVI_SUELO`).
   Se descuenta además `margen_mezcla(fc) = (1 − fc) · 0,03`, la mitad si el suelo
   se ha medido: no saber cómo es el suelo pesa entero en la parte del píxel que
   no es copa, así que el margen es mayor cuanta menos copa hay.
   **Y si el juicio cambia de índice, cambia el listón.** Cuando la cubierta domina
   se juzga con MSAVI en vez de NDVI; el rango pasa entonces a ser el de MSAVI en
   escala de parcela (`msavi_min_parcela` / `msavi_max_parcela`). Antes se comparaba
   el MSAVI contra el rango de NDVI de la fase: magnitudes distintas, «Revisar» por
   construcción.
   Y **una sola escala en el juicio**: el p90 no se usa como si fuera copa pura,
   porque a 10 m de píxel ni un marco de 12 m da un píxel limpio de copa (es el
   «límite honesto» de `contraste_indices`). Sirve para el reparto copa/cubierta y
   para contarlo. Sin marco no hay traducción posible, y entonces el aviso no pasa
   de «Vigilar».
9. **Los kg/ha no se calculan.** El rendimiento, la humedad del grano, la
   superficie cosechada y el origen del dato se anotan a mano en un evento
   `COSECHA` y se muestran tal cual. El programa no los estima, no los corrige a
   humedad comercial y no predice con ellos. Es el único dato objetivo del
   sistema: viene de la báscula, no de una imagen.
15. **Filtrar y ordenar no vuelven a evaluar; todo lo demás sí.** Evaluar una
   parcela cuesta traer su serie de pasadas y pasarla entera por
   `evaluar_parcela`. El texto de búsqueda y el criterio de orden **no pueden
   cambiar ningún diagnóstico**, así que se aplican sobre la lista ya evaluada
   (`_refrescar(recargar=False)` → `_pintar_filas`). Lo que sí lo cambia
   —sincronizar, dar de alta, editar, borrar, cambiar de campaña— llama a
   `_refrescar()` a secas y vuelve a evaluar. Antes cada tecla de la caja de
   búsqueda recorría la base y evaluaba **todas** las parcelas: escribir «Olivar»
   eran seis pasadas completas del motor agronómico en el hilo de la interfaz
   (medido: 239 ms con 500 parcelas; ahora 2 ms).
   La lista evaluada es un dato **derivado**, así que cumple la regla 2: se apunta
   a `almacen.al_eliminar_parcela` mediante un contador de versión (`_GENERACION`),
   no con una referencia al panel —que retendría viva una ventana ya cerrada—. Y
   guarda con qué campaña se calculó: enseñar los diagnósticos de otra campaña
   sería exactamente la clase de error callado que este programa no se permite.
   Hay pruebas para las cuatro guardias, y se ha comprobado que **fallan** al
   romper cada una a propósito: una prueba que no muerde es decoración.

16. **La búsqueda repinta tras la última tecla, no en cada una.**
   `RETARDO_BUSQUEDA_MS` (180 ms) con `after_cancel` del repintado anterior. De
   los seis repintados que provocaba escribir «Olivar», cinco no los llegaba a
   leer nadie. Ojo al probarlo: hay que dejar vencer el plazo antes de mirar la
   tabla, o se lee la de antes (`_teclear(..., espera_ms=...)` en el arnés).

14. **Toda medida en píxeles pasa por `esc()`.** La aplicación se declara
   consciente del DPI (`activar_dpi()`, y hay que llamarlo **antes** de crear
   `tk.Tk()`: después Windows ya ha decidido cómo escalarla). A partir de ahí las
   **fuentes** miden sus puntos de verdad y crecen en un monitor al 150 %, pero
   una caja escrita como `height=380` seguiría midiendo 380 píxeles físicos. Si
   no crecen las dos a la vez el contenido deja de caber, y dentro del marco con
   scroll de la ficha `pack` **no avisa**: sencillamente no dibuja lo último
   (mismo fallo silencioso que ya está contado en `FichaParcela`). Por eso las
   alturas de fila, los anchos de columna, el `rowheight` de las tablas y los
   tamaños de ventana (`geom()`) van todos multiplicados por el factor.
   El factor se deduce del DPI real y se **redondea a cuartos**, que es lo que
   ofrecen los sistemas (100 %, 125 %, 150 %…): el DPI informado trae ruido y a
   96 ppp salía 1,0007, con lo que una ventana de 1440 acababa midiendo 1441.
   Está acotado a `[1, 3]`. **A 96 ppp el factor es exactamente 1 y no se mueve
   ni un píxel** respecto de la versión anterior; hay una comparación de capturas
   que lo fija.
   `aplicar_tema(root, escala=...)` permite imponerlo a mano. Existe para las
   pruebas: si el factor saliera del monitor, `pruebas_interfaz.py` daría un
   resultado distinto en cada máquina. El arnés lo fija en 1.0, y el escenario de
   presentación monta aparte una raíz al 150 % para que el camino escalado no se
   quede sin probar.

10. **Las entidades viajan como `dict`**, no como clases. Es deliberado: toleran
   registros antiguos sin campos nuevos. Convertirlas a `dataclass` cambiaría el
   formato de datos.

---

## 5. La interfaz: dónde está cada cosa

`panel_gestion_parcelas.py` es un monolito. Piezas principales:

| Clase | Qué es |
|---|---|
| `PanelGestionParcelas` | Lista de parcelas, búsqueda, orden, autosincronización. La lista se evalúa una vez y se reutiliza al filtrar y ordenar (ver §4.15). |
| `FichaParcela` | Ficha: tabla de pasadas, gráfica, mapa, interpretación, cuaderno. |
| `LienzoMapa` | Mapa con zoom y arrastre. Cachea la imagen escalada y **mueve** el elemento al arrastrar (si no, cada movimiento reescalaba: ~38 ms). |
| `VentanaRadar` | Sentinel-1: gráfica de parámetros y mapa de radar. |
| `VentanaComparaMapas` | Dos mapas lado a lado. |
| `DialogoCorreccion` | Corrección del diagnóstico y **ámbito** (parcela o cultivo). |
| `CampoFecha` / `PopupCalendario` | Entrada de fecha con máscara y calendario. |
| `PanelCredenciales` | Earth Engine y clave de OpenAI. |

Fuera de las clases, en la cabecera del módulo, está la **capa de presentación**:
`activar_dpi()` / `esc()` / `geom()` (escala, ver §4.14), `poner_icono()` y el
cargador perezoso `_matplotlib()`. El icono son dos ficheros junto al fuente,
`icono.png` (ventana, y barra de tareas en Linux/macOS) e `icono.ico` (barra de
tareas de Windows, que no usa el PNG); **son opcionales**: si faltan, la ventana
sale con el icono por defecto de Tk y no pasa nada más.

> **Cuidado:** `FichaParcela`, `LienzoMapa` y `PanelMapaComparado` **no son
> widgets**: son clases normales que pintan sobre un `master`. Pasarles `self`
> como padre de un widget lanza `AttributeError: ... has no attribute 'tk'`, y
> como pasa dentro de un callback de Tk no se ve nada: el widget simplemente no
> aparece. Usa `self.master`. Hay una prueba que lo vigila sobre el fuente.

---

## 6. Piezas opcionales (borrar el fichero y listo)

Se importan con `try/except`. **Si borras el fichero, la función desaparece y el
resto sigue igual**; no hay interruptor que tocar.

- `informe_anual.py` → quita el botón «Informe / Exportar».
- `herbicida_contexto.py` → el herbicida con LAI constante vuelve a «sin cambio claro».
- `calibracion_umbrales.py` → desaparecen el selector de pasada y la validación por
  índice; el diagnóstico vuelve a los umbrales de la tabla. Lo ya anotado se queda
  en la base (`validaciones_indice`), por si se repone.
- `clima_era5.py` → desaparece la tarjeta de clima de la ficha. Lo descargado se
  queda en la tabla `clima`. **Hoy solo enseña datos**: no mueve ningún
  diagnóstico, ni un umbral, ni una fase.

Sus pruebas se autoexcluyen: la suite sigue en verde con o sin ellos.
Comprobado borrando cada fichero: completo 595, sin `informe_anual` 584,
sin `herbicida_contexto` 593, sin `calibracion_umbrales` 566, sin `clima_era5` 564
— los cinco en verde (y la interfaz también, sin `clima_era5`).

---

## 7. Cómo trabajar en este proyecto

```bash
pip install -r requirements.txt
python pruebas.py          # 595 pruebas, sin pantalla ni red
python pruebas_interfaz.py # la interfaz de verdad (xvfb-run -a ... si no hay pantalla)
python demo_sistema.py     # siembra parcelas de ejemplo en parcelas.db
python panel_gestion_parcelas.py
```

Herramientas útiles:
```bash
python -m pyflakes *.py                                  # nombres muertos/indefinidos
python -m mypy --ignore-missing-imports fechas.py geo.py campanas.py cultivo.py sigpac.py
```

### Límites conocidos de las pruebas
- `pruebas.py` corre **sin Tkinter** a propósito, así que no ve nada de lo que
  pasa dentro de la interfaz. Para eso está `pruebas_interfaz.py`, que monta la
  aplicación de verdad y la recorre (`xvfb-run -a python pruebas_interfaz.py` en
  un servidor sin pantalla). Lo que **ninguna** de las dos comprueba es el
  aspecto: que no reviente no significa que se vea bien.
- **No cubren Earth Engine ni la red**: requieren credenciales. `sigpac` sí se
  prueba porque la petición se inyecta; `descargar_mapa_*` **no tiene cobertura**
  (es la deuda técnica más clara que queda).
- **La interpretación se prueba con entradas ya dadas por buenas.** Casi todas las
  pruebas de fenología parten de diccionarios sintéticos (`"ndvi": 0.55`,
  `"lai": 1.8`), así que comprueban el razonamiento pero no de dónde salen esos
  números. Ahí se coló el fallo de escala de las bandas. `pruebas_escala_indices`
  tapa ese agujero para los siete índices: entra bandas crudas de la colección,
  fija el valor exacto que sale (valores de oro sobre olivar, cereal en encañado
  y suelo desnudo), comprueba el rango físico y detecta la regresión si alguien
  vuelve a quitar el escalado. Cualquier índice nuevo debería entrar por ahí.
- Algunas pruebas del panel extraen funciones del fuente con expresiones regulares.
  Al mover código de sitio, revisa esos anclajes (o mejor: extrae la función a un
  módulo puro e impórtala, como ya se hizo con fechas/geo/campanas/sigpac/cultivo).

---

## 8. Deuda técnica pendiente (por orden de valor)

1. **El panel sigue siendo un monolito** de ~3.900 líneas. Partirlo (ficha, radar,
   diálogos, tema) es viable, pero conviene hacerlo con la aplicación abierta para
   verificar cada paso.
2. **Arranque**: resuelto. `matplotlib` ya no se importa al arrancar, sino la
   primera vez que se dibuja una gráfica (`_matplotlib()`). Lo que lo impedía era
   que `aplicar_tema()` tocaba sus `rcParams`; ese trozo se separó en
   `_tema_matplotlib()`, que llama el propio cargador. Importar el panel bajó de
   ~0,51 s a ~0,15 s medidos, y quien solo consulta la lista no la carga nunca.
   Queda una vía si hiciera falta más: `tkintermapview` y `PIL` siguen siendo
   importaciones de arranque.
