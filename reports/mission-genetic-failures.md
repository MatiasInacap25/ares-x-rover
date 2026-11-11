# Informe de fallos: Control de misión → Algoritmo genético

Fecha: 2026-11-11. Estado: tres defectos confirmados y corregidos el 2026-11-11.

## Resumen

| ID | Fallo | Severidad estimada |
| --- | --- | --- |
| F01 | El fitness histórico cambia al avanzar la misión. | Media |
| F02 | El minimapa pierde las rutas al seleccionar una ejecución histórica. | Media |
| F03 | Una política sin AG conserva la etiqueta de generación anterior. | Baja |

Las severidades corresponden a la consistencia y trazabilidad de F. No se
demostró que estos defectos causen movimientos inseguros del rover.

## F01 · Las generaciones históricas no conservan sus evaluaciones

### Reproducción y evidencia

1. Crear una misión híbrida con semilla `42`.
2. Consultar `ga_generation` para la ejecución `0`, generación `5`.
3. Ejecutar `step` con `n=20` desde la misma sesión.
4. Consultar nuevamente la misma ejecución y generación.

Las ocho filas devueltas cambiaron. En la primera, el cromosoma permaneció
idéntico, pero se observaron estos valores:

| Campo | Antes | Después |
| --- | --- | --- |
| Fitness de la fila | 1.7114 | 0.9614 |
| Componente científico | 0.75 | 0.50 |
| Mejor fitness histórico registrado | 1.7114 | 1.7114 |

**Esperado:** consultar una ejecución archivada debe conservar sus evaluaciones
originales, independientemente del progreso posterior de la misión.

**Impacto:** el detalle de cromosomas puede contradecir la curva histórica y el
mejor fitness registrado. La inspección deja de ser reproducible.

### Causa y recomendación

