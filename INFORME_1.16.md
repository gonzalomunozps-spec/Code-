# MONITOR DE PARCELAS 1.16 — ANTES / DESPUÉS

Informe de cierre del plan de trabajo 1.16 (fases 0–7).
Punto de partida: `fa19d7b`, v1.17.0. Punto de llegada: v1.21.1.
Todas las cifras de este informe están **medidas**, no estimadas; al lado de cada
una va cómo reproducirla.

---

## 1. La tabla

Las notas son mi valoración, con la evidencia al lado para que se pueda discutir.
Las filas son las cinco metas del plan (robustez, mantenibilidad, seguridad ante
regresiones, estabilidad para el agricultor, transparencia) más las cinco cosas que
hubo que tocar para conseguirlas.

| # | Dimensión | Antes | Después | Evidencia |
|---|-----------|-------|---------|-----------|
| 1 | Robustez del motor | 6 | **8** | `evaluar_parcela` pasó de CC 108 / 346 líneas / 48 locales a CC 12 / 55 / 6, y el juicio vive en `_diagnostico_crudo` + 9 reglas, ninguna por encima de CC 19 |
| 2 | Mantenibilidad del motor | 4 | **8** | Las reglas 7 y 8 (plausibilidad, fiabilidad) se añadieron **sin tocar las seis anteriores**. Ésa es la prueba, no el número de líneas |
| 3 | Seguridad ante regresiones | 3 | **8** | Fichero de oro: 3.499 casos, 13 bloques, 7 estados. Perturbar `lo*0,8 → lo*0,85` mueve 121 casos: la red **agarra** |
| 4 | Estabilidad del semáforo | 4 | **8** | Sobre 282 series con ruido realista: 623 → 140 cambios de estado (−78 %), 483 falsos cambios evitados |
| 5 | Transparencia del diagnóstico | 3 | **7** | Uno de cada cuatro veredictos cambia si el NDVI se mueve ±0,03; ahora esos lo dicen. Sensibilidad 98 %, precisión 93 % contra pruebas empíricas de vuelco |
| 6 | Detección de datos incoherentes | 2 | **7** | Estado nuevo `Revisar datos` con dos niveles (imposible / propio de otra fase). 44 de los 3.499 casos del barrido lo activan |
| 7 | Piezas opcionales de verdad borrables | 6 | **9** | Con **los 12 módulos opcionales borrados a la vez**: 777 pruebas verdes y la interfaz entera. Antes de esta auditoría, no |
| 8 | Cobertura del núcleo | 86,1 % | **87,3 %** | 8 módulos de núcleo, `trace` de la stdlib. El motor concretamente: 89,9 % → 92,8 % |
| 9 | Documentación fiel al código | 5 | **8** | Se corrigieron 5 afirmaciones de `ARQUITECTURA.md` que el código había dejado atrás (ver §4) |
| 10 | Trazabilidad de la agronomía | 3 | **3** | **Sin cambio, a propósito.** Ver §6 |

### Filas que suben: qué se hizo, qué evidencia hay, qué limitación queda

**1. Robustez.** Once bloques seguidos mutaban las mismas tres variables (`clave`,
`estado`, `motivo`); para saber qué hacía el séptimo había que haber leído los seis
anteriores. Hoy hay un contexto de sólo lectura (`_Ctx`), un juicio base exclusivo y
una lista de reglas. *Evidencia:* la métrica de complejidad (AST propio, medida antes
y después) y las pruebas de que ninguna regla puede tocar el contexto.
*Limitación:* la complejidad de `evaluar_parcela` volvió a subir a 12 al montarle
encima el pliegue de la persistencia. Es complejidad de bucle, no de agronomía, pero
está ahí.

**2. Mantenibilidad.** El orden de las reglas era la posición de las líneas; ahora es
una lista con nombres. *Evidencia:* dos reglas nuevas entraron después sin editar las
seis previas, y el fichero de oro dijo exactamente qué cambiaba cada una.
*Limitación:* sigue habiendo un dato que fluye de una regla a otra
(`_Diag.evento_explica`). Va explícito, pero es acoplamiento.

**3. Regresiones.** No había forma de saber si un cambio movía un veredicto.
*Evidencia:* el barrido se generó de las propias tablas de fases, incluye bloques que
se pegan a ±0,005 de cada umbral, y se **probó que falla**: una perturbación de un
umbral mueve 121 casos (con el barrido grueso inicial movía 10 — por eso se rehizo).
*Limitación:* congela lo que el motor dice hoy, no lo que debería decir. Un error
agronómico congelado sigue siendo un error congelado.

