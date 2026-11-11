# Tareas: ARES-X v1.1

Spec: `SPEC.md` · Plan: `tasks/plan.md`

Comandos de verificación:
- Tests: `.venv/bin/python -m pytest -q`
- Panel local: `.venv/bin/python server.py --port 8765`
- Regenerar: `.venv/bin/python build_notebook.py && .venv/bin/python build_site.py`

---

## Fase 1 · Panel sin riesgo

- [x] **T1 (F7) · Velocidad base y multiplicadores**
  - Qué: cadencia base de 700 ms por paso; selector ×0,5, ×0,75, ×1, ×1,5, ×2, ×4; un paso por ciclo.
  - Aceptación: con ×0,5 pasan al menos 1,3 s entre pasos; con ×1, entre 0,6 y 0,9 s; el cambio se aplica sin reiniciar.
  - Verificar: medir en Chrome el intervalo entre dos pasos con ×0,5 y ×1.
  - Depende de: nada · Archivos: `web/index.html` · Tamaño: XS

- [x] **T2 (F5) · Bandera de Chile**
  - Qué: textura generada por código; bandera en mástil y en los costados del rover; en la góndola de la sonda.
  - Aceptación: se reconoce en las tres cámaras; no usa archivos externos.
  - Verificar: capturas en Chrome con cámara seguir, general y cenital, en Marte y en Júpiter.
  - Depende de: nada · Archivos: `web/index.html` · Tamaño: S

### Punto de control A
- [x] Página sin scroll y sin errores de consola
- [x] Commit local de T1 y T2

---

## Fase 2 · Eventos en el motor

- [x] **T3 (F8) · Ola de calor**
  - Qué: evento `ola_calor` de 12 pasos: +40 °C exterior, +35 °C en componentes, +20 % de consumo; botón y telemetría.
  - Aceptación: en Marte la velocidad difusa baja y la misión continúa; en Venus termina con `R01_LIMITE_TERMICO`; a los 12 pasos todo vuelve al valor previo.
  - Verificar: tests nuevos en rojo y luego en verde; suite completa.
  - Depende de: nada · Archivos: `src/ares/events.py`, `src/ares/mission.py`, `web/index.html`, `tests/test_h3_hybrid.py` · Tamaño: M

- [x] **T4 (F4) · Métricas por evento en el motor**
  - Qué: efectos numéricos de la tabla del spec (sismo, meteorito, señal biológica, alienígena, enlace, viento, falla de sensor); conteo por tipo y pasos en espera en `summary()` y en las exportaciones.
  - Aceptación: un test por evento muestra que su métrica cambia frente a la misma misión sin el evento; la señal biológica sigue sin afirmar vida.
  - Verificar: tests nuevos en rojo y luego en verde; suite completa.
  - Depende de: T3 · Archivos: `src/ares/mission.py`, `src/ares/api.py`, `tests/test_h3_hybrid.py` · Tamaño: M

- [x] **T5 (F4) · Métricas por evento en el panel**
  - Qué: filas de telemetría para vibración, viento, latencia de enlace y órdenes en cola, y contadores de eventos.
  - Aceptación: al inyectar cada evento, su valor cambia en pantalla en el mismo paso o el siguiente.
  - Verificar: en Chrome, inyectar sismo, viento, pérdida de enlace y señal biológica.
  - Depende de: T4 · Archivos: `web/index.html` · Tamaño: S

- [x] **T6 (F9) · Replanificación inmediata**
  - Qué: los eventos perceptibles (meteorito, sismo, viento, batería baja, ola de calor, tormenta) recalculan la ruta al inyectarse; los peligros ocultos no.
  - Aceptación: en pausa, un meteorito sobre la ruta cambia la ruta sin dar un paso; un barranco no la cambia hasta que el sensor lo confirma; el AG no corre dos veces por el mismo evento.
  - Verificar: tests nuevos en rojo y luego en verde; suite completa.
  - Depende de: T3, T4 · Archivos: `src/ares/mission.py`, `tests/test_h3_hybrid.py` · Tamaño: S

### Punto de control B
- [x] Suite completa en verde
- [x] Barrido de 20 semillas del escenario con eventos: híbrido con 0 violaciones de seguridad; informar los números nuevos
- [x] Commits locales de T3 a T6

---

## Fase 3 · Eventos vivos y alertas

- [ ] **T7 (F3) · Eventos aleatorios en el motor**
  - Qué: parámetro `event_rate` (0 a 0,10; 0 por defecto); sorteo por paso con generador propio; lista ponderada por planeta y modo; origen `aleatorio` en la bitácora.
  - Aceptación: misma semilla y tasa dan la misma traza; con tasa 0 la traza es idéntica a la actual; en 200 pasos al 5 % hay entre 2 y 25 eventos; nunca hay eventos inválidos para el modo ni con la misión terminada.
  - Verificar: tests nuevos en rojo y luego en verde; suite completa.
  - Depende de: T3, T4, T6 · Archivos: `src/ares/mission.py`, `tests/test_h3_hybrid.py` · Tamaño: M

