# Informe de fallos: Control de misión → Red neuronal

Fecha de verificación: 2026-11-11.
Estado: defecto confirmado y corregido el 2026-11-11.

Se confirmó un defecto visual reproducible mediante cuatro controles del panel C.
Los tests ejecutados no detectaron errores de cálculo neuronal.

## F01 · Entradas neuronales desactualizadas

**Severidad estimada:** media.

| Acción en C · Control de misión | Fallo observado en D · Red neuronal |
| --- | --- |
| Reiniciar | Conserva las seis entradas de la inferencia anterior. |
| Aplicar configuración | Conserva entradas de la misión previa. |
| Activar Carrera de fantasmas | Conserva entradas anteriores al reinicio. |
| Activar Dron explorador | Conserva entradas anteriores al reinicio. |

### Comportamiento esperado

En modo **En vivo**, cuando ya no existe una predicción, las entradas deben
limpiarse o identificarse claramente como no vigentes.

### Comportamiento actual

Desaparecen las probabilidades y la celda evaluada, pero permanecen los seis
valores anteriores: distancia, pendiente, desnivel, textura, visibilidad y vibración.

En la reproducción registrada permanecieron los valores
`9.74, 5.56, -0.23, 0.23, 1.00, 0.51`, respectivamente.

### Impacto

El panel D presenta un estado contradictorio: informa que no existe predicción,
pero mantiene entradas editables de una inferencia anterior. Esto puede hacer
interpretar datos históricos como lecturas actuales. No se demostró que este
defecto visual altere las decisiones del motor.

### Pasos para reproducir

1. Abrir el dashboard local y seleccionar la política híbrida.
2. Mantener el panel D en **En vivo**.
3. Pulsar **Paso** para obtener una predicción.
4. Ejecutar cualquiera de las cuatro acciones de la tabla.
5. Observar que desaparecen la predicción y la celda, pero permanecen las entradas.

### Causa confirmada

En [`web/index.html:713`](../web/index.html#L713), `renderNN()` actualiza las
entradas únicamente cuando `nnMode === 'live' && S.rna`. No contempla limpiarlas
cuando `S.rna` pasa a `null`.

### Corrección aplicada

- En **En vivo** sin predicción, `renderNN()` deja los seis campos vacíos con el
  marcador «—» y un aviso de que no hay predicción vigente.
- Los valores del modo **Prueba** se guardan aparte (`nnTestInputs`). Al pasar a
  Prueba, o al escribir en un campo vacío, los campos vacíos toman el último valor
  evaluado en Prueba (o los valores por defecto).
- Con una predicción vigente, escribir en un campo sigue partiendo de la lectura
  en vivo, como antes.

## Evidencia de tests

| Verificación | Resultado |
| --- | --- |
| Nuevos tests de integración con la API real | 58 aprobados |
| Escenarios en Chromium real | 43 aprobados; 4 fallidos por F01 |
| Suite completa de pytest | 251 aprobados; 1 fallido; 178.83 segundos |

El único test fallido de pytest agrupa los cuatro escenarios de navegador que
reproducen F01; no son cuatro defectos independientes.

Archivos de prueba:

- [`tests/test_panel_c_neural.py`](../tests/test_panel_c_neural.py).
- [`tests/panel_c_neural_browser.mjs`](../tests/panel_c_neural_browser.mjs).

Comandos para reproducir las verificaciones:

```bash
.venv/bin/python -m pytest tests/test_panel_c_neural.py -q
.venv/bin/python -m pytest -q
```

Los tests de navegador requieren Chromium, Node con WebSocket integrado y
permiso para iniciar un servidor local.

## Alcance y limitaciones

- Se verificó el dashboard local servido desde `web/index.html`.
- No se verificó el despliegue publicado ni su ejecución con Pyodide.
- Los tests de destinos y terreno invocan `cellAction`; no prueban la selección
  de celdas mediante clic 3D real y raycasting.
- La exportación de comparación se comprobó sin una comparación previa,
  verificando su rechazo y que no modifique D; no se probó su descarga exitosa.
- La corrección toca solo el panel (`web/index.html` y su copia en `site/`); el motor no cambió.

## Verificación de la corrección

`tests/test_panel_c_neural.py`: 59 aprobados, incluida la verificación en
Chromium real. Las cuatro reproducciones de F01 ya no fallan, y el escenario
«D Prueba remains independent of C and En vivo restores mission inference»
sigue aprobado.