**4. Estabilidad.** El semáforo oscilaba con una sola pasada. Se midió primero: con
ruido cero no cambia nunca; con ruido de ±0,03 oscila en el 45 % de los casos, y sólo
en una franja tan ancha como el ruido. *Evidencia:* 6.880 combinaciones y 282 series.
*Limitación:* un deterioro real se avisa **una pasada más tarde** (~5 días). Es el
precio, y se pagó a sabiendas: k=3 quitaba más ruido (92 %) pero en la prueba de
deterioro real no llegaba a avisar en ocho pasadas.

**5. Transparencia.** Todos los veredictos se presentaban con la misma rotundidad.
*Evidencia:* la nota de fiabilidad se validó contra pruebas de vuelco empíricas
(98 % sensibilidad, 93 % precisión) y **no cambió ni un veredicto**: 0 de 3.499.
*Limitación:* el margen (`MARGEN_FILO = 0,03`) sale del ruido medido en un juego de
datos; en otra instalación puede no ser el mismo. Se remedia con `medir_ruido.py`.

**6. Datos incoherentes.** Ninguna regla comparaba nunca contra el techo de la fase:
un NDVI de 0,85 en nascencia se juzgaba «OK». *Evidencia:* los dos niveles salen de
las tablas que ya existen, sin una sola constante inventada. *Limitación:* sólo cubre
extensivos. En leñosos el techo depende del marco y de la copa, y no hay tabla que dé
un imposible fiable.

**7. Piezas opcionales.** *Evidencia:* la prueba de borrar los 12 a la vez, que hasta
esta auditoría **no pasaba** (el botón «Copias» lanzaba `ModuleNotFoundError`).
*Limitación:* la comprobación es manual; sólo la parte de `copias` tiene prueba
automática.

**8. Cobertura.** Subió poco y es honesto decirlo: +1,2 puntos globales. El grueso
está en el motor (+2,9). *Limitación:* `calibracion_umbrales` (70,7 %) y
`heterogeneidad_espacial` (71,8 %) siguen siendo los flojos, y `descargar_mapa_*` no
tiene cobertura ninguna porque necesita credenciales.

**9. Documentación.** *Evidencia:* las cinco correcciones están en §4 de este informe,
cada una comprobable ejecutando la medida. *Limitación:* nada impide que vuelva a
desincronizarse. Sólo el empaquetado tiene trinquete automático.

### La fila que no sube, y por qué

**10. Trazabilidad de la agronomía.** Se estudió marcar los ~599 números de
`fenologia_especies` con su procedencia y se decidió **no hacerlo**. Las medidas:
son 599 valores, no ~400; en 820 líneas hay 5 menciones de procedencia y hablan de
*qué fase es crítica*, no de umbrales sueltos; la cabecera del fichero ya declara la
incertidumbre en prosa y ya distingue bibliografía de derivado; y el conocimiento es
**de grupo**, no de número, así que 599 casillas repetirían la misma frase. Marcarlas
todas como «estimado» habría sido **menos preciso** que los comentarios que ya hay.
Queda documentado como deuda deliberada en `ARQUITECTURA.md` §8.2, con la forma
reducida que sí tendría valor (procedencia por grupo + trinquete).

---

## 2. Métricas

| Métrica | Antes (`fa19d7b`) | Después (`5f731f6`) | Cómo se mide |
|---|---|---|---|
| Pruebas sin pantalla | 837 | **958** (+121) | `python3.12 pruebas.py` |
| Tiempo de la suite | 4,65 s | **12,2 s** | `time python3.12 pruebas.py` |
| Pruebas de interfaz | verdes | **verdes** | `xvfb-run -a python3.12 pruebas_interfaz.py` |
| Fichero de oro | no existía | **3.499 casos, 13 bloques** | `python3.12 pruebas_oro.py` |
| Cobertura del núcleo (8 módulos) | 86,1 % | **87,3 %** | `trace` de la stdlib |
| Cobertura del motor | 89,9 % | **92,8 %** | ídem |
| `evaluar_parcela` | CC 108 / 346 líneas / 48 locales | **CC 12 / 55 / 6** | contador AST propio |
| Funciones con CC > 20 (árbol) | 20 | **20** | ídem |
| CC medio (árbol) | 5,5 | **5,5** | ídem |
| Cambios de semáforo (282 series ruidosas) | 623 | **140** (−78 %) | estudio de la fase 3 |
| Retardo del aviso | 0 pasadas | **+1 pasada** (~5 días) | ídem |
| Módulos | 48 / ~17.100 líneas | **49 / ~18.000** | `wc -l *.py` sin `pruebas*` |
| Esquema de la base | v11 | **v11** | `almacen.ESQUEMA_VERSION` |
| pyflakes | limpio | **limpio** | `python3.12 -m pyflakes *.py` |

