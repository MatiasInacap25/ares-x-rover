"""JSON command surface shared by the Colab bridge, the local server and Pyodide.

Every UI action goes through ``Session.dispatch(fn, args)`` so the dashboard is
just a view: the AI engine and the simulation live in Python.
"""
import json
import math

import numpy as np

from .experiments import SCENARIOS, run_experiments, summary_records
from .fuzzy import FuzzyController
from .logger import clean
from .mission import EVENT_LABELS, POLICIES, HybridMission, shared_perception, validate_config
from .neural import FEATURES
from .planet import ASSUMPTION, PROFILES, PlanetProfile
from .supervisor import REASONS

VERSION = '1.0.0'


def _r(value, digits=3):
    if isinstance(value, (float, np.floating)):
        return round(float(value), digits) if math.isfinite(value) else None
    return value


def _cells(cells):
    return sorted([int(r), int(c)] for r, c in cells)


def fuzzy_sets():
    """Sampled membership curves for every linguistic variable (for plots)."""
    controller = FuzzyController()
    universes = {'distance': (0, 20), 'battery': (0, 100), 'slope': (0, 45), 'temperature': (-80, 120)}
    out = {}
    for name, sets in controller.membership_sets.items():
        low, high = universes[name]
        xs = np.linspace(low, high, 61)
        out[name] = {'x': [_r(x, 2) for x in xs],
                     'sets': {label: [_r(controller.membership(float(x), spec), 3) for x in xs]
                              for label, spec in sets.items()}}
    xs = np.linspace(0, 1, 61)
    out['speed'] = {'x': [_r(x, 3) for x in xs],
                    'sets': {label: [_r(controller.membership(float(x), spec), 3) for x in xs]
                             for label, spec in controller.output_sets.items()}}
    return out


def fuzzy_payload(result, controller=None):
    controller = controller or FuzzyController()
    descriptions = {rule['id']: rule for rule in controller.rules}
    curve = result.get('aggregated_curve') or []
    return dict(
        speed=_r(result['speed'], 4), caution=_r(result['caution'], 4), centroid=_r(result['centroid'], 4),
        reason=result['reason'], inputs=result.get('inputs'),
        degrees={k: {s: _r(v, 3) for s, v in d.items()} for k, d in result.get('membership_degrees', {}).items()},
        rules=[dict(id=r['id'], strength=_r(r['strength'], 3), description=r['description'], consequent=r['consequent'])
               for r in result.get('activated_rules', [])],
        all_rules=[dict(id=r['id'], description=r['description'], consequent=r['consequent'],
                        antecedents=[list(a) for a in r['antecedents']]) for r in descriptions.values()],
        curve=[_r(v, 3) for v in curve[::4]], fallback='Sin reglas activas: velocidad 0 (parar), cautela 1.')


def ga_view(ga):
    ga = ga or {}
    return dict(mode=ga.get('mode'), reason=ga.get('reason'), chosen=ga.get('chosen'), message=ga.get('message'),
                rejected=ga.get('rejected', []), generations_run=ga.get('generations_run'),
                stopped_early=ga.get('stopped_early'), weights=ga.get('weights'), step=ga.get('step'),
                history=ga.get('history', []),
                candidates=[{k: v for k, v in c.items() if k != 'route'} for c in ga.get('candidates', [])])


