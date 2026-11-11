# Spec: ARES-X v1.1 — eventos vivos, alertas y control del operador

Estado: **borrador pendiente de aprobación**. No se implementa nada hasta que se apruebe.

## Objetivo

Hacer que la simulación ARES-X se sienta viva y que el operador tenga más control, sin romper lo que ya
cumple la pauta del PDF (integración causal RNA + difuso + AG, reproducibilidad por semilla, una sola pantalla).

Usuario: el estudiante que presenta la demo y el docente que la evalúa en vivo.

Ocho cambios pedidos:

| ID | Cambio | Dónde vive |
|---|---|---|
| F1 | Animación de viaje entre planetas | Panel |
| F2 | Sistema de alertas en la parte superior del mapa | Panel |
| F3 | Pequeña probabilidad de evento aleatorio en cada paso | Motor + panel |
| F4 | Cada evento se refleja en métricas, no solo en animaciones | Motor + panel |
| F5 | Rover personalizado con la bandera de Chile | Panel |
| F6 | Definir el punto hacia donde debe ir el rover | Motor + panel |
| F7 | Velocidad base más lenta en modo automático y opciones ×0,75 y ×0,5 | Panel |
| F8 | Nuevo evento: ola de calor | Motor + panel |
| F9 | La ruta se actualiza en el momento del evento, no en el paso siguiente | Motor |
| F10 | Cambiar entre vista 2D y 3D | Panel |
| F11 | Terreno con forma de superficie planetaria (curvo, sin cerros en los bordes) | Panel |
| F12 | Las ediciones del operador (barranco, obstáculo) se ven al colocarlas | Panel |

## Supuestos (corrígelos antes de aprobar)

1. **F3:** la probabilidad es del 3 % por paso, ajustable de 0 a 10 % con un slider. Está activa por defecto en el
   panel y **apagada (0 %)** en el motor, los experimentos y los tests, para no cambiar los resultados actuales.
2. **F3:** los eventos aleatorios usan un generador propio derivado de la semilla, así que la misma semilla y la
   misma probabilidad producen la misma secuencia de eventos.
3. **F6:** el destino es un punto de paso obligatorio. El rover va hasta ahí con el mismo ciclo híbrido, lo marca
   como alcanzado y después retoma la misión normal (objetivos pendientes y retorno al refugio).
4. **F7:** cada ciclo automático ejecuta un paso. La cadencia base pasa de 330 ms a 700 ms y el selector ofrece
   ×0,5, ×0,75, ×1, ×1,5, ×2 y ×4.
5. **F1:** la animación dura unos 3 segundos, se puede saltar con un clic y solo ocurre cuando el cambio de
   planeta es válido.
6. **F5:** la bandera se dibuja por código (sin archivos de imagen) y va en un mástil y en los costados del
   rover; en modo sonda va en la góndola.
7. **F8:** los valores de la ola de calor son supuestos de simulación ajustables, como el resto.

## Requisitos y criterios de aceptación

### F7 · Velocidad de simulación
- La cadencia base del modo automático es de 700 ms por paso.
- El selector de velocidad ofrece ×0,5, ×0,75, ×1, ×1,5, ×2 y ×4; la espera entre pasos es 700 ms dividido por el multiplicador.
- Cambiar la velocidad durante la ejecución se aplica en el paso siguiente, sin reiniciar la misión.
- **Aceptación:** con ×0,5 pasan al menos 1,3 s entre dos pasos consecutivos; con ×1, entre 0,6 y 0,9 s.

### F5 · Bandera de Chile
- El rover muestra la bandera chilena (franja blanca arriba, roja abajo, cantón azul con estrella blanca) en un mástil y en ambos costados del cuerpo.
- En modo sonda la bandera aparece en la góndola.
- **Aceptación:** la bandera se reconoce en las tres cámaras (seguir, general, cenital) y no depende de archivos externos.