Sobre las dos métricas que **no** mejoran: el número de funciones con CC > 20 se queda
en 20 y el CC medio en 5,5. No es un empate casual: salió `evaluar_parcela` (108) y
entró `medir_ruido.informe` (24), que es una herramienta de diagnóstico opcional que
imprime un informe y no forma parte del programa. Prefiero decirlo así a presentar un
«20 → 19» que no significaría nada. Los otros 19 (los constructores de PDF/Excel de
`informe_anual`, `separacion_copa_cubierta`, `interpretar_radar`) siguen igual: no
eran el objetivo de este plan.

**El tiempo de suite se triplica.** Lo paga entero el fichero de oro (3.499
evaluaciones completas del motor). 12 segundos sigue siendo una suite que se ejecuta
en cada cambio sin pensárselo, así que se acepta.

### Regresiones detectadas y veredictos cambiados

El fichero de oro se auditó fase a fase antes de regenerarlo. Esto es lo que movió
cada una, medido sobre el propio histórico del `.json`:

| Fase | Casos | Veredictos cambiados | Motivos cambiados |
|---|---|---|---|
| 2 — tubería de reglas | 3.493 → 3.499 | **0** | **0** |
| 3 — persistencia k=2 | 3.499 | 27 | 27 |
| 4 — plausibilidad | 3.499 | 44 | 111 |
| 5 — fiabilidad | 3.499 | **0** | 1.343 |
| 7 — auditoría | 3.499 | **0** | **0** |

La fila que importa es la primera: **el refactor grande no cambió ni un veredicto ni
un texto**. Las otras tres cifras distintas de cero son cambios buscados (§3).

Además, durante el trabajo el barrido destapó tres errores **míos** antes de que
llegaran a nada: un barrido demasiado grueso para notar un cambio de umbral, un
estudio de retardo que medía a través de un cambio de fase (el umbral se movía con el
valor), y un desfase de uno que hacía que k=2 y k=3 se comportaran igual. También una
expectativa de prueba mal puesta (`0,55*0,8 = 0,44000000000000006`, así que NDVI 0,44
cae en `Revisar`, no en `Vigilar`): se corrigió la prueba a la verdad medida y se
**documentó el borde de coma flotante** en vez de «arreglarlo», para que nadie mueva
veredictos sin querer.

---

## 3. Cambios deliberados

Cosas que un usuario nota, hechas a propósito:

1. **El semáforo espera una segunda pasada** antes de cambiar (k=2). No se retiene
   `Sin dato`, `Segado`, `N.A.` ni nada marcado como `esperado`: eso son hechos, no
   ruido. Mientras espera, el motivo lo dice.
2. **Estado nuevo `Revisar datos`.** No es rojo: el cultivo puede estar perfecto, lo
   que no cuadra es el dato con la fase declarada. Va en ámbar en el panel y en el
   PDF, se ordena justo detrás de `Revisar`, **no entra** en el recuento de avisos
   agronómicos del informe anual y **no alimenta el aprendizaje**.
3. **Los veredictos ajustados llevan `*`** en la lista de parcelas, y el motivo dice
   a qué distancia del corte se decidió.
4. **El aprendizaje mira el estado crudo, no el mostrado.** Si mirase el retenido
   estaría aprendiendo del filtro en vez de del cultivo.
5. **El botón «Copias» no aparece** si el módulo opcional no está.
6. **`medir_ruido.py`**, herramienta nueva y borrable, para medir el ruido real de tu
   instalación en vez de fiarte del ±0,03 medido aquí.

## 4. Cambios que NO deben haber ocurrido — confirmación

Comprobado con `git diff fa19d7b..HEAD`:

- **`fenologia_especies.py`: 0 líneas modificadas.** Ni un umbral, ni una fase, ni un
  `ndmi_min`, ni un mes de leñoso.
- **`cultivo.py`: 0 líneas.**
- **`almacen.py`: 0 líneas.** `ESQUEMA_VERSION` sigue en **11**: ninguna tabla nueva,
  ninguna columna nueva, ninguna migración. Una base de 1.17.0 se abre en 1.21.1 sin
  tocarla, y al revés.
- **Ningún dato nuevo se guarda en disco.** Las claves nuevas del diagnóstico
  (`estado_crudo`, `clave_cruda`, `confirmando`, `ajustado`) viven sólo en memoria: el
  diagnóstico **nunca se persiste, se recalcula**.