- [ ] **T8 (F3) · Control en el panel y 3 % por defecto**
  - Qué: slider "Eventos aleatorios" (0 a 10 %); el servidor local, el `Dashboard` y la versión web arrancan con 3 %.
  - Aceptación: con 0 % no aparece ningún evento aleatorio; con 10 % aparecen en una misión automática; los tests siguen usando 0.
  - Verificar: en Chrome, misión automática con 10 % y con 0 %.
  - Depende de: T7 · Archivos: `web/index.html`, `server.py`, `src/ares/dashboard.py`, `build_site.py` · Tamaño: S

- [ ] **T9 (F2) · Alertas sobre el mapa**
  - Qué: franja superior con hasta 3 alertas, color por severidad, cierre automático a los 6 s y cierre manual para las críticas; fuentes: eventos, vetos y cambios de estado, fin de misión.
  - Aceptación: un barranco frente al rover muestra la alerta del evento y, al paso siguiente, la del veto `R04`; no hay scroll ni se tapan los controles de cámara.
  - Verificar: en Chrome a 1366×768 y a pantalla completa.
  - Depende de: T7 · Archivos: `web/index.html`, `src/ares/api.py` · Tamaño: M

### Punto de control C
- [ ] Misión automática con eventos aleatorios y alertas revisada en Chrome
- [ ] Medir cuánto tarda una replanificación en la versión web
- [ ] Commits locales de T7 a T9

---

## Fase 4 · Control del operador y cierre

- [x] **T10 (F6) · Destino en el motor**
  - Qué: comando para fijar destino; validación (fuera del mapa, obstáculo o barranco conocido, sin ruta, energía insuficiente para ir y volver); el AG planifica hacia el destino; al llegar se registra y la misión continúa.
  - Aceptación: un destino válido cambia la ruta y el rover pasa por la celda; sobre un barranco conocido devuelve error sin cambiar la ruta; con batería insuficiente se rechaza explicando que no hay retorno seguro.
  - Verificar: tests nuevos en rojo y luego en verde; suite completa.
  - Depende de: T6 · Archivos: `src/ares/mission.py`, `src/ares/api.py`, `tests/test_h3_hybrid.py` · Tamaño: M

- [x] **T11 (F6) · Destino en el panel**
  - Qué: herramienta "Fijar destino" con clic en el mapa 3D; marcador en 3D y en el minimapa; distancia restante en telemetría.
  - Aceptación: al hacer clic, la ruta se redibuja hacia el marcador; los rechazos muestran el mensaje del motor.
  - Verificar: en Chrome, fijar un destino válido y uno sobre un obstáculo.
  - Depende de: T10 · Archivos: `web/index.html` · Tamaño: S

- [ ] **T12 (F1) · Animación de viaje**
  - Qué: animación de unos 3 s sobre el mapa al cambiar a un planeta válido; se salta con un clic; no aparece en la primera carga ni con cambios inválidos.
  - Aceptación: tras la animación, planeta, terreno y telemetría son los del destino y la misión está en el paso 0; Júpiter con ruedas no anima.
  - Verificar: en Chrome, Marte a Venus, Marte a Júpiter con ruedas y saltar con clic.
  - Depende de: nada · Archivos: `web/index.html` · Tamaño: S

- [ ] **T13 · Documentación y verificación final**
  - Qué: actualizar `README.md` (eventos, supuestos nuevos, cantidad de tests); regenerar notebook y sitio; ejecutar el notebook completo.
  - Aceptación: los cuatro criterios de éxito del spec.
  - Verificar: suite completa; notebook ejecutado sin errores; versión web local carga y simula; página sin scroll a 1366×768 y 1920×1080.
  - Depende de: T1 a T12 · Archivos: `README.md`, `ARES_X_Rover.ipynb`, `site/` · Tamaño: S

- [x] **T14 (F10) · Vista 2D y 3D** (agregada el 2026-11-10 a pedido del usuario)
  - Aceptación: al cambiar de vista la misión conserva paso y ruta; un clic en 2D fija la misma celda que en 3D.
  - Verificado en Chrome. Archivos: `web/index.html`

- [x] **T15 (F11) · Terreno con forma de superficie planetaria**
  - Aceptación: horizonte curvo y ninguna zona fuera de la cuadrícula más alta que el mapa.
  - Verificado en Chrome (máximo dentro 0,86; máximo fuera −0,46). Archivos: `web/index.html`

- [x] **T16 (F12) · Ediciones del operador visibles**
  - Aceptación: un barranco colocado queda marcado sin activar "ocultos" y sin dar un paso.
  - Verificado en Chrome. Archivos: `web/index.html`

- [x] **T17 (F13) · Varios destinos con el mejor orden de visita** (agregada el 2026-11-11 a pedido del usuario)
  - Aceptación: el orden coincide con el óptimo exacto; el rover visita todos; el recorrido completo respeta la batería.
  - Verificado: 14 tests nuevos y prueba en Chrome con 4 destinos. Archivos: `src/ares/genetic.py`, `src/ares/mission.py`, `src/ares/api.py`, `web/index.html`

### Punto de control final
- [ ] Criterios de éxito del spec cumplidos
- [ ] Preguntar antes de `git push` (publica en producción)