### F8 · Evento ola de calor
- Nuevo evento `ola_calor`, con botón en el motor de eventos, válido en los ocho cuerpos.
- Dura 12 pasos. Mientras dura: temperatura exterior +40 °C, temperatura de componentes +35 °C y consumo por celda +20 % (refrigeración).
- La temperatura de componentes ya alimenta la lógica difusa, así que la ola de calor reduce la velocidad por la regla "temperatura caliente".
- Si la temperatura de componentes supera el límite térmico, el supervisor aplica `R01_LIMITE_TERMICO`.
- **Aceptación:**
  - en Marte, la velocidad difusa durante la ola es menor que antes de ella y la misión puede continuar;
  - en Venus, la ola supera el límite térmico y la misión termina en modo seguro con `R01`;
  - al terminar los 12 pasos, las temperaturas y el consumo vuelven a sus valores previos.

### F4 · Cada evento se refleja en métricas
Regla: todo evento debe cambiar al menos un valor numérico visible en telemetría y quedar contado en el resumen de misión.

| Evento | Hoy | Se agrega |
|---|---|---|
| Barranco | barrancos evitados | — |
| Batería baja | batería | — |
| Día / noche | potencia solar, visibilidad | — |
| Tormenta de polvo | visibilidad, potencia solar | — |
| Corrosión | integridad | — |
| Falla de sensor | lectura NaN | contador de pasos degradados |
| Sismo | solo espera | vibración en telemetría e integridad −3 % |
| Meteorito | riesgo en celdas vecinas | vibración en telemetría; integridad −5 % si cae a 1 celda o menos |
| Señal biológica | solo mensaje | contador de anomalías registradas y −1 % de batería por el análisis |
| Alienígena | obstáculo | contador de contactos ficticios |
| Pérdida de enlace | indicador | latencia de enlace (s) y órdenes en cola |
| Viento | espera en sonda; nada en rover | velocidad del viento (m/s) y consumo +30 % durante 5 pasos en ambos modos |
| Ola de calor | no existe | temperaturas y consumo (ver F8) |

- El resumen de misión y las exportaciones CSV/JSON incluyen el total de eventos, el conteo por tipo y los pasos perdidos en esperas.
- La señal biológica sigue sin afirmar vida.
- **Aceptación:** un test por evento comprueba que la métrica asociada cambia respecto de una misión idéntica sin el evento.

### F3 · Eventos aleatorios
- Nuevo parámetro `event_rate` (0 a 0,10). En cada paso, con esa probabilidad, ocurre un evento elegido de una lista ponderada según el planeta (por ejemplo, tormenta de polvo en Marte, corrosión en Venus, viento en modo sonda).
- No se generan eventos con la misión terminada ni eventos inválidos para el modo (barranco en sonda).
- Los eventos aleatorios se distinguen de los inyectados por el operador en la bitácora y en las alertas.
- El panel tiene un slider "Eventos aleatorios" con el porcentaje; 0 % los desactiva.
- **Aceptación:**
  - misma semilla y misma probabilidad producen la misma secuencia de eventos y la misma traza;
  - con `event_rate` 0 la traza es idéntica a la actual;
  - en 200 pasos con 5 %, la cantidad de eventos queda entre 2 y 25.

### F2 · Alertas sobre el mapa
- Una franja en la parte superior del mapa 3D muestra hasta 3 alertas apiladas, con color por severidad (información, advertencia, crítica).
- Generan alerta: todo evento (inyectado o aleatorio), los vetos y cambios de estado del supervisor (barranco confirmado, peligro RNA, retorno por energía, refugio inalcanzable, sensores fallidos, daño crítico, límite térmico) y el fin de misión.
- Cada alerta dice qué pasó y qué hizo el rover, y desaparece sola a los 6 segundos; las críticas quedan hasta que el operador las cierra.
- La franja no agrega scroll de página ni tapa los controles de cámara.
- **Aceptación:** inyectar un barranco frente al rover muestra primero la alerta del evento y, en el paso siguiente, la del veto `R04`.