[`ga_generation`](../src/ares/mission.py#L555) reconstruye el contexto histórico
a partir de la creencia **actual** y restaura solamente los obstáculos y
barrancos antiguos. No conserva todo el estado utilizado al evaluar la generación.

El [cálculo científico](../src/ares/genetic.py#L171) depende de
`science_sites - visited_science`; las visitas posteriores alteran la recompensa
de cromosomas históricos. Debe conservarse el contexto completo de la evaluación
o sus resultados originales, sin consultar el estado actual para reconstruirlos.

## F02 · La ejecución histórica no dibuja sus rutas

### Reproducción y evidencia

1. Iniciar una misión híbrida con semilla `42`: F muestra rutas en su minimapa.
2. Inyectar **Tormenta de polvo** desde C para generar una nueva ejecución.
3. Seleccionar la ejecución `0` en el selector de F.

Los datos de candidatas y cromosomas siguen disponibles, pero el minimapa dibuja
**cero segmentos de ruta**. El test observa las llamadas reales de dibujo de
Chromium, sin sustituir el resultado del planificador.

**Esperado:** al inspeccionar una ejecución anterior, sus rutas deben seguir
siendo visibles o debe indicarse explícitamente que no están disponibles.

**Impacto:** no es posible contrastar visualmente las candidatas históricas con
su tabla de fitness.

### Causa y recomendación

La [rama de dibujo histórico](../web/index.html#L814) pasa siempre `null`
a la función que dibuja rutas:

```javascript
P(cnd.science_order && cnd.chromosome ? null : null);
```

Ambas ramas de la expresión producen `null`. Deben conservarse y exponerse las
rutas originales de cada ejecución para dibujarlas con su contexto histórico.

## F03 · Etiqueta de generación obsoleta al desactivar el AG

### Reproducción y evidencia

1. Con una misión híbrida, observar una generación en F.
2. Seleccionar **Sin AG** (`sin_ag`) o **Control** (`control`) en C.
3. Pulsar **Aplicar configuración**.

El selector informa que no hay ejecuciones y se limpian los cromosomas y las
operaciones, pero la etiqueta conserva valores de la ejecución anterior, como
`14/14` o `0/14`.

**Esperado:** mostrar una etiqueta vacía, no disponible o equivalente cuando
no existen generaciones del AG.

**Impacto:** el panel presenta una generación que ya no pertenece a la misión
actual. El problema se reprodujo con ambas políticas.

### Causa y recomendación

En [`gaGen()`](../web/index.html#L795), la rama sin ejecuciones limpia `gaChrom`
y `gaOps`, pero retorna sin limpiar `gaGenLbl`. Debe actualizarse también esa
etiqueta y cualquier indicador de selección que no corresponda al estado actual.

## Correcciones aplicadas

| ID | Corrección |
| --- | --- |
| F01 | Cada ejecución del AG guarda los sitios científicos ya visitados al planificar; `ga_generation` los restaura al reevaluar, así la recompensa científica es la original. |
| F02 | `ga_run` devuelve las rutas de las candidatas (`routes`) y el minimapa dibuja la elegida y las demás de la ejecución seleccionada. |
| F03 | `gaGen()` también limpia la etiqueta de generación («—») cuando no hay ejecuciones del AG. |

Verificación: `tests/test_panel_c_genetic.py`, 61 aprobados, incluida la
verificación en Chromium real; y un test nuevo de API en
`tests/test_panel_e_states.py` que comprueba que una ejecución histórica conserva
sus rutas.

## Base de prueba y cobertura

Se capturó una copia aislada del estado de trabajo para preservar cambios locales
ajenos. Posteriormente se verificó que los archivos de aplicación de esa copia
coinciden con los del commit `7ae6eed`, creado durante la verificación. Las
referencias de línea corresponden a esa base. Las modificaciones de aplicación
y las pruebas ajenas añadidas posteriormente no se incorporaron a la copia.

SHA-256 del manifiesto de `src/**/*.py`, `web/index.html` y `server.py`:

```text
8b948b1a60a615d722e500ef4630dd81e388e5b7622621d5b2edf1dacd5588da
```

Los tests cubren los controles de C: planetas y modos, políticas, valores
representativos de semilla/dificultad/batería, duraciones de paso, aplicación y
reinicio, fantasmas, dron, Paso, inicio/pausa, seis velocidades, eventos, destinos,
herramientas de terreno y exportaciones. En F se contrastan candidatas,
componentes de fitness, selección, generaciones y ejecuciones históricas.

En esta versión, **activar el dron no reinicia la misión**: se verifican la
conservación del plan y del historial al activarlo y desactivarlo. Una expectativa
inicial de reinicio se corrigió al contrastarla con el contrato vigente; no se
considera un fallo de la aplicación.

## Resultados finales

| Verificación | Resultado |
| --- | --- |
| Integración C → F, acumulando foco inicial y prueba nueva del dron | 59 aprobados; 1 fallido por F01 |
| Escenarios finales de navegador C → F | 47 aprobados; 3 fallidos por F02 y F03 |
| Revalidación limitada del dron y del navegador | 1 test aprobado; 1 fallido; 59 no seleccionados; 135,25 segundos |
| Suite integral sobre la copia aislada | Interrumpida con código 143; sin resumen final ni totales confiables |

El test de navegador agrupa los cincuenta escenarios: las dos políticas sin AG
reproducen F03 y la selección histórica reproduce F02. La prueba nueva del dron
y su escenario de navegador aprobaron con el contrato vigente de activación
sin reinicio. Los resultados iniciales que esperaban un reinicio del dron no se
atribuyen a un defecto de la aplicación.

La ejecución integral no completó su resumen. No se afirma que la suite completa
esté aprobada; queda pendiente repetirla si se necesita ese cierre. Tras la
interrupción se realizó solamente la revalidación focalizada indicada, sin
repetir toda la suite. Se verificó que el manifiesto de la aplicación aislada
permaneció sin cambios durante las pruebas.

## Alcance y limitaciones

- Se probó el dashboard local con el motor real y Chromium aislado; no el
  despliegue publicado ni su ejecución con Pyodide.
- No se probaron exhaustivamente todas las combinaciones de configuración.
- Los tests de destinos y terreno invocan `cellAction`; no verifican el clic 3D
  real ni su raycasting. Los selectores y botones usan sus eventos DOM reales.
- La exportación de comparación se verifica sin comparación previa: rechazo
  sin alterar F, no descarga exitosa.
- No se considera fallo que una ruta ignore un peligro todavía desconocido
  para el rover, ni que un paso no requiera una nueva ejecución del AG.
- No se modificaron los archivos de aplicación, cambios ajenos, commits ni
  despliegues como parte de esta verificación.

## Archivos y comandos

- [`tests/test_panel_c_genetic.py`](../tests/test_panel_c_genetic.py).
- [`tests/panel_c_genetic_browser.mjs`](../tests/panel_c_genetic_browser.mjs).

```bash
.venv/bin/python -m pytest tests/test_panel_c_genetic.py -q
.venv/bin/python -m pytest -q
```

Se requieren Chromium, Node con WebSocket integrado y permiso para iniciar un
servidor local.
