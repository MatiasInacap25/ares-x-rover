"""Seeded two-dimensional physical terrain; coordinates are (row, column)."""
import numpy as np
from .planet import ASSUMPTION


class World:
    operational_label = ASSUMPTION

    def __init__(self, width=16, height=12, seed=0, difficulty='medium', science_count=5):
        if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (width, height)):
            raise ValueError('Las dimensiones deben ser enteros positivos')
        if difficulty not in ('low', 'medium', 'high'):
            raise ValueError('Dificultad inválida: low, medium o high')
        if not isinstance(science_count, int) or science_count < 0:
            raise ValueError('Cantidad de sitios inválida')
        self.width, self.height, self.seed, self.difficulty = width, height, seed, difficulty
        self.rng = np.random.default_rng(seed)
        self.elevation = self.rng.uniform(0, 3, (height, width))
        self.elevation[0, 0] = 0
        cells = [(r, c) for r in range(height) for c in range(width) if (r, c) != (0, 0)]
        self.rng.shuffle(cells)
        count = int(len(cells) * {'low': .05, 'medium': .12, 'high': .22}[difficulty])
        self.obstacles = set(cells[:count])
        free = cells[count:]
        self.science_sites = set(free[:science_count])
        self.resources = set(free[science_count:science_count + 3])
        self.refuges = {(0, 0)}
        self.cliffs = set()
        self.visited_science = set()

    def in_bounds(self, position):
        try:
            r, c = position
            return isinstance(r, (int, np.integer)) and isinstance(c, (int, np.integer)) and 0 <= r < self.height and 0 <= c < self.width
        except (TypeError, ValueError):
            return False

    def add_obstacle(self, position):
        if not self.in_bounds(position):
            raise ValueError('Obstáculo fuera del mapa')
        self.obstacles.add(tuple(position))

    def traversable(self, position, mode='rover'):
        return self.in_bounds(position) and tuple(position) not in self.obstacles and (mode == 'probe' or tuple(position) not in self.cliffs)

    @property
    def science_progress(self):
        return len(self.visited_science & self.science_sites) / len(self.science_sites) if self.science_sites else 1.0

    def refuge_distance(self, position, mode='rover'):
        """Shortest currently feasible return distance, without promising rescue."""
        from collections import deque
        queue = deque([(tuple(position), 0)])
        seen = {tuple(position)}
        while queue:
            cell, distance = queue.popleft()
            if cell in self.refuges:
                return distance
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                neighbor = (cell[0] + dr, cell[1] + dc)
                if neighbor not in seen and self.traversable(neighbor, mode):
                    seen.add(neighbor)
                    queue.append((neighbor, distance + 1))
        return float('inf')