### F6 · Destino definido por el operador
- Nueva herramienta "Fijar destino": el operador hace clic en una celda del mapa 3D (o del minimapa) y esa celda pasa a ser el destino.
- El destino se marca en el mapa 3D y en el minimapa, y la telemetría muestra la distancia restante.
- El rover replanifica de inmediato con el AG. Al llegar, la bitácora registra "destino alcanzado" y la misión continúa con los objetivos pendientes y el retorno.
- Se rechaza con un mensaje legible si la celda está fuera del mapa, es un obstáculo o barranco conocido, no tiene ruta, o la energía no alcanza para ir y volver a un refugio.
- El supervisor conserva la última palabra: un destino nunca anula un veto de seguridad.
- **Aceptación:**
  - fijar un destino válido cambia la ruta planificada y el rover pasa por esa celda;
  - fijar un destino sobre un barranco conocido devuelve un error y no cambia la ruta;
  - con batería insuficiente, se rechaza explicando que no hay retorno seguro.

### F9 · Replanificación inmediata tras un evento
- Hoy un evento solo marca que hay que replanificar y la ruta nueva aparece recién en el paso siguiente. Con F9, la ruta se recalcula y se redibuja en el mismo momento en que ocurre el evento, sin esperar un paso.
- Aplica a los eventos que el rover percibe al instante: meteorito, sismo, viento, batería baja, ola de calor, tormenta de polvo y el destino fijado por el operador (F6).
- **No aplica a peligros ocultos** (barranco, alienígena, obstáculo colocado a mano): el rover no es omnisciente y los descubre con sus sensores cuando se acerca, igual que hoy. Su ruta cambia cuando los detecta.
- La replanificación inmediata queda registrada en la bitácora con el paso en que ocurrió y cuenta como una ejecución del AG.
- Un evento aleatorio (F3) ocurre dentro de un paso, así que su replanificación se resuelve en ese mismo paso.
- **Aceptación:**
  - con la misión en pausa, inyectar un meteorito sobre la ruta cambia la ruta planificada sin dar ningún paso;
  - inyectar un barranco no cambia la ruta hasta que el sensor de borde lo confirma;
  - la traza sigue siendo reproducible con la misma semilla y la misma secuencia de eventos.

### F10 · Vista 2D y 3D
- Un selector "2D / 3D" en los controles de cámara cambia la vista del mapa sin reiniciar la misión.
- La vista 2D es un mapa cenital plano con los mismos elementos que la 3D: relieve, obstáculos, barrancos, riesgo RNA, sitios científicos, instrumentos, refugios, ruta planificada, recorrido, candidatas del AG, destino y rover.
- Las herramientas de clic (editar terreno, fijar destino) funcionan igual en las dos vistas.
- **Aceptación:** al cambiar de 3D a 2D y volver, la misión conserva su paso y su ruta; un clic en 2D con "Fijar destino" fija la misma celda que mostraría la 3D.

### F11 · Terreno con forma de superficie planetaria
- El terreno se curva como la superficie de un planeta: cae suavemente hacia el horizonte en todas las direcciones y ya no tiene cerros levantados en los bordes del mapa.
- El relieve interno se suaviza; los barrancos siguen viéndose como depresiones.
- No cambia el motor: la cuadrícula, las alturas y las rutas son las mismas.
- **Aceptación:** en la vista general se ve el horizonte curvo y ninguna zona fuera de la cuadrícula queda más alta que el mapa.

### F12 · Ediciones del operador visibles
- Un barranco u obstáculo colocado por el operador se marca en el mapa (2D y 3D) en el momento, con un contorno propio, aunque el rover todavía no lo haya detectado.
- El mensaje de confirmación indica la celda y que el rover debe descubrirlo con sus sensores.
- **Aceptación:** tras colocar un barranco, la celda queda marcada sin activar "ocultos" y sin dar ningún paso.

