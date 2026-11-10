"""Build ARES_X_Rover.ipynb: a self-contained Colab notebook (sources embedded)."""
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parent
MODULES = ['__init__', 'planet', 'world', 'sensors', 'events', 'logger', 'state_machine', 'neural', 'fuzzy',
           'genetic', 'supervisor', 'mission', 'experiments', 'api', 'dashboard']
TESTS = sorted(p.name for p in (ROOT / 'tests').glob('test_*.py'))

md = nbf.v4.new_markdown_cell
code = nbf.v4.new_code_cell


def writefile(path, source):
    return code(f'%%writefile {path}\n{source}')


cells = [
    md("""# ARES-X · Rover autónomo de exploración planetaria
**IA híbrida: RNA + lógica difusa + algoritmo genético, con supervisor de seguridad.**

Simulación ficticia con parámetros astronómicos de referencia. Todo valor operacional es un *supuesto de simulación*.

**Cómo usar:** `Entorno de ejecución → Ejecutar todas`. CPU gratuita, sin GPU ni claves. El panel de control (sección 5)
ocupa una sola pantalla; cada botón ejecuta el motor Python de este cuaderno.

Flujo por paso: sensores con ruido → preprocesamiento → RNA (probabilidades) → difuso (velocidad/cautela) →
AG (rutas, solo ante objetivo/bloqueo/evento grave) → supervisor de seguridad → acción → física → bitácora."""),
    code("""# 0. Dependencias (todas gratuitas y preinstaladas en Colab)
import importlib, subprocess, sys
for pkg in ('numpy', 'pandas', 'sklearn', 'matplotlib'):
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'scikit-learn' if pkg == 'sklearn' else pkg], check=True)
import os
for folder in ('ares_x/src/ares', 'ares_x/web', 'ares_x/tests'):
    os.makedirs(folder, exist_ok=True)
print('Python', sys.version.split()[0])"""),
    md('## 1. Código modular\nClases `PlanetProfile`, `World`, `SensorSuite`, `NeuralPerception`, `FuzzyController`, '
       '`GeneticPlanner`, `SafetySupervisor`, `MissionLogger`, `HybridMission` y `Dashboard`, escritas como módulos dentro del cuaderno.'),
]
for name in MODULES:
    cells.append(writefile(f'ares_x/src/ares/{name}.py', (ROOT / 'src' / 'ares' / f'{name}.py').read_text(encoding='utf-8')))