- **`contraste_indices.py`:** el único cambio es sacar a `_mes_de` una guarda que
  estaba duplicada dos veces con su comentario. Salida del motor **idéntica**: 3.499
  casos sin una sola diferencia.
- **El fichero de oro no se regeneró nunca para tapar nada.** Cada regeneración fue
  precedida de auditar el diff caso a caso, y las cifras están en la tabla de arriba.
- **No se inventó ni una cita ni una constante.** Los dos niveles de plausibilidad
  salen de las tablas que ya existían; el margen de fiabilidad, del ruido medido.

### Lo que la auditoría destapó y arregló

1. **El botón «Copias» reventaba** si se borraba el módulo opcional `copias`: el
   manejador importaba `ui_copias` **al pulsar**, no al cargar. Había un invariante
   escrito en `ARQUITECTURA.md` que no se cumplía.
2. **`Revisar datos` salía en tinta normal en el PDF anual** mientras el panel lo
   pinta en ámbar. El informe es el papel que se archiva.
3. **`medir_ruido` no viajaba en `pip install .`**: faltaba en `py-modules`. Se
   encontró a mano, así que se dejó un **trinquete** que lo impide en adelante —y se
   comprobó que el trinquete falla al quitar un módulo, porque un trinquete que nunca
   salta no es una prueba.
4. **Cinco afirmaciones de `ARQUITECTURA.md` que el código había dejado atrás:** la
   tubería tiene 9 reglas y decía 7; `evaluar_parcela` está en CC 12 y decía 4;
   49 ficheros y ~18.000 líneas, no 48 y ~17.100; el grafo tiene **una** arista hacia
   atrás diferida a propósito (`calibracion_umbrales` → motor) y decía «sin ciclos» a
   secas; y faltaban `ui_copias` y `version` en la tabla de módulos.
5. **Una duplicación** de 7 líneas con su comentario de 4, en `contraste_indices`.

### Abstracciones repasadas una a una

Las 19 piezas nuevas de las fases 1–5 tienen usuario real; ninguna quedó huérfana. Las
cinco de una sola llamada (`_retiene`, `_distancia_al_corte`, `_sequia_comarcal`,
`_fase_en_duda`, `_indice_de_juicio_lenoso`) se conservan porque **nombran una
decisión** —`_retiene` es una línea, pero es la línea donde se discute qué se retiene
y qué no— y no porque acorten nada. No se creó ninguna capa, ningún registro de
plugins, ninguna clase base: las reglas son funciones sueltas en una lista.

---

## 5. Deuda pendiente

Por orden de valor, tal como queda en `ARQUITECTURA.md` §8:

1. **Auditoría agronómica.** Todo lo revisado ha sido *código*. Queda contrastar los
   umbrales contra bibliografía y contra coherencia interna. Saldrían **propuestas**,
   no cambios: mover un `msavi_min` desplaza el diagnóstico de todas las parcelas de
   esa especie, incluidas las ya validadas. Y no se puede contrastar contra campo:
   eso lo dicen las validaciones del agricultor.
2. **Procedencia de los ~599 números** (§6 de este informe).
3. **La gráfica de radar tiene doble eje Y** (dB contra adimensional). Lo correcto
   serían dos paneles apilados; es una decisión de presentación agronómica, no se tocó.
4. **`descargar_mapa_*` sin cobertura** (necesita credenciales).
5. 🔴 **El `LICENSE` no tiene titular.** Sigue diciendo `Copyright (c) 2026 <TU
   NOMBRE>`. Mientras sea un hueco, la licencia MIT no cede derechos de nadie y el
   proyecto no es legalmente redistribuible. **Lo rellena el autor**: no es un dato
   deducible del repositorio.

Además, fuera de `ARQUITECTURA.md`: quedan ~350 textos visibles para el usuario sin
acentuar, y no existe un `CLAUDE.md` en el repositorio.

---

## 6. Qué NO se hizo, y por qué

- **Fase 6 (procedencia número a número): saltada por decisión del autor**, tras
  presentarle la medida. Documentada como deuda deliberada, no como olvido.
- **No se tocó la agronomía.** Era la primera regla del plan y se cumplió: el diff de
  `fenologia_especies.py` está vacío.
- **No se reescribió el programa.** El diff son 6.442 líneas añadidas, de las cuales
  4.235 son el fichero de oro y su generador, y 695 son pruebas. El código de
  producción que cambió cabe en `interpretacion_fenologica.py` (+1.016, casi todo
  comentario y reglas nuevas) y cuatro ficheros más con menos de 45 líneas cada uno.
