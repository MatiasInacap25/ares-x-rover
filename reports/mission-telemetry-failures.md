# Informe de fallos: Control de misión → Telemetría

Fecha: 2026-11-11. Panel objetivo: **A · Telemetría**, no el mapa vecino.
Estado: dos problemas de presentación confirmados y corregidos el 2026-11-11.

## Resumen

| ID | Fallo | Severidad estimada |
| --- | --- | --- |
| F01 | El valor de presión usa bar mientras su etiqueta indica Pa. | Baja |
| F02 | Las lecturas ausentes reciben estados NOMINAL o ALERTA. | Media |

La API devuelve correctamente valores numéricos o `null` según corresponda.
No se demostró que estos problemas alteren el cálculo del motor o el movimiento.

## F01 · Unidades de presión contradictorias

### Reproducción y evidencia

1. Seleccionar **Tierra** o **Venus** desde C, con modo rover.
2. Ejecutar **Paso**.
3. Leer la fila **Presión** de A.

| Planeta probado | Valor mostrado | Etiqueta de unidad |
| --- | --- | --- |
| Tierra | `1.0 bar` | `Pa · referencia` |
| Venus | `92.0 bar` | `Pa · referencia` |

**Esperado:** la etiqueta y el valor deben utilizar una unidad coherente.

**Impacto:** la fila mezcla dos unidades. Esto dificulta interpretar o comparar
las magnitudes, aunque no demuestra un error en la conversión aritmética.

### Causa y recomendación

