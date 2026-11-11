# Plan de implementación: ARES-X v1.1

Spec: `SPEC.md` (aprobado el 2026-11-10). Lista de tareas: `tasks/todo.md`.

## Resumen

Nueve cambios (F1 a F9) sobre la app existente. Cuatro tocan el motor Python (F3, F4, F6, F8, F9) y se hacen con
test primero; el resto es del panel (`web/index.html`) y se verifica en Chrome. Cada tarea deja la app funcionando
y termina con un commit local. No se hace `git push` sin preguntar, porque publica en producción.

## Decisiones de arquitectura

- **Efectos con duración (F8, F4):** se reutiliza el diccionario `timers` de la misión (`storm`, `link`, `vibration`) y se agregan `heat` y `wind`. Los multiplicadores de consumo se aplican en `cell_cost`, que ya usan el planificador, el supervisor y el movimiento, así el presupuesto de energía sigue siendo coherente.
- **Métricas por evento (F4):** un contador por tipo de evento y un contador de pasos en espera dentro de `metrics`; salen en `summary()`, en el estado del panel y en las exportaciones.
- **Replanificación inmediata (F9):** `inject()` llama a `_plan()` en el momento para los eventos perceptibles, en vez de dejar `replan_reason` para el paso siguiente. Los peligros ocultos no cambian.
- **Eventos aleatorios (F3):** generador propio (`default_rng(seed + 101)`), independiente del ruido de sensores, para que activar eventos no altere las lecturas. `event_rate` vale 0 por defecto en el motor; el servidor local, el `Dashboard` de Colab y la versión web crean la sesión con 0,03.
- **Destino (F6):** el AG ya acepta un parámetro `goal`. Con un destino fijado, se planifica con `goal = destino`; al llegar se borra el destino y se vuelve al objetivo normal. Así el AG sigue siendo causal y el supervisor no cambia.
- **Alertas (F2):** se construyen en el panel a partir de la bitácora que ya envía el motor (eventos nuevos y motivo de cada decisión). El motor solo agrega el origen del evento (`operador` o `aleatorio`).
- **Viaje (F1), bandera (F5) y velocidad (F7):** solo panel. La animación es un canvas 2D superpuesto al mapa; la bandera es una textura generada por código.

## Lista de tareas

### Fase 1 · Panel sin riesgo
- [x] T1 (F7): velocidad base y multiplicadores
- [x] T2 (F5): bandera de Chile

### Punto de control A
- [x] Sin scroll ni errores de consola; revisión visual

### Fase 2 · Eventos en el motor
- [x] T3 (F8): ola de calor
- [x] T4 (F4): métricas por evento en el motor
- [x] T5 (F4): métricas por evento en el panel
- [x] T6 (F9): replanificación inmediata

### Punto de control B
- [x] Suite completa y barrido de 20 semillas con eventos

### Fase 3 · Eventos vivos y alertas
- [ ] T7 (F3): eventos aleatorios en el motor
- [ ] T8 (F3): control en el panel y valor por defecto 3 %
- [x] T9 (F2): alertas sobre el mapa

### Punto de control C
- [ ] Misión automática con eventos aleatorios y alertas, revisada en Chrome

### Fase 4 · Control del operador y cierre
- [x] T10 (F6): destino en el motor
- [x] T11 (F6): destino en el panel
- [x] T12 (F1): animación de viaje
- [x] T14 (F10): vista 2D y 3D
- [x] T15 (F11): terreno con forma de superficie planetaria
- [x] T16 (F12): ediciones del operador visibles
- [x] T17 (F13): varios destinos con el mejor orden de visita
- [ ] T13: documentación, notebook, sitio y verificación final

### Punto de control final
- [ ] Criterios de éxito del spec cumplidos; preguntar antes de publicar

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| F4 cambia los resultados del escenario "eventos" de los experimentos (el sismo ahora resta integridad) | Medio | Es consecuencia de efectos ya aprobados. Se vuelve a correr el barrido de 20 semillas y se informan los números nuevos. |
| F9 replanifica dos veces (al inyectar y otra vez en el paso) | Medio | `inject` limpia `replan_reason` al planificar; un test cuenta las ejecuciones del AG. |
| Los eventos aleatorios rompen la reproducibilidad | Alto | Generador propio con semilla; test de traza idéntica con la misma semilla y test de traza sin cambios con tasa 0. |
| Un destino deja al rover sin energía para volver | Alto | Se valida ida más retorno antes de aceptar; el supervisor conserva `R06` y `R07`. |
| Una ola de calor aleatoria en Venus termina la misión | Bajo | Comportamiento decidido. La alerta crítica lo explica. |
| Replanificar con el AG en cada evento se nota lento en la versión web (Pyodide) | Medio | Se mide en el punto de control C; si molesta, se informa antes de ajustar. |
| Las alertas tapan la barra de estado o los botones de cámara | Bajo | Franja centrada con ancho máximo; se revisa en 1366×768. |
| `web/index.html` ya supera las 700 líneas | Bajo | Una tarea a la vez sobre ese archivo, nunca en paralelo. |

## Preguntas abiertas

Ninguna. Las decisiones del spec están cerradas.
