# ARES-X · Rover autónomo de exploración planetaria

Prototipo académico de **IA híbrida** (RNA + lógica difusa + algoritmo genético) con un supervisor de seguridad,
ejecutable de principio a fin en **Google Colab gratuito con CPU**. La interfaz es un centro de control de misión
que ocupa **una sola pantalla, sin scroll**.

> Simulación ficticia con parámetros astronómicos de referencia. Todo valor operacional (consumos, umbrales, daños,
> temperaturas internas) es un **supuesto de simulación**, no una especificación de ingeniería espacial.

## Instalación desde cero

### Opción A: Google Colab (recomendada)
1. Subir `ARES_X_Rover.ipynb` a Colab.
2. `Entorno de ejecución → Ejecutar todas`. No requiere GPU, claves ni pagos (numpy, pandas, matplotlib, scikit-learn).
3. El panel aparece en la sección 5. Cada botón ejecuta el motor Python del cuaderno a través de
   `google.colab.kernel.invokeFunction`.

El cuaderno es autocontenido: escribe sus propios módulos (`%%writefile`), genera su dataset sintético y no depende de
archivos locales.

### Opción B: local
```bash
python -m venv .venv
.venv/bin/pip install numpy pandas scikit-learn matplotlib pytest
.venv/bin/python server.py          # http://127.0.0.1:8765
.venv/bin/python -m pytest -q       # 458 pruebas (~16 min; incluye pruebas de navegador con Chromium y Node)
.venv/bin/python build_notebook.py  # regenera ARES_X_Rover.ipynb desde src/ y web/
.venv/bin/python build_site.py      # regenera site/ (versión web con Pyodide, la que publica Vercel)
```

## Semilla de demostración
`Marte · rover · semilla 42 · dificultad media · batería 100 % · política Híbrido completo`.
Guion de 6–8 minutos: iniciar → inyectar **Barranco** (se detiene antes, veto `R04`, replanifica) → **Tormenta de polvo**
(baja visibilidad y velocidad) → **Falla de sensor** (degradación `R13`) → pestañas Laboratorio RNA / Difuso / Genético →
Comparación de políticas con 5 semillas → exportar CSV/JSON.

## Uso del panel
| Zona | Contenido |
|---|---|
| A · Telemetría | Batería, integridad, riesgo, temperaturas, presión, pendiente, proximidad, visibilidad, estado de sensores y enlace. |
| Mapa | Vista 3D o 2D; cámaras seguir, general y cenital; «ocultos» revela lo que el rover aún no descubrió; alertas sobre el mapa; línea de tiempo para repetir la misión. Ruta ejecutada y planificada, refugios, sitios científicos, destinos y ediciones del operador. |
| C · Control de misión | Planeta, modo, política, semilla, dificultad, batería, duración de paso, **eventos aleatorios (0–10 %, 3 % por defecto)**; iniciar, paso, reiniciar, velocidad; carrera de fantasmas; dron explorador; 14 eventos inyectables; destinos del rover; edición del terreno real; exportar CSV/JSON. |
| D · Red neuronal | Predicción en vivo de la celda siguiente o modo prueba con valores editables. |
| E · Lógica difusa | Membresías, reglas activas, agregación y centroide (en vivo o de prueba). |
| F · Algoritmo genético | Ejecuciones y generaciones del AG, cromosomas, fitness, operadores y pesos configurables. |
| G · Bitácora | Decisiones filtrables (vetos, AG, eventos; los aleatorios se marcan «(aleatorio)») y comparación de políticas con n semillas. |

## Arquitectura
`src/ares/`: `PlanetProfile` (planet.py), `World`, `SensorSuite`, `Event`, `MissionLogger`, `NeuralPerception`,
`FuzzyController`, `GeneticPlanner`, `SafetySupervisor`, `HybridMission`, `experiments`, `api.Session` y `Dashboard`.

Ciclo por paso: `observar → validar_sensores → predecir_riesgo_rna → inferir_control_difuso →
replanificar_ag_si_corresponde → aplicar_restricciones → ejecutar_accion → actualizar_mundo → registrar_traza`.

- **RNA**: MLP (32,16) ReLU con softmax (libre/obstáculo/barranco) en scikit-learn. Datos sintéticos etiquetados por el
  simulador y particionados **por mapa**. Mira dos celdas adelante y alimenta el mapa de riesgo del AG y el veto del supervisor.
- **Difuso**: 4 variables con 3 conjuntos cada una (triangulares y trapezoidales), 12 reglas Mamdani min–max y
  centroide. Fija la velocidad, que se traduce en 0, 1 o 2 celdas por paso y en el consumo de energía.
- **AG**: 3 puntos de paso con reparación, población 30, 30 generaciones, torneo, cruce, mutación, elitismo y parada
  temprana. Familias integradas: laberinto (factibilidad) y viajero (orden de visita científica).
- **Supervisor**: prioridades deterministas R00–R16. Primero las prohibiciones físicas y luego las propuestas de IA.
  Veta las rutas que cruzan un barranco confirmado.
- **No omnisciencia**: el rover planifica sobre un mapa creído; barrancos y ~30 % de obstáculos están ocultos.

## Límites del modelo
- Física en cuadrícula 16×12 con movimiento a 4 vecinos; sin dinámica continua.
- La RNA aprende de datos sintéticos del propio simulador: su alta exactitud no se traslada a sensores reales.
- La temperatura interna se modela como 20 °C + 0,1·(T_ext − 20 °C) y el límite térmico es configurable (70 °C por defecto).
- Los gigantes gaseosos solo admiten el modo sonda atmosférica virtual: el modo ruedas se bloquea con una explicación.
- La señal biológica es una anomalía simulada y **nunca confirma vida**. Los alienígenas son un evento narrativo ficticio.

## Registro de supuestos de simulación
| Supuesto | Valor |
|---|---|
| Mapa / refugios / sitios científicos | 16×12; refugio base (0,0) + 1 lejano; 5 sitios |
| Peligros ocultos | 4 barrancos (6 en experimentos), 30 % de obstáculos |
| Consumo por celda | 0,45·(0,7 + 0,6·v)·(1 + 0,5·(1 − visibilidad)) + 0,01·pendiente |
| Recarga solar / en refugio | +0,12·visibilidad por paso de día / +6 por paso |
| Ciclo día/noche | 30 pasos; noche → visibilidad 0,6 |
| Tormenta / falla de sensor / pérdida de enlace | 15 / 8 / 10 pasos |
| Colisión | −25 % de integridad; caída en barranco = pérdida del rover |
| Instrumentación | 3 cajas por mapa; son objetivos del planificador junto con los sitios científicos; cada una recuperada suma +5 % de batería |
| Duración de paso | 0,5–3 s configurable; escala el tiempo transcurrido y la energía por celda |
| Umbral RNA | confianza ≥ 0,65 para vetar; riesgo = 0,7·p(obstáculo) + p(barranco) |
| Margen de retorno | se vuelve al refugio cuando energía de retorno × 1,25 ≥ batería |
| Corrosión en Venus | −0,4 % de integridad por paso |
| Eventos aleatorios | Probabilidad por paso 0–10 % (3 % en el panel, 0 % en motor, experimentos y tests); generador propio derivado de la semilla; tipo elegido por pesos según el planeta (p. ej. tormenta de polvo en Marte, corrosión y ola de calor en Venus); sin barrancos en modo sonda |

Referencias de contraste: NASA Planetary Fact Sheet y NASA Science (temperaturas del sistema solar, Venus y Marte).