### F13 · Varios destinos con el mejor orden de visita
Agregado el 2026-11-11 a pedido del usuario; amplía F6.
- El operador puede fijar hasta 8 destinos. Un clic sobre un destino ya fijado lo quita; «Quitar todos» los borra.
- El orden de visita lo decide un AG de permutaciones (familia viajero) que minimiza las celdas del recorrido completo, incluido el retorno al refugio más cercano. Con la misma semilla da el mismo orden.
- Criterios: el orden coincide con el óptimo exacto en las pruebas (hasta 7 paradas); el rover pasa por todos los destinos; un destino que se cruza de camino cuenta como visitado; un destino que encarece el recorrido más allá de la batería se rechaza con «no hay retorno seguro».
- El panel numera los destinos en orden de visita y dibuja el recorrido entre ellos en 2D y 3D.
- Límite conocido: el orden es óptimo en distancia sobre el mapa creído; cada tramo lo planifica el AG de rutas, que puede desviarse a sitios científicos.

### F14 · Carrera de fantasmas (modo activable)
Agregado el 2026-11-11 a pedido del usuario.
- Botón «Carrera de fantasmas». Al activarlo la misión se reinicia y las otras políticas (sin RNA, sin difuso, sin AG; el híbrido si el rover usa una ablación) corren el mismo mapa y la misma semilla, paso a paso junto al rover.
- Los eventos, las ediciones de terreno y los destinos del operador se aplican a todos los corredores.
- Se dibujan translúcidos con su recorrido en 2D y 3D, y un marcador muestra batería, ciencia y estado. Al terminar todos, se ordena por misión cumplida, ciencia, batería y colisiones.
- Criterio: con el modo apagado, la traza y el estado son idénticos a los de antes.

### F15 · Repetición con línea de tiempo
- Barra bajo el mapa con deslizador, paso anterior, paso siguiente y «En vivo». Al retroceder, todo el panel muestra ese paso y una tarjeta explica la decisión: código de motivo, acción, explicación, RNA, velocidad difusa, batería y eventos.
- Cualquier acción de simulación (paso, iniciar, reiniciar, evento) vuelve al presente.
- Límite conocido: la historia vive en el navegador; al recargar la página empieza desde el paso actual.

### F16 · Dron explorador
- Parámetro `drone` (apagado por defecto; con él apagado la traza no cambia). Botón «Dron explorador» en el panel. Se activa y apaga en caliente (cambio del 2026-11-11 a pedido del usuario): la misión conserva paso y ruta, el cambio queda en la bitácora y la exportación con su paso, se aplica también a los fantasmas y se mantiene al reiniciar.
- Supuestos de simulación: en cada paso revisa las 4 celdas siguientes de la ruta y sus vecinas, y agrega al mapa creído los barrancos y obstáculos reales que ve; si alguno está en la ruta, se replanifica con motivo `DRON_DETECTA_PELIGRO`. Cada vuelo cuesta 0,08 % de batería del rover.
- Queda en tierra con tormenta de polvo, viento fuerte o batería bajo 15 %. No existe en modo sonda.
- Criterio: un barranco oculto en la ruta se descubre antes del veto `R04`; 0 violaciones de seguridad. Medido en 20 semillas con 6 barrancos ocultos: pasos 38,3 → 36,7, replanificaciones 4,45 → 3,65, vetos R04 0,55 → 0, batería final 73,9 % → 69,8 %.

### F1 · Viaje entre planetas
- Al elegir un planeta distinto y válido, se muestra una animación de unos 3 segundos sobre el área del mapa: el planeta de origen se aleja, una nave cruza el espacio y aparece el planeta de destino; después se muestra el terreno nuevo.
- Un clic salta la animación.
- Si el cambio es inválido (gigante gaseoso con ruedas), no hay animación y se muestra la explicación actual.
- **Aceptación:** tras la animación, el planeta, el terreno y la telemetría corresponden al destino, y la misión queda en el paso 0.

## Orden de construcción

`F7, F5` (solo panel, sin riesgo) → `F8` → `F4` → `F9` → `F3` (depende de F4, F8 y F9) → `F2` (depende de F3) → `F6` (usa F9) → `F1`.

## Stack

Sin cambios ni dependencias nuevas: Python 3 con numpy, pandas y scikit-learn en el motor; HTML, canvas 2D y
Three.js r128 (CDN) en el panel; Pyodide 0.27.7 en la versión web.

## Comandos