En [`renderTelemetry()`](../web/index.html#L662), la fila de presión conserva
la etiqueta fija `Pa · referencia`, pero convierte el valor a bar cuando
`T.pressure >= 100000`.

La etiqueta debe acompañar la unidad elegida para el valor, o debe mantenerse
una sola unidad en toda la fila. No se requiere modificar la presión del motor.

## F02 · Estados de salud sin una lectura disponible

### Reproducción y evidencia

1. Con la política híbrida en Marte, ejecutar **Paso** para obtener lecturas.
2. Pulsar **Reiniciar**, **Aplicar configuración** o **Carrera de fantasmas**.
3. Inspeccionar A antes del siguiente paso.

La misión vuelve al paso cero y la API deja las lecturas sin muestra en `null`.
El valor visible es `—`, pero los siguientes indicadores reciben estos estados:

| Indicador | Valor | Estado mostrado |
| --- | --- | --- |
| Radiación (índice) | `—` | `NOMINAL` |
| Pendiente | `—` | `NOMINAL` |
| Proximidad | `—` | `NOMINAL` |
| LIDAR / borde | `—` | `NOMINAL` |
| O₂ almacenado | `—` | `NOMINAL` |
| Potencia solar | `—` | `ALERTA` |

**Esperado:** distinguir una muestra pendiente de una lectura válida nominal,
baja o defectuosa. La ausencia de una medición no debe generar por sí misma
una advertencia por potencia medida insuficiente.

**Impacto:** A presenta una alerta sin lectura solar y no distingue claramente
la disponibilidad de los demás datos. No se afirma que el motor invente muestras
ni que se haya detectado una avería real en el hardware simulado.

### Causa y recomendación

Las filas de [`renderTelemetry()`](../web/index.html#L662) clasifican valores
sin comprobar previamente si existe una muestra. En particular, la condición
`T.solar_power < 1` resulta verdadera para `null`, produciendo `ALERTA`.
Otras filas utilizan `ok` directamente o lo toman como valor por defecto.

Comprobar primero la disponibilidad y mostrar un estado explícito, por ejemplo
**SIN DATOS** o **PENDIENTE**. Después de una muestra válida, conservar las
clasificaciones normales; una falla de sensor confirmada debe seguir diferenciada.

## Correcciones aplicadas

| ID | Corrección |
| --- | --- |
| F01 | La etiqueta de la fila **Presión** usa la misma unidad que el valor: `bar · referencia` desde 100 000 Pa y `Pa · referencia` por debajo. |
| F02 | Las filas que dependen de una lectura de sensor (temperatura exterior, O₂ exterior y almacenado, presión, radiación, pendiente, proximidad, LIDAR y potencia solar) muestran `—` con el estado **SIN DATOS** cuando no hay muestra. Con una muestra válida se mantienen las clasificaciones normales, y una falla de sensor confirmada sigue mostrándose como **FALLA**. |

Verificación: `tests/test_panel_c_telemetry.py`, 63 aprobados, incluida la
verificación en Chromium real.

## Cobertura

Se contrastaron los **23 indicadores** con el motor real, además del nombre,
modo, gravedad y estado ambiental del encabezado de A.

- Ocho planetas, modos y seis políticas.
- Valores representativos de semilla, dificultad y batería; seis duraciones de paso.
- Aplicación, reinicio, fantasmas, dron, Paso, inicio/pausa y seis velocidades automáticas.
- Catorce eventos y fallo total de navegación, incluidos sus efectos inmediatos
  sobre batería, integridad, ambiente, enlace, contadores y validez de sensores.
- Destinos y edición de terreno mediante clics nativos CDP en el mapa **2D**,
  verificando que la celda seleccionada sea la esperada y que A se actualice.
- Exportaciones sin modificar A; determinismo con la misma semilla y secuencia.

Se respetó el contrato de muestreo: un evento puede actualizar el estado actual
sin volver a medir los sensores hasta el próximo paso. Ese desfase, por sí solo,
no se clasificó como un fallo.

## Base y resultados

Las pruebas usan una copia aislada para preservar los cambios locales ajenos.
Los archivos de aplicación capturados coincidieron posteriormente con el commit
`96a6675`. No se incorporan modificaciones ni pruebas nuevas posteriores a la copia.

SHA-256 del manifiesto de `src/**/*.py`, `web/index.html` y `server.py`:

```text
bb4c379367ab76a40fec3f0951e4e8f1453cf057f795e66968083f9eb35a97f2
```

| Verificación focalizada | Resultado |
| --- | --- |
| Tests de integración con la API real | 62 aprobados |
| Escenarios de Chromium | 51 aprobados; 5 fallidos |
| Pytest C → A | 62 aprobados; 1 fallido; 249,76 segundos |
| Excepciones JavaScript no capturadas durante la prueba | 0 |
| Clics nativos 2D para destinos y terreno | Ambos escenarios aprobados |

El único test fallido de pytest agrupa los escenarios de navegador. Dos casos
reproducen F01 y tres reproducen F02; no son cinco defectos independientes.

### Suite integral

**447 tests aprobados y 1 fallido en 665,67 segundos (11 minutos y 5 segundos).**
El único test fallido es el agregado de navegador C → A y reproduce los mismos
cinco escenarios de F01/F02. No hubo tests omitidos ni verificaciones interrumpidas.

La ejecución integral utilizó los archivos finales de prueba. Su proceso de
navegador dispone de un límite de 360 segundos, ajustado después de observar el
tiempo de la ejecución focalizada, sin cambiar ninguna aserción funcional.
En esta segunda ejecución también aprobaron 51/56 escenarios y ambos casos de
clic nativo 2D; no se registraron excepciones JavaScript no capturadas.

## Limitaciones y alcance

- Se verificó el dashboard local, no el despliegue publicado ni Pyodide.
- No se probaron exhaustivamente todas las combinaciones de configuración.
- Se usaron clics nativos sobre el mapa 2D; no se verificó el raycasting 3D.
- No se realizó una auditoría visual píxel a píxel del icono planetario.
- Las descargas se bloquearon en Chromium para evitar archivos fuera del entorno
  de prueba. Se comprobó que exportar no altere A, no el guardado físico del archivo.
- La exportación de comparación se probó sin una comparación previa: se verificó
  el rechazo sin alterar A, no su descarga exitosa.
- No se modificó la aplicación ni se realizaron commits, publicaciones o despliegues
  como parte de esta verificación.

## Archivos y comandos

- [`tests/test_panel_c_telemetry.py`](../tests/test_panel_c_telemetry.py).
- [`tests/panel_c_telemetry_browser.mjs`](../tests/panel_c_telemetry_browser.mjs).

```bash
.venv/bin/python -m pytest tests/test_panel_c_telemetry.py -q
.venv/bin/python -m pytest -q
```

Se requieren Chromium, Node con WebSocket integrado y permiso para iniciar un
servidor local.
