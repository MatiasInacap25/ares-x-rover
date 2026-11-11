"""Seeded waypoint evolution over a known map, never a future-event oracle."""
from collections import deque
from math import isfinite
import random

from .planet import ASSUMPTION


class GeneticPlanner:
    """Science-visit ordering and maze feasibility with conservative safe return.

    All operational defaults and objective weights are simulation assumptions.
    Positive science competes with normalized distance, energy, risk and time.
    Every infeasible chromosome receives a penalty above any possible reward.
    """

    operational_label = ASSUMPTION
    default_weights = dict(science=3., distance=1., energy=1., predicted_risk=2., time=1.)

    def __init__(self, population_size=30, generations=30, waypoints=4, seed=0,
                 mutation_rate=.25, crossover_rate=.85, elitism=2,
                 tournament_size=3, weights=None, early_stop=True):
        for name, value, minimum in [('population_size', population_size, 30),
                                     ('generations', generations, 30),
                                     ('waypoints', waypoints, 1),
                                     ('elitism', elitism, 1),
                                     ('tournament_size', tournament_size, 2)]:
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                raise ValueError(f'{name}: valor inválido; mínimo {minimum}')
        if elitism >= population_size or tournament_size > population_size:
            raise ValueError('Elitismo o torneo incompatible con la población')
        if any(not isinstance(v, (int, float)) or not isfinite(v) or not 0 <= v <= 1
               for v in (mutation_rate, crossover_rate)):
            raise ValueError('Las tasas deben estar entre 0 y 1')
        self.weights = self.default_weights.copy()
        if weights is not None:
            if set(weights) - set(self.weights):
                raise ValueError('Componente de fitness desconocido')
            self.weights.update(weights)
        if any(not isinstance(v, (int, float)) or not isfinite(v) or v < 0
               for v in self.weights.values()) or not any(self.weights.values()):
            raise ValueError('Pesos inválidos: deben ser finitos, no negativos y no todos cero')
        self.population_size, self.generations, self.waypoints = population_size, generations, waypoints
        self.seed, self.mutation_rate, self.crossover_rate = seed, mutation_rate, crossover_rate
        self.elitism, self.tournament_size, self.early_stop = elitism, tournament_size, early_stop
        self.rng = random.Random(seed)
        self.history = []

    @staticmethod
    def _free(world):
        return [(r, c) for r in range(world.height) for c in range(world.width)
                if world.traversable((r, c))]

    def repair(self, chromosome, world):
        """Clamp invalid coordinates and replace blocked genes with nearest free cells."""
        free = self._free(world)
        if not free:
            return [(0, 0)] * self.waypoints
        genes = list(chromosome)[:self.waypoints]
        genes += [free[0]] * (self.waypoints - len(genes))
        repaired = []
        for gene in genes:
            try:
                row, col = gene
                row = min(world.height - 1, max(0, round(row))) if isfinite(row) else 0
                col = min(world.width - 1, max(0, round(col))) if isfinite(col) else 0
            except (TypeError, ValueError, OverflowError):
                row, col = free[0]
            point = (row, col)
            if not world.traversable(point):
                point = min(free, key=lambda p: (abs(p[0] - row) + abs(p[1] - col), p))
            repaired.append(point)
        return repaired

    def mutate(self, chromosome, world):
        """Mutate positions or scientific visit order, then repair every gene."""
        genes = self.repair(chromosome, world)
        free = self._free(world)
        if free:
            for i in range(self.waypoints):
                if self.rng.random() < self.mutation_rate:
                    genes[i] = self.rng.choice(free)
            if self.waypoints > 1 and self.rng.random() < self.mutation_rate:
                a, b = self.rng.sample(range(self.waypoints), 2)
                genes[a], genes[b] = genes[b], genes[a]
        return self.repair(genes, world)

    @staticmethod
    def _path(world, start, goal):
        if not world.traversable(start) or not world.traversable(goal):
            return None
        queue, previous = deque([start]), {start: None}
        while queue:
            cell = queue.popleft()
            if cell == goal:
                route = []
                while cell is not None:
                    route.append(cell)
                    cell = previous[cell]
                return route[::-1]
            for dr, dc in ((-1, 0), (0, 1), (1, 0), (0, -1)):
                neighbor = (cell[0] + dr, cell[1] + dc)
                if (neighbor not in previous and world.traversable(neighbor)
                        and world.elevation[neighbor] - world.elevation[cell] >= -5):
                    # Match the deterministic cliff rule used by SensorSuite.
                    previous[neighbor] = cell
                    queue.append(neighbor)
        return None

    def _return_distance(self, world, position):
        """Return paths obey the same directed cliff edges as outbound travel."""
        distances = []
        for refuge in sorted(world.refuges):
            path = self._path(world, position, refuge)
            if path is not None:
                distances.append(len(path) - 1)
        return min(distances, default=float('inf'))

    @staticmethod
    def _risk_at(estimated_risk, cell):
        if estimated_risk is None:
            return 0.
        try:
            value = estimated_risk.get(cell, 0.) if hasattr(estimated_risk, 'get') else estimated_risk[cell]
            value = float(value)
        except (TypeError, ValueError, IndexError, KeyError):
            raise ValueError('Mapa de riesgo estimado inválido') from None
        if not isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Riesgo estimado fuera de [0, 1]')
        return value

    def evaluate(self, chromosome, world, start, goal, battery=100, estimated_risk=None,
                 temperature=20, thermal_limit=80, energy_per_step=1, time_per_step=1):
        """Decode a chromosome; normalized costs use fixed map-wide scales.

        Battery reserves cover the route AND a shortest known return from its end.
        Thermal feasibility is a supplied current hardware estimate, not weather.
        """
        numeric = (battery, temperature, thermal_limit, energy_per_step, time_per_step)
        if any(not isinstance(v, (int, float)) or not isfinite(v) for v in numeric):
            raise ValueError('Parámetros de planificación no finitos')
        if battery < 0 or energy_per_step <= 0 or time_per_step <= 0:
            raise ValueError('Batería o costo de paso inválido')
        genes = self.repair(chromosome, world)
        repaired = list(chromosome) != genes
        violations, route = [], []
        if not world.in_bounds(start) or not world.in_bounds(goal):
            violations.append('bounds')
        elif not world.traversable(start) or not world.traversable(goal):
            violations.append('collision_or_cliff')
        else:
            route = [tuple(start)]
            for index, point in enumerate(genes + [tuple(goal)]):
                segment = self._path(world, route[-1], point)
                if segment is None:
                    if index < self.waypoints:
                        # A disconnected optional waypoint cannot invalidate a reachable goal.
                        genes[index] = route[-1]
                        repaired = True
                        continue
                    violations.append('unreachable')
                    break
                route.extend(segment[1:])
        if temperature > thermal_limit:
            violations.append('thermal')
        distance = max(0, len(route) - 1)
        return_distance = self._return_distance(world, route[-1]) if route else float('inf')
        energy_required = (distance + return_distance) * energy_per_step
        if energy_required > battery or (distance > 0 and battery == 0):
            violations.append('battery')
        remaining_sites = world.science_sites - world.visited_science
        science_order = []
        for cell in route:
            if cell in remaining_sites and cell not in science_order:
                science_order.append(cell)
        max_distance = max(1, (world.width * world.height - 1) * (self.waypoints + 1))
        components = {
            'science': len(science_order) / len(remaining_sites) if remaining_sites else 0.,
            'distance': min(1., distance / max_distance),
            'energy': min(1., distance * energy_per_step / 100.),
            'predicted_risk': sum(self._risk_at(estimated_risk, p) for p in route) / max(1, len(route)),
            'time': min(1., distance * time_per_step / max_distance),
        }
        penalty = (1 + sum(self.weights.values())) * len(violations)
        fitness = self.weights['science'] * components['science'] - sum(
            self.weights[k] * v for k, v in components.items() if k != 'science') - penalty
        return dict(chromosome=genes, route=route, feasible=not violations, fitness=fitness,
                    components=components, penalty=penalty, violations=violations,
                    science_order=science_order, energy_required=energy_required,
                    distance=distance, repaired=repaired)

    def plan(self, world, start, goal, battery=100, estimated_risk=None, **kwargs):
        """Return at least three candidates plus inspectable evolutionary history.

        A planning run resets its seed for identical inputs/configuration. Early
        stopping can end before the configured >=30-generation budget, after ten
        stagnant generations; the global best feasible route is always retained.
        """
        self.rng = random.Random(self.seed)
        free = self._free(world)
        fallback = tuple(start) if world.in_bounds(start) else (0, 0)
        population = [[fallback] * self.waypoints]
        sites = sorted(world.science_sites - world.visited_science)
        for _ in range(self.population_size - 1):
            pool = sites if sites and self.rng.random() < .5 else free
            population.append([self.rng.choice(pool) if pool else fallback for _ in range(self.waypoints)])
        self.history, archive = [], {}
        stale, best_score, best_feasible = 0, float('-inf'), None
        counters = dict(tournaments=0, crossovers=0, mutations=0)
        for generation in range(self.generations + 1):
            scored = [self.evaluate(g, world, start, goal, battery, estimated_risk, **kwargs) for g in population]
            scored.sort(key=lambda c: (c['feasible'], c['fitness']), reverse=True)
            for candidate in scored:
                key = tuple(candidate['route'])
                if key not in archive or candidate['fitness'] > archive[key]['fitness']:
                    archive[key] = candidate
                if candidate['feasible'] and (best_feasible is None or candidate['fitness'] > best_feasible['fitness']):
                    best_feasible = candidate
            score = scored[0]['fitness']
            stale = 0 if score > best_score else stale + 1
            best_score = max(best_score, score)
            self.history.append(dict(generation=generation, chromosomes=[c['chromosome'][:] for c in scored],
                                     best_chromosome=scored[0]['chromosome'][:], best_fitness=score,
                                     best_feasible_fitness=best_feasible['fitness'] if best_feasible else None,
                                     stale_generations=stale, **counters))
            if generation == self.generations or (self.early_stop and stale >= 10):
                break
            population = [c['chromosome'][:] for c in scored[:self.elitism]]
            counters = dict(tournaments=0, crossovers=0, mutations=0)
            while len(population) < self.population_size:
                parents = []
                for _ in range(2):
                    contestants = self.rng.sample(scored, self.tournament_size)
                    parents.append(max(contestants, key=lambda c: (c['feasible'], c['fitness']))['chromosome'])
                    counters['tournaments'] += 1
                child = parents[0][:]
                if self.waypoints > 1 and self.rng.random() < self.crossover_rate:
                    split = self.rng.randrange(1, self.waypoints)
                    child = parents[0][:split] + parents[1][split:]
                    counters['crossovers'] += 1
                mutated = self.mutate(child, world)
                counters['mutations'] += sum(a != b for a, b in zip(child, mutated))
                population.append(mutated)
        candidates = sorted(archive.values(), key=lambda c: (c['feasible'], c['fitness']), reverse=True)[:3]
        while len(candidates) < 3:
            candidates.append(scored[len(candidates) % len(scored)])
        feasible = best_feasible is not None
        return dict(route=best_feasible['route'] if feasible else [], feasible=feasible,
                    fitness=best_feasible['fitness'] if feasible else scored[0]['fitness'],
                    candidates=candidates, history=self.history, generations_run=generation,
                    stopped_early=generation < self.generations,
                    message='Ruta factible (supuesto de simulación)' if feasible else
                    'Sin solución: retornar solo si es factible; de lo contrario, esperar en modo seguro.')