cells += [
    md('Panel HTML (vista). La lógica no vive aquí: cada acción llama al motor Python mediante `google.colab.kernel.invokeFunction`.'),
    writefile('ares_x/web/index.html', (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')),
    code("""import sys, importlib
sys.path.insert(0, 'ares_x/src')
import numpy as np, pandas as pd, matplotlib.pyplot as plt
from ares.api import Session
from ares.mission import HybridMission, shared_perception, POLICIES
from ares.fuzzy import FuzzyController
from ares.genetic import GeneticPlanner
from ares.experiments import run_experiments, summarize
from ares.dashboard import Dashboard
print('Motor ARES-X cargado.')"""),
    md("""## 2. RNA — percepción (RF-04, CA-06)
Datos sintéticos etiquetados por el simulador (la verdad es la pertenencia de la celda a barranco/obstáculo, no la variable que recibe la red).
Partición **por mapa** en entrenamiento/validación/test para evitar fuga. MLP (32,16) ReLU con softmax de 3 clases."""),
    code("""perception = shared_perception(0)
report = perception.report_
print(f"Entrenamiento: {report['training_samples']} muestras · {report['iterations']} iteraciones · {perception.train_seconds_:.2f} s")
print('Mapas por partición:', report['split_maps'])
for split in ('validation', 'test'):
    m = report[split]
    print(f"{split:>10}: exactitud {m['accuracy']:.3f} | baseline mayoría {m['majority_baseline']:.3f} | macro-F1 {m['macro_f1']:.3f} | recall barranco {m['barranco_recall']:.3f} | ECE {m['calibration_error']:.3f}")
fig, ax = plt.subplots(figsize=(4, 3.4))
cm = np.array(report['test']['confusion_matrix'])
ax.imshow(cm, cmap='Blues'); ax.set_xticks(range(3), report['test']['labels']); ax.set_yticks(range(3), report['test']['labels'])
for i in range(3):
    for j in range(3):
        ax.text(j, i, cm[i, j], ha='center', va='center')
ax.set_xlabel('predicho'); ax.set_ylabel('real'); ax.set_title('Matriz de confusión (test)'); plt.show()
sample = dict(distance=.05, slope=30, elevation_delta=-10, texture=.3, visibility=.9, vibration=1.5)
pred = perception.predict(sample)
print('Lectura con caída de 10 m →', pred['label'], {k: round(v, 3) for k, v in pred['probabilities'].items()})"""),
    md("""## 3. Lógica difusa — control (RF-05, RF-06, CA-05)
Distancia (cerca/media/lejos), batería (crítica/baja/alta), pendiente (plana/media/fuerte) y temperatura; 10 reglas Mamdani min–max,
desfusificación por centroide. Sin reglas activas → salida documentada 0 (parar)."""),
    code("""fz = FuzzyController()
for rule in fz.rules:
    print(f"R{rule['id']:>2}: {rule['description']}")
for distance in (10, 1):
    out = fz.infer(distance, 60, 5, 12)
    active = ', '.join(f"R{r['id']}={r['strength']:.2f}" for r in out['activated_rules'])
    print(f"distancia {distance:>2} m → velocidad {out['speed']:.3f} · reglas activas: {active}")
fig, axes = plt.subplots(1, 2, figsize=(10, 2.8))
xs = np.linspace(0, 20, 201)
for label, spec in fz.membership_sets['distance'].items():
    axes[0].plot(xs, [fz.membership(x, spec) for x in xs], label=label)
axes[0].axvline(10, ls='--', c='k'); axes[0].axvline(1, ls=':', c='r'); axes[0].set_title('Distancia a riesgo (m)'); axes[0].legend()
for distance, style in ((10, '-'), (1, ':')):
    out = fz.infer(distance, 60, 5, 12)
    axes[1].plot(out['universe'], out['aggregated_curve'], style, label=f"{distance} m → centroide {out['centroid']:.2f}")
axes[1].set_title('Agregación y centroide (velocidad)'); axes[1].legend(); plt.show()"""),
    md("""## 4. Algoritmo genético — planificación (RF-07, CA-04)
Cromosoma: K=3 puntos de paso decodificados a una ruta contigua con reparación. Población 30, ≥30 generaciones, torneo, cruce, mutación,
elitismo 2, semilla controlada y parada temprana tras 10 generaciones sin mejora. Familias integradas: **laberinto** (factibilidad de ruta)
y **viajero** (orden de visita de sitios científicos)."""),
    code("""mission = HybridMission(seed=42)
mission.step()
ga = mission.ga
print(f"Generaciones: {ga['generations_run']} · parada temprana: {ga['stopped_early']} · pesos: {ga['weights']}")
for cand in ga['candidates']:
    print(f"#{cand['index']} fitness {cand['fitness']:+.3f} factible={cand['feasible']} componentes={cand['components']} orden={cand['science_order']}")
gen5 = mission.ga_generation(5, run=0)
print(f"Generación 5: torneos {gen5['tournaments']}, cruces {gen5['crossovers']}, genes mutados {gen5['mutations']}")
for row in gen5['rows'][:3]:
    print('  ', row['chromosome'], 'fitness', row['fitness'])
plt.figure(figsize=(6, 2.6))
plt.plot([h['best'] for h in ga['history']], label='mejor'); plt.plot([h['best_feasible'] for h in ga['history']], '--', label='mejor factible')
plt.xlabel('generación'); plt.ylabel('fitness'); plt.legend(); plt.title('Convergencia del AG'); plt.show()"""),
    md("""## 5. Centro de control de misión (una sola pantalla)
Panel A mapa y rutas · B telemetría · C decisión explicable por algoritmo · D traza filtrable/exportable · E controles y eventos.
Pestañas: Laboratorio RNA, Difuso, Genético y Comparación de políticas. Iniciar, pausar, paso a paso, reiniciar, velocidad,
inyectar eventos y editar el terreno real (clic en el mapa)."""),
    code("""dashboard = Dashboard(seed=42, planet='Marte', height=880)
dashboard.show()"""),
    md("""## 6. Experimentos: 20 semillas, ablaciones y baselines (RF-14, RF-15)
Mismas semillas y condiciones para cada política: control (ruta más corta sin riesgos), AG puro con riesgos fijos, híbrido completo y
ablaciones sin RNA / sin difuso / sin AG. Se reporta media, mediana y dispersión."""),
    code("""import time, json
results = {}
for scenario in ('estandar', 'eventos'):
    t0 = time.time()
    frame = run_experiments(seeds=20, scenario=scenario)
    results[scenario] = frame
    print(f"Escenario {scenario}: {len(frame)} misiones en {time.time() - t0:.1f} s")
    display(summarize(frame).round(3))
frame = pd.concat(results.values())
frame.to_csv('ares_x_experimentos.csv', index=False)
fig, axes = plt.subplots(1, 3, figsize=(13, 3))
for ax, metric in zip(axes, ('success', 'collisions', 'battery_left')):
    data = results['eventos'].groupby('policy')[metric].apply(list)
    ax.boxplot([data[p] for p in POLICIES], tick_labels=list(POLICIES)) if metric != 'success' else ax.bar(list(POLICIES), [np.mean(data[p]) for p in POLICIES])
    ax.set_title(metric + ' (eventos)'); ax.tick_params(axis='x', rotation=45)
plt.tight_layout(); plt.show()"""),
    code("""# Exportación de una misión completa (CSV de pasos + JSON con configuración, motivos y trazas) (RF-12)
demo = HybridMission(seed=42)
demo.step(); demo.inject('barranco'); demo.run()
open('ares_x_mision_semilla42.csv', 'w', encoding='utf-8').write(demo.export_csv())
json.dump(demo.export_json(), open('ares_x_mision_semilla42.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(demo.summary())
try:
    from google.colab import files  # descarga opcional en Colab
    print('Use files.download("ares_x_mision_semilla42.json") para descargar.')
except ImportError:
    pass"""),
    md('## 7. Pruebas automáticas\nCasos de borde (sección 12) y casos de aceptación CA-01…CA-08.'),
]
for name in TESTS:
    cells.append(writefile(f'ares_x/tests/{name}', (ROOT / 'tests' / name).read_text(encoding='utf-8')))
cells += [
    code("""import subprocess, sys
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'pytest'])
result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--color=no', '-p', 'no:cacheprovider', 'ares_x/tests'], capture_output=True, text=True)
print(result.stdout[-2500:] or result.stderr[-2500:])"""),
    md("""## 8. Conclusiones, límites y supuestos
- **Integración causal:** las pruebas de causalidad muestran que alterar solo la salida de la RNA, del difuso o del AG cambia la decisión o el
  movimiento; el supervisor nunca decide con una "función secreta".
- **Seguridad primero:** prohibiciones físicas (energía, sensores, barranco confirmado) preceden a las propuestas de IA; cada decisión tiene
  un código de motivo reproducible (R00–R15).
- **No omnisciencia:** el rover planifica sobre un mapa creído; barrancos y parte de los obstáculos están ocultos y se descubren con sensores.
- **Límites:** física simplificada en cuadrícula 16×12; consumos, temperaturas internas, umbrales y daños son *supuestos de simulación*,
  no especificaciones de ingeniería. La señal biológica es anómala y simulada: nunca confirma vida.
- **Gigantes gaseosos:** Júpiter, Saturno, Urano y Neptuno bloquean el modo ruedas y proponen la sonda atmosférica virtual."""),
]

notebook = nbf.v4.new_notebook(cells=cells, metadata={
    'kernelspec': {'name': 'python3', 'display_name': 'Python 3'},
    'language_info': {'name': 'python'}, 'colab': {'provenance': []}})
nbf.write(notebook, ROOT / 'ARES_X_Rover.ipynb')
print('ARES_X_Rover.ipynb generado con', len(cells), 'celdas')
