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
| `campanas.py` | Campaña agrícola (sep–ago): actual, rango, listado. |
| `cultivo.py` | Modelo de cultivo: `spec_de`, `clave_cultivo`. |
| `sigpac.py` | Consulta de recintos SIGPAC y parseo GeoJSON. La petición HTTP se **inyecta**, por eso se prueba sin red. |
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
| `pruebas.py` | 416 pruebas sin pantalla ni red. |
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
2. **Todo acceso a SQLite va por `almacen.py`** y bajo su lock.
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
10. **El régimen hídrico manda sobre la especie en leñosos.** Un olivar de secano
   en julio está en déficit por diseño. Donde el déficit es normal o buscado
   (secano en verano, viña en envero) el NDMI **no se juzga**: `ndmi_min = None`.
   Un régimen sin declarar cuenta como SECANO, que es el supuesto que no alarma.
11. **Los umbrales de la bibliografía no se editan.** `fenologia_especies` es la
   referencia agronómica. Lo que el usuario valida se guarda aparte y se aplica
   como una capa encima (`calibracion_umbrales`), acotada y reversible. Donde la
   tabla dice `ndmi_min: None` («aquí este índice no significa nada») no se
   inventa un umbral por muchas validaciones que haya.
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
   `_MIGRACIONES` (receta completa en el docstring de `almacen.py`).
9. **Los kg/ha no se calculan.** El rendimiento, la humedad del grano, la
   superficie cosechada y el origen del dato se anotan a mano en un evento
   `COSECHA` y se muestran tal cual. El programa no los estima, no los corrige a
   humedad comercial y no predice con ellos. Es el único dato objetivo del
   sistema: viene de la báscula, no de una imagen.
10. **Las entidades viajan como `dict`**, no como clases. Es deliberado: toleran
   registros antiguos sin campos nuevos. Convertirlas a `dataclass` cambiaría el
   formato de datos.

---

## 5. La interfaz: dónde está cada cosa

`panel_gestion_parcelas.py` es un monolito. Piezas principales:

| Clase | Qué es |
|---|---|
| `PanelGestionParcelas` | Lista de parcelas, búsqueda, orden, autosincronización. |
| `FichaParcela` | Ficha: tabla de pasadas, gráfica, mapa, interpretación, cuaderno. |
| `LienzoMapa` | Mapa con zoom y arrastre. Cachea la imagen escalada y **mueve** el elemento al arrastrar (si no, cada movimiento reescalaba: ~38 ms). |
| `VentanaRadar` | Sentinel-1: gráfica de parámetros y mapa de radar. |
| `VentanaComparaMapas` | Dos mapas lado a lado. |
| `DialogoCorreccion` | Corrección del diagnóstico y **ámbito** (parcela o cultivo). |
| `CampoFecha` / `PopupCalendario` | Entrada de fecha con máscara y calendario. |
| `PanelCredenciales` | Earth Engine y clave de OpenAI. |

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

Sus pruebas se autoexcluyen: la suite sigue en verde con o sin ellos.
Comprobado borrando cada fichero: completo 493, sin `informe_anual` 482,
sin `herbicida_contexto` 491, sin `calibracion_umbrales` 471 — los cuatro en verde.

---

## 7. Cómo trabajar en este proyecto

```bash
pip install -r requirements.txt
python pruebas.py          # 493 pruebas, sin pantalla ni red
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

1. **El panel sigue siendo un monolito** de ~3.400 líneas. Partirlo (ficha, radar,
   diálogos, tema) es viable, pero conviene hacerlo con la aplicación abierta para
   verificar cada paso.
3. **Arranque**: `matplotlib` cuesta ~1,6 s al importar. Diferirlo no ayuda porque
   `aplicar_tema()` lo necesita igualmente al arrancar.