```bash
.venv/bin/python -m pytest -q          # suite completa (hoy 131 tests)
.venv/bin/python server.py --port 8765 # panel local en http://127.0.0.1:8765
.venv/bin/python build_notebook.py     # regenera ARES_X_Rover.ipynb
.venv/bin/python build_site.py         # regenera site/ (versión web con Pyodide)
git push origin main                   # despliega solo a https://ares-x-rover.vercel.app
```

## Estructura del proyecto

```
src/ares/mission.py     → ciclo híbrido, eventos, destino (F3, F4, F6, F8)
src/ares/events.py      → catálogo de eventos (F8)
src/ares/supervisor.py  → prioridades y códigos de motivo
src/ares/api.py         → comandos JSON que usa el panel (F3, F4, F6)
web/index.html          → panel de una sola pantalla (F1, F2, F5, F7 y la vista de F3, F4, F6, F8)
tests/test_h3_hybrid.py → tests de integración y de eventos
site/, ARES_X_Rover.ipynb → generados; no se editan a mano
```

## Estilo de código

Identificadores y comentarios en inglés, textos visibles en español, valores operacionales como constantes con nombre
marcadas como supuesto, y errores de entrada como `ValueError` con mensaje legible.

```python
HEAT_WAVE_STEPS = 12          # duration of a heat wave (supuesto)

def inject(self, kind, **data):
    if self.finished:
        raise ValueError('La misión ya terminó: reinicie para inyectar eventos.')
```

## Estrategia de pruebas

- **Motor (F3, F4, F6, F8):** test primero con pytest, por la interfaz pública (`HybridMission`, `Session.dispatch`). Cada regla nueva tiene su test y se observa fallar antes de implementarla.
- **Regresión:** los 131 tests actuales siguen pasando; con `event_rate` 0 las trazas no cambian.
- **Panel (F1, F2, F5, F7):** verificación en Chrome sobre el servidor local: sin scroll de página, sin errores de consola, y los criterios de aceptación de cada punto.
- **Barrido:** 20 semillas del escenario con eventos para confirmar que el híbrido mantiene 0 violaciones de seguridad.

## Límites

- **Siempre:** correr la suite antes de cada commit; regenerar notebook y sitio cuando cambie el motor o el panel; mantener todo en una pantalla sin scroll de página; mantener la reproducibilidad por semilla.
- **Preguntar antes:** agregar dependencias; cambiar valores por defecto que alteren los resultados de los experimentos; hacer `git push` (publica en producción).
- **Nunca:** borrar o desactivar tests para que pasen; afirmar vida en la señal biológica; permitir que un destino o un evento salte un veto del supervisor; subir credenciales.

## Criterios de éxito

1. Los criterios de aceptación de F1 a F8 se cumplen.
2. La suite completa pasa, con tests nuevos para F3, F4, F6 y F8.
3. La página sigue sin scroll y sin errores de consola en 1366×768 y 1920×1080.
4. El notebook se ejecuta completo y la versión web carga y simula.

## Preguntas abiertas

1. **F9:** ¿la interpretación es correcta (la ruta se actualiza en el momento del evento, no en el paso siguiente)?
2. **F9:** los peligros ocultos (barranco, alienígena, obstáculo manual) no replanifican al instante para no volver omnisciente al rover. ¿De acuerdo?

## Decisiones tomadas (2026-11-10)

- **F10, F11, F12:** agregados a pedido del usuario durante la fase 2. "Plano u ovalado" se resuelve como superficie curva tipo planeta. El destino (F6) se adelanta antes que los eventos aleatorios.
- **F8:** en Venus la ola de calor termina la misión en modo seguro por límite térmico (el margen es de 5,6 °C). Se deja así.

- **F3:** 3 % por paso, activo por defecto en el panel. Aprobado.
- **F6:** al llegar al destino la misión continúa con los objetivos pendientes y el retorno. Aprobado.
- **F4:** efectos numéricos por evento aprobados tal como están en la tabla.
- **F1:** la animación de viaje no aparece en la primera carga de la página; solo al cambiar de planeta.
