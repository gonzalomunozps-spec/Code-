# Registro de cambios

Se sigue [Keep a Changelog](https://keepachangelog.com/es/) y
[SemVer](https://semver.org/lang/es/).

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
