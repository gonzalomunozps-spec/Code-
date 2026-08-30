# Manual de usuario — Gestor de Parcelas

Guía breve para usar el programa en el día a día. No hace falta saber programar.

---

## 1. Qué es

Un programa de escritorio para **seguir el estado de tus parcelas con imágenes
de satélite** (Sentinel-2 y Sentinel-1 de Copernicus). Para cada parcela calcula
índices de vegetación (NDVI y otros), estima la fase del cultivo y avisa cuando
algo se sale de lo normal. Todo se guarda en tu equipo.

---

## 2. Primeros pasos

### Instalar
- **Con instalador:** ejecuta `python instalar.py`. Crea un acceso directo en el
  escritorio y prepara todo. Para desinstalar, `python desinstalar.py`.
- **Sin instalar:** ejecuta `python iniciar.py` para abrirlo directamente.

### Conectar con el satélite (Earth Engine)
Descargar imágenes necesita una cuenta de Google Earth Engine (gratuita para uso
académico y de investigación):
1. Abre la pestaña **«Credenciales»**.
2. Sigue las instrucciones para autorizar Earth Engine.
3. (Opcional) Si quieres interpretaciones redactadas con IA, pega tu clave de
   OpenAI ahí mismo. Se guarda **cifrada** en el llavero del sistema.

Sin Earth Engine el programa se abre igual y puedes consultar lo ya descargado;
solo no podrás bajar imágenes nuevas.

---

## 3. Dar de alta una parcela

Pulsa **«+ Nueva parcela»** (abajo a la derecha) y rellena:

- **Nombre** y **propietario**.
- **Geometría**, de una de estas formas:
  - **Por SIGPAC:** teclea los códigos (provincia, municipio, polígono, parcela,
    recinto) y pulsa «Capturar recinto SIGPAC».
  - **Dibujándola:** haz clic en el mapa para marcar los vértices. El dibujo a
    mano **manda** sobre lo capturado por SIGPAC.
- **Tipo y especie:** extensivo (con fecha de siembra), leñoso (con marco de
  plantación) o barbecho.
- **Margen interior** (opcional): descarta los píxeles del borde, mezclados con
  caminos o linderos. 15 m por defecto.
- **Arbolado disperso** (dehesa, encinas): márcalo para que el análisis no
  confunda los árboles con el cultivo herbáceo.

### Integrales térmicas (grados-día) — opcional
Si defines una integral térmica, la fase del cultivo la marca la **temperatura
acumulada** y no el calendario (más fiable en años fríos o cálidos):

- **Cero vegetativo:** se rellena solo al elegir el cultivo; puedes cambiarlo.
- **Método de cálculo:** tiempo térmico (el habitual), directo, exponencial o
  heliotérmico.
- **Desde / Hasta:** entre qué dos fases se cuenta. Ofrece todas las fases de la
  especie.
- **Valor (°C·día):** si mides tú el GDD entre dos estados, escríbelo aquí. Si
  encadenas tramos desde la siembra, **tus valores mandan** sobre los de tabla.

---

## 4. La ficha de la parcela

Doble clic en una parcela para abrir su ficha. De arriba a abajo:

- **Tabla de pasadas y mapa:** cada fecha con imagen, y el mapa del índice
  elegido. Botones para acercar, alejar y **comparar** dos fechas.
- **Gráfica de índices:** la evolución de NDVI y los demás a lo largo de la
  campaña. Marca o desmarca los índices que quieras ver.
- **Interpretación automática:** el estado del cultivo (OK / Vigilar / Revisar),
  la fase y el porqué. Puedes **confirmarlo** o **corregirlo** (el programa
  aprende de tus correcciones).
- **Zonas (heterogeneidad):** si dentro de la parcela hay un rodal que va peor,
  lo señala.
- **Validación con observaciones de campo:** lo que anotes a pie de finca sirve
  para medir cuánto acierta el sistema (ver punto 6).
- **Cuaderno de campo:** apunta tratamientos, riegos, siegas y cosechas.
- **Clima y grados-día:** el tiempo de la comarca y la integral térmica.

### Sincronizar
- **«↻ Sincronizar Copernicus»** (en la ficha) baja las pasadas nuevas de esa
  parcela.
- **«↻ Sincronizar ahora»** (abajo) lo hace para todas.
- **«📡 Sentinel-1 (radar)»** baja radar, que atraviesa nubes.

---

## 5. Cuaderno de campo y rendimientos

En la ficha, sección **«Cuaderno de campo»**:

- **Producto:** nombre, objetivo y dosis. Puedes pedir un día de informe para
  medir su efecto sobre el cultivo (doble clic en el evento para verlo).
- **Cosecha / Siega:** anota el rendimiento de báscula (kg/ha), humedad de grano
  y superficie. Admite **fechas de campañas anteriores**: cada dato se archiva en
  su año.

---

## 6. Observaciones de campo (medir el acierto)

Botón **«🔬 Observación de campo»** en la cabecera de la ficha. Anota lo que ves
de verdad: fase observada, rendimiento medido, humedad de sonda o un dato de dron
multiespectral. Elige la fecha en que tomaste el dato.

El programa **guarda esas observaciones como verdad-terreno** y las compara con
lo que había predicho, para darte una nota de acierto (matriz de fases, error del
GDD, correlación índice-rendimiento). No cambia el diagnóstico: solo lo mide.

---

## 7. Campañas

- El selector de campaña (abajo) cambia el año agrícola que se ve.
- **«⏲ Campañas anteriores»** (en la ficha) baja varios años de golpe.
- **«🗑 Borrar campaña»** elimina un año concreto (con doble confirmación). La
  parcela y sus otras campañas no se tocan.

---

## 8. Informes

En la ficha, **«📄 Informe / Exportar»**:

- **Informe de balance (PDF):** resumen de la campaña. Puedes **elegir qué
  secciones** incluir.
- **Informe técnico (PDF):** el detalle.
- **Hoja de cálculo (Excel):** índices por mes y gráficas.

---

## 9. Copias de seguridad 🛡

**Importante:** todos tus datos viven en una sola base de datos. Haz copias.

- El programa guarda una **copia automática** cada vez que lo abres (si no hay
  una reciente).
- Botón **«🛡 Copias»** (abajo) para:
  - **Crear copia ahora.**
  - **Restaurar** una copia anterior (antes guarda una de los datos actuales, por
    si acaso).
  - **Exportar a…** un pen-drive o carpeta de red.

Si cambias de equipo, exporta una copia y restáurala en el nuevo.

---

## 10. Problemas frecuentes

- **«earthengine-api no disponible»:** falta configurar Earth Engine en la
  pestaña «Credenciales», o no hay conexión a internet.
- **No aparecen imágenes nuevas:** puede que no haya pasadas del satélite sin
  nubes en esas fechas. Prueba con el radar (Sentinel-1), que atraviesa nubes.
- **El clima es igual en dos parcelas cercanas:** es normal. El dato de clima es
  de comarca (un píxel de 11 km), no de parcela.
- **Se llenó el disco:** borra imágenes de la caché (se vuelven a descargar
  solas); tus datos y copias no se tocan.

---

*Para dudas sobre la arquitectura interna del programa, ver `ARQUITECTURA.md`.*
