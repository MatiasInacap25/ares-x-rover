# Informe de fallos: Control de misión → Lógica difusa

Fecha: 2026-11-11. Versión de referencia: `9775ad4`.
Estado: defecto confirmado y corregido el 2026-11-11.

## F01 · Una inferencia pendiente se presenta como lógica difusa desactivada

**Severidad estimada: media.** El panel E muestra información incorrecta sobre
la política activa, aunque no se demostró que esto altere el cálculo o el movimiento.

Con la política **Híbrido**, que sí utiliza lógica difusa, E muestra estos mensajes
cuando la misión está en el paso cero y todavía no existe una inferencia:

> desactivada en esta política

> Política sin lógica difusa: velocidad fija 0,50.

### Reproducciones confirmadas

| Estado o acción de C | Resultado incorrecto en E |
| --- | --- |
| Misión reiniciada, antes de ejecutar el primer paso | Informa que la lógica difusa está desactivada. |
| Reiniciar | Repite el mensaje de política sin lógica difusa. |
| Aplicar configuración | Repite el mensaje, aunque se mantiene la política híbrida. |
| Activar Carrera de fantasmas | Repite el mensaje tras reiniciar la misión principal. |
| Activar Dron explorador | Ya no aplica: desde `7ae6eed` el dron se activa sin reiniciar la misión. |

Son cinco escenarios de prueba del mismo defecto, no cinco errores independientes.

### Reproducción manual

1. Seleccionar la política híbrida y mantener E en **En vivo**.
2. Pulsar **Paso**: aparecen entradas, reglas activas y centroide.
3. Pulsar **Reiniciar**, **Aplicar configuración**, **Carrera de fantasmas** o
   **Dron explorador**.
4. Observar los mensajes citados, sin haber seleccionado una política sin difuso.
5. Pulsar **Paso** nuevamente: vuelve a mostrarse la inferencia difusa.

### Causa

[`renderFuzzy()`](../web/index.html#L759) usa la ausencia de `S.fuzzy` como si
demostrara que la política desactiva el controlador. Sin embargo, `S.fuzzy` también
es `null` después de reiniciar una política que sí lo utiliza.

El encabezado incorrecto está en [`web/index.html:760`](../web/index.html#L760)
y el mensaje de velocidad fija en [`web/index.html:780`](../web/index.html#L780).

### Comportamiento esperado

Distinguir tres estados: **inferencia disponible**, **inferencia pendiente** y
**controlador desactivado por la política**. Para una política habilitada en el
paso cero, mostrar un mensaje como «Sin inferencia todavía: ejecute un paso».
No afirmar que se utiliza velocidad fija por ausencia de una predicción.

## Corrección aplicada

- El estado del panel incluye `policy_uses` (`rna`, `fuzzy`, `ga`), tomado de la política activa.
- `renderFuzzy()` distingue tres estados: inferencia disponible; inferencia pendiente
  («Sin inferencia todavía: ejecute un paso.» en el paso cero, o «Sin inferencia
  difusa en este paso.» después); y controlador desactivado por la política, el
  único que muestra «desactivada en esta política» y la velocidad fija 0,50.
- Los tests de navegador ahora esperan la respuesta de `configure` al cambiar de
  planeta (el botón valida primero y configura después), y el escenario del dron
  comprueba que la misión y la inferencia de E se conservan.

Verificación: `tests/test_panel_c_fuzzy.py` y `tests/test_panel_e_states.py`, 66
aprobados, incluida la verificación en Chromium real.

## Cobertura y resultados

Los tests usan `Session.dispatch` con el motor real y Chromium con un perfil
temporal. No sustituyen las inferencias por respuestas simuladas.

- Configuración: ocho planetas, modos, seis políticas, semillas, dificultades,
  batería, duración de paso y dron, con valores representativos.
- Ejecución: Paso, inicio/pausa, seis velocidades automáticas y fantasmas.
- Eventos: los catorce eventos y el fallo total de navegación.
- Destinos y edición de terreno; exportaciones sin alterar E.
- Entradas, doce reglas, intensidades de activación, curva agregada, centroide,
  concordancia con evaluación manual y separación entre **Prueba** y **En vivo**.

## Resultados finales

| Verificación | Resultado |
| --- | --- |
| Nuevos tests de integración C → E | 58 aprobados |
| Escenarios de navegador C → E, ejecución final | 44 aprobados; 5 fallidos por F01 |
| Pytest focalizado C → E, ejecución final | 58 aprobados; 1 fallido; 112,98 segundos |
| Suite completa | 310 aprobados; 1 fallido; 289,39 segundos |

El único test fallido agrupa los escenarios de navegador. La suite completa
se ejecutó antes del último ajuste del test de coordenadas del gráfico: una
comparación exacta se reemplazó por una tolerancia de un píxel más el redondeo
de la interfaz. No se atribuye esa sensibilidad del test a un fallo de la aplicación.
Después se reejecutó toda la suite focalizada C → E: quedaron únicamente las
cinco reproducciones de F01. No se repitió la suite completa tras ese ajuste
exclusivamente de tests; no se modificó el motor ni la interfaz de la aplicación.

## Alcance y limitaciones

- Se probó el dashboard local de `web/index.html`, no el despliegue publicado
  ni su ejecución con Pyodide.
- Los destinos y las ediciones invocan `cellAction`; no se verificó el raycasting
  mediante clic 3D real. Los gráficos de E sí reciben eventos DOM de clic.
- La exportación de comparación se probó sin comparación previa: se verificó
  su rechazo sin alterar E, no una descarga exitosa.
- No se probaron exhaustivamente todas las combinaciones de configuración.
- La velocidad difusa es una propuesta previa al supervisor; una diferencia
  respecto a la velocidad ejecutada no se considera por sí sola un defecto.

## Archivos y comandos

- [`tests/test_panel_c_fuzzy.py`](../tests/test_panel_c_fuzzy.py).
- [`tests/panel_c_fuzzy_browser.mjs`](../tests/panel_c_fuzzy_browser.mjs).

```bash
.venv/bin/python -m pytest tests/test_panel_c_fuzzy.py -q
.venv/bin/python -m pytest -q
```

Se requieren Chromium, Node con WebSocket integrado y permiso para abrir un
servidor local.
