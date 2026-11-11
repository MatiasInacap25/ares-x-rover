"""Hybrid mission loop.

observar -> validar_sensores -> predecir_riesgo_rna -> inferir_control_difuso ->
replanificar_ag_si_corresponde -> aplicar_restricciones -> ejecutar_accion ->
actualizar_mundo -> registrar_traza

The rover is not omniscient: it plans over a *belief* map that misses hidden
cliffs and part of the obstacles. Those are revealed through sensors (RNA
camera/LIDAR lookahead, deterministic edge sensor) or, worst case, by contact.
"""
from collections import deque
import math
import time

import numpy as np

from .events import Event
from .fuzzy import FuzzyController
from .genetic import GeneticPlanner, optimize_visit_order
from .logger import MissionLogger, clean
from .neural import NeuralPerception
from .planet import ASSUMPTION, PROFILES, PlanetProfile, normalize
from .sensors import SensorSuite
from .supervisor import SafetySupervisor
from .world import World

POLICIES = {
    'hibrido': dict(rna=True, fuzzy=True, ga=True, fixed_risk=False, label='Híbrido completo'),
    'sin_rna': dict(rna=False, fuzzy=True, ga=True, fixed_risk=False, label='Ablación: sin RNA'),
    'sin_difuso': dict(rna=True, fuzzy=False, ga=True, fixed_risk=False, label='Ablación: sin difuso'),
    'sin_ag': dict(rna=True, fuzzy=True, ga=False, fixed_risk=False, label='Ablación: sin AG'),
    'control': dict(rna=False, fuzzy=False, ga=False, fixed_risk=False, label='Control: ruta más corta sin riesgos'),
    'ag_puro': dict(rna=False, fuzzy=False, ga=True, fixed_risk=True, label='AG puro con riesgos fijos'),
}
FIXED_SPEED = .5          # speed used when the fuzzy controller is disabled
PLAN_SPEED = .85          # speed assumed when budgeting energy (typical cruise; avoids optimistic plans)
RISK_PRIOR = .1           # belief risk of a never-observed cell (supuesto)
FIXED_RISK = .15          # constant estimated risk for the 'ag_puro' baseline
DAY_LENGTH = 30           # steps per half day/night cycle (supuesto)
MAX_STEPS = 400
INSTRUMENT_BATTERY = 5.   # battery recovered with each instrument cache (supuesto)
# Event effects (all values are simulation assumptions).
MAX_DESTINATIONS = 8
DRONE_AHEAD, DRONE_ENERGY, DRONE_RESERVE = 4, .08, 15.  # cells scouted, % battery per flight, minimum battery
HEAT_STEPS, HEAT_EXTERNAL, HEAT_INTERNAL, HEAT_ENERGY = 12, 40., 35., 1.2
WIND_STEPS, WIND_ENERGY, WIND_SPEED = 5, 1.3, 22.
LINK_STEPS = 10
QUAKE_DAMAGE, METEORITE_DAMAGE, BIOSIGNAL_ENERGY, VIBRATION_LEVEL = 3., 5., 1., 2.5
# Events the rover perceives at once: the route is recomputed when they happen (F9).
# Hidden hazards (cliff, alien, manual obstacle) are discovered later by the sensors.
PERCEIVABLE_EVENTS = ('meteorito', 'sismo', 'viento', 'bateria_baja', 'ola_calor', 'tormenta_polvo')
WAIT_REASONS = ('R02_SENSORES_NAVEGACION_FALLIDOS', 'R08_ESPERA_SISMO', 'R12_DIFUSO_PARAR', 'R16_ESPERA_VIENTO')
EVENT_LABELS = {
    'barranco': 'Barranco', 'bateria_baja': 'Batería baja', 'dia': 'Día', 'noche': 'Noche',
    'sismo': 'Sismo', 'meteorito': 'Meteorito', 'tormenta_polvo': 'Tormenta de polvo',
    'corrosion': 'Corrosión', 'biosenal_anomala': 'Señal biológica anómala',
    'alienigena': 'Objeto/ser alienígena (ficción)', 'falla_sensor': 'Falla de sensor',
    'perdida_enlace': 'Pérdida de enlace', 'viento': 'Ráfaga de viento', 'ola_calor': 'Ola de calor',
}

_NN_CACHE = {}


def shared_perception(seed=0):
    """Train the MLP once per process (offline phase) and reuse it online."""
    if seed not in _NN_CACHE:
        started = time.perf_counter()
        perception = NeuralPerception(seed=seed)
        perception.train()
        perception.train_seconds_ = time.perf_counter() - started
        _NN_CACHE[seed] = perception
    return _NN_CACHE[seed]


def _finite(value):
    return isinstance(value, (int, float, np.number)) and not isinstance(value, bool) and math.isfinite(value)


def validate_config(config):
    """Return a normalized config or raise ValueError with a readable message."""
    cfg = dict(planet='Marte', mode='rover', seed=42, difficulty='medium', battery=100.,
               policy='hibrido', step_duration=1., science_count=5, thermal_limit=70.,
               weights=None, hidden_cliffs=4, ga_population=30, ga_generations=30,
               ga_crossover=.85, ga_mutation=.25, drone=False)
    cfg.update({k: v for k, v in (config or {}).items() if v is not None})
    if normalize(str(cfg['planet'])) not in PROFILES:
        raise ValueError(f"Planeta desconocido: {cfg['planet']}")
    if normalize(str(cfg['mode'])) not in ('rover', 'ruedas', 'sonda', 'probe'):
        raise ValueError('Modo inválido: use rover (ruedas) o sonda')
    for key, low, high in (('battery', 0, 100), ('step_duration', .01, 100), ('thermal_limit', -100, 1000)):
        try:
            cfg[key] = float(cfg[key])
        except (TypeError, ValueError):
            raise ValueError(f'{key}: debe ser un número') from None
        if not math.isfinite(cfg[key]) or not low <= cfg[key] <= high:
            raise ValueError(f'{key}: valor imposible ({cfg[key]}); rango permitido {low}–{high}')
    for key in ('ga_crossover', 'ga_mutation'):
        try:
            cfg[key] = float(cfg[key])
        except (TypeError, ValueError):
            raise ValueError(f'{key}: debe ser un número') from None
        if not math.isfinite(cfg[key]) or not 0 <= cfg[key] <= 1:
            raise ValueError(f'{key}: probabilidad imposible ({cfg[key]}); rango 0–1')
    for key, low, high in (('seed', 0, 2**31 - 1), ('science_count', 0, 12), ('hidden_cliffs', 0, 12),
                           ('ga_population', 30, 120), ('ga_generations', 30, 150)):
        value = cfg[key]
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not low <= value <= high:
            raise ValueError(f'{key}: debe ser entero entre {low} y {high}')
        cfg[key] = int(value)
    if not isinstance(cfg['drone'], (bool, np.bool_)):
        raise ValueError('drone: debe ser verdadero o falso')
    cfg['drone'] = bool(cfg['drone'])
    if cfg['difficulty'] not in ('low', 'medium', 'high'):
        raise ValueError('Dificultad inválida: low, medium o high')
    if cfg['policy'] not in POLICIES:
        raise ValueError(f"Política desconocida: {cfg['policy']}")
    if cfg['weights'] is not None:
        weights = {}
        for key, value in dict(cfg['weights']).items():
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f'Peso {key}: debe ser un número') from None
            if not math.isfinite(value) or value < 0:
                raise ValueError(f'Peso {key}: debe ser finito y no negativo')
            weights[key] = value
        if set(weights) - set(GeneticPlanner.default_weights):
            raise ValueError('Componente de fitness desconocido')
        if not any(weights.values()):
            raise ValueError('Los pesos del fitness no pueden ser todos cero')
        cfg['weights'] = weights
    # Raises a scientific explanation for gas giants + wheels (CA-07).
    PlanetProfile.for_body(cfg['planet'], cfg['mode'])
    return cfg