class Session:
    def __init__(self, **config):
        self.config = validate_config(config)
        self.mission = HybridMission(**self.config).prepare()
        self.comparison = None

    # ---------------------------------------------------------------- views
    def snapshot(self):
        m = self.mission
        world, belief = m.world, m.belief
        hidden_obstacles = world.obstacles - belief.obstacles
        hidden_cliffs = world.cliffs - belief.cliffs
        ga = m.ga or {}
        route_cells = [tuple(c) for c in (m.route or [])]
        last = m.last
        trace = m.logger.trace
        perception = m.perception
        rna = last.get('rna')
        decision = last.get('decision')
        readings = last.get('readings') or {}
        fuzzy = last.get('fuzzy')
        log = [dict(step=t['step'], state=t['state'], action=t['action'], reason=t['reason'],
                    battery=t['battery'], explanation=t['explanation'], moved=t['moved'],
                    events=[e['label'] for e in t['events']],
                    rna=(t['rna'] or {}).get('label'), conf=(t['rna'] or {}).get('confidence'),
                    speed=t['crisp_speed'], ga=(t['ga'] or {}).get('best_fitness')) for t in trace[-60:]]
        return clean(dict(
            version=VERSION, operational_label=ASSUMPTION, config=self.config,
            policy_label=POLICIES[self.config['policy']]['label'],
            planet=dict(name=m.profile.name, mode=m.profile.mode, gravity=m.profile.gravity,
                        temperature=m.profile.temperature, pressure=m.profile.pressure,
                        oxygen=m.profile.oxygen, hazards=list(m.profile.hazards)),
            status=dict(step=m.step_index, t=m.elapsed, state=m.state, finished=m.finished, outcome=m.outcome,
                        position=list(m.position), battery=_r(m.battery, 2), health=_r(m.health, 2),
                        daylight=m.daylight, visibility=m.visibility, returning=m.returning,
                        science=_r(world.science_progress, 3), link=m.timers['link'] == 0,
                        instruments=len(m.recovered), instruments_total=len(world.resources),
                        destination_distance=(route_cells.index(m.destination) if m.destination in route_cells else None),
                        destinations_left=len(m.destinations), tour_cells=m.tour_cells,
                        vibration=m.vibration_level, wind=m.wind_speed, heat=m.timers['heat'],
                        link_latency=_r(m.link_latency, 1), queued_orders=m.queued_orders,
                        events_total=sum(m.metrics['events'].values()), events=dict(m.metrics['events']),
                        anomalies=m.metrics['anomalies'], contacts=m.metrics['contacts'],
                        wait_steps=m.metrics['wait_steps'], degraded_steps=m.metrics['degraded_steps'],
                        storm=m.timers['storm'], quake=m.wait_steps,
                        sensor_failures=sorted(m.sensors.failures),
                        temperature_internal=_r(m.temperature_internal, 1)),
            map=dict(width=world.width, height=world.height,
                     elevation=[[_r(v, 2) for v in row] for row in world.elevation.tolist()],
                     obstacles=_cells(belief.obstacles), hidden_obstacles=_cells(hidden_obstacles),
                     cliffs=_cells(belief.cliffs), hidden_cliffs=_cells(hidden_cliffs),
                     science=[[int(r), int(c), (r, c) in world.visited_science] for r, c in sorted(world.science_sites)],
                     refuges=_cells(world.refuges),
                     resources=[[int(r), int(c), (r, c) in m.recovered] for r, c in sorted(world.resources)],
                     risk=[[int(r), int(c), _r(v, 2)] for (r, c), v in sorted(m.risk.items()) if v >= .15],
                     path=[list(p) for p in m.path], route=[list(p) for p in (m.route or [])],
                     candidates=[c['route'] for c in ga.get('candidates', [])][:3],
                     chosen=ga.get('chosen'), destination=list(m.destination) if m.destination else None,
                     destinations=[list(d) for d in m.destinations], tour=[list(p) for p in m.destination_tour()],
                     events=[dict(kind=e['kind'], position=e['position']) for e in m.event_log if e.get('position')]),
            telemetry=dict(
                distance=_r(readings.get('distance')), elevation_delta=_r(readings.get('elevation_delta')),
                slope=_r(readings.get('slope')), temperature_external=_r(readings.get('temperature_external'), 1),
                radiation=_r(readings.get('radiation')), pressure=_r(readings.get('pressure'), 1),
                oxygen_ambient=_r(readings.get('oxygen_ambient')), oxygen_stored=_r(readings.get('oxygen_stored')),
                co2=_r(readings.get('co2')), solar_power=_r(readings.get('solar_power')),
                nav_valid=last.get('nav_valid'), edge_cliff=(trace[-1]['edge_cliff'] if trace else None)),
            decision=decision,
            rna=None if rna is None else dict(
                label=rna['label'], confidence=_r(rna['confidence'], 4), low_confidence=rna['low_confidence'],
                probabilities={k: _r(v, 4) for k, v in rna['probabilities'].items()}, cell=rna.get('cell'),
                features={k: _r(v, 3) for k, v in rna['features'].items()},
                normalized=[_r(v, 3) for v in rna['normalized_input']],
                layers=[{k: _r(v, 3) for k, v in s.items()} for s in rna['activation_summaries']]),
            rna_error=(trace[-1]['rna_error'] if trace else None),
            fuzzy=None if fuzzy is None else fuzzy_payload(fuzzy, m.fuzzy),
            speed=_r(last.get('speed'), 4),
            ga=ga_view(ga),
            ga_runs=[dict(index=i, reason=r['ga']['reason'], step=r['step'],
                          generations=r['ga'].get('generations_run')) for i, r in enumerate(m.ga_runs)],
            metrics=m.summary(),
            series=dict(battery=[t['battery'] for t in trace][-200:],
                        risk=[_r(1 - (t['rna'] or {}).get('probabilities', {}).get('libre', 1.), 3) for t in trace][-200:],
                        speed=[t['crisp_speed'] for t in trace][-200:]),
            log=log,
            nn=dict(test=perception.report_['test'], validation=perception.report_['validation'],
                    converged=perception.report_['converged'], iterations=perception.report_['iterations'],
                    training_samples=perception.report_['training_samples'],
                    split_maps=perception.report_['split_maps'],
                    train_seconds=_r(getattr(perception, 'train_seconds_', None), 2)),
            comparison=self.comparison))

    def meta(self):
        model = shared_perception(0).model
        network = dict(layers=[len(FEATURES)] + list(model.hidden_layer_sizes) + [len(model.classes_)],
                       classes=list(model.classes_),
                       coefs=[[[_r(v, 3) for v in row] for row in layer.tolist()] for layer in model.coefs_],
                       intercepts=[[_r(v, 3) for v in layer.tolist()] for layer in model.intercepts_])
        training = [{k: _r(v, 4) for k, v in row.items()} for row in shared_perception(0).report_['history']]
        return clean(dict(version=VERSION, network=network, training=training, planets=[dict(key=k, name=v[0], rocky=v[1]) for k, v in PROFILES.items()],
                          policies={k: v['label'] for k, v in POLICIES.items()}, events=EVENT_LABELS,
                          scenarios={k: v['label'] for k, v in SCENARIOS.items()}, reasons=REASONS,
                          features=list(FEATURES), fuzzy_sets=fuzzy_sets(), operational_label=ASSUMPTION))

    # ------------------------------------------------------------- commands
    def dispatch(self, fn, args=None):
        args = dict(args or {})
        try:
            handler = getattr(self, 'cmd_' + str(fn))
        except AttributeError:
            return {'error': f'Comando desconocido: {fn}'}
        try:
            return handler(**args)
        except (ValueError, TypeError, KeyError) as error:
            message = error.args[0] if error.args else str(error)
            return {'error': str(message)}

    def cmd_meta(self):
        return self.meta()

    def cmd_state(self):
        return self.snapshot()

    def cmd_configure(self, **config):
        merged = dict(self.config)
        merged.update(config)
        config = validate_config(merged)  # raises readable ValueError (CA-07, NaN sliders)
        self.config = config
        self.mission = HybridMission(**config).prepare()
        return self.snapshot()

    def cmd_validate(self, **config):
        merged = dict(self.config)
        merged.update(config)
        validate_config(merged)
        return {'ok': True}

    def cmd_reset(self):
        self.mission = HybridMission(**self.config).prepare()
        return self.snapshot()

    def cmd_step(self, n=1):
        n = int(n)
        if not 1 <= n <= 400:
            raise ValueError('Pasos inválidos (1–400)')
        for _ in range(n):
            if self.mission.finished:
                break
            self.mission.step()
        return self.snapshot()

    def cmd_inject(self, kind, **data):
        self.mission.inject(kind, **data)
        return self.snapshot()

    def cmd_destination(self, position=None):
        """Add a destination; the same cell again removes it; no position clears them all."""
        m = self.mission
        if position is not None and tuple(int(v) for v in position) in m.destinations:
            m.remove_destination(position)
        else:
            m.set_destination(position)
        return self.snapshot()

    def cmd_place(self, position, kind='obstaculo'):
        """Operator edits the real terrain (RF-02); the rover must discover it."""
        m = self.mission
        cell = tuple(int(v) for v in position)
        if not m.world.in_bounds(cell):
            raise ValueError('Celda fuera del mapa')
        if cell == m.position or cell in m.world.refuges:
            raise ValueError('No se puede colocar sobre el rover o un refugio')
        if kind == 'barranco':
            m.inject('barranco', position=list(cell))
        elif kind == 'obstaculo':
            m.world.add_obstacle(cell)
            m.event_log.append(dict(step=m.step_index, kind='obstaculo_manual', label='Obstáculo manual',
                                    message='Obstáculo colocado por el operador (oculto al rover).', position=list(cell)))
        elif kind == 'limpiar':
            if cell in m.world.cliffs:
                m.world.elevation[cell] = m.belief.elevation[cell]  # refill the 10 m drop
            m.risk.pop(cell, None)
            m.rna_marks.discard(cell)
            m.world.obstacles.discard(cell)
            m.world.cliffs.discard(cell)
            m.belief.obstacles.discard(cell)
            m.belief.cliffs.discard(cell)
        else:
            raise ValueError('Tipo de celda desconocido')
        return self.snapshot()

    def cmd_fuzzy_eval(self, distance, battery, slope, temperature=20.):
        controller = FuzzyController()
        values = [float(v) for v in (distance, battery, slope, temperature)]
        result = controller.infer(*values)
        result['inputs'] = dict(distance=values[0], battery=values[1], slope=values[2], temperature=values[3])
        return clean(fuzzy_payload(result, controller))

    def cmd_rna_eval(self, **features):
        perception = shared_perception(0)
        values = {name: float(features[name]) for name in FEATURES}
        prediction = perception.predict(values)
        return clean(dict(label=prediction['label'], confidence=_r(prediction['confidence'], 4),
                          low_confidence=prediction['low_confidence'],
                          probabilities={k: _r(v, 4) for k, v in prediction['probabilities'].items()},
                          normalized=[_r(v, 3) for v in prediction['normalized_input']],
                          layers=[{k: _r(v, 3) for k, v in s.items()} for s in prediction['activation_summaries']],
                          risk=_r(prediction['risk'], 4)))

    def cmd_ga_generation(self, generation=0, run=None):
        return clean(self.mission.ga_generation(generation, run))

    def cmd_ga_run(self, run=None):
        index, record = self.mission.ga_run(run)
        return clean(dict(run=index, ga=ga_view(record['ga'])))

    def cmd_compare(self, seeds=5, scenario='estandar', policies=None):
        if scenario not in SCENARIOS:
            raise ValueError('Escenario desconocido')
        frame = run_experiments(policies, int(seeds), scenario, planet=self.config['planet'], mode=self.config['mode'])
        self.comparison = dict(scenario=scenario, label=SCENARIOS[scenario]['label'], seeds=int(seeds),
                               summary=summary_records(frame))
        self._comparison_frame = frame
        return clean(self.comparison)

    def cmd_export(self, format='json'):
        if format == 'csv':
            return {'filename': f"ares_x_traza_semilla{self.config['seed']}.csv", 'content': self.mission.export_csv()}
        if format == 'comparison_csv':
            frame = getattr(self, '_comparison_frame', None)
            if frame is None:
                raise ValueError('Primero ejecute una comparación de políticas')
            return {'filename': 'ares_x_comparacion.csv', 'content': frame.to_csv(index=False)}
        payload = json.dumps(self.mission.export_json(), ensure_ascii=False, indent=1)
        return {'filename': f"ares_x_mision_semilla{self.config['seed']}.json", 'content': payload}


def handle_json(session, fn, args_json):
    """String-in/string-out entry point (Colab callback and Pyodide)."""
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError:
        return json.dumps({'error': 'Argumentos JSON inválidos'})
    return json.dumps(session.dispatch(fn, args), ensure_ascii=False, allow_nan=False)