def optimize_visit_order(leg, closing, seed=0, population_size=40, generations=60,
                         crossover_rate=.9, mutation_rate=.3, elitism=2, tournament_size=3):
    """Permutation GA (travelling-salesman family): best order to visit n stops.

    ``leg[i][j]`` is the cost from node i to node j, node 0 being the start and
    nodes 1..n the stops; ``closing[i]`` is the cost of ending the tour at node i
    (the safe return). Returns the order as stop indices 0..n-1, its cost and the
    best cost per generation. Seeded, so the same inputs give the same order.
    """
    stops = len(leg) - 1
    if stops <= 0:
        return dict(order=[], cost=0, history=[0])

    def cost(order):
        total, node = 0, 0
        for stop in order:
            total += leg[node][stop + 1]
            node = stop + 1
        return total + closing[node]

    rng = random.Random(seed)
    base = list(range(stops))
    nearest, node, left = [], 0, set(base)       # nearest-neighbour seed individual
    while left:
        nxt = min(left, key=lambda s: (leg[node][s + 1], s))
        nearest.append(nxt)
        left.discard(nxt)
        node = nxt + 1
    population = [nearest, base[:]]
    while len(population) < population_size:
        population.append(rng.sample(base, stops))
    if stops < 3:                                # every permutation fits in the population
        population = [nearest] + [list(p) for p in ([base, base[::-1]] if stops == 2 else [base])]
    history = []
    for _ in range(generations):
        population.sort(key=lambda o: (cost(o), o))
        history.append(cost(population[0]))
        if stops < 3:
            break
        children = [o[:] for o in population[:elitism]]
        while len(children) < population_size:
            a = min(rng.sample(population, tournament_size), key=cost)
            b = min(rng.sample(population, tournament_size), key=cost)
            child = a[:]
            if rng.random() < crossover_rate:    # order crossover (OX)
                i, j = sorted(rng.sample(range(stops + 1), 2))
                kept = a[i:j]
                rest = [s for s in b if s not in kept]
                child = rest[:i] + kept + rest[i:]
            if rng.random() < mutation_rate:     # swap mutation
                i, j = rng.sample(range(stops), 2)
                child[i], child[j] = child[j], child[i]
            if rng.random() < mutation_rate:     # segment reversal (2-opt move)
                i, j = sorted(rng.sample(range(stops + 1), 2))
                child[i:j] = child[i:j][::-1]
            children.append(child)
        population = children
    population.sort(key=lambda o: (cost(o), o))
    best = population[0]
    history.append(cost(best))
    return dict(order=best, cost=cost(best), history=history)