class CachedPlanner(GeneticPlanner):
    """Same GA, with per-run memoized BFS segments (speed only, same results)."""

    def plan(self, world, start, goal, battery=100, estimated_risk=None, **kwargs):
        self._cache = {}
        try:
            return super().plan(world, start, goal, battery, estimated_risk, **kwargs)
        finally:
            self._cache = None

    def _path(self, world, start, goal):
        cache = getattr(self, '_cache', None)
        if cache is None:
            return GeneticPlanner._path(world, start, goal)
        key = (tuple(start), tuple(goal))
        if key not in cache:
            cache[key] = GeneticPlanner._path(world, start, goal)
        return cache[key]


class HybridMission:
    operational_label = ASSUMPTION

    def __init__(self, **config):
        self.config = validate_config(config)
        cfg = self.config
        self.policy = POLICIES[cfg['policy']]
        self.profile = PlanetProfile.for_body(cfg['planet'], cfg['mode'])
        self.seed = cfg['seed']
        self.rng = np.random.default_rng(self.seed + 7)
        self.world = World(16, 12, seed=self.seed, difficulty=cfg['difficulty'], science_count=cfg['science_count'])
        self.home = (0, 0)
        self._add_second_refuge()
        self.hidden_cliffs, self.hidden_obstacles = self._hide_hazards(cfg['hidden_cliffs'])
        self.rna_marks = set()    # hazards believed only from RNA output (unconfirmed)
        self.rna_retried = set()  # marks already discarded once; a second RNA flag makes them firm
        self.done = set()        # objectives completed: science sites visited + instruments recovered
        self.recovered = set()   # instrument caches recovered (mission goal: recuperar instrumentación)
        self.belief = self._make_belief()
        self.sensors = SensorSuite(self.seed, noise=.05)
        self.perception = shared_perception(0)
        self.fuzzy = FuzzyController()
        self.supervisor = SafetySupervisor()
        self.logger = MissionLogger()
        self.risk = {}
        self.position = self.home
        self.battery = cfg['battery']
        self.health = 100.
        self.daylight, self.visibility = True, 1.
        self.wait_steps = 0
        self.wind_wait = 0
        self.elapsed = 0.
        self.step_index = 0
        self.state = 'CONFIGURACION'
        self.route = None
        self.path = [self.position]
        self.planned_history = []
        self.ga = None
        self.ga_context = None
        self.ga_history_raw = []
        self.ga_runs = []
        self.returning = False
        self.finished = False
        self.outcome = None
        self.replan_reason = 'INICIO'
        self.timers = {'storm': 0, 'link': 0, 'vibration': 0, 'heat': 0, 'wind': 0}
        self.link_down_steps = 0
        self.queued_orders = 0
        self.sensor_timers = {}
        self.destinations = []  # operator waypoints in visiting order (F6, F13)
        self.tour_cells = 0
        self.day_counter = 0
        self.no_route_steps = 0
        self.nothing_left = False
        self.pending_events = []
        self.event_log = []
        self.last = {}
        self.metrics = dict(collisions=0, cliffs_avoided=0, hazards_avoided=0, replans=0, ga_runs=0,
                            science_samples=0, safety_violations=0, energy_used=0., distance=0,
                            decision_seconds=0., planning_seconds=0., anomalies=0, contacts=0, events={},
                            wait_steps=0, degraded_steps=0, link_outage_steps=0,
                            drone_steps=0, drone_discoveries=0, drone_energy=0.)
        self.drone = None  # scout drone state (F16); None when the mission has no drone

    # ------------------------------------------------------------------ setup
    def _free_cells(self):
        world = self.world
        return [(r, c) for r in range(world.height) for c in range(world.width)
                if world.traversable((r, c)) and (r, c) not in world.refuges]

    def _add_second_refuge(self):
        far = [cell for cell in self._free_cells() if cell[0] + cell[1] >= 18
               and cell not in self.world.science_sites and cell not in self.world.resources]
        if far:
            self.world.refuges.add(far[int(self.rng.integers(len(far)))])

    def _hide_hazards(self, count):
        world = self.world
        reserved = world.refuges | world.science_sites | world.resources | {self.home, (0, 1), (1, 0), (1, 1)}
        candidates = [cell for cell in self._free_cells() if cell not in reserved]
        cliffs = set()
        if self.profile.mode == 'rover' and candidates:
            for index in self.rng.permutation(len(candidates))[:count]:
                cell = candidates[int(index)]
                cliffs.add(cell)
                world.cliffs.add(cell)
                world.elevation[cell] -= 10.
        obstacles = sorted(world.obstacles)
        hidden = {obstacles[int(i)] for i in self.rng.permutation(len(obstacles))[:int(len(obstacles) * .3)]}
        return cliffs, hidden

    def _make_belief(self):
        belief = World.__new__(World)
        world = self.world
        belief.width, belief.height, belief.seed, belief.difficulty = world.width, world.height, world.seed, world.difficulty
        belief.rng = None
        belief.elevation = world.elevation.copy()
        for cell in self.hidden_cliffs:
            belief.elevation[cell] += 10.  # orbital map does not resolve the drop
        belief.obstacles = set(world.obstacles) - self.hidden_obstacles
        belief.cliffs = set()
        # Planner objectives = science sites + instrument caches to recover.
        belief.science_sites = world.science_sites | world.resources
        belief.visited_science = self.done
        belief.resources = world.resources
        belief.refuges = world.refuges
        return belief

    # -------------------------------------------------------------- helpers
    @property
    def temperature_internal(self):
        base = 20. + (self.profile.temperature - 20.) * .1  # thermal control model (supuesto)
        return base + (HEAT_INTERNAL if self.timers['heat'] else 0.)

    @property
    def vibration_level(self):
        return VIBRATION_LEVEL if self.timers['vibration'] else 0.

    @property
    def wind_speed(self):
        return WIND_SPEED if self.timers['wind'] else 0.

    @property
    def link_latency(self):
        """Seconds since the link was lost (0 with the link up)."""
        return self.link_down_steps * self.config['step_duration']

    def cell_cost(self, speed=FIXED_SPEED, slope=0.):
        base = .45 * (.7 + .6 * speed) * (1 + .5 * (1 - self.visibility)) + .01 * slope
        factor = (HEAT_ENERGY if self.timers['heat'] else 1.) * (WIND_ENERGY if self.timers['wind'] else 1.)
        return base * self.config['step_duration'] * factor

    def _bfs(self, start, goal=None, avoid=frozenset(), goals=None):
        goals = goals or {goal}
        world = self.belief
        queue, previous = deque([start]), {start: None}
        while queue:
            cell = queue.popleft()
            if cell in goals:
                route = []
                while cell is not None:
                    route.append(cell)
                    cell = previous[cell]
                return route[::-1]
            for dr, dc in ((-1, 0), (0, 1), (1, 0), (0, -1)):
                nxt = (cell[0] + dr, cell[1] + dc)
                if nxt in previous or not world.traversable(nxt, self.profile.mode) or (nxt in avoid and nxt not in goals):
                    continue
                if self.profile.mode == 'rover' and world.elevation[nxt] - world.elevation[cell] < -5:
                    continue
                previous[nxt] = cell
                queue.append(nxt)
        return None

    def refuge_route(self):
        return self._bfs(self.position, goals=set(self.world.refuges))

    def energy_to_refuge(self):
        if self.position in self.world.refuges:
            return 0.
        route = self.refuge_route()
        return math.inf if route is None else (len(route) - 1) * self.cell_cost(PLAN_SPEED)

    def _risk_avoid(self):
        return {cell for cell, value in self.risk.items() if value >= .5}

    def _hazard_distance(self):
        """Meters to the first known/predicted hazard along the planned route."""
        for k, cell in enumerate((self.route or [])[1:5], start=1):
            known = cell in self.belief.cliffs or cell in self.belief.obstacles
            if known or self.risk.get(cell, 0.) >= .5:
                return float((k - 1) * 5 + 1)
        return 20.

    # ------------------------------------------------------------ perception
    def _features(self, cell, readings):
        distance = readings.get('distance')
        delta = readings.get('elevation_delta')
        if not _finite(distance) or not _finite(delta):
            raise ValueError('Lectura inválida para la RNA')
        noise = 1 + 2 * (1 - self.visibility)
        rng = self.rng
        return {
            'distance': float(np.clip(distance + rng.normal(0, .8 * noise), .01, 20)),
            'slope': float(np.clip(readings['slope'] + rng.normal(0, 2.), 0, 45)),
            'elevation_delta': float(delta + rng.normal(0, 1.3 * noise)),
            'texture': float(np.clip(.25 + .3 * (cell in self.world.obstacles) + rng.normal(0, .22 * noise), 0, 1)),
            'visibility': float(np.clip(self.visibility, .35, 1.)),
            'vibration': float(np.clip(abs(delta) * .15 + rng.normal(0, .15) + (1.5 if self.timers['vibration'] else 0), 0, 20)),
        }

    def _observe(self, cell):
        readings = self.sensors.observe(self.world, self.position, cell, self.battery, self.profile,
                                        self.daylight, self.visibility)
        if self.timers['heat'] and _finite(readings.get('temperature_external')):
            readings['temperature_external'] += HEAT_EXTERNAL
        readings['vibration'] = self.vibration_level
        readings['wind_speed'] = self.wind_speed
        return readings

    # ------------------------------------------------------------- planning
    def _mark_rna(self, cell, label):
        """Record a hazard inferred by the RNA; it stays revisable until seen twice."""
        (self.belief.cliffs if label == 'barranco' else self.belief.obstacles).add(cell)
        if cell not in self.rna_retried:
            self.rna_marks.add(cell)

    def _plan(self, reason):
        if self.destinations and not self.returning:
            self._order_destinations()
        self._plan_once(reason)
        if len(self.route) <= 1 and self.rna_marks:
            # No route while relying on unconfirmed RNA beliefs: discard them once and
            # replan. Edge sensor and RNA still re-check those cells before entering.
            cells = sorted(self.rna_marks)
            for cell in cells:
                self.belief.cliffs.discard(cell)
                self.belief.obstacles.discard(cell)
            self.rna_retried |= self.rna_marks
            self.rna_marks.clear()
            self.nothing_left = False
            entry = dict(step=self.step_index, kind='revision_rna', label='Revisión de creencias RNA',
                         message='Sin ruta con peligros inferidos solo por la RNA: se descartan '
                                 f'{len(cells)} marca(s) no confirmada(s) y se replanifica.', position=None)
            self.event_log.append(entry)
            self.pending_events.append(entry)
            self._plan_once(reason + '+REVISION_RNA')
        while len(self.route) <= 1 and self.destinations and not self.returning:
            # The next destination became unreachable (new hazard or low energy): drop it and resume.
            self._drop_destination(self.destinations[0])
            self._order_destinations()
            self._plan_once(reason + '+SIN_DESTINO')
        if len(self.route) <= 1 and not self.returning and self.position not in self.world.refuges:
            # No feasible exploration plan (typically low energy): head for the nearest
            # reachable refuge instead of waiting without a route.
            back = self.refuge_route()
            if back and len(back) > 1:
                self.returning = True
                self._plan_once(reason + '+RETORNO')

    @property
    def destination(self):
        """Next operator destination in the optimised visiting order."""
        return self.destinations[0] if self.destinations else None

    def _drop_destination(self, cell):
        self.destinations.remove(cell)
        entry = dict(step=self.step_index, kind='destino_descartado', label='Destino descartado',
                     message=f'El destino {list(cell)} ya no tiene ruta segura: se descarta y se retoma la misión.',
                     position=list(cell))
        self.event_log.append(entry)
        self.pending_events.append(entry)

    def _tour(self, cells):
        """Best order to visit ``cells`` from the current position, ending at a refuge.

        Distances come from the believed map; the order is evolved by the
        permutation GA. Returns (ordered cells, total cells including the return).
        """
        nodes = [self.position] + list(cells)
        hops = lambda path: len(path) - 1 if path else math.inf
        leg = [[0 if a == b else hops(self._bfs(a, b)) for b in nodes] for a in nodes]
        closing = [hops(self._bfs(node, goals=set(self.world.refuges))) for node in nodes]
        result = optimize_visit_order(leg, closing, seed=self.seed)
        return [nodes[i + 1] for i in result['order']], result['cost']

    def _order_destinations(self):
        """Drop unreachable destinations and keep the rest in the best visiting order."""
        for cell in [c for c in self.destinations if self._bfs(self.position, c) is None]:
            self._drop_destination(cell)
        if not self.destinations:
            self.tour_cells = 0
            return
        order, self.tour_cells = self._tour(self.destinations)
        if order != self.destinations and len(order) > 1:
            entry = dict(step=self.step_index, kind='orden_destinos', label='Orden de visita optimizado',
                         message='El AG de permutaciones ordenó los destinos: '
                                 + ' → '.join(str(list(c)) for c in order)
                                 + f' ({self.tour_cells} celdas con retorno al refugio).', position=None)
            self.event_log.append(entry)
            self.pending_events.append(entry)
        self.destinations = order

    def destination_tour(self):
        """Cells joining the destinations in visiting order (the leg to the first is the route)."""
        cells = [self.destinations[0]] if self.destinations else []
        for a, b in zip(self.destinations, self.destinations[1:]):
            cells += (self._bfs(a, b) or [a, b])[1:]
        return cells

    def _plan_once(self, reason):
        started = time.perf_counter()
        self.metrics['replans'] += 1
        self.replan_reason = None
        if self.returning:
            route = self.refuge_route()
            self.route = route if route else [self.position]
            self.ga = dict(reason=reason, mode='retorno', candidates=[], rejected=[], history=[],
                           message='Ruta directa al refugio más cercano.')
        elif self.policy['ga']:
            self._plan_ga(reason)
        else:
            self._plan_greedy(reason)
        self.ga['step'] = max(1, self.step_index)
        self.planned_history.append(list(self.route))
        self.metrics['planning_seconds'] += time.perf_counter() - started

    def risk_map(self):
        cells = [(r, c) for r in range(self.belief.height) for c in range(self.belief.width)]
        if self.policy['fixed_risk']:
            base = {cell: FIXED_RISK for cell in cells}
        else:
            base = {cell: RISK_PRIOR for cell in cells}
            base.update({cell: float(np.clip(v, 0, 1)) for cell, v in self.risk.items()})
        for cell in self.belief.cliffs | self.belief.obstacles:
            base[cell] = 1.
        return base

    def _plan_ga(self, reason):
        self.metrics['ga_runs'] += 1
        cfg = self.config
        planner = CachedPlanner(population_size=cfg['ga_population'], generations=cfg['ga_generations'], waypoints=3,
                                seed=self.seed + self.metrics['ga_runs'], weights=cfg['weights'],
                                crossover_rate=cfg['ga_crossover'], mutation_rate=cfg['ga_mutation'])
        goal = self.destination or self.home
        risk = self.risk_map()
        kwargs = dict(temperature=self.temperature_internal, thermal_limit=self.config['thermal_limit'],
                      energy_per_step=self.cell_cost(PLAN_SPEED))
        result = planner.plan(self.belief, self.position, goal, battery=self.battery, estimated_risk=risk, **kwargs)
        accepted, rejected = self.supervisor.filter_routes(result['candidates'], self.belief.cliffs, self.belief.obstacles)
        chosen = accepted[0] if accepted else None
        self.route = list(result['candidates'][chosen]['route']) if chosen is not None else [self.position]
        if chosen is None or (not result['candidates'][chosen]['science_order'] and self.position in self.world.refuges):
            self.nothing_left = self.position in self.world.refuges
        self.ga_context = dict(planner=planner, goal=goal, battery=self.battery, risk=risk, kwargs=kwargs,
                               start=self.position)
        self.ga_history_raw = result['history']
        self.ga = dict(
            reason=reason, mode='ag', chosen=chosen, rejected=rejected, feasible=result['feasible'],
            message=result['message'], generations_run=result['generations_run'], stopped_early=result['stopped_early'],
            candidates=[dict(index=i, route=[list(p) for p in c['route']], fitness=round(c['fitness'], 4),
                             feasible=c['feasible'], components={k: round(v, 4) for k, v in c['components'].items()},
                             penalty=round(c['penalty'], 3), violations=c['violations'],
                             science_order=[list(p) for p in c['science_order']],
                             chromosome=[list(p) for p in c['chromosome']], distance=c['distance'])
                        for i, c in enumerate(result['candidates'])],
            history=[dict(generation=h['generation'], best=round(h['best_fitness'], 4),
                          best_feasible=None if h['best_feasible_fitness'] is None else round(h['best_feasible_fitness'], 4),
                          tournaments=h['tournaments'], crossovers=h['crossovers'], mutations=h['mutations'])
                     for h in result['history']],
            weights=dict(planner.weights))
        self.ga_runs.append(dict(ga=self.ga, raw=self.ga_history_raw, ctx=self.ga_context,
                                 belief=(set(self.belief.obstacles), set(self.belief.cliffs)),
                                 visited=set(self.belief.visited_science),
                                 step=self.step_index))

    def ga_run(self, run=None):
        if not self.ga_runs:
            raise ValueError('Aún no hay ejecuciones del AG')
        run = len(self.ga_runs) - 1 if run is None else max(0, min(int(run), len(self.ga_runs) - 1))
        return run, self.ga_runs[run]

    def _plan_greedy(self, reason):
        """Nearest-neighbour tour over remaining sites with a battery check (no GA)."""
        avoid = self._risk_avoid() if self.policy['rna'] else set()
        if self.destination is not None:
            self.route = self._bfs(self.position, self.destination, avoid) or self._bfs(self.position, self.destination) or [self.position]
            self.ga = dict(reason=reason, mode='voraz', chosen=None, rejected=[], candidates=[], history=[],
                           message='Ruta directa al destino del operador (sin AG).', science_order=[])
            return
        remaining = sorted(self.belief.science_sites - self.done)
        position, route, order = self.position, [self.position], []
        cost = self.cell_cost(PLAN_SPEED)
        while remaining:
            options = [(self._bfs(position, site, avoid), site) for site in remaining]
            options = [(p, s) for p, s in options if p]
            if not options:
                break
            path, site = min(options, key=lambda o: (len(o[0]), o[1]))
            back = self._bfs(site, goals=set(self.world.refuges), avoid=avoid)
            if back is None or (len(route) - 1 + len(path) - 1 + len(back) - 1) * cost > self.battery:
                break
            route.extend(path[1:])
            order.append(site)
            remaining.remove(site)
            position = site
        back = self._bfs(position, self.home, avoid) or self._bfs(position, goals=set(self.world.refuges), avoid=avoid)
        if back:
            route.extend(back[1:])
        self.route = route
        if not order and self.position in self.world.refuges:
            self.nothing_left = True
        self.ga = dict(reason=reason, mode='voraz', chosen=None, rejected=[], candidates=[], history=[],
                       message='Planificador voraz (sin AG): vecino más cercano.',
                       science_order=[list(p) for p in order])

    def ga_generation(self, generation, run=None):
        """Chromosomes of one generation re-evaluated with that run's planning context."""
        run, record = self.ga_run(run)
        raw, ctx = record['raw'], record['ctx']
        generation = max(0, min(int(generation), len(raw) - 1))
        entry = raw[generation]
        # Re-evaluate against the belief known when that plan was made.
        snapshot = World.__new__(World)
        snapshot.__dict__.update(self.belief.__dict__)
        snapshot.obstacles, snapshot.cliffs = set(record['belief'][0]), set(record['belief'][1])
        snapshot.visited_science = set(record['visited'])  # science reward depends on what was still pending
        rows = []
        for chromosome in entry['chromosomes'][:8]:
            result = ctx['planner'].evaluate(chromosome, snapshot, ctx['start'], ctx['goal'], ctx['battery'],
                                             ctx['risk'], **ctx['kwargs'])
            rows.append(dict(chromosome=[list(p) for p in chromosome], fitness=round(result['fitness'], 4),
                             feasible=result['feasible'], violations=result['violations'],
                             components={k: round(v, 4) for k, v in result['components'].items()}))
        return dict(generation=generation, total=len(raw), rows=rows, run=run, runs=len(self.ga_runs),
                    tournaments=entry['tournaments'], crossovers=entry['crossovers'], mutations=entry['mutations'],
                    best=round(entry['best_fitness'], 4))

    # ---------------------------------------------------------------- events
    def _replan_now(self, reason):
        """Replan at once (F9); before the first plan exists, just record the reason."""
        if self.route is None:
            self.replan_reason = reason
            return False
        self._plan(reason)
        self.ga['step'] = self.step_index + 1  # logged with the next step record
        return True

    def _destination_cell(self, position):
        try:
            cell = tuple(int(v) for v in position)
            assert len(cell) == 2
        except (TypeError, ValueError, AssertionError):
            raise ValueError('Destino inválido: se esperan (fila, columna).') from None
        return cell

    def remove_destination(self, position):
        """Operator removes one destination; the rest are reordered."""
        cell = self._destination_cell(position)
        if cell not in self.destinations:
            raise ValueError('No hay un destino fijado en esa celda.')
        self.destinations.remove(cell)
        entry = dict(step=self.step_index, kind='destino_cancelado', label='Destino cancelado',
                     message=f'El operador quitó el destino {list(cell)}: quedan {len(self.destinations)}.',
                     position=list(cell))
        self.event_log.append(entry)
        self.pending_events.append(entry)
        self._replan_now('DESTINO_CANCELADO')
        return entry

    def set_destination(self, position):
        """Add an operator destination (None clears them all).

        Validated, planned with the same pipeline and never above safety. With
        several destinations the visiting order is the shortest tour found by the GA.
        """
        if self.finished:
            raise ValueError('La misión ya terminó: reinicie para fijar un destino.')
        if position is None:
            if not self.destinations:
                raise ValueError('No hay destino fijado.')
            entry = dict(step=self.step_index, kind='destino_cancelado', label='Destino cancelado',
                         message='El operador quitó los destinos: se retoma la misión.', position=list(self.destinations[0]))
            self.destinations, self.tour_cells = [], 0
        else:
            cell = self._destination_cell(position)
            if not self.world.in_bounds(cell):
                raise ValueError('Destino fuera del mapa.')
            if cell == self.position:
                raise ValueError('El rover ya está en esa celda.')
            if cell in self.destinations:
                raise ValueError('Ese destino ya está fijado.')
            if len(self.destinations) >= MAX_DESTINATIONS:
                raise ValueError(f'Máximo {MAX_DESTINATIONS} destinos a la vez.')
            if not self.belief.traversable(cell, self.profile.mode):
                raise ValueError('Destino inválido: la celda es un obstáculo o barranco conocido.')
            if self._bfs(self.position, cell) is None:
                raise ValueError('Destino inalcanzable: no existe ruta conocida hasta esa celda.')
            order, cells = self._tour(self.destinations + [cell])
            need = cells * self.cell_cost(PLAN_SPEED)
            if need > self.battery:
                raise ValueError('Destino rechazado: la energía no alcanza para visitar los destinos y volver a un refugio '
                                 f'(se requiere {need:.1f} % y hay {self.battery:.1f} %): no hay retorno seguro.')
            self.destinations.append(cell)
            self.returning = False
            entry = dict(step=self.step_index, kind='destino', label='Destino fijado',
                         message=f'Destino del operador en {list(cell)}: {len(self.destinations)} destino(s), '
                                 f'recorrido de {cells} celdas con retorno al refugio.', position=list(cell))
        self.event_log.append(entry)
        self.pending_events.append(entry)
        self._replan_now(entry['kind'].upper())
        return entry

    def inject(self, kind, **data):
        if self.finished:
            raise ValueError('La misión ya terminó: reinicie para inyectar eventos.')
        position = data.pop('position', None)
        event = Event(kind, data)
        kind = event.kind
        if self.timers['link']:
            self.queued_orders += 1  # operator order issued during the outage
        if position is not None:
            position = tuple(int(v) for v in position)
        if kind in ('barranco', 'meteorito', 'alienigena'):
            if kind == 'barranco' and self.profile.mode != 'rover':
                raise ValueError('Barranco no aplica al modo sonda')
            if position is None:
                route = self.route or [self.position]
                offset = {'barranco': 1, 'meteorito': 3, 'alienigena': 2}[kind]
                position = route[min(offset, len(route) - 1)] if len(route) > 1 else None
                if position is None or position in self.world.refuges or position == self.position:
                    neighbors = [(self.position[0] + dr, self.position[1] + dc) for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0))]
                    neighbors = [n for n in neighbors if self.world.traversable(n) and n not in self.world.refuges]
                    if not neighbors:
                        raise ValueError('No hay celda libre adyacente para el evento')
                    position = neighbors[0]
            if not self.world.in_bounds(position):
                raise ValueError('Evento fuera del mapa')
            if position == self.position or position in self.world.refuges:
                raise ValueError('No se puede colocar un peligro sobre el rover o un refugio')
            event.data['position'] = position
        if kind == 'falla_sensor':
            sensor = data.get('sensor', 'distance')
            names = ['distance', 'elevation_delta'] if sensor == 'todos' else [sensor]
            for name in names:
                self.sensors.fail(name, data.get('failure', 'nan'))
                self.sensor_timers[name] = 8
            pretty = {'distance': 'proximidad', 'elevation_delta': 'LIDAR'}
            result = {'kind': kind, 'message': 'Falla simulada de sensor ' + ', '.join(pretty.get(n, n) for n in names)
                      + ' (NaN) durante 8 pasos: degradación segura.'}
        else:
            quake_wait = self.wait_steps
            result = event.apply(self)
            if kind == 'viento':
                self.wait_steps = quake_wait  # wind is not a quake: it has its own hold
        if kind == 'barranco':
            self.world.elevation[position] += 10.  # Event lowers 20 m; keep a 10 m drop
        elif kind == 'meteorito':
            self.belief.add_obstacle(position)
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    cell = (position[0] + dr, position[1] + dc)
                    if self.world.in_bounds(cell) and cell != self.position:
                        self.risk[cell] = max(self.risk.get(cell, 0.), .6)
            self.timers['vibration'] = 2
            if abs(position[0] - self.position[0]) + abs(position[1] - self.position[1]) <= 1:
                self.health = max(0., self.health - METEORITE_DAMAGE)
        elif kind == 'sismo':
            self.wait_steps = 2
            self.timers['vibration'] = 3
            self.health = max(0., self.health - QUAKE_DAMAGE)
        elif kind == 'ola_calor':
            self.timers['heat'] = HEAT_STEPS
        elif kind == 'alienigena':
            self.metrics['contacts'] += 1
        elif kind == 'tormenta_polvo':
            self.timers['storm'] = 15
        elif kind in ('dia', 'noche'):
            self.day_counter = 0
        elif kind == 'perdida_enlace':
            self.timers['link'] = LINK_STEPS
        elif kind == 'biosenal_anomala':
            self.metrics['anomalies'] += 1
            self.battery = max(0., self.battery - BIOSIGNAL_ENERGY)  # spectrometer analysis
        elif kind == 'viento':
            self.timers['wind'] = WIND_STEPS
            if self.profile.mode == 'probe':
                self.wind_wait = 1
        self.metrics['events'][kind] = self.metrics['events'].get(kind, 0) + 1
        entry = dict(step=self.step_index, kind=kind, label=EVENT_LABELS.get(kind, kind),
                     message=result.get('message', kind), position=list(position) if position else None)
        self.event_log.append(entry)
        self.pending_events.append(entry)
        if kind in PERCEIVABLE_EVENTS:
            entry['replanned'] = self._replan_now(kind.upper())  # F9: now, not on the next step
        return entry

    def _tick_environment(self):
        self.day_counter += 1
        if self.day_counter >= DAY_LENGTH:
            self.day_counter = 0
            self.daylight = not self.daylight
        if self.timers['storm']:
            self.timers['storm'] -= 1
            self.visibility = .2
        else:
            self.visibility = 1. if self.daylight else .6
        for key in ('vibration', 'heat', 'wind'):
            if self.timers[key]:
                self.timers[key] -= 1
        if self.timers['link']:
            self.timers['link'] -= 1
            self.metrics['link_outage_steps'] += 1
            self.link_down_steps += 1
            if not self.timers['link']:
                self.link_down_steps = 0
                self.queued_orders = 0  # queue is flushed when the link returns
        self.sensors.link_available = self.timers['link'] == 0
        for name in list(self.sensor_timers):
            self.sensor_timers[name] -= 1
            if self.sensor_timers[name] <= 0:
                del self.sensor_timers[name]
                self.sensors.failures.pop(name, None)
        if self.daylight and self.profile.mode == 'rover':
            self.battery = min(100., self.battery + .12 * self.visibility)  # solar (supuesto)
        if self.profile.name == 'Venus':
            self.health = max(0., self.health - .4)  # corrosion (supuesto)

    def set_drone(self, enabled):
        """Turn the scout drone on or off during the mission, without restarting it.

        The change is logged with its step (and exported), so the final config is
        never mistaken for a drone that flew from the start.
        """
        if not isinstance(enabled, (bool, np.bool_)):
            raise ValueError('enabled: debe ser verdadero o falso')
        enabled = bool(enabled)
        if self.finished:
            raise ValueError('La misión ya terminó: reinicie para cambiar el dron.')
        if enabled == self.config['drone']:
            raise ValueError('El dron ya está ' + ('activado.' if enabled else 'apagado.'))
        self.config = dict(self.config, drone=enabled)
        if enabled:
            self.drone = dict(position=list(self.position), flying=False, reason='Despega en el próximo paso.',
                              scanned=[], found=[])
        else:
            self.drone = None
        entry = dict(step=self.step_index, kind='dron_activado' if enabled else 'dron_desactivado',
                     label='Dron activado' if enabled else 'Dron desactivado',
                     message=(f'El operador activó el dron en el paso {self.step_index}: '
                              'explora la ruta desde el próximo paso.') if enabled else
                             f'El operador apagó el dron en el paso {self.step_index}: el rover sigue solo con sus sensores.',
                     position=None)
        self.event_log.append(entry)
        self.pending_events.append(entry)
        return entry

    def _drone_scan(self):
        """Scout drone: flies the next cells of the route and shares hazards with the rover.

        It only reads what is physically there, never future events. Flight energy is
        taken from the rover battery; it stays grounded in dust storms, strong wind
        or below the battery reserve, and does not exist in probe mode.
        """
        if not self.config['drone']:
            return
        ahead = [tuple(c) for c in (self.route or [])[1:DRONE_AHEAD + 1]]
        reason = None
        if self.profile.mode != 'rover':
            reason = 'La sonda atmosférica no lleva dron.'
        elif self.timers['storm']:
            reason = 'En tierra por la tormenta de polvo.'
        elif self.timers['wind']:
            reason = 'En tierra por el viento fuerte.'
        elif self.battery < DRONE_RESERVE:
            reason = f'En tierra: batería bajo la reserva de {DRONE_RESERVE:.0f} %.'
        elif not ahead:
            reason = 'En tierra: no hay ruta que explorar.'
        if reason:
            self.drone = dict(position=list(self.position), flying=False, reason=reason, scanned=[], found=[])
            return
        world, belief = self.world, self.belief
        scan = {(r + dr, c + dc) for r, c in ahead for dr in (-1, 0, 1) for dc in (-1, 0, 1)}
        scan = {cell for cell in scan if world.in_bounds(cell)}
        cliffs = (world.cliffs & scan) - belief.cliffs
        obstacles = (world.obstacles & scan) - belief.obstacles
        found = sorted(cliffs | obstacles)
        belief.cliffs |= cliffs
        belief.obstacles |= obstacles
        self.rna_marks -= cliffs | obstacles  # confirmed by the drone, no longer a revisable belief
        self.battery = max(0., self.battery - DRONE_ENERGY)
        self.metrics['drone_steps'] += 1
        self.metrics['drone_energy'] += DRONE_ENERGY
        self.metrics['drone_discoveries'] += len(found)
        self.drone = dict(position=list(ahead[-1]), flying=True, reason=None,
                          scanned=[list(c) for c in sorted(scan)], found=[list(c) for c in found])
        if found:
            blocked = [c for c in found if c in set(tuple(x) for x in self.route)]
            entry = dict(step=self.step_index, kind='dron', label='Dron explorador',
                         message=f'El dron detectó {len(cliffs)} barranco(s) y {len(obstacles)} obstáculo(s) adelante'
                                 + (': la ruta pasaba por ahí y se recalcula.' if blocked else ', fuera de la ruta.'),
                         position=list(found[0]), cells=[list(c) for c in found])
            self.event_log.append(entry)
            self.pending_events.append(entry)
            if blocked and not self.replan_reason:
                self.replan_reason = 'DRON_DETECTA_PELIGRO'

    # ------------------------------------------------------------------ step
    def step(self):
        if self.finished:
            return self.last.get('record')
        started = time.perf_counter()
        self.step_index += 1
        self.elapsed += self.config['step_duration']
        depleted = self.battery <= 0  # 0 % means end of mission: solar cannot revive it
        self._tick_environment()
        if depleted:
            self.battery = 0.
        self._drone_scan()
        complete = self.position in self.world.refuges and self.step_index > 1 and not self.returning and (
            not (self.belief.science_sites - self.done) or self.nothing_left) and self.destination is None
        if not complete:
            if self.route is None or (self.replan_reason and self.replan_reason not in ('RECARGA_COMPLETA',)):
                self._plan(self.replan_reason or 'INICIO')
            elif self.replan_reason == 'RECARGA_COMPLETA':
                self._plan('RECARGA_COMPLETA')
            if self.route and len(self.route) <= 1 and not (self.returning and self.position in self.world.refuges):
                self._plan('OBJETIVO_ALCANZADO')
                complete = self.position in self.world.refuges and self.nothing_left and self.step_index > 1
        next_cell = self.route[1] if self.route and len(self.route) > 1 else None

        # 1-2. observe + validate
        readings = self._observe(next_cell or self.position)
        nav_valid = {'proximidad': _finite(readings.get('distance')) and 0 <= readings['distance'] <= 20,
                     'lidar': _finite(readings.get('elevation_delta'))}
        edge = bool(readings.get('cliff')) if next_cell and nav_valid['lidar'] and self.profile.mode == 'rover' else None

        # 3. RNA lookahead (next two cells)
        rna, rna_error = None, None
        if self.policy['rna'] and next_cell:
            for k, cell in enumerate(self.route[1:3]):
                obs = readings if k == 0 else self._observe(cell)
                try:
                    features = self._features(cell, obs)
                    prediction = self.perception.predict(features)
                except ValueError as error:
                    rna_error = str(error)
                    break
                self.risk[cell] = float(np.clip(prediction['risk'], 0, 1))
                if k == 0:
                    rna = dict(prediction, features=features, cell=list(cell))
                elif prediction['label'] != 'libre' and prediction['confidence'] >= self.supervisor.confidence_threshold:
                    # Early warning two cells ahead: mark the cell and replan next step.
                    self._mark_rna(cell, prediction['label'])
                    self.replan_reason = 'RNA_ANTICIPA_PELIGRO'
                    self.metrics['hazards_avoided'] += 1

        # 4. fuzzy control
        slope = readings['slope'] if _finite(readings.get('slope')) else 20.
        hazard = self._hazard_distance() if nav_valid['proximidad'] else 2.
        if edge:
            hazard = 1.
        fuzzy = None
        if self.policy['fuzzy']:
            fuzzy = self.fuzzy.infer(hazard, float(np.clip(self.battery, 0, 100)), float(np.clip(slope, 0, 45)),
                                     float(np.clip(self.temperature_internal, -273.15, 1000)))
            fuzzy['inputs'] = dict(distance=hazard, battery=round(self.battery, 2), slope=round(slope, 2),
                                   temperature=round(self.temperature_internal, 2))
            speed = fuzzy['speed']
        else:
            speed = FIXED_SPEED

        # 5. supervisor
        at_refuge = self.position in self.world.refuges
        ctx = dict(battery=self.battery, health=self.health, temperature_internal=self.temperature_internal,
                   thermal_limit=self.config['thermal_limit'], nav_valid=nav_valid, edge_cliff=edge,
                   rna=rna, rna_used=self.policy['rna'], fuzzy_speed=speed if self.policy['fuzzy'] else None,
                   has_route=next_cell is not None,
                   needs_replan=self.replan_reason is not None and self.replan_reason != 'RECARGA_COMPLETA',
                   quake_wait=self.wait_steps, wind_wait=self.wind_wait, at_refuge=at_refuge, energy_to_refuge=self.energy_to_refuge(),
                   recharge_target=90. if self.returning else 0., returning=self.returning,
                   mission_complete=complete)
        decision = self.supervisor.decide(ctx)
        moved, collision, cost_total = [], None, 0.

        # 6. act
        action = decision.action
        if action == 'replanificar':
            if decision.reason == 'R04_VETO_BARRANCO_CONFIRMADO':
                self.belief.cliffs.add(next_cell)
                self.metrics['cliffs_avoided'] += 1
            elif decision.reason == 'R05_RNA_PELIGRO':
                self._mark_rna(next_cell, rna['label'])
                self.metrics['hazards_avoided'] += 1
            self._plan(decision.reason)
        elif action == 'volver':
            self.returning = True
            self._plan('RETORNO_ENERGIA')
        elif action == 'recargar':
            self.battery = min(100., self.battery + 6.)
            if self.battery >= 90.:
                self.returning = False
                self.replan_reason = 'RECARGA_COMPLETA'
        elif action == 'avanzar':
            effective = min(speed, decision.speed_cap)
            cells = 2 if (effective >= .65 and len(self.route) > 2
                          and self.risk.get(self.route[2], RISK_PRIOR) < .3) else 1
            for _ in range(cells):
                if len(self.route) < 2:
                    break
                cell = self.route[1]
                cost = self.cell_cost(effective, slope)
                if cell in self.world.cliffs and self.profile.mode == 'rover':
                    self.health = 0.
                    self.metrics['safety_violations'] += 1
                    collision = 'caida_barranco'
                    break
                if cell in self.world.obstacles:
                    self.health = max(0., self.health - 25.)
                    self.metrics['collisions'] += 1
                    self.belief.obstacles.add(cell)
                    self.battery = max(0., self.battery - cost / 2)
                    collision = 'colision'
                    self.replan_reason = 'COLISION'
                    break
                if cost > self.battery:
                    break
                self.battery = max(0., self.battery - cost)
                cost_total += cost
                self.position = cell
                self.route.pop(0)
                self.path.append(cell)
                moved.append(cell)
                self.metrics['distance'] += 1
                if cell in self.world.science_sites and cell not in self.world.visited_science:
                    self.world.visited_science.add(cell)
                    self.done.add(cell)
                    self.metrics['science_samples'] += 1
                if cell in self.destinations:
                    self.destinations.remove(cell)
                    left = len(self.destinations)
                    entry = dict(step=self.step_index, kind='destino_alcanzado', label='Destino alcanzado',
                                 message=f'Destino {list(cell)} alcanzado: '
                                         + (f'quedan {left} destino(s).' if left else 'se retoman los objetivos pendientes y el retorno.'),
                                 position=list(cell))
                    self.event_log.append(entry)
                    self.pending_events.append(entry)
                    self.replan_reason = 'DESTINO_ALCANZADO'
                if cell in self.world.resources and cell not in self.recovered:
                    self.recovered.add(cell)
                    self.done.add(cell)
                    self.battery = min(100., self.battery + INSTRUMENT_BATTERY)
                    entry = dict(step=self.step_index, kind='instrumento', label='Instrumento recuperado',
                                 message=f'Instrumentación recuperada en {list(cell)}: +{INSTRUMENT_BATTERY:.0f} % de batería (celda de energía).',
                                 position=list(cell))
                    self.event_log.append(entry)
                    self.pending_events.append(entry)
        if action not in ('avanzar', 'recargar'):
            idle = .05 * self.config['step_duration']
            self.battery = max(0., self.battery - idle)
            cost_total += idle
        self.metrics['energy_used'] += cost_total
        if self.wait_steps and decision.reason == 'R08_ESPERA_SISMO':
            self.wait_steps -= 1
        if self.wind_wait and decision.reason == 'R16_ESPERA_VIENTO':
            self.wind_wait -= 1
        self.no_route_steps = self.no_route_steps + 1 if decision.reason == 'R10_SIN_RUTA' else 0
        self.metrics['wait_steps'] += decision.reason in WAIT_REASONS
        self.metrics['degraded_steps'] += not all(nav_valid.values())

        # 7. update mission state
        self.state = decision.state
        if collision == 'caida_barranco' or self.health <= 0 or (self.battery <= 0 and self.position not in self.world.refuges):
            self.state, self.finished = 'FRACASO', True
            self.outcome = 'Rover perdido: ' + ('caída en barranco' if collision == 'caida_barranco' else 'recursos agotados')
        elif decision.reason == 'R15_MISION_COMPLETA':
            self.finished, self.outcome = True, 'Misión cumplida: objetivos alcanzables y retorno seguro'
        elif decision.reason in ('R06_REFUGIO_INALCANZABLE', 'R01_LIMITE_TERMICO', 'R00_RECURSOS_AGOTADOS',
                                 'R03_DANO_CRITICO'):
            self.finished, self.outcome = True, decision.explanation
            self.state = 'FRACASO' if decision.reason == 'R00_RECURSOS_AGOTADOS' else 'MODO_SEGURO'
        elif self.no_route_steps >= 10:
            self.state, self.finished, self.outcome = 'FRACASO', True, 'Sin solución: no existe ruta factible'
        elif self.step_index >= MAX_STEPS:
            self.state, self.finished, self.outcome = 'FRACASO', True, 'Tiempo extremo agotado'
        elif collision:
            self.state = 'ALERTA'
        self.metrics['decision_seconds'] += time.perf_counter() - started

        # 8. trace
        events, self.pending_events = self.pending_events, []
        explanation = decision.explanation
        if collision == 'colision':
            explanation += ' Contacto con obstáculo no detectado: daño -25 %, se replanifica.'
        if self.timers['link']:
            explanation += ' Enlace perdido: autonomía local, órdenes en cola.'
        ga_now = self.ga if self.ga is not None and self.ga.get('step') == self.step_index else None
        record = self.logger.record(
            step=self.step_index, t=round(self.elapsed, 2), policy=self.config['policy'], state=self.state,
            position=list(self.position), moved=[list(c) for c in moved], battery=round(self.battery, 3),
            health=round(self.health, 2), action=action, reason=decision.reason, explanation=explanation,
            vetoes=decision.vetoes, permitted_by=decision.permitted_by,
            sensors={k: readings.get(k) for k in ('distance', 'elevation_delta', 'slope', 'temperature_external',
                                                     'visibility', 'solar_power', 'pressure', 'oxygen_ambient',
                                                     'radiation', 'link_available', 'vibration', 'wind_speed')},
            nav_valid=nav_valid, edge_cliff=edge,
            rna=None if rna is None else dict(label=rna['label'], confidence=round(rna['confidence'], 4),
                                              probabilities={k: round(v, 4) for k, v in rna['probabilities'].items()},
                                              low_confidence=rna['low_confidence']),
            rna_error=rna_error,
            fuzzy=None if fuzzy is None else dict(speed=round(fuzzy['speed'], 4), caution=round(fuzzy['caution'], 4),
                                                  rules=[[r['id'], round(r['strength'], 3)] for r in fuzzy['activated_rules']]),
            crisp_speed=round(speed, 4), collision=collision,
            ga=None if ga_now is None else dict(
                mode=ga_now['mode'], reason=ga_now['reason'], chosen=ga_now.get('chosen'),
                best_fitness=(ga_now['candidates'][ga_now['chosen']]['fitness']
                              if ga_now.get('chosen') is not None else None),
                rejected=ga_now.get('rejected')),
            route=[list(c) for c in (self.route or [])[:12]], events=events,
            science=round(self.world.science_progress, 3), seed=self.seed,
            event_count=sum(self.metrics['events'].values()), operational_label=ASSUMPTION)
        self.last = dict(record=record, rna=rna, fuzzy=fuzzy, decision=decision.to_dict(), readings=readings,
                         nav_valid=nav_valid, speed=speed)
        return record

    def prepare(self):
        """Compute the initial plan before the first step so the UI can show it."""
        if self.route is None and self.step_index == 0:
            self._plan(self.replan_reason or 'INICIO')
        return self

    def run(self, max_steps=MAX_STEPS):
        while not self.finished and self.step_index < max_steps:
            self.step()
        return self.summary()

    # ------------------------------------------------------------- reporting
    def summary(self):
        m = self.metrics
        return dict(policy=self.config['policy'], seed=self.seed, planet=self.profile.name,
                    success=self.state == 'EXITO', state=self.state, outcome=self.outcome,
                    steps=self.step_index, collisions=m['collisions'], cliffs_avoided=m['cliffs_avoided'],
                    hazards_avoided=m['hazards_avoided'], battery_left=round(self.battery, 3),
                    energy_used=round(m['energy_used'], 3), distance=m['distance'],
                    science=round(self.world.science_progress, 3), samples=m['science_samples'],
                    instruments=len(self.recovered), instruments_total=len(self.world.resources),
                    events=dict(m['events']), events_total=sum(m['events'].values()),
                    wait_steps=m['wait_steps'], degraded_steps=m['degraded_steps'],
                    anomalies=m['anomalies'], contacts=m['contacts'], link_outage_steps=m['link_outage_steps'],
                    drone_steps=m['drone_steps'], drone_discoveries=m['drone_discoveries'],
                    replans=m['replans'], ga_runs=m['ga_runs'], safety_violations=m['safety_violations'],
                    decision_ms=round(1000 * m['decision_seconds'] / max(1, self.step_index), 3),
                    planning_s=round(m['planning_seconds'], 3), health=round(self.health, 2))

    def export_json(self):
        return clean(dict(version='1.0', operational_label=ASSUMPTION, config=self.config,
                          summary=self.summary(), events=self.event_log, trace=self.logger.trace))

    def export_csv(self):
        return self.logger.export_csv()
